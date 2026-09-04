"""Always-on-top, frameless, draggable overlay window. Houses the
CardContainer, the tray for stowed (hidden) cards, and Settings.
"""
import subprocess

from PySide6.QtCore import Qt, QPoint, QTimer, QKeyCombination
from PySide6.QtGui import QGuiApplication, QKeySequence, QColor, QPainter
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSlider, QSizeGrip, QSizePolicy, QLineEdit
)

from host import theme
from host import hotkey as hotkey_mod
from host.card_container import CardContainer
from host.config import Config
from host.paths import app_root, relaunch_command

def _build_stylesheet() -> str:
    # A function, not a module-level constant: theme.fpx() must read
    # theme.FONT_SCALE at call time. This module is imported (and a
    # module-level string would be frozen) before main.py has a chance to
    # set the scale from config.
    return f"""
QWidget#titleBar {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #0f1a1d, stop:1 #0a1214);
    border: 1px solid {theme.BORDER_CYAN};
}}
QLabel#wordmark {{
    font-family: "{theme.FONT_DISPLAY}";
    font-weight: 800;
    font-size: {theme.fpx(14)}px;
    letter-spacing: 3px;
}}
QLabel#cardTitle {{
    color: {theme.TEXT_PRIMARY};
    font-family: "{theme.FONT_DISPLAY}";
    font-weight: 700;
    font-size: {theme.fpx(11)}px;
    letter-spacing: 2px;
}}
QPushButton#cardIconBtn {{
    background: transparent;
    color: {theme.TEXT_MUTED};
    border: none;
    font-size: {theme.fpx(11)}px;
}}
QPushButton#cardIconBtn:hover {{
    color: {theme.ACCENT_CYAN};
}}
QPushButton#retryBtn {{
    background: transparent;
    color: {theme.ACCENT_AMBER};
    border: 1px solid {theme.BORDER_AMBER};
    font-family: "{theme.FONT_MONO}";
    font-size: {theme.fpx(10)}px;
    letter-spacing: 2px;
    padding: 5px 0;
}}
QPushButton#retryBtn:hover {{
    background: {theme.ACCENT_AMBER_DIM};
}}
QLabel#errorMessage {{
    color: {theme.TEXT_PRIMARY};
    font-family: "{theme.FONT_MONO}";
    font-size: {theme.fpx(11)}px;
}}
QWidget#titleBtn {{
    background: transparent;
    color: {theme.TEXT_MUTED};
    border: none;
}}
QWidget#titleBtn:hover {{
    color: {theme.ACCENT_CYAN};
}}
"""


def _panel_header_style() -> str:
    return f"""
    color: {theme.TEXT_MUTED}; font-family: "{theme.FONT_DISPLAY}";
    font-weight: 700; font-size: {theme.fpx(10)}px; letter-spacing: 2px;
    padding: 9px 12px; border-bottom: 1px solid {theme.BORDER_FLAT};
"""


def _default_launch_position() -> tuple[int, int]:
    """Pick a non-primary monitor to open on when there's no saved position.
    On this dev machine the primary monitor is the active gaming display —
    default there is exactly what a screenshot-testing loop should avoid.
    Falls back to the primary screen if only one monitor exists.
    """
    screens = QGuiApplication.screens()
    primary = QGuiApplication.primaryScreen()
    others = [s for s in screens if s is not primary]
    target = others[0] if others else primary
    geo = target.geometry()
    return geo.x() + 100, geo.y() + 100


