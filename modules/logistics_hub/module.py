"""Logistics Hub – OCR driven hauling mission board helper.

Captures a user‑selected region of the screen (over the in‑game mission
board), runs OCR against the captured image, and turns each scan into a
**contract** (one or more pickups, one or more drop‑offs, and a reward —
real contracts use both "DROP OFF LOCATIONS (ANY ORDER)" and "PICK UP
LOCATIONS (ANY ORDER)" panels). Contracts accumulate across scans —
scanning a second mission board page adds to the list instead of replacing
it — so several contracts can be queued up before planning one combined
route across every pickup and drop-off.

The module lives entirely under ``modules/logistics_hub/`` and intentionally
does **not** use any host‑side screen‑capture or OCR helpers. All new
third‑party dependencies are declared in the local :file:`requirements.txt`
so the base project stays clean.

Chosen OCR engine: **easyocr** – permissively licensed (Apache 2.0)
and fully pip‑installable on Windows, which avoids making the user
install a separate Tesseract binary. The tradeoff is a much heavier
download (it pulls in PyTorch and torchvision), so it may take a few
seconds on first use.

Route optimization: OCR'd location text is resolved against the shared
Core location service (``host/locations.py`` — every module gets its own
``LocationService`` instance, backed by a session-cached, disk-persisted
index over UEX's ``terminals``/``space_stations``/``outposts``/``cities``
data) to find the real terminal/planet/system a location name refers to,
then a nearest‑neighbour visiting order is planned using
a hierarchy-aware travel cost (same terminal < same body < same system <
different system) instead of guessing from raw text similarity alone. A
location that can't be resolved against UEX data falls back to a
text-similarity heuristic so the module still produces *something*
usable, clearly marked as unresolved.

The route always starts from the CURRENT LOCATION picker's selection (a
searchable combo over the same location data), not an arbitrary contract's
pickup — and never visits a drop-off before every pickup on its own
contract has been visited, since cargo can't be delivered before it's
been collected.
"""
import re
import time
import uuid

