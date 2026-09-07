"""Trade Route Optimizer module: most profitable known trade routes from a
chosen origin terminal, using UEX's pre-computed commodities_routes data.
See docs/modules/trade-route-optimizer.md for scope.
"""
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QComboBox, QCompleter, QLabel, QHBoxLayout, QVBoxLayout, QWidget,
    QPushButton, QLineEdit
)

from host import theme
from host.api_client import UexRateLimitError
from host.locations import LocationService
from host.module_base import ModuleBase

TOP_N_ROUTES = 5
ALL_SYSTEMS = "All Systems"
ANY_LOCATION = "— Any Location —"
SCAN_STEP_INTERVAL_MS = 120  # be nice to the API — ~8 requests/sec while scanning
SCAN_CACHE_SECONDS = 1800  # 30 min, same as Commodity Prices' Retrieve Data
FORCE_CONFIRM_TIMEOUT_MS = 4000

_COMBO_STYLE = f"""
    QComboBox {{
        background: {theme.BG_VOID}; color: {theme.ACCENT_CYAN};
        border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px; padding: 4px 22px 4px 6px;
        font-family: "{theme.FONT_DISPLAY}"; font-weight: 700; font-size: {theme.fpx(12)}px;
    }}
    QComboBox::drop-down {{
        width: 18px; border: none;
    }}
"""
_FILTER_COMBO_STYLE = f"""
    QComboBox {{
        background: {theme.BG_VOID}; color: {theme.TEXT_MUTED};
        border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px; padding: 2px 18px 2px 4px;
        font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(9)}px;
    }}
    QComboBox::drop-down {{
        width: 16px; border: none;
    }}
"""
_INVESTMENT_STYLE = f"""
    QLineEdit {{
        background: {theme.BG_VOID}; color: {theme.TEXT_PRIMARY};
        border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px; padding: 4px 6px;
        font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(11)}px;
    }}
"""
_ROUTE_ROW_STYLE = f"border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px; padding: 7px 9px;"
_COMMODITY_STYLE = f'color: {theme.ACCENT_CYAN}; font-family: "{theme.FONT_DISPLAY}"; font-weight: 800; font-size: {theme.fpx(13)}px;'
_DEST_STYLE = f'color: {theme.TEXT_MUTED}; font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(9)}px;'
_PROFIT_STYLE = f'color: {theme.TEXT_PRIMARY}; font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(14)}px; font-weight: bold;'
_ROI_STYLE = f'color: {theme.TEXT_MUTED}; font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(9)}px;'
_TIMESTAMP_STYLE = f'color: {theme.TEXT_DIM}; font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(9)}px; letter-spacing: 1px;'
_LABEL_SMALL = f'color: {theme.TEXT_MUTED}; font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(9)}px; letter-spacing: 1px;'
_ACTION_BTN_STYLE = f"""
    QPushButton {{
        background: transparent; color: {theme.ACCENT_CYAN};
        border: 1px solid {theme.BORDER_CYAN}; border-radius: {theme.RADIUS}px; padding: 5px 0;
        font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(9)}px; letter-spacing: 1px;
    }}
    QPushButton:disabled {{
        color: {theme.TEXT_DIM}; border: 1px solid {theme.BORDER_FLAT};
    }}
"""