class _TrayRow(QWidget):
    """One stowed card's row in the tray panel — click anywhere to deploy it."""

    def __init__(self, card_id: str, title: str, on_deploy):
        super().__init__()
        self._card_id = card_id
        self._on_deploy = on_deploy
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(f"""
            _TrayRow {{ background: transparent; }}
            _TrayRow:hover {{ background: {theme.ACCENT_CYAN_DIM}; }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)

        label = QLabel(title)
        label.setStyleSheet(f'color: {theme.TEXT_PRIMARY}; font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(10)}px;')
        layout.addWidget(label)
        layout.addStretch()

        deploy = QLabel("DEPLOY")
        deploy.setStyleSheet(f'color: {theme.ACCENT_CYAN}; font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(9)}px; letter-spacing: 1px;')
        layout.addWidget(deploy)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._on_deploy(self._card_id)


class _TrayPanel(QWidget):
    """Slide-down panel listing stowed cards, styled like a MobiGlas app
    drawer rather than a native OS dropdown menu. Closes automatically on
    an outside click (Qt.Popup)."""

    def __init__(self, main_window: "MainWindow"):
        super().__init__(main_window, Qt.Popup)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            _TrayPanel {{ background: {theme.BG_PANEL}; border: 1px solid {theme.BORDER_CYAN}; }}
        """)
        self._win = main_window
        self.setFixedWidth(210)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QLabel("STOWED MODULES")
        header.setStyleSheet(_panel_header_style())
        layout.addWidget(header)

        stowed = main_window.card_container.stowed_cards()
        if not stowed:
            empty = QLabel("NOTHING STOWED")
            empty.setStyleSheet(f"""
                color: {theme.TEXT_DIM}; font-family: "{theme.FONT_MONO}";
                font-size: {theme.fpx(10)}px; padding: 16px 12px;
            """)
            layout.addWidget(empty)
        else:
            for card_id, title in stowed:
                layout.addWidget(_TrayRow(card_id, title, self._deploy))

    def _deploy(self, card_id: str):
        self._win.card_container.deploy_card(card_id)
        self.close()


class _SettingsRow(QWidget):
    """One labeled control row in the Settings panel: a title, an optional
    one-line description underneath, and the control itself."""

    def __init__(self, title: str, description: str = ""):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        title_label = QLabel(title)
        title_label.setStyleSheet(f"""
            color: {theme.TEXT_PRIMARY}; font-family: "{theme.FONT_DISPLAY}";
            font-weight: 700; font-size: {theme.fpx(10)}px; letter-spacing: 1px;
        """)
        layout.addWidget(title_label)

        if description:
            desc_label = QLabel(description)
            desc_label.setWordWrap(True)
            desc_label.setStyleSheet(f"""
                color: {theme.TEXT_DIM}; font-family: "{theme.FONT_MONO}";
                font-size: {theme.fpx(9)}px;
            """)
            layout.addWidget(desc_label)

        self.control_row = QHBoxLayout()
        self.control_row.setSpacing(8)
        layout.addLayout(self.control_row)


