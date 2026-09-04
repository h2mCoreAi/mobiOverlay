"""System-wide (global) hotkey support via a low-level keyboard hook.

Plain Qt shortcuts (QShortcut) only fire while the app itself has focus —
useless for "toggle the overlay while I'm alt-tabbed into the game," which
is the whole point of this feature. The Win32 RegisterHotKey/WM_HOTKEY API
was tried first and reliably failed to fire while Star Citizen had focus —
RegisterHotKey delivers its message through the normal window message
queue, which fullscreen/exclusive-input games can block. ThrottleWatch (a
separate, already-shipping SC overlay by the same author) never has that
problem because it uses the `keyboard` library's low-level global hook
(WH_KEYBOARD_LL via SetWindowsHookEx) instead — that hooks the actual
keyboard input stream below the window message queue, so it isn't affected
by which window Windows currently considers focused. This module ports
that proven approach (see ThrottleWatch's HotkeyState for the original).
"""
import ctypes
import threading

import keyboard
from PySide6.QtCore import QObject, QTimer, Signal

MAPVK_VSC_TO_VK = 1
ctypes.windll.user32.GetAsyncKeyState.restype = ctypes.c_short
ctypes.windll.user32.GetAsyncKeyState.argtypes = [ctypes.c_int]

_vk_name_cache: dict[str, int | None] = {}


def _vk_for_key_name(name: str) -> int | None:
    """Maps a keyboard-library key name (e.g. "ctrl", "f3") to a Windows
    virtual-key code, for the physical-state watchdog below."""
    if name in _vk_name_cache:
        return _vk_name_cache[name]
    vk = None
    try:
        scan_code = keyboard.key_to_scan_codes(name)[0]
        vk = ctypes.windll.user32.MapVirtualKeyW(scan_code, MAPVK_VSC_TO_VK) or None
    except (ValueError, IndexError, OSError):
        vk = None
    _vk_name_cache[name] = vk
    return vk


def _key_is_physically_down(vk: int) -> bool:
    return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)


class HotkeyState:
    """Tracks one global hotkey combo from raw key down/up events fed to it
    by a single shared keyboard.hook(), instead of keyboard.add_hotkey/
    remove_hotkey.

    That higher-level API matches combos against a dict of currently-pressed
    keys shared globally across every hotkey in the process. If a single
    key-up event is ever lost — e.g. a UAC prompt steals focus while a
    modifier is held, which happens easily when alt-tabbing out of a
    fullscreen game — a stray scan code gets stuck "pressed" there forever,
    and the hotkey never matches again until the process restarts. Tracking
    state as plain attributes here, plus the reconcile() watchdog below,
    sidesteps that.
    """

    def __init__(self):
        self.combo: tuple[str, ...] = ()
        self.callback = None
        self.pressed: set[str] = set()
        self.held = False

    def configure(self, hotkey: str, callback):
        if not hotkey:
            return
        self.combo = tuple(p.strip().lower() for p in hotkey.split("+") if p.strip())
        self.callback = callback
        self.pressed.clear()
        self.held = False

    def clear(self):
        self.combo = ()
        self.callback = None
        self.pressed.clear()
        self.held = False

    def handle_event(self, name: str, event_type: str):
        combo = self.combo
        if not combo:
            return
        trigger_key = combo[-1]
        modifiers = combo[:-1]

        if event_type == "down":
            self.pressed.add(name)
            if name != trigger_key or not all(m in self.pressed for m in modifiers):
                return
            if self.held:
                # Windows key-repeat re-fires "down" while the key stays
                # held; ignore repeats.
                return
            self.held = True
            if self.callback is not None:
                self.callback()
        elif event_type == "up":
            self.pressed.discard(name)
            if name == trigger_key or name in modifiers:
                self.held = False

    def reconcile(self):
        """Watchdog: clears stuck state if the OS says the relevant keys
        aren't actually held anymore, self-healing from a key-up event that
        never reached the hook (see class docstring)."""
        if not self.combo or (not self.pressed and not self.held):
            return
        for name in list(self.pressed):
            vk = _vk_for_key_name(name)
            if vk is not None and not _key_is_physically_down(vk):
                self.pressed.discard(name)
        if self.held:
            vk = _vk_for_key_name(self.combo[-1])
            if vk is not None and not _key_is_physically_down(vk):
                self.held = False


class GlobalHotkey(QObject):
    """Owns the one persistent low-level keyboard hook for the app's
    lifetime and dispatches matching key events to a single HotkeyState
    (Stow/Deploy — the only global hotkey mobiOverlay has right now).

    keyboard.hook()'s callback runs on the keyboard library's own dispatch
    thread, never the Qt/GUI thread — emitting a Qt signal from there is
    the standard thread-safe way to marshal back onto the GUI thread
    (Qt auto-queues a cross-thread signal to the receiver's thread), the
    same role ThrottleWatch's `self.root.after(0, ...)` plays for Tk.
    """

    # Emitted from the keyboard-hook thread; Qt auto-queues delivery to
    # whatever thread the connected slot lives on (the GUI thread), which
    # is what makes it safe for the slot to touch Qt widgets at all.
    triggered = Signal()

    def __init__(self):
        super().__init__()
        self._state = HotkeyState()
        self._callback = None
        self.triggered.connect(self._dispatch)

        self._reconcile_timer = QTimer(self)
        self._reconcile_timer.timeout.connect(self._state.reconcile)
        self._reconcile_timer.start(1000)

        try:
            self._hook = keyboard.hook(self._on_key_event, suppress=False)
        except Exception:
            # No admin rights, or the hook install otherwise failed —
            # the hotkey silently won't fire; the Settings UI still works,
            # it just never gets a callback.
            self._hook = None

    def _on_key_event(self, event):
        # Runs on keyboard's dispatch thread. A broad except here matters:
        # keyboard's dispatch loop has no exception handling of its own, so
        # an uncaught error here would silently kill hotkey delivery for
        # the rest of the process's life, not just this one event.
        try:
            name = (event.name or "").lower()
            self._state.handle_event(name, event.event_type)
        except Exception:
            pass

    def _dispatch(self):
        # Runs on the GUI thread (queued via the cross-thread signal
        # emit in HotkeyState.handle_event -> self.triggered.emit below).
        if self._callback is not None:
            self._callback()

    def set_hotkey(self, combo: str, callback) -> bool:
        self._callback = callback
        self._state.configure(combo, self.triggered.emit)
        return True

    def clear(self):
        self._state.clear()
        self._callback = None

    def capture_combo(self, on_captured, on_error=None):
        """Blocks (on a background thread) until the user presses and
        releases a key combo, then reports it back via `on_captured` —
        called on the GUI thread through the same signal-based marshaling
        as the hotkey callback itself. Mirrors ThrottleWatch's
        keyboard.read_hotkey()-in-a-thread capture pattern exactly, since
        that's the one already proven to work reliably here."""
        signal_holder = _CaptureResult()
        signal_holder.captured.connect(on_captured)
        if on_error is not None:
            signal_holder.failed.connect(on_error)

        def worker():
            try:
                combo = keyboard.read_hotkey(suppress=False)
                signal_holder.captured.emit(combo)
            except Exception as exc:
                signal_holder.failed.emit(str(exc))

        threading.Thread(target=worker, daemon=True).start()
        return signal_holder  # caller must keep a reference alive until it fires


class _CaptureResult(QObject):
    captured = Signal(str)
    failed = Signal(str)
