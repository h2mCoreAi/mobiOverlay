"""Single-instance guard: prevents running two mobiOverlay processes at once.

A global WH_KEYBOARD_LL hook (the `keyboard` library's mechanism) can block
game input if the owning process hangs or is killed improperly — the hook
stays installed until Windows times it out, and until then every keystroke
waits for a response from a dead/hung process. Running two instances doubles
that risk and makes debugging impossible (which one has the hotkey? which
one's hook is blocking?). This module ensures only one instance runs at a
time, covering both the frozen exe and `python host/main.py`.

Implementation: a lockfile with an exclusive write lock (fcntl on Unix,
msvcrt on Windows). The lock is held for the process's lifetime — closing or
crashing releases it automatically, no cleanup code needed. A second instance
that tries to acquire the same lock fails immediately and can show a dialog.
"""
import sys
from pathlib import Path

from host.paths import app_root

LOCK_FILENAME = ".mobioverlay.lock"


class SingleInstanceError(Exception):
    """Another mobiOverlay instance is already running."""
    pass


class SingleInstance:
    """Context manager that acquires an exclusive lockfile on enter and
    releases it on exit. Raises SingleInstanceError if another instance
    already holds the lock.

    Usage:
        with SingleInstance():
            # only one process reaches here at a time
            main()
    """

    def __init__(self):
        self._lock_path = app_root() / LOCK_FILENAME
        self._lock_file = None

    def __enter__(self):
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._lock_file = open(self._lock_path, "w")
        except OSError as e:
            raise SingleInstanceError(f"Could not open lock file: {e}") from e

        if sys.platform == "win32":
            import msvcrt
            try:
                msvcrt.locking(self._lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                self._lock_file.close()
                self._lock_file = None
                raise SingleInstanceError(
                    "mobiOverlay is already running.\n\n"
                    "Only one instance can run at a time — the global keyboard "
                    "hook used for hotkeys can block game input if two copies "
                    "are competing.\n\n"
                    "Check your system tray or Task Manager."
                )
        else:
            import fcntl
            try:
                fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                self._lock_file.close()
                self._lock_file = None
                raise SingleInstanceError(
                    "mobiOverlay is already running.\n\n"
                    "Only one instance can run at a time."
                )

        self._lock_file.write(str(sys.executable))
        self._lock_file.flush()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._lock_file is not None:
            if sys.platform == "win32":
                import msvcrt
                try:
                    msvcrt.locking(self._lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl
                try:
                    fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
            self._lock_file.close()
            self._lock_file = None
        return False
