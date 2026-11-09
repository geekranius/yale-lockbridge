"""Alexa – local emulation of a Belkin WeMo switch (no cloud, no skill).

An Echo device on the same LAN discovers a "switch" named e.g. "Front door".
  "Alexa, turn off front door"  → lock
  "Alexa, turn on front door"   → unlock (only if explicitly allowed in settings!)

Note: Alexa does not support Croatian; set the device name in Alexa's language (e.g. English).
For a voice PIN when unlocking, use the Home Assistant route (see README).
"""

import asyncio
import email.utils
import hashlib
import logging
import re
import socket
import struct

from .. import db as dbmod
from ..events import bus

log = logging.getLogger("lockbridge.alexa")

SSDP_ADDR = "239.255.255.250"
SSDP_PORT = 1900
DEFAULTS = {"enabled": False, "name": "Front door", "port": 49915, "allow_unlock": False}


def get_cfg() -> dict:
    c = dict(DEFAULTS)
    c.update((dbmod.db.get("integrations", {}) or {}).get("alexa", {}))
    return c


def local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


SETUP_XML = """<?xml version="1.0"?>
<root xmlns="urn:Belkin:device-1-0">
  <specVersion><major>1</major><minor>0</minor></specVersion>
  <device>
    <deviceType>urn:Belkin:device:controllee:1</deviceType>
    <friendlyName>{name}</friendlyName>
    <manufacturer>Belkin International Inc.</manufacturer>
    <modelName>Socket</modelName>
    <modelNumber>3.1415</modelNumber>
    <modelDescription>Belkin Plugin Socket 1.0</modelDescription>
    <UDN>uuid:Socket-1_0-{serial}</UDN>
    <serialNumber>{serial}</serialNumber>
    <binaryState>0</binaryState>
    <serviceList>
      <service>
        <serviceType>urn:Belkin:service:basicevent:1</serviceType>
        <serviceId>urn:Belkin:serviceId:basicevent1</serviceId>
        <controlURL>/upnp/control/basicevent1</controlURL>
        <eventSubURL>/upnp/event/basicevent1</eventSubURL>
        <SCPDURL>/eventservice.xml</SCPDURL>
      </service>
    </serviceList>
  </device>
</root>"""

EVENTSERVICE_XML = """<?xml version="1.0"?>
<scpd xmlns="urn:Belkin:service-1-0">
  <actionList>
    <action><name>SetBinaryState</name><argumentList><argument><retval/><name>BinaryState</name>
      <relatedStateVariable>BinaryState</relatedStateVariable><direction>in</direction></argument></argumentList></action>
    <action><name>GetBinaryState</name><argumentList><argument><retval/><name>BinaryState</name>
      <relatedStateVariable>BinaryState</relatedStateVariable><direction>out</direction></argument></argumentList></action>
  </actionList>
  <serviceStateTable>
    <stateVariable sendEvents="yes"><name>BinaryState</name><dataType>Boolean</dataType><defaultValue>0</defaultValue></stateVariable>
  </serviceStateTable>
</scpd>"""

SOAP = """<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>
<u:{action}Response xmlns:u="urn:Belkin:service:basicevent:1"><BinaryState>{state}</BinaryState></u:{action}Response>
</s:Body></s:Envelope>"""


class _SSDP(asyncio.DatagramProtocol):
    def __init__(self, emu: "AlexaEmulator"):
        self.emu = emu
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        text = data.decode(errors="ignore")
        if "M-SEARCH" not in text:
            return
        if any(s in text for s in ("urn:Belkin:device:**", "ssdp:all", "upnp:rootdevice")):
            asyncio.get_running_loop().call_later(0.1, self._reply, addr)

    def _reply(self, addr):
        e = self.emu
        msg = (
            "HTTP/1.1 200 OK\r\n"
            "CACHE-CONTROL: max-age=86400\r\n"
            f"DATE: {email.utils.formatdate(usegmt=True)}\r\n"
            "EXT:\r\n"
            f"LOCATION: http://{e.ip}:{e.port}/setup.xml\r\n"
            'OPT: "http://schemas.upnp.org/upnp/1/0/"; ns=01\r\n'
            f"01-NLS: {e.serial}\r\n"
            "SERVER: Unspecified, UPnP/1.0, Unspecified\r\n"
            "ST: urn:Belkin:device:**\r\n"
            f"USN: uuid:Socket-1_0-{e.serial}::urn:Belkin:device:**\r\n"
            "X-User-Agent: redsonic\r\n\r\n"
        )
        try:
            self.transport.sendto(msg.encode(), addr)
        except Exception:  # noqa: BLE001
            pass


