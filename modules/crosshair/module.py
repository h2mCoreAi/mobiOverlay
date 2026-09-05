"""Crosshair overlay module: draws a fixed reticle dead-center on the
primary display (the gaming monitor on this machine — see
docs/ARCHITECTURE.md), with small-increment nudge controls, because Star
Citizen's own crosshair has a habit of disappearing.

The reticle itself (_CrosshairOverlay) is a separate top-level widget from
the card — it needs to be click-through and centered on the actual
screen, independent of wherever the mobiOverlay window itself is sitting.
The card just holds the Show/Hide toggle, nudge buttons, and Reset.
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QColor, QPainter, QPen
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QWidget

from host import theme
from host.module_base import ModuleBase

RETICLE_SIZE = 40  # the overlay widget is a square this many px on a side
LINE_LENGTH = 14  # each arm of the "+"
GAP = 4  # empty space at dead-center, so the lines don't cover the aim point
LINE_WIDTH = 2
NUDGE_STEP = 1  # px per click — deliberately small, this is for fine calibration


class _CrosshairOverlay(QWidget):
    """The actual reticle — a tiny, click-through, always-on-top widget
    repositioned to stay centered on the primary screen plus whatever
    offset the user has dialed in. Never intercepts mouse input: it must
    never get in the way of aiming."""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setFixedSize(RETICLE_SIZE, RETICLE_SIZE)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(theme.ACCENT_CYAN))
        pen.setWidth(LINE_WIDTH)
        painter.setPen(pen)
        c = RETICLE_SIZE // 2
        half = LINE_LENGTH // 2
        painter.drawLine(c - half - GAP, c, c - GAP, c)
        painter.drawLine(c + GAP, c, c + half + GAP, c)
        painter.drawLine(c, c - half - GAP, c, c - GAP)
        painter.drawLine(c, c + GAP, c, c + half + GAP)

    def reposition(self, offset_x: int, offset_y: int):
        screen = QGuiApplication.primaryScreen()
        geo = screen.geometry()
        cx = geo.x() + geo.width() // 2 + offset_x
        cy = geo.y() + geo.height() // 2 + offset_y
        self.move(cx - RETICLE_SIZE // 2, cy - RETICLE_SIZE // 2)


_TOGGLE_BTN_STYLE = f"""
    QPushButton {{
        background: transparent; color: {theme.ACCENT_CYAN};
        border: 1px solid {theme.BORDER_CYAN}; border-radius: {theme.RADIUS}px; padding: 6px 0;
        font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(9)}px; letter-spacing: 1px;
    }}
    QPushButton:hover {{ background: {theme.ACCENT_CYAN_DIM}; }}
"""
_NUDGE_BTN_STYLE = f"""
    QPushButton {{
        background: transparent; color: {theme.ACCENT_CYAN};
        border: 1px solid {theme.BORDER_CYAN}; border-radius: {theme.RADIUS}px; font-size: {theme.fpx(13)}px;
    }}
    QPushButton:hover {{ background: {theme.ACCENT_CYAN_DIM}; }}
"""
_OFFSET_LABEL_STYLE = f'color: {theme.TEXT_MUTED}; font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(9)}px;'


class CrosshairModule(ModuleBase):
    module_id = "crosshair"
    # Rich-text mobi-branding, same pattern as Logistics Hub's
    # display_name (host/card.py's title_label no longer forces
    # uppercase, so this mixed case survives intact).
    display_name = (
        f'<span style="color:{theme.TEXT_PRIMARY};">mobi</span>'
        f'<span style="color:{theme.ACCENT_CYAN};">Aim</span>'
    )

    def __init__(self, api_client, config):
        super().__init__(api_client, config)
        self._overlay = _CrosshairOverlay()
        self.request_refresh = None  # injected by host after wrapping refresh()

    def create_card(self, container):
        card = container.add_card(self.module_id, self.display_name)

        self.toggle_btn = QPushButton()
        self.toggle_btn.setStyleSheet(_TOGGLE_BTN_STYLE)
        self.toggle_btn.clicked.connect(self._on_toggle_clicked)
        card.body_layout.addWidget(self.toggle_btn)

        self.offset_label = QLabel()
        self.offset_label.setStyleSheet(_OFFSET_LABEL_STYLE)
        self.offset_label.setAlignment(Qt.AlignCenter)
        card.body_layout.addWidget(self.offset_label)

        nudge_grid = QGridLayout()
        nudge_grid.setSpacing(4)
        up_btn, down_btn, left_btn, right_btn = (
            QPushButton("▲"), QPushButton("▼"), QPushButton("◀"), QPushButton("▶")
        )
        for btn in (up_btn, down_btn, left_btn, right_btn):
            btn.setStyleSheet(_NUDGE_BTN_STYLE)
            btn.setFixedSize(36, 28)
        up_btn.clicked.connect(lambda: self._nudge(0, -NUDGE_STEP))
        down_btn.clicked.connect(lambda: self._nudge(0, NUDGE_STEP))
        left_btn.clicked.connect(lambda: self._nudge(-NUDGE_STEP, 0))
        right_btn.clicked.connect(lambda: self._nudge(NUDGE_STEP, 0))
        nudge_grid.addWidget(up_btn, 0, 1)
        nudge_grid.addWidget(left_btn, 1, 0)
        nudge_grid.addWidget(right_btn, 1, 2)
        nudge_grid.addWidget(down_btn, 2, 1)
        nudge_wrap = QHBoxLayout()
        nudge_wrap.addStretch()
        nudge_wrap.addLayout(nudge_grid)
        nudge_wrap.addStretch()
        card.body_layout.addLayout(nudge_wrap)

        reset_btn = QPushButton("RESET TO CENTER")
        reset_btn.setStyleSheet(_TOGGLE_BTN_STYLE)
        reset_btn.clicked.connect(self._on_reset_clicked)
        card.body_layout.addWidget(reset_btn)

        self.card = card
        self._apply_state()
        return card

    def refresh(self):
        pass  # purely local visual state — nothing to fetch from anywhere

    def _apply_state(self):
        visible = self.settings.get("visible", True)
        offset_x = self.settings.get("offset_x", 0)
        offset_y = self.settings.get("offset_y", 0)
        self._overlay.reposition(offset_x, offset_y)
        self._overlay.setVisible(visible)
        self.toggle_btn.setText("HIDE CROSSHAIR" if visible else "SHOW CROSSHAIR")
        self.offset_label.setText(f"OFFSET   X {offset_x:+d}   Y {offset_y:+d}")

    def _save_settings(self):
        self.config.set_module_settings(self.module_id, self.settings)

    def _on_toggle_clicked(self):
        self.settings["visible"] = not self.settings.get("visible", True)
        self._save_settings()
        self._apply_state()

    def _nudge(self, dx: int, dy: int):
        self.settings["offset_x"] = self.settings.get("offset_x", 0) + dx
        self.settings["offset_y"] = self.settings.get("offset_y", 0) + dy
        self._save_settings()
        self._apply_state()

    def _on_reset_clicked(self):
        self.settings["offset_x"] = 0
        self.settings["offset_y"] = 0
        self._save_settings()
        self._apply_state()


MODULE_CLASS = CrosshairModule