from PySide6.QtCore import Qt, QRect, QPoint, QTimer, Signal
from PySide6.QtGui import (
    QGuiApplication,
    QImage,
    QPainter,
    QColor,
    QPen,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QCompleter,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from host import theme
from host.locations import LocationService
from host.module_base import ModuleBase

import logging

logger = logging.getLogger("mobioverlay.logistics_hub")

# ---------------------------------------------------------------------------
# Optional third‑party dependencies – imported lazily so the module can still
# load if the user has not yet installed the local requirements.txt.
# ---------------------------------------------------------------------------
try:
    import easyocr  # type: ignore
    from PIL import Image, ImageOps  # type: ignore

    OCR_AVAILABLE = True
except ImportError:
    easyocr = None  # type: ignore
    Image = None  # type: ignore
    ImageOps = None  # type: ignore
    OCR_AVAILABLE = False

AUTO_RESCAN_MS = 5 * 60 * 1000  # 5 minutes, off by default

# Hierarchy-aware travel cost when both endpoints resolved against UEX data.
COST_SAME_TERMINAL = 0
COST_SAME_BODY = 1       # same planet/moon/space station/city/outpost
COST_SAME_SYSTEM = 2
COST_DIFFERENT_SYSTEM = 5
COST_UNRESOLVED = 3       # at least one side has no API match — text-heuristic territory


def _virtual_desktop_rect() -> QRect | None:
    """Return the union of all Qt screen geometries (multi‑monitor aware)."""
    screens = QGuiApplication.screens()
    if not screens:
        return None
    rect = screens[0].geometry()
    for sc in screens[1:]:
        rect = rect.united(sc.geometry())
    return rect


_PICKUP_COMMODITY_RE = re.compile(r"\bcollect\s+(.+?)\s+from\s+(.+)", re.I)
_DROPOFF_COMMODITY_RE = re.compile(r"\bdeliver\s+[\d/]*\s*scu\s+of\s+(.+?)\s+to\s+(.+)", re.I)


def _extract_commodities(raw_text: str, location_raw: str, role: str) -> list[str]:
    """What cargo is actually changing hands at one pickup/drop-off — the
    thing the module never surfaced at all before, even though every real
    contract line spells it out ("Collect Silicon from...", "Deliver...of
    Waste to..."). A location only needs to appear *somewhere* on the same
    line as the commodity mention for it to count — doesn't need to be the
    exact candidate string that resolved it (OCR line-wraps and station
    codes mean the two rarely match exactly), just a substring match after
    stripping non-alphanumerics from both sides.

    A single location can have more than one commodity moving through it
    (contract 3: Long Forest Station -> Waste on one scan, Scrap on a
    different mission built around the same pickup) — collect every
    distinct match rather than stopping at the first, so the picked-up/
    delivered items shown for a stop are never silently incomplete.
    """
    loc_key = re.sub(r"[^a-z0-9]", "", location_raw.lower())
    if not loc_key:
        return []
    pattern = _PICKUP_COMMODITY_RE if role == "pickup" else _DROPOFF_COMMODITY_RE

    found: list[str] = []
    seen: set[str] = set()
    for line in raw_text.splitlines():
        m = pattern.search(line)
        if not m:
            continue
        loc_part = re.sub(r"[^a-z0-9]", "", m.group(2).lower())
        if loc_key not in loc_part:
            continue
        commodity = re.sub(r"[.:_,;]+$", "", m.group(1)).strip()
        key = commodity.lower()
        if commodity and key not in seen:
            seen.add(key)
            found.append(commodity)
    return found


def _extract_reward(raw_text: str) -> str | None:
    # aUEC amounts are comma-grouped ("50,250") — that's a much more
    # reliable signal than the word "reward" itself, since OCR frequently
    # mangles the reward icon glyph next to it into stray characters
    # ("4 50,250" for what's actually "▲ 50,250" in-game).
    m = re.search(r"(\d{1,3}(?:,\d{3})+)", raw_text)
    return m.group(1) if m else None


# Real contract panels are full of chrome/flavor text around the actual
# pickup/drop-off names ("Contract Deadline", "PRIMARY OBJECTIVES", the
# contractor's own name, UI buttons like "ABANDON"/"SHARE"/"TRACK"). None
# of that will ever match a real UEX terminal, so it's harmless noise once
# every candidate gets checked against the API — but filtering the most
# common chrome up front keeps the candidate list (and any manual review
# of "(unresolved)" entries) shorter and easier to read.
_PHRASE_STOPWORDS = {
    "reward", "contract deadline", "contracted by", "details",
    "primary objectives", "drop off locations", "abandon", "share",
    "track", "any order", "lagrange point", "rookie", "small haul",
    "collect stims", "freight elevator",
}


_DROPOFF_SECTION_RE = re.compile(r"drop.?off locations", re.I)
_PICKUP_SECTION_RE = re.compile(r"pick.?up locations", re.I)
_PICKUP_HINT_RE = re.compile(r"\bcollect\b|\bpick(?:ed|ing)?\s*up\b", re.I)
_DROPOFF_HINT_RE = re.compile(r"\bdeliver(?:ed)?\b.*\bto\b", re.I)


def _candidate_phrases(raw_text: str) -> list[tuple[str, str]]:
    """Extract plausible location-name phrases (2-4 capitalized words) from
    every line of the OCR text, tagged with a role hint ("pickup",
    "dropoff", or "neutral") based on nearby keywords / whether the line
    falls under a "DROP OFF LOCATIONS" or "PICK UP LOCATIONS" section
    header (real contracts use either, one pickup with several drop-offs
    or one drop-off with several pickups). Deduped, in first-seen order
    (first hint wins on a repeat).

    Deliberately over-generates candidates — a contract panel mentions its
    real pickup/drop-off names multiple times across different sentences,
    often with an OCR error in any single mention, so casting wide and
    letting `_resolve_location` filter against real UEX data is far more
    robust than trying to regex-parse the narrative structure exactly
    right. The hint only decides *role* (pickup vs. drop-off) once a
    candidate is already confirmed real by the API — it never invents a
    location that isn't a genuine phrase match.
    """
    candidates: list[tuple[str, str]] = []
    seen: dict[str, int] = {}  # normalized phrase -> index in candidates
    section_hint = None  # None, "pickup", or "dropoff" — set by a section header

    for line in raw_text.splitlines():
        if _DROPOFF_SECTION_RE.search(line):
            section_hint = "dropoff"
            continue
        if _PICKUP_SECTION_RE.search(line):
            section_hint = "pickup"
            continue
        # A per-line keyword ("Collect X from Y" / "Deliver X to Y") is a
        # more specific signal than which section we're currently under —
        # e.g. contract 3's PICK UP LOCATIONS section still had "Deliver
        # ...to Port Tressler" lines mixed in among its pickups.
        if _PICKUP_HINT_RE.search(line):
            hint = "pickup"
        elif _DROPOFF_HINT_RE.search(line):
            hint = "dropoff"
        elif section_hint is not None and re.search(r"\bat\b", line, re.I):
            # The section header applies until the panel ends, but nothing
            # marks that end explicitly — so don't trust it forever. Real
            # list rows under either header ("Freight elevator at X at Y's
            # L# Lagrange point") always contain "at"; trailing signature/
            # footer text (contractor name, "Jr. Logistics Coordinator",
            # the company name, ABANDON/SHARE/TRACK buttons) never does,
            # so require it rather than tagging everything after the header.
            hint = section_hint
        else:
            hint = "neutral"

        def add_candidate(phrase: str, phrase_hint: str) -> None:
            key = phrase.lower()
            if key in _PHRASE_STOPWORDS or len(phrase) < 5:
                return
            if key in seen:
                idx = seen[key]
                # A later, more specific hint (pickup/dropoff) upgrades an
                # earlier "neutral" tag for the same phrase.
                if candidates[idx][1] == "neutral" and phrase_hint != "neutral":
                    candidates[idx] = (candidates[idx][0], phrase_hint)
                return
            seen[key] = len(candidates)
            candidates.append((phrase, phrase_hint))

        for m in re.finditer(r"[A-Z][a-zA-Z']+(?:\s+[A-Z][a-zA-Z']+){1,3}", line):
            words = m.group(0).split()
            phrase = " ".join(words)
            add_candidate(phrase, hint)
            # A leading word that's very short (≤3 chars — "Lz", "Ll", "LI",
            # "L2"...) is almost always a station-code fragment the capital-
            # word regex swept up because a hyphen ("MIC-L1") broke it away
            # from its own "MIC" prefix, not part of the real place name.
            # OCR also frequently mis-reads the digit in these codes as a
            # letter (L1 -> "Ll"/"LI"/"Lz"), which breaks exact/substring
            # matching against the real UEX name — so also offer the phrase
            # with that leading fragment stripped; if it's wrong, resolution
            # just returns None and it's discarded, no harm done.
            if len(words) >= 3 and len(words[0]) <= 3:
                add_candidate(" ".join(words[1:]), hint)

        # Many real UEX outposts/terminals are named as a single hyphenated
        # token — "HDMS-Edmond", "HDMS-Thedus" — with no second
        # space-separated word at all. The multi-word regex above requires
        # 2+ words, so these were completely invisible to it; a contract
        # naming several such outposts lost every one of them. Catch them
        # separately: 2+ leading capitals, then one or more "-word" segments.
        # A trailing OCR artifact right after the real name — an errant
        # underscore standing in for a period, e.g. "HDMS-Edmond_" — was
        # silently blocking \b, since \b treats "_" as a word character
        # with no boundary against a letter. Use an explicit non-alnum (or
        # end-of-string) lookahead/lookbehind instead so stray punctuation
        # like that can't swallow an otherwise-clean match.
        for m in re.finditer(
            r"(?<![A-Za-z0-9])[A-Z]{2,}(?:-[A-Za-z0-9]+)+(?=[^A-Za-z0-9]|$)", line
        ):
            # If a capitalized word immediately follows ("MIC-L1 Shallow
            # Frontier Station"), the multi-word regex above already
            # captured the fuller, more specific phrase — and separately
            # offers a code-stripped variant of it too. Adding the bare
            # code as *another* independent candidate here doesn't help in
            # that case and can actively hurt: some real UEX shops are
            # nicknamed with the exact same bare station code as the
            # station itself ("Landing Services - MIC-L1" vs. the actual
            # "MIC-L1 Shallow Frontier Station"), so resolving the bare
            # code alone can land on the wrong one of the two and show up
            # as a spurious duplicate stop. Only offer it standalone when
            # nothing more descriptive follows on the line.
            if re.match(r"\s+[A-Z]", line[m.end():]):
                continue
            add_candidate(m.group(0), hint)

    return candidates


class _RegionSelector(QWidget):
    """Full‑screen transparent widget used to drag‑draw a capture rectangle.

    Only shows on the screen where the cursor is at the moment the user
    clicks “SELECT REGION”.  Coordinates emitted in global desktop space.
    """

    selected = Signal(QRect)

    def __init__(self, desktop_rect: QRect):
        super().__init__()
        self._desktop_rect = desktop_rect
        self._start = None
        self._end = None

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setCursor(Qt.CrossCursor)
        self.setFocusPolicy(Qt.StrongFocus)

        self.setGeometry(desktop_rect)
        self.show()
        self.raise_()
        self.setFocus(Qt.OtherFocusReason)

    # ---- painting -----------------------------------------------------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        # Dim the whole screen slightly so the capture rectangle stands out.
        painter.fillRect(self.rect(), QColor(0, 0, 0, 70))

        if self._start is not None and self._end is not None:
            rect = QRect(self._start, self._end).normalized()

            # translucent cyan fill behind the future capture boundaries
            brush = QColor(theme.ACCENT_CYAN)
            brush.setAlpha(70)
            painter.fillRect(rect, brush)

            pen = QPen(QColor(theme.ACCENT_CYAN), 1, Qt.DashLine)
            painter.setPen(pen)
            painter.drawRect(rect.adjusted(0, 0, -1, -1))

    # ---- mouse/key handling -------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._start = event.position().toPoint()
            self._end = None
            self.update()

    def mouseMoveEvent(self, event):
        if self._start is not None:
            self._end = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):
        if (
            event.button() == Qt.LeftButton
            and self._start is not None
            and self._end is not None
        ):
            local_rect = QRect(self._start, self._end).normalized()
            global_top_left = self.geometry().topLeft() + local_rect.topLeft()
            self.selected.emit(QRect(global_top_left, local_rect.size()))
        self._finish()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._finish()
        else:
            super().keyPressEvent(event)

    def _finish(self):
        self._start = None
        self._end = None
        self.close()
        self.deleteLater()


