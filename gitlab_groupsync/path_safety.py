"""Central lstat-based containment and managed-path validation."""

import errno
import json
import os
import stat
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any


class UnsafePathError(Exception):
    """A path could escape the destination or touch unmanaged content."""


def validate_relative(value: str | Path, *, label: str = "managed path") -> Path:
    """Return a normalized relative path after rejecting portable path hazards."""
    text = str(value)
    if not text or "\x00" in text or "\\" in text:
        raise UnsafePathError(f"unsafe {label}")
    path = PurePosixPath(text)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise UnsafePathError(f"unsafe {label}")
    if any(part == ".git" for part in path.parts):
        raise UnsafePathError(f"unsafe Git-internal {label}")
    return Path(*path.parts)


def assert_no_symlinks(path: Path, *, include_leaf: bool = True) -> None:
    """Reject symlinks in every existing component without following them."""
    absolute = path.absolute()
    current = Path(absolute.anchor)
    parts = absolute.parts[1:] if absolute.anchor else absolute.parts
    for index, part in enumerate(parts):
        current /= part
        if not include_leaf and index == len(parts) - 1:
            break
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            continue
        except OSError as exc:
            if exc.errno == errno.ENOTDIR:
                raise UnsafePathError(
                    "managed path ancestor is not a directory"
                ) from exc
            raise UnsafePathError("could not inspect managed path") from exc
        if stat.S_ISLNK(mode):
            raise UnsafePathError("unsafe managed path has a symlink ancestor")


def contained_path(
    root: Path,
    relative: str | Path,
    *,
    create_parents: bool = False,
    label: str = "managed path",
) -> Path:
    """Construct a destination-contained path and optionally create safe parents."""
    safe = validate_relative(relative, label=label)
    if root.exists() and not root.is_dir():
        raise UnsafePathError("managed root must be a directory")
    assert_no_symlinks(root)
    target = root / safe
    assert_no_symlinks(target)
    try:
        target.relative_to(root)
    except ValueError as exc:  # pragma: no cover - lexical child by construction
        raise UnsafePathError(f"unsafe {label}") from exc
    if create_parents:
        _mkdir_chain(root, safe.parent)
    return target


def _mkdir_chain(root: Path, relative: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    assert_no_symlinks(root)
    current = root
    for part in relative.parts:
        current /= part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            current.mkdir(exist_ok=True)
            mode = current.lstat().st_mode
            if not stat.S_ISDIR(mode):  # pragma: no cover - mkdir race defense
                raise UnsafePathError(
                    "managed path ancestor is not a directory"
                ) from None
            continue
        if not stat.S_ISDIR(mode):  # pragma: no cover - preflight catches ancestors
            raise UnsafePathError("managed path ancestor is not a directory")


def read_marker(path: Path, expected: Mapping[str, Any]) -> bool:
    """Validate a regular, non-symlink JSON marker against stable identity fields."""
    assert_no_symlinks(path)
    try:
        mode = path.lstat().st_mode
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return False
    return (
        stat.S_ISREG(mode)
        and isinstance(value, dict)
        and all(
            value.get(key) == expected_value for key, expected_value in expected.items()
        )
    )


def fsync_directories(paths: Sequence[Path]) -> None:
    """Durably persist directory entry changes where the platform supports it."""
    for path in dict.fromkeys(paths):
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
