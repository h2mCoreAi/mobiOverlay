"""Multi-Commodity Finder module: given a list of commodities you're hauling
(SELL mode) or want to stock up on (BUY mode), find the terminal(s) that
cover the most of that list at once — even if it isn't the single best price
for any one of them — because fewer stops usually beats a slightly better
per-unit price. See docs/modules/multi-commodity-finder.md for the full
design writeup and the gating rules ported from Commodity Prices.
"""
import time

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox, QLabel, QHBoxLayout, QVBoxLayout, QWidget, QPushButton,
    QListWidget, QListWidgetItem, QScrollArea, QLineEdit,
)

from host import theme
from host.api_client import UexRateLimitError
from host.locations import LocationService
from host.module_base import ModuleBase

ALL_SYSTEMS = "All Systems"
ANY_FACILITY = "Any Facility"
SCAN_STEP_INTERVAL_MS = 120  # ~8 requests/sec, same throttle every scan-style module uses
SCAN_CACHE_SECONDS = 1800  # 30 min, same window Commodity Prices uses
FORCE_CONFIRM_TIMEOUT_MS = 4000
MAX_RESULTS = 8
COPY_CONFIRM_MS = 1500  # how long the COPY button shows "COPIED" before reverting, same as Logistics Hub's COPY ROUTE

_LABEL_SMALL = f'color: {theme.TEXT_MUTED}; font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(9)}px; letter-spacing: 2px;'
_LIST_STYLE = f"""
    QListWidget {{
        background: {theme.BG_VOID}; color: {theme.TEXT_PRIMARY};
        border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px;
        font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(10)}px;
    }}
"""
_SEARCH_STYLE = f"""
    QLineEdit {{
        background: {theme.BG_VOID}; color: {theme.TEXT_PRIMARY};
        border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px; padding: 4px 6px;
        font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(10)}px;
    }}
"""
_COMBO_STYLE = f"""
    QComboBox {{
        background: {theme.BG_VOID}; color: {theme.TEXT_MUTED};
        border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px; padding: 3px 5px;
        font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(9)}px;
    }}
"""
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
_RESULT_ROW_STYLE = f"border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px; padding: 8px 10px;"
_RESULT_HEADER_STYLE = f'font-family: "{theme.FONT_DISPLAY}"; font-weight: 800; font-size: {theme.fpx(12)}px; color: {theme.ACCENT_CYAN};'
_RESULT_TOTAL_STYLE = f'font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(11)}px; color: {theme.TEXT_PRIMARY};'
_RESULT_LINE_STYLE = f'font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(9)}px; color: {theme.TEXT_MUTED};'
_RESULT_MISSING_STYLE = f'font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(9)}px; color: {theme.ACCENT_AMBER};'
_TIMESTAMP_STYLE = f'color: {theme.TEXT_DIM}; font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(9)}px; letter-spacing: 1px;'


