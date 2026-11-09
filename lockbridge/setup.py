"""Guided setup wizard for LockBridge.

Runs a sequence of steps, each of which is safe to repeat:

  1. system checks (OS, Python, Bluetooth adapter)
  2. locate Home Assistant on the LAN, or optionally install HA Container here
  3. make sure the Yale integration is configured (OAuth flow)
  4. obtain the lock's offline key from the Yale cloud (no manual key handling)
  5. scan for the lock over Bluetooth and select it
  6. write the configuration and (re)start the service

Usage (on the Pi, after ./install.sh, or from a source checkout):

    sudo /opt/lockbridge/venv/bin/python -m lockbridge.setup
    sudo ... -m lockbridge.setup --ha-url http://192.168.1.10:8123 --ha-token ...
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

APP_DIR = os.environ.get("LB_APP_DIR", "/opt/lockbridge")
DATA_DIR = os.environ.get("LB_DATA_DIR", "/var/lib/lockbridge")


# --------------------------------------------------------------------------- UI helpers
def c(text: str, color: str = "") -> str:
    codes = {"g": "32", "b": "34", "y": "33", "r": "31", "dim": "2"}
    code = codes.get(color)
    return f"\033[{code}m{text}\033[0m" if code and sys.stdout.isatty() else text


def step(n: int, title: str) -> None:
    print(f"\n{c(f'[{n}/6]', 'b')} {c(title, 'b')}")


def ok(text: str) -> None:
    print(f"  {c('OK', 'g')} {text}")


def warn(text: str) -> None:
    print(f"  {c('!', 'y')} {text}")


def fail(text: str) -> None:
    print(f"  {c('x', 'r')} {text}")


def info(text: str) -> None:
    print(f"  {c('-', 'dim')} {text}")


def ask(question: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"  {question}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(130)
    return answer or default


def ask_yes(question: str, default: bool = False) -> bool:
    suffix = " [Y/n]" if default else " [y/N]"
    try:
        answer = input(f"  {question}{suffix}: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(130)
    if not answer:
        return default
    return answer in ("y", "yes", "d", "da")


def sh(cmd: list[str], check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


# --------------------------------------------------------------------------- 1. system
def bluetooth_adapters() -> list[str]:
    try:
        return sorted(a for a in os.listdir("/sys/class/bluetooth") if a.startswith("hci"))
    except OSError:
        return []


def check_system() -> bool:
    step(1, "System check")
    good = True

    with open("/proc/device-tree/model", "rb") as fh:
        model = fh.read().replace(b"\x00", b"").decode(errors="replace")
    ok(f"Hardware: {model}")

    with open("/etc/os-release", encoding="utf-8") as fh:
        os_name = next((ln.split("=", 1)[1].strip('"') for ln in fh if ln.startswith("PRETTY_NAME=")), "Linux")
    ok(f"OS: {os_name}")

    if sys.version_info < (3, 11):
        fail(f"Python 3.11+ required (found {sys.version.split()[0]})")
        good = False
    else:
        ok(f"Python {sys.version.split()[0]}")

    adapters = bluetooth_adapters()
    if adapters:
        ok(f"Bluetooth adapter: {', '.join(adapters)}")
    else:
        fail("No Bluetooth adapter (hciX) found")
        info("Run: sudo rfkill unblock bluetooth && sudo systemctl restart bluetooth")
        good = False

    if shutil.disk_usage(DATA_DIR if os.path.isdir(DATA_DIR) else "/").free < 200 * 1024 * 1024:
        warn("Less than 200 MB free disk space")

    if os.geteuid() != 0:
        warn("Not running as root - writing the configuration may fail. Use sudo.")
    return good


# --------------------------------------------------------------------------- 2. HA
def http_json(url: str, token: str | None = None, data: dict | None = None,
              method: str | None = None, timeout: float = 10) -> tuple[int, dict | list | str]:
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method or ("POST" if body else "GET"))
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if body:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode(errors="replace")
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw
    except urllib.error.HTTPError as err:
        raw = err.read().decode(errors="replace")
        try:
            return err.code, json.loads(raw)
        except json.JSONDecodeError:
            return err.code, raw
    except (urllib.error.URLError, TimeoutError, OSError) as err:
        return 0, str(err)


def local_subnet_hosts() -> list[str]:
    """Best-effort /24 host list of the default-route interface."""
    try:
        out = sh(["ip", "-4", "route", "show", "default"]).stdout
        match = re.search(r"via (\d+\.\d+\.\d+)\.\d+ .* dev (\S+)", out)
        if not match:
            return []
        prefix, dev = match.group(1), match.group(2)
        out = sh(["ip", "-4", "-o", "addr", "show", dev]).stdout
        # keep only addresses inside the same /24
        return [f"{prefix}.{i}" for i in range(1, 255)]
    except Exception:  # noqa: BLE001
        return []


async def _probe(host: str, port: int, timeout: float) -> bool:
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass
        return True
    except Exception:  # noqa: BLE001
        return False


async def _scan_8123(hosts: list[str]) -> list[str]:
    results = await asyncio.gather(*(_probe(h, 8123, 0.7) for h in hosts))
    return [h for h, found in zip(hosts, results) if found]


def discover_ha() -> list[str]:
    found: list[str] = []
    # 1) mDNS hostnames commonly used by Home Assistant
    for name in ("homeassistant.local", "homeassistant", "hassio.local"):
        try:
            ip = socket.gethostbyname(name)
            if ip not in found:
                found.append(ip)
        except OSError:
            pass
    # 2) quick port scan of the local /24
    hosts = local_subnet_hosts()
    if hosts:
        found += [h for h in asyncio.run(_scan_8123(hosts)) if h not in found]
    # 3) verify that it really looks like Home Assistant
    verified = []
    for host in found:
        status, body = http_json(f"http://{host}:8123/api/", timeout=5)
        text = body if isinstance(body, str) else json.dumps(body)
        if status == 401 or "API running" in text:
            verified.append(host)
    return verified


def find_ha(args) -> str | None:
    step(2, "Home Assistant")
    if args.ha_url:
        base = args.ha_url.rstrip("/")
        ok(f"Using {base}")
        return base

    info("Looking for Home Assistant on the local network...")
    found = discover_ha()
    if found:
        for host in found:
            ok(f"Found Home Assistant at http://{host}:8123")
        if len(found) == 1:
            return f"http://{found[0]}:8123"
        choice = ask("Which one should I use?", f"http://{found[0]}:8123")
        return choice.rstrip("/")

    warn("No Home Assistant found on this network.")
    print("""
  Home Assistant is needed once, to authorise access to your Yale account and
  download the lock's offline key. You have these options:

    1) Install Home Assistant Container on this Raspberry Pi (Docker, ~1 GB RAM)
    2) I have Home Assistant somewhere else -> enter its address
    3) I already have the offline key -> enter it manually
    4) Skip - configure later in the web UI (Settings -> Lock)
