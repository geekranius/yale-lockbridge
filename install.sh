#!/usr/bin/env bash
# LockBridge – install / upgrade / uninstall on Raspberry Pi OS (or Debian/Ubuntu)
#
#   sudo ./install.sh                 # install or upgrade (prompts for Cloudflare Access details)
#   sudo ./install.sh --wizard        # install, then run the guided setup
#   sudo ./install.sh --cf-team=myteam --cf-aud=<AUD tag> \
#        --cf-emails=me@mail.com,mom@mail.com --proxy-ip=192.168.1.20 \\
#        --public-url=https://lock.example.com [--lan]
#   sudo ./install.sh --uninstall     # remove the service and app (data stays in /var/lib/lockbridge)
#
# External access goes through YOUR existing cloudflared (on another machine on the network):
# Cloudflare dashboard → tunnel → Public hostname → http://<this Pi's IP>:8080, plus an Access application.
set -euo pipefail

APP_DIR=/opt/lockbridge
DATA_DIR=/var/lib/lockbridge
ENV_FILE=/etc/lockbridge.env
SVC_USER=lockbridge
PORT=8080
CF_TEAM="" CF_AUD="" CF_EMAILS="" PROXY_IP="" LAN_BYPASS="" CF_GIVEN=0
PUBLIC_URL=""
WIZARD=""
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

c_ok() { printf '\033[1;32m✔ %s\033[0m\n' "$*"; }
c_info() { printf '\033[1;34m➜ %s\033[0m\n' "$*"; }
c_warn() { printf '\033[1;33m! %s\033[0m\n' "$*"; }
die() { printf '\033[1;31m✘ %s\033[0m\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Run with sudo: sudo ./install.sh"

for arg in "$@"; do
  case "$arg" in
    --port=*) PORT="${arg#*=}" ;;
    --cf-team=*) CF_TEAM="${arg#*=}"; CF_GIVEN=1 ;;
    --cf-aud=*) CF_AUD="${arg#*=}"; CF_GIVEN=1 ;;
    --cf-emails=*) CF_EMAILS="${arg#*=}"; CF_GIVEN=1 ;;
    --proxy-ip=*) PROXY_IP="${arg#*=}"; CF_GIVEN=1 ;;
    --lan) LAN_BYPASS=1 ;;
    --public-url=*) PUBLIC_URL="${arg#*=}" ;;
    --wizard) WIZARD=1 ;;
    --uninstall)
      c_info "Uninstalling LockBridge…"
      systemctl disable --now lockbridge 2>/dev/null || true
      rm -f /etc/systemd/system/lockbridge.service /usr/local/bin/lockbridge-admin
      systemctl daemon-reload
      rm -rf "$APP_DIR"
      c_ok "Removed. Data (users, lock key, log) was kept in $DATA_DIR, settings in $ENV_FILE."
      exit 0 ;;
    -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
    *) die "Unknown option: $arg" ;;
  esac
done

[[ -f "$SRC_DIR/lockbridge/web.py" ]] || die "Run the script from the project directory (where the lockbridge/ directory is)."

# ---------------------------------------------------------------- system packages
c_info "Installing system packages (Python, BlueZ)…"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip bluez rfkill curl ca-certificates >/dev/null

PYV=$(python3 -c 'import sys; print("%d%02d" % sys.version_info[:2])')
[[ $PYV -ge 311 ]] || die "Python 3.11+ is required (you have $(python3 --version)). Use Raspberry Pi OS Bookworm or Trixie."
c_ok "$(python3 --version)"

# ---------------------------------------------------------------- Bluetooth
c_info "Enabling Bluetooth…"
rfkill unblock bluetooth || true
systemctl enable --now bluetooth >/dev/null 2>&1 || true
sleep 1
if ls /sys/class/bluetooth/hci* >/dev/null 2>&1; then
  c_ok "Bluetooth adapter: $(ls /sys/class/bluetooth | tr '\n' ' ')"