class MultiCommodityFinderModule(ModuleBase):
    module_id = "multi_commodity_finder"
    display_name = (
        f'<span style="color:{theme.TEXT_PRIMARY};">mobi</span>'
        f'<span style="color:{theme.ACCENT_CYAN};">Consolidate</span>'
    )

    def __init__(self, api_client, config):
        super().__init__(api_client, config)
        self._locations = LocationService(api_client)
        self._commodities: list[str] = []
        self._terminal_names: dict[int, str] = {}
        self._terminal_facilities: dict[int, set[str]] = {}
        self.request_refresh = None  # injected by host after wrapping refresh()

        self._scan_timer: QTimer | None = None
        self._scan_queue: list[str] = []
        self._scan_index = 0
        self._scanned_data: dict[str, list[dict]] = {}
        self._last_scan_time = 0.0
        self._countdown_timer: QTimer | None = None
        self._force_confirm_pending = False
        self._force_confirm_revert_timer: QTimer | None = None
        self._result_rows: list[QWidget] = []
        self._last_ranked: list[dict] = []
        self._last_selected: list[str] = []
        self._copy_revert_timer: QTimer | None = None

    def create_card(self, container):
        card = container.add_card(self.module_id, self.display_name)

        label = QLabel("SELECT COMMODITIES")
        label.setStyleSheet(_LABEL_SMALL)
        card.body_layout.addWidget(label)

        self.commodity_search = QLineEdit()
        self.commodity_search.setStyleSheet(_SEARCH_STYLE)
        self.commodity_search.setPlaceholderText("Type to search...")
        self.commodity_search.setClearButtonEnabled(True)
        self.commodity_search.textChanged.connect(self._on_commodity_search_changed)
        card.body_layout.addWidget(self.commodity_search)

        self.commodity_list = QListWidget()
        self.commodity_list.setStyleSheet(_LIST_STYLE)
        self.commodity_list.setFixedHeight(120)
        self.commodity_list.itemChanged.connect(self._on_selection_changed)
        card.body_layout.addWidget(self.commodity_list)

        controls = QHBoxLayout()
        self.mode_combo = QComboBox()
        self.mode_combo.setStyleSheet(_COMBO_STYLE)
        self.mode_combo.addItems(["SELL (they buy from you)", "BUY (they sell to you)"])
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        controls.addWidget(self.mode_combo, stretch=2)

        self.system_combo = QComboBox()
        self.system_combo.setStyleSheet(_COMBO_STYLE)
        self.system_combo.addItem(ALL_SYSTEMS)
        self.system_combo.currentTextChanged.connect(self._on_system_filter_changed)
        controls.addWidget(self.system_combo, stretch=1)
        card.body_layout.addLayout(controls)

        self.facility_combo = QComboBox()
        self.facility_combo.setStyleSheet(_COMBO_STYLE)
        self.facility_combo.addItem(ANY_FACILITY)
        self.facility_combo.addItems(sorted(LocationService.FACILITY_FLAGS.values()))
        self.facility_combo.setToolTip(
            "Only show terminals that also report having this facility "
            "(e.g. a Refinery or Loading Dock) — from UEX's own terminal "
            "data, not a guess."
        )
        self.facility_combo.currentTextChanged.connect(self._on_facility_filter_changed)
        card.body_layout.addWidget(self.facility_combo)

        self.clear_btn = QPushButton("CLEAR ALL")
        self.clear_btn.setStyleSheet(_ACTION_BTN_STYLE)
        self.clear_btn.setToolTip(
            "Clears the commodity search text, unchecks every commodity, "
            "and resets the system/facility filters back to their defaults."
        )
        self.clear_btn.clicked.connect(self._on_clear_clicked)
        card.body_layout.addWidget(self.clear_btn)

        self.scan_btn = QPushButton("SCAN")
        self.scan_btn.setStyleSheet(_ACTION_BTN_STYLE)
        self.scan_btn.setToolTip(
            "Downloads current prices for every checked commodity and finds "
            "the terminal(s) covering the most of them at once. Click again "
            "before the countdown ends to force an early rescan."
        )
        self.scan_btn.clicked.connect(self._on_scan_clicked)
        card.body_layout.addWidget(self.scan_btn)

        self.results_area = QScrollArea()
        self.results_area.setWidgetResizable(True)
        self.results_area.setFixedHeight(220)
        self.results_area.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.results_container = QWidget()
        self.results_layout = QVBoxLayout(self.results_container)
        self.results_layout.setContentsMargins(0, 0, 0, 0)
        self.results_layout.setSpacing(6)
        self.results_layout.addStretch()
        self.results_area.setWidget(self.results_container)
        card.body_layout.addWidget(self.results_area)

        self.status_label = QLabel("Check commodities above, then SCAN.")
        self.status_label.setStyleSheet(_TIMESTAMP_STYLE)
        self.status_label.setWordWrap(True)
        card.body_layout.addWidget(self.status_label)

        self.copy_btn = QPushButton("COPY")
        self.copy_btn.setStyleSheet(_ACTION_BTN_STYLE)
        self.copy_btn.setToolTip(
            "Copies your selected commodities, mode, filters, and the "
            "current results to the clipboard as neatly formatted plain "
            "text — for sharing in Discord/chat."
        )
        self.copy_btn.clicked.connect(self._copy_to_clipboard)
        card.body_layout.addWidget(self.copy_btn)

        self._populate_commodities()
        self._restore_mode()
        self._restore_facility_filter()

        self.card = card
        return card

    # -- setup --------------------------------------------------------------
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
        selected = set(self.settings.get("selected_commodities", []))

        self.commodity_list.blockSignals(True)
        for name in names:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if name in selected else Qt.Unchecked)
            self.commodity_list.addItem(item)
        self.commodity_list.blockSignals(False)

    def _restore_mode(self):
        mode = self.settings.get("mode", "sell")
        self.mode_combo.blockSignals(True)
        self.mode_combo.setCurrentIndex(1 if mode == "buy" else 0)
        self.mode_combo.blockSignals(False)

    def _restore_facility_filter(self):
        saved = self.settings.get("facility_filter", ANY_FACILITY)
        self.facility_combo.blockSignals(True)
        self.facility_combo.setCurrentText(
            saved if saved in LocationService.FACILITY_FLAGS.values() or saved == ANY_FACILITY else ANY_FACILITY
        )
        self.facility_combo.blockSignals(False)

    def _on_commodity_search_changed(self, text: str):
        # Substring match, case-insensitive, against every commodity name —
        # same filtering approach Trade Route Optimizer's terminal picker
        # already uses (QCompleter, Qt.MatchContains). A plain QListWidget
        # has no built-in text-filter box the way an editable QComboBox has
        # a completer, so this hides/shows rows by hand instead; checked
        # items stay checked even while hidden, so filtering never loses a
        # selection.
        needle = text.strip().lower()
        for i in range(self.commodity_list.count()):
            item = self.commodity_list.item(i)
            item.setHidden(bool(needle) and needle not in item.text().lower())

    def _on_clear_clicked(self):
        # Clears the search text and every checked commodity, plus resets
        # both filter dropdowns to their defaults — a one-click "start over"
        # rather than clicking the search box's own clear button, unchecking
        # everything by hand, and resetting two combos separately. Leaves
        # SELL/BUY mode and any already-scanned results alone — those aren't
        # "filters," and clearing a scan the user might still want to look
        # at while re-picking commodities would be a surprising side effect.
        self.commodity_search.blockSignals(True)
        self.commodity_search.clear()
        self.commodity_search.blockSignals(False)
        self._on_commodity_search_changed("")

        self.commodity_list.blockSignals(True)
        for i in range(self.commodity_list.count()):
            self.commodity_list.item(i).setCheckState(Qt.Unchecked)
        self.commodity_list.blockSignals(False)
        self.settings["selected_commodities"] = []

        self.system_combo.blockSignals(True)
        self.system_combo.setCurrentText(ALL_SYSTEMS)
        self.system_combo.blockSignals(False)
        self.settings["system_filter"] = ALL_SYSTEMS

        self.facility_combo.blockSignals(True)
        self.facility_combo.setCurrentText(ANY_FACILITY)
        self.facility_combo.blockSignals(False)
        self.settings["facility_filter"] = ANY_FACILITY

        self.config.set_module_settings(self.module_id, self.settings)
        if self._scanned_data:
            self._render_results()

    def _selected_commodities(self) -> list[str]:
        result = []
        for i in range(self.commodity_list.count()):
            item = self.commodity_list.item(i)
            if item.checkState() == Qt.Checked:
                result.append(item.text())
        return result

    def _on_selection_changed(self, _item):
        self.settings["selected_commodities"] = self._selected_commodities()
        self.config.set_module_settings(self.module_id, self.settings)

    def _on_mode_changed(self, _index):
        self.settings["mode"] = "buy" if self.mode_combo.currentIndex() == 1 else "sell"
        self.config.set_module_settings(self.module_id, self.settings)
        if self._scanned_data:
            self._render_results()

    def _on_system_filter_changed(self, _system):
        self.settings["system_filter"] = self.system_combo.currentText()
        self.config.set_module_settings(self.module_id, self.settings)
        if self._scanned_data:
            self._render_results()

    def _on_facility_filter_changed(self, _facility):
        self.settings["facility_filter"] = self.facility_combo.currentText()
        self.config.set_module_settings(self.module_id, self.settings)
        if self._scanned_data:
            self._render_results()

    def refresh(self):
        # No auto-refresh — this is an on-demand scan, same reasoning as
        # Commodity Prices' Retrieve Data and Trade Route Optimizer's
        # Any-Location SCAN (multi-call, shouldn't run silently on a timer).
        pass

    # -- scan -----------------------------------------------------------
    def _on_scan_clicked(self):
        if self._scan_timer is not None:
            return

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
        selected = self._selected_commodities()
        if not selected:
            self.status_label.setText("Check at least one commodity first.")
            return

        self._stop_countdown()
        self._scan_queue = selected
        self._scan_index = 0
        self._scanned_data = {}
        self.scan_btn.setEnabled(False)
        self.scan_btn.setText(f"SCANNING 0/{len(self._scan_queue)}")
        self.status_label.setText("Scanning...")

        self._scan_timer = QTimer()
        self._scan_timer.timeout.connect(self._scan_step)
        self._scan_timer.start(SCAN_STEP_INTERVAL_MS)

    def _scan_step(self):
        if self._scan_index >= len(self._scan_queue):
            self._finish_scan()
            return

        name = self._scan_queue[self._scan_index]
        self._scan_index += 1
        try:
            rows = self.api.get("commodities_prices", {"commodity_name": name})
            self._scanned_data[name] = [r for r in rows if r.get("commodity_name") == name]
        except UexRateLimitError as exc:
            self._scan_timer.stop()
            self._scan_timer = None
            self.scan_btn.setEnabled(True)
            self.scan_btn.setText("SCAN")
            self.card.set_error(str(exc), retry_callback=self._start_scan)
            return
        except Exception:
            pass  # skip commodities that individually fail; don't abort the whole scan

        self.scan_btn.setText(f"SCANNING {self._scan_index}/{len(self._scan_queue)}")

    def _finish_scan(self):
        self._scan_timer.stop()
        self._scan_timer = None
        self._last_scan_time = time.time()
        self.scan_btn.setEnabled(True)
        self.card.clear_error()
        self._populate_terminal_names()
        self._repopulate_system_filter()
        self._render_results()
        self._start_countdown()

    def _populate_terminal_names(self):
        rows = [
            row for row in self._locations.all_locations()
            if row.get("_endpoint") == "terminals" and row.get("type") == "commodity"
        ]
        self._terminal_names = {
            row["id"]: self._locations.display_name(row) for row in rows if row.get("id")
        }
        self._terminal_facilities = {
            row["id"]: self._locations.facilities(row) for row in rows if row.get("id")
        }

    def _repopulate_system_filter(self):
        systems = set()
        for rows in self._scanned_data.values():
            for r in rows:
                if r.get("star_system_name"):
                    systems.add(r["star_system_name"])
        current = self.system_combo.currentText()
        self.system_combo.blockSignals(True)
        self.system_combo.clear()
        self.system_combo.addItem(ALL_SYSTEMS)
        self.system_combo.addItems(sorted(systems))
        saved = self.settings.get("system_filter", ALL_SYSTEMS)
        restore = saved if saved in systems else (current if current in systems else ALL_SYSTEMS)
        self.system_combo.setCurrentText(restore)
        self.system_combo.blockSignals(False)

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
            self.scan_btn.setText("SCAN")
            return
        mins, secs = divmod(remaining, 60)
        self.scan_btn.setText(f"REFRESH IN {mins:02d}:{secs:02d}")

    def _stop_countdown(self):
        if self._countdown_timer is not None:
            self._countdown_timer.stop()
            self._countdown_timer = None

    # -- ranking / rendering --------------------------------------------
    def _render_results(self):
        for w in self._result_rows:
            self.results_layout.removeWidget(w)
            w.deleteLater()
        self._result_rows = []

        is_buy_mode = self.mode_combo.currentIndex() == 1
        system_filter = self.system_combo.currentText()
        facility_filter = self.facility_combo.currentText()

        # terminal id -> {"name": str, "system": str, "prices": {commodity: price}}
        terminals: dict[int, dict] = {}
        for name, rows in self._scanned_data.items():
            for r in rows:
                if system_filter != ALL_SYSTEMS and r.get("star_system_name") != system_filter:
                    continue
                tid_check = r.get("id_terminal")
                if facility_filter != ANY_FACILITY and facility_filter not in self._terminal_facilities.get(tid_check, set()):
                    continue
                if is_buy_mode:
                    # Same stock gate Commodity Prices' Best Buy uses — a
                    # quoted buy price with 0 source stock isn't a real option.
                    if not (r.get("price_buy", 0) > 0 and r.get("scu_buy", 0) > 0):
                        continue
                    price = r["price_buy"]
                else:
                    # No scu_sell gate — same reasoning as Commodity Prices'
                    # Best Sell (UEX doesn't reliably track sell-side demand
                    # caps, see docs/DECISIONS.md 2026-09-05).
                    if not (r.get("price_sell", 0) > 0):
                        continue
                    price = r["price_sell"]

                tid = r.get("id_terminal")
                if tid is None:
                    continue
                entry = terminals.setdefault(tid, {
                    "name": self._terminal_names.get(tid) or r.get("terminal_name") or "",
                    "system": r.get("star_system_name") or "",
                    "place": r.get("city_name") or r.get("planet_name") or "",
                    "prices": {},
                })
                # Keep the best available price per commodity at this
                # terminal, in case of duplicate rows (e.g. different SCU
                # tiers) — mirrors _apply_filters()'s max/min-per-row logic.
                existing = entry["prices"].get(name)
                if existing is None or (is_buy_mode and price < existing) or (not is_buy_mode and price > existing):
                    entry["prices"][name] = price

        selected = self._selected_commodities()
        ranked = sorted(
            terminals.values(),
            key=lambda t: (len(t["prices"]), sum(t["prices"].values())),
            reverse=True,
        )[:MAX_RESULTS]
        # Kept for the COPY button (_format_for_clipboard) so it reflects
        # exactly what's on screen without re-deriving it from widget text.
        self._last_ranked = ranked
        self._last_selected = selected

        if not ranked:
            self.status_label.setText("No terminals found for the checked commodities" +
                                       ("" if system_filter == ALL_SYSTEMS else f" in {system_filter}") + ".")
            return

        self.status_label.setText(
            f"SCANNED {len(selected)} COMMODITIES · {time.strftime('%H:%M:%S')}"
        )

        for entry in ranked:
            self._result_rows.append(self._build_result_row(entry, selected, is_buy_mode))

        for w in reversed(self._result_rows):
            self.results_layout.insertWidget(0, w)

    @staticmethod
    def _missing_text(name: str, is_buy_mode: bool) -> str:
        # "not available here" was genuinely ambiguous — a user reading it
        # under SELL mode (terminal buys from you) reasonably read it as
        # "they don't have any in stock" rather than its actual meaning,
        # "this terminal doesn't buy this commodity at all." Spelling out
        # buy/sell directly, matching the mode's own wording, removes the
        # ambiguity instead of leaving the reader to infer direction from
        # context. See docs/DECISIONS.md, 2026-09-08.
        return f"{name}: doesn't sell to you" if is_buy_mode else f"{name}: doesn't buy from you"

    def _build_result_row(self, entry: dict, selected: list[str], is_buy_mode: bool) -> QWidget:
        box = QWidget()
        box.setStyleSheet(_RESULT_ROW_STYLE)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)

        place = f" · {entry['place']}" if entry.get("place") else ""
        header = QLabel(f"{entry['name']}{place}  [{len(entry['prices'])}/{len(selected)}]")
        header.setStyleSheet(_RESULT_HEADER_STYLE)
        header.setWordWrap(True)
        layout.addWidget(header)

        total = sum(entry["prices"].values())
        total_label = QLabel(f"TOTAL: {total:,.0f} aUEC/SCU across {len(entry['prices'])} commodities")
        total_label.setStyleSheet(_RESULT_TOTAL_STYLE)
        layout.addWidget(total_label)

        for name in selected:
            if name in entry["prices"]:
                line = QLabel(f"  ✓ {name}: {entry['prices'][name]:,.0f}")
                line.setStyleSheet(_RESULT_LINE_STYLE)
            else:
                line = QLabel(f"  ✕ {self._missing_text(name, is_buy_mode)}")
                line.setStyleSheet(_RESULT_MISSING_STYLE)
            layout.addWidget(line)

        return box

    # -- copy to clipboard --------------------------------------------
    def _format_for_clipboard(self) -> str:
        """Plain-text summary of the selected commodities/mode/filters/
        results, for pasting into Discord/chat. Deliberately excludes the
        commodity search box text — that's just a UI narrowing aid, not
        part of the actual query, so it'd be noise in a shared summary.
        Reads from `_last_ranked`/`_last_selected`
        (set by `_render_results()`) rather than re-scanning `_scanned_data`
        or scraping result-row widget text, so what's copied always matches
        what's actually on screen, including after a filter change that
        hasn't triggered a new SCAN."""
        lines = ["mobiConsolidate — Multi-Commodity Finder"]

        is_buy_mode = self.mode_combo.currentIndex() == 1
        mode = "BUY (terminal sells to you)" if is_buy_mode else "SELL (terminal buys from you)"
        lines.append(f"Mode: {mode}")

        system_filter = self.system_combo.currentText()
        facility_filter = self.facility_combo.currentText()
        lines.append(f"System filter: {system_filter}")
        lines.append(f"Facility filter: {facility_filter}")

        selected = self._last_selected or self._selected_commodities()
        lines.append(f"Commodities ({len(selected)}): " + (", ".join(selected) if selected else "none checked"))
        lines.append("")

        if not self._last_ranked:
            lines.append("No results yet — run a SCAN first.")
            return "\n".join(lines)

        lines.append(f"Results ({len(self._last_ranked)} terminals, ranked by coverage then total value):")
        for i, entry in enumerate(self._last_ranked, start=1):
            place = f" · {entry['place']}" if entry.get("place") else ""
            total = sum(entry["prices"].values())
            lines.append(
                f"{i}. {entry['name']}{place}  "
                f"[{len(entry['prices'])}/{len(selected)}]  "
                f"TOTAL {total:,.0f} aUEC/SCU"
            )
            for name in selected:
                if name in entry["prices"]:
                    lines.append(f"    - {name}: {entry['prices'][name]:,.0f}")
                else:
                    lines.append(f"    - {self._missing_text(name, is_buy_mode)}")

        return "\n".join(lines)

    def _copy_to_clipboard(self):
        QGuiApplication.clipboard().setText(self._format_for_clipboard())

        if self._copy_revert_timer is not None:
            self._copy_revert_timer.stop()
        self.copy_btn.setText("COPIED")
        self._copy_revert_timer = QTimer()
        self._copy_revert_timer.setSingleShot(True)
        self._copy_revert_timer.timeout.connect(self._revert_copy_btn)
        self._copy_revert_timer.start(COPY_CONFIRM_MS)

    def _revert_copy_btn(self):
        self._copy_revert_timer = None
        self.copy_btn.setText("COPY")


MODULE_CLASS = MultiCommodityFinderModule
