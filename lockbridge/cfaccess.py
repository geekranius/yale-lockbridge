"""Cloudflare Zero Trust Access JWT verification (an extra layer of protection behind a Cloudflare tunnel).

Cloudflare Access adds a signed JWT to every allowed request (the
`Cf-Access-Jwt-Assertion` header, or the `CF_Authorization` cookie). The application checks:
  * the signature (the team's public keys from /cdn-cgi/access/certs),
  * `aud` (Application Audience tag) and `iss` (your team domain),
  * that the e-mail is on the allow list (LB_CF_EMAILS).
This way even a misconfigured Access policy does not let outsiders in.
"""

import asyncio
import ipaddress
import logging
import time

from . import config

log = logging.getLogger("lockbridge.cfaccess")

LOOPBACK = ("127.0.0.1", "::1")


def enabled() -> bool:
    return bool(config.CF_TEAM and config.CF_AUD)


def issuer() -> str:
    t = config.CF_TEAM.strip().rstrip("/")
    if t.startswith("http://") or t.startswith("https://"):
        return t
    if not t.endswith(".cloudflareaccess.com"):
        t += ".cloudflareaccess.com"
    return "https://" + t


class AccessDenied(Exception):
    pass


class Verifier:
    def __init__(self):
        self._jwks = None
        self._cache: dict[str, tuple[dict, float]] = {}

    def _client(self):
        if self._jwks is None:
            from jwt import PyJWKClient

            self._jwks = PyJWKClient(f"{issuer()}/cdn-cgi/access/certs", cache_keys=True, lifespan=3600, timeout=10)
        return self._jwks

    def _verify_sync(self, token: str) -> dict:
        import jwt

        key = self._client().get_signing_key_from_jwt(token).key
        return jwt.decode(
            token, key, algorithms=["RS256"], audience=config.CF_AUD, issuer=issuer(),
            options={"require": ["exp", "iat", "aud", "iss"]}, leeway=30,
        )

    async def verify(self, token: str | None) -> dict:
        if not token:
            raise AccessDenied("missing Cloudflare Access token")
        now = time.time()
        if (hit := self._cache.get(token)) and hit[1] > now:
            return hit[0]
        try:
            claims = await asyncio.to_thread(self._verify_sync, token)
        except Exception as e:  # noqa: BLE001
            raise AccessDenied(f"invalid Cloudflare Access token ({type(e).__name__})") from None
        email = (claims.get("email") or "").lower()
        is_service = bool(claims.get("common_name")) and not email  # Access service token (e.g. Home Assistant)
        if config.CF_EMAILS and not is_service and email not in config.CF_EMAILS:
            raise AccessDenied(f"e-mail {email or '?'} is not on the allow list")
        if len(self._cache) > 500:
            self._cache.clear()
        self._cache[token] = (claims, min(claims["exp"], now + 300))
        return claims


verifier = Verifier()


def lan_bypass_ok(host: str | None, headers) -> bool:
    """Direct requests from the home network (without the tunnel) – only if explicitly allowed (--lan)."""
    if not config.CF_LAN_BYPASS or not host or host in LOOPBACK or host in config.PROXY_IPS:
        return False  # traffic coming through the tunnel (cloudflared) must always carry a valid token
    if headers.get("cf-ray") or headers.get("cf-connecting-ip"):
        return False  # it went through Cloudflare, regardless of which LAN address it came from
    try:
        return ipaddress.ip_address(host).is_private
    except ValueError:
        return False