""")
    choice = ask("Choose 1-4", "1")
    if choice == "2":
        return ask("Home Assistant URL", "http://homeassistant.local:8123").rstrip("/")
    if choice == "3":
        return "manual"
    if choice == "4":
        return None
    return install_ha_container()


def install_ha_container() -> str | None:
    info("Installing Docker and Home Assistant Container on this machine.")
    warn("This uses about 1 GB of RAM and downloads ~1 GB. Do not use this on a 1 GB board.")
    if not ask_yes("Continue?"):
        return None

    if not shutil.which("docker"):
        if shutil.which("apt-get"):
            sh(["apt-get", "update", "-qq"])
            sh(["apt-get", "install", "-y", "-qq", "docker.io"], check=False)
        else:
            fail("Docker is not installed and apt-get is not available.")
            return None
    if not shutil.which("docker"):
        fail("Docker installation failed.")
        return None

    sh(["docker", "rm", "-f", "homeassistant"], check=False)
    code = sh([
        "docker", "run", "-d", "--name", "homeassistant", "--restart", "unless-stopped",
        "--network", "host", "-v", "/opt/homeassistant:/config",
        "-v", "/etc/localtime:/etc/localtime:ro", "--privileged",
        "ghcr.io/home-assistant/home-assistant:stable",
    ], check=False)
    if code.returncode != 0:
        fail("Could not start the Home Assistant container.")
        info(code.stderr.strip()[:400])
        return None
    ok("Home Assistant Container started (config in /opt/homeassistant)")
    info("Waiting for it to come up...")
    for _ in range(60):
        status, body = http_json("http://127.0.0.1:8123/api/", timeout=2)
        if status == 401 or "API running" in str(body):
            ok("Home Assistant is running at http://127.0.0.1:8123")
            print("""
  Open http://<this-pi-ip>:8123 in a browser and finish the onboarding
  (create an account). Then re-run this wizard.
