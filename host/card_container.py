"""Free-form canvas that owns Card widgets: positions them, persists layout
to config, tracks which cards are stowed (hidden) so the tray can deploy
them again, and shows the purple grid-snap preview while a card is dragged.
"""
from PySide6.QtCore import Qt, QEvent, Signal
from PySide6.QtWidgets import QApplication, QWidget, QFrame

from host import theme
from host.card import Card, CARD_WIDTH
from host.config import Config

_GRID_GAP_X = 26
_COLUMNS = 2


class CardContainer(QWidget):
    visibility_changed = Signal()  # a card was stowed or deployed

    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self.config = config
        self.cards: dict[str, Card] = {}
        self._registration_order: list[str] = []
        self._stowed: set[str] = set()  # tracked ourselves — Card.isVisible()
        # is unreliable before the top-level window itself has been shown
        # (Qt visibility depends on ancestor visibility too)
        self._card_opacity = config.data["ui"]["card_opacity"]

        self.snap_overlay = QFrame(self)
        self.snap_overlay.setStyleSheet(
            f"background: {theme.SNAP_FILL}; border: 1px solid {theme.SNAP_BORDER};"
        )
        self.snap_overlay.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.snap_overlay.hide()

        # App-wide filter so clicking ANYWHERE inside a card (not just its
        # header) raises it — a click on a child widget (combo box, button,
        # label) never bubbles up to the Card's own mousePressEvent, so
        # watching at the application level is the reliable way to catch it.
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress:
            card = self._card_ancestor_of(obj)
            if card is not None:
                card.raise_()
        return super().eventFilter(obj, event)

    def _card_ancestor_of(self, obj) -> Card | None:
        widget = obj if isinstance(obj, QWidget) else None
        while widget is not None:
            if isinstance(widget, Card):
                return widget if widget.parentWidget() is self else None
            widget = widget.parentWidget()
        return None

    def add_card(self, card_id: str, title: str) -> Card:
        card = Card(card_id, title, self)
        card.set_card_opacity(self._card_opacity)
        card.moved.connect(self._on_card_moved)
        card.resized.connect(self._on_card_resized)
        card.collapsed_changed.connect(self._on_card_collapsed_changed)
        card.stowed.connect(self.stow_card)

        state = self.config.card_state(card_id)
        if card_id not in self._registration_order:
            self._registration_order.append(card_id)
        has_saved_position = card_id in self.config.data["cards"] and (
            state.get("x", 0) or state.get("y", 0)
        )
        if has_saved_position:
            card.move(state["x"], state["y"])
        else:
            self._auto_place(card)

        if state.get("width") and state.get("height"):
            card.set_manual_size(state["width"], state["height"])

        card.set_collapsed(state.get("collapsed", False))
        initially_visible = state.get("visible", True)
        card.setVisible(initially_visible)
        card.show()
        self.cards[card_id] = card
        if not initially_visible:
            self._stowed.add(card_id)
        self.visibility_changed.emit()
        return card

    def _auto_place(self, card: Card):
        index = len(self._registration_order) - 1
        col = index % _COLUMNS
        row = index // _COLUMNS
        x = col * (CARD_WIDTH + _GRID_GAP_X)
        y = row * 220  # rough vertical rhythm; cards resize to content
        card.move(x, y)
        self.config.set_card_state(card.card_id, x=x, y=y)

    def stow_card(self, card_id: str):
        if card_id in self.cards:
            self.cards[card_id].setVisible(False)
            self.config.set_card_state(card_id, visible=False)
            self._stowed.add(card_id)
            self.visibility_changed.emit()

    def deploy_card(self, card_id: str):
        if card_id in self.cards:
            self.cards[card_id].setVisible(True)
            self.config.set_card_state(card_id, visible=True)
            self._stowed.discard(card_id)
            self.visibility_changed.emit()

    def is_visible(self, card_id: str) -> bool:
        return card_id in self.cards and card_id not in self._stowed

    def stowed_cards(self) -> list[tuple[str, str]]:
        """(card_id, title) pairs for every currently-stowed card."""
        return [
            (card_id, card.header.title_label.text())
            for card_id, card in self.cards.items()
            if card_id in self._stowed
        ]

    def _on_card_moved(self, card_id: str, x: int, y: int):
        self.config.set_card_state(card_id, x=x, y=y)

    def _on_card_resized(self, card_id: str, w: int, h: int):
        self.config.set_card_state(card_id, width=w, height=h)

    def _on_card_collapsed_changed(self, card_id: str, collapsed: bool):
        self.config.set_card_state(card_id, collapsed=collapsed)

    # -- grid snap (drag preview) --------------------------------------------
    @staticmethod
    def snap_to_grid(value: int) -> int:
        return round(value / theme.GRID_SIZE) * theme.GRID_SIZE

    def show_snap_preview(self, x: int, y: int, w: int, h: int):
        self.snap_overlay.setGeometry(x, y, w, h)
        self.snap_overlay.show()
        self.snap_overlay.raise_()

    def hide_snap_preview(self):
        self.snap_overlay.hide()

    # -- card opacity (independent of window opacity) -----------------------
    def set_all_card_opacity(self, opacity: float):
        self._card_opacity = opacity
        for card in self.cards.values():
            card.set_card_opacity(opacity)
