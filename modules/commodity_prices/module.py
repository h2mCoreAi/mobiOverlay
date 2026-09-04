"""Commodity Prices module: best sell/buy price for a chosen commodity
across UEX-tracked terminals. Sell and buy each have their own independent
star-system filter (e.g. buy in Stanton, sell in Pyro). Also offers a
"Find Most Profitable" scan across every commodity UEX tracks.
See docs/modules/commodity-prices.md for scope.
"""
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QComboBox, QLabel, QHBoxLayout, QVBoxLayout, QWidget, QPushButton

from host import theme
from host.api_client import UexRateLimitError
from host.module_base import ModuleBase

ALL_SYSTEMS = "All Systems"
SCAN_STEP_INTERVAL_MS = 120  # be nice to the API — ~8 requests/sec while scanning
SCAN_CACHE_SECONDS = 1800  # 30 min — commodity prices don't move that fast

_ROW_STYLE = f"border: 1px solid {theme.BORDER_FLAT}; padding: 9px 10px;"
_LABEL_SMALL = f'color: {theme.TEXT_MUTED}; font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(9)}px; letter-spacing: 2px;'
_PRICE_STYLE = f'font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(20)}px; font-weight: bold;'
_LOC_STYLE = f'color: {theme.TEXT_MUTED}; font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(10)}px;'
_TIMESTAMP_STYLE = f'color: {theme.TEXT_DIM}; font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(9)}px; letter-spacing: 1px;'
_COMBO_STYLE = f"""
    QComboBox {{
        background: {theme.BG_VOID}; color: {theme.ACCENT_CYAN};
        border: 1px solid {theme.BORDER_FLAT}; padding: 4px 6px;
        font-family: "{theme.FONT_DISPLAY}"; font-weight: 800; font-size: {theme.fpx(15)}px;
    }}
"""
_SYSTEM_COMBO_STYLE = f"""
    QComboBox {{
        background: {theme.BG_VOID}; color: {theme.TEXT_MUTED};
        border: 1px solid {theme.BORDER_FLAT}; padding: 2px 4px;
        font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(9)}px;
    }}
"""
_SCAN_BTN_STYLE = f"""
    QPushButton {{
        background: transparent; color: {theme.ACCENT_CYAN};
        border: 1px solid {theme.BORDER_CYAN}; padding: 5px 0;
        font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(9)}px; letter-spacing: 1px;
    }}
    QPushButton:disabled {{
        color: {theme.TEXT_DIM}; border: 1px solid {theme.BORDER_FLAT};
    }}
"""


class CommodityPricesModule(ModuleBase):
    module_id = "commodity_prices"
    display_name = "Commodity Prices"

    def __init__(self, api_client, config):
        super().__init__(api_client, config)
        self._commodities: list[str] = []
        self._last_rows: list[dict] = []
        self.request_refresh = None  # injected by host after wrapping refresh()

        # "Find Most Profitable" scan state
        self._scan_timer: QTimer | None = None
        self._scan_queue: list[str] = []
        self._scan_index = 0
        self._scan_results: dict[str, float] = {}
        self._profitable_cache: str | None = None
        self._profitable_cache_time = 0.0

    def create_card(self, container):
        card = container.add_card(self.module_id, self.display_name)

        self.combo = QComboBox()
        self.combo.setStyleSheet(_COMBO_STYLE)
        self.combo.setEditable(False)
        card.body_layout.addWidget(self.combo)

        self.scan_btn = QPushButton("FIND MOST PROFITABLE")
        self.scan_btn.setStyleSheet(_SCAN_BTN_STYLE)
        self.scan_btn.setToolTip("Scans every commodity UEX tracks for the biggest sell-minus-buy margin. Takes a bit — result is cached for 30 minutes.")
        self.scan_btn.clicked.connect(self.start_profitability_scan)
        card.body_layout.addWidget(self.scan_btn)

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
        refresh_btn.setStyleSheet(f"background: transparent; color: {theme.ACCENT_CYAN}; border: none; font-size: {theme.fpx(13)}px;")
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
        default = watched if watched in names else (names[0] if names else "")
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

        # An empty result is a legitimate state (some commodities genuinely
        # have no active listings right now), not an error — _apply_filters
        # already renders "no terminals buying/selling" gracefully per row,
        # so let it flow through instead of raising and showing a scary
        # card-level error for something that isn't actually broken.
        rows = self.api.get("commodities_prices", {"commodity_name": name})
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

    # -- Find Most Profitable: brute-force scan across every commodity ------
    def start_profitability_scan(self):
        if self._scan_timer is not None or not self._commodities:
            return

        now = time.time()
        if self._profitable_cache and now - self._profitable_cache_time < SCAN_CACHE_SECONDS:
            self.combo.setCurrentText(self._profitable_cache)
            return

        self._scan_queue = list(self._commodities)
        self._scan_index = 0
        self._scan_results = {}
        self.scan_btn.setEnabled(False)
        self.scan_btn.setText(f"SCANNING 0/{len(self._scan_queue)}")

        self._scan_timer = QTimer()
        self._scan_timer.timeout.connect(self._scan_step)
        self._scan_timer.start(SCAN_STEP_INTERVAL_MS)

    def _scan_step(self):
        if self._scan_index >= len(self._scan_queue):
            self._stop_scan()
            self._finish_scan()
            return

        name = self._scan_queue[self._scan_index]
        self._scan_index += 1
        try:
            rows = self.api.get("commodities_prices", {"commodity_name": name})
            sell_rows = [r for r in rows if r.get("price_sell", 0) > 0]
            buy_rows = [r for r in rows if r.get("price_buy", 0) > 0]
            if sell_rows and buy_rows:
                margin = max(r["price_sell"] for r in sell_rows) - min(r["price_buy"] for r in buy_rows)
                if margin > 0:
                    self._scan_results[name] = margin
        except UexRateLimitError as exc:
            self._stop_scan()
            self.card.set_error(str(exc), retry_callback=self.start_profitability_scan)
            return
        except Exception:
            pass  # skip commodities that individually fail; don't abort the whole scan

        self.scan_btn.setText(f"SCANNING {self._scan_index}/{len(self._scan_queue)}")

    def _stop_scan(self):
        if self._scan_timer is not None:
            self._scan_timer.stop()
            self._scan_timer = None
        self.scan_btn.setEnabled(True)
        self.scan_btn.setText("FIND MOST PROFITABLE")

    def _finish_scan(self):
        if not self._scan_results:
            self.card.set_error(
                "Scan found no profitable commodities right now.",
                retry_callback=self.start_profitability_scan,
            )
            return
        best = max(self._scan_results, key=self._scan_results.get)
        self._profitable_cache = best
        self._profitable_cache_time = time.time()
        self.card.clear_error()
        self.combo.setCurrentText(best)  # triggers a normal refresh via currentTextChanged


MODULE_CLASS = CommodityPricesModule
