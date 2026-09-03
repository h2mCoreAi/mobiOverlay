"""Price Lookup module: best sell/buy price for a chosen commodity across
UEX-tracked terminals. Sell and buy each have their own independent
star-system filter (e.g. buy in Stanton, sell in Pyro).
See docs/modules/price-lookup.md for scope.
"""
import time

from PySide6.QtWidgets import QComboBox, QLabel, QHBoxLayout, QVBoxLayout, QWidget, QPushButton

from host import theme
from host.module_base import ModuleBase

ALL_SYSTEMS = "All Systems"

_ROW_STYLE = f"""
    border: 1px solid {theme.BORDER_FLAT};
    padding: 9px 10px;
"""
_LABEL_SMALL = f"""
    color: {theme.TEXT_MUTED}; font-family: "{theme.FONT_MONO}";
    font-size: 9px; letter-spacing: 2px;
"""
_PRICE_STYLE = f'font-family: "{theme.FONT_MONO}"; font-size: 20px; font-weight: bold;'
_LOC_STYLE = f'color: {theme.TEXT_MUTED}; font-family: "{theme.FONT_MONO}"; font-size: 10px;'
_TIMESTAMP_STYLE = f'color: {theme.TEXT_DIM}; font-family: "{theme.FONT_MONO}"; font-size: 9px; letter-spacing: 1px;'
_COMBO_STYLE = f"""
    QComboBox {{
        background: {theme.BG_VOID}; color: {theme.ACCENT_CYAN};
        border: 1px solid {theme.BORDER_FLAT}; padding: 4px 6px;
        font-family: "{theme.FONT_DISPLAY}"; font-weight: 800; font-size: 15px;
    }}
"""
_SYSTEM_COMBO_STYLE = f"""
    QComboBox {{
        background: {theme.BG_VOID}; color: {theme.TEXT_MUTED};
        border: 1px solid {theme.BORDER_FLAT}; padding: 2px 4px;
        font-family: "{theme.FONT_MONO}"; font-size: 9px;
    }}
"""


