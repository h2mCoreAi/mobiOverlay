"""Logistics Hub result rendering: the contracts list, freight manifest,
planned route rows, and the always-on-top route popout window.

A mixin, not a separate widget: these methods read and write the module's
own state (self._contracts, self._route, layouts built in create_card), so
they were moved here verbatim from module.py to keep that file reviewable.
Loaded by modules/logistics_hub/module.py by file path.
"""
import importlib.util
import os
import sys

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizeGrip,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from host import theme


def _sibling(name: str, filename: str):
    """The already-loaded sibling module (module.py registers each one in
    sys.modules), or load it by file path if this file is imported alone."""
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(name, os.path.join(os.path.dirname(__file__), filename))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


grading = _sibling("mobioverlay_logistics_hub_grading", "grading.py")
parsing = _sibling("mobioverlay_logistics_hub_parsing", "parsing.py")
popups = _sibling("mobioverlay_logistics_hub_popups", "popups.py")
_cargo_label = parsing._cargo_label
_entry_scu = parsing._entry_scu
_total_reward = parsing._total_reward
_ReminderBanner = popups._ReminderBanner


class ResultsViewMixin:
    # ------------------------------------------------------------------
    # Result rendering
    # ------------------------------------------------------------------
    @staticmethod
    def _clear_layout(layout: QVBoxLayout | QHBoxLayout):
        """Remove and delete every item in `layout`, recursing into nested
        sub-layouts (e.g. route_title_row below, added via addLayout).
        `takeAt(i).widget()` is None for a sub-layout item, so a shallow
        clear leaves that sub-layout's widgets orphaned — still alive,
        still parented to the container, but no longer positioned by any
        layout — where they float at their last geometry and can visually
        cover whatever gets laid out over them on the next render."""
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
                continue
            sub_layout = item.layout()
            if sub_layout is not None:
                ResultsViewMixin._clear_layout(sub_layout)

    def _render_results(self):
        # Clear any previous contents.
        self._clear_layout(self._results_layout)

        contracts = self.settings.get("contracts", [])
        self._contracts_title.setText(f"CONTRACTS ({len(contracts)})")
        self._populate_contracts_rows(self._contracts_layout, contracts)
        self._populate_manifest_rows(self._manifest_layout, contracts)

        if contracts:
            reward = _total_reward(contracts)
            peak_scu = self._peak_cargo_scu(contracts)
            plural = "s" if len(contracts) != 1 else ""
            summary = f"{len(contracts)} contract{plural} · {reward:,} aUEC · {peak_scu} SCU peak cargo"
            capacity = self.settings.get("cargo_capacity_scu")
            over_capacity = bool(capacity) and peak_scu > capacity
            if capacity:
                if over_capacity:
                    summary += f"  ⚠ EXCEEDS {capacity} SCU CAPACITY BY {peak_scu - capacity}"
                else:
                    summary += f"  (of {capacity} SCU)"
            self._summary_label.setText(summary)
            self._summary_label.setStyleSheet(
                f"color: {theme.ACCENT_AMBER if over_capacity else theme.TEXT_MUTED}; "
                f"font-family: {theme.FONT_MONO}; font-size: {theme.fpx(9)}px; "
                f"letter-spacing: 0.5px; font-weight: {700 if over_capacity else 400};"
            )
        else:
            self._summary_label.setText("")

        self._tracker_btn.setVisible(bool(self._route_order))
        self._tracker_btn.setText("RETURN TO CARD" if self._route_popout is not None else "TRACKER")

        # Keep an already-open Tracker popout in sync unconditionally, even
        # when there are now zero stops — this used to live inside the
        # `if self._route_order:` block below, which CLEAR (or any other
        # action that empties the route) skips entirely, silently leaving
        # the popout showing whatever stale stops it had before the clear
        # until the next scan happens to repopulate it. Confirmed real
        # (2026-09-06): clicking CLEAR with the Tracker open looked like
        # old contracts "weren't fully cleared."
        if self._route_popout is not None:
            self._populate_route_rows(self._route_popout_layout, contracts, transparent_bg=True)

        if self._route_order:
            route_title = QLabel("ROUTE")
            route_title.setStyleSheet(self._title_style())
            self._results_layout.addWidget(route_title)

            # Full per-stop list, inline on the card — re-added 2026-09-07.
            # A 2026-09-05 attempt at this same thing hit rows that stayed
            # invisible until the Tracker popout had been opened once, and
            # was reverted rather than chased blind (no way to run the real
            # Qt UI in that pass). This time verified live in the running
            # app (not just code-reviewed) — see docs/DECISIONS.md,
            # 2026-09-07, for what the actual cause turned out to be. The
            # Tracker popout still exists alongside this as an optional
            # always-on-top detached window for while the game has focus;
            # both stay in sync via the same `_populate_route_rows` call.
            self._populate_route_rows(self._results_layout, contracts)
            if self._route_popout is not None:
                self._results_layout.addWidget(self._info_label(
                    "Also open in the detached Tracker window."
                ))

        self._results_layout.addWidget(self._info_label(
            "Best-effort OCR + UEX matching. Verify against the actual "
            "in-game contracts before committing to a route."
        ))

        if self._card_widget is not None:
            self._card_widget.apply_size()

    def _populate_route_rows(
        self, target_layout: QVBoxLayout, contracts: list[dict], transparent_bg: bool = False
    ):
        while target_layout.count():
            item = target_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        route_done = set(self.settings.get("route_done", []))
        for idx, node in enumerate(self._route_order, start=1):
            described = self._describe_stop(contracts, node)
            if described is None:
                continue
            label, route_key = described
            target_layout.addWidget(
                self._route_row(
                    f"{idx}. {label}",
                    route_key,
                    done=route_key in route_done,
                    transparent_bg=transparent_bg,
                )
            )

    def _stop_entry(self, contracts: list[dict], node) -> tuple[dict, str] | None:
        """The pickup/dropoff entry dict + role a route node points at, or
        `None` if the node's contract/index no longer exists (shouldn't
        happen for a route built from the current contract list, but never
        crash the card over a stale node). Shared lookup behind
        `_describe_stop` and `_peak_cargo_scu` below — was previously
        duplicated inline in `_populate_route_rows` only."""
        i, role, j = node
        contract = contracts[i] if i < len(contracts) else None
        if contract is None:
            return None
        key = "pickups" if role == "pickup" else "dropoffs"
        items = contract.get(key, [])
        entry = items[j] if j < len(items) else {}
        return entry, role

    def _describe_stop(self, contracts: list[dict], node) -> tuple[str, str] | None:
        """One route node as `(display_text, route_key)` — `display_text`
        has no numbering prefix, so both the numbered route list and the
        unnumbered NEXT STOP banner can use it as-is."""
        resolved = self._stop_entry(contracts, node)
        if resolved is None:
            return None
        entry, role = resolved
        i, _role, j = node
        contract = contracts[i]
        terminal = entry.get("terminal")
        raw = entry.get("raw", "??")
        label_text = self._locations.display_name(terminal) if terminal else None
        display = label_text or f"{raw} (unresolved)"
        role_tag = "PICKUP" if role == "pickup" else "DROPOFF"
        cargo_text = f" — {_cargo_label(entry.get('commodities'))}"
        route_key = f"{contract.get('id')}:{role}:{j}"
        return f"[{role_tag}] {display}{cargo_text}", route_key

    def _peak_cargo_scu(self, contracts: list[dict], route_order: list | None = None) -> int:
        """The largest amount of cargo actually in the hold at any point
        along the *planned* route — not a flat sum of every pickup, which
        would overstate the ship size needed whenever some cargo gets
        dropped off before more is picked up. Walks `route_order` (defaults
        to `self._route_order`, the currently-active route — pass an
        explicit route, e.g. from a hypothetical candidate-included
        `_plan_route()` call, to check a contract not yet added) in order,
        +SCU on a pickup, -SCU on a dropoff, tracking the running peak."""
        if route_order is None:
            route_order = self._route_order
        current = 0
        peak = 0
        for node in route_order:
            resolved = self._stop_entry(contracts, node)
            if resolved is None:
                continue
            entry, role = resolved
            scu = _entry_scu(entry)
            current += scu if role == "pickup" else -scu
            peak = max(peak, current)
        return peak

    def _toggle_route_popout(self):
        if self._route_popout is not None:
            self._on_route_popout_closed()
        else:
            self._open_route_popout()

    def _make_always_on_top_window(
        self, title_html: str, on_close, geometry: dict | None, opacity_pct: int
    ) -> tuple[QWidget, QVBoxLayout, QSlider]:
        """Shared shell for a detached, always-on-top, frameless window
        (only the ROUTE popout uses this today — the CONTRACTS list popup
        was tried and reverted, see DECISIONS.md). Frameless means there's
        no OS title bar and no OS close button, so both are built here:
        a small header styled like mobiOverlay's own main window
        (host/main_window.py's _TitleBar), draggable the same way, with a
        close button wired to `on_close` instead of a Qt close event.

        Opacity fades only the window's own void background, not the
        header/content on top of it — same per-pixel-alpha technique as
        host/main_window.py's MainWindow.paintEvent (setWindowOpacity was
        tried first and rejected: it dims the *entire* rendered surface
        uniformly, including text, which is exactly what was asked not to
        happen)."""
        win = QWidget()
        # WindowDoesNotAcceptFocus: this is Qt.Window (not Qt.Tool like the
        # main window), which on Windows can grab OS foreground focus both
        # on first show and whenever an always-on-top window's z-order gets
        # re-evaluated — plausible cause of the game occasionally losing
        # focus while this is open. Mouse clicks (slider, close button,
        # route-stop toggling) are unaffected; only keyboard/foreground
        # activation is blocked. Added 2026-09-05, see DECISIONS.md.
        win.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
        win.setAttribute(Qt.WA_TranslucentBackground, True)
        win.resize(420, 480)
        win.setMinimumSize(240, 160)
        if geometry:
            win.setGeometry(geometry["x"], geometry["y"], geometry["w"], geometry["h"])

        paint_state = {"opacity": opacity_pct / 100.0}

        def win_paint_event(event):
            painter = QPainter(win)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setCompositionMode(QPainter.CompositionMode_Source)
            painter.fillRect(win.rect(), Qt.transparent)
            color = QColor(theme.BG_VOID)
            color.setAlphaF(paint_state["opacity"])
            path = QPainterPath()
            path.addRoundedRect(QRectF(win.rect()), theme.RADIUS, theme.RADIUS)
            painter.fillPath(path, color)
            # Same border treatment as a Logistics Hub Card (see
            # card.py's _apply_border) — full opacity regardless of the
            # window fade above, since chrome (not content) shouldn't wash
            # out. Stroked on an inset rect, not the fill rect, so the 1px
            # line isn't half-clipped at the window's true edge.
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            stroke_path = QPainterPath()
            stroke_rect = QRectF(win.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
            stroke_path.addRoundedRect(stroke_rect, theme.RADIUS, theme.RADIUS)
            painter.setPen(QPen(QColor(theme.ACCENT_CYAN), 1))
            painter.drawPath(stroke_path)
            painter.end()

        win.paintEvent = win_paint_event

        outer = QVBoxLayout(win)
        outer.setContentsMargins(1, 1, 1, 1)
        outer.setSpacing(0)

        header = QWidget()
        header.setFixedHeight(30)
        header.setStyleSheet(f"background: {theme.BG_PANEL}; border-bottom: 1px solid {theme.BORDER_FLAT};")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 0, 8, 0)

        title_label = QLabel(title_html)
        title_label.setTextInteractionFlags(Qt.NoTextInteraction)
        title_label.setStyleSheet(
            f"font-family: {theme.FONT_DISPLAY}; font-weight: 700; "
            f"font-size: {theme.fpx(10)}px; letter-spacing: 1px;"
        )
        header_layout.addWidget(title_label)
        header_layout.addStretch()

        # Own opacity control — fully local to this window instance, no
        # shared config, no coupling to the main window's or any card's
        # opacity setting. Persisted to module settings on close.
        opacity_slider = QSlider(Qt.Horizontal)
        opacity_slider.setFixedWidth(70)
        opacity_slider.setRange(30, 100)
        opacity_slider.setValue(opacity_pct)
        opacity_slider.setToolTip("Tracker window opacity (independent of the rest of the UI)")

        def on_opacity_changed(v):
            paint_state["opacity"] = v / 100.0
            win.update()

        opacity_slider.valueChanged.connect(on_opacity_changed)
        header_layout.addWidget(opacity_slider)

        close_btn = QPushButton("✕")
        close_btn.setObjectName("cardIconBtn")
        close_btn.setFixedSize(20, 20)
        close_btn.clicked.connect(on_close)
        header_layout.addWidget(close_btn)

        drag_state = {"offset": None}

        def header_mouse_press(event):
            if event.button() == Qt.LeftButton:
                drag_state["offset"] = event.globalPosition().toPoint() - win.pos()

        def header_mouse_move(event):
            if drag_state["offset"] is not None:
                win.move(event.globalPosition().toPoint() - drag_state["offset"])

        def header_mouse_release(event):
            drag_state["offset"] = None

        header.mousePressEvent = header_mouse_press
        header.mouseMoveEvent = header_mouse_move
        header.mouseReleaseEvent = header_mouse_release

        outer.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            f"""
            QScrollArea {{ background: transparent; border: 1px solid {theme.BORDER_FLAT};
                border-radius: {theme.RADIUS}px; }}
            QScrollBar:vertical {{ background: {theme.BG_VOID}; width: 8px; margin: 2px;
                border-radius: 4px; }}
            QScrollBar::handle:vertical {{ background: {theme.BORDER_FLAT}; border-radius: 4px;
                min-height: 24px; }}
            QScrollBar::handle:vertical:hover {{ background: {theme.ACCENT_CYAN}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
            QScrollBar:horizontal {{ height: 0px; }}
            """
        )
        # QScrollArea's internal viewport widget autofills with the
        # palette's (grey) Base color regardless of the QSS "background:
        # transparent" above, which only styles the frame — this is what
        # was showing as an opaque grey card behind every row. Both the
        # viewport and the content widget it hosts need to opt out too.
        scroll.viewport().setAutoFillBackground(False)
        scroll.viewport().setStyleSheet("background: transparent;")
        content = QWidget()
        content.setAutoFillBackground(False)
        content.setStyleSheet("background: transparent;")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(6, 6, 6, 6)
        content_layout.setSpacing(2)
        scroll.setWidget(content)
        outer.addWidget(scroll)

        grip_row = QHBoxLayout()
        grip_row.setContentsMargins(0, 0, 4, 2)
        grip_row.addStretch()
        size_grip = QSizeGrip(win)
        size_grip.setFixedSize(14, 14)
        size_grip.setStyleSheet("background: transparent;")

        def grip_paint_event(event):
            painter = QPainter(size_grip)
            painter.setRenderHint(QPainter.Antialiasing)
            pen = QPen(QColor(theme.ACCENT_CYAN), 1.5)
            painter.setPen(pen)
            w, h = size_grip.width(), size_grip.height()
            # Three diagonal strokes fanning from the bottom-right corner —
            # the drag-resize affordance, styled to match the window's
            # cyan chrome instead of the OS's default grey dot grip.
            for offset in (3, 7, 11):
                painter.drawLine(w - 2, h - offset, w - offset, h - 2)
            painter.end()

        size_grip.paintEvent = grip_paint_event
        grip_row.addWidget(size_grip)
        outer.addLayout(grip_row)

        return win, content_layout, opacity_slider

    def _open_route_popout(self):
        geometry = self.settings.get("tracker_geometry")
        opacity_pct = self.settings.get("tracker_opacity_pct", 100)
        title_html = (
            f'<span style="color:{theme.TEXT_PRIMARY};">mobi</span>'
            f'<span style="color:{theme.ACCENT_CYAN};">Logistics</span>'
        )
        popout, content_layout, opacity_slider = self._make_always_on_top_window(
            title_html, self._on_route_popout_closed, geometry, opacity_pct
        )
        self._route_popout_opacity_slider = opacity_slider

        self._route_popout = popout
        self._route_popout_layout = content_layout

        # Own reminder banner, added 2026-09-08 — inserted into the
        # popout's OUTER layout (index 1: right after the header, before
        # the scroll area), never into `content_layout` itself, since
        # `_populate_route_rows()` clears `content_layout` completely on
        # every render and would delete a banner living there.
        self._popout_reminder_banner = _ReminderBanner(self._dismiss_accept_reminder)
        self._popout_reminder_banner.setVisible(False)
        popout.layout().insertWidget(1, self._popout_reminder_banner)
        # A reminder already active when the Tracker is opened (e.g. it
        # fired while the popout was closed) must show up here too, not
        # just wait for the next `_show_accept_reminder`/blink tick.
        if self._reminder_text is not None:
            self._popout_reminder_banner.setText(self._reminder_text)
            self._popout_reminder_banner.setVisible(True)

        popout.show()
        self._render_results()

    def _on_route_popout_closed(self):
        if self._route_popout is not None:
            geo = self._route_popout.geometry()
            self.settings["tracker_geometry"] = {
                "x": geo.x(), "y": geo.y(), "w": geo.width(), "h": geo.height(),
            }
            if self._route_popout_opacity_slider is not None:
                self.settings["tracker_opacity_pct"] = self._route_popout_opacity_slider.value()
            self._save_settings()
            self._route_popout.close()
        self._route_popout = None
        self._route_popout_layout = None
        self._route_popout_opacity_slider = None
        self._popout_reminder_banner = None
        self._render_results()

    def _populate_contracts_rows(self, target_layout: QVBoxLayout, contracts: list[dict]):
        while target_layout.count():
            item = target_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        if not contracts:
            target_layout.addWidget(self._info_label(
                "No contracts yet. Frame one mission's pickup/drop-off "
                "text and click SCAN CONTRACT."
            ))
        else:
            for c in contracts:
                target_layout.addWidget(self._contract_row(c))
                for note in c.get("ambiguous", []):
                    target_layout.addWidget(self._ambiguous_row(note))

    @staticmethod
    def _freight_manifest(contracts: list[dict]) -> dict:
        """Commodity name -> total SCU and contract count. See grading.freight_manifest."""
        return grading.freight_manifest(contracts)

    # ------------------------------------------------------------------
    # Ship/location compatibility feedback DB + contract grading
    # (Part 3 of the confirm-gate/grading plan, 2026-09-07 — see
    # docs/DECISIONS.md). No reliable static source exists for which
    # locations physically support which ships (checked against real
    # sources, an AI-generated table was found partly fabricated) — so
    # instead of guessing, this asks GOOD/BAD once per (ship, location)
    # pair it hasn't seen, remembers the answer, and starts empty rather
    # than wrong.
    # ------------------------------------------------------------------
    @staticmethod
    def _compat_key(ship: str, terminal: dict) -> str:
        return grading.compat_key(ship, terminal)

    @staticmethod
    def _contract_terminals(contract: dict) -> list[dict]:
        """Every resolved pickup/dropoff terminal in a contract. See grading.contract_terminals."""
        return grading.contract_terminals(contract)

    def _rate_compatibility(self, ship: str, terminal: dict, good: bool) -> None:
        ratings = self.settings.setdefault("ship_location_ratings", {})
        ratings[self._compat_key(ship, terminal)] = "good" if good else "bad"
        self._save_settings()

    def _grade_contract(self, contract: dict, existing_contracts: list[dict]) -> tuple[int | None, str, bool]:
        """0-100 score + one-line reason + whether a hard warning capped it, or
        `(None, prompt, False)` without a Hauler Profile. See grading.grade_contract."""
        return grading.grade_contract(
            contract,
            existing_contracts,
            profile=self.settings.get("hauler_profile"),
            ratings=self.settings.get("ship_location_ratings"),
            capacity=self.settings.get("cargo_capacity_scu"),
            thresholds=self.settings.get("grading_thresholds"),
            current_terminal=self._current_location_terminal(),
            pickup_scu=sum(_entry_scu(e) for e in contract.get("pickups", [])),
            display_name=self._locations.display_name,
            plan_route=self._plan_route,
            peak_cargo_scu=self._peak_cargo_scu,
        )

    def _populate_manifest_rows(self, target_layout: QVBoxLayout, contracts: list[dict]):
        while target_layout.count():
            item = target_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        manifest = self._freight_manifest(contracts)
        if not manifest:
            target_layout.addWidget(self._info_label(
                "Nothing hauled yet — commodities appear here once a "
                "contract is scanned."
            ))
            return

        for name in sorted(manifest.keys()):
            row = manifest[name]
            scu, count = row["scu"], row["contract_count"]
            if count > 1:
                target_layout.addWidget(self._ambiguous_row(
                    f"{name} — {scu} SCU total, split across {count} "
                    "contracts — the game will not let you tell these "
                    "apart once picked up"
                ))
            else:
                label = QLabel(f"{name} — {scu} SCU" if scu else name)
                label.setWordWrap(True)
                label.setStyleSheet(
                    f"background: {theme.BG_PANEL}; color: {theme.TEXT_PRIMARY}; "
                    f"border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px; "
                    f"padding: 5px 8px; font-family: {theme.FONT_MONO}; "
                    f"font-size: {theme.fpx(10)}px;"
                )
                target_layout.addWidget(label)

    @staticmethod
    def _title_style() -> str:
        return (
            f"color: {theme.ACCENT_CYAN}; font-family: {theme.FONT_DISPLAY}; "
            f"font-weight: 800; font-size: {theme.fpx(11)}px; letter-spacing: 2px;"
        )

    @staticmethod
    def _entry_names(entries: list[dict], display_name) -> str:
        names = []
        for e in entries:
            base = display_name(e["terminal"]) if e.get("terminal") else f"{e.get('raw', '??')} (unresolved)"
            names.append(f"{base} ({_cargo_label(e.get('commodities'))})")
        return " / ".join(names) if names else "??"

    def _contract_row(self, contract: dict) -> QWidget:
        pickups_text = self._entry_names(contract.get("pickups", []), self._locations.display_name)
        dropoffs_text = self._entry_names(contract.get("dropoffs", []), self._locations.display_name)
        reward = contract.get("reward")
        reward_text = f"  ·  {reward} aUEC" if reward else ""

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(4)

        label = QLabel(f"{pickups_text} → {dropoffs_text}{reward_text}")
        label.setWordWrap(True)
        label.setStyleSheet(
            f"background: {theme.BG_PANEL}; color: {theme.TEXT_PRIMARY}; "
            f"border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px; "
            f"padding: 5px 8px; font-family: {theme.FONT_MONO}; "
            f"font-size: {theme.fpx(10)}px;"
        )
        row_layout.addWidget(label, 1)

        remove_btn = QPushButton("✕")
        remove_btn.setToolTip("Remove this contract")
        remove_btn.setFixedWidth(22)
        remove_btn.setStyleSheet(
            f"background: {theme.BG_VOID}; color: {theme.ACCENT_AMBER}; "
            f"border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px; "
            f"font-family: {theme.FONT_MONO}; font-size: {theme.fpx(10)}px;"
        )
        remove_btn.clicked.connect(lambda: self._remove_contract(contract.get("id")))
        row_layout.addWidget(remove_btn)

        return row

    def _remove_contract(self, contract_id: str | None):
        contracts = self.settings.get("contracts", [])
        self.settings["contracts"] = [c for c in contracts if c.get("id") != contract_id]
        self._save_settings()
        if self.settings["contracts"]:
            self._route_order = self._plan_route(self.settings["contracts"])
        else:
            self._route_order = []
        self._render_results()
        self._set_status("Contract removed.")

    def _route_row(self, text: str, route_key: str, done: bool, transparent_bg: bool = False) -> QWidget:
        row = QLabel(text)
        row.setWordWrap(True)
        row.setCursor(Qt.PointingHandCursor)
        row.setToolTip("Click to mark this stop done/skipped")
        # In the Tracker popout, each row's own solid background would sit
        # as an opaque "card" on top of the window's faded void, making the
        # opacity slider barely visible — transparent here so the row's
        # background fades with the window while the text itself (drawn on
        # top by Qt, not affected by a background fill) stays fully legible.
        bg = "transparent" if transparent_bg else theme.BG_VOID
        if done:
            row.setStyleSheet(
                f"background: {bg}; color: {theme.TEXT_DIM}; "
                f"border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px; "
                f"padding: 5px 8px; font-family: {theme.FONT_MONO}; "
                f"font-size: {theme.fpx(10)}px; text-decoration: line-through;"
            )
        else:
            row.setStyleSheet(
                f"background: {bg}; color: {theme.ACCENT_CYAN}; "
                f"border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px; "
                f"padding: 5px 8px; font-family: {theme.FONT_MONO}; "
                f"font-size: {theme.fpx(10)}px;"
            )
        row.mousePressEvent = lambda event: self._toggle_route_done(route_key)
        return row

    def _toggle_route_done(self, route_key: str):
        route_done = set(self.settings.get("route_done", []))
        if route_key in route_done:
            route_done.discard(route_key)
        else:
            route_done.add(route_key)
        self.settings["route_done"] = list(route_done)
        self._save_settings()
        self._render_results()

    def _ambiguous_row(self, text: str) -> QWidget:
        """A location phrase that matched more than one distinct real
        place (see the `ambiguous` note in `_build_contract`) — surfaced
        visibly rather than silently guessing one and possibly being
        wrong. Amber, same as the card's own error-state accent."""
        row = QLabel(f"⚠ {text}")
        row.setWordWrap(True)
        row.setStyleSheet(
            f"background: {theme.ACCENT_AMBER_DIM}; color: {theme.ACCENT_AMBER}; "
            f"border: 1px solid {theme.ACCENT_AMBER}; border-radius: {theme.RADIUS}px; "
            f"padding: 5px 8px; font-family: {theme.FONT_MONO}; "
            f"font-size: {theme.fpx(9)}px;"
        )
        return row

    def _info_label(self, text: str) -> QWidget:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-family: {theme.FONT_MONO}; "
            f"font-size: {theme.fpx(8)}px;"
        )
        return label

