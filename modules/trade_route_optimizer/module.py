"""Trade Route Optimizer module: most profitable known trade routes from a
chosen origin terminal, using UEX's pre-computed commodities_routes data.
See docs/modules/trade-route-optimizer.md for scope.
"""
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QComboBox, QLabel, QHBoxLayout, QVBoxLayout, QWidget, QPushButton, QLineEdit
)

from host import theme
from host.module_base import ModuleBase

TOP_N_ROUTES = 5

_COMBO_STYLE = f"""
    QComboBox {{
        background: {theme.BG_VOID}; color: {theme.ACCENT_CYAN};
        border: 1px solid {theme.BORDER_FLAT}; padding: 4px 6px;
        font-family: "{theme.FONT_DISPLAY}"; font-weight: 700; font-size: 12px;
    }}
"""
_INVESTMENT_STYLE = f"""
    QLineEdit {{
        background: {theme.BG_VOID}; color: {theme.TEXT_PRIMARY};
        border: 1px solid {theme.BORDER_FLAT}; padding: 4px 6px;
        font-family: "{theme.FONT_MONO}"; font-size: 11px;
    }}
"""
_ROUTE_ROW_STYLE = f"border: 1px solid {theme.BORDER_FLAT}; padding: 7px 9px;"
_COMMODITY_STYLE = f'color: {theme.ACCENT_CYAN}; font-family: "{theme.FONT_DISPLAY}"; font-weight: 800; font-size: 13px;'
_DEST_STYLE = f'color: {theme.TEXT_MUTED}; font-family: "{theme.FONT_MONO}"; font-size: 9px;'
_PROFIT_STYLE = f'color: {theme.TEXT_PRIMARY}; font-family: "{theme.FONT_MONO}"; font-size: 14px; font-weight: bold;'
_ROI_STYLE = f'color: {theme.TEXT_MUTED}; font-family: "{theme.FONT_MONO}"; font-size: 9px;'
_TIMESTAMP_STYLE = f'color: {theme.TEXT_DIM}; font-family: "{theme.FONT_MONO}"; font-size: 9px; letter-spacing: 1px;'
_LABEL_SMALL = f'color: {theme.TEXT_MUTED}; font-family: "{theme.FONT_MONO}"; font-size: 9px; letter-spacing: 1px;'