""")
            return None
        time.sleep(2)
    warn("Home Assistant did not respond yet - finish onboarding and re-run the wizard.")
    return None


# --------------------------------------------------------------------------- 3. token
def read_ha_storage(args, ha_base: str) -> str | None:
    """Return the raw contents of core.config_entries from the HA host."""
    candidates = [args.ha_storage] if args.ha_storage else []
    if os.path.exists("/opt/homeassistant/.storage/core.config_entries"):
        candidates.append("/opt/homeassistant/.storage/core.config_entries")
    if os.path.exists("/config/.storage/core.config_entries"):
        candidates.append("/config/.storage/core.config_entries")
    for path in candidates:
        if path and os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as fh:
                    ok(f"Read Home Assistant storage: {path}")
                    return fh.read()
            except OSError as err:
                warn(f"Cannot read {path}: {err}")

    if args.ha_ssh:
        ok(f"Reading Home Assistant storage over SSH ({args.ha_ssh})")
        proc = sh(["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new",
                   args.ha_ssh, "cat /config/.storage/core.config_entries"])
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout
        warn(f"SSH read failed: {proc.stderr.strip()[:200]}")

    print("""
  The offline key is stored by Home Assistant in
      /config/.storage/core.config_entries
  This machine cannot read that file directly. Paste its full contents below
  (Settings -> Add-ons -> File editor, or Terminal & SSH), or leave it empty
  to enter the key manually.
""")
    text = ask("Path to the file, or paste JSON (empty = manual key)", "")
    if not text:
        return None
    if os.path.exists(text):
        with open(text, encoding="utf-8") as fh:
            return fh.read()
    return text


def token_from_storage(raw: str | None) -> tuple[str | None, str]:
    """Return (access_token, brand) from Home Assistant's config entries."""
    if not raw:
        return None, "yale_global"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None, "yale_global"
    entries = data.get("data", {}).get("entries", []) if isinstance(data, dict) else []
    brands = {"yale": "yale_global", "august": "august"}
    for entry in entries:
        domain = entry.get("domain")
        if domain not in brands:
            continue
        token = (entry.get("data") or {}).get("token") or {}
        access = token.get("access_token")
        expires = token.get("expires_at") or 0
        if access and expires > time.time() - 60:
            return access, brands[domain]
        if access:
            warn("The cloud token in Home Assistant has expired.")
            info("Open Home Assistant once (it refreshes the token) and re-run the wizard.")
    return None, "yale_global"


def ensure_cloud_integration(base: str, token: str, args) -> bool:
    status, entries = http_json(f"{base}/api/config/config_entries/entry", token)
    if status == 401:
        fail("Home Assistant rejected the token. Create a new long-lived token "
             "(Profile -> Security -> Long-lived access tokens).")
        return False
    if status != 200 or not isinstance(entries, list):
        fail(f"Could not list Home Assistant integrations (HTTP {status}).")
        return False
    if any(e.get("domain") in ("yale", "august") for e in entries):
        ok("Cloud integration is configured in Home Assistant")
        return True

    warn("The Yale/August cloud integration is not configured yet.")
    if not ask_yes("Start the cloud login now?", True):
        return False

    handler = "yale"
    if not args.non_interactive:
        handler = ask("Which cloud? (yale = Yale Home/Access, august = August)", "yale").lower()
        handler = handler if handler in ("yale", "august") else "yale"
    status, flow = http_json(f"{base}/api/config/config_entries/flow", token,
                             {"handler": handler}, method="POST")
    if status not in (200, 201) or not isinstance(flow, dict):
        fail(f"Could not start the Yale flow (HTTP {status}): {flow}")
        return False
    flow_id = flow.get("flow_id")
    url = flow.get("url")
    print(f"""
  Open this address in a browser and sign in with the Yale Home account that
  owns the lock:

    {c(url or '(no url returned)', 'b')}

  After the login completes, this wizard continues automatically.
""")
    for _ in range(120):  # up to ~10 minutes
        status, state = http_json(f"{base}/api/config/config_entries/flow/{flow_id}", token)
        if isinstance(state, dict) and state.get("type") == "abort":
            if state.get("reason") == "already_configured":
                ok("Yale integration configured")
                return True
            fail(f"Yale login was aborted: {state.get('reason')}")
            return False
        if isinstance(state, dict) and state.get("type") == "create_entry":
            ok("Yale integration configured")
            return True
        time.sleep(5)
    fail("Timed out waiting for the Yale login.")
    return False


