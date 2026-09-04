"""Always-on-top, frameless, draggable overlay window. Houses the
CardContainer, the tray for stowed (hidden) cards, and Settings.
"""
import subprocess

from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSlider, QSizeGrip, QSizePolicy
)

from host import theme
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
            "WINDOW OPACITY", "How see-through the whole overlay is."
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


class _TitleBar(QWidget):
    def __init__(self, main_window: "MainWindow"):
        super().__init__()
        self.setObjectName("titleBar")
        self._win = main_window
        self._drag_offset: QPoint | None = None
        self.setFixedHeight(38)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 12, 0)

        wordmark = QLabel(
            f'<span style="color:{theme.TEXT_PRIMARY};">MOBI</span>'
            f'<span style="color:{theme.ACCENT_CYAN};">OVERLAY</span>'
            f'<span style="color:{theme.TEXT_MUTED}; font-size:{theme.fpx(7)}px;"> by Kestryl</span>'
        )
        wordmark.setObjectName("wordmark")
        layout.addWidget(wordmark)
        layout.addStretch()

        _button_style = f"""
            font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(10)}px; letter-spacing: 1px;
            padding: 3px 8px; border: 1px solid {theme.BORDER_FLAT};
        """

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

        close_btn = QPushButton("✕")
        close_btn.setObjectName("cardIconBtn")
        close_btn.setFixedSize(20, 20)
        close_btn.clicked.connect(self._win.close)
        layout.addWidget(close_btn)

    def update_tray_label(self):
        count = len(self._win.card_container.stowed_cards())
        self.tray_btn.setText(f"TRAY ({count})" if count else "TRAY")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self._win.pos()

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None:
            self._win.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None


class MainWindow(QWidget):
    def __init__(self, config: Config):
        super().__init__()
        self.config = config
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setStyleSheet(_build_stylesheet())
        self.setWindowOpacity(config.data["ui"]["window_opacity"])

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(10)
        self.setStyleSheet(self.styleSheet() + f"MainWindow {{ background: {theme.BG_VOID}; }}")

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

        self.setMinimumSize(460, 380)

        geo = config.data["ui"].get("window_geometry") or {}
        self.resize(geo.get("width", 680), geo.get("height", 560))
        default_x, default_y = _default_launch_position()
        self.move(geo.get("x", default_x), geo.get("y", default_y))

    def set_window_opacity_percent(self, value: int):
        opacity = value / 100
        self.setWindowOpacity(opacity)
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
        self.config.data["ui"]["window_geometry"] = {
            "x": self.x(), "y": self.y(),
            "width": self.width(), "height": self.height(),
        }
        self.config.save()
        super().closeEvent(event)
