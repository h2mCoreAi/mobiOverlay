"""Refinery Finder module: which real UEX-tracked refinery terminal has the
best reported yield modifier for a chosen raw commodity, plus a static
refining-methods comparison table.

Deliberately NOT a literal "enter N SCU, get exact output" calculator —
verified live (2026-09-06) that UEX exposes no base yield%/purity data for
any raw commodity, and only 3 real `refineries_audits` rows exist
project-wide, far too sparse to reverse-engineer a formula from. Building
one would mean inventing constants UEX doesn't provide, which this project
has consistently avoided (see docs/modules/commodity-prices.md's
`commodities_ranking` dead-end for the precedent). See
docs/modules/refinery-finder.md for the full scoping writeup.
"""
import time

from PySide6.QtWidgets import QComboBox, QLabel, QHBoxLayout, QVBoxLayout, QWidget

from host import theme
from host.module_base import ModuleBase

ALL_SYSTEMS = "All Systems"
TOP_N = 5

_LABEL_SMALL = f'color: {theme.TEXT_MUTED}; font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(9)}px; letter-spacing: 2px;'
_ROW_STYLE = f"border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px; padding: 6px 8px;"
_RANK_STYLE = f'font-family: "{theme.FONT_DISPLAY}"; font-weight: 800; font-size: {theme.fpx(13)}px; color: {theme.ACCENT_CYAN};'
_TERMINAL_STYLE = f'font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(11)}px; color: {theme.TEXT_PRIMARY};'
_SUBTEXT_STYLE = f'font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(9)}px; color: {theme.TEXT_MUTED};'
_YIELD_STYLE = f'font-family: "{theme.FONT_DISPLAY}"; font-weight: 800; font-size: {theme.fpx(13)}px;'
_INFO_STYLE = f'color: {theme.TEXT_DIM}; font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(9)}px;'
_METHOD_ROW_STYLE = f'font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(9)}px; color: {theme.TEXT_MUTED};'
_TIMESTAMP_STYLE = f'color: {theme.TEXT_DIM}; font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(9)}px; letter-spacing: 1px;'
_COMBO_STYLE = f"""
    QComboBox {{
        background: {theme.BG_VOID}; color: {theme.ACCENT_CYAN};
        border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px; padding: 4px 6px;
        font-family: "{theme.FONT_DISPLAY}"; font-weight: 800; font-size: {theme.fpx(14)}px;
    }}
    QComboBox::drop-down {{ width: 18px; border: none; }}
"""
_SYSTEM_COMBO_STYLE = f"""
    QComboBox {{
        background: {theme.BG_VOID}; color: {theme.TEXT_MUTED};
        border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px; padding: 2px 4px;
        font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(9)}px;
    }}
    QComboBox::drop-down {{ width: 16px; border: none; }}
"""


