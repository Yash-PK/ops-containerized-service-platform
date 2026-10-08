"""Create local file secrets under a private directory, never overwrite credentials."""

import os
import secrets
import stat
from pathlib import Path

NAMES = ("owner_password", "app_password", "cache_password")


def generate(root):
    root = Path(root).absolute()
    if root.resolve() != root or not root.is_dir():
        raise ValueError("Canonical project root required")
    runtime = root / ".runtime"
    if runtime.is_symlink():
        raise ValueError("Runtime symlink forbidden")
    runtime.mkdir(mode=0o700, exist_ok=True)
    info = runtime.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError("Runtime must be owned and mode 0700")
    folder = runtime / "secrets"
    if folder.exists() or folder.is_symlink():
        raise ValueError("Secrets already exist; refusing silent credential rotation")
    folder.mkdir(mode=0o700)
    # Compose file-backed secrets preserve source mode. The 0700 parents prevent
    # host access; 0444 permits distinct non-root container UIDs to read their mount.
    for name in NAMES:
        descriptor = os.open(folder / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
        with os.fdopen(descriptor, "w") as handle:
            handle.write(secrets.token_hex(24) + "\n")
            os.fchmod(handle.fileno(), 0o444)
    return folder
