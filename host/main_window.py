"""Always-on-top, frameless, draggable overlay window. Houses the
CardContainer, the tray for stowed (hidden) cards, and Settings.
"""
import ctypes
import subprocess
from ctypes import wintypes

from PySide6.QtCore import Qt, QPoint, QRectF, QTimer
from PySide6.QtGui import QGuiApplication, QColor, QPainter, QPainterPath
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
        stop:0 #182029, stop:1 #0d131a);
    border: 1px solid {theme.BORDER_CYAN};
    border-radius: {theme.RADIUS}px;
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
    border-radius: {theme.RADIUS}px;
    font-size: {theme.fpx(11)}px;
}}
QPushButton#cardIconBtn:hover {{
    color: {theme.ACCENT_CYAN};
}}
QPushButton#retryBtn {{
    background: transparent;
    color: {theme.ACCENT_AMBER};
    border: 1px solid {theme.BORDER_AMBER};
    border-radius: {theme.RADIUS}px;
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
            _TrayPanel {{ background: {theme.BG_PANEL}; border: 1px solid {theme.BORDER_CYAN}; border-radius: {theme.RADIUS}px; }}
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
    hotkey — works even while another app (the game) has focus. Capture is
    handled by host/hotkey.py's GlobalHotkey.capture_combo(), which uses
    the `keyboard` library's low-level global hook (the same mechanism
    ThrottleWatch uses) rather than Qt key events — a Qt.Popup-hosted field
    like this one doesn't reliably receive OS keyboard focus for
    SendKeys-style testing, and more importantly the previous Win32
    RegisterHotKey approach this used to be built on didn't fire at all
    while a fullscreen game had focus (see docs/DECISIONS.md).

    A bare key (no modifier) is allowed — this hook doesn't "steal" the
    key system-wide the way RegisterHotKey would (suppress=False), it
    only listens, so a bare F3 hotkey doesn't stop F3 also reaching the
    game normally.
    """

    def __init__(self, main_window: "MainWindow"):
        super().__init__()
        self._win = main_window
        self.setReadOnly(True)
        self.setAlignment(Qt.AlignCenter)
        self._capturing = False
        self._capture_handles = []  # keeps in-flight capture signal-holder QObjects alive
        self._show_current()

    def _show_current(self):
        display = self._win.config.data["ui"].get("hotkey_display") or ""
        self.setText(display if display else "Click to set…")

    def _flash(self, message: str):
        self.setText(message)
        QTimer.singleShot(1600, self._show_current)

    def mousePressEvent(self, event):
        if self._capturing:
            return
        self._capturing = True
        self.setText("Press a key combo…")
        handle = self._win.capture_hotkey_combo(
            lambda combo: self._on_captured(handle, combo),
            lambda message: self._on_capture_error(handle, message),
        )
        self._capture_handles.append(handle)

    def _on_captured(self, handle, combo: str):
        self._capture_handles.remove(handle)
        self._capturing = False
        if not combo or combo.lower() == "esc":
            self._show_current()  # Escape cancels rather than becoming the hotkey
            return
        display = "+".join(part.title() for part in combo.split("+"))
        if self._win.set_stow_hotkey(combo, display):
            self._show_current()
        else:
            self._flash("Could not set hotkey")

    def _on_capture_error(self, handle, message: str):
        self._capture_handles.remove(handle)
        self._capturing = False
        self._flash("Capture failed — try again")


class _SettingsPanel(QWidget):
    """Window Opacity, Card Opacity, and Text Size — a themed panel next to
    the Tray, same Qt.Popup pattern (closes on an outside click)."""

    def __init__(self, main_window: "MainWindow"):
        super().__init__(main_window, Qt.Popup)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            _SettingsPanel {{ background: {theme.BG_PANEL}; border: 1px solid {theme.BORDER_CYAN}; border-radius: {theme.RADIUS}px; }}
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
                    border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px; padding: 4px 6px;
                    font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(9)}px;
                }}
                QPushButton:checked {{
                    color: {theme.ACCENT_CYAN}; border: 1px solid {theme.BORDER_CYAN};
                }}
            """)
            btn.clicked.connect(lambda checked, s=scale: main_window.set_font_scale(s))
            text_row.control_row.addWidget(btn)
        layout.addWidget(text_row)

        # -- Debug Console --
        console_row = _SettingsRow(
            "DEBUG CONSOLE",
            "Shows a console window with log output. Applies after a relaunch.",
        )
        current_show_console = main_window.config.data["ui"].get("show_console", False)
        console_btn = QPushButton()
        console_btn.setCheckable(True)
        console_btn.setChecked(current_show_console)
        console_btn.setText("ON" if current_show_console else "OFF")
        console_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {theme.TEXT_MUTED};
                border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px; padding: 4px 10px;
                font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(9)}px;
            }}
            QPushButton:checked {{
                color: {theme.ACCENT_CYAN}; border: 1px solid {theme.BORDER_CYAN};
            }}
        """)

        def _on_console_toggled(checked: bool):
            console_btn.setText("ON" if checked else "OFF")
            main_window.set_show_console(checked)

        console_btn.toggled.connect(_on_console_toggled)
        console_row.control_row.addWidget(console_btn)
        layout.addWidget(console_row)

        # -- Relaunch --
        relaunch_row = QWidget()
        relaunch_layout = QHBoxLayout(relaunch_row)
        relaunch_layout.setContentsMargins(12, 4, 12, 12)
        relaunch_btn = QPushButton("RELAUNCH")
        relaunch_btn.setToolTip("Closes and reopens mobiOverlay — applies Text Size and anything else that needs a fresh start.")
        relaunch_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {theme.ACCENT_CYAN};
                border: 1px solid {theme.BORDER_CYAN}; border-radius: {theme.RADIUS}px; padding: 6px 0;
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
                border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px; padding: 4px 6px;
                font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(10)}px;
            }}
        """)
        hotkey_row.control_row.addWidget(hotkey_field, 1)
        clear_btn = QPushButton("CLEAR")
        clear_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {theme.TEXT_MUTED};
                border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px; padding: 4px 8px;
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
            f'<span style="color:{theme.TEXT_PRIMARY};">mobi</span>'
            f'<span style="color:{theme.ACCENT_CYAN};">Overlay</span>'
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
            padding: 3px 8px; border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px;
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
        if self._drag_offset is not None:
            moved = (event.globalPosition().toPoint() - self._press_pos).manhattanLength()
            if self._win.is_app_stowed():
                if moved < 5:
                    self._win.deploy_app()
                else:
                    # A real drag, not a click-to-deploy — save the pill's
                    # new spot immediately, at the exact moment the drag
                    # ends, rather than on a debounce timer that a quick
                    # follow-up deploy could race and overwrite.
                    self._win.save_current_position()
            elif moved >= 5:
                self._win.save_current_position()
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
        # game has focus, via a low-level keyboard hook (see hotkey.py).
        self._hotkey = hotkey_mod.GlobalHotkey()
        saved_combo = config.data["ui"].get("hotkey_combo")
        if saved_combo:
            self._hotkey.set_hotkey(saved_combo, self.toggle_app_stow)

    def toggle_collapse_all(self):
        self._all_collapsed = not self._all_collapsed
        self.card_container.set_all_collapsed(self._all_collapsed)
        self.title_bar.set_collapse_all_label(self._all_collapsed)

    def is_app_stowed(self) -> bool:
        return self._app_stowed

    def moveEvent(self, event):
        super().moveEvent(event)
        # Position is saved precisely at the natural end of a move — a
        # drag release in the title bar (_TitleBar.mouseReleaseEvent), or
        # the end of stow_app()/deploy_app()'s own programmatic
        # repositioning below — not here. A debounced save keyed off raw
        # move events was tried first and had a real bug: the shared timer
        # only checks is_app_stowed() when it finally fires, so a quick
        # drag-the-pill-then-deploy sequence could restart the same timer
        # from the deploy's own move before the pill's save ever fired,
        # silently dropping the pill's dragged position entirely.

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Resizing only happens deployed (the grip is hidden while
        # stowed), so this can safely always target pre_stow_geometry —
        # no risk of the moveEvent race above, since there's no
        # size-changing gesture on the pill to race against.
        if not self._geometry_tracking_ready or self._app_stowed:
            return
        self._geometry_save_timer.start(400)

    def _save_tracked_geometry(self):
        self._pre_stow_geometry = (self.x(), self.y(), self.width(), self.height())
        self.config.data["ui"]["pre_stow_geometry"] = {
            "x": self.x(), "y": self.y(), "width": self.width(), "height": self.height(),
        }
        self.config.save()

    def save_current_position(self):
        """Immediate (non-debounced) position save — called right when a
        move actually finishes: a drag release in the title bar, or the
        end of stow_app()/deploy_app()'s own repositioning. Whatever ends
        up on screen is exactly what gets persisted, with no window for a
        fast follow-up action to race and overwrite it first."""
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
        self.save_current_position()
        self._take_foreground_focus()

    def _take_foreground_focus(self):
        """Deploying via the hotkey shouldn't leave the game with input
        focus while the overlay is what's visually on top — pull real OS
        focus onto the window, not just raise it in z-order.

        Windows normally refuses SetForegroundWindow from a background
        process (the caller here is the keyboard-hook callback, not a
        real click). AttachThreadInput temporarily joins this thread's
        input queue with the currently-focused window's thread — Windows'
        foreground-switch restriction is keyed on "is the caller attached
        to the same input queue as the current foreground window," so this
        satisfies it directly rather than relying on lock-timeout heuristics
        (the "tap Alt first" trick some hotkey launchers use) that turned
        out not to be reliable here.
        """
        self.raise_()
        self.activateWindow()

        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.BringWindowToTop.argtypes = [wintypes.HWND]

        hwnd = wintypes.HWND(int(self.winId()))
        fg_hwnd = user32.GetForegroundWindow()
        cur_thread = ctypes.windll.kernel32.GetCurrentThreadId()
        fg_thread = user32.GetWindowThreadProcessId(fg_hwnd, None) if fg_hwnd else 0

        if fg_thread and fg_thread != cur_thread:
            user32.AttachThreadInput(cur_thread, fg_thread, True)
            try:
                user32.SetForegroundWindow(hwnd)
                user32.BringWindowToTop(hwnd)
            finally:
                user32.AttachThreadInput(cur_thread, fg_thread, False)
        else:
            user32.SetForegroundWindow(hwnd)

    def toggle_app_stow(self):
        self.deploy_app() if self._app_stowed else self.stow_app()

    def capture_hotkey_combo(self, on_captured, on_error=None):
        return self._hotkey.capture_combo(on_captured, on_error)

    def set_stow_hotkey(self, combo: str, display: str) -> bool:
        ok = self._hotkey.set_hotkey(combo, self.toggle_app_stow)
        if ok:
            self.config.data["ui"]["hotkey_combo"] = combo
            self.config.data["ui"]["hotkey_display"] = display
            self.config.save()
        return ok

    def clear_stow_hotkey(self):
        self._hotkey.clear()
        self.config.data["ui"]["hotkey_combo"] = ""
        self.config.data["ui"]["hotkey_display"] = ""
        self.config.save()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        # CompositionMode_Source writes the RGBA pixels directly instead of
        # blending onto whatever's already in the (possibly garbage, for a
        # freshly-resized translucent surface) backing store — required for
        # the alpha value itself to be trustworthy. Clear the whole rect
        # first (fully transparent), since fillPath below only touches
        # pixels inside the rounded shape — without this, the four corners
        # cut off by the rounding would keep whatever garbage/stale pixels
        # were already in the backing store instead of being see-through.
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.fillRect(self.rect(), Qt.transparent)
        color = QColor(theme.BG_VOID)
        color.setAlphaF(self._void_opacity)
        path = QPainterPath()
        # This is the window's own true outer edge — both deployed and
        # stowed-to-a-pill use this same MainWindow/paintEvent, so the
        # pill gets the exact same corner radius as everything else for
        # free, not a separate value to keep in sync.
        path.addRoundedRect(QRectF(self.rect()), theme.RADIUS, theme.RADIUS)
        painter.fillPath(path, color)
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

    def set_show_console(self, show_console: bool):
        self.config.data["ui"]["show_console"] = show_console
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
        # Release this instance's exclusive resources *before* starting the
        # new one, not after — spawning the new process first (the old
        # order) left a window where both instances could be alive at
        # once: two live global keyboard hooks racing for the same Stow/
        # Deploy hotkey, and the new instance reading config.json before
        # this one's window_geometry save had actually landed.
        self._save_window_geometry()
        self._hotkey.shutdown()
        subprocess.Popen(relaunch_command(), cwd=str(app_root()))
        self.close()
        # Not just self.close(): the Settings panel that owns this button
        # is itself a live top-level widget (Qt.Popup with WA_StyledBackground
        # still counts as a window), so Qt's quitOnLastWindowClosed never
        # fires and the old process lingers indefinitely. Quit explicitly.
        QApplication.instance().quit()
        # Belt-and-suspenders against the user-reported symptom this was
        # written for ("the old process isn't always fully gone before the
        # new one starts"): everything that must be saved is already done
        # above, so don't trust a normal interpreter shutdown to finish
        # promptly from here. Once a Logistics Hub scan has loaded
        # easyocr/torch, their native (non-Python) thread pools are a
        # known source of slow or stuck interpreter teardown on Windows —
        # os._exit() ends the process immediately instead of waiting on
        # that.
        import os
        os._exit(0)

    def _save_window_geometry(self):
        # If stowed, self.x()/y()/width()/height() describe the tiny pill,
        # not a size worth reopening at next launch — save the geometry
        # from before it was stowed instead.
        if self._app_stowed and self._pre_stow_geometry:
            x, y, w, h = self._pre_stow_geometry
        else:
            x, y, w, h = self.x(), self.y(), self.width(), self.height()
        self.config.data["ui"]["window_geometry"] = {"x": x, "y": y, "width": w, "height": h}
        self.config.save()

    def closeEvent(self, event):
        self._save_window_geometry()
        # Fully releases the OS-level global keyboard hook and its
        # watchdog timer, not just this app's own combo/callback state —
        # see `GlobalHotkey.shutdown()`. Safe to call even if `relaunch()`
        # already called it (idempotent).
        self._hotkey.shutdown()
        super().closeEvent(event)