class RefineryFinderModule(ModuleBase):
    module_id = "refinery_finder"
    display_name = (
        f'<span style="color:{theme.TEXT_PRIMARY};">mobi</span>'
        f'<span style="color:{theme.ACCENT_CYAN};">Refinery</span>'
    )

    def __init__(self, api_client, config):
        super().__init__(api_client, config)
        self.settings.setdefault("system_filter", ALL_SYSTEMS)
        self._raw_commodities: list[dict] = []  # [{id, name}] where is_raw == 1
        self._methods: list[dict] = []
        self._last_yield_rows: list[dict] = []
        self._capacity_by_terminal: dict[int, int] = {}
        self.request_refresh = None  # injected by host after wrapping refresh()

    # ------------------------------------------------------------------
    # Card construction
    # ------------------------------------------------------------------
    def create_card(self, container):
        card = container.add_card(self.module_id, self.display_name)
        layout = card.body_layout

        header = QHBoxLayout()
        header.setSpacing(6)
        picker_label = QLabel("RAW COMMODITY")
        picker_label.setStyleSheet(_LABEL_SMALL)
        header.addWidget(picker_label)
        header.addStretch()
        self.system_combo = QComboBox()
        self.system_combo.setStyleSheet(_SYSTEM_COMBO_STYLE)
        self.system_combo.setFixedWidth(96)
        self.system_combo.addItem(ALL_SYSTEMS)
        header.addWidget(self.system_combo)
        layout.addLayout(header)

        self.combo = QComboBox()
        self.combo.setStyleSheet(_COMBO_STYLE)
        self.combo.setEditable(False)
        layout.addWidget(self.combo)

        self._results_layout = QVBoxLayout()
        self._results_layout.setSpacing(6)
        layout.addLayout(self._results_layout)

        methods_label = QLabel("REFINING METHODS")
        methods_label.setStyleSheet(_LABEL_SMALL)
        layout.addWidget(methods_label)
        self._methods_layout = QVBoxLayout()
        self._methods_layout.setSpacing(2)
        layout.addLayout(self._methods_layout)

        footer = QHBoxLayout()
        self.timestamp_label = QLabel("NO DATA YET")
        self.timestamp_label.setStyleSheet(_TIMESTAMP_STYLE)
        footer.addWidget(self.timestamp_label)
        footer.addStretch()
        layout.addLayout(footer)

        self._populate_commodities()
        self._render_methods()  # static reference — render once, doesn't need a refresh
        self.combo.currentTextChanged.connect(self._on_commodity_changed)
        self.system_combo.currentTextChanged.connect(self._on_system_changed)

        self.card = card
        return card

    def _populate_commodities(self):
        try:
            data = self.api.get("commodities")
        except Exception:
            data = []
        rows = [
            {"id": row["id"], "name": row["name"]}
            for row in data
            if row.get("is_raw") == 1 and row.get("is_visible") and row.get("name") and row.get("id") is not None
        ]
        rows.sort(key=lambda r: r["name"])
        self._raw_commodities = rows
        names = [r["name"] for r in rows]

        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItems(names)
        watched = self.settings.get("watched_commodity")
        default = watched if watched in names else (names[0] if names else "")
        if default:
            self.combo.setCurrentText(default)
        self.combo.blockSignals(False)

        saved_system = self.settings.get("system_filter", ALL_SYSTEMS)
        self.system_combo.blockSignals(True)
        self.system_combo.setCurrentText(saved_system if saved_system else ALL_SYSTEMS)
        self.system_combo.blockSignals(False)

    def _on_commodity_changed(self, _name: str):
        self.request_refresh and self.request_refresh()

    def _on_system_changed(self, system: str):
        self.settings["system_filter"] = system
        self.config.set_module_settings(self.module_id, self.settings)
        self._render_results()

    # ------------------------------------------------------------------
    # ModuleBase refresh
    # ------------------------------------------------------------------
    def refresh(self):
        name = self.combo.currentText()
        if not name:
            raise ValueError("No raw commodity selected")

        # Confirmed live (2026-09-06): `id_commodity` does NOT filter this
        # endpoint server-side despite looking like a real query param —
        # same "verify, don't assume" lesson as Commodity Prices' substring-
        # match surprise. Fetch everything, filter client-side below.
        self._last_yield_rows = self.api.get("refineries_yields")
        capacities = self.api.get("refineries_capacities")
        self._capacity_by_terminal = {
            row["id_terminal"]: row["value"]
            for row in capacities
            if row.get("id_terminal") is not None and row.get("value") is not None
        }
        self._methods = self.api.get("refineries_methods")
        self._render_methods()
        self._render_results()

        self.timestamp_label.setText("UPDATED " + time.strftime("%H:%M:%S"))
        self.settings["watched_commodity"] = name
        self.config.set_module_settings(self.module_id, self.settings)

    # ------------------------------------------------------------------
    # Results rendering
    # ------------------------------------------------------------------
    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _render_results(self):
        self._clear_layout(self._results_layout)

        name = self.combo.currentText()
        commodity = next((c for c in self._raw_commodities if c["name"] == name), None)
        if commodity is None:
            return

        rows = [r for r in self._last_yield_rows if r.get("id_commodity") == commodity["id"]]
        system = self.system_combo.currentText()
        if system != ALL_SYSTEMS:
            rows = [r for r in rows if r.get("star_system_name") == system]

        if not rows:
            note = f"No yield data reported yet for {name}" + (
                "" if system == ALL_SYSTEMS else f" in {system}"
            )
            self._results_layout.addWidget(self._info_label(note))
            return

        # Best (highest) yield modifier first. A terminal can have more than
        # one report for the same commodity (repeat submissions over time,
        # confirmed live) — keep only its best reported value, not every
        # duplicate row, so the ranked list isn't dominated by one terminal.
        best_by_terminal: dict[int, dict] = {}
        for row in rows:
            term_id = row.get("id_terminal")
            if term_id is None:
                continue
            existing = best_by_terminal.get(term_id)
            if existing is None or row["value"] > existing["value"]:
                best_by_terminal[term_id] = row

        ranked = sorted(best_by_terminal.values(), key=lambda r: r["value"], reverse=True)
        for rank, row in enumerate(ranked[:TOP_N], start=1):
            self._results_layout.addWidget(self._result_row(rank, row))

        if len(ranked) > TOP_N:
            self._results_layout.addWidget(self._info_label(
                f"Showing top {TOP_N} of {len(ranked)} terminals."
            ))

    def _result_row(self, rank: int, row: dict) -> QWidget:
        box = QWidget()
        box.setStyleSheet(_ROW_STYLE)
        outer = QHBoxLayout(box)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        rank_label = QLabel(f"#{rank}")
        rank_label.setStyleSheet(_RANK_STYLE)
        rank_label.setFixedWidth(28)
        outer.addWidget(rank_label)

        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        terminal = QLabel(row.get("terminal_name") or "Unknown terminal")
        terminal.setStyleSheet(_TERMINAL_STYLE)
        terminal.setWordWrap(True)
        text_col.addWidget(terminal)
        capacity = self._capacity_by_terminal.get(row.get("id_terminal"))
        capacity_text = f"{capacity:,} SCU capacity" if capacity is not None else "capacity unknown"
        sub = QLabel(f"{row.get('star_system_name') or '?'} · {capacity_text}")
        sub.setStyleSheet(_SUBTEXT_STYLE)
        text_col.addWidget(sub)
        outer.addLayout(text_col, stretch=1)

        value = row["value"]
        yield_label = QLabel(f"{'+' if value >= 0 else ''}{value}%")
        yield_color = theme.ACCENT_CYAN if value >= 0 else theme.ACCENT_AMBER
        yield_label.setStyleSheet(_YIELD_STYLE + f" color: {yield_color};")
        outer.addWidget(yield_label)

        return box

    def _info_label(self, text: str) -> QWidget:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet(_INFO_STYLE)
        return label

    # ------------------------------------------------------------------
    # Static methods reference table
    # ------------------------------------------------------------------
    def _render_methods(self):
        self._clear_layout(self._methods_layout)
        methods = sorted(self._methods, key=lambda m: m.get("name", ""))
        if not methods:
            self._methods_layout.addWidget(self._info_label("Methods data not loaded yet."))
            return
        for m in methods:
            row = QLabel(
                f"{m.get('name', '?'):<24} YIELD {m.get('rating_yield', '?')}/3 · "
                f"COST {m.get('rating_cost', '?')}/3 · SPEED {m.get('rating_speed', '?')}/3"
            )
            row.setStyleSheet(_METHOD_ROW_STYLE)
            self._methods_layout.addWidget(row)


MODULE_CLASS = RefineryFinderModule
