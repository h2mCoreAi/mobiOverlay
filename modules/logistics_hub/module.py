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
then a nearest-neighbour + 2-opt visiting order is planned using **real
UEX travel distance** (``LocationService.distance()`` — point-to-point
via ``terminals_distances`` when both stops are trade terminals, orbit-
to-orbit via ``orbits_distances`` otherwise, queried lazily and cached
per-session, never bulk-prefetched) rather than a guessed hierarchy tier.
A pair with no determinable real distance (missing orbit/system data, or
the distance endpoints themselves failing) falls back to a coarse same-
terminal/body/system/different-system tier scaled into the same rough
numeric range, so a fallback edge doesn't look artificially cheap next to
a real-distance one in the same route. A location that can't be resolved
against UEX data at all falls back further, to a text-similarity
heuristic, so the module still produces *something* usable, clearly
marked as unresolved.

The route always starts from the CURRENT LOCATION picker's selection (a
searchable combo over the same location data), not an arbitrary contract's
pickup — and never visits a drop-off before every pickup on its own
contract has been visited, since cargo can't be delivered before it's
been collected.
"""
import re
import time
import uuid

from PySide6.QtCore import Qt, QRect, QRectF, QPoint, QTimer, Signal
from PySide6.QtGui import (
    QGuiApplication,
    QImage,
    QPainter,
    QPainterPath,
    QColor,
    QPen,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QCompleter,
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

COPY_ROUTE_CONFIRM_MS = 1500  # how long the COPY ROUTE button shows "COPIED" before reverting

# Real UEX distance (LocationService.distance(), see host/locations.py) is
# the primary travel cost between two resolved locations now — genuine
# point-to-point/orbit-to-orbit numbers, not a guess. These are only the
# *fallback* tiers for when a real distance can't be determined (missing
# orbit/system data, or the UEX distance endpoints themselves failed) —
# scaled to roughly the same numeric range real distances live in (tens to
# low hundreds, per live UEX data) so a fallback-tier edge doesn't look
# artificially cheap next to a real-distance edge in the same route.
COST_SAME_TERMINAL = 0
COST_SAME_BODY = 5        # same planet/moon/space station/city/outpost
COST_SAME_SYSTEM = 50
COST_DIFFERENT_SYSTEM = 200
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
    Waste to..."). A location only needs to appear *somewhere* on the
    commodity-mention line or the one right after it (OCR line-wraps the
    location name past the line break more often than not) for it to
    count — doesn't need to be the exact candidate string that resolved it
    (OCR errors and station codes mean the two rarely match exactly), just
    a substring match after stripping non-alphanumerics from both sides.

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

    lines = raw_text.splitlines()
    found: list[str] = []
    seen: set[str] = set()
    for i, line in enumerate(lines):
        m = pattern.search(line)
        if not m:
            continue
        # The location name after "from"/"to" often continues onto the
        # very next line — OCR line-wrap splits "MIC-LI Shallow Frontier"
        # from "Station:" — so a match on this line's tail alone can be
        # truncated right before the part that would actually confirm it's
        # this location. Widen the search window by one line so a
        # truncated tail doesn't silently drop the commodity.
        window = m.group(2)
        if i + 1 < len(lines):
            window += " " + lines[i + 1]
        loc_part = re.sub(r"[^a-z0-9]", "", window.lower())
        if loc_key not in loc_part:
            continue
        commodity = re.sub(r"[.:_,;]+$", "", m.group(1)).strip()
        key = commodity.lower()
        if commodity and key not in seen:
            seen.add(key)
            found.append(commodity)
    return found


# A pickup/dropoff always has *some* cargo in a real contract — a blank
# commodity field is never a genuine "nothing to carry" result, only a
# parsing gap (e.g. OCR splits a location name across lines with unrelated
# text interleaved in between, wider than `_extract_commodities` can
# safely bridge without risking cross-attaching the wrong location's
# cargo — see docs/DECISIONS.md, 2026-09-04). Silently showing nothing
# looked like the module had simply confirmed there was no cargo, when
# it actually just couldn't find it — say so explicitly instead, in
# every place a commodity list gets displayed or exported.
_CARGO_UNKNOWN = "cargo unknown — check raw OCR text"


def _cargo_label(commodities: list[str] | None) -> str:
    return "/".join(commodities) if commodities else _CARGO_UNKNOWN


def _all_commodity_names(raw_text: str) -> set[str]:
    """Every commodity name mentioned anywhere in the text (normalized,
    lowercase), regardless of which location it's tied to — used only to
    keep the "always have a fallback stop" logic in `_build_contract` from
    grabbing a commodity name and displaying it as if it were an
    unresolved location. Confirmed real: when a contract's real drop-off
    text never matches anything ("NB Int. Spaceport" — an abbreviation
    with no real substring relationship to the actual place, "New
    Babbage" — see docs/DECISIONS.md), the fallback used to pick the
    nearest leftover dropoff-hinted candidate with no regard for whether
    it was actually a place; that leftover was "Ship Ammunition", the
    commodity being delivered, not a location at all.
    """
    names: set[str] = set()
    for pattern in (_PICKUP_COMMODITY_RE, _DROPOFF_COMMODITY_RE):
        for line in raw_text.splitlines():
            m = pattern.search(line)
            if m:
                commodity = re.sub(r"[.:_,;]+$", "", m.group(1)).strip().lower()
                if commodity:
                    names.add(commodity)
    return names


def _extract_reward(raw_text: str) -> str | None:
    # aUEC amounts are comma-grouped ("50,250") — that's a much more
    # reliable signal than the word "reward" itself, since OCR frequently
    # mangles the reward icon glyph next to it into stray characters
    # ("4 50,250" for what's actually "▲ 50,250" in-game). OCR occasionally
    # misreads the comma as a period ("63.250" instead of "63,250") —
    # confirmed real, so accept either as the thousands separator.
    m = re.search(r"(\d{1,3}(?:[,.]\d{3})+)", raw_text)
    return m.group(1).replace(".", ",") if m else None


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
    # Bare section headers ("PICK UP" / "DROP OFF" with no "LOCATIONS"
    # suffix — see the section regexes below) matched the general
    # capitalized-phrase pattern and got treated as location text in their
    # own right. Confirmed real and bad: "DROP OFF" normalizes to
    # "dropoff", which contains Port Olisar's 2-letter nickname "PO" as a
    # substring, so it silently "resolved" to a real but completely
    # unrelated place. Excluding them here is a second, independent guard
    # alongside the section regexes actually consuming these lines.
    "pick up", "drop off",
}


# Matches a *standalone* section header line — "PICK UP", "DROP OFF",
# "PICK UP LOCATIONS", "DROP OFF LOCATIONS (ANY ORDER)" — anchored to the
# whole line (plus optional trailing "(...)"/punctuation) so it can't
# accidentally fire on an unrelated sentence that merely contains the
# words "pick up"/"drop off" somewhere in the middle (e.g. "Doesn't matter
# what order you drop them off:" must NOT trigger section mode).
_DROPOFF_SECTION_RE = re.compile(r"^\s*drop.?off(\s+locations)?\s*(\(.*\))?\s*:?\s*$", re.I)
_PICKUP_SECTION_RE = re.compile(r"^\s*pick.?up(\s+locations)?\s*(\(.*\))?\s*:?\s*$", re.I)
_PICKUP_HINT_RE = re.compile(r"\bcollect\b|\bpick(?:ed|ing)?\s*up\b", re.I)
_DROPOFF_HINT_RE = re.compile(r"\bdeliver(?:ed)?\b.*\bto\b", re.I)


def _candidate_phrases(raw_text: str) -> list[tuple[str, str, int]]:
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
    # Hint sources aren't equally trustworthy — a keyword on the phrase's
    # *own* line is direct evidence; one inherited via backward lookback is
    # a proximity guess that can attach to the wrong nearby phrase (see
    # below); a section header is weaker still. Track a priority alongside
    # each candidate's hint so a *later*, more-trustworthy mention can
    # still override an *earlier*, less-trustworthy one for the same
    # phrase — plain "was it neutral before" wasn't enough. Confirmed real:
    # a run-on sentence ("A freight elevator at Long Forest Station ... has
    # cargo delivered to Endless Odyssey Station...") put "Long Forest
    # Station" on a line with no keyword of its own; lookback found the
    # *preceding* "Deliver...to Endless Odyssey" line and wrongly hinted it
    # "dropoff" — then the correct later "Collect Silicon from ...Long
    # Forest Station" mention (a real own-line pickup keyword) couldn't
    # override it because the existing hint wasn't "neutral" anymore.
    HINT_PRIORITY = {"neutral": 0, "section": 1, "lookback": 2, "own_line": 3}
    # (phrase, hint, priority) — the priority travels all the way out to
    # `_build_contract`'s own resolved-terminal merge now too, not just the
    # text-keyed merge here, since the same override bug can recur at that
    # later stage: two *differently-worded* candidates ("Shallow Frontier
    # Station" from one line, "Shallow Frontier" from another) can each
    # resolve to the *same real terminal* while carrying different hints —
    # confirmed real, a lookback-mishinted "dropoff" mention blocked a
    # later, correct, higher-priority "pickup" mention of the same place
    # because they never shared a dedup key here at all.
    candidates: list[tuple[str, str, int]] = []
    seen: dict[str, int] = {}  # normalized phrase -> index in candidates
    section_hint = None  # None, "pickup", or "dropoff" — set by a section header

    raw_lines = raw_text.splitlines()

    # First pass: a per-line keyword hint from "Collect X from Y" / "Deliver
    # X to Y" alone (no section fallback yet) — used below to look
    # *backward* a couple of lines when a location's own line has no
    # keyword. Real panels split "Collect Processed Food" and its location
    # ("HDMS-Ryder.") across 2-3 lines when OCR reads a two-column layout
    # in the wrong order, interleaving unrelated flavor-text sentences in
    # between; a same-line-only check missed every one of those.
    KEYWORD_LOOKBACK = 2
    keyword_hints: list[str | None] = []
    for line in raw_lines:
        if _PICKUP_HINT_RE.search(line):
            keyword_hints.append("pickup")
        elif _DROPOFF_HINT_RE.search(line):
            keyword_hints.append("dropoff")
        else:
            keyword_hints.append(None)

    for line_idx, line in enumerate(raw_lines):
        if _DROPOFF_SECTION_RE.search(line):
            section_hint = "dropoff"
            continue
        if _PICKUP_SECTION_RE.search(line):
            section_hint = "pickup"
            continue

        if keyword_hints[line_idx] is not None:
            hint = keyword_hints[line_idx]
            hint_source = "own_line"
        else:
            # No keyword on this exact line — check the last couple of
            # lines for one before falling back to section/neutral. Nearest
            # keyword wins if more than one is in range.
            hint = None
            for back in range(1, KEYWORD_LOOKBACK + 1):
                idx = line_idx - back
                if idx < 0:
                    break
                if keyword_hints[idx] is not None:
                    hint = keyword_hints[idx]
                    hint_source = "lookback"
                    break
            if hint is None:
                if section_hint is not None and re.search(r"\bat\b", line, re.I):
                    # The section header applies until the panel ends, but
                    # nothing marks that end explicitly — so don't trust it
                    # forever. Real list rows under either header ("Freight
                    # elevator at X at Y's L# Lagrange point") always
                    # contain "at"; trailing signature/footer text
                    # (contractor name, "Jr. Logistics Coordinator", the
                    # company name, ABANDON/SHARE/TRACK buttons) never does.
                    hint = section_hint
                    hint_source = "section"
                else:
                    hint = "neutral"
                    hint_source = "neutral"
        priority = HINT_PRIORITY[hint_source]

        def add_candidate(phrase: str, phrase_hint: str, phrase_priority: int) -> None:
            key = phrase.lower()
            if key in _PHRASE_STOPWORDS or len(phrase) < 5:
                return
            if key in seen:
                idx = seen[key]
                # A higher-priority hint (see HINT_PRIORITY above) always
                # wins for the same phrase, regardless of which mention
                # came first in the text.
                if phrase_priority > candidates[idx][2]:
                    candidates[idx] = (candidates[idx][0], phrase_hint, phrase_priority)
                return
            seen[key] = len(candidates)
            candidates.append((phrase, phrase_hint, phrase_priority))

        for m in re.finditer(
            r"[A-Z][a-zA-Z']+(?:\s+[A-Z][a-zA-Z']+){1,3}(?:\s+(?=\S*\d)[A-Za-z0-9-]+)?", line
        ):
            words = m.group(0).split()
            phrase = " ".join(words)
            add_candidate(phrase, hint, priority)
            # Real UEX names for near-identical sibling locations often
            # differ only by a trailing number ("ArcCorp Mining Area 045"
            # vs "...061") — the word-only pattern above can't capture a
            # digit at all, so a real, present disambiguating suffix was
            # being silently dropped even when OCR read it perfectly
            # clean on the same line. The optional trailing group above
            # picks it up when present (requires at least one digit in
            # that trailing token, so it doesn't also start swallowing
            # unrelated words like "at"/"above" that follow a real name).
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
                add_candidate(" ".join(words[1:]), hint, priority)

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
            add_candidate(m.group(0), hint, priority)

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


class _DuplicatePopup(QWidget):
    """Small themed confirm/deny prompt — same Qt.Popup pattern as
    host/main_window.py's Settings/Tray panels (closes on an outside
    click), used here instead of a plain QMessageBox to match the rest of
    the app's HUD styling."""

    def __init__(self, parent_widget, on_confirm, on_deny):
        super().__init__(parent_widget, Qt.Popup)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            _DuplicatePopup {{
                background: {theme.BG_PANEL}; border: 1px solid {theme.ACCENT_AMBER};
                border-radius: {theme.RADIUS}px;
            }}
        """)
        self._on_confirm = on_confirm
        self._on_deny = on_deny

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        label = QLabel("Duplicate detected. Add?")
        label.setStyleSheet(
            f"color: {theme.TEXT_PRIMARY}; font-family: {theme.FONT_DISPLAY}; "
            f"font-weight: 700; font-size: {theme.fpx(11)}px;"
        )
        layout.addWidget(label)

        btn_row = QHBoxLayout()
        confirm_btn = QPushButton("CONFIRM")
        deny_btn = QPushButton("DENY")
        btn_style = (
            f"background: {theme.BG_VOID}; color: {theme.ACCENT_CYAN}; "
            f"border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px; "
            f"padding: 4px 10px; font-family: {theme.FONT_DISPLAY}; font-weight: 700; "
            f"font-size: {theme.fpx(10)}px;"
        )
        confirm_btn.setStyleSheet(btn_style)
        deny_btn.setStyleSheet(btn_style)
        confirm_btn.clicked.connect(self._confirm)
        deny_btn.clicked.connect(self._deny)
        btn_row.addWidget(confirm_btn)
        btn_row.addWidget(deny_btn)
        layout.addLayout(btn_row)

    def _confirm(self):
        self._on_confirm()
        self.close()

    def _deny(self):
        self._on_deny()
        self.close()


class LogisticsHubModule(ModuleBase):
    module_id = "logistics_hub"
    # Rich-text, styled like the main window's own wordmark (see
    # host/main_window.py's _TitleBar) — Card's title_label (host/card.py)
    # renders whatever it's given as HTML, and .upper()'s case change is a
    # no-op on tag names/hex colors, so this survives that unaffected.
    display_name = (
        f'<span style="color:{theme.TEXT_PRIMARY};">MOBI</span>'
        f'<span style="color:{theme.ACCENT_CYAN};">LOGISTICS</span>'
    )

    def __init__(self, api_client, config):
        super().__init__(api_client, config)
        self._selector = None
        self._card_widget = None
        self._copy_route_revert_timer: QTimer | None = None
        self._route_popout: QWidget | None = None
        self._route_popout_layout: QVBoxLayout | None = None
        self._route_popout_opacity_slider: QSlider | None = None
        self._reader = None
        # Shared Core service (host/locations.py) — one place resolving/
        # caching UEX location data for every module, not this module's
        # own copy. See docs/DECISIONS.md, 2026-09-04, for why this lives
        # in Core rather than as a "location module" other modules depend on.
        self._locations = LocationService(api_client)
        self._location_choices: dict[str, dict] = {}  # display name -> terminal row, for the picker
        self._pending_duplicate: dict | None = None  # scanned but held back, awaiting confirm
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

        self._copy_route_btn = QPushButton("COPY ROUTE")
        self._copy_route_btn.setToolTip("Copies the suggested route (and full contract details) to the clipboard as plain text.")
        self._copy_route_btn.setStyleSheet(self._button_style())
        self._copy_route_btn.clicked.connect(self._copy_route_to_clipboard)
        action_row.addWidget(self._copy_route_btn)

        # CLEAR is placed last, away from SCAN/COPY, since it's destructive
        # and the user has accidentally hit it reaching for the other two.
        clear_btn = QPushButton("CLEAR")
        clear_btn.setStyleSheet(self._button_style())
        clear_btn.clicked.connect(self._clear_contracts)
        action_row.addWidget(clear_btn)
        layout.addLayout(action_row)

        # ---- contracts list (own scroll area — see 2026-09-04 DECISIONS ---
        # entry: this used to share one scroll area with the ROUTE section
        # below it, and a freshly-scanned contract could leave that shared
        # viewport scrolled into ROUTE instead, hiding CONTRACTS. Two
        # independent scroll areas means each keeps its own scroll position
        # and neither can push the other out of view.
        contracts_title_row = QHBoxLayout()
        self._contracts_title = QLabel("CONTRACTS")
        self._contracts_title.setStyleSheet(self._title_style())
        contracts_title_row.addWidget(self._contracts_title, 1)

        # Lives here (not next to the ROUTE title below) and is created
        # once rather than rebuilt on every _render_results call — it used
        # to be rebuilt inside the ROUTE section each render, which was
        # fragile (see DECISIONS.md 2026-09-04: a clear-loop bug orphaned
        # the old one on every second+ render, leaving a stale copy
        # floating at its last position on top of the new one).
        self._tracker_btn = QPushButton("TRACKER")
        self._tracker_btn.setStyleSheet(self._button_style())
        self._tracker_btn.clicked.connect(self._toggle_route_popout)
        self._tracker_btn.setVisible(False)
        contracts_title_row.addWidget(self._tracker_btn)
        layout.addLayout(contracts_title_row)

        self._contracts_scroll = QScrollArea()
        self._contracts_scroll.setWidgetResizable(True)
        self._contracts_scroll.setStyleSheet(
            f"QScrollArea {{ background: transparent; border: 1px solid {theme.BORDER_FLAT}; "
            f"border-radius: {theme.RADIUS}px; }}"
        )
        self._contracts_widget = QWidget()
        self._contracts_layout = QVBoxLayout(self._contracts_widget)
        self._contracts_layout.setContentsMargins(8, 8, 8, 8)
        self._contracts_layout.setSpacing(4)
        self._contracts_scroll.setWidget(self._contracts_widget)
        self._contracts_scroll.setMinimumHeight(90)
        self._contracts_scroll.setMaximumHeight(160)
        layout.addWidget(self._contracts_scroll)

        # ---- scrollable route list --------------------------------------
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

    def _save_settings(self):
        self.config.set_module_settings(self.module_id, self.settings)

    def _clear_contracts(self):
        self.settings["contracts"] = []
        self.settings["route_done"] = []
        self._save_settings()
        self._route_order = []
        self._pending_duplicate = None
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
                    cargo = f" ({_cargo_label(entry.get('commodities'))})"
                    raw = entry.get("raw", "??")
                    lines.append(f"     [{role_label}] {name}{cargo}  (OCR text: {raw!r})")
            for note in contract.get("ambiguous", []):
                lines.append(f"     [AMBIGUOUS] {note}")
            raw_text = contract.get("raw_text")
            if raw_text:
                lines.append("     --- raw OCR text for this scan ---")
                for raw_line in raw_text.splitlines():
                    lines.append(f"     | {raw_line}")
        lines.append("")

        lines.append("ROUTE")
        if not self._route_order:
            lines.append("  (none)")
        total_cost = 0.0
        prev_terminal, prev_raw = start_terminal, start_name
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
            cargo = f" — {_cargo_label(entry.get('commodities'))}"
            role_tag = "PICKUP" if role == "pickup" else "DROPOFF"

            # Per-edge cost, and whether it's a real UEX distance or a
            # fallback estimate — lets a live test actually verify a route
            # that "looks" wrong (e.g. revisiting a stop) against real
            # numbers instead of just eyeballing the stop order.
            if prev_terminal and terminal:
                edge_cost = self._terminal_cost(prev_terminal, terminal)
                real = self._locations.distance(prev_terminal, terminal) is not None
                source = "same stop" if edge_cost == COST_SAME_TERMINAL else ("real dist" if real else "est.")
            else:
                edge_cost = COST_UNRESOLVED + self._text_cost(prev_raw or "", entry.get("raw", ""))
                source = "text-match est."
            total_cost += edge_cost
            lines.append(f"  {step}. [{role_tag}] {name}{cargo}  [+{edge_cost:.0f} {source}, running {total_cost:.0f}]")

            prev_terminal, prev_raw = terminal, name

        return "\n".join(lines)

    def _copy_route_to_clipboard(self):
        text = self._format_route_text()
        QGuiApplication.clipboard().setText(text)
        self._set_status("Route copied to clipboard.")

        if self._copy_route_revert_timer is not None:
            self._copy_route_revert_timer.stop()
        self._copy_route_btn.setText("COPIED")
        self._copy_route_revert_timer = QTimer()
        self._copy_route_revert_timer.setSingleShot(True)
        self._copy_route_revert_timer.timeout.connect(self._revert_copy_route_btn)
        self._copy_route_revert_timer.start(COPY_ROUTE_CONFIRM_MS)

    def _revert_copy_route_btn(self):
        self._copy_route_btn.setText("COPY ROUTE")
        self._copy_route_revert_timer = None

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
        if any(self._is_likely_duplicate(c, contract) for c in contracts):
            self._pending_duplicate = contract
            self._show_duplicate_popup()
            self._set_status("Duplicate detected — confirm or deny.")
            return

        self._add_contract(contract)

    def _add_contract(self, contract: dict):
        contracts = self.settings.setdefault("contracts", [])
        contracts.append(contract)
        self._save_settings()
        self._route_order = self._plan_route(contracts)
        self._render_results()
        self._set_status(
            f"Added contract ({len(contracts)} total) at {time.strftime('%H:%M:%S')}"
        )

    @classmethod
    def _is_likely_duplicate(cls, a: dict, b: dict) -> bool:
        """Same reward, scanned again — but OCR noise varies scan to scan,
        so two captures of the *same real contract* can each resolve a
        slightly different set of pickups (one scan lost HDMS-Perlman,
        another lost Shubin, on two otherwise-identical scans of the same
        contract — confirmed real). Requiring the *entire* location set to
        match exactly missed that case entirely. Reward equality is
        already a strong signal on its own (two different real contracts
        rarely pay the exact same amount) — only need *some* resolved
        location in common on top of that, not a perfect set match."""
        if a.get("reward") != b.get("reward") or not a.get("reward"):
            return False
        a_locs = cls._location_keys(a)
        b_locs = cls._location_keys(b)
        return bool(a_locs & b_locs)

    @staticmethod
    def _location_keys(contract: dict) -> frozenset:
        return frozenset(
            LogisticsHubModule._locations_terminal_key_or_raw(e)
            for e in contract.get("pickups", []) + contract.get("dropoffs", [])
        )

    @staticmethod
    def _locations_terminal_key_or_raw(entry: dict):
        terminal = entry.get("terminal")
        if terminal:
            return LocationService.terminal_key(terminal)
        return entry.get("raw", "").lower()

    def _show_duplicate_popup(self):
        popup = _DuplicatePopup(self._card_widget, self._on_duplicate_confirm, self._on_duplicate_deny)
        anchor = self._scan_btn.mapToGlobal(self._scan_btn.rect().bottomLeft())
        popup.move(anchor)
        popup.show()

    def _on_duplicate_confirm(self):
        if self._pending_duplicate is not None:
            self._add_contract(self._pending_duplicate)
        self._pending_duplicate = None

    def _on_duplicate_deny(self):
        self._pending_duplicate = None
        self._set_status("Duplicate not added.")

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

    def _disambiguate_by_suffix(self, text: str, matches: list[dict], raw_text: str) -> dict | None:
        """When a bare phrase matches several distinct real places that
        differ only by a trailing code/number ("ArcCorp Mining Area" ->
        045/048/056/061/141), the *contract text itself* often does
        contain the disambiguating suffix somewhere — just not attached to
        this exact candidate string (a different mention, a line away, or
        the phrase regex genuinely can't include a digit). Rather than
        guess, check each candidate's own distinguishing suffix (its
        normalized name/nickname with the ambiguous phrase's own prefix
        stripped) against every line of the raw text individually — line-
        by-line, not the whole text concatenated, so two unrelated digits
        that happen to sit at a line boundary can't coincidentally form a
        false match. Only resolves if the suffix is long enough to be
        meaningful and exactly one candidate's suffix is actually found;
        any other outcome (zero or multiple matches) stays ambiguous.
        """
        phrase_norm = self._locations.normalize(text)
        lines_norm = [self._locations.normalize(line) for line in raw_text.splitlines()]

        found: dict | None = None
        found_count = 0
        for candidate in matches:
            suffix = None
            for key in ("name", "nickname"):
                label = candidate.get(key)
                if not label:
                    continue
                label_norm = self._locations.normalize(label)
                if label_norm.startswith(phrase_norm) and len(label_norm) > len(phrase_norm):
                    suffix = label_norm[len(phrase_norm):]
                    break
            if not suffix or len(suffix) < 2:
                continue
            if any(suffix in line for line in lines_norm):
                found_count += 1
                found = candidate
                if found_count > 1:
                    return None

        return found if found_count == 1 else None

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
        candidates = _candidate_phrases(raw_text)  # list of (phrase, hint, priority)
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
        # A bare phrase can genuinely match more than one distinct real
        # place — "ArcCorp Mining Area" alone matches both "...045" and
        # "...056" — usually because OCR separated the distinguishing
        # suffix onto a different line entirely. Silently picking one is
        # worse than admitting the parser isn't sure: only note this for
        # candidates that actually got a real pickup/dropoff hint (a
        # "neutral" ambiguous match was never going anywhere anyway and
        # would just be noise here).
        ambiguous_notes: list[str] = []
        noted: set[str] = set()

        def merge_resolved(text: str, terminal: dict, hint: str, priority: int) -> None:
            key = self._locations.terminal_key(terminal)
            if key not in resolved_by_key:
                # 5th element: every raw OCR spelling that resolved to this
                # same real place ("Long Forest Station", and separately
                # "Forest Station" once disambiguated) — commodity
                # extraction needs *all* of them, not just whichever won
                # the display text, since a garbled mention that's missing
                # a word can still be the only line mentioning a
                # particular commodity for this stop.
                resolved_by_key[key] = [text, terminal, hint, priority, {text}]
                order.append(key)
                return
            resolved_by_key[key][4].add(text)
            if priority > resolved_by_key[key][3]:
                # Same real place reached via a *differently-worded*
                # candidate (e.g. "Shallow Frontier Station" from one line
                # vs. bare "Shallow Frontier" from another) — these never
                # share a text-based dedup key, so the priority check has
                # to happen again here too, not just inside
                # `_candidate_phrases`. Confirmed real: a lookback-mishinted
                # "dropoff" mention blocked a later, correct, higher-
                # priority "pickup" mention of the very same terminal.
                resolved_by_key[key][2] = hint
                resolved_by_key[key][3] = priority

        # Pass 1: every candidate that resolves to exactly one real place —
        # these are the ground truth the ambiguous pass below leans on.
        pending_ambiguous: list[tuple[str, str, int, list[dict]]] = []
        for text, hint, priority in candidates:
            matches = self._locations.resolve_all(text)
            if not matches:
                continue
            if len(matches) > 1 and hint != "neutral":
                pending_ambiguous.append((text, hint, priority, matches))
                continue
            merge_resolved(text, matches[0], hint, priority)

        # Pass 2: try to disambiguate what's left, now that we know which
        # real places this contract has *already* confirmed unambiguously.
        # Two independent checks, either is enough to resolve:
        #  - a distinguishing suffix particular to one candidate appears
        #    somewhere in the text ("ArcCorp Mining Area" -> "...061" seen
        #    on another line);
        #  - one of the ambiguous options was *already* confirmed by a
        #    different, unambiguous mention elsewhere in this same
        #    contract ("Forest Station" alone is ambiguous between "Wide
        #    Forest Station"/"Long Forest Station", but this contract's
        #    OTHER mentions already unambiguously confirmed "Long Forest
        #    Station" — a real place appearing twice under two different
        #    OCR-garbled spellings is far more likely than two unrelated
        #    real places both showing up in one contract by coincidence).
        for text, hint, priority, matches in pending_ambiguous:
            disambiguated = self._disambiguate_by_suffix(text, matches, raw_text)
            if disambiguated is None:
                already_confirmed = [
                    m for m in matches
                    if self._locations.terminal_key(m) in resolved_by_key
                ]
                if len(already_confirmed) == 1:
                    disambiguated = already_confirmed[0]

            if disambiguated is not None:
                merge_resolved(text, disambiguated, hint, priority)
                continue

            if text.lower() not in noted:
                noted.add(text.lower())
                options = ", ".join(self._locations.display_name(m) for m in matches[:5])
                ambiguous_notes.append(f"{text!r} ({hint}) could be: {options} — not auto-resolved")

        resolved: list[tuple[str, dict, str, set]] = [
            (resolved_by_key[k][0], resolved_by_key[k][1], resolved_by_key[k][2], resolved_by_key[k][4])
            for k in order
        ]

        if not resolved and not candidates:
            return None

        if resolved:
            pickups = [
                {"raw": text, "terminal": terminal, "_aka": aka}
                for text, terminal, hint, aka in resolved if hint == "pickup"
            ]
            dropoffs = [
                {"raw": text, "terminal": terminal, "_aka": aka}
                for text, terminal, hint, aka in resolved if hint == "dropoff"
            ]
            # A resolved but merely "neutral" match (e.g. the contractor's
            # own company name happening to also be a real UEX shop/company
            # record) is noise, not a mission stop — only fall back to it
            # if a role would otherwise be completely empty.
            neutrals = [
                {"raw": text, "terminal": terminal, "_aka": aka}
                for text, terminal, hint, aka in resolved if hint == "neutral"
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
            dropoffs = [{"raw": c, "terminal": None} for c, _hint, _priority in candidates[1:3]]

        if not pickups:
            pickups = [{"raw": "?", "terminal": None}]
        if not dropoffs:
            # Always have at least one drop-off slot, even if unresolved,
            # so the route always has somewhere to go besides the pickup —
            # but never invent one out of a candidate that's actually a
            # commodity name ("Ship Ammunition"), not a place at all.
            pickup_raws = {p["raw"].lower() for p in pickups}
            commodity_names = _all_commodity_names(raw_text)
            remaining = [
                (c, h) for c, h, _priority in candidates
                if c.lower() not in pickup_raws and c.lower() not in commodity_names
            ]
            fallback = next((c for c, h in remaining if h == "dropoff"), None)
            if fallback is None and remaining:
                fallback = remaining[0][0]
            dropoffs = [{
                "raw": fallback if fallback is not None else "(unresolved — no location text found)",
                "terminal": None,
            }]

        for entry in pickups:
            entry["commodities"] = self._entry_commodities(raw_text, entry, "pickup")
        for entry in dropoffs:
            entry["commodities"] = self._entry_commodities(raw_text, entry, "dropoff")
        # `_aka` (a set) was only needed to widen the commodity search above
        # — drop it before this contract gets persisted to config.json,
        # since a set isn't JSON-serializable.
        for entry in pickups + dropoffs:
            entry.pop("_aka", None)

        return {
            "id": uuid.uuid4().hex[:8],
            "pickups": pickups,
            "dropoffs": dropoffs,
            "reward": reward,
            "scanned_at": time.strftime("%H:%M:%S"),
            "ambiguous": ambiguous_notes,
            "raw_text": raw_text,
        }

    @staticmethod
    def _entry_commodities(raw_text: str, entry: dict, role: str) -> list[str]:
        """Try every name this location is known by — every raw OCR
        spelling that resolved to it (`_aka`, including ones that only
        got there via disambiguation and would otherwise be lost — a
        garbled mention missing a word, like "Forest Station" instead of
        "Long Forest Station", can still be the only line mentioning a
        particular commodity for this stop), plus its real terminal
        nickname/name — since the commodity-bearing line ("Collect X from
        Y") doesn't always use the same wording as whichever candidate
        happened to win resolution."""
        keys = list(entry.get("_aka") or [entry["raw"]])
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
        distance = self._locations.distance(a, b)
        if distance is not None:
            return distance
        # Real distance unavailable (missing orbit/system data on either
        # side, or the UEX distance endpoints themselves failed) — fall
        # back to the coarse tier, scaled into the same rough numeric
        # range real distances live in (see the COST_* comment above).
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
                LogisticsHubModule._clear_layout(sub_layout)

    def _render_results(self):
        # Clear any previous contents.
        self._clear_layout(self._results_layout)

        contracts = self.settings.get("contracts", [])
        self._contracts_title.setText(f"CONTRACTS ({len(contracts)})")
        self._populate_contracts_rows(self._contracts_layout, contracts)

        self._tracker_btn.setVisible(bool(self._route_order))
        self._tracker_btn.setText("RETURN TO CARD" if self._route_popout is not None else "TRACKER")

        if self._route_order:
            route_title = QLabel("ROUTE")
            route_title.setStyleSheet(self._title_style())
            self._results_layout.addWidget(route_title)

            if self._route_popout is not None:
                self._results_layout.addWidget(self._info_label(
                    "Route is in its own always-on-top Tracker window."
                ))
                self._populate_route_rows(self._route_popout_layout, contracts, transparent_bg=True)
            else:
                self._populate_route_rows(self._results_layout, contracts)

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
            cargo_text = f" — {_cargo_label(entry.get('commodities'))}"
            route_key = f"{contract.get('id')}:{role}:{j}"
            target_layout.addWidget(
                self._route_row(
                    f"{idx}. [{role_tag}] {display}{cargo_text}",
                    route_key,
                    done=route_key in route_done,
                    transparent_bg=transparent_bg,
                )
            )

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
        win.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
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


MODULE_CLASS = LogisticsHubModule
