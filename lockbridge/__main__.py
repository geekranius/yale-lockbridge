"""Starting and administering from the command line.

  python -m lockbridge                      # start the server
  python -m lockbridge users                # list users
  python -m lockbridge reset-2fa <user>     # reset 2FA (lost phone)
  python -m lockbridge reset-password <user>
"""

import getpass
import logging
import sys


def main() -> None:
    from . import config

    args = sys.argv[1:]
    if not args or args[0] == "run":
        import uvicorn

        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        # proxy_headers disabled: we handle X-Forwarded-* ourselves and only from 127.0.0.1 (see web._from_local_proxy)
        # timeout_graceful_shutdown: otherwise an open SSE (/api/stream) from a browser
        # keeps uvicorn shutting down until systemd kills it (90 s); after 5 s we interrupt.
        uvicorn.run(
            "lockbridge.web:app", host=config.HOST, port=config.PORT, proxy_headers=False,
            log_level="warning", timeout_graceful_shutdown=5,
        )
        return

    from . import db as dbmod
    from . import security

    db = dbmod.init()
    cmd = args[0]
    if cmd == "users":
        for u in db.all("SELECT * FROM users ORDER BY id"):
            print(f"{u['id']:>3}  {u['username']:<20} {u['role']:<6} 2FA={'yes' if u['totp_enabled'] else 'no'}"
                  f" active={'yes' if u['active'] else 'no'}")
    elif cmd in ("reset-2fa", "reset-password") and len(args) == 2:
        u = db.one("SELECT * FROM users WHERE username=?", (args[1],))
        if not u:
            sys.exit(f"User '{args[1]}' does not exist.")
        if cmd == "reset-2fa":
            db.execute("UPDATE users SET totp_secret=?, totp_enabled=0 WHERE id=?", (security.new_totp_secret(), u["id"]))
            print("2FA has been reset – on the next login the user scans a new QR code.")
        else:
            pw = getpass.getpass("New password: ")
            if prob := security.password_problem(pw):
                sys.exit(prob)
            if pw != getpass.getpass("Repeat password: "):
                sys.exit("Passwords do not match.")
            db.execute("UPDATE users SET pw_hash=?, active=1 WHERE id=?", (security.hash_password(pw), u["id"]))
            print("Password changed.")
        security.delete_user_sessions(u["id"])
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
