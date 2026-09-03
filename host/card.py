"""Reusable Card widget: draggable (with grid-snap preview), resizable,
collapsible, closable, with a built-in error state. Modules build their
content inside `card.body` and never touch the header/chrome directly.
"""
from PySide6.QtCore import Qt, Signal, QPoint
from PySide6.QtGui import QPainter, QPen, QColor
from PySide6.QtWidgets import (
    QFrame, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
)

from host import theme

CARD_WIDTH = 300
CARD_MIN_WIDTH = 220
CARD_MIN_HEIGHT = theme.CARD_HEADER_HEIGHT + 60


class _DragHeader(QWidget):
    """Header strip: status dot, title, collapse toggle, close button.
    Dragging the header moves the owning Card within its container and
    shows a purple grid-snap preview of where it will land.
    """
    collapse_toggled = Signal()
    close_clicked = Signal()

    def __init__(self, title: str, parent_card: "Card"):
        super().__init__()
        self._card = parent_card
        self._drag_offset: QPoint | None = None
        self.setFixedHeight(theme.CARD_HEADER_HEIGHT)
        self.setCursor(Qt.OpenHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 10, 0)
        layout.setSpacing(8)

        self.dot = QLabel("●")
        self.dot.setStyleSheet(f"color: {theme.ACCENT_CYAN}; font-size: 9px;")
        layout.addWidget(self.dot)

        self.title_label = QLabel(title.upper())
        self.title_label.setObjectName("cardTitle")
        layout.addWidget(self.title_label)
        layout.addStretch()

        self.collapse_btn = QPushButton("▾")
        self.collapse_btn.setObjectName("cardIconBtn")
        self.collapse_btn.setFixedSize(18, 18)
        self.collapse_btn.clicked.connect(self.collapse_toggled.emit)
        layout.addWidget(self.collapse_btn)

        self.close_btn = QPushButton("✕")
        self.close_btn.setObjectName("cardIconBtn")
        self.close_btn.setFixedSize(18, 18)
        self.close_btn.setToolTip("Stow")
        self.close_btn.clicked.connect(self.close_clicked.emit)
        layout.addWidget(self.close_btn)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self._card.pos()
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None:
            new_pos = event.globalPosition().toPoint() - self._drag_offset
            self._card.move_within_container(new_pos)
            container = self._card.container
            snapped_x = container.snap_to_grid(self._card.x())
            snapped_y = container.snap_to_grid(self._card.y())
            container.show_snap_preview(snapped_x, snapped_y, self._card.width(), self._card.height())

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = None
            self.setCursor(Qt.OpenHandCursor)
            self._card.container.hide_snap_preview()
            self._card.drag_finished()


class _ResizeHandle(QWidget):
    """Bottom-right corner grip: drag to resize the card while expanded."""

    def __init__(self, parent_card: "Card"):
        super().__init__(parent_card)
        self._card = parent_card
        self.setFixedSize(14, 14)
        self.setCursor(Qt.SizeFDiagCursor)
        self._drag_start: QPoint | None = None
        self._start_size = None

    def paintEvent(self, event):
        painter = QPainter(self)
        pen = QPen(QColor(theme.ACCENT_CYAN))
        painter.setPen(pen)
        for offset in (2, 6, 10):
            painter.drawLine(offset, 13, 13, offset)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start = event.globalPosition().toPoint()
            self._start_size = self._card.size()

    def mouseMoveEvent(self, event):
        if self._drag_start is not None:
            delta = event.globalPosition().toPoint() - self._drag_start
            new_w = max(CARD_MIN_WIDTH, self._start_size.width() + delta.x())
            new_h = max(CARD_MIN_HEIGHT, self._start_size.height() + delta.y())
            self._card.set_manual_size(new_w, new_h)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start = None


