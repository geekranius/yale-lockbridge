"""Storage for the lock's offline key, kept outside the main database.

Why a separate file:
  * the SQLite database is what the backup endpoint exports – the lock key must
    never end up in a downloadable backup;
  * the key is never written to logs, and no API endpoint returns it;
  * file permissions are 0600 and owned by the service user.

Note: this protects against accidental leaks (backups, logs, exports) and keeps
the key out of the web data model. It is not a defence against an attacker who
already has code execution as the service user – see SECURITY.md.
"""

import os

from . import config

KEY_NAME = "lock.key"


def key_path():
    return config.DATA_DIR / KEY_NAME


def load_key() -> str | None:
    try:
        value = key_path().read_text(encoding="utf-8").strip()
    except (FileNotFoundError, OSError):
        return None
    return value or None


def save_key(key: str) -> None:
    config.ensure_dirs()
    target = key_path()
    tmp = target.with_name(target.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(key.strip().lower() + "\n")
    os.replace(tmp, target)
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass


def clear_key() -> None:
    for path in (key_path(), key_path().with_name(KEY_NAME + ".tmp")):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
