"""mobiThrottle: live throttle-axis position bar, ported from ThrottleWatch
(a separate, already-shipping standalone SC overlay by the same author —
D:\\Documents\\Mitch\\Star Citizen\\ThrottleWatch\\throttle_watch.py, Tkinter).

This is a rewrite, not a copy/paste port — see docs/modules/mobi-throttle.md
for the full architecture and what was deliberately dropped (the separate
Settings window, ThrottleWatch's own tray icon, the two-window transparent-
color-key + SetWindowRgn panel-shaping hack that only existed because
Tkinter has no real per-pixel alpha on Windows). Passive HID reads only —
never touches Star Citizen's process memory.

The floating bar (_ThrottleBar) is a standalone always-on-top widget the
card only controls, the same separation Crosshair already established
between its card and its reticle overlay. All configuration lives in the
card; there is no second settings window.
"""
import threading
import time

import pygame  # provided by the pygame-ce package (see requirements.txt)

try:
    import winsound
except ImportError:  # pragma: no cover - Windows-only
    winsound = None

from PySide6.QtCore import Qt, QTimer, QRectF, QPointF, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QSlider, QVBoxLayout,
    QWidget,
)

from host import theme
from host.hotkey import GlobalHotkey
from host.module_base import ModuleBase

AXIS_POLL_HZ = 60
DEADZONE = 0.03
MIN_BAR_WIDTH = 14
MIN_BAR_HEIGHT = 14
TRACK_MARGIN = 10  # px reserved on each side of the track for tick marks
TICK_COUNT = 10  # divisions; TICK_COUNT + 1 marks drawn along the travel axis
KNOB_HALF_THICKNESS = 4
KNOB_POP_HALF_THICKNESS = 11  # briefly wider knob on a home crossing
HOME_FLASH_DURATION = 0.18  # seconds
HOME_TICK_FREQ = 1400
HOME_TICK_MS = 45
RECONNECT_STATUS_UNAVAILABLE = "No device connected"
# Corner radius for the panel background, scaled to the bar's own size
# rather than a fixed px value — this bar is user-resizable over a wide
# range (a thin sliver up past a normal card's width), and a fixed radius
# either overwhelms a thin bar into a full pill or shrinks to invisible on
# a large one.
PANEL_RADIUS_RATIO = 0.22
PANEL_RADIUS_MIN = 8
PANEL_RADIUS_MAX = 40
KNOB_HIGHLIGHT = "#e4e9f5"


def panel_radius_for(w, h):
    return min(PANEL_RADIUS_MAX, max(PANEL_RADIUS_MIN, round(min(w, h) * PANEL_RADIUS_RATIO)))


def dim_color(hex_color, factor=0.55):
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    return "#%02x%02x%02x" % (int(r * factor), int(g * factor), int(b * factor))


