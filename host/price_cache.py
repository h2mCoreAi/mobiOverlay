"""Small persistent key/value cache for fetched UEX data, backed by SQLite.

Used so a bulk price download (Commodity Prices' RETRIEVE DATA, ~20-30 s of
requests) survives an app restart instead of being thrown away: the module
restores the last result at launch and shows how old it is. The cache never
decides what is fresh — callers get the original fetch time back and apply
their own limits, so a stale entry is never silently presented as current.

One short-lived connection per call, so any thread may use it. A file
SQLite can't open is moved aside (host/fileio.quarantine_corrupt) and
recreated empty rather than failing every later call.
"""
import json
import logging
import sqlite3
import time
from pathlib import Path

from host.fileio import quarantine_corrupt
from host.paths import app_root

logger = logging.getLogger("mobioverlay.price_cache")

CACHE_FILENAME = "price_cache.sqlite3"


class PriceCache:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else app_root() / CACHE_FILENAME

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5)
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS cache ("
                "key TEXT PRIMARY KEY, fetched_at REAL NOT NULL, payload TEXT NOT NULL)"
            )
        except Exception:
            conn.close()
            raise
        return conn

    def _run(self, fn):
        """Run `fn(conn)`, recovering once from an unreadable database file."""
        for attempt in (1, 2):
            try:
                conn = self._connect()
            except sqlite3.DatabaseError:
                if attempt == 2 or not self.path.exists():
                    raise
                quarantine_corrupt(self.path)
                continue
            try:
                with conn:
                    return fn(conn)
            except sqlite3.DatabaseError:
                conn.close()
                if attempt == 2 or not self.path.exists():
                    raise
                quarantine_corrupt(self.path)
            finally:
                conn.close()

    def load(self, key: str):
        """Return `(fetched_at_epoch_seconds, payload)` or None if there is no
        entry, or the cache can't be read."""
        try:
            row = self._run(lambda c: c.execute(
                "SELECT fetched_at, payload FROM cache WHERE key = ?", (key,)).fetchone())
            if row is None:
                return None
            return row[0], json.loads(row[1])
        except (sqlite3.Error, ValueError, OSError):
            logger.warning("price cache: could not read %r", key, exc_info=True)
            return None

    def save(self, key: str, payload, fetched_at: float | None = None) -> bool:
        """Store `payload` (anything JSON-serializable). Returns False if it
        could not be written; the app carries on without a cache."""
        try:
            text = json.dumps(payload)
            self._run(lambda c: c.execute(
                "INSERT OR REPLACE INTO cache (key, fetched_at, payload) VALUES (?, ?, ?)",
                (key, fetched_at if fetched_at is not None else time.time(), text)))
            return True
        except (sqlite3.Error, TypeError, ValueError, OSError):
            logger.warning("price cache: could not write %r", key, exc_info=True)
            return False
