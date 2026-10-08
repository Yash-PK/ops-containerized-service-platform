"""Bound dependency destinations to the canonical checkout; reject symlinks."""

from pathlib import Path


def bounded(root: Path, path: Path) -> Path:
    root = root.absolute()
    path = path.absolute()
    if root.resolve() != root:
        raise ValueError("Project root must be a canonical directory")
    relative = path.relative_to(root)
    current = root
    for part in relative.parts:
        if part in {"..", "."}:
            raise ValueError("Unsafe dependency destination")
        current /= part
        if current.is_symlink():
            raise ValueError("Refusing symlink in dependency destination")
    return path
