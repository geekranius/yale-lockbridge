# Security model

This document describes what LockBridge protects against, what it does not, and how to report a problem.

## What the app protects

LockBridge controls a physical door lock. We assume the lock itself is secure and focus on the network-facing software.

### Access layering

1. **Cloudflare Access** (optional but recommended) – only the e-mail addresses you list can even reach the app. Everyone else sees a login wall.
2. **Password** – `scrypt` (N=2^14, r=8, p=1), 16-byte random salt.
3. **TOTP 2FA** – mandatory for every account, replay-protected (a code cannot be reused within its time step).
4. **In-app JWT verification** – with Access enabled, every request must carry a valid Cloudflare Access JWT: signature (team JWKS), `aud`, `iss`, and the e-mail allow-list are checked. A misconfigured Access policy alone does not let anyone in.
5. **CSRF** – all state-changing requests need the `X-LB: 1` header and a same-origin session cookie (`SameSite=Lax`, `HttpOnly`).
6. **Rate limiting** – 8 failed logins per IP or username trigger a 15-minute block, and the admin is notified.

### The offline key

The lock's offline key is the credential that allows any BLE device to open the lock. It is treated as the most sensitive secret in the system.

- **No API endpoint returns it.** `GET /api/lockcfg` exposes only `has_key: true/false`.
- **It is not in the database.** It lives in `/var/lib/lockbridge/lock.key`, mode `0600`, owned by the service user. The SQLite database is therefore free of the key.
- **It is not in backups.** The backup endpoint exports the database only, so downloaded backups never contain the key.
- **It is not logged.** Error paths and log messages never print it.
- **It is never sent to the browser.** The web UI only ever sends the key *to* the server when you paste it once.

### Host hardening

The systemd unit runs as an unprivileged system user with:

- `ProtectSystem=strict`, `ProtectHome=yes`, `PrivateTmp=yes`
- `NoNewPrivileges=yes`, `ProtectKernelTunables/Modules`, `ProtectControlGroups`
- `RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK AF_BLUETOOTH`
- `UMask=0077` (files created by the service are private)

The service only needs write access to `/var/lib/lockbridge`.

### Web hardening

- Strict `Content-Security-Policy`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`
- HSTS when served over HTTPS
- No third-party scripts, fonts, CDNs or analytics — the whole UI is served from the device
- No inbound ports are opened; remote access only through your own tunnel

## What is *not* protected

Be honest with yourself about these:

- **Full host compromise.** If an attacker gets code execution as the service user (or root), they can read `/var/lib/lockbridge/lock.key`, because the service must decrypt/use it to talk to the lock. No self-hosted software can avoid this. Physical access to the SD card or a root shell equals control of the lock. Protect SSH (keys only, no password login), keep the system updated, and keep the Pi physically inside your home.
- **Stolen phone with an active session.** The session cookie is `HttpOnly` and lasts up to 30 days. Revoke it in *Settings → My account → Sessions*, or use "Log out all devices".
- **Cloudflare account compromise.** If someone controls your Cloudflare account they can change the Access policy. Protect that account with a strong password and hardware 2FA.
- **Yale/August cloud.** The key is fetched from the vendor cloud once. If that account is compromised, the attacker may rotate keys. Use a dedicated owner account where possible and keep your Yale account secure.
- **Bluetooth range.** Anyone within radio range could try to talk to the lock, but the BLE session is encrypted with the offline key. Keep the key secret and the lock firmware updated.
- **Denial of service.** Someone who can reach the Pi can make it busy; they cannot open the door without a valid session.

LockBridge cannot promise "100 % secure" — nothing can. It is designed so that a compromise of the *web layer* does not leak the key, and so that every remote path requires three independent factors.

## Reporting a vulnerability

Open a **private security advisory** on GitHub (Security → Report a vulnerability) instead of a public issue. Please include:

- affected version/commit
- steps to reproduce
- impact (what an attacker can do)

We aim to respond within a few days. Please do not test against other people's installations.