class Card(QFrame):
    stowed = Signal(str)   # card_id — emitted when the header's Stow button is clicked
    moved = Signal(str, int, int)  # card_id, x, y
    resized = Signal(str, int, int)  # card_id, width, height
    collapsed_changed = Signal(str, bool)  # card_id, collapsed

    def __init__(self, card_id: str, title: str, container: QWidget):
        super().__init__(container)
        self.card_id = card_id
        self.container = container
        self._collapsed = False
        self._manual_size: tuple[int, int] | None = None
        self.setMinimumWidth(CARD_MIN_WIDTH)
        self.setMinimumHeight(CARD_MIN_HEIGHT)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.header = _DragHeader(title, self)
        self.header.collapse_toggled.connect(self.toggle_collapsed)
        self.header.close_clicked.connect(lambda: self.stowed.emit(self.card_id))
        outer.addWidget(self.header)

        # Body: module content lives here.
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(14, 14, 14, 14)
        self.body_layout.setSpacing(8)
        outer.addWidget(self.body)

        # Error overlay: built in, toggled via set_error()/clear_error().
        self.error_widget = self._build_error_widget()
        self.error_widget.setVisible(False)
        outer.addWidget(self.error_widget)

        self._resize_handle = _ResizeHandle(self)

        self._apply_border(theme.ACCENT_CYAN)
        self.apply_size()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_handle.move(self.width() - 14, self.height() - 14)
        self._resize_handle.raise_()

    # -- sizing -----------------------------------------------------------
    def apply_size(self):
        """Recompute this card's on-screen size. Called after the module
        populates card.body (the card had no content yet when it first
        computed a size), and any time collapse/error state changes.
        A manually-resized width always sticks; manually-resized height
        sticks only while expanded and error-free (collapse/error always
        show their own natural, minimal height).
        """
        self.layout().activate()
        hint = self.layout().sizeHint()
        width = self._manual_size[0] if self._manual_size else hint.width()
        if self._collapsed or self.error_widget.isVisible():
            height = hint.height()
        elif self._manual_size:
            height = self._manual_size[1]
        else:
            height = hint.height()
        self.resize(width, height)
        self.update()
        self.container.update()

    def set_manual_size(self, w: int, h: int):
        w = max(CARD_MIN_WIDTH, w)
        h = max(CARD_MIN_HEIGHT, h)
        self._manual_size = (w, h)
        self.apply_size()
        self.resized.emit(self.card_id, w, h)

    # -- error state --------------------------------------------------
    def _build_error_widget(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(14, 16, 14, 16)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignCenter)

        icon = QLabel("⚠")
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet(f"color: {theme.ACCENT_AMBER}; font-size: 22px;")
        layout.addWidget(icon)

        self.error_message = QLabel("")
        self.error_message.setAlignment(Qt.AlignCenter)
        self.error_message.setWordWrap(True)
        self.error_message.setObjectName("errorMessage")
        layout.addWidget(self.error_message)

        retry_btn = QPushButton("RETRY")
        retry_btn.setObjectName("retryBtn")
        retry_btn.setFixedWidth(90)
        retry_btn.clicked.connect(self._on_retry)
        layout.addWidget(retry_btn, alignment=Qt.AlignCenter)
        self._retry_btn = retry_btn
        self._retry_callback = None
        return w

    def set_error(self, message: str, retry_callback=None):
        self.error_message.setText(message)
        self._retry_callback = retry_callback
        self.body.setVisible(False)
        self.error_widget.setVisible(not self._collapsed)
        self._apply_border(theme.ACCENT_AMBER)
        self.apply_size()

    def clear_error(self):
        self.error_widget.setVisible(False)
        self.body.setVisible(not self._collapsed)
        self._apply_border(theme.ACCENT_CYAN)
        self.apply_size()

    def _on_retry(self):
        if self._retry_callback:
            self._retry_callback()

    def _apply_border(self, color: str):
        self.setStyleSheet(f"""
            Card {{
                background: {theme.BG_PANEL};
                border: 1px solid {color};
            }}
        """)

    # -- collapse -------------------------------------------------------
    def toggle_collapsed(self):
        self.set_collapsed(not self._collapsed)

    def set_collapsed(self, collapsed: bool):
        self._collapsed = collapsed
        in_error = self.error_widget.isVisible() or (
            not self.body.isVisible() and self._retry_callback is not None
        )
        if in_error:
            self.error_widget.setVisible(not collapsed)
        else:
            self.body.setVisible(not collapsed)
        self.header.collapse_btn.setText("▸" if collapsed else "▾")
        self._resize_handle.setVisible(not collapsed)
        self.apply_size()
        self.collapsed_changed.emit(self.card_id, collapsed)

    # -- drag / position --------------------------------------------------
    def move_within_container(self, pos: QPoint):
        x = max(0, min(pos.x(), self.container.width() - self.width()))
        y = max(0, min(pos.y(), self.container.height() - self.height()))
        self.move(x, y)

    def drag_finished(self):
        snapped_x = self.container.snap_to_grid(self.x())
        snapped_y = self.container.snap_to_grid(self.y())
        self.move_within_container(QPoint(snapped_x, snapped_y))
        self.moved.emit(self.card_id, self.x(), self.y())