class TradeRouteOptimizerModule(ModuleBase):
    module_id = "trade_route_optimizer"
    display_name = "Trade Routes"

    def __init__(self, api_client, config):
        super().__init__(api_client, config)
        self._systems: dict[str, int] = {}  # name -> id, available systems only
        self._terminals: dict[str, int] = {}  # name -> id, scoped to current system
        self.request_refresh = None  # injected by host after wrapping refresh()

    def create_card(self, container):
        card = container.add_card(self.module_id, self.display_name)

        picker_row = QHBoxLayout()
        self.system_combo = QComboBox()
        self.system_combo.setStyleSheet(_COMBO_STYLE)
        picker_row.addWidget(self.system_combo, 1)

        self.terminal_combo = QComboBox()
        self.terminal_combo.setStyleSheet(_COMBO_STYLE)
        picker_row.addWidget(self.terminal_combo, 2)
        card.body_layout.addLayout(picker_row)

        investment_row = QHBoxLayout()
        investment_label = QLabel("MAX INVESTMENT")
        investment_label.setStyleSheet(_LABEL_SMALL)
        investment_row.addWidget(investment_label)
        self.investment_input = QLineEdit()
        self.investment_input.setPlaceholderText("unlimited")
        self.investment_input.setValidator(QIntValidator(0, 999_999_999))
        self.investment_input.setStyleSheet(_INVESTMENT_STYLE)
        self.investment_input.setFixedWidth(100)
        investment_row.addWidget(self.investment_input)
        investment_row.addStretch()
        card.body_layout.addLayout(investment_row)

        self._route_rows = []
        for _ in range(TOP_N_ROUTES):
            row_widgets = self._build_route_row()
            card.body_layout.addWidget(row_widgets[0])
            self._route_rows.append(row_widgets)

        footer = QHBoxLayout()
        self.timestamp_label = QLabel("NO DATA YET")
        self.timestamp_label.setStyleSheet(_TIMESTAMP_STYLE)
        footer.addWidget(self.timestamp_label)
        footer.addStretch()
        refresh_btn = QPushButton("↻")
        refresh_btn.setFixedSize(20, 20)
        refresh_btn.setStyleSheet(f"background: transparent; color: {theme.ACCENT_CYAN}; border: none; font-size: 13px;")
        refresh_btn.clicked.connect(lambda: self.request_refresh and self.request_refresh())
        footer.addWidget(refresh_btn)
        card.body_layout.addLayout(footer)

        self._populate_systems()
        self.system_combo.currentTextChanged.connect(self._on_system_changed)
        self.terminal_combo.currentTextChanged.connect(lambda _: self.request_refresh and self.request_refresh())
        self.investment_input.editingFinished.connect(lambda: self.request_refresh and self.request_refresh())

        self.card = card
        return card

    def _build_route_row(self):
        box = QWidget()
        box.setStyleSheet(_ROUTE_ROW_STYLE)
        layout = QHBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)

        left = QVBoxLayout()
        left.setSpacing(2)
        commodity = QLabel("—")
        commodity.setStyleSheet(_COMMODITY_STYLE)
        left.addWidget(commodity)
        dest = QLabel("")
        dest.setStyleSheet(_DEST_STYLE)
        dest.setWordWrap(True)
        left.addWidget(dest)
        layout.addLayout(left, 1)

        right = QVBoxLayout()
        right.setSpacing(2)
        right.setAlignment(Qt.AlignRight)
        profit = QLabel("")
        profit.setStyleSheet(_PROFIT_STYLE)
        profit.setAlignment(Qt.AlignRight)
        right.addWidget(profit)
        roi = QLabel("")
        roi.setStyleSheet(_ROI_STYLE)
        roi.setAlignment(Qt.AlignRight)
        right.addWidget(roi)
        layout.addLayout(right)

        return box, commodity, dest, profit, roi

    def _populate_systems(self):
        try:
            data = self.api.get("star_systems")
        except Exception:
            data = []
        self._systems = {
            row["name"]: row["id"] for row in data if row.get("is_available") and row.get("name")
        }
        names = sorted(self._systems.keys())
        self.system_combo.blockSignals(True)
        self.system_combo.addItems(names)
        saved = self.settings.get("origin_system")
        default = saved if saved in names else ("Stanton" if "Stanton" in names else (names[0] if names else ""))
        if default:
            self.system_combo.setCurrentText(default)
        self.system_combo.blockSignals(False)
        self._populate_terminals(default)

    def _on_system_changed(self, system_name: str):
        self.settings["origin_system"] = system_name
        self.config.set_module_settings(self.module_id, self.settings)
        self._populate_terminals(system_name)

    def _populate_terminals(self, system_name: str):
        system_id = self._systems.get(system_name)
        if system_id is None:
            return
        try:
            data = self.api.get("terminals", {"id_star_system": system_id, "type": "commodity"})
        except Exception:
            data = []
        terminals = {
            row["name"]: row["id"] for row in data
            if row.get("is_available_live") and row.get("name")
        }
        names = sorted(terminals.keys())
        self._terminals = terminals

        self.terminal_combo.blockSignals(True)
        self.terminal_combo.clear()
        self.terminal_combo.addItems(names)
        saved = self.settings.get("origin_terminal")
        if saved in names:
            self.terminal_combo.setCurrentText(saved)
        self.terminal_combo.blockSignals(False)

        if self.request_refresh:
            self.request_refresh()

    def refresh(self):
        terminal_name = self.terminal_combo.currentText()
        if not terminal_name:
            raise ValueError("No origin terminal selected")
        terminal_id = self._terminals.get(terminal_name)
        if terminal_id is None:
            raise ValueError(f"Unknown terminal: {terminal_name}")

        params = {"id_terminal_origin": terminal_id}
        investment_text = self.investment_input.text().strip()
        if investment_text:
            params["investment"] = investment_text

        rows = self.api.get("commodities_routes", params)
        if not rows:
            raise ValueError(f"No profitable routes found from {terminal_name}")

        rows.sort(key=lambda r: r.get("profit", 0), reverse=True)
        top_routes = rows[:TOP_N_ROUTES]

        # Rows always stay visible (even with placeholder text) rather than
        # being hidden when there are fewer than TOP_N_ROUTES results — the
        # card's outer size isn't recomputed on every refresh (only on
        # population/collapse/error), so hiding rows would leave stale
        # blank space instead of actually shrinking the card.
        for i, (box, commodity_label, dest_label, profit_label, roi_label) in enumerate(self._route_rows):
            if i < len(top_routes):
                r = top_routes[i]
                commodity_label.setText(r.get("commodity_name", "—"))
                dest_place = r.get("destination_planet_name") or r.get("destination_star_system_name") or ""
                dest_label.setText(f"→ {r.get('destination_terminal_name', '')} · {dest_place}")
                profit_label.setText(f"{r.get('profit', 0):,} aUEC")
                roi_label.setText(f"{r.get('price_roi', 0):.1f}% ROI")
            else:
                commodity_label.setText("—")
                dest_label.setText("no route available")
                profit_label.setText("")
                roi_label.setText("")

        self.timestamp_label.setText("UPDATED " + time.strftime("%H:%M:%S"))
        self.settings["origin_terminal"] = terminal_name
        self.settings["investment_budget"] = investment_text
        self.config.set_module_settings(self.module_id, self.settings)


MODULE_CLASS = TradeRouteOptimizerModule