class _HotkeyField(QLineEdit):
    """Click, then press a key combo to record it as the global Stow/Deploy
    hotkey — works even while another app (the game) has focus, since it's
    a real OS-level hotkey (host/hotkey.py), not a Qt shortcut.

    Must include at least one modifier (Ctrl/Alt/Shift/Win): a bare key
    would hijack that key system-wide, including while playing. Escape
    cancels without changing anything.
    """

    def __init__(self, main_window: "MainWindow"):
        super().__init__()
        self._win = main_window
        self.setReadOnly(True)
        self.setAlignment(Qt.AlignCenter)
        self._listening = False
        self._show_current()

    def _show_current(self):
        display = self._win.config.data["ui"].get("hotkey_display") or ""
        self.setText(display if display else "Click to set…")

    def _flash(self, message: str):
        self.setText(message)
        QTimer.singleShot(1600, self._show_current)

    def mousePressEvent(self, event):
        self._listening = True
        self.setText("Press a key combo… (Esc cancels)")

    def keyPressEvent(self, event):
        if not self._listening:
            return
        key = event.key()
        if key == Qt.Key_Escape:
            self._listening = False
            self._show_current()
            return
        if key in (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta, Qt.Key_unknown):
            return  # a bare modifier isn't a complete combo yet — keep listening

        self._listening = False
        mod = hotkey_mod.qt_modifiers_to_mod(event.modifiers())
        vk = hotkey_mod.qt_key_to_vk(key)

        # Bare letters/digits/space/etc. would hijack normal typing if
        # registered without a modifier — but function keys and navigation
        # keys (F1-F12, Insert, arrows, ...) never produce a character
        # during normal typing, so those are fine standalone (this is also
        # what let the user's F3-alone case through instead of being
        # wrongly rejected).
        if mod == 0 and hotkey_mod.key_requires_modifier(key):
            self._flash("Needs Ctrl / Alt / Shift / Win too")
            return
        if vk is None:
            self._flash("Unsupported key — try another")
            return

        # PySide6/Qt6 uses new-style enums: event.modifiers() returns a
        # Qt.KeyboardModifier flag object that int() can't coerce directly
        # (raises TypeError) — QKeyCombination is the Qt6-correct way to
        # pair a modifier flag with a key for QKeySequence. QKeyCombination
        # also insists on an actual Qt.Key enum member, not the plain int
        # event.key() returns — wrap it or this throws too.
        display = QKeySequence(QKeyCombination(event.modifiers(), Qt.Key(key))).toString()
        if self._win.set_stow_hotkey(mod, vk, display):
            self._show_current()
        else:
            err = self._win.last_hotkey_error()
            self._flash(f"Already in use (Win32 error {err})" if err else "Could not register hotkey")


class _SettingsPanel(QWidget):
    """Window Opacity, Card Opacity, and Text Size — a themed panel next to
    the Tray, same Qt.Popup pattern (closes on an outside click)."""

    def __init__(self, main_window: "MainWindow"):
        super().__init__(main_window, Qt.Popup)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            _SettingsPanel {{ background: {theme.BG_PANEL}; border: 1px solid {theme.BORDER_CYAN}; }}
        """)
        self._win = main_window
        self.setFixedWidth(230)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QLabel("SETTINGS")
        header.setStyleSheet(_panel_header_style())
        layout.addWidget(header)

        # -- Window Opacity --
        window_row = _SettingsRow(
            "WINDOW OPACITY", "How see-through the empty space around your cards is."
        )
        window_slider = QSlider(Qt.Horizontal)
        window_slider.setRange(40, 100)
        window_slider.setValue(int(main_window.config.data["ui"]["window_opacity"] * 100))
        window_slider.valueChanged.connect(main_window.set_window_opacity_percent)
        window_row.control_row.addWidget(window_slider)
        layout.addWidget(window_row)

        # -- Card Opacity --
        card_row = _SettingsRow(
            "CARD OPACITY",
            "How see-through each card's background is, on its own — "
            "separate from the window above.",
        )
        card_slider = QSlider(Qt.Horizontal)
        card_slider.setRange(20, 100)
        card_slider.setValue(int(main_window.config.data["ui"]["card_opacity"] * 100))
        card_slider.valueChanged.connect(main_window.set_card_opacity_percent)
        card_row.control_row.addWidget(card_slider)
        layout.addWidget(card_row)

        # -- Text Size --
        text_row = _SettingsRow("TEXT SIZE", "Applies after a relaunch — use the button below.")
        current_scale = main_window.config.data["ui"]["font_scale"]
        for name, scale in theme.FONT_SCALE_OPTIONS.items():
            btn = QPushButton(name.upper())
            btn.setCheckable(True)
            btn.setChecked(abs(scale - current_scale) < 0.001)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; color: {theme.TEXT_MUTED};
                    border: 1px solid {theme.BORDER_FLAT}; padding: 4px 6px;
                    font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(9)}px;
                }}
                QPushButton:checked {{
                    color: {theme.ACCENT_CYAN}; border: 1px solid {theme.BORDER_CYAN};
                }}
            """)
            btn.clicked.connect(lambda checked, s=scale: main_window.set_font_scale(s))
            text_row.control_row.addWidget(btn)
        layout.addWidget(text_row)

        # -- Relaunch --
        relaunch_row = QWidget()
        relaunch_layout = QHBoxLayout(relaunch_row)
        relaunch_layout.setContentsMargins(12, 4, 12, 12)
        relaunch_btn = QPushButton("RELAUNCH")
        relaunch_btn.setToolTip("Closes and reopens mobiOverlay — applies Text Size and anything else that needs a fresh start.")
        relaunch_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {theme.ACCENT_CYAN};
                border: 1px solid {theme.BORDER_CYAN}; padding: 6px 0;
                font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(10)}px; letter-spacing: 1px;
            }}
            QPushButton:hover {{ background: {theme.ACCENT_CYAN_DIM}; }}
        """)
        relaunch_btn.clicked.connect(main_window.relaunch)
        relaunch_layout.addWidget(relaunch_btn)
        layout.addWidget(relaunch_row)

        # -- Stow/Deploy hotkey --
        hotkey_row = _SettingsRow(
            "STOW/DEPLOY HOTKEY",
            "Toggles the whole overlay, even while the game has focus.",
        )
        hotkey_field = _HotkeyField(main_window)
        hotkey_field.setStyleSheet(f"""
            QLineEdit {{
                background: {theme.BG_VOID}; color: {theme.ACCENT_CYAN};
                border: 1px solid {theme.BORDER_FLAT}; padding: 4px 6px;
                font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(10)}px;
            }}
        """)
        hotkey_row.control_row.addWidget(hotkey_field, 1)
        clear_btn = QPushButton("CLEAR")
        clear_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {theme.TEXT_MUTED};
                border: 1px solid {theme.BORDER_FLAT}; padding: 4px 8px;
                font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(9)}px;
            }}
        """)
        clear_btn.clicked.connect(lambda: (main_window.clear_stow_hotkey(), hotkey_field._show_current()))
        hotkey_row.control_row.addWidget(clear_btn)
        layout.addWidget(hotkey_row)


