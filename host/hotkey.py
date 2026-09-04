"""System-wide (global) hotkey support via the Win32 RegisterHotKey API.

Plain Qt shortcuts (QShortcut) only fire while the app itself has focus —
useless for "toggle the overlay while I'm alt-tabbed into the game," which
is the whole point of this feature. RegisterHotKey posts a WM_HOTKEY
message to this process's queue regardless of which window is focused;
a QAbstractNativeEventFilter is how Qt's event loop lets us see it.
"""
import ctypes
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter
from PySide6.QtCore import Qt

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
WM_HOTKEY = 0x0312

_HOTKEY_ID = 1  # only one global hotkey exists right now (Stow/Deploy)

# Qt.Key -> Windows virtual-key code. Covers the keys someone would
# realistically pick for a hotkey; anything else is reported as unsupported
# by the capture field rather than silently registering the wrong key.
_QT_TO_VK: dict[int, int] = {}
for _i in range(Qt.Key_A, Qt.Key_Z + 1):
    _QT_TO_VK[_i] = _i  # Qt.Key_A..Z (0x41-0x5A) are numerically identical to VK_A..Z
for _i in range(Qt.Key_0, Qt.Key_9 + 1):
    _QT_TO_VK[_i] = _i  # same story for the digit keys
_QT_TO_VK.update({
    Qt.Key_F1: 0x70, Qt.Key_F2: 0x71, Qt.Key_F3: 0x72, Qt.Key_F4: 0x73,
    Qt.Key_F5: 0x74, Qt.Key_F6: 0x75, Qt.Key_F7: 0x76, Qt.Key_F8: 0x77,
    Qt.Key_F9: 0x78, Qt.Key_F10: 0x79, Qt.Key_F11: 0x7A, Qt.Key_F12: 0x7B,
    Qt.Key_Insert: 0x2D, Qt.Key_Delete: 0x2E,
    Qt.Key_Home: 0x24, Qt.Key_End: 0x23,
    Qt.Key_PageUp: 0x21, Qt.Key_PageDown: 0x22,
    Qt.Key_Left: 0x25, Qt.Key_Up: 0x26, Qt.Key_Right: 0x27, Qt.Key_Down: 0x28,
    Qt.Key_Space: 0x20, Qt.Key_Tab: 0x09, Qt.Key_Backspace: 0x08,
    Qt.Key_QuoteLeft: 0xC0,  # backtick / tilde key
    Qt.Key_Minus: 0xBD, Qt.Key_Equal: 0xBB,
    Qt.Key_BracketLeft: 0xDB, Qt.Key_BracketRight: 0xDD,
})


def qt_key_to_vk(qt_key: int) -> int | None:
    return _QT_TO_VK.get(qt_key)


def qt_modifiers_to_mod(modifiers) -> int:
    mod = 0
    if modifiers & Qt.ControlModifier:
        mod |= MOD_CONTROL
    if modifiers & Qt.ShiftModifier:
        mod |= MOD_SHIFT
    if modifiers & Qt.AltModifier:
        mod |= MOD_ALT
    if modifiers & Qt.MetaModifier:
        mod |= MOD_WIN
    return mod


class GlobalHotkey(QAbstractNativeEventFilter):
    """Registers one system-wide hotkey and calls a callback when it's
    pressed. Install once via
    `QApplication.instance().installNativeEventFilter(instance)` and keep
    a reference alive for the app's lifetime — Qt doesn't keep filters
    alive on its own.
    """

    def __init__(self):
        super().__init__()
        self._callback = None
        self._registered = False

    def set_hotkey(self, mod: int, vk: int, callback) -> bool:
        """Registers (mod, vk) as the global hotkey. Returns False if the
        combo is already claimed by another application — the caller
        should tell the user, not assume success."""
        self.clear()
        ok = bool(ctypes.windll.user32.RegisterHotKey(None, _HOTKEY_ID, mod, vk))
        if ok:
            self._callback = callback
            self._registered = True
        return ok

    def clear(self):
        if self._registered:
            ctypes.windll.user32.UnregisterHotKey(None, _HOTKEY_ID)
            self._registered = False
        self._callback = None

    def nativeEventFilter(self, eventType, message):
        if eventType == b"windows_generic_MSG" and self._callback is not None:
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam == _HOTKEY_ID:
                self._callback()
        return False, 0