else
  c_warn "Bluetooth adapter not found! On the Pi check /boot/firmware/config.txt (without 'dtoverlay=disable-bt') or plug in a USB Bluetooth adapter."
fi

# ---------------------------------------------------------------- user and files
if ! id "$SVC_USER" >/dev/null 2>&1; then
  useradd --system --home "$DATA_DIR" --shell /usr/sbin/nologin "$SVC_USER"
fi
usermod -aG bluetooth "$SVC_USER"
install -d -m 700 -o "$SVC_USER" -g "$SVC_USER" "$DATA_DIR"
install -d -m 755 "$APP_DIR"

c_info "Copying the app to $APP_DIR…"
rm -rf "$APP_DIR/app.new"
mkdir -p "$APP_DIR/app.new"
cp -r "$SRC_DIR/lockbridge" "$SRC_DIR/requirements.txt" "$APP_DIR/app.new/"
find "$APP_DIR/app.new" -name '__pycache__' -prune -exec rm -rf {} +
rm -rf "$APP_DIR/app"
mv "$APP_DIR/app.new" "$APP_DIR/app"

if [[ ! -x "$APP_DIR/venv/bin/python" ]]; then
  python3 -m venv "$APP_DIR/venv"
fi
c_info "Installing Python dependencies (the first run may take a few minutes)…"
"$APP_DIR/venv/bin/python" -m pip install -q --upgrade pip wheel
"$APP_DIR/venv/bin/python" -m pip install -q -r "$APP_DIR/app/requirements.txt"
c_ok "Dependencies installed"

# ---------------------------------------------------------------- Cloudflare Access settings
# On upgrade the existing values are kept unless new ones are given.
get_env() { [[ -f "$ENV_FILE" ]] && sed -n "s/^$1=//p" "$ENV_FILE" | head -1 || true; }
[[ -n "$CF_TEAM" ]] || CF_TEAM=$(get_env LB_CF_TEAM)
[[ -n "$CF_AUD" ]] || CF_AUD=$(get_env LB_CF_AUD)
[[ -n "$CF_EMAILS" ]] || CF_EMAILS=$(get_env LB_CF_EMAILS)
[[ -n "$PROXY_IP" ]] || PROXY_IP=$(get_env LB_PROXY_IPS)
[[ -n "$LAN_BYPASS" ]] || LAN_BYPASS=$(get_env LB_CF_LAN_BYPASS)
[[ -n "$PUBLIC_URL" ]] || PUBLIC_URL=$(get_env LB_PUBLIC_URL)

if [[ -z "$CF_AUD" && $CF_GIVEN -eq 0 && -t 0 ]]; then
  echo
  c_info "Cloudflare Zero Trust Access – extra verification inside the app itself (recommended)."
  echo "  You'll find the details in Zero Trust → Access → Applications → your application (README, section 2.3)."
  echo "  Leave empty to skip (later just run install.sh again)."
  read -r -p "  Team name (e.g. 'myteam' from myteam.cloudflareaccess.com): " CF_TEAM
  if [[ -n "$CF_TEAM" ]]; then
    read -r -p "  Application Audience (AUD) tag: " CF_AUD
    read -r -p "  Allowed e-mails (comma-separated): " CF_EMAILS
    read -r -p "  IP address of the machine running cloudflared: " PROXY_IP
    read -r -p "  Public HTTPS address for installing the app (e.g. https://lock.example.com): " PUBLIC_URL
    read -r -p "  Allow direct access from the home network without Access (http://IP:$PORT)? [y/N] " ans
    [[ "${ans:-N}" =~ ^[DdYy]$ ]] && LAN_BYPASS=1
  fi
fi
[[ -n "$CF_TEAM" && -z "$CF_AUD" ]] && die "The AUD tag is required together with the team name (--cf-aud=…)."

