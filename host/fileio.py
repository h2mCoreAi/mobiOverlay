"""Crash-safe file helpers for the app's persistent JSON files (config,
notes, location cache).

A plain `open(path, "w")` truncates the file before writing — if the
process dies mid-write (crash, power loss, Relaunch's os._exit), the file
is left empty or half-written, the next launch can't parse it, and the
first save after that silently replaces the user's data with defaults.
`atomic_write_text` writes to a temp file in the same folder and swaps it
in with os.replace (atomic on NTFS), so the real file is always either
the old version or the new one, never a partial one.
"""
import logging
import os
import tempfile
import time
from pathlib import Path

logger = logging.getLogger("mobioverlay.fileio")


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    """Replace `path`'s contents with `text` atomically. Raises OSError on
    failure, leaving the existing file untouched."""
    path = Path(path)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        # Retried briefly: on Windows, an antivirus/indexer/sync client
        # holding the destination open makes os.replace fail with a
        # transient PermissionError.
        for attempt in range(5):
            try:
                os.replace(tmp_name, path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05 * (attempt + 1))
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def quarantine_corrupt(path: Path) -> Path | None:
    """Move an unreadable data file aside (e.g. `config.json` ->
    `config.json.corrupt-20261003-142501`) instead of letting the next save
    overwrite it, so the user's data can still be recovered by hand.
    Returns the new path, or None if the move itself failed."""
    path = Path(path)
    target = path.with_name(f"{path.name}.corrupt-{time.strftime('%Y%m%d-%H%M%S')}")
    try:
        os.replace(path, target)
    except OSError:
        logger.warning("Could not move unreadable %s aside", path, exc_info=True)
        return None
    logger.warning("%s was unreadable — moved aside to %s", path.name, target.name)
    return target