class AlexaEmulator:
    def __init__(self):
        self._server = None
        self._ssdp = None
        self.status = "disabled"
        self.ip = ""
        self.port = 0
        self.serial = ""

    def start(self):
        asyncio.create_task(self.restart())

    async def stop(self):
        if self._server:
            self._server.close()
            self._server = None
        if self._ssdp:
            self._ssdp.close()
            self._ssdp = None

    async def restart(self):
        await self.stop()
        cfg = get_cfg()
        if not cfg["enabled"]:
            self.status = "disabled"
            return
        self.ip = local_ip()
        self.port = int(cfg["port"])
        self.serial = hashlib.md5(f"lockbridge-{cfg['name']}".encode()).hexdigest()[:14]
        try:
            self._server = await asyncio.start_server(self._handle, "0.0.0.0", self.port)
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "SO_REUSEPORT"):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            sock.bind(("", SSDP_PORT))
            mreq = struct.pack("4s4s", socket.inet_aton(SSDP_ADDR), socket.inet_aton(self.ip))
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            loop = asyncio.get_running_loop()
            self._ssdp, _ = await loop.create_datagram_endpoint(lambda: _SSDP(self), sock=sock)
            self.status = f"active on {self.ip}:{self.port} – say 'Alexa, discover devices'"
        except Exception as e:  # noqa: BLE001
            self.status = f"error: {e}"
            log.warning("Alexa emulation: %s", e)

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 10)
            lines = head.decode(errors="ignore").split("\r\n")
            method, path = lines[0].split(" ")[:2]
            headers = {l.split(":", 1)[0].lower(): l.split(":", 1)[1].strip() for l in lines[1:] if ":" in l}
            body = b""
            if n := int(headers.get("content-length", "0") or 0):
                body = await asyncio.wait_for(reader.readexactly(n), 10)
            status, ctype, out = await self._route(method, path, headers, body.decode(errors="ignore"))
            data = out.encode()
            writer.write(
                f"HTTP/1.1 {status}\r\nCONTENT-TYPE: {ctype}\r\nCONTENT-LENGTH: {len(data)}\r\n"
                f"DATE: {email.utils.formatdate(usegmt=True)}\r\nSERVER: Unspecified, UPnP/1.0, Unspecified\r\n"
                "X-User-Agent: redsonic\r\nCONNECTION: close\r\n\r\n".encode() + data
            )
            await writer.drain()
        except Exception:  # noqa: BLE001
            pass
        finally:
            writer.close()

    async def _route(self, method, path, headers, body):
        from ..lock import LockError, manager

        cfg = get_cfg()
        if method == "GET" and path.startswith("/setup.xml"):
            return "200 OK", 'text/xml; charset="utf-8"', SETUP_XML.format(name=cfg["name"], serial=self.serial)
        if method == "GET" and path.startswith("/eventservice.xml"):
            return "200 OK", 'text/xml; charset="utf-8"', EVENTSERVICE_XML
        if method == "POST" and path.startswith("/upnp/control/basicevent1"):
            action = headers.get("soapaction", "")
            unlocked = manager.state["lock"] in ("UNLOCKED", "UNLATCHED", "UNLOCKING")
            if "GetBinaryState" in action:
                return "200 OK", 'text/xml; charset="utf-8"', SOAP.format(action="GetBinaryState", state=int(unlocked))
            if "SetBinaryState" in action:
                m = re.search(r"<BinaryState>(\d)</BinaryState>", body)
                want_on = bool(m and m.group(1) == "1")
                if want_on and not cfg["allow_unlock"]:
                    bus.emit("error", "Alexa tried to unlock the door, but unlocking by voice is not allowed.",
                             level="warning", source="Alexa")
                    return "200 OK", 'text/xml; charset="utf-8"', SOAP.format(action="SetBinaryState", state=int(unlocked))
                async def _do():
                    try:
                        await manager.command("unlock" if want_on else "lock", "Alexa", "Alexa (voice)")
                    except LockError:
                        pass  # already logged

                # Alexa expects a fast response, while the BLE command can take a few seconds
                asyncio.create_task(_do())
                return "200 OK", 'text/xml; charset="utf-8"', SOAP.format(action="SetBinaryState", state=int(want_on))
        return "404 Not Found", "text/plain", "not found"


emulator = AlexaEmulator()