class _TitleBar(QWidget):
    def __init__(self, main_window: "MainWindow"):
        super().__init__()
        self.setObjectName("titleBar")
        self._win = main_window
        self._drag_offset: QPoint | None = None
        self._press_pos = QPoint()
        self.setFixedHeight(38)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 12, 0)

        wordmark = QLabel(
            f'<span style="color:{theme.TEXT_PRIMARY};">MOBI</span>'
            f'<span style="color:{theme.ACCENT_CYAN};">OVERLAY</span>'
        )
        wordmark.setObjectName("wordmark")
        # Rich-text QLabels default to Qt::LinksAccessibleByMouse, which
        # intercepts mouse events before they reach the title bar's own
        # mousePressEvent/mouseMoveEvent — that ate every drag attempt on
        # the pill (the wordmark is the whole clickable surface there).
        wordmark.setTextInteractionFlags(Qt.NoTextInteraction)
        layout.addWidget(wordmark)

        self.byline_label = QLabel(
            f'<span style="color:{theme.TEXT_MUTED}; font-size:{theme.fpx(7)}px;"> by Kestryl</span>'
        )
        self.byline_label.setObjectName("wordmark")
        self.byline_label.setTextInteractionFlags(Qt.NoTextInteraction)
        layout.addWidget(self.byline_label)
        layout.addStretch()

        _button_style = f"""
            font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(10)}px; letter-spacing: 1px;
            padding: 3px 8px; border: 1px solid {theme.BORDER_FLAT};
        """

        self.collapse_all_btn = QPushButton("▾ ALL")
        self.collapse_all_btn.setObjectName("cardIconBtn")
        self.collapse_all_btn.setStyleSheet(_button_style)
        self.collapse_all_btn.setToolTip("Collapse or expand every card at once")
        self.collapse_all_btn.clicked.connect(self._win.toggle_collapse_all)
        layout.addWidget(self.collapse_all_btn)

        self.tray_btn = QPushButton("TRAY")
        self.tray_btn.setObjectName("cardIconBtn")
        self.tray_btn.setStyleSheet(_button_style)
        self.tray_btn.clicked.connect(self._win.show_tray)
        layout.addWidget(self.tray_btn)

        self.settings_btn = QPushButton("SETTINGS")
        self.settings_btn.setObjectName("cardIconBtn")
        self.settings_btn.setStyleSheet(_button_style)
        self.settings_btn.clicked.connect(self._win.show_settings)
        layout.addWidget(self.settings_btn)

        self.minimize_btn = QPushButton("▬")
        self.minimize_btn.setObjectName("cardIconBtn")
        self.minimize_btn.setFixedSize(20, 20)
        self.minimize_btn.setToolTip("Stow mobiOverlay to a small button — click it (or the hotkey) to bring it back")
        self.minimize_btn.clicked.connect(self._win.stow_app)
        layout.addWidget(self.minimize_btn)

        close_btn = QPushButton("✕")
        close_btn.setObjectName("cardIconBtn")
        close_btn.setFixedSize(20, 20)
        close_btn.clicked.connect(self._win.close)
        layout.addWidget(close_btn)

    def update_tray_label(self):
        count = len(self._win.card_container.stowed_cards())
        self.tray_btn.setText(f"TRAY ({count})" if count else "TRAY")

    def set_collapse_all_label(self, all_collapsed: bool):
        self.collapse_all_btn.setText("▸ ALL" if all_collapsed else "▾ ALL")

    def set_stowed_mode(self, stowed: bool):
        """Pill mode: only the wordmark (click to deploy) and close stay
        visible — everything else would be dead weight on a small button."""
        self.collapse_all_btn.setVisible(not stowed)
        self.tray_btn.setVisible(not stowed)
        self.settings_btn.setVisible(not stowed)
        self.minimize_btn.setVisible(not stowed)
        self.byline_label.setVisible(not stowed)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self._win.pos()
            self._press_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None:
            self._win.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, event):
        if self._drag_offset is not None and self._win.is_app_stowed():
            moved = (event.globalPosition().toPoint() - self._press_pos).manhattanLength()
            if moved < 5:
                self._win.deploy_app()
        self._drag_offset = None


