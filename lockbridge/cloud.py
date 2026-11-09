"""Retrieving the lock's offline key.

1) Import from Home Assistant (recommended for Yale Home – the Yale Global cloud requires OAuth via HA).
2) E-mail/password login for Yale Access / August accounts (legacy backend).
3) Manual entry of the key and slot.
"""

import json
import re
import uuid

import aiohttp

from . import config
from . import db as dbmod

HEX32 = re.compile(r"^[0-9a-fA-F]{32}$")


def validate_key(key: str, slot) -> tuple[str, int]:
    key = (key or "").strip().replace(" ", "")
    if not HEX32.match(key):
        raise ValueError("The key must be exactly 32 hexadecimal characters.")
    try:
        slot = int(slot)
    except (TypeError, ValueError):
        raise ValueError("The slot must be a number.") from None
    if not 0 <= slot <= 255:
        raise ValueError("The slot must be between 0 and 255.")
    return key.lower(), slot


def parse_ha_config_entries(text: str) -> list[dict]:
    """Extract yalexs_ble records from /config/.storage/core.config_entries."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}") from None
    entries = data.get("data", {}).get("entries", []) if isinstance(data, dict) else data
    found = []
    for e in entries or []:
        if not isinstance(e, dict) or e.get("domain") not in ("yalexs_ble", "yale_ble"):
            continue
        d = e.get("data", {})
        if d.get("key") is None:
            continue
        found.append(
            {
                "name": e.get("title") or d.get("local_name") or "Yale lock",
                "address": (d.get("address") or "").upper(),
                "local_name": d.get("local_name") or "",
                "key": d.get("key"),
                "slot": d.get("slot"),
            }
        )
    if not found:
        raise ValueError("The file contains no 'yalexs_ble' (Yale Access Bluetooth) entry with a key.")
    return found


class CloudLogin:
    """Sign in to the Yale Access / August cloud (temporarily, only to retrieve the key)."""

    def __init__(self, brand: str, email: str, password: str):
        from yalexs.const import Brand

        self.brand = Brand(brand)
        self.email = email
        self.password = password
        self.session: aiohttp.ClientSession | None = None
        self.api = None
        self.auth = None
        self.authentication = None

    async def _setup(self):
        from yalexs.api_async import ApiAsync
        from yalexs.authenticator_async import AuthenticatorAsync

        self.session = aiohttp.ClientSession()
        self.api = ApiAsync(self.session, timeout=20, brand=self.brand)
        install_id = dbmod.db.get("cloud_install_id") or str(uuid.uuid4())
        dbmod.db.set("cloud_install_id", install_id)
        self.auth = AuthenticatorAsync(
            self.api, "email", self.email, self.password, install_id=install_id,
            access_token_cache_file=str(config.DATA_DIR / "cloud_token.json"),
        )
        await self.auth.async_setup_authentication()

    async def login(self) -> str:
        from yalexs.authenticator_common import AuthenticationState

        await self._setup()
        if self.api.brand_config.require_oauth:
            raise ValueError(
                "This account (Yale Home / Yale Global) requires OAuth login via Home Assistant. "
                "Use the 'Import from Home Assistant' option."
            )
        self.authentication = await self.auth.async_authenticate()
        if self.authentication.state == AuthenticationState.BAD_PASSWORD:
            raise ValueError("Incorrect e-mail or password.")
        if self.authentication.state == AuthenticationState.REQUIRES_VALIDATION:
            await self.auth.async_send_verification_code()
            return "need_code"
        return "ok"

    async def verify(self, code: str) -> None:
        from yalexs.authenticator_common import ValidationResult

        res = await self.auth.async_validate_verification_code(code.strip())
        if res != ValidationResult.VALIDATED:
            raise ValueError("Invalid verification code.")
        self.authentication = await self.auth.async_authenticate()

    async def locks(self) -> list[dict]:
        token = self.authentication.access_token
        out = []
        for lk in await self.api.async_get_operable_locks(token):
            det = await self.api.async_get_lock_detail(token, lk.device_id)
            out.append(
                {
                    "name": getattr(det, "device_name", None) or lk.device_name,
                    "address": (getattr(det, "mac_address", None) or "").upper(),
                    "serial": getattr(det, "serial_number", None),
                    "key": det.offline_key,
                    "slot": det.offline_slot,
                    "model": getattr(det, "model", None),
                }
            )
        return out

    async def close(self):
        if self.session:
            await self.session.close()
        try:
            (config.DATA_DIR / "cloud_token.json").unlink()
        except FileNotFoundError:
            pass
