"""Always-on-top, frameless, draggable, opacity-adjustable overlay window.
Houses the CardContainer and a card picker for hidden cards.
"""
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSlider, QMenu,
    QSizeGrip, QSizePolicy
)

from host import theme
from host.card_container import CardContainer
from host.config import Config

STYLESHEET = f"""
QWidget#titleBar {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #0f1a1d, stop:1 #0a1214);
    border: 1px solid {theme.BORDER_CYAN};
}}
QLabel#wordmark {{
    font-family: "{theme.FONT_DISPLAY}";
    font-weight: 800;
    font-size: 14px;
    letter-spacing: 3px;
}}
QLabel#cardTitle {{
    color: {theme.TEXT_PRIMARY};
    font-family: "{theme.FONT_DISPLAY}";
    font-weight: 700;
    font-size: 11px;
    letter-spacing: 2px;
}}
QPushButton#cardIconBtn {{
    background: transparent;
    color: {theme.TEXT_MUTED};
    border: none;
    font-size: 11px;
}}
QPushButton#cardIconBtn:hover {{
    color: {theme.ACCENT_CYAN};
}}
QPushButton#retryBtn {{
    background: transparent;
    color: {theme.ACCENT_AMBER};
    border: 1px solid {theme.BORDER_AMBER};
    font-family: "{theme.FONT_MONO}";
    font-size: 10px;
    letter-spacing: 2px;
    padding: 5px 0;
}}
QPushButton#retryBtn:hover {{
    background: {theme.ACCENT_AMBER_DIM};
}}
QLabel#errorMessage {{
    color: {theme.TEXT_PRIMARY};
    font-family: "{theme.FONT_MONO}";
    font-size: 11px;
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
            f'<span style="color:{theme.TEXT_MUTED}; font-size:7px;"> by Kestryl</span>'
        )
        wordmark.setObjectName("wordmark")
        layout.addWidget(wordmark)
        layout.addStretch()

        self.picker_btn = QPushButton("+ ADD CARD")
        self.picker_btn.setObjectName("cardIconBtn")
        self.picker_btn.setStyleSheet(f"""
            font-family: "{theme.FONT_MONO}"; font-size: 10px; letter-spacing: 1px;
            padding: 3px 8px; border: 1px solid {theme.BORDER_FLAT};
        """)
        self.picker_btn.clicked.connect(self._win.show_card_picker)
        layout.addWidget(self.picker_btn)

        opacity_slider = QSlider(Qt.Horizontal)
        opacity_slider.setRange(40, 100)
        opacity_slider.setValue(int(self._win.config.data["ui"]["opacity"] * 100))
        opacity_slider.setFixedWidth(70)
        opacity_slider.valueChanged.connect(self._win.set_opacity_percent)
        layout.addWidget(opacity_slider)

        close_btn = QPushButton("✕")
        close_btn.setObjectName("cardIconBtn")
        close_btn.setFixedSize(20, 20)
        close_btn.clicked.connect(self._win.close)
        layout.addWidget(close_btn)

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
        self.setStyleSheet(STYLESHEET)
        self.setWindowOpacity(config.data["ui"]["opacity"])

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(10)
        self.setStyleSheet(self.styleSheet() + f"MainWindow {{ background: {theme.BG_VOID}; }}")

        self.title_bar = _TitleBar(self)
        outer.addWidget(self.title_bar)

        self.card_container = CardContainer(config)
        self.card_container.setMinimumSize(420, 320)
        self.card_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
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

    def set_opacity_percent(self, value: int):
        opacity = value / 100
        self.setWindowOpacity(opacity)
        self.config.data["ui"]["opacity"] = opacity
        self.config.save()

    def show_card_picker(self):
        menu = QMenu(self)
        for card_id, card in self.card_container.cards.items():
            visible = self.card_container.is_visible(card_id)
            label = ("✓ " if visible else "  ") + card.header.title_label.text()
            action = menu.addAction(label)
            action.triggered.connect(
                lambda checked=False, cid=card_id, v=visible: (
                    self.card_container.hide_card(cid) if v else self.card_container.show_card(cid)
                )
            )
        menu.exec(self.title_bar.picker_btn.mapToGlobal(QPoint(0, self.title_bar.picker_btn.height())))

    def closeEvent(self, event):
        self.config.data["ui"]["window_geometry"] = {
            "x": self.x(), "y": self.y(),
            "width": self.width(), "height": self.height(),
        }
        self.config.save()
        super().closeEvent(event)