class MainWindow(QWidget):
    def __init__(self, config: Config):
        super().__init__()
        self.config = config
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        # Per-pixel alpha (not setWindowOpacity, which dims the whole
        # rendered window uniformly) so the empty background can be made
        # see-through independently of card opacity — cards paint their own
        # background at their own alpha (see Card.set_card_opacity) on top
        # of whatever the void behind them is doing.
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet(_build_stylesheet())

        # The void background is painted directly in paintEvent() below,
        # not via a QSS "background" rule. QSS-driven backgrounds on a
        # WA_TranslucentBackground top-level widget were tried first and
        # didn't work reliably — the alpha value updated correctly on the
        # Python/Qt side (confirmed) but never visibly changed on screen,
        # a known rough edge with Qt's style-sheet background compositing
        # on translucent windows. Painting with QPainter in
        # CompositionMode_Source writes the RGBA pixels directly and
        # doesn't go through that pipeline at all.
        self._void_opacity = config.data["ui"]["window_opacity"]

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(10)

        self.title_bar = _TitleBar(self)
        outer.addWidget(self.title_bar)

        self.card_container = CardContainer(config)
        self.card_container.setMinimumSize(420, 320)
        self.card_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.card_container.visibility_changed.connect(self.title_bar.update_tray_label)
        outer.addWidget(self.card_container, 1)

        footer = QHBoxLayout()
        footer.addStretch()
        self._size_grip = QSizeGrip(self)
        self._size_grip.setFixedSize(16, 16)
        footer.addWidget(self._size_grip)
        outer.addLayout(footer)

        self._normal_min_size = (460, 380)
        self.setMinimumSize(*self._normal_min_size)

        # Must exist before the resize()/move() calls below — moveEvent/
        # resizeEvent fire as soon as geometry changes, even pre-show.
        self._all_collapsed = False
        self._app_stowed = False
        self._geometry_tracking_ready = False
        self._geometry_save_timer = QTimer(self)
        self._geometry_save_timer.setSingleShot(True)
        self._geometry_save_timer.timeout.connect(self._save_tracked_geometry)

        pre_stow = config.data["ui"].get("pre_stow_geometry") or {}
        self._pre_stow_geometry: tuple[int, int, int, int] | None = (
            (pre_stow["x"], pre_stow["y"], pre_stow["width"], pre_stow["height"])
            if pre_stow else None
        )
        pill_geo = config.data["ui"].get("pill_geometry") or {}
        self._pill_geometry: tuple[int, int] | None = (
            (pill_geo["x"], pill_geo["y"]) if pill_geo else None
        )

        geo = config.data["ui"].get("window_geometry") or {}
        self.resize(geo.get("width", 680), geo.get("height", 560))
        default_x, default_y = _default_launch_position()
        self.move(geo.get("x", default_x), geo.get("y", default_y))
        self._geometry_tracking_ready = True

        # Global (system-wide) Stow/Deploy hotkey — works even while the
        # game has focus. installNativeEventFilter doesn't keep the filter
        # alive on its own, so self._hotkey is the thing keeping it around.
        self._hotkey = hotkey_mod.GlobalHotkey()
        QApplication.instance().installNativeEventFilter(self._hotkey)
        saved_mod = config.data["ui"].get("hotkey_mod")
        saved_vk = config.data["ui"].get("hotkey_vk")
        if saved_mod is not None and saved_vk is not None:
            self._hotkey.set_hotkey(saved_mod, saved_vk, self.toggle_app_stow)

    def toggle_collapse_all(self):
        self._all_collapsed = not self._all_collapsed
        self.card_container.set_all_collapsed(self._all_collapsed)
        self.title_bar.set_collapse_all_label(self._all_collapsed)

    def is_app_stowed(self) -> bool:
        return self._app_stowed

    def moveEvent(self, event):
        super().moveEvent(event)
        self._queue_geometry_save()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._queue_geometry_save()

    def _queue_geometry_save(self):
        # Debounced: a drag fires dozens of these a second, and only the
        # final position is worth writing to disk.
        if not self._geometry_tracking_ready:
            return
        self._geometry_save_timer.start(400)

    def _save_tracked_geometry(self):
        if self._app_stowed:
            self._pill_geometry = (self.x(), self.y())
            self.config.data["ui"]["pill_geometry"] = {"x": self.x(), "y": self.y()}
        else:
            self._pre_stow_geometry = (self.x(), self.y(), self.width(), self.height())
            self.config.data["ui"]["pre_stow_geometry"] = {
                "x": self.x(), "y": self.y(), "width": self.width(), "height": self.height(),
            }
        self.config.save()

    def stow_app(self):
        if self._app_stowed:
            return
        self._pre_stow_geometry = (self.x(), self.y(), self.width(), self.height())
        self.config.data["ui"]["pre_stow_geometry"] = {
            "x": self.x(), "y": self.y(), "width": self.width(), "height": self.height(),
        }
        self.card_container.setVisible(False)
        self._size_grip.setVisible(False)
        self.title_bar.set_stowed_mode(True)
        self._app_stowed = True
        self.setMinimumSize(1, 1)  # let it actually shrink to pill size
        # title_bar.sizeHint() alone ignores MainWindow's own content
        # margins (outer.setContentsMargins(10,10,10,10)) — pad for them
        # explicitly rather than resizing to an exact fit that clips it.
        hint = self.title_bar.sizeHint()
        self.resize(hint.width() + 24, hint.height() + 24)
        # Re-open at the pill's own last remembered spot, not wherever the
        # full-size window happened to be sitting — dragging the pill
        # around shouldn't get forgotten every time it's deployed and
        # re-stowed.
        if self._pill_geometry:
            self.move(*self._pill_geometry)
        self.config.save()

    def deploy_app(self):
        if not self._app_stowed:
            return
        self.card_container.setVisible(True)
        self._size_grip.setVisible(True)
        self.title_bar.set_stowed_mode(False)
        self._app_stowed = False
        self.setMinimumSize(*self._normal_min_size)
        if self._pre_stow_geometry:
            x, y, w, h = self._pre_stow_geometry
            self.move(x, y)
            self.resize(w, h)

    def toggle_app_stow(self):
        self.deploy_app() if self._app_stowed else self.stow_app()

    def set_stow_hotkey(self, mod: int, vk: int, display: str) -> bool:
        ok = self._hotkey.set_hotkey(mod, vk, self.toggle_app_stow)
        if ok:
            self.config.data["ui"]["hotkey_mod"] = mod
            self.config.data["ui"]["hotkey_vk"] = vk
            self.config.data["ui"]["hotkey_display"] = display
            self.config.save()
        return ok

    def clear_stow_hotkey(self):
        self._hotkey.clear()
        self.config.data["ui"]["hotkey_mod"] = None
        self.config.data["ui"]["hotkey_vk"] = None
        self.config.data["ui"]["hotkey_display"] = ""
        self.config.save()

    def last_hotkey_error(self) -> int | None:
        return self._hotkey.last_error

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        # CompositionMode_Source writes the RGBA pixels directly instead of
        # blending onto whatever's already in the (possibly garbage, for a
        # freshly-resized translucent surface) backing store — required for
        # the alpha value itself to be trustworthy.
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        color = QColor(theme.BG_VOID)
        color.setAlphaF(self._void_opacity)
        painter.fillRect(self.rect(), color)
        painter.end()
        super().paintEvent(event)

    def set_window_opacity_percent(self, value: int):
        opacity = value / 100
        self._void_opacity = opacity
        self.update()
        self.config.data["ui"]["window_opacity"] = opacity
        self.config.save()

    def set_card_opacity_percent(self, value: int):
        opacity = value / 100
        self.card_container.set_all_card_opacity(opacity)
        self.config.data["ui"]["card_opacity"] = opacity
        self.config.save()

    def set_font_scale(self, scale: float):
        self.config.data["ui"]["font_scale"] = scale
        self.config.save()

    def show_tray(self):
        panel = _TrayPanel(self)
        btn = self.title_bar.tray_btn
        panel.move(btn.mapToGlobal(QPoint(0, btn.height())))
        panel.show()

    def show_settings(self):
        panel = _SettingsPanel(self)
        btn = self.title_bar.settings_btn
        panel.move(btn.mapToGlobal(QPoint(0, btn.height())))
        panel.show()

    def relaunch(self):
        subprocess.Popen(relaunch_command(), cwd=str(app_root()))
        self.close()
        # Not just self.close(): the Settings panel that owns this button
        # is itself a live top-level widget (Qt.Popup with WA_StyledBackground
        # still counts as a window), so Qt's quitOnLastWindowClosed never
        # fires and the old process lingers indefinitely. Quit explicitly.
        QApplication.instance().quit()

    def closeEvent(self, event):
        # If stowed, self.x()/y()/width()/height() describe the tiny pill,
        # not a size worth reopening at next launch — save the geometry
        # from before it was stowed instead.
        if self._app_stowed and self._pre_stow_geometry:
            x, y, w, h = self._pre_stow_geometry
        else:
            x, y, w, h = self.x(), self.y(), self.width(), self.height()
        self.config.data["ui"]["window_geometry"] = {"x": x, "y": y, "width": w, "height": h}
        self.config.save()
        self._hotkey.clear()
        super().closeEvent(event)