class PriceLookupModule(ModuleBase):
    module_id = "price_lookup"
    display_name = "Price Lookup"

    def __init__(self, api_client, config):
        super().__init__(api_client, config)
        self._commodities: list[str] = []
        self._last_rows: list[dict] = []
        self.request_refresh = None  # injected by host after wrapping refresh()

    def create_card(self, container):
        card = container.add_card(self.module_id, self.display_name)

        self.combo = QComboBox()
        self.combo.setStyleSheet(_COMBO_STYLE)
        self.combo.setEditable(False)
        card.body_layout.addWidget(self.combo)

        self.sell_box, self.sell_price, self.sell_loc, self.sell_system = self._build_price_row(
            "▲ BEST SELL", theme.ACCENT_CYAN
        )
        card.body_layout.addWidget(self.sell_box)

        self.buy_box, self.buy_price, self.buy_loc, self.buy_system = self._build_price_row(
            "▼ BEST BUY", theme.TEXT_PRIMARY
        )
        card.body_layout.addWidget(self.buy_box)

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

        self._populate_commodities()
        self.combo.currentTextChanged.connect(lambda _: self.request_refresh and self.request_refresh())
        self.sell_system.currentTextChanged.connect(self._on_sell_filter_changed)
        self.buy_system.currentTextChanged.connect(self._on_buy_filter_changed)

        self.card = card
        return card

    def _build_price_row(self, label_text: str, price_color: str):
        box = QWidget()
        box.setStyleSheet(_ROW_STYLE)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)

        header = QHBoxLayout()
        header.setSpacing(6)
        label = QLabel(label_text)
        label.setStyleSheet(_LABEL_SMALL)
        header.addWidget(label)
        header.addStretch()
        system_combo = QComboBox()
        system_combo.setStyleSheet(_SYSTEM_COMBO_STYLE)
        system_combo.setFixedWidth(96)
        system_combo.addItem(ALL_SYSTEMS)
        header.addWidget(system_combo)
        layout.addLayout(header)

        price = QLabel("—")
        price.setStyleSheet(_PRICE_STYLE + f" color: {price_color};")
        layout.addWidget(price)

        loc = QLabel("")
        loc.setStyleSheet(_LOC_STYLE)
        layout.addWidget(loc)

        return box, price, loc, system_combo

    def _populate_commodities(self):
        try:
            data = self.api.get("commodities")
        except Exception:
            data = []
        names = sorted({
            row["name"] for row in data
            if row.get("is_visible") and row.get("name")
        })
        self._commodities = names
        self.combo.blockSignals(True)
        self.combo.addItems(names)
        watched = self.settings.get("watched_commodity")
        default = watched if watched in names else ("Laranite" if "Laranite" in names else (names[0] if names else ""))
        if default:
            self.combo.setCurrentText(default)
        self.combo.blockSignals(False)

    def _on_sell_filter_changed(self, _system: str):
        self.settings["sell_system_filter"] = self.sell_system.currentText()
        self.config.set_module_settings(self.module_id, self.settings)
        self._apply_filters()

    def _on_buy_filter_changed(self, _system: str):
        self.settings["buy_system_filter"] = self.buy_system.currentText()
        self.config.set_module_settings(self.module_id, self.settings)
        self._apply_filters()

    def refresh(self):
        name = self.combo.currentText()
        if not name:
            raise ValueError("No commodity selected")

        rows = self.api.get("commodities_prices", {"commodity_name": name})
        if not rows:
            raise ValueError(f"No active price data for {name}")

        self._last_rows = rows
        self._repopulate_system_filters(rows)
        self._apply_filters()

        self.timestamp_label.setText("UPDATED " + time.strftime("%H:%M:%S"))
        self.settings["watched_commodity"] = name
        self.config.set_module_settings(self.module_id, self.settings)

    def _repopulate_system_filters(self, rows: list[dict]):
        systems = sorted({r["star_system_name"] for r in rows if r.get("star_system_name")})
        for combo, setting_key in ((self.sell_system, "sell_system_filter"), (self.buy_system, "buy_system_filter")):
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(ALL_SYSTEMS)
            combo.addItems(systems)
            saved = self.settings.get(setting_key, ALL_SYSTEMS)
            combo.setCurrentText(saved if saved in systems else ALL_SYSTEMS)
            combo.blockSignals(False)

    def _apply_filters(self):
        sell_system = self.sell_system.currentText()
        buy_system = self.buy_system.currentText()

        sell_rows = [r for r in self._last_rows if r.get("price_sell", 0) > 0]
        if sell_system != ALL_SYSTEMS:
            sell_rows = [r for r in sell_rows if r.get("star_system_name") == sell_system]

        buy_rows = [r for r in self._last_rows if r.get("price_buy", 0) > 0]
        if buy_system != ALL_SYSTEMS:
            buy_rows = [r for r in buy_rows if r.get("star_system_name") == buy_system]

        if sell_rows:
            best = max(sell_rows, key=lambda r: r["price_sell"])
            self.sell_price.setText(f"{best['price_sell']:,} aUEC/SCU")
            self.sell_loc.setText(self._format_location(best))
        else:
            self.sell_price.setText("—")
            self.sell_loc.setText("no terminals buying" + ("" if sell_system == ALL_SYSTEMS else f" in {sell_system}"))

        if buy_rows:
            best = min(buy_rows, key=lambda r: r["price_buy"])
            self.buy_price.setText(f"{best['price_buy']:,} aUEC/SCU")
            self.buy_loc.setText(self._format_location(best))
        else:
            self.buy_price.setText("—")
            self.buy_loc.setText("no terminals selling" + ("" if buy_system == ALL_SYSTEMS else f" in {buy_system}"))

    @staticmethod
    def _format_location(row: dict) -> str:
        place = row.get("city_name") or row.get("planet_name") or row.get("star_system_name") or ""
        terminal = row.get("terminal_name") or ""
        return f"{terminal} · {place}" if place else terminal


MODULE_CLASS = PriceLookupModule
