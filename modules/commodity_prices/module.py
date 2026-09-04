"""Commodity Prices module: best sell/buy price for a chosen commodity
across UEX-tracked terminals. Sell and buy each have their own independent
star-system filter (e.g. buy in Stanton, sell in Pyro).

Also offers "Retrieve Data" (downloads current prices for every commodity
UEX tracks) and "Find Most Profitable" (an instant, local-only search over
that retrieved data, respecting the system filters above) as two separate
actions — see docs/modules/commodity-prices.md for why they're split and
how the countdown/force-update button behaves.
"""
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QComboBox, QLabel, QHBoxLayout, QVBoxLayout, QWidget, QPushButton

from host import theme
from host.api_client import UexRateLimitError
from host.module_base import ModuleBase

ALL_SYSTEMS = "All Systems"
RETRIEVE_STEP_INTERVAL_MS = 120  # be nice to the API — ~8 requests/sec while retrieving
REFRESH_CACHE_SECONDS = 1800  # 30 min — commodity prices don't move that fast
FORCE_CONFIRM_TIMEOUT_MS = 4000  # how long "FORCE UPDATE?" stays up before reverting

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
_ACTION_BTN_STYLE = f"""
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
        self._terminal_nicknames: dict[int, str] = {}
        self.request_refresh = None  # injected by host after wrapping refresh()

        # Retrieve Data state
        self._all_commodity_data: dict[str, list[dict]] = {}
        self._retrieve_timer: QTimer | None = None
        self._retrieve_queue: list[str] = []
        self._retrieve_index = 0
        self._last_retrieve_time = 0.0
        self._countdown_timer: QTimer | None = None
        self._force_confirm_pending = False
        self._force_confirm_revert_timer: QTimer | None = None

    def create_card(self, container):
        card = container.add_card(self.module_id, self.display_name)

        self.combo = QComboBox()
        self.combo.setStyleSheet(_COMBO_STYLE)
        self.combo.setEditable(False)
        card.body_layout.addWidget(self.combo)

        self.retrieve_btn = QPushButton("RETRIEVE DATA")
        self.retrieve_btn.setStyleSheet(_ACTION_BTN_STYLE)
        self.retrieve_btn.setToolTip(
            "Downloads current prices for every commodity UEX tracks (takes "
            "~20-30s). Click again before the countdown ends to force an "
            "early refresh."
        )
        self.retrieve_btn.clicked.connect(self._on_retrieve_clicked)
        card.body_layout.addWidget(self.retrieve_btn)

        self.profitable_btn = QPushButton("FIND MOST PROFITABLE")
        self.profitable_btn.setStyleSheet(_ACTION_BTN_STYLE)
        self.profitable_btn.setToolTip(
            "Finds the biggest sell-minus-buy margin among retrieved data, "
            "respecting the system filters below. Instant — no new API "
            "calls. Retrieve Data first."
        )
        self.profitable_btn.setEnabled(False)
        self.profitable_btn.clicked.connect(self.find_most_profitable)
        card.body_layout.addWidget(self.profitable_btn)

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
        self._populate_terminal_nicknames()
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

    def _populate_terminal_nicknames(self):
        # commodities_prices only gives back "terminal_name", which is the
        # raw in-game kiosk label (e.g. "Admin - MIC-L2", or "TDD - Trade
        # and Development Division - Area 18") — not the clean name players
        # actually know a place by. The terminals endpoint's "nickname"
        # field has that ("MIC-L2", "TDD Area 18"); it doesn't come back on
        # commodities_prices itself, so fetch it once here and look terminals
        # up by id_terminal instead. Same field trade_route_optimizer's
        # origin-terminal picker already uses, for consistency.
        try:
            data = self.api.get("terminals", {"type": "commodity"})
        except Exception:
            data = []
        self._terminal_nicknames = {
            row["id"]: row.get("nickname") or row["name"] for row in data if row.get("id")
        }

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
        # UEX's commodity_name filter is a substring match, not exact --
        # querying "Diamond" also returns "Diamond Laminate" rows (a
        # different commodity that happens to contain the same substring),
        # which without this filter could get picked as the "best" price
        # for the wrong item entirely. Confirmed live: this is exactly what
        # was inflating Diamond's reported sell price 10x.
        rows = [r for r in self.api.get("commodities_prices", {"commodity_name": name})
                if r.get("commodity_name") == name]
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

    def _format_location(self, row: dict) -> str:
        place = row.get("city_name") or row.get("planet_name") or row.get("star_system_name") or ""
        terminal = self._terminal_nicknames.get(row.get("id_terminal")) or row.get("terminal_name") or ""
        return f"{terminal} · {place}" if place else terminal

    # -- Retrieve Data: downloads every commodity's prices, no math yet -----
    def _on_retrieve_clicked(self):
        if self._retrieve_timer is not None:
            return  # already retrieving — ignore extra clicks

        if self._force_confirm_pending:
            self._force_confirm_pending = False
            if self._force_confirm_revert_timer is not None:
                self._force_confirm_revert_timer.stop()
                self._force_confirm_revert_timer = None
            self._start_retrieve()
            return

        if self._countdown_timer is not None:
            # Data's still fresh — ask for confirmation instead of
            # re-fetching immediately.
            self._force_confirm_pending = True
            self.retrieve_btn.setText("FORCE UPDATE?")
            self._force_confirm_revert_timer = QTimer()
            self._force_confirm_revert_timer.setSingleShot(True)
            self._force_confirm_revert_timer.timeout.connect(self._cancel_force_confirm)
            self._force_confirm_revert_timer.start(FORCE_CONFIRM_TIMEOUT_MS)
            return

        self._start_retrieve()

    def _cancel_force_confirm(self):
        self._force_confirm_pending = False
        self._force_confirm_revert_timer = None
        self._update_countdown_label()

    def _start_retrieve(self):
        if not self._commodities:
            return
        self._stop_countdown()
        self._retrieve_queue = list(self._commodities)
        self._retrieve_index = 0
        self._all_commodity_data = {}
        self.retrieve_btn.setEnabled(False)
        self.profitable_btn.setEnabled(False)
        self.retrieve_btn.setText(f"RETRIEVING 0/{len(self._retrieve_queue)}")

        self._retrieve_timer = QTimer()
        self._retrieve_timer.timeout.connect(self._retrieve_step)
        self._retrieve_timer.start(RETRIEVE_STEP_INTERVAL_MS)

    def _retrieve_step(self):
        if self._retrieve_index >= len(self._retrieve_queue):
            self._finish_retrieve()
            return

        name = self._retrieve_queue[self._retrieve_index]
        self._retrieve_index += 1
        try:
            rows = self.api.get("commodities_prices", {"commodity_name": name})
            self._all_commodity_data[name] = [r for r in rows if r.get("commodity_name") == name]
        except UexRateLimitError as exc:
            self._retrieve_timer.stop()
            self._retrieve_timer = None
            self.retrieve_btn.setEnabled(True)
            self.retrieve_btn.setText("RETRIEVE DATA")
            self.profitable_btn.setEnabled(bool(self._all_commodity_data))
            self.card.set_error(str(exc), retry_callback=self._start_retrieve)
            return
        except Exception:
            pass  # skip commodities that individually fail; don't abort the whole retrieval

        self.retrieve_btn.setText(f"RETRIEVING {self._retrieve_index}/{len(self._retrieve_queue)}")

    def _finish_retrieve(self):
        self._retrieve_timer.stop()
        self._retrieve_timer = None
        self._last_retrieve_time = time.time()
        self.retrieve_btn.setEnabled(True)
        self.profitable_btn.setEnabled(bool(self._all_commodity_data))
        self.card.clear_error()
        self._start_countdown()

    def _start_countdown(self):
        self._countdown_timer = QTimer()
        self._countdown_timer.timeout.connect(self._update_countdown_label)
        self._countdown_timer.start(1000)
        self._update_countdown_label()

    def _update_countdown_label(self):
        if self._force_confirm_pending:
            return  # don't overwrite the "FORCE UPDATE?" prompt mid-tick
        remaining = int(REFRESH_CACHE_SECONDS - (time.time() - self._last_retrieve_time))
        if remaining <= 0:
            self._stop_countdown()
            self.retrieve_btn.setText("RETRIEVE DATA")
            return
        mins, secs = divmod(remaining, 60)
        self.retrieve_btn.setText(f"REFRESH IN {mins:02d}:{secs:02d}")

    def _stop_countdown(self):
        if self._countdown_timer is not None:
            self._countdown_timer.stop()
            self._countdown_timer = None

    # -- Find Most Profitable: instant, local, respects the system filters --
    def find_most_profitable(self):
        if not self._all_commodity_data:
            return

        sell_system = self.sell_system.currentText()
        buy_system = self.buy_system.currentText()

        results: dict[str, float] = {}
        for name, rows in self._all_commodity_data.items():
            sell_rows = [r for r in rows if r.get("price_sell", 0) > 0]
            if sell_system != ALL_SYSTEMS:
                sell_rows = [r for r in sell_rows if r.get("star_system_name") == sell_system]

            buy_rows = [r for r in rows if r.get("price_buy", 0) > 0]
            if buy_system != ALL_SYSTEMS:
                buy_rows = [r for r in buy_rows if r.get("star_system_name") == buy_system]

            if sell_rows and buy_rows:
                margin = max(r["price_sell"] for r in sell_rows) - min(r["price_buy"] for r in buy_rows)
                if margin > 0:
                    results[name] = margin

        if not results:
            filter_note = ""
            if sell_system != ALL_SYSTEMS or buy_system != ALL_SYSTEMS:
                filter_note = " with the current system filters"
            self.card.set_error(
                f"No profitable commodity found{filter_note}.",
                retry_callback=self.find_most_profitable,
            )
            return

        best = max(results, key=results.get)
        self.card.clear_error()
        self.combo.setCurrentText(best)  # triggers a normal refresh via currentTextChanged


MODULE_CLASS = CommodityPricesModule