class TradeRouteOptimizerModule(ModuleBase):
    module_id = "trade_route_optimizer"
    # Rich-text mobi-branding, same pattern as Logistics Hub's
    # display_name (host/card.py's title_label no longer forces
    # uppercase, so this mixed case survives intact).
    display_name = (
        f'<span style="color:{theme.TEXT_PRIMARY};">mobi</span>'
        f'<span style="color:{theme.ACCENT_CYAN};">Trade</span>'
    )

    def __init__(self, api_client, config):
        super().__init__(api_client, config)
        self._locations = LocationService(api_client)
        self._origin_choices: dict[str, dict] = {}  # search_label -> terminal row
        self._last_rows: list[dict] = []
        self.request_refresh = None  # injected by host after wrapping refresh()

        # Scan state (Any Location / BUY IN system mode — see refresh() and
        # _start_scan()). Mirrors Commodity Prices' Retrieve Data state.
        self._scan_timer: QTimer | None = None
        self._scan_queue: list[dict] = []
        self._scan_index = 0
        self._scan_rows: list[dict] = []
        self._last_scan_time = 0.0
        self._countdown_timer: QTimer | None = None
        self._force_confirm_pending = False
        self._force_confirm_revert_timer: QTimer | None = None

    def create_card(self, container):
        card = container.add_card(self.module_id, self.display_name)

        buy_label = QLabel("▲ BUY HERE")
        buy_label.setStyleSheet(_LABEL_SMALL)
        card.body_layout.addWidget(buy_label)

        picker_row = QHBoxLayout()
        self.origin_combo = QComboBox()
        self.origin_combo.setStyleSheet(_COMBO_STYLE)
        # Single searchable combo across every system's terminals at once —
        # same editable-combo-with-completer pattern as Logistics Hub's
        # CURRENT LOCATION picker (modules/logistics_hub/module.py), instead
        # of the old system-then-terminal cascade. Type to narrow (100+
        # terminals total), or just open the dropdown and scroll. Also
        # includes the ANY_LOCATION sentinel — a real terminal is no longer
        # required (see BUY IN filter + SCAN button below).
        self.origin_combo.setEditable(True)
        self.origin_combo.setInsertPolicy(QComboBox.NoInsert)
        origin_completer = QCompleter(self.origin_combo.model(), self.origin_combo)
        origin_completer.setCaseSensitivity(Qt.CaseInsensitive)
        origin_completer.setFilterMode(Qt.MatchContains)
        origin_completer.setCompletionMode(QCompleter.PopupCompletion)
        self.origin_combo.setCompleter(origin_completer)
        picker_row.addWidget(self.origin_combo, 1)
        card.body_layout.addLayout(picker_row)

        buy_in_row = QHBoxLayout()
        buy_in_label = QLabel("BUY IN")
        buy_in_label.setStyleSheet(_LABEL_SMALL)
        buy_in_row.addWidget(buy_in_label)
        self.buy_system_combo = QComboBox()
        self.buy_system_combo.setStyleSheet(_FILTER_COMBO_STYLE)
        self.buy_system_combo.setFixedWidth(96)
        self.buy_system_combo.addItem(ALL_SYSTEMS)
        buy_in_row.addWidget(self.buy_system_combo)
        buy_in_row.addStretch()
        card.body_layout.addLayout(buy_in_row)

        self.scan_btn = QPushButton("SCAN")
        self.scan_btn.setStyleSheet(_ACTION_BTN_STYLE)
        self.scan_btn.clicked.connect(self._on_scan_clicked)
        card.body_layout.addWidget(self.scan_btn)

        filters_row = QHBoxLayout()
        investment_label = QLabel("MAX INVESTMENT")
        investment_label.setStyleSheet(_LABEL_SMALL)
        filters_row.addWidget(investment_label)
        self.investment_input = QLineEdit()
        self.investment_input.setPlaceholderText("unlimited")
        self.investment_input.setValidator(QIntValidator(0, 999_999_999))
        self.investment_input.setStyleSheet(_INVESTMENT_STYLE)
        self.investment_input.setFixedWidth(100)
        filters_row.addWidget(self.investment_input)
        filters_row.addStretch()
        sell_in_label = QLabel("SELL IN")
        sell_in_label.setStyleSheet(_LABEL_SMALL)
        filters_row.addWidget(sell_in_label)
        self.dest_system_combo = QComboBox()
        self.dest_system_combo.setStyleSheet(_FILTER_COMBO_STYLE)
        self.dest_system_combo.setFixedWidth(96)
        self.dest_system_combo.addItem(ALL_SYSTEMS)
        filters_row.addWidget(self.dest_system_combo)
        card.body_layout.addLayout(filters_row)

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
        refresh_btn.setStyleSheet(f"background: transparent; color: {theme.ACCENT_CYAN}; border: none; font-size: {theme.fpx(13)}px;")
        refresh_btn.clicked.connect(lambda: self.request_refresh and self.request_refresh())
        footer.addWidget(refresh_btn)
        card.body_layout.addLayout(footer)

        self._populate_buy_system_combo()
        self._populate_origin_combo()
        self._update_origin_mode()
        # textActivated (not currentTextChanged): the origin combo is
        # editable, so currentTextChanged fires on every keystroke — that
        # would trigger a refresh (and an "unknown terminal" error) on each
        # partial character typed. textActivated only fires once a
        # selection is actually committed (click, Enter, completer pick).
        self.origin_combo.textActivated.connect(self._on_origin_selected)
        self.investment_input.editingFinished.connect(self._on_investment_changed)
        self.dest_system_combo.currentTextChanged.connect(self._on_dest_filter_changed)
        self.buy_system_combo.currentTextChanged.connect(self._on_buy_system_filter_changed)

        self.card = card
        return card

    def _build_route_row(self):
        box = QWidget()
        box.setStyleSheet(_ROUTE_ROW_STYLE)
        layout = QHBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)

        left = QVBoxLayout()
        left.setSpacing(2)
        buy_at = QLabel("")
        buy_at.setStyleSheet(_DEST_STYLE)
        buy_at.setWordWrap(True)
        left.addWidget(buy_at)
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

        return box, buy_at, commodity, dest, profit, roi

    def _candidate_terminals(self, system_name: str | None = None) -> list[dict]:
        """Live, tradeable commodity terminals — optionally scoped to one
        system. Shared by the origin combo (all systems) and the SCAN
        button's terminal queue (optionally narrowed by BUY IN)."""
        rows = [
            row for row in self._locations.all_locations()
            if row.get("_endpoint") == "terminals"
            and row.get("type") == "commodity"
            and row.get("is_available_live")
            and row.get("id") is not None
        ]
        if system_name and system_name != ALL_SYSTEMS:
            rows = [row for row in rows if row.get("star_system_name") == system_name]
        return rows

    def _populate_buy_system_combo(self):
        systems = self._locations.available_systems()
        names = sorted({row["name"] for row in systems if row.get("name")})
        self.buy_system_combo.blockSignals(True)
        self.buy_system_combo.clear()
        self.buy_system_combo.addItem(ALL_SYSTEMS)
        self.buy_system_combo.addItems(names)
        saved = self.settings.get("buy_system_filter", ALL_SYSTEMS)
        self.buy_system_combo.setCurrentText(saved if saved in names else ALL_SYSTEMS)
        self.buy_system_combo.blockSignals(False)

    def _populate_origin_combo(self):
        """Fill the origin picker from every available system's commodity
        terminals at once — same predicate the old cascading picker used
        per-system, just not scoped to one. Labeled via
        LocationService.friendly_label() (name + short code together) so
        searching by either works, same as Logistics Hub's location combo.
        Only terminals: commodities_routes (refresh()) requires a real
        id_terminal_origin, which space stations/outposts/cities can't
        provide. ANY_LOCATION sentinel first — origin no longer required,
        see refresh()/the SCAN button for what "no origin" means."""
        rows = self._candidate_terminals()
        self._origin_choices = {}
        for row in rows:
            label = self._locations.friendly_label(row)
            if label in self._origin_choices and self._origin_choices[label] is not row:
                system = row.get("star_system_name")
                if system:
                    label = f"{label} [{system}]"
            self._origin_choices[label] = row
        names = [ANY_LOCATION] + sorted(self._origin_choices.keys())

        self.origin_combo.blockSignals(True)
        self.origin_combo.clear()
        self.origin_combo.addItems(names)
        saved = self.settings.get("origin_terminal_name", ANY_LOCATION)
        self.origin_combo.setCurrentText(saved if saved in names else ANY_LOCATION)
        self.origin_combo.blockSignals(False)

        if self.request_refresh:
            self.request_refresh()

    def _on_origin_selected(self, origin_name: str):
        self.settings["origin_terminal_name"] = origin_name
        self.config.set_module_settings(self.module_id, self.settings)
        self._update_origin_mode()
        if origin_name == ANY_LOCATION:
            # refresh() no-ops in this mode — any rows still on screen are
            # leftover from whatever mode was active before, not this
            # scope. Require a fresh SCAN rather than leave old data up.
            self._invalidate_scan_results()
        elif self.request_refresh:
            self.request_refresh()

    def _update_origin_mode(self):
        """BUY IN only means anything when no specific terminal is picked —
        disable it (rather than silently ignore it) once a real terminal is
        selected, so the filter's irrelevance is visible, not confusing.
        Also keeps the SCAN button's label/visibility in sync."""
        any_location = self.origin_combo.currentText() == ANY_LOCATION
        self.buy_system_combo.setEnabled(any_location)
        self.scan_btn.setVisible(any_location)
        self._update_scan_button_label()

    def _on_buy_system_filter_changed(self, _system: str):
        self.settings["buy_system_filter"] = self.buy_system_combo.currentText()
        self.config.set_module_settings(self.module_id, self.settings)
        # Narrowing/widening BUY IN changes which terminals a fresh SCAN
        # would even query — any currently-shown rows may no longer match
        # the selected scope, so invalidate rather than leave them looking
        # current.
        self._invalidate_scan_results()
        self._update_scan_button_label()

    def _on_investment_changed(self):
        if self.origin_combo.currentText() == ANY_LOCATION:
            # A changed budget changes what commodities_routes itself
            # would return per terminal (it's a server-side cap, not a
            # client-side filter) — a stale scan's numbers would silently
            # no longer reflect the field on screen, which is exactly the
            # confusing case a user hit live (a large old-uncapped profit
            # sitting next to a small typed-in budget). Invalidate rather
            # than leave it looking current; a fresh SCAN click is required.
            self._invalidate_scan_results()
        elif self.request_refresh:
            self.request_refresh()

    def _invalidate_scan_results(self):
        if not self._last_rows and not self._scan_rows:
            return  # nothing shown yet — nothing to invalidate
        self._stop_countdown()
        self._force_confirm_pending = False
        if self._force_confirm_revert_timer is not None:
            self._force_confirm_revert_timer.stop()
            self._force_confirm_revert_timer = None
        self._last_rows = []
        self._scan_rows = []
        self._apply_dest_filter()
        self.timestamp_label.setText("RESCAN NEEDED")
        self._update_scan_button_label()

    def _update_scan_button_label(self):
        if self._scan_timer is not None or self._force_confirm_pending:
            return  # don't stomp on live progress / the force-confirm prompt
        system = self.buy_system_combo.currentText()
        count = len(self._candidate_terminals(system))
        if system == ALL_SYSTEMS:
            self.scan_btn.setText(f"SCAN {count} TERMINALS")
        else:
            self.scan_btn.setText(f"SCAN {count} TERMINALS ({system.upper()})")

    def _on_dest_filter_changed(self, _system: str):
        self.settings["dest_system_filter"] = self.dest_system_combo.currentText()
        self.config.set_module_settings(self.module_id, self.settings)
        self._apply_dest_filter()

    def refresh(self):
        origin_name = self.origin_combo.currentText()
        if origin_name == ANY_LOCATION:
            # Any Location has no single fast call to make — results only
            # ever come from an explicit SCAN (see _start_scan()). No-op
            # rather than raise, so auto-refresh/startup don't error every
            # tick while in this mode.
            return
        terminal = self._origin_choices.get(origin_name)
        if terminal is None:
            raise ValueError(f"Unknown terminal: {origin_name}")

        params = {"id_terminal_origin": terminal["id"]}
        investment_text = self.investment_input.text().strip()
        if investment_text:
            params["investment"] = investment_text

        rows = self.api.get("commodities_routes", params)
        if not rows:
            raise ValueError(f"No profitable routes found from {origin_name}")

        self._last_rows = rows
        self._repopulate_dest_filter(rows)
        self._apply_dest_filter()

        self.timestamp_label.setText("UPDATED " + time.strftime("%H:%M:%S"))
        self.settings["investment_budget"] = investment_text
        self.config.set_module_settings(self.module_id, self.settings)

    # -- SCAN (Any Location / BUY IN system mode): multi-terminal, manual,
    # throttled — commodities_routes has no bulk-origin query (confirmed
    # live: id_star_system_origin alone returns missing_one_required_inputs),
    # so this calls it once per candidate terminal. Same shape as Commodity
    # Prices' Retrieve Data (_start_retrieve/_retrieve_step/_finish_retrieve).
    def _on_scan_clicked(self):
        if self._scan_timer is not None:
            return  # already scanning — ignore extra clicks

        if self._force_confirm_pending:
            self._force_confirm_pending = False
            if self._force_confirm_revert_timer is not None:
                self._force_confirm_revert_timer.stop()
                self._force_confirm_revert_timer = None
            self._start_scan()
            return

        if self._countdown_timer is not None:
            self._force_confirm_pending = True
            self.scan_btn.setText("FORCE UPDATE?")
            self._force_confirm_revert_timer = QTimer()
            self._force_confirm_revert_timer.setSingleShot(True)
            self._force_confirm_revert_timer.timeout.connect(self._cancel_force_confirm)
            self._force_confirm_revert_timer.start(FORCE_CONFIRM_TIMEOUT_MS)
            return

        self._start_scan()

    def _cancel_force_confirm(self):
        self._force_confirm_pending = False
        self._force_confirm_revert_timer = None
        self._update_countdown_label()

    def _start_scan(self):
        self._stop_countdown()
        self._scan_queue = self._candidate_terminals(self.buy_system_combo.currentText())
        if not self._scan_queue:
            return
        self._scan_index = 0
        self._scan_rows = []
        self.scan_btn.setEnabled(False)
        self.scan_btn.setText(f"SCANNING 0/{len(self._scan_queue)}")

        self._scan_timer = QTimer()
        self._scan_timer.timeout.connect(self._scan_step)
        self._scan_timer.start(SCAN_STEP_INTERVAL_MS)

    def _scan_step(self):
        if self._scan_index >= len(self._scan_queue):
            self._finish_scan()
            return

        terminal = self._scan_queue[self._scan_index]
        self._scan_index += 1
        params = {"id_terminal_origin": terminal["id"]}
        investment_text = self.investment_input.text().strip()
        if investment_text:
            params["investment"] = investment_text

        try:
            rows = self.api.get("commodities_routes", params)
            self._scan_rows.extend(rows)
        except UexRateLimitError as exc:
            self._scan_timer.stop()
            self._scan_timer = None
            self.scan_btn.setEnabled(True)
            self._update_scan_button_label()
            self.card.set_error(str(exc), retry_callback=self._start_scan)
            return
        except Exception:
            pass  # skip terminals that individually fail; don't abort the whole scan

        self.scan_btn.setText(f"SCANNING {self._scan_index}/{len(self._scan_queue)}")

    def _finish_scan(self):
        self._scan_timer.stop()
        self._scan_timer = None
        self._last_scan_time = time.time()
        self.scan_btn.setEnabled(True)

        self._last_rows = self._scan_rows
        self._repopulate_dest_filter(self._last_rows)
        self._apply_dest_filter()
        self.timestamp_label.setText("UPDATED " + time.strftime("%H:%M:%S"))
        self.card.clear_error()

        investment_text = self.investment_input.text().strip()
        self.settings["investment_budget"] = investment_text
        self.config.set_module_settings(self.module_id, self.settings)

        self._start_countdown()

    def _stop_countdown(self):
        if self._countdown_timer is not None:
            self._countdown_timer.stop()
            self._countdown_timer = None

    def _start_countdown(self):
        self._countdown_timer = QTimer()
        self._countdown_timer.timeout.connect(self._update_countdown_label)
        self._countdown_timer.start(1000)
        self._update_countdown_label()

    def _update_countdown_label(self):
        if self._force_confirm_pending:
            return
        remaining = int(SCAN_CACHE_SECONDS - (time.time() - self._last_scan_time))
        if remaining <= 0:
            self._stop_countdown()
            self._update_scan_button_label()
            return
        mins, secs = divmod(remaining, 60)
        self.scan_btn.setText(f"REFRESH IN {mins:02d}:{secs:02d}")

    def _repopulate_dest_filter(self, rows: list[dict]):
        systems = sorted({r["destination_star_system_name"] for r in rows if r.get("destination_star_system_name")})
        self.dest_system_combo.blockSignals(True)
        self.dest_system_combo.clear()
        self.dest_system_combo.addItem(ALL_SYSTEMS)
        self.dest_system_combo.addItems(systems)
        saved = self.settings.get("dest_system_filter", ALL_SYSTEMS)
        self.dest_system_combo.setCurrentText(saved if saved in systems else ALL_SYSTEMS)
        self.dest_system_combo.blockSignals(False)

    def _apply_dest_filter(self):
        dest_system = self.dest_system_combo.currentText()
        rows = self._last_rows
        if dest_system != ALL_SYSTEMS:
            rows = [r for r in rows if r.get("destination_star_system_name") == dest_system]

        rows = sorted(rows, key=lambda r: r.get("profit", 0), reverse=True)
        top_routes = rows[:TOP_N_ROUTES]

        # Rows always stay visible (even with placeholder text) rather than
        # being hidden when there are fewer than TOP_N_ROUTES results — the
        # card's outer size isn't recomputed on every refresh (only on
        # population/collapse/error), so hiding rows would leave stale
        # blank space instead of actually shrinking the card.
        for i, (box, buy_at_label, commodity_label, dest_label, profit_label, roi_label) in enumerate(self._route_rows):
            if i < len(top_routes):
                r = top_routes[i]
                origin_place = r.get("origin_planet_name") or r.get("origin_star_system_name") or ""
                origin_name = self._strip_admin_prefix(r.get("origin_terminal_name", ""))
                buy_at_label.setText(f"BUY AT {origin_name} · {origin_place}")
                commodity_label.setText(r.get("commodity_name", "—"))
                dest_place = r.get("destination_planet_name") or r.get("destination_star_system_name") or ""
                dest_name = self._strip_admin_prefix(r.get("destination_terminal_name", ""))
                dest_label.setText(f"SELL AT {dest_name} · {dest_place}")
                profit_label.setText(f"{r.get('profit', 0):,} aUEC")
                roi_label.setText(f"{r.get('price_roi', 0):.1f}% ROI")
            else:
                buy_at_label.setText("")
                commodity_label.setText("—")
                dest_label.setText(
                    "no route available" if dest_system == ALL_SYSTEMS
                    else f"no route to {dest_system}"
                )
                profit_label.setText("")
                roi_label.setText("")

    @staticmethod
    def _strip_admin_prefix(name: str) -> str:
        """commodities_routes has no 'nickname' field for destinations
        (unlike the terminals endpoint used for the picker), so fall back
        to trimming the same 'Admin - ' in-game kiosk-label prefix by hand."""
        prefix = "Admin - "
        return name[len(prefix):] if name.startswith(prefix) else name


MODULE_CLASS = TradeRouteOptimizerModule
