"""Basic configuration from environment variables."""

import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("LB_DATA_DIR", "/var/lib/lockbridge"))
HOST = os.environ.get("LB_HOST", "0.0.0.0")
PORT = int(os.environ.get("LB_PORT", "8080"))
# LB_DEMO=1 starts a simulated lock (for trying out the interface without hardware)
DEMO = os.environ.get("LB_DEMO", "0") == "1"
# We trust X-Forwarded-* / Cf-Connecting-Ip only from these addresses: 127.0.0.1 and the machine running
# cloudflared (LB_PROXY_IPS, e.g. "192.168.1.20"; multiple addresses separated by commas)
TRUST_PROXY = os.environ.get("LB_TRUST_PROXY", "1") == "1"
PROXY_IPS = {"127.0.0.1", "::1"} | {ip.strip() for ip in os.environ.get("LB_PROXY_IPS", "").split(",") if ip.strip()}

# Cloudflare Zero Trust Access (see cfaccess.py). Empty = disabled.
CF_TEAM = os.environ.get("LB_CF_TEAM", "")  # e.g. "myteam" or "myteam.cloudflareaccess.com"
CF_AUD = os.environ.get("LB_CF_AUD", "")  # Application Audience (AUD) tag from the Access application
CF_EMAILS = {e.strip().lower() for e in os.environ.get("LB_CF_EMAILS", "").split(",") if e.strip()}
# 1 = direct requests from the home network (private IP addresses) may bypass Access (never from LB_PROXY_IPS)
CF_LAN_BYPASS = os.environ.get("LB_CF_LAN_BYPASS", "0") == "1"
# Public (HTTPS) address of the application, e.g. https://door.yourdomain.com.
# Used to install the PWA on a phone (QR code) – unavailable without HTTPS.
PUBLIC_URL = (os.environ.get("LB_PUBLIC_URL", "") or "").strip().rstrip("/")

STATIC_DIR = Path(__file__).parent / "static"


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(DATA_DIR, 0o700)
    except OSError:
        pass