{
  echo "# LockBridge settings (loaded by systemd). After changes: sudo systemctl restart lockbridge"
  echo "LB_PORT=$PORT"
  echo "LB_CF_TEAM=$CF_TEAM"
  echo "LB_CF_AUD=$CF_AUD"
  echo "LB_CF_EMAILS=$CF_EMAILS"
  echo "LB_PROXY_IPS=$PROXY_IP"
  echo "LB_CF_LAN_BYPASS=${LAN_BYPASS:-0}"
  echo "LB_PUBLIC_URL=$PUBLIC_URL"
} > "$ENV_FILE"
chown root:"$SVC_USER" "$ENV_FILE"
chmod 640 "$ENV_FILE"

if [[ -n "$CF_AUD" ]]; then
  c_ok "Cloudflare Access verification enabled (team: $CF_TEAM, e-mails: ${CF_EMAILS:-anyone Access allows})"
  [[ -n "$PROXY_IP" ]] || c_warn "The cloudflared machine IP is not set – the log will show its address instead of the real one."
else
  c_warn "Cloudflare Access verification is NOT enabled – the app is protected only by password and 2FA."
fi

# ---------------------------------------------------------------- systemd
cp "$SRC_DIR/systemd/lockbridge.service" /etc/systemd/system/lockbridge.service
systemctl daemon-reload
systemctl enable lockbridge >/dev/null 2>&1
systemctl restart lockbridge

# admin helper:  sudo lockbridge-admin users | reset-2fa <user> | reset-password <user>
cat > /usr/local/bin/lockbridge-admin <<EOF
#!/bin/sh
cd $APP_DIR/app && exec sudo -u $SVC_USER env LB_DATA_DIR=$DATA_DIR $APP_DIR/venv/bin/python -m lockbridge "\$@"
EOF
chmod 755 /usr/local/bin/lockbridge-admin

# guided setup helper:  sudo lockbridge-setup
cat > /usr/local/bin/lockbridge-setup <<EOF
#!/bin/sh
cd $APP_DIR/app && exec env LB_DATA_DIR=$DATA_DIR LB_APP_DIR=$APP_DIR $APP_DIR/venv/bin/python -m lockbridge.setup "\$@"
EOF
chmod 755 /usr/local/bin/lockbridge-setup

c_info "Waiting for the service to start…"
for _ in $(seq 1 30); do
  curl -fs "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1 && break
  sleep 1
done
if curl -fs "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1; then
  c_ok "LockBridge is running"
else
  c_warn "The service did not respond. Check: journalctl -u lockbridge -n 50"
fi

IP=$(hostname -I | awk '{print $1}')
echo
c_ok "Installation complete!"
echo
echo "  In the Cloudflare dashboard (your tunnel → Public hostname) add:"
echo "      lock.example.com  →  HTTP  →  $IP:$PORT"
echo "  and an Access application for that hostname with the policy 'Emails: you + mom' (README, section 2.3)."
echo
echo "  This Pi:          http://$IP:$PORT   (give it a fixed IP on your router)"
echo "  Logs:             journalctl -u lockbridge -f"
echo "  Administration:   sudo lockbridge-admin users | reset-2fa <user> | reset-password <user>"
echo "  Guided setup:     sudo lockbridge-setup"
echo "  Settings:         $ENV_FILE   (after changes: sudo systemctl restart lockbridge)"
echo "  Upgrade:          copy the new version and run again: sudo ./install.sh"
echo

# ---------------------------------------------------------------- guided setup
if [[ -z "$WIZARD" && -t 0 ]]; then
  echo
  ans=""
  read -r -p "  Run the guided setup now (Home Assistant, offline key, lock pairing)? [Y/n] " ans || true
  if [[ "${ans:-Y}" =~ ^[YyDd] ]]; then WIZARD=1; fi
fi
if [[ "$WIZARD" == "1" ]]; then
  echo
  c_info "Starting the guided setup…"
  ( cd "$APP_DIR/app" && LB_DATA_DIR="$DATA_DIR" LB_APP_DIR="$APP_DIR" LB_PORT="$PORT" \
      "$APP_DIR/venv/bin/python" -m lockbridge.setup ) || \
    c_warn "The guided setup did not finish. Re-run it with: cd $APP_DIR/app && sudo $APP_DIR/venv/bin/python -m lockbridge.setup"
fi