def lerp_color(hex_a, hex_b, t):
    a = tuple(int(hex_a.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    b = tuple(int(hex_b.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    r, g, bl = (round(a[i] + (b[i] - a[i]) * t) for i in range(3))
    return "#%02x%02x%02x" % (r, g, bl)


def value_to_color(abs_val, line_color):
    """The bar's own accent color (nominal) at center, gradually shifting to
    the alert amber at full deflection — mirrors MobiGlas's own
    cyan=nominal/amber=alert convention."""
    span = max(1e-9, 1.0 - DEADZONE)
    t = max(0.0, min(1.0, (abs_val - DEADZONE) / span))
    return lerp_color(line_color, theme.ACCENT_AMBER, t)


def play_home_tick(count):
    if winsound is None or count <= 0:
        return

    def beep_sequence():
        for i in range(count):
            winsound.Beep(HOME_TICK_FREQ, HOME_TICK_MS)
            if i < count - 1:
                time.sleep(0.06)

    threading.Thread(target=beep_sequence, daemon=True).start()


def list_joysticks():
    pygame.joystick.quit()
    pygame.joystick.init()
    devices = []
    for i in range(pygame.joystick.get_count()):
        j = pygame.joystick.Joystick(i)
        try:
            guid = j.get_guid()
        except AttributeError:  # pragma: no cover - older pygame without GUIDs
            guid = None
        devices.append({"index": i, "name": j.get_name(), "guid": guid, "numaxes": j.get_numaxes()})
    return devices


def _default_bar_position() -> tuple[int, int]:
    """Same non-primary-monitor default host/main_window.py's own window
    uses (see its _default_launch_position) — this machine's primary
    monitor is the active gaming display, and a floating bar defaulting
    there is exactly the mistake that fix exists to avoid. Only used when
    no position has ever been saved for this bar."""
    screens = QGuiApplication.screens()
    primary = QGuiApplication.primaryScreen()
    others = [s for s in screens if s is not primary]
    target = others[0] if others else primary
    geo = target.geometry()
    return geo.x() + 100, geo.y() + 100


def find_joystick(device_guid):
    """Finds the configured device by saved GUID, or falls back to the
    first connected device with at least one axis — deliberately no
    hardcoded device-name hint (unlike ThrottleWatch's original
    DEVICE_NAME_HINT): mobiOverlay is meant to work on someone else's rig,
    not just this machine's VKB throttle."""
    pygame.joystick.quit()
    pygame.joystick.init()
    fallback = None
    for i in range(pygame.joystick.get_count()):
        j = pygame.joystick.Joystick(i)
        if device_guid:
            try:
                if j.get_guid() == device_guid:
                    return j
            except AttributeError:  # pragma: no cover - older pygame without GUIDs
                continue
        elif fallback is None and j.get_numaxes() > 0:
            fallback = j
    return None if device_guid else fallback


class _ThrottleBar(QWidget):
    """The floating bar itself — a standalone, always-on-top, frameless
    widget the card only controls (position/size/colors), same separation
    Crosshair already uses between its card and its reticle overlay.

    Unlike ThrottleWatch's Tk version, this needs only one window: Qt's
    WA_TranslucentBackground gives real per-pixel alpha compositing, so the
    same paintEvent draws the semi-transparent background panel AND the
    ticks/track/knob — no second window, no transparent-color-key, no
    Win32 SetWindowRgn panel-shaping hack.
    """

    def __init__(self, module: "MobiThrottleModule"):
        super().__init__()
        self._module = module
        self.value = 0.0
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._drag_offset = None
        self._resize_start = None  # (mouse_x, mouse_y, start_w, start_h)
        s = module.settings
        self.setGeometry(s["x"], s["y"], s["width"], s["height"])
        self.set_click_through(s["click_through"])

    def set_click_through(self, enabled: bool):
        """WA_TransparentForMouseEvents makes every mouse event on this
        widget fall straight through to whatever's underneath (the game)
        instead of reaching mousePressEvent/etc. here — same mechanism
        Crosshair's own reticle uses to never intercept an aim click.
        Requested directly by the user: an accidental left-click-drag on
        the bar mid-flight was moving it while playing."""
        self.setAttribute(Qt.WA_TransparentForMouseEvents, enabled)
        # Dragging/resizing is exactly what click-through disables — clear
        # any in-progress gesture so a stale offset doesn't jump the bar
        # the moment click-through is switched off again mid-drag.
        self._drag_offset = None
        self._resize_start = None

    # -- geometry persistence ------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.pos()
        elif event.button() == Qt.RightButton:
            self._resize_start = (event.globalPosition().x(), event.globalPosition().y(),
                                   self.width(), self.height())

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
        elif self._resize_start is not None:
            sx, sy, sw, sh = self._resize_start
            dw = event.globalPosition().x() - sx
            dh = event.globalPosition().y() - sy
            new_w = max(MIN_BAR_WIDTH, round(sw + dw))
            new_h = max(MIN_BAR_HEIGHT, round(sh + dh))
            self.resize(new_w, new_h)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._drag_offset is not None:
            self._drag_offset = None
            self._module.on_bar_moved(self.x(), self.y())
        elif event.button() == Qt.RightButton and self._resize_start is not None:
            self._resize_start = None
            self._module.on_bar_resized(self.width(), self.height())

    # -- drawing --------------------------------------------------------
    def paintEvent(self, event):
        s = self._module.settings
        w, h = self.width(), self.height()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        # See host/main_window.py's paintEvent for why Source composition +
        # an explicit transparent clear matters here: without it, pixels
        # cut off by the rounded corners keep stale backing-store garbage
        # instead of being genuinely see-through.
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.fillRect(self.rect(), Qt.transparent)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)

        bg_color = QColor(s["bg_color"])
        bg_color.setAlphaF(s["bg_opacity"])
        radius = panel_radius_for(w, h)
        bg_path = QPainterPath()
        bg_path.addRoundedRect(QRectF(0, 0, w, h), radius, radius)
        painter.fillPath(bg_path, bg_color)

        painter.setOpacity(s["line_opacity"])
        vertical = s["orientation"] != "horizontal"
        length = h if vertical else w
        thickness = w if vertical else h

        def to_xy(along, cross):
            return (cross, along) if vertical else (along, cross)

        def rect_from_ac(along0, cross0, along1, cross1):
            x0, y0 = to_xy(along0, cross0)
            x1, y1 = to_xy(along1, cross1)
            return QRectF(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))

        line_color = s["line_color"]
        dim = dim_color(line_color)
        cross0, cross1 = TRACK_MARGIN, thickness - TRACK_MARGIN

        # Track outline — rounded with the panel's own radius (not a
        # smaller fixed one) since its ends reach the same along=0/length
        # extremes the panel itself curves at.
        painter.setPen(QPen(QColor(dim), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect_from_ac(0, cross0, length, cross1), radius, radius)

        # Center line (full length, across the middle of the thickness).
        mid_cross = thickness / 2
        x0, y0 = to_xy(0, mid_cross)
        x1, y1 = to_xy(length, mid_cross)
        painter.setPen(QPen(QColor(dim), 2))
        painter.drawLine(QPointF(x0, y0), QPointF(x1, y1))

        # Tick marks — skipped near the two ends when they'd fall inside
        # the panel's own rounded corner, so an outward-reaching tick line
        # doesn't poke straight through where the panel curves away.
        for i in range(TICK_COUNT + 1):
            along = i / TICK_COUNT * length
            if along < radius or along > length - radius:
                continue
            is_major = abs(along - length / 2) < 2
            tick_len = TRACK_MARGIN - 2 if is_major else TRACK_MARGIN - 5
            pen_w = 2 if is_major else 1
            color = line_color if is_major else dim
            painter.setPen(QPen(QColor(color), pen_w))
            ax0, ay0 = to_xy(along, cross0 - tick_len)
            ax1, ay1 = to_xy(along, cross0)
            painter.drawLine(QPointF(ax0, ay0), QPointF(ax1, ay1))
            bx0, by0 = to_xy(along, cross1)
            bx1, by1 = to_xy(along, cross1 + tick_len)
            painter.drawLine(QPointF(bx0, by0), QPointF(bx1, by1))

        # Knob.
        half = KNOB_POP_HALF_THICKNESS if self._module.is_home_flashing() else KNOB_HALF_THICKNESS
        pos_along = (self.value + 1.0) / 2.0 * length
        knob_color = value_to_color(abs(self.value), line_color)
        painter.setPen(QPen(QColor(s["bg_color"]), 1))
        painter.setBrush(QColor(knob_color))
        painter.drawRoundedRect(
            rect_from_ac(pos_along - half, cross0 - 4, pos_along + half, cross1 + 4),
            theme.RADIUS, theme.RADIUS,
        )
        hx0, hy0 = to_xy(pos_along - half + 2, cross0 - 2)
        hx1, hy1 = to_xy(pos_along - half + 2, cross1 + 2)
        painter.setPen(QPen(QColor(KNOB_HIGHLIGHT), 1))
        painter.drawLine(QPointF(hx0, hy0), QPointF(hx1, hy1))
        painter.end()

    def set_value(self, value: float):
        self.value = value
        self.update()

    def apply_geometry(self):
        s = self._module.settings
        self.setGeometry(s["x"], s["y"], s["width"], s["height"])

    def apply_orientation_swap(self):
        s = self._module.settings
        s["width"], s["height"] = s["height"], s["width"]
        self.resize(s["width"], s["height"])


_TOGGLE_BTN_STYLE = f"""
    QPushButton {{
        background: transparent; color: {theme.ACCENT_CYAN};
        border: 1px solid {theme.BORDER_CYAN}; border-radius: {theme.RADIUS}px; padding: 6px 0;
        font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(9)}px; letter-spacing: 1px;
    }}
    QPushButton:hover {{ background: {theme.ACCENT_CYAN_DIM}; }}
"""
_SMALL_BTN_STYLE = f"""
    QPushButton {{
        background: transparent; color: {theme.ACCENT_CYAN};
        border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px; padding: 3px 6px;
        font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(9)}px;
    }}
    QPushButton:hover {{ background: {theme.ACCENT_CYAN_DIM}; }}
"""
_HEADER_LABEL_STYLE = f'color: {theme.ACCENT_CYAN}; font-family: "{theme.FONT_DISPLAY}"; font-weight: 700; font-size: {theme.fpx(10)}px;'
_LABEL_STYLE = f'color: {theme.TEXT_MUTED}; font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(9)}px;'
_STATUS_STYLE = f'color: {theme.TEXT_PRIMARY}; font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(9)}px;'
_COMBO_STYLE = f"""
    QComboBox {{
        background: {theme.BG_VOID}; color: {theme.TEXT_PRIMARY};
        border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px; padding: 3px 18px 3px 6px;
        font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(9)}px;
    }}
    QComboBox::drop-down {{ width: 16px; border: none; }}
"""
_STEPPER_BTN_STYLE = f"""
    QPushButton {{
        background: {theme.BG_VOID}; color: {theme.ACCENT_CYAN};
        border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px;
        font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(13)}px; font-weight: 700;
        padding: 0;
    }}
    QPushButton:hover {{ background: {theme.ACCENT_CYAN_DIM}; }}
    QPushButton:pressed {{ background: {theme.ACCENT_CYAN}; color: {theme.BG_VOID}; }}
"""
_STEPPER_VALUE_STYLE = f"""
    color: {theme.TEXT_PRIMARY}; font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(10)}px;
    background: {theme.BG_VOID}; border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px;
"""
_CHECK_STYLE = f'color: {theme.TEXT_MUTED}; font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(9)}px;'
_HOTKEY_FIELD_STYLE = f"""
    QLineEdit {{
        background: {theme.BG_VOID}; color: {theme.ACCENT_CYAN};
        border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px; padding: 4px 6px;
        font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(9)}px;
    }}
"""


def _section_header(text):
    label = QLabel(text)
    label.setStyleSheet(_HEADER_LABEL_STYLE)
    return label


def _hline():
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setStyleSheet(f"background: {theme.BORDER_FLAT}; max-height: 1px; border: none;")
    return line


class _Stepper(QWidget):
    """A value with big [-]/[+] buttons instead of a QSpinBox's native
    up/down arrows — those arrows are tiny (a handful of px tall,
    typically shorter than half the field height) and hard to hit
    reliably, reported directly by the user after the card shipped with
    QSpinBox/QDoubleSpinBox everywhere. These buttons are full-size,
    themed, and impossible to miss."""

    valueChanged = Signal(float)

    def __init__(self, minimum: float, maximum: float, step: float, value: float, decimals: int = 0):
        super().__init__()
        self._min, self._max, self._step, self._decimals = minimum, maximum, step, decimals
        self._value = value

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.minus_btn = QPushButton("−")
        self.minus_btn.setStyleSheet(_STEPPER_BTN_STYLE)
        self.minus_btn.setFixedSize(26, 24)
        self.minus_btn.clicked.connect(lambda: self._step_by(-1))
        layout.addWidget(self.minus_btn)

        self.value_label = QLabel()
        self.value_label.setStyleSheet(_STEPPER_VALUE_STYLE)
        self.value_label.setAlignment(Qt.AlignCenter)
        self.value_label.setFixedSize(44, 24)
        layout.addWidget(self.value_label)

        self.plus_btn = QPushButton("+")
        self.plus_btn.setStyleSheet(_STEPPER_BTN_STYLE)
        self.plus_btn.setFixedSize(26, 24)
        self.plus_btn.clicked.connect(lambda: self._step_by(1))
        layout.addWidget(self.plus_btn)

        self._render()

    def _step_by(self, direction: int):
        self.setValue(self._value + direction * self._step)

    def _render(self):
        text = f"{self._value:.{self._decimals}f}" if self._decimals else str(int(round(self._value)))
        self.value_label.setText(text)

    def value(self):
        return int(round(self._value)) if self._decimals == 0 else round(self._value, self._decimals)

    def setValue(self, value: float, emit: bool = True):
        clamped = max(self._min, min(self._max, value))
        clamped = round(clamped, self._decimals) if self._decimals else round(clamped)
        if clamped == self._value:
            self._render()
            return
        self._value = clamped
        self._render()
        if emit:
            self.valueChanged.emit(self._value)


class _HotkeyField(QLineEdit):
    """Click, then press a key combo — captured via the module's own
    GlobalHotkey.capture_combo(), same pattern as main_window.py's
    _HotkeyField for the app-wide Stow/Deploy hotkey."""

    def __init__(self, hotkey: GlobalHotkey, initial_display: str, on_applied):
        super().__init__()
        self._hotkey = hotkey
        self._on_applied = on_applied
        self._capturing = False
        self._capture_handles = []  # keeps in-flight capture signal-holders alive
        self.setReadOnly(True)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(_HOTKEY_FIELD_STYLE)
        self.setText(initial_display or "Click to set…")

    def mousePressEvent(self, event):
        if self._capturing:
            return
        self._capturing = True
        self.setText("Press keys...")
        handle = self._hotkey.capture_combo(self._on_captured, self._on_capture_failed)
        self._capture_handles.append(handle)

    def _on_captured(self, combo):
        self._capturing = False
        self.setText(combo)
        self._on_applied(combo)

    def _on_capture_failed(self, _message):
        self._capturing = False
        self.setText("Click to set…")


class MobiThrottleModule(ModuleBase):
    module_id = "mobi_throttle"
    display_name = (
        f'<span style="color:{theme.TEXT_PRIMARY};">mobi</span>'
        f'<span style="color:{theme.ACCENT_CYAN};">Throttle</span>'
    )

    DEFAULTS = {
        "device_guid": None,
        "device_name": None,
        "axis_index": 0,
        "axis_reverse": False,
        "orientation": "vertical",
        "width": 60, "height": 260,
        "bg_color": theme.BG_PANEL, "line_color": theme.ACCENT_CYAN,
        "bg_opacity": 0.85, "line_opacity": 1.0,
        "bar_visible": True,
        "click_through": False,
        "home_chirp_enabled": True, "home_chirp_count": 1, "home_chirp_cooldown": 2.0,
        "position_1": None, "position_2": None,
        "position_1_enabled": True, "position_2_enabled": True,
        "toggle_hotkey": "ctrl+alt+o", "toggle_hotkey_display": "Ctrl+Alt+O",
        "position_hotkey": "ctrl+alt+p", "position_hotkey_display": "Ctrl+Alt+P",
        "position_hold_ms": 0,
        # Reconnect-check cadence — decoupled from the bar's own 60Hz poll
        # timer (see refresh()); much shorter than the host's 300s default
        # so plugging the device back in doesn't take minutes to notice.
        "refresh_interval_seconds": 5,
    }

    def __init__(self, api_client, config):
        super().__init__(api_client, config)
        for key, value in self.DEFAULTS.items():
            self.settings.setdefault(key, value)
        if "x" not in self.settings or "y" not in self.settings:
            self.settings["x"], self.settings["y"] = _default_bar_position()
        self.request_refresh = None  # injected by host after wrapping refresh()

        if not pygame.get_init():
            pygame.init()

        self._device = None
        self._prev_in_home = True
        self._last_chirp_time = 0.0
        self._flash_until = 0.0
        self._position_index = 0
        self._device_list = []

        self._bar = _ThrottleBar(self)
        self._bar.setVisible(self.settings["bar_visible"])

        self._toggle_hotkey = GlobalHotkey()
        self._position_hotkey = GlobalHotkey()
        self._apply_hotkeys()

        self._poll_timer = QTimer()
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start(int(1000 / AXIS_POLL_HZ))

    # -- persistence ------------------------------------------------------
    def _save(self):
        self.config.set_module_settings(self.module_id, self.settings)

    # -- card ---------------------------------------------------------
    def create_card(self, container):
        card = container.add_card(self.module_id, self.display_name)
        layout = card.body_layout

        self.status_label = QLabel(RECONNECT_STATUS_UNAVAILABLE)
        self.status_label.setStyleSheet(_STATUS_STYLE)
        layout.addWidget(self.status_label)

        self.toggle_btn = QPushButton()
        self.toggle_btn.setStyleSheet(_TOGGLE_BTN_STYLE)
        self.toggle_btn.clicked.connect(self._on_toggle_bar_clicked)
        layout.addWidget(self.toggle_btn)
        self._update_toggle_btn_text()

        self.click_through_check = QCheckBox("Click-through (disable drag/resize)")
        self.click_through_check.setStyleSheet(_CHECK_STYLE)
        self.click_through_check.setChecked(self.settings["click_through"])
        self.click_through_check.toggled.connect(self._on_click_through_toggled)
        layout.addWidget(self.click_through_check)

        layout.addWidget(_hline())
        layout.addWidget(_section_header("DEVICE"))

        device_row = QHBoxLayout()
        self.device_combo = QComboBox()
        self.device_combo.setStyleSheet(_COMBO_STYLE)
        device_row.addWidget(self.device_combo, 1)
        refresh_devices_btn = QPushButton("Refresh")
        refresh_devices_btn.setStyleSheet(_SMALL_BTN_STYLE)
        refresh_devices_btn.clicked.connect(self._refresh_device_list)
        device_row.addWidget(refresh_devices_btn)
        layout.addLayout(device_row)

        axis_row = QHBoxLayout()
        axis_row.addWidget(self._label("Axis:"))
        self.axis_spin = _Stepper(0, 15, 1, self.settings["axis_index"])
        axis_row.addWidget(self.axis_spin)
        self.axis_reverse_check = QCheckBox("Reverse")
        self.axis_reverse_check.setStyleSheet(_CHECK_STYLE)
        self.axis_reverse_check.setChecked(self.settings["axis_reverse"])
        axis_row.addWidget(self.axis_reverse_check)
        axis_row.addStretch()
        layout.addLayout(axis_row)

        apply_device_btn = QPushButton("APPLY DEVICE")
        apply_device_btn.setStyleSheet(_TOGGLE_BTN_STYLE)
        apply_device_btn.clicked.connect(self._on_apply_device_clicked)
        layout.addWidget(apply_device_btn)

        layout.addWidget(_hline())
        layout.addWidget(_section_header("APPEARANCE"))

        orientation_row = QHBoxLayout()
        orientation_row.addWidget(self._label("Orientation:"))
        self.orientation_combo = QComboBox()
        self.orientation_combo.setStyleSheet(_COMBO_STYLE)
        self.orientation_combo.addItems(["Vertical", "Horizontal"])
        self.orientation_combo.setCurrentText(
            "Horizontal" if self.settings["orientation"] == "horizontal" else "Vertical")
        self.orientation_combo.currentTextChanged.connect(self._on_orientation_changed)
        orientation_row.addWidget(self.orientation_combo, 1)
        layout.addLayout(orientation_row)

        layout.addWidget(self._label("Background opacity:"))
        self.bg_opacity_slider = self._opacity_slider(self.settings["bg_opacity"], self._on_bg_opacity_changed)
        layout.addWidget(self.bg_opacity_slider)

        layout.addWidget(self._label("Line opacity:"))
        self.line_opacity_slider = self._opacity_slider(self.settings["line_opacity"], self._on_line_opacity_changed)
        layout.addWidget(self.line_opacity_slider)

        colors_row = QHBoxLayout()
        self.line_color_btn = self._color_button(self.settings["line_color"], self._on_pick_line_color)
        colors_row.addWidget(self._label("Line"))
        colors_row.addWidget(self.line_color_btn)
        self.bg_color_btn = self._color_button(self.settings["bg_color"], self._on_pick_bg_color)
        colors_row.addWidget(self._label("Background"))
        colors_row.addWidget(self.bg_color_btn)
        colors_row.addStretch()
        layout.addLayout(colors_row)

        layout.addWidget(_hline())
        layout.addWidget(_section_header("HOTKEYS"))

        toggle_hotkey_row = QHBoxLayout()
        toggle_hotkey_row.addWidget(self._label("Toggle bar:"))
        self.toggle_hotkey_field = _HotkeyField(
            self._toggle_hotkey, self.settings["toggle_hotkey_display"], self._on_toggle_hotkey_applied)
        toggle_hotkey_row.addWidget(self.toggle_hotkey_field, 1)
        layout.addLayout(toggle_hotkey_row)

        pos_hotkey_row = QHBoxLayout()
        pos_hotkey_row.addWidget(self._label("Toggle position:"))
        self.position_hotkey_field = _HotkeyField(
            self._position_hotkey, self.settings["position_hotkey_display"], self._on_position_hotkey_applied)
        pos_hotkey_row.addWidget(self.position_hotkey_field, 1)
        layout.addLayout(pos_hotkey_row)

        hold_row = QHBoxLayout()
        hold_row.addWidget(self._label("Hold time (ms):"))
        self.hold_ms_spin = _Stepper(0, 5000, 50, self.settings["position_hold_ms"])
        self.hold_ms_spin.valueChanged.connect(self._on_hold_ms_changed)
        hold_row.addWidget(self.hold_ms_spin)
        hold_row.addStretch()
        layout.addLayout(hold_row)

        layout.addWidget(_hline())
        layout.addWidget(_section_header("POSITIONS"))

        grid = QGridLayout()
        grid.addWidget(self._label("SCM Mode:"), 0, 0)
        scm_set = QPushButton("Set"); scm_set.setStyleSheet(_SMALL_BTN_STYLE)
        scm_set.clicked.connect(lambda: self._save_position("position_1"))
        grid.addWidget(scm_set, 0, 1)
        scm_go = QPushButton("Go"); scm_go.setStyleSheet(_SMALL_BTN_STYLE)
        scm_go.clicked.connect(lambda: self._go_to_position("position_1", 0))
        grid.addWidget(scm_go, 0, 2)
        self.scm_enabled_check = QCheckBox("Enabled")
        self.scm_enabled_check.setStyleSheet(_CHECK_STYLE)
        self.scm_enabled_check.setChecked(self.settings["position_1_enabled"])
        self.scm_enabled_check.toggled.connect(lambda v: self._on_position_enabled_toggled("position_1_enabled", v))
        grid.addWidget(self.scm_enabled_check, 0, 3)

        grid.addWidget(self._label("NAV Mode:"), 1, 0)
        nav_set = QPushButton("Set"); nav_set.setStyleSheet(_SMALL_BTN_STYLE)
        nav_set.clicked.connect(lambda: self._save_position("position_2"))
        grid.addWidget(nav_set, 1, 1)
        nav_go = QPushButton("Go"); nav_go.setStyleSheet(_SMALL_BTN_STYLE)
        nav_go.clicked.connect(lambda: self._go_to_position("position_2", 1))
        grid.addWidget(nav_go, 1, 2)
        self.nav_enabled_check = QCheckBox("Enabled")
        self.nav_enabled_check.setStyleSheet(_CHECK_STYLE)
        self.nav_enabled_check.setChecked(self.settings["position_2_enabled"])
        self.nav_enabled_check.toggled.connect(lambda v: self._on_position_enabled_toggled("position_2_enabled", v))
        grid.addWidget(self.nav_enabled_check, 1, 3)
        layout.addLayout(grid)

        layout.addWidget(_hline())
        layout.addWidget(_section_header("HOME CHIRP"))

        chirp_row = QHBoxLayout()
        self.chirp_enabled_check = QCheckBox("Enabled")
        self.chirp_enabled_check.setStyleSheet(_CHECK_STYLE)
        self.chirp_enabled_check.setChecked(self.settings["home_chirp_enabled"])
        self.chirp_enabled_check.toggled.connect(self._on_chirp_enabled_toggled)
        chirp_row.addWidget(self.chirp_enabled_check)
        chirp_row.addWidget(self._label("Beeps:"))
        self.chirp_count_spin = _Stepper(1, 10, 1, self.settings["home_chirp_count"])
        self.chirp_count_spin.valueChanged.connect(self._on_chirp_count_changed)
        chirp_row.addWidget(self.chirp_count_spin)
        layout.addLayout(chirp_row)

        cooldown_row = QHBoxLayout()
        cooldown_row.addWidget(self._label("Cooldown (s):"))
        self.cooldown_spin = _Stepper(0.0, 10.0, 0.5, self.settings["home_chirp_cooldown"], decimals=1)
        self.cooldown_spin.valueChanged.connect(self._on_cooldown_changed)
        cooldown_row.addWidget(self.cooldown_spin)
        cooldown_row.addStretch()
        layout.addLayout(cooldown_row)

        self.card = card
        self._refresh_device_list()
        return card

    def _label(self, text):
        label = QLabel(text)
        label.setStyleSheet(_LABEL_STYLE)
        return label

    def _opacity_slider(self, initial, on_changed):
        slider = QSlider(Qt.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(round(initial * 100))
        slider.valueChanged.connect(on_changed)
        return slider

    def _color_button(self, hex_color, on_clicked):
        btn = QPushButton()
        btn.setFixedSize(28, 20)
        btn.setStyleSheet(f"background: {hex_color}; border: 1px solid {theme.BORDER_FLAT}; border-radius: 4px;")
        btn.clicked.connect(on_clicked)
        return btn

    # -- device -----------------------------------------------------
    def _refresh_device_list(self):
        self._device_list = list_joysticks()
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        self.device_combo.addItem("Auto (first detected)")
        selected = 0
        current_guid = self.settings.get("device_guid")
        for i, d in enumerate(self._device_list, start=1):
            self.device_combo.addItem(f"[{d['index']}] {d['name']} ({d['numaxes']} axes)")
            if current_guid and d["guid"] == current_guid:
                selected = i
        self.device_combo.setCurrentIndex(selected)
        self.device_combo.blockSignals(False)

    def _on_apply_device_clicked(self):
        selection = self.device_combo.currentIndex()
        axis = self.axis_spin.value()
        if selection <= 0:
            self.settings["device_guid"] = None
            self.settings["device_name"] = None
        else:
            entry = self._device_list[selection - 1]
            self.settings["device_guid"] = entry["guid"]
            self.settings["device_name"] = entry["name"]
            axis = min(axis, max(0, entry["numaxes"] - 1))
            self.axis_spin.setValue(axis)
        self.settings["axis_index"] = axis
        self.settings["axis_reverse"] = self.axis_reverse_check.isChecked()
        self._save()
        # Force an immediate reconnect against the new selection instead of
        # waiting for the next refresh_interval_seconds tick.
        self._device = None
        if self.request_refresh is not None:
            self.request_refresh()

    def _try_connect(self):
        self._device = find_joystick(self.settings.get("device_guid"))
        if self._device is not None:
            self.settings["device_name"] = self._device.get_name()
            self._save()
            self.status_label.setText(f"Connected: {self.settings['device_name']}")

    # -- polling / drawing ------------------------------------------------
    def _poll(self):
        if self._device is None:
            return
        try:
            pygame.event.pump()
            raw = self._device.get_axis(self.settings["axis_index"])
        except Exception:
            self._device = None
            self.status_label.setText(RECONNECT_STATUS_UNAVAILABLE)
            return
        value = -raw if self.settings["axis_reverse"] else raw
        self._bar.set_value(value)
        self._check_home_chirp(value)

    def _check_home_chirp(self, value):
        now = time.time()
        in_home = abs(value) < DEADZONE
        if in_home and not self._prev_in_home:
            self._flash_until = now + HOME_FLASH_DURATION
            if self.settings["home_chirp_enabled"] and now - self._last_chirp_time >= self.settings["home_chirp_cooldown"]:
                play_home_tick(self.settings["home_chirp_count"])
                self._last_chirp_time = now
        self._prev_in_home = in_home

    def is_home_flashing(self):
        return time.time() < self._flash_until

    # -- bar geometry / visibility -----------------------------------------
    def on_bar_moved(self, x, y):
        self.settings["x"], self.settings["y"] = x, y
        self._save()

    def on_bar_resized(self, w, h):
        self.settings["width"], self.settings["height"] = w, h
        self._save()

    def _update_toggle_btn_text(self):
        self.toggle_btn.setText("HIDE BAR" if self.settings["bar_visible"] else "SHOW BAR")

    def _on_toggle_bar_clicked(self):
        self._set_bar_visible(not self.settings["bar_visible"])

    def _set_bar_visible(self, visible):
        self.settings["bar_visible"] = visible
        self._save()
        self._bar.setVisible(visible)
        self._update_toggle_btn_text()

    def _toggle_bar_visibility(self):
        # Called from the keyboard-hook thread via GlobalHotkey's Qt signal
        # marshaling — safe to touch Qt widgets here, same as the host's
        # own Stow/Deploy hotkey callback.
        self._set_bar_visible(not self.settings["bar_visible"])

    def _on_click_through_toggled(self, enabled):
        # Requested directly by the user: an accidental left-click-drag on
        # the bar mid-flight was moving it while playing. With this on,
        # every mouse event passes straight through to the game — the bar
        # can't be dragged or resized until it's switched back off.
        self.settings["click_through"] = enabled
        self._save()
        self._bar.set_click_through(enabled)

    # -- orientation / appearance -------------------------------------------
    def _on_orientation_changed(self, text):
        new_orientation = "horizontal" if text == "Horizontal" else "vertical"
        if new_orientation == self.settings["orientation"]:
            return
        self.settings["orientation"] = new_orientation
        self._bar.apply_orientation_swap()
        self._save()

    def _on_bg_opacity_changed(self, value):
        self.settings["bg_opacity"] = value / 100
        self._save()
        self._bar.update()

    def _on_line_opacity_changed(self, value):
        self.settings["line_opacity"] = value / 100
        self._save()
        self._bar.update()

    def _on_pick_line_color(self):
        color = QColorDialog.getColor(QColor(self.settings["line_color"]), self.card, "Line color")
        if color.isValid():
            self.settings["line_color"] = color.name()
            self.line_color_btn.setStyleSheet(
                f"background: {color.name()}; border: 1px solid {theme.BORDER_FLAT}; border-radius: 4px;")
            self._save()
            self._bar.update()

    def _on_pick_bg_color(self):
        color = QColorDialog.getColor(QColor(self.settings["bg_color"]), self.card, "Background color")
        if color.isValid():
            self.settings["bg_color"] = color.name()
            self.bg_color_btn.setStyleSheet(
                f"background: {color.name()}; border: 1px solid {theme.BORDER_FLAT}; border-radius: 4px;")
            self._save()
            self._bar.update()

    # -- hotkeys ------------------------------------------------------
    def _apply_hotkeys(self):
        self._toggle_hotkey.set_hotkey(self.settings["toggle_hotkey"], self._toggle_hotkey_triggered)
        self._position_hotkey.set_hotkey(self.settings["position_hotkey"], self._position_hotkey_triggered)

    def _toggle_hotkey_triggered(self):
        self._toggle_bar_visibility()

    def _position_hotkey_triggered(self):
        self._toggle_position()

    def _on_toggle_hotkey_applied(self, combo):
        self.settings["toggle_hotkey"] = combo
        self.settings["toggle_hotkey_display"] = combo
        self._toggle_hotkey.set_hotkey(combo, self._toggle_hotkey_triggered)
        self._save()

    def _on_position_hotkey_applied(self, combo):
        self.settings["position_hotkey"] = combo
        self.settings["position_hotkey_display"] = combo
        self._position_hotkey.set_hotkey(combo, self._position_hotkey_triggered)
        self._save()

    def _on_hold_ms_changed(self, value):
        # GlobalHotkey doesn't support hold-to-trigger itself (the app-wide
        # Stow/Deploy hotkey never needed it) — held here and honored by
        # _toggle_position's own delay via a QTimer.singleShot instead of
        # extending the shared primitive for one caller.
        # int(): _Stepper.valueChanged is declared Signal(float), so Qt
        # coerces even a whole-number Python int to float on the way
        # through — cast back for a step-size setting that should stay int.
        self.settings["position_hold_ms"] = int(value)
        self._save()

    # -- positions ------------------------------------------------------
    def _save_position(self, key):
        self.settings[key] = {"x": self._bar.x(), "y": self._bar.y()}
        self._save()

    def _go_to_position(self, key, index):
        pos = self.settings.get(key)
        if pos is None:
            return
        self._bar.move(pos["x"], pos["y"])
        self.settings["x"], self.settings["y"] = pos["x"], pos["y"]
        self._save()
        self._position_index = index

    def _toggle_position(self):
        hold_ms = self.settings.get("position_hold_ms", 0)
        if hold_ms > 0:
            QTimer.singleShot(hold_ms, self._toggle_position_now)
        else:
            self._toggle_position_now()

    def _toggle_position_now(self):
        target_index = 1 - self._position_index
        key = "position_1" if target_index == 0 else "position_2"
        enabled_key = "position_1_enabled" if target_index == 0 else "position_2_enabled"
        if not self.settings.get(enabled_key, True):
            return  # the other position is disabled — nothing to toggle to
        self._go_to_position(key, target_index)

    def _on_position_enabled_toggled(self, key, value):
        other_key = "position_2_enabled" if key == "position_1_enabled" else "position_1_enabled"
        other_check = self.nav_enabled_check if key == "position_1_enabled" else self.scm_enabled_check
        if not value and not self.settings.get(other_key, True):
            # At least one position must always stay enabled.
            other_check.setChecked(True)
            self.settings[other_key] = True
        self.settings[key] = value
        self._save()

    # -- home chirp ------------------------------------------------------
    def _on_chirp_enabled_toggled(self, value):
        self.settings["home_chirp_enabled"] = value
        self._save()

    def _on_chirp_count_changed(self, value):
        # See _on_hold_ms_changed's comment — Signal(float) coerces int to
        # float in transit; cast back since this is a whole beep count.
        self.settings["home_chirp_count"] = int(value)
        self._save()

    def _on_cooldown_changed(self, value):
        self.settings["home_chirp_cooldown"] = round(value, 1)
        self._save()

    # -- module contract --------------------------------------------------
    def refresh(self):
        """Reconnect check only — the bar's own 60Hz poll timer (see
        __init__) drives the actual axis reads, decoupled from the host's
        refresh cycle. Raising here (no device found) puts this card into
        the host's normal error state with a Retry button, same as any
        other module's failed refresh."""
        if self._device is None:
            self._try_connect()
        if self._device is None:
            hint = self.settings.get("device_name") or "any joystick"
            raise RuntimeError(f"No device found ({hint}). Connect it, then Apply Device or Retry.")

    def shutdown(self):
        """Releases the two OS-level global keyboard hooks this module
        owns — required before a Relaunch spawns a new process, same
        reasoning as host/main_window.py's own Stow/Deploy hotkey (see
        ModuleBase.shutdown's docstring)."""
        self._poll_timer.stop()
        self._toggle_hotkey.shutdown()
        self._position_hotkey.shutdown()


MODULE_CLASS = MobiThrottleModule