# --------------------------------------------------------------------------- 4. key
def fetch_locks(access_token: str, brand: str = "yale_global") -> list[dict]:
    """Ask the vendor cloud for locks and their offline keys.

    The brand decides which API is used (Yale Home / Yale Access / August), so we
    try the one implied by the Home Assistant integration first, then the others.
    """
    from yalexs.api_async import ApiAsync
    from yalexs.const import Brand

    async def run_with(brand_name: str) -> list[dict]:
        import aiohttp

        async with aiohttp.ClientSession() as session:
            api = ApiAsync(session, timeout=25, brand=Brand(brand_name))
            locks = []
            for item in await api.async_get_operable_locks(access_token):
                detail = await api.async_get_lock_detail(access_token, item.device_id)
                locks.append({
                    "name": getattr(detail, "device_name", None) or getattr(item, "device_name", "Lock"),
                    "address": (getattr(detail, "mac_address", "") or "").upper(),
                    "serial": getattr(detail, "serial_number", None),
                    "model": getattr(detail, "model", None),
                    "key": getattr(detail, "offline_key", None),
                    "slot": getattr(detail, "offline_slot", None),
                })
            return locks

    order = [brand] + [b for b in ("yale_global", "yale_access", "august") if b != brand]
    last_error = None
    for name in order:
        try:
            locks = asyncio.run(run_with(name))
        except Exception as err:  # noqa: BLE001
            last_error = err
            continue
        if locks:
            return locks
    if last_error:
        fail(f"Could not read locks from the cloud: {last_error}")
    return []


# --------------------------------------------------------------------------- 5. BLE
async def _ble_scan(seconds: float = 12) -> dict[str, dict]:
    from bleak import BleakScanner
    from yalexs_ble.const import COMMAND_SERVICE_UUID, YALE_MFR_IDS

    yale_ids = set(YALE_MFR_IDS)
    found: dict[str, dict] = {}

    def callback(device, adv):
        mfr = set(adv.manufacturer_data)
        uuids = [u.lower() for u in adv.service_uuids]
        is_yale = bool(mfr & yale_ids) or (COMMAND_SERVICE_UUID or "").lower() in uuids
        found[device.address.upper()] = {
            "address": device.address.upper(),
            "name": adv.local_name or device.name or "",
            "rssi": adv.rssi,
            "yale": is_yale,
        }

    async with BleakScanner(detection_callback=callback, scanning_mode="active"):
        await asyncio.sleep(seconds)
    return found


def choose_lock(locks: list[dict], seen: dict[str, dict]) -> dict | None:
    if not locks:
        return None
    for lock in locks:
        adv = seen.get(lock["address"])
        lock["rssi"] = adv["rssi"] if adv else None
        lock["present"] = bool(adv)
    locks.sort(key=lambda l: (not l["present"], -(l.get("rssi") or -999)))

    print("  Locks on your Yale account:")
    for i, lock in enumerate(locks, 1):
        signal = f"{lock['rssi']} dBm" if lock["present"] else "not in Bluetooth range"
        key_state = "key available" if lock["key"] else "NO KEY in cloud"
        print(f"    {i}) {lock['name']}  {lock['address']}  {signal}  ({key_state})")

    if len(locks) == 1:
        return locks[0]
    index = ask("Which lock?", "1")
    try:
        return locks[int(index) - 1]
    except (ValueError, IndexError):
        return locks[0]


# --------------------------------------------------------------------------- 6. save
def write_config(lock: dict, args) -> bool:
    from . import db as dbmod
    from . import secret

    cfg = dict(dbmod.init().get("lock", {}) or {})
    cfg.update({
        "address": lock["address"],
        "slot": int(lock["slot"]),
        "local_name": lock.get("name") or "",
        "adapter": args.adapter or "",
        "always_connected": bool(args.always_connected),
    })
    cfg.pop("key", None)
    dbmod.db.set("lock", cfg)
    secret.save_key(lock["key"])
    hand_over()
    ok(f"Lock configured: {lock['name']} ({lock['address']}), key slot {lock['slot']}")
    return True


def hand_over() -> None:
    """If the wizard runs as root, give the data files back to the service user."""
    if os.geteuid() != 0:
        return
    try:
        import pwd

        user = pwd.getpwnam("lockbridge")
    except KeyError:
        return
    try:
        names = os.listdir(DATA_DIR)
    except OSError:
        return
    for name in names:
        path = os.path.join(DATA_DIR, name)
        try:
            os.chown(path, user.pw_uid, user.pw_gid)
        except OSError:
            pass