class LogisticsHubModule(ModuleBase):
    module_id = "logistics_hub"
    display_name = "Logistics Hub"

    def __init__(self, api_client, config):
        super().__init__(api_client, config)
        self._selector = None
        self._timer = None
        self._card_widget = None
        self._reader = None
        # Shared Core service (host/locations.py) — one place resolving/
        # caching UEX location data for every module, not this module's
        # own copy. See docs/DECISIONS.md, 2026-09-04, for why this lives
        # in Core rather than as a "location module" other modules depend on.
        self._locations = LocationService(api_client)
        self._location_choices: dict[str, dict] = {}  # display name -> terminal row, for the picker
        # A "node" is one stop to visit: (contract_index, "pickup"/"dropoff",
        # index within that role's list) — a contract can have several
        # pickups or several drop-offs (real panels use both DROP OFF
        # LOCATIONS (ANY ORDER) and PICK UP LOCATIONS (ANY ORDER)).
        self._route_order: list[tuple[int, str, int]] = []
        # host/main.py calls refresh() once automatically right after every
        # module's card is created (its "initial fetch"). For this module
        # that means OCR-ing whatever's on screen at the last saved region
        # before the user has touched anything — useless (and often wrong)
        # if the game isn't even open yet. Treat that first automatic call
        # as a no-op; only an explicit SCAN click or the opt-in auto-rescan
        # timer should trigger a real capture. This is a module-local
        # workaround, not a core change — main.py's shared startup-refresh
        # behavior is unchanged for every other module.
        self._started = False

    # ------------------------------------------------------------------
    # Card construction
    # ------------------------------------------------------------------
    def create_card(self, container):
        card = container.add_card(self.module_id, self.display_name)
        self._card_widget = card
        layout = card.body_layout

        # ---- current location picker ----------------------------------
        # The route planner needs a starting point — without one it can
        # only guess (previously it silently started from whichever
        # contract's pickup happened to be scanned first, which is only
        # right by coincidence). Same editable-combo-with-completer pattern
        # trade_route_optimizer uses for its terminal picker.
        location_row = QHBoxLayout()
        location_label = QLabel("LOCATION")
        location_label.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-family: {theme.FONT_MONO}; "
            f"font-size: {theme.fpx(9)}px; letter-spacing: 1px;"
        )
        location_row.addWidget(location_label)

        self._location_combo = QComboBox()
        self._location_combo.setEditable(True)
        self._location_combo.setInsertPolicy(QComboBox.NoInsert)
        self._location_combo.setStyleSheet(
            f"""
            QComboBox {{
                background: {theme.BG_VOID}; color: {theme.ACCENT_CYAN};
                border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px;
                padding: 4px 6px; font-family: "{theme.FONT_DISPLAY}"; font-weight: 700;
                font-size: {theme.fpx(11)}px;
            }}
            """
        )
        location_completer = QCompleter(self._location_combo.model(), self._location_combo)
        location_completer.setCaseSensitivity(Qt.CaseInsensitive)
        location_completer.setFilterMode(Qt.MatchContains)
        location_completer.setCompletionMode(QCompleter.PopupCompletion)
        self._location_combo.setCompleter(location_completer)
        # textActivated (not currentTextChanged) — same reasoning as
        # trade_route_optimizer's terminal combo: this one's editable/
        # searchable, so currentTextChanged would fire (and try to resolve
        # a location, replan, and error) on every keystroke.
        self._location_combo.textActivated.connect(self._on_location_selected)
        location_row.addWidget(self._location_combo, 1)
        layout.addLayout(location_row)

        # ---- region status row --------------------------------------
        region_row = QHBoxLayout()
        self._region_label = QLabel("Region: not set")
        self._region_label.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-family: {theme.FONT_MONO}; "
            f"font-size: {theme.fpx(9)}px; letter-spacing: 1px;"
        )
        region_row.addWidget(self._region_label, 1)

        select_btn = QPushButton("SELECT REGION")
        select_btn.setStyleSheet(self._button_style())
        select_btn.clicked.connect(self._select_region)
        region_row.addWidget(select_btn)
        layout.addLayout(region_row)

        # ---- action row ---------------------------------------------
        action_row = QHBoxLayout()
        self._status_label = QLabel("Ready")
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet(
            f"color: {theme.TEXT_PRIMARY}; font-family: {theme.FONT_MONO}; "
            f"font-size: {theme.fpx(9)}px;"
        )
        action_row.addWidget(self._status_label, 1)

        self._scan_btn = QPushButton("SCAN CONTRACT")
        self._scan_btn.setToolTip(
            "Captures the region as one contract. Location phrases found in "
            "the text are checked against real UEX data — the first match "
            "becomes the pickup, the rest become drop-offs. Frame one "
            "mission's detail panel per scan."
        )
        self._scan_btn.setStyleSheet(self._button_style())
        self._scan_btn.clicked.connect(self._safe_scan)
        action_row.addWidget(self._scan_btn)

        clear_btn = QPushButton("CLEAR")
        clear_btn.setStyleSheet(self._button_style())
        clear_btn.clicked.connect(self._clear_contracts)
        action_row.addWidget(clear_btn)

        copy_btn = QPushButton("COPY ROUTE")
        copy_btn.setToolTip("Copies the suggested route (and full contract details) to the clipboard as plain text.")
        copy_btn.setStyleSheet(self._button_style())
        copy_btn.clicked.connect(self._copy_route_to_clipboard)
        action_row.addWidget(copy_btn)
        layout.addLayout(action_row)

        # ---- optional auto-rescan toggle -----------------------------
        auto_row = QHBoxLayout()
        self._auto_check = QCheckBox("AUTO RESCAN")
        self._auto_check.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-family: {theme.FONT_MONO}; "
            f"font-size: {theme.fpx(9)}px;"
        )
        self._auto_check.setChecked(bool(self.settings.get("auto_rescan")))
        self._auto_check.toggled.connect(self._toggle_auto_rescan)
        auto_row.addWidget(self._auto_check)
        auto_row.addStretch()
        layout.addLayout(auto_row)

        # ---- scrollable contracts / route list ------------------------
        self._results_scroll = QScrollArea()
        self._results_scroll.setWidgetResizable(True)
        self._results_scroll.setStyleSheet(
            f"QScrollArea {{ background: transparent; border: 1px solid {theme.BORDER_FLAT}; "
            f"border-radius: {theme.RADIUS}px; }}"
        )

        self._results_widget = QWidget()
        self._results_layout = QVBoxLayout(self._results_widget)
        self._results_layout.setContentsMargins(8, 8, 8, 8)
        self._results_layout.setSpacing(4)
        self._results_scroll.setWidget(self._results_widget)

        layout.addWidget(self._results_scroll, 1)

        self._results_scroll.setMinimumHeight(180)
        self._results_scroll.setMaximumHeight(360)

        # Timer for opt-in 5-minute auto rescanning.
        self._timer = QTimer(card)
        self._timer.setInterval(AUTO_RESCAN_MS)
        self._timer.timeout.connect(self._safe_scan)
        if self.settings.get("auto_rescan"):
            self._timer.start()

        self._refresh_region_label()
        self._populate_location_combo()
        self._render_results()
        card.apply_size()
        return card

    @staticmethod
    def _button_style() -> str:
        return (
            f"background: {theme.BG_VOID}; color: {theme.ACCENT_CYAN}; "
            f"border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px; "
            f"padding: 4px 8px; font-family: {theme.FONT_DISPLAY}; font-weight: 700; "
            f"font-size: {theme.fpx(11)}px;"
        )

    # ------------------------------------------------------------------
    # UI helpers
    # ------------------------------------------------------------------
    def _refresh_region_label(self):
        region = self.settings.get("region")
        if region:
            text = f"XY {region.get('x')},{region.get('y')}  {region.get('w')}×{region.get('h')}"
        else:
            text = "Region: not set"
        self._region_label.setText(text)

    def _set_status(self, msg: str):
        if getattr(self, "_status_label", None) is not None:
            self._status_label.setText(msg)

    def _clear_error_state(self):
        """Make sure the card body (with the SELECT REGION button) is visible
        even if the host previously put this card into its error state due to
        a missing capture region."""
        card = getattr(self, "_card_widget", None)
        if card is not None:
            card.clear_error()

    def _select_region(self):
        desktop = _virtual_desktop_rect()
        if desktop is None:
            return
        selector = _RegionSelector(desktop)
        selector.selected.connect(self._on_region_selected)
        self._selector = selector  # keep a reference so the GC doesn't reap it

    def _on_region_selected(self, rect: QRect):
        self.settings["region"] = {
            "x": rect.x(),
            "y": rect.y(),
            "w": rect.width(),
            "h": rect.height(),
        }
        self._save_settings()
        self._refresh_region_label()
        self._set_status("Region saved.")

    def _populate_location_combo(self):
        """Fill the current-location picker from the shared Core location
        service (host/locations.py) — synchronous, same pattern
        trade_route_optimizer uses to populate its system/terminal combos
        in create_card(). Restores the last-saved location, if any."""
        self._location_choices = {}
        for row in self._locations.all_locations():
            label = self._locations.search_label(row)
            if label in self._location_choices and self._location_choices[label] is not row:
                # Two distinct locations produced the same label (rare, but
                # possible across systems) — disambiguate rather than
                # silently dropping one from the picker. This is a picker-UI
                # concern, not something the shared service decides for us.
                system = row.get("star_system_name")
                if system:
                    label = f"{label} [{system}]"
            self._location_choices[label] = row
        names = sorted(self._location_choices.keys())

        self._location_combo.blockSignals(True)
        self._location_combo.clear()
        self._location_combo.addItems(names)
        saved_name = self.settings.get("current_location_name", "")
        if saved_name in self._location_choices:
            self._location_combo.setCurrentText(saved_name)
        else:
            self._location_combo.setCurrentText("")
        self._location_combo.blockSignals(False)

    def _on_location_selected(self, name: str):
        terminal = self._location_choices.get(name)
        if terminal is None:
            self._set_status(f"Unknown location: {name}")
            return
        self.settings["current_location_name"] = name
        self.settings["current_location"] = terminal
        self._save_settings()
        self._set_status(f"Location set: {name}")
        # Where we start from just changed — replan immediately rather than
        # waiting for the next scan, so the picker feels responsive.
        contracts = self.settings.get("contracts", [])
        if contracts:
            self._route_order = self._plan_route(contracts)
            self._render_results()

    def _current_location_terminal(self) -> dict | None:
        return self.settings.get("current_location")

    def _toggle_auto_rescan(self, enabled: bool):
        self.settings["auto_rescan"] = bool(enabled)
        self._save_settings()
        if enabled:
            self._timer.start()
            self._set_status("Auto rescan enabled.")
        else:
            self._timer.stop()
            self._set_status("Auto rescan disabled.")

    def _save_settings(self):
        self.config.set_module_settings(self.module_id, self.settings)

    def _clear_contracts(self):
        self.settings["contracts"] = []
        self._save_settings()
        self._route_order = []
        self._render_results()
        self._set_status("Contracts cleared.")

    def _format_route_text(self) -> str:
        """Plain-text export of the current contracts + suggested route —
        primarily for debugging (so raw OCR text and resolution status are
        included alongside the clean names, not just what the card shows),
        but kept in the shipped app since it's also just a handy way to
        get a route out of the overlay and into a notepad/Discord message."""
        contracts = self.settings.get("contracts", [])
        lines = [
            f"Logistics Hub — Route Export ({time.strftime('%Y-%m-%d %H:%M:%S')})",
        ]

        start_terminal = self._current_location_terminal()
        start_name = self._locations.display_name(start_terminal) if start_terminal else "(not set)"
        lines.append(f"Starting location: {start_name}")
        lines.append("")

        lines.append(f"CONTRACTS ({len(contracts)})")
        if not contracts:
            lines.append("  (none)")
        for idx, contract in enumerate(contracts, start=1):
            reward = contract.get("reward")
            reward_text = f" · {reward} aUEC" if reward else ""
            lines.append(f"  {idx}. scanned {contract.get('scanned_at', '?')}{reward_text}")
            for role_key, role_label in (("pickups", "PICKUP"), ("dropoffs", "DROPOFF")):
                for entry in contract.get(role_key, []):
                    terminal = entry.get("terminal")
                    name = self._locations.display_name(terminal) if terminal else f"{entry.get('raw', '??')} [UNRESOLVED]"
                    commodities = entry.get("commodities") or []
                    cargo = f" ({'/'.join(commodities)})" if commodities else ""
                    raw = entry.get("raw", "??")
                    lines.append(f"     [{role_label}] {name}{cargo}  (OCR text: {raw!r})")
        lines.append("")

        lines.append("SUGGESTED VISITING ORDER")
        if not self._route_order:
            lines.append("  (none)")
        for step, node in enumerate(self._route_order, start=1):
            i, role, j = node
            contract = contracts[i] if i < len(contracts) else None
            if contract is None:
                continue
            key = "pickups" if role == "pickup" else "dropoffs"
            items = contract.get(key, [])
            entry = items[j] if j < len(items) else {}
            terminal = entry.get("terminal")
            name = self._locations.display_name(terminal) if terminal else f"{entry.get('raw', '??')} [UNRESOLVED]"
            commodities = entry.get("commodities") or []
            cargo = f" — {'/'.join(commodities)}" if commodities else ""
            role_tag = "PICKUP" if role == "pickup" else "DROPOFF"
            lines.append(f"  {step}. [{role_tag}] {name}{cargo}")

        return "\n".join(lines)

    def _copy_route_to_clipboard(self):
        text = self._format_route_text()
        QGuiApplication.clipboard().setText(text)
        self._set_status("Route copied to clipboard.")

    def _safe_scan(self):
        # OCR (first call loads an easyocr model — can take several seconds
        # — plus every call after that runs real inference) and the UEX API
        # calls in refresh() are both fully synchronous on the GUI thread
        # (see host/main.py's module-contract note on this); there's no
        # progress signal to hook into without a threading redesign, which
        # is out of scope here. The honest, cheap fix: flip the button into
        # an obvious busy state and force Qt to actually paint it *before*
        # the blocking call starts, so a first-time user doesn't mistake a
        # long pause for a hang.
        btn = getattr(self, "_scan_btn", None)
        if btn is not None:
            btn.setEnabled(False)
            btn.setText("SCANNING…")
        self._set_status("Scanning — this can take a few seconds…")
        QApplication.processEvents()
        try:
            self.refresh()
        except Exception as exc:
            self._set_status(f"Error: {exc}")
        finally:
            if btn is not None:
                btn.setText("SCAN CONTRACT")
                btn.setEnabled(True)

    # ------------------------------------------------------------------
    # ModuleBase refresh
    # ------------------------------------------------------------------
    def refresh(self):
        """Capture the selected region, OCR it into one new contract, append
        it to the persisted contract list, resolve locations against UEX
        data, and replan the combined route across every contract."""
        if not self._started:
            self._started = True
            self._set_status("Ready — click SCAN CONTRACT to capture one.")
            return

        region = self.settings.get("region")
        if not region:
            self._set_status("No capture region set — use SELECT REGION on the card first.")
            self._clear_error_state()
            return
        if not OCR_AVAILABLE:
            raise RuntimeError(
                "easyocr/Pillow not installed. Run:\n"
                "  pip install -r modules/logistics_hub/requirements.txt"
            )

        pix = self._grab_region(region)
        raw_text = self._ocr(pix)
        logger.info("logistics_hub OCR raw text:\n%s", raw_text)

        contract = self._build_contract(raw_text)
        if contract is None:
            raise ValueError("No usable text could be OCR'd — try adjusting the region or brightness.")

        contracts = self.settings.setdefault("contracts", [])
        contracts.append(contract)
        self._save_settings()

        self._route_order = self._plan_route(contracts)
        self._render_results()
        self._set_status(
            f"Added contract ({len(contracts)} total) at {time.strftime('%H:%M:%S')}"
        )

    # ------------------------------------------------------------------
    # Screen capture / OCR
    # ------------------------------------------------------------------
    def _grab_region(self, region: dict):
        x, y, w, h = int(region["x"]), int(region["y"]), int(region["w"]), int(region["h"])
        point = QPoint(x, y)
        screen = QGuiApplication.screenAt(point)
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            raise RuntimeError("No screen is available for capture.")

        local_x = x - screen.geometry().x()
        local_y = y - screen.geometry().y()
        return screen.grabWindow(0, local_x, local_y, w, h)

    def _ocr(self, pixmap):
        """Runs EasyOCR over the given QPixmap and returns raw text."""
        # Convert QPixmap → QImage → PIL image. In PySide6/Qt6, QImage.bits()
        # already returns a correctly-sized Python memoryview (unlike PyQt5's
        # sip.voidptr, which needed .setsize() to become buffer-like) — wrap
        # it in bytes() and hand it straight to PIL.
        qimg = pixmap.toImage().convertToFormat(QImage.Format_RGBA8888)
        buf = bytes(qimg.bits())
        pil_rgba = Image.frombuffer(
            "RGBA", (qimg.width(), qimg.height()), buf, "raw", "RGBA", 0, 1
        )
        pil_rgb = pil_rgba.convert("RGB")

        # Preprocess a little for the OCR engine.
        gray = ImageOps.grayscale(pil_rgb)
        gray = ImageOps.autocontrast(gray)

        if self._reader is None:
            self._reader = easyocr.Reader(["en"], gpu=False, verbose=False)

        import numpy as np
        result = self._reader.readtext(np.array(gray), detail=0)
        return "\n".join(result)

    # ------------------------------------------------------------------
    # Location resolution now lives in the shared Core service
    # (host/locations.py, self._locations) — a mission's drop-off is very
    # often a pure delivery point (a space station/outpost/city) with no
    # commodity trading kiosk at all, and different location endpoints
    # have colliding raw ids for unrelated real places, both handled
    # there once for every module instead of per-module. See
    # docs/DECISIONS.md, 2026-09-04, for the full history.
    # ------------------------------------------------------------------

    def _build_contract(self, raw_text: str) -> dict | None:
        """Build one contract from a scan's OCR text: pull every plausible
        location phrase, resolve each against real UEX terminal data, and
        split the distinct resolved terminals into pickups vs. drop-offs by
        role hint. A contract can have several of *either* — real panels use
        one pickup with several drop-offs (DROP OFF LOCATIONS (ANY ORDER))
        just as often as one drop-off with several pickups (PICK UP
        LOCATIONS (ANY ORDER)). Falls back to raw, unresolved candidate
        phrases if nothing resolved at all, so a scan still produces
        something reviewable instead of silently failing."""
        candidates = _candidate_phrases(raw_text)  # list of (phrase, hint)
        reward = _extract_reward(raw_text)

        # Resolve every candidate against real UEX data, deduped by
        # terminal id (falling back to normalized text for records with no
        # id) so a second OCR mention of the same real place can *upgrade*
        # an earlier neutral-hinted match to pickup/dropoff instead of being
        # silently discarded — losing that hint was a real bug: an
        # OCR-garbled second mention ("MIC-Lz Long Forest Station") sat
        # right next to "Collect", the clearest pickup signal in the whole
        # panel, and got dropped for resolving to the same id as an
        # earlier, hint-less mention.
        resolved_by_key: dict = {}
        order: list = []
        for text, hint in candidates:
            terminal = self._locations.resolve(text)
            if terminal is None:
                continue
            key = self._locations.terminal_key(terminal)
            if key not in resolved_by_key:
                resolved_by_key[key] = [text, terminal, hint]
                order.append(key)
            elif resolved_by_key[key][2] == "neutral" and hint != "neutral":
                resolved_by_key[key][2] = hint

        resolved: list[tuple[str, dict, str]] = [tuple(resolved_by_key[k]) for k in order]

        if not resolved and not candidates:
            return None

        if resolved:
            pickups = [
                {"raw": text, "terminal": terminal}
                for text, terminal, hint in resolved if hint == "pickup"
            ]
            dropoffs = [
                {"raw": text, "terminal": terminal}
                for text, terminal, hint in resolved if hint == "dropoff"
            ]
            # A resolved but merely "neutral" match (e.g. the contractor's
            # own company name happening to also be a real UEX shop/company
            # record) is noise, not a mission stop — only fall back to it
            # if a role would otherwise be completely empty.
            neutrals = [
                {"raw": text, "terminal": terminal}
                for text, terminal, hint in resolved if hint == "neutral"
            ]
            if not pickups and not dropoffs:
                # Nothing got a real role hint at all — best guess: first
                # resolved location is the pickup, the rest are drop-offs.
                pickups = neutrals[:1]
                dropoffs = neutrals[1:]
            elif not pickups:
                pickups = neutrals[:1]
            elif not dropoffs:
                dropoffs = neutrals[:1]
        else:
            # Nothing resolved against UEX data — keep the module useful by
            # falling back to raw text, clearly marked unresolved in the UI.
            pickups = [{"raw": candidates[0][0], "terminal": None}]
            dropoffs = [{"raw": c, "terminal": None} for c, _hint in candidates[1:3]]

        if not pickups:
            pickups = [{"raw": "?", "terminal": None}]
        if not dropoffs:
            # Always have at least one drop-off slot, even if unresolved,
            # so the route always has somewhere to go besides the pickup.
            pickup_raws = {p["raw"].lower() for p in pickups}
            remaining = [(c, h) for c, h in candidates if c.lower() not in pickup_raws]
            fallback = next((c for c, h in remaining if h == "dropoff"), None)
            if fallback is None:
                fallback = remaining[0][0] if remaining else pickups[0]["raw"]
            dropoffs = [{"raw": fallback, "terminal": None}]

        for entry in pickups:
            entry["commodities"] = self._entry_commodities(raw_text, entry, "pickup")
        for entry in dropoffs:
            entry["commodities"] = self._entry_commodities(raw_text, entry, "dropoff")

        return {
            "id": uuid.uuid4().hex[:8],
            "pickups": pickups,
            "dropoffs": dropoffs,
            "reward": reward,
            "scanned_at": time.strftime("%H:%M:%S"),
        }

    @staticmethod
    def _entry_commodities(raw_text: str, entry: dict, role: str) -> list[str]:
        """Try every name this location is known by — the exact OCR phrase
        that resolved it, plus its real terminal/nickname name if resolved
        — since the commodity-bearing line ("Collect X from Y") doesn't
        always use the same wording as whichever candidate happened to win
        resolution."""
        keys = [entry["raw"]]
        terminal = entry.get("terminal")
        if terminal:
            for k in (terminal.get("nickname"), terminal.get("name")):
                if k:
                    keys.append(k)
        found: list[str] = []
        seen: set[str] = set()
        for key in keys:
            for commodity in _extract_commodities(raw_text, key, role):
                ck = commodity.lower()
                if ck not in seen:
                    seen.add(ck)
                    found.append(commodity)
        return found

    # ------------------------------------------------------------------
    # Route heuristic
    # ------------------------------------------------------------------
    def _stop_nodes(self, contracts: list[dict]) -> list[tuple[int, str, int]]:
        nodes = []
        for i, c in enumerate(contracts):
            for j in range(len(c.get("pickups", []))):
                nodes.append((i, "pickup", j))
            for j in range(len(c.get("dropoffs", []))):
                nodes.append((i, "dropoff", j))
        return nodes

    def _node_entry(self, contracts: list[dict], node) -> dict:
        i, role, j = node
        key = "pickups" if role == "pickup" else "dropoffs"
        return contracts[i][key][j]

    def _node_terminal(self, contracts: list[dict], node) -> dict | None:
        return self._node_entry(contracts, node).get("terminal")

    def _node_raw(self, contracts: list[dict], node) -> str:
        return self._node_entry(contracts, node).get("raw", "")

    def _plan_route(self, contracts: list[dict]) -> list[tuple[int, str, int]]:
        """Visiting order across every contract's pickup and drop-off
        stops: a nearest-neighbour greedy pass to build an initial route,
        then a precedence-aware 2-opt pass to fix the greedy pass's classic
        blind spot — it can't look ahead, so it happily visits a stop early
        even when that forces an expensive backtrack later (confirmed on a
        real 4-contract test: it revisited Port Tressler twice — once for
        its own contract, then again after a detour to Crusader for a
        different contract's pickup — when picking up that Crusader cargo
        *first* and doing every microTech stop in one pass was strictly
        shorter). 2-opt repeatedly tries reversing a sub-segment of the
        route and keeps the reversal if it lowers total cost, which is
        exactly the "should I have done these in the other order" check
        greedy construction can't do on its own.

        Two things a pure "closest next stop" search would get wrong on its
        own, both handled explicitly here:
        - **Starting point.** Without this, the route always started from
          whichever contract's pickup happened to be scanned first — right
          only by coincidence. It now starts from the CURRENT LOCATION
          picker's pick (see `_current_location_terminal`), falling back to
          the old "just start at the first node" behavior only if no
          location has been set yet.
        - **Pickup-before-dropoff.** You can't drop off cargo you haven't
          picked up. Every drop-off node is ineligible to be chosen until
          *all* of its own contract's pickup nodes have already been
          visited — this is a hard constraint, not a cost tiebreaker, so
          the greedy search (and the 2-opt pass afterward) will detour to
          a farther pickup rather than visit a nearer but not-yet-loaded
          drop-off, and 2-opt rejects any reversal that would break it.
        """
        nodes = self._stop_nodes(contracts)
        n = len(nodes)
        if n == 0:
            return []

        pickups_needed = [len(c.get("pickups", [])) for c in contracts]
        pickups_done = [0] * len(contracts)

        def eligible(idx: int) -> bool:
            i, role, _j = nodes[idx]
            return role == "pickup" or pickups_done[i] >= pickups_needed[i]

        start_terminal = self._current_location_terminal()
        start_raw = self._locations.display_name(start_terminal) if start_terminal else None
        current_terminal, current_raw = start_terminal, start_raw

        visited = [False] * n
        order: list[int] = []

        for step in range(n):
            candidates = [idx for idx in range(n) if not visited[idx] and eligible(idx)]
            if not candidates:
                # Shouldn't happen for well-formed contracts (every dropoff
                # eventually becomes eligible once its pickups are visited),
                # but never hang if it somehow does.
                break

            if current_terminal is not None or current_raw is not None:
                best = min(
                    candidates,
                    key=lambda idx: self._cost_to_node(contracts, nodes[idx], current_terminal, current_raw),
                )
            else:
                # No known starting point at all (location never set) — no
                # basis to prefer one node over another for the very first
                # stop, so just take the first eligible one deterministically.
                best = candidates[0]

            visited[best] = True
            order.append(best)
            i, role, _j = nodes[best]
            if role == "pickup":
                pickups_done[i] += 1
            current_terminal = self._node_terminal(contracts, nodes[best])
            current_raw = self._node_raw(contracts, nodes[best])

        route = [nodes[i] for i in order]
        return self._two_opt(contracts, route, start_terminal, start_raw, pickups_needed)

    def _route_cost(
        self, contracts: list[dict], seq: list, start_terminal: dict | None, start_raw: str | None
    ) -> float:
        total = 0.0
        prev_terminal, prev_raw = start_terminal, start_raw
        for node in seq:
            term = self._node_terminal(contracts, node)
            raw = self._node_raw(contracts, node)
            if prev_terminal and term:
                total += self._terminal_cost(prev_terminal, term)
            else:
                total += COST_UNRESOLVED + self._text_cost(prev_raw or "", raw)
            prev_terminal, prev_raw = term, raw
        return total

    @staticmethod
    def _respects_precedence(contracts: list[dict], seq: list, pickups_needed: list[int]) -> bool:
        pickups_done = [0] * len(contracts)
        for node in seq:
            i, role, _j = node
            if role == "dropoff":
                if pickups_done[i] < pickups_needed[i]:
                    return False
            else:
                pickups_done[i] += 1
        return True

    def _two_opt(
        self,
        contracts: list[dict],
        seq: list,
        start_terminal: dict | None,
        start_raw: str | None,
        pickups_needed: list[int],
    ) -> list:
        """Standard 2-opt local search over a fixed-start path: repeatedly
        reverse a sub-segment [i:j+1] and keep the reversal if it lowers
        total route cost and doesn't put a drop-off before its own
        contract's pickup. Runs until a full pass finds no improving move.
        Cheap at the stop counts a real scan session produces (a handful
        of contracts, rarely more than ~15-20 stops total) — O(n^2) per
        pass, bounded number of passes since each accepted move strictly
        lowers a bounded integer/float cost."""
        best = list(seq)
        best_cost = self._route_cost(contracts, best, start_terminal, start_raw)
        n = len(best)

        improved = True
        while improved:
            improved = False
            for i in range(n - 1):
                for j in range(i + 1, n):
                    candidate = best[:i] + best[i:j + 1][::-1] + best[j + 1:]
                    if not self._respects_precedence(contracts, candidate, pickups_needed):
                        continue
                    cost = self._route_cost(contracts, candidate, start_terminal, start_raw)
                    if cost < best_cost - 1e-9:
                        best, best_cost = candidate, cost
                        improved = True
        return best

    def _cost_to_node(self, contracts: list[dict], node, from_terminal: dict | None, from_raw: str | None) -> float:
        term_b = self._node_terminal(contracts, node)
        if from_terminal and term_b:
            return self._terminal_cost(from_terminal, term_b)
        return COST_UNRESOLVED + self._text_cost(from_raw or "", self._node_raw(contracts, node))

    def _terminal_cost(self, a: dict, b: dict) -> float:
        if self._locations.terminal_key(a) == self._locations.terminal_key(b):
            return COST_SAME_TERMINAL
        body_keys = ("planet_name", "moon_name", "space_station_name", "city_name", "outpost_name")
        if any(a.get(k) and a.get(k) == b.get(k) for k in body_keys):
            return COST_SAME_BODY
        if a.get("star_system_name") and a.get("star_system_name") == b.get("star_system_name"):
            return COST_SAME_SYSTEM
        return COST_DIFFERENT_SYSTEM

    @staticmethod
    def _text_cost(a: str, b: str) -> float:
        if not a or not b:
            return 1.0
        a_low, b_low = a.lower(), b.lower()
        if a_low == b_low:
            return 0.0
        tokens_a = set(re.findall(r"[a-z0-9']+", a_low))
        tokens_b = set(re.findall(r"[a-z0-9']+", b_low))
        return 0.5 if (tokens_a & tokens_b) else 1.0

    # ------------------------------------------------------------------
    # Result rendering
    # ------------------------------------------------------------------
    def _render_results(self):
        # Clear any previous contents.
        while self._results_layout.count():
            item = self._results_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        contracts = self.settings.get("contracts", [])

        contracts_title = QLabel(f"CONTRACTS ({len(contracts)})")
        contracts_title.setStyleSheet(self._title_style())
        self._results_layout.addWidget(contracts_title)

        if not contracts:
            self._results_layout.addWidget(self._info_label(
                "No contracts yet. Frame one mission's pickup/drop-off "
                "text and click SCAN CONTRACT."
            ))
        else:
            for c in contracts:
                self._results_layout.addWidget(self._contract_row(c))

        if self._route_order:
            route_title = QLabel("SUGGESTED VISITING ORDER")
            route_title.setStyleSheet(self._title_style())
            self._results_layout.addWidget(route_title)

            for idx, node in enumerate(self._route_order, start=1):
                i, role, j = node
                contract = contracts[i] if i < len(contracts) else None
                if contract is None:
                    continue
                key = "pickups" if role == "pickup" else "dropoffs"
                items = contract.get(key, [])
                entry = items[j] if j < len(items) else {}
                terminal = entry.get("terminal")
                raw = entry.get("raw", "??")
                label_text = self._locations.display_name(terminal) if terminal else None
                display = label_text or f"{raw} (unresolved)"
                role_tag = "PICKUP" if role == "pickup" else "DROPOFF"
                commodities = entry.get("commodities") or []
                cargo_text = f" — {' / '.join(commodities)}" if commodities else ""
                self._results_layout.addWidget(
                    self._route_row(f"{idx}. [{role_tag}] {display}{cargo_text}")
                )

        self._results_layout.addWidget(self._info_label(
            "Best-effort OCR + UEX matching. Verify against the actual "
            "in-game contracts before committing to a route."
        ))

        if self._card_widget is not None:
            self._card_widget.apply_size()

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
            commodities = e.get("commodities") or []
            names.append(f"{base} ({'/'.join(commodities)})" if commodities else base)
        return " / ".join(names) if names else "??"

    def _contract_row(self, contract: dict) -> QWidget:
        pickups_text = self._entry_names(contract.get("pickups", []), self._locations.display_name)
        dropoffs_text = self._entry_names(contract.get("dropoffs", []), self._locations.display_name)
        reward = contract.get("reward")
        reward_text = f"  ·  {reward} aUEC" if reward else ""

        row = QLabel(f"{pickups_text} → {dropoffs_text}{reward_text}")
        row.setWordWrap(True)
        row.setStyleSheet(
            f"background: {theme.BG_PANEL}; color: {theme.TEXT_PRIMARY}; "
            f"border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px; "
            f"padding: 5px 8px; font-family: {theme.FONT_MONO}; "
            f"font-size: {theme.fpx(10)}px;"
        )
        return row

    def _route_row(self, text: str) -> QWidget:
        row = QLabel(text)
        row.setWordWrap(True)
        row.setStyleSheet(
            f"background: {theme.BG_VOID}; color: {theme.ACCENT_CYAN}; "
            f"border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px; "
            f"padding: 5px 8px; font-family: {theme.FONT_MONO}; "
            f"font-size: {theme.fpx(10)}px;"
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


MODULE_CLASS = LogisticsHubModule