def restart_service() -> None:
    if shutil.which("systemctl"):
        res = sh(["systemctl", "restart", "lockbridge"])
        if res.returncode == 0:
            ok("Service restarted")
        else:
            warn("Could not restart the service (is it installed?)")


def configured(lock: dict) -> dict:
    return {k: v for k, v in lock.items() if k in ("name", "address", "slot", "model", "serial", "present", "rssi")}


# --------------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="lockbridge-setup", description="Guided LockBridge setup")
    parser.add_argument("--ha-url", help="Home Assistant URL, e.g. http://192.168.1.10:8123")
    parser.add_argument("--ha-token", help="Home Assistant long-lived access token")
    parser.add_argument("--ha-storage", help="Path to core.config_entries (local HA install)")
    parser.add_argument("--ha-ssh", help="user@host[:port] with access to /config")
    parser.add_argument("--manual-key", help="Offline key (32 hex chars) if you already have it")
    parser.add_argument("--slot", type=int, default=1, help="Key slot (default 1)")
    parser.add_argument("--adapter", default="", help="Bluetooth adapter, e.g. hci0")
    parser.add_argument("--always-connected", action="store_true", help="Keep the BLE link open")
    parser.add_argument("--non-interactive", action="store_true", help="Never prompt (CI/smoke tests)")
    parser.add_argument("--skip-system-check", action="store_true")
    args = parser.parse_args(argv)

    print(c("\nLockBridge setup\n================", "b"))

    if not args.skip_system_check and not check_system():
        fail("Fix the problems above and run the wizard again.")
        sys.exit(1)

    # manual key shortcut
    if args.manual_key:
        address = ask("Bluetooth address of the lock (AA:BB:CC:DD:EE:FF)", "")
        write_config({"name": "Yale lock", "address": address.upper(), "slot": args.slot,
                      "key": args.manual_key.strip().lower()}, args)
        restart_service()
        return

    base = find_ha(args)
    if base is None:
        warn("Skipped Home Assistant - configure the lock later in the web UI.")
        return
    if base == "manual":
        key = ask("Offline key (32 hex characters)")
        address = ask("Bluetooth address of the lock (AA:BB:CC:DD:EE:FF)")
        write_config({"name": "Yale lock", "address": address.upper(), "slot": args.slot,
                      "key": key.strip().lower()}, args)
        restart_service()
        return

    step(3, "Home Assistant access")
    token = args.ha_token or os.environ.get("LB_HA_TOKEN")
    if not token:
        if not args.non_interactive:
            token = getpass.getpass("  Home Assistant long-lived access token (input hidden): ").strip()
    if not token:
        fail("A Home Assistant token is required.")
        sys.exit(1)
    status, config = http_json(f"{base}/api/config", token)
    if status != 200:
        fail(f"Home Assistant rejected the token (HTTP {status}).")
        sys.exit(1)
    ok(f"Connected to Home Assistant {config.get('version', '')}")

    ensure_cloud_integration(base, token, args)

    step(4, "Offline key")
    raw = read_ha_storage(args, base)
    access, brand = token_from_storage(raw)
    if access:
        ok("Found the cloud access token in Home Assistant storage")
    locks = fetch_locks(access, brand) if access else []
    if not locks:
        warn("Could not obtain the key automatically.")
        if args.non_interactive:
            sys.exit(2)
        key = ask("Offline key (32 hex characters, empty to abort)")
        if not key:
            fail("Aborted.")
            sys.exit(2)
        address = ask("Bluetooth address of the lock (AA:BB:CC:DD:EE:FF)")
        write_config({"name": "Yale lock", "address": address.upper(), "slot": args.slot,
                      "key": key.strip().lower()}, args)
        restart_service()
        return

    step(5, "Bluetooth")
    info("Scanning for the lock (12 s)...")
    seen = asyncio.run(_ble_scan(12))
    lock = choose_lock(locks, seen)
    if not lock or not lock.get("key"):
        fail("No usable lock/key found.")
        sys.exit(2)

    step(6, "Saving")
    write_config(lock, args)
    restart_service()
    info("Open the web UI and check the lock state. If it is unreachable, move "
         "the Pi closer or plug in a USB Bluetooth adapter.")


if __name__ == "__main__":
    main()
