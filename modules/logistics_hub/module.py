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
import json
import re
import time
import uuid

from PySide6.QtCore import Qt, QRect, QRectF, QPoint, QTimer, Signal
from PySide6.QtGui import (
    QGuiApplication,
    QImage,
    QIntValidator,
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
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizeGrip,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from host import paths, theme
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

DEBUG_LOG_FILENAME = "logistics_hub_debug.jsonl"  # always-on scan history, see docs/DECISIONS.md

# Hauler Profile choices (added 2026-09-07) — fixed, small option sets
# rather than free text, so grading (a later part of the same plan) has
# a closed set of values to branch on instead of parsing arbitrary text.
# Ship is the one free-text field (no reliable static ship-data source —
# see docs/DECISIONS.md) and doubles as the key for the ship/location
# compatibility feedback database.
PROFILE_GOAL_CHOICES = ["Profit", "Reputation", "Keep Busy"]
PROFILE_RISK_CHOICES = ["Safe systems only", "Moderate", "Will run risky routes for good pay"]
PROFILE_TIME_CHOICES = ["Quick (<30 min)", "Medium", "Long session"]
PROFILE_REGION_CHOICES = ["Current system only", "Willing to cross jump points"]

# `_grade_contract()` returns a raw 0-100 score directly (shown as a
# percentage) rather than a letter — per user direction, 2026-09-07: a
# numeric scale reads more precisely than 5 coarse letter bands. Weights
# below are a first-pass rubric, meant to be tuned against real usage the
# same way this module's OCR/routing thresholds already were.
#
# A known-BAD ship/location match or a duplicate-freight overlap never
# blocks ACCEPT (per user direction) but caps the score here regardless of
# how good everything else scores — matches this module's existing
# "never silently averaged away" pattern for the Freight Manifest warning.
GRADE_CAP_ON_WARNING = 55
# A stricter cap for cargo capacity overflow specifically — added
# 2026-09-07 after a live test showed a contract that needed nearly 4x
# the user's actual cargo capacity still scored a "B" (55), since grading
# never checked capacity at all (a separate oversight — capacity checking
# already existed on the card's own summary line, just never wired into
# grading). Exceeding capacity is a harder constraint than a duplicate-
# freight annoyance or an unconfirmed location: it's not just annoying or
# unverified, it's physically impossible to complete as queued — so it
# gets a lower ceiling than the other two warnings, not the same one.
CAPACITY_OVERFLOW_CAP = 20
# Real system names UEX marks as more dangerous to route through — used
# only as a soft nudge against Risk Tolerance, not a hard rule (Star
# Citizen's actual risk map shifts with game updates; this is deliberately
# small and easy to extend, not treated as authoritative).
RISKY_SYSTEMS = {"Pyro"}

# Restricts what EasyOCR can output to characters that can actually appear
# in a contract panel — letters, digits, and every punctuation mark
# observed across this session's real captures (periods, commas, colons,
# semicolons, apostrophes/quotes, hyphens, slashes for "0/37", parens,
# brackets for "[BP]*", asterisks, underscores — a documented real OCR
# artifact standing in for a period — plus basic sentence punctuation).
# Restricting a classifier's output space to only valid characters can
# only remove wrong options, never introduce new ones — but an
# *incomplete* list could suppress a real, legitimate character, so this
# is deliberately generous rather than minimal. Empirically inconclusive
# in this session's own synthetic testing (no measurable difference on
# clean synthetic text — the real benefit is against genuine OCR
# hallucination artifacts, like a reward-icon glyph misread as a stray
# symbol, which synthetic text can't reproduce); needs a real scan to
# actually confirm, same as the earlier column-ordering change.
OCR_ALLOWLIST = (
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    " .,:;'\"-/()[]*_%&!?"
)

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


def _order_ocr_boxes(results: list, image_width: int) -> list[str]:
    """Reorder EasyOCR's `detail=1` results (each `(bbox, text, confidence)`,
    `bbox` a 4-point quadrilateral) into genuine left-to-right,
    top-to-bottom reading order, instead of trusting whatever order
    EasyOCR's own internal sort happened to return.

    The in-game contract panel is consistently two columns (mission
    narrative text next to a separate PICK UP/DROP OFF list) — this is
    documented as the root cause behind the large majority of parsing
    bugs fixed this session (split location names, orphaned words, role
    misattribution): every one of them was really a downstream symptom of
    reading both columns interleaved by vertical position instead of one
    column at a time. This fixes it at the source: split into at most two
    columns by the single largest horizontal gap between text boxes (only
    if that gap is wide enough to plausibly be a real column boundary,
    not just normal text spacing), sort each column top-to-bottom, then
    read the left column in full before the right one.

    A capture with no genuine column split (the common case for a
    single-pickup/single-dropoff contract, or any capture that isn't two
    columns at all) finds no wide-enough gap and degrades to one column,
    sorted purely top-to-bottom — never worse than the old behavior.
    """
    boxes = []
    for bbox, text, _confidence in results:
        xs = [p[0] for p in bbox]
        ys = [p[1] for p in bbox]
        boxes.append({"text": text, "x_min": min(xs), "y_center": sum(ys) / len(ys)})

    if len(boxes) < 2:
        return [b["text"] for b in boxes]

    ordered = sorted(boxes, key=lambda b: b["x_min"])
    gaps = [(ordered[i + 1]["x_min"] - ordered[i]["x_min"], i) for i in range(len(ordered) - 1)]
    biggest_gap, split_idx = max(gaps)

    # A real column boundary is a large fraction of the capture's own
    # width, not a fixed pixel count — capture regions vary a lot in size
    # (a tight single-contract crop vs. a wide multi-column one).
    if biggest_gap < max(50, image_width * 0.15):
        columns = [ordered]
    else:
        columns = [ordered[: split_idx + 1], ordered[split_idx + 1 :]]

    lines: list[str] = []
    for column in columns:
        lines.extend(b["text"] for b in sorted(column, key=lambda b: b["y_center"]))
    return lines


_PICKUP_COMMODITY_RE = re.compile(r"\bcollect\s+(.+?)\s+from\s+(.+)", re.I)
# Captures the SCU quantity too (group 1) — unlike the "Collect X from Y"
# pickup line, which never states its own quantity, each "Deliver N/TOTAL
# SCU of X to Y" line always does, and it's *this specific delivery's*
# amount (group 3 is the destination it belongs to).
_DROPOFF_COMMODITY_RE = re.compile(r"\bdeliver\s+(?:\d+/)?(\d+)\s*scu\s+of\s+(.+?)\s+to\s+(.+)", re.I)


def _find_delivery_match(lines: list[str], start: int, pattern: "re.Pattern", max_join: int = 2):
    """Search `pattern` starting at `lines[start]`, progressively folding in
    following lines when it doesn't match yet. A "Collect X from Y" or
    "Deliver N SCU of X to Y" line can be split by OCR's two-column
    reordering well before the destination even starts — confirmed real:
    "Deliver 0/5 SCU of Pressurized" / "to Ambitious Dream" / "Station..."
    are three separate lines, so a same-line-only search misses the whole
    delivery, not just its tail. Returns `(match, end_index)`, where
    `end_index` is the last line folded into the text the match came from
    (so a caller widening its own search further, e.g. for a still-
    truncated destination name, knows where to resume); `None` if nothing
    matched within `max_join` extra lines."""
    text = lines[start]
    end = start
    for _ in range(max_join + 1):
        m = pattern.search(text)
        if m:
            return m, end
        end += 1
        if end >= len(lines):
            return None
        text = f"{text} {lines[end]}"
    return None


def _complete_commodity_name(commodity: str, known_names: dict[str, str]) -> str:
    """OCR can split a delivery line badly enough that the commodity's own
    second word lands nowhere a nearby-line join can reach at all —
    confirmed real: "...of Pressurized" / "to Ambitious Dream" /
    "Station..." left the word "Ice" orphaned several lines away entirely,
    scrambled in with unrelated trailing footer/button text. Rather than
    chase an orphaned word with no reliable anchor, complete a truncated
    match against a fuller name of the *same* commodity already confirmed
    elsewhere in this same contract via a normal, complete, single-line
    match (`known_names`, from `_all_commodity_names`) — the same
    commodity is virtually always spelled out intact on at least one of
    its other pickup/drop-off lines. Only fires when the truncated text
    isn't already a recognized complete name and is a whole-word prefix of
    *exactly one* longer known name; any other outcome (already complete,
    no match, more than one candidate) leaves the text alone rather than
    guessing."""
    key = commodity.lower()
    if key in known_names:
        return commodity
    candidates = [
        original for lower, original in known_names.items()
        if lower.startswith(key + " ")
    ]
    return candidates[0] if len(candidates) == 1 else commodity


def _commodity_quantities(raw_text: str) -> dict[str, str]:
    """Map each commodity name to its TOTAL SCU across every "Deliver
    N/TOTAL SCU of X to..." line mentioning it — summed, not just the last
    one seen. A single pickup can feed more than one drop-off of the same
    commodity (confirmed real: one contract collecting Titanium once, then
    delivering 52 SCU of it to one station and 50 SCU to another — the
    pickup needs the combined 102, not whichever delivery line happened to
    be read last). Used only for the pickup side's total; each drop-off
    gets its own exact per-line quantity directly instead (see
    `_extract_commodities` below), so this summing never leaks into a
    drop-off showing the wrong (combined) amount for its own delivery."""
    lines = raw_text.splitlines()
    known_names = _all_commodity_names(raw_text)
    totals: dict[str, int] = {}
    i = 0
    while i < len(lines):
        result = _find_delivery_match(lines, i, _DROPOFF_COMMODITY_RE)
        if result is None:
            i += 1
            continue
        m, end = result
        commodity = re.sub(r"[.:_,;]+$", "", m.group(2)).strip()
        commodity = _complete_commodity_name(commodity, known_names)
        key = commodity.lower()
        if key:
            totals[key] = totals.get(key, 0) + int(m.group(1))
        i = end + 1
    return {k: str(v) for k, v in totals.items()}


def _extract_commodities(
    raw_text: str, location_raw: str, role: str, qty_by_commodity: dict[str, str] | None = None
) -> list[tuple[str, str | None]]:
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
    is_pickup = role == "pickup"
    pattern = _PICKUP_COMMODITY_RE if is_pickup else _DROPOFF_COMMODITY_RE
    # Group layout differs: the pickup line never states its own quantity
    # (commodity, destination); the drop-off line always does (quantity,
    # commodity, destination) — see `_DROPOFF_COMMODITY_RE`.
    commodity_group, dest_group = (1, 2) if is_pickup else (2, 3)
    qty_by_commodity = qty_by_commodity or {}
    known_names = _all_commodity_names(raw_text)

    lines = raw_text.splitlines()
    found: list[tuple[str, str | None]] = []
    seen: set[str] = set()
    i = 0
    while i < len(lines):
        result = _find_delivery_match(lines, i, pattern)
        if result is None:
            i += 1
            continue
        m, end = result
        i = end + 1
        # The location name after "from"/"to" often continues past even
        # whatever line(s) `_find_delivery_match` already folded in — OCR
        # line-wrap splits "MIC-LI Shallow Frontier" from "Station:" — so a
        # match on the destination's tail alone can be truncated right
        # before the part that would actually confirm it's this location.
        # Widen the search window by one more line so a truncated tail
        # doesn't silently drop the commodity — but only trust a match that
        # actually straddles the boundary (some of it already in this
        # line's own destination text). Confirmed real: "Deliver 0/13 SCU
        # of Corundum to Everus Harbor above" is immediately followed, by
        # pure two-column OCR interleaving, by an unrelated "Freight
        # elevator at Port Tressler..." listing line — accepting a loc_key
        # match found *anywhere* in the widened text let Port Tressler's
        # own extraction pass steal this Everus-Harbor-bound delivery
        # (wrong destination entirely, not just an imprecise one), which
        # also blocked the real, correct Port Tressler delivery line later
        # in the contract via the dedup-by-commodity-name check below.
        base = re.sub(r"[^a-z0-9]", "", m.group(dest_group).lower())
        if loc_key in base:
            loc_part = base
        elif end + 1 < len(lines):
            next_line = lines[end + 1]
            widened = re.sub(r"[^a-z0-9]", "", (m.group(dest_group) + " " + next_line).lower())
            idx = widened.find(loc_key)
            straddles = idx != -1 and idx < len(base)
            # A single-word city candidate (see _candidate_phrases's "in "
            # pass) is, by construction, never going to straddle this
            # boundary — a destination phrased "Teasa Spaceport" / "in
            # Lorville:" always puts the *entire* city name on the next
            # line, none of it on this one. That's a direct grammatical
            # continuation of the same destination ("X in CITY"), not a
            # coincidentally-adjacent unrelated mention (the Port Tressler
            # case above is a different *terminal's* own freight-elevator
            # listing, never introduced by "in "). Confirmed real: a live
            # scan's "Deliver...to Teasa Spaceport" / "in Lorville:" lost
            # its commodity entirely for the Lorville stop without this —
            # the straddle check can structurally never pass for this
            # pattern, not just miss it occasionally.
            next_in_match = re.match(r"\s*in\s+([A-Za-z']+)", next_line, re.I)
            is_in_continuation = (
                next_in_match is not None
                and re.sub(r"[^a-z0-9]", "", next_in_match.group(1).lower()) == loc_key
            )
            loc_part = widened if (straddles or is_in_continuation) else base
        else:
            loc_part = base
        if loc_key not in loc_part:
            continue
        commodity = re.sub(r"[.:_,;]+$", "", m.group(commodity_group)).strip()
        commodity = _complete_commodity_name(commodity, known_names)
        key = commodity.lower()
        if commodity and key not in seen:
            seen.add(key)
            # Pickup: the contract-wide total across every drop-off of this
            # commodity (`qty_by_commodity`, summed in `_commodity_quantities`).
            # Drop-off: this specific delivery's own amount, straight from
            # this line's own match — never the pickup's combined total.
            qty = qty_by_commodity.get(key) if is_pickup else m.group(1)
            found.append((commodity, qty))
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


def _cargo_label(commodities: list | None) -> str:
    """Render one entry's commodity list, with SCU quantity when known
    ("13 SCU Agricultural Supplies") — bare name only when it isn't (older
    saved contracts persisted before quantity tracking was added carry
    plain strings instead of (name, qty) pairs, so both are accepted)."""
    if not commodities:
        return _CARGO_UNKNOWN
    parts = []
    for c in commodities:
        if isinstance(c, (list, tuple)):
            name, qty = c
        else:
            name, qty = c, None
        parts.append(f"{qty} SCU {name}" if qty else name)
    return "/".join(parts)


def _entry_scu(entry: dict) -> int:
    """Total SCU across one pickup/dropoff entry's commodities — same
    tolerance for missing/non-numeric quantities as `_cargo_label` above
    (older saved contracts, or a "cargo unknown" entry with no commodities
    at all), so a stop with unknown cargo just contributes 0 rather than
    raising. Used by the card's peak-cargo-capacity summary."""
    total = 0
    for c in entry.get("commodities") or []:
        qty = c[1] if isinstance(c, (list, tuple)) and len(c) > 1 else None
        if qty and str(qty).isdigit():
            total += int(qty)
    return total


def _all_commodity_names(raw_text: str) -> dict[str, str]:
    """Every commodity name mentioned anywhere in the text, keyed by its
    normalized (lowercase) form and mapped to the original-cased spelling
    it was first seen with. Two uses: (1) keep the "always have a fallback
    stop" logic in `_build_contract` from grabbing a commodity name and
    displaying it as if it were an unresolved location — confirmed real:
    when a contract's real drop-off text never matches anything ("NB Int.
    Spaceport" — an abbreviation with no real substring relationship to
    the actual place, "New Babbage" — see docs/DECISIONS.md), the fallback
    used to pick the nearest leftover dropoff-hinted candidate with no
    regard for whether it was actually a place; that leftover was "Ship
    Ammunition", the commodity being delivered, not a location at all.
    (2) the reference vocabulary `_complete_commodity_name` completes a
    truncated name against — see that function for why. Deliberately
    single-line matching only, never `_find_delivery_match`'s multi-line
    join: a name gathered here needs to already be trustworthy/complete on
    its own, since it's what a truncated mention elsewhere gets completed
    against — folding in a *different* truncated mention here could
    complete one fragment against another instead of a real full name.
    """
    names: dict[str, str] = {}
    # Commodity is group 1 for the pickup line, group 2 for the drop-off
    # line (group 1 there is the SCU quantity) — see `_DROPOFF_COMMODITY_RE`.
    for pattern, commodity_group in ((_PICKUP_COMMODITY_RE, 1), (_DROPOFF_COMMODITY_RE, 2)):
        for line in raw_text.splitlines():
            m = pattern.search(line)
            if m:
                commodity = re.sub(r"[.:_,;]+$", "", m.group(commodity_group)).strip()
                key = commodity.lower()
                if key and key not in names:
                    names[key] = commodity
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


def _total_reward(contracts: list[dict]) -> int:
    """Sum of every contract's reward (already a comma-grouped string from
    `_extract_reward` — "87,250"), for the card's at-a-glance summary.
    Contracts with no parsed reward simply contribute 0."""
    total = 0
    for c in contracts:
        reward = c.get("reward")
        if reward:
            digits = reward.replace(",", "")
            if digits.isdigit():
                total += int(digits)
    return total


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
            # No keyword on this exact line. A line under an active DROP
            # OFF/PICK UP LOCATIONS section that looks like a real location
            # row is claimed by that section *before* falling back to
            # backward lookback — the section header is explicit, on-screen
            # structure ("Freight elevator at X at Y's L# Lagrange point"
            # always contains "at"; trailing signature/footer text like the
            # contractor name, "Jr. Logistics Coordinator", the company
            # name, or ABANDON/SHARE/TRACK never does, so "at" is a safe
            # qualifier), while lookback is only a proximity guess.
            # Confirmed real: two-column OCR reordering can land an
            # unrelated pickup-keyword line (flavor text for a *different*
            # item) directly before a real drop-off row printed under an
            # active DROP OFF LOCATIONS header — lookback then claimed that
            # row as a pickup instead of trusting the section it was
            # actually under (see DECISIONS.md). Lookback only runs when
            # no section is active, or the line doesn't look like a
            # section row (e.g. narrative sentences with no header at all).
            hint = None
            if section_hint is not None and re.search(r"\bat\b", line, re.I):
                hint = section_hint
                hint_source = "section"
            else:
                for back in range(1, KEYWORD_LOOKBACK + 1):
                    idx = line_idx - back
                    if idx < 0:
                        break
                    if keyword_hints[idx] is not None:
                        hint = keyword_hints[idx]
                        hint_source = "lookback"
                        break
                if hint is None:
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

        # A location named with a single capitalized word (real cities can
        # be — "Lorville") never becomes a candidate at all above, since
        # that regex requires 2+ words in a row. Confirmed real: "...Teasa
        # Spaceport in Lorville." never offered "Lorville" itself as a
        # candidate — only the genuinely ambiguous 2-word "Teasa Spaceport"
        # (which resolves to two different real shops there) was tried, so
        # the city was never even considered. Deliberately narrow: only
        # after "in " specifically, never "at "/"above " — every real
        # contract template seen introduces a *planet* via "above PLANET"
        # ("above Hurston:", "above Crusader."), and planets aren't part of
        # LocationService's indexed endpoints at all, so nothing already
        # filters them out; confirmed live that bare planet names collide
        # with unrelated real shops via substring match ("Hurston" ->
        # "Hurston Dynamics Showcase - Lorville", "Crusader" ambiguous
        # across 3 unrelated shops). "in " never precedes a planet/system
        # name in any template seen, so this scoping targets the reported
        # bug shape without reopening that risk. The negative lookahead
        # skips a multi-word name's first word ("in New Deal Plaza") —
        # the 2+-word regex above already captures that fuller phrase.
        for m in re.finditer(r"\bin\s+([A-Z][a-zA-Z']{3,})(?!\s+[A-Z])", line):
            add_candidate(m.group(1), hint, priority)

        # A location name itself (not just the flavor text around it) can be
        # split across a line wrap by the same two-column OCR reordering,
        # e.g. "...SCU of Agricultural Supplies to Everus" / "Harbor above
        # Hurston:" — the real name "Everus Harbor" never appears intact on
        # either line, so the phrase regex above can't see it at all, and
        # the location only resolves via a *different*, unrelated mention
        # elsewhere that gets whatever hint lookback happens to guess.
        # Confirmed real: this silently reversed pickup/dropoff for a
        # contract whose "Deliver...to X" line wrapped, while the actual
        # pickup keyword ("Collect...from Y") landed on an adjacent line by
        # coincidence and lookback attached its hint to the wrapped dropoff
        # name instead. Re-scan the current line joined with the next one,
        # reusing the current line's own hint/priority — if the keyword and
        # its object are on this line (own_line), the reassembled full name
        # now gets that same trustworthy hint instead of an unrelated
        # lookback guess. Purely additive: `add_candidate` only replaces an
        # existing entry on a strictly higher priority, and a bogus joined
        # phrase simply won't resolve against real UEX data later.
        #
        # Restricted to `own_line` on purpose — trying this for every line
        # (including lookback/section/neutral lines) backfired in practice:
        # joining a lookback-hinted line with its neighbor let the *same*
        # contamination this is meant to fix reach one line further than
        # before, wrongly dragging an unrelated, correctly-neutral phrase
        # ("Seraphim Station", two lines after the real dropoff keyword)
        # into that keyword's hint. Only a line whose keyword is directly
        # on it is trustworthy enough to extend across the wrap.
        #
        # Also restricted to matches that actually straddle the line break
        # (some of the match's characters on each side of the join) — a
        # match sitting entirely inside the next line isn't a wrapped name
        # at all, just an unrelated phrase that happens to follow this
        # line, and inheriting this line's own_line hint/priority for it is
        # its own, separately confirmed real bug: "Collect Processed Food
        # from Seraphim Station." (own_line pickup) directly followed by
        # the unrelated "Freight elevator at Ambitious Dream Station at
        # Crusader's Ll" pulled "Ambitious Dream Station" — a real
        # drop-off elsewhere in the same contract — in as a bogus pickup at
        # the highest priority, permanently locking out its correct hint.
        # A genuinely wrapped name (e.g. "...to Everus" / "Harbor above
        # Hurston:") always has match characters on both sides of the
        # join, so this restriction only removes the false case.
        if hint_source == "own_line" and line_idx + 1 < len(raw_lines):
            next_line = raw_lines[line_idx + 1]
            joined = f"{line} {next_line}"
            boundary = len(line)  # index of the inserted joining space
            for m in re.finditer(
                r"[A-Z][a-zA-Z']+(?:\s+[A-Z][a-zA-Z']+){1,3}(?:\s+(?=\S*\d)[A-Za-z0-9-]+)?",
                joined,
            ):
                if not (m.start() < boundary and m.end() > boundary + 1):
                    continue
                phrase = " ".join(m.group(0).split())
                add_candidate(phrase, hint, priority)

    return candidates


class _RegionSelector(QWidget):
    """Full‑screen transparent widget used to drag‑draw a capture rectangle.

    Only shows on the screen where the cursor is at the moment the user
    clicks “SET SCAN AREA”.  Coordinates emitted in global desktop space.
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


class _ReviewPopup(QWidget):
    """Shown after every scan (not just duplicates) — added 2026-09-07 per
    user direction: SCAN CONTRACT used to add straight to the queue/route,
    only pausing for a duplicate. Now every scan pauses here first. Same
    themed `Qt.Popup` shell `_DuplicatePopup` used (closes on an outside
    click, matches the rest of the app's HUD styling instead of a plain
    QMessageBox) — generalized to show the contract summary and (later,
    once the grading pass lands) a 0-100 score, not just a duplicate
    warning. The duplicate warning line still appears here when relevant,
    folded into this one popup instead of a separate flow."""

    def __init__(
        self, parent_widget, summary_text: str, duplicate_warning: str | None,
        grade: int | None, grade_reason: str, grade_capped: bool,
        unrated_terminals: list[tuple[str, dict]], on_rate, on_accept, on_reject,
    ):
        # A real top-level window, not Qt.Popup — added 2026-09-07 after a
        # live test showed Qt.Popup auto-closes on any outside click or
        # focus loss (e.g. tabbing away to check something), silently
        # discarding an in-progress compatibility rating and forcing a
        # rescan. This decision needs to survive that; only ACCEPT/REJECT
        # should ever close it. Positioned manually below (popup.move()),
        # same as before.
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_StyledBackground, True)
        border_color = theme.ACCENT_AMBER if duplicate_warning else theme.BORDER_FLAT
        self.setStyleSheet(f"""
            _ReviewPopup {{
                background: {theme.BG_PANEL}; border: 1px solid {border_color};
                border-radius: {theme.RADIUS}px;
            }}
        """)
        self._on_rate = on_rate
        self._on_accept = on_accept
        self._on_reject = on_reject

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        self.setMaximumWidth(420)

        title = QLabel("Add this contract?")
        title.setStyleSheet(
            f"color: {theme.TEXT_PRIMARY}; font-family: {theme.FONT_DISPLAY}; "
            f"font-weight: 700; font-size: {theme.fpx(11)}px;"
        )
        layout.addWidget(title)

        summary = QLabel(summary_text)
        summary.setWordWrap(True)
        summary.setStyleSheet(
            f"color: {theme.TEXT_PRIMARY}; font-family: {theme.FONT_MONO}; "
            f"font-size: {theme.fpx(10)}px;"
        )
        layout.addWidget(summary)

        if grade is not None:
            # Amber whenever a hard warning capped the score, regardless of
            # what the number still looks like — the cap can still land
            # somewhere that looks decent (e.g. 55%), and that's exactly
            # the "90% great, one hard no, hidden behind a decent-looking
            # score" case this feature exists to prevent. Otherwise amber
            # only for a low score on its own merits.
            grade_color = theme.ACCENT_AMBER if (grade_capped or grade < 50) else theme.ACCENT_CYAN
            grade_label = QLabel(f"GRADE: {grade}% — {grade_reason}")
            grade_label.setWordWrap(True)
            grade_label.setStyleSheet(
                f"color: {grade_color}; font-family: {theme.FONT_DISPLAY}; "
                f"font-weight: 800; font-size: {theme.fpx(11)}px;"
            )
            layout.addWidget(grade_label)
        else:
            hint = QLabel(grade_reason)  # "Set your PROFILE for a grade."
            hint.setStyleSheet(
                f"color: {theme.TEXT_DIM}; font-family: {theme.FONT_MONO}; "
                f"font-size: {theme.fpx(9)}px;"
            )
            layout.addWidget(hint)

        if duplicate_warning:
            warn = QLabel(f"⚠ {duplicate_warning}")
            warn.setWordWrap(True)
            warn.setStyleSheet(
                f"background: {theme.ACCENT_AMBER_DIM}; color: {theme.ACCENT_AMBER}; "
                f"border: 1px solid {theme.ACCENT_AMBER}; border-radius: {theme.RADIUS}px; "
                f"padding: 5px 8px; font-family: {theme.FONT_MONO}; "
                f"font-size: {theme.fpx(9)}px;"
            )
            layout.addWidget(warn)

        for label_text, terminal in unrated_terminals:
            row = QHBoxLayout()
            q = QLabel(f"Compatible with your ship at {label_text}?")
            q.setWordWrap(True)
            q.setStyleSheet(
                f"color: {theme.TEXT_MUTED}; font-family: {theme.FONT_MONO}; "
                f"font-size: {theme.fpx(9)}px;"
            )
            row.addWidget(q, 1)
            good_btn = QPushButton("✅")
            bad_btn = QPushButton("❌")
            small_btn_style = (
                f"background: {theme.BG_VOID}; border: 1px solid {theme.BORDER_FLAT}; "
                f"border-radius: {theme.RADIUS}px; padding: 2px 6px; font-size: {theme.fpx(10)}px;"
            )
            good_btn.setStyleSheet(small_btn_style)
            bad_btn.setStyleSheet(small_btn_style)
            good_btn.clicked.connect(
                lambda _checked, t=terminal, lbl=label_text, g=good_btn, b=bad_btn: self._rate(t, True, lbl, g, b)
            )
            bad_btn.clicked.connect(
                lambda _checked, t=terminal, lbl=label_text, g=good_btn, b=bad_btn: self._rate(t, False, lbl, g, b)
            )
            row.addWidget(good_btn)
            row.addWidget(bad_btn)
            layout.addLayout(row)

        btn_row = QHBoxLayout()
        accept_btn = QPushButton("ACCEPT")
        reject_btn = QPushButton("REJECT")
        btn_style = (
            f"background: {theme.BG_VOID}; color: {theme.ACCENT_CYAN}; "
            f"border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px; "
            f"padding: 4px 10px; font-family: {theme.FONT_DISPLAY}; font-weight: 700; "
            f"font-size: {theme.fpx(10)}px;"
        )
        accept_btn.setStyleSheet(btn_style)
        reject_btn.setStyleSheet(btn_style)
        accept_btn.clicked.connect(self._accept)
        reject_btn.clicked.connect(self._reject)
        btn_row.addWidget(accept_btn)
        btn_row.addWidget(reject_btn)
        layout.addLayout(btn_row)

    def _rate(self, terminal: dict, good: bool, label: str, good_btn: QPushButton, bad_btn: QPushButton):
        # Saves immediately, doesn't close the popup — you can rate several
        # locations before deciding ACCEPT/REJECT. Doesn't affect *this*
        # popup's already-shown grade (recomputing live isn't worth the
        # complexity for a rating that mainly pays off on the *next* scan
        # of the same location) — just disables the row so it's clear the
        # answer was recorded.
        self._on_rate(terminal, good, label)
        good_btn.setEnabled(False)
        bad_btn.setEnabled(False)
        # 2026-09-07: both buttons used to just grey out identically on
        # click, with no way to tell which one had actually registered
        # (a live test confirmed the click did work, but looked like it
        # hadn't). The chosen button now stays bright with a colored
        # border; the other visibly dims further than Qt's default
        # disabled look.
        chosen, other = (good_btn, bad_btn) if good else (bad_btn, good_btn)
        chosen_color = theme.ACCENT_CYAN if good else theme.ACCENT_AMBER
        chosen.setStyleSheet(
            f"background: {theme.BG_VOID}; border: 2px solid {chosen_color}; "
            f"border-radius: {theme.RADIUS}px; padding: 2px 6px; font-size: {theme.fpx(10)}px;"
        )
        other.setStyleSheet(
            f"background: {theme.BG_VOID}; border: 1px solid {theme.BORDER_FLAT}; "
            f"border-radius: {theme.RADIUS}px; padding: 2px 6px; font-size: {theme.fpx(10)}px; "
            f"color: {theme.TEXT_DIM};"
        )

    def _accept(self):
        self._on_accept()
        self.close()

    def _reject(self):
        self._on_reject()
        self.close()


class _HaulerProfilePopup(QWidget):
    """Ship + hauling-preference profile, set once and edited whenever —
    added 2026-09-07 (Part 2 of the confirm-gate/grading plan, see
    docs/DECISIONS.md). Not re-asked per scan; a later grading pass reads
    these five fields from `self.settings["hauler_profile"]` to score a
    freshly-scanned contract. Real top-level window, not Qt.Popup — same
    2026-09-07 fix as `_ReviewPopup` (Qt.Popup auto-closes on any outside
    click/focus loss, which would silently discard an in-progress edit
    here too); only SAVE closes it."""

    def __init__(self, parent_widget, profile: dict, capacity: int | None, on_save):
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            _HaulerProfilePopup {{
                background: {theme.BG_PANEL}; border: 1px solid {theme.BORDER_FLAT};
                border-radius: {theme.RADIUS}px;
            }}
        """)
        self._on_save = on_save
        self.setMinimumWidth(320)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        title = QLabel("HAULER PROFILE")
        title.setStyleSheet(
            f"color: {theme.ACCENT_CYAN}; font-family: {theme.FONT_DISPLAY}; "
            f"font-weight: 800; font-size: {theme.fpx(11)}px; letter-spacing: 2px;"
        )
        layout.addWidget(title)

        ship_row = QHBoxLayout()
        ship_label = QLabel("SHIP")
        ship_label.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-family: {theme.FONT_MONO}; "
            f"font-size: {theme.fpx(9)}px; letter-spacing: 1px;"
        )
        ship_row.addWidget(ship_label)
        self._ship_edit = QLineEdit(profile.get("ship", ""))
        self._ship_edit.setPlaceholderText("Ship (e.g. Hull C)")
        self._ship_edit.setStyleSheet(
            f"""
            QLineEdit {{
                background: {theme.BG_VOID}; color: {theme.ACCENT_CYAN};
                border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px;
                padding: 4px 6px; font-family: "{theme.FONT_DISPLAY}"; font-weight: 700;
                font-size: {theme.fpx(11)}px;
            }}
            """
        )
        ship_row.addWidget(self._ship_edit, 1)
        layout.addLayout(ship_row)

        # Moved here from the card face, 2026-09-07, per user request —
        # sits with the ship it's actually describing (a hold size only
        # means something in the context of a specific ship) rather than
        # as an unrelated standalone field on the card. Manual entry, not
        # a ship picker — the user's actual hold size depends on cargo-
        # grid loadout, which UEX's static vehicle data can't reflect.
        capacity_row = QHBoxLayout()
        capacity_label = QLabel("CARGO CAPACITY")
        capacity_label.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-family: {theme.FONT_MONO}; "
            f"font-size: {theme.fpx(9)}px; letter-spacing: 1px;"
        )
        capacity_row.addWidget(capacity_label)
        self._capacity_edit = QLineEdit(str(capacity) if capacity else "")
        self._capacity_edit.setValidator(QIntValidator(0, 100000, self._capacity_edit))
        self._capacity_edit.setPlaceholderText("SCU")
        self._capacity_edit.setStyleSheet(
            f"""
            QLineEdit {{
                background: {theme.BG_VOID}; color: {theme.ACCENT_CYAN};
                border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px;
                padding: 4px 6px; font-family: "{theme.FONT_DISPLAY}"; font-weight: 700;
                font-size: {theme.fpx(11)}px;
            }}
            """
        )
        capacity_row.addWidget(self._capacity_edit, 1)
        layout.addLayout(capacity_row)

        self._goal_combo = self._add_row(layout, "GOAL", PROFILE_GOAL_CHOICES, profile.get("goal"))
        self._risk_combo = self._add_row(layout, "RISK TOLERANCE", PROFILE_RISK_CHOICES, profile.get("risk"))
        self._time_combo = self._add_row(layout, "SESSION TIME", PROFILE_TIME_CHOICES, profile.get("time_budget"))
        self._region_combo = self._add_row(layout, "REGION", PROFILE_REGION_CHOICES, profile.get("region_pref"))

        save_btn = QPushButton("SAVE")
        save_btn.setStyleSheet(
            f"background: {theme.BG_VOID}; color: {theme.ACCENT_CYAN}; "
            f"border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px; "
            f"padding: 4px 10px; font-family: {theme.FONT_DISPLAY}; font-weight: 700; "
            f"font-size: {theme.fpx(10)}px;"
        )
        save_btn.clicked.connect(self._save)
        layout.addWidget(save_btn)

    def _add_row(self, layout: QVBoxLayout, label_text: str, choices: list[str], current: str | None) -> QComboBox:
        row = QHBoxLayout()
        label = QLabel(label_text)
        label.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-family: {theme.FONT_MONO}; "
            f"font-size: {theme.fpx(9)}px; letter-spacing: 1px;"
        )
        row.addWidget(label)

        combo = QComboBox()
        combo.addItems(choices)
        if current in choices:
            combo.setCurrentText(current)
        combo.setStyleSheet(
            f"""
            QComboBox {{
                background: {theme.BG_VOID}; color: {theme.ACCENT_CYAN};
                border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px;
                padding: 4px 22px 4px 6px; font-family: "{theme.FONT_DISPLAY}"; font-weight: 700;
                font-size: {theme.fpx(10)}px;
            }}
            QComboBox::drop-down {{ width: 18px; border: none; }}
            """
        )
        row.addWidget(combo, 1)
        layout.addLayout(row)
        return combo

    def _save(self):
        capacity_text = self._capacity_edit.text().strip()
        self._on_save(
            {
                "ship": self._ship_edit.text().strip(),
                "goal": self._goal_combo.currentText(),
                "risk": self._risk_combo.currentText(),
                "time_budget": self._time_combo.currentText(),
                "region_pref": self._region_combo.currentText(),
            },
            int(capacity_text) if capacity_text else None,
        )
        self.close()


class LogisticsHubModule(ModuleBase):
    module_id = "logistics_hub"
    # Rich-text, styled like the main window's own wordmark (see
    # host/main_window.py's _TitleBar) — Card's title_label (host/card.py)
    # renders whatever it's given as HTML and no longer forces uppercase,
    # so this mixed-case branding survives intact.
    display_name = (
        f'<span style="color:{theme.TEXT_PRIMARY};">mobi</span>'
        f'<span style="color:{theme.ACCENT_CYAN};">Logistics</span>'
    )

    def __init__(self, api_client, config):
        super().__init__(api_client, config)
        # This module is on-demand only (SCAN CONTRACT) — the host's generic
        # periodic-refresh timer would otherwise call refresh() every
        # DEFAULT_REFRESH_SECONDS and re-OCR whatever's on screen at that
        # moment (desktop, chat, menus...), silently appending garbage
        # "contracts". 0 tells host/main.py to skip starting that timer for
        # this module; explicit user config can still override it.
        self.settings.setdefault("refresh_interval_seconds", 0)
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
        self._pending_scan: dict | None = None  # scanned, awaiting ACCEPT/REJECT in the review popup
        # Debug-log context for the currently-open review popup — set in
        # `refresh()`/`_show_review_popup()`, read back by
        # `_log_review_outcome()` when ACCEPT/REJECT is actually clicked
        # (which happens later, asynchronously, so it can't be logged in
        # the same call that shows the popup). See docs/DECISIONS.md,
        # 2026-09-07.
        self._pending_grade: tuple[int | None, str, bool] | None = None
        self._pending_unrated_names: list[str] = []
        self._pending_ratings_given: list[dict] = []
        # Both now real Qt.Window widgets (2026-09-07 fix, see _ReviewPopup/
        # _HaulerProfilePopup) — need an explicit reference held somewhere
        # or they're garbage-collected the instant the showing method
        # returns, since (unlike Qt.Popup) nothing else keeps one alive.
        self._review_popup: QWidget | None = None
        self._profile_popup: QWidget | None = None
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
                padding: 4px 22px 4px 6px; font-family: "{theme.FONT_DISPLAY}"; font-weight: 700;
                font-size: {theme.fpx(11)}px;
            }}
            QComboBox::drop-down {{
                width: 18px; border: none;
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

        select_btn = QPushButton("SET SCAN AREA")
        select_btn.setStyleSheet(self._button_style())
        select_btn.clicked.connect(self._select_region)
        region_row.addWidget(select_btn)

        profile_btn = QPushButton("PROFILE")
        profile_btn.setToolTip(
            "Your ship + hauling preferences — set once, used to grade "
            "future scans. Doesn't affect parsing or routing."
        )
        profile_btn.setStyleSheet(self._button_style())
        profile_btn.clicked.connect(self._show_profile_popup)
        region_row.addWidget(profile_btn)
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

        # Re-parses every saved contract from its own stored OCR text and
        # replans the route — no rescan needed. Added 2026-09-05 so a
        # parsing/quantity fix can be picked up on contracts already sitting
        # in this session without CLEAR + rescanning them all from the game.
        reprocess_btn = QPushButton("REPROCESS")
        reprocess_btn.setToolTip(
            "Re-parses every saved contract from its own stored OCR text "
            "(locations + commodities) and replans the route — no rescan "
            "needed. Useful after a parsing fix."
        )
        reprocess_btn.setStyleSheet(self._button_style())
        reprocess_btn.clicked.connect(self._safe_reprocess)
        action_row.addWidget(reprocess_btn)

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

        # At-a-glance summary (total reward, peak cargo capacity needed) —
        # added 2026-09-05 after reviewing the card from a player's
        # perspective: everything else here needs scrolling through the
        # contract/route lists to answer "how much am I making" or "what
        # size cargo hold do I need for this run." Lives outside both
        # scroll areas so it's visible without touching either. Created
        # once, text set in `_render_results()`.
        self._summary_label = QLabel("")
        self._summary_label.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-family: {theme.FONT_MONO}; "
            f"font-size: {theme.fpx(9)}px; letter-spacing: 0.5px;"
        )
        layout.addWidget(self._summary_label)

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

        # ---- freight manifest (running list of what's being hauled) -----
        # Added 2026-09-07 per user direction: a running total of every
        # commodity across all active contracts, so a duplicate — the same
        # freight picked up under two different contracts, which the game
        # makes very hard to tell apart once it's in the hold — is caught
        # by eye right after a scan, before it's a problem at the pickup
        # terminal. See docs/DECISIONS.md.
        manifest_title = QLabel("FREIGHT MANIFEST")
        manifest_title.setStyleSheet(self._title_style())
        layout.addWidget(manifest_title)

        self._manifest_scroll = QScrollArea()
        self._manifest_scroll.setWidgetResizable(True)
        self._manifest_scroll.setStyleSheet(
            f"QScrollArea {{ background: transparent; border: 1px solid {theme.BORDER_FLAT}; "
            f"border-radius: {theme.RADIUS}px; }}"
        )
        self._manifest_widget = QWidget()
        self._manifest_layout = QVBoxLayout(self._manifest_widget)
        self._manifest_layout.setContentsMargins(8, 8, 8, 8)
        self._manifest_layout.setSpacing(4)
        self._manifest_scroll.setWidget(self._manifest_widget)
        self._manifest_scroll.setMinimumHeight(60)
        self._manifest_scroll.setMaximumHeight(140)
        layout.addWidget(self._manifest_scroll)

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
        # Contracts persist across restarts, but _route_order is in-memory
        # only and starts empty — without recomputing it here, a relaunch
        # shows every persisted contract but an empty ROUTE section until
        # the next scan or location change happens to replan it.
        contracts = self.settings.get("contracts", [])
        if contracts:
            self._route_order = self._plan_route(contracts)
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
        """Make sure the card body (with the SET SCAN AREA button) is visible
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

    def _show_profile_popup(self):
        # `.get(key, {})` only falls back when the key is *absent* — the
        # key can legitimately be present with value `None` (e.g. never
        # set, or explicitly cleared), which crashed this the first time
        # it was live-tested. `or {}` covers both cases, same pattern
        # `_grade_contract()` already uses for the same field.
        profile = self.settings.get("hauler_profile") or {}
        capacity = self.settings.get("cargo_capacity_scu")
        popup = _HaulerProfilePopup(self._card_widget, profile, capacity, self._on_profile_saved)
        # Same reference-keeping fix as _review_popup below — a real
        # Qt.Window has no implicit reference keeping it alive once this
        # method returns.
        self._profile_popup = popup
        anchor = self._card_widget.mapToGlobal(self._card_widget.rect().topLeft())
        popup.move(anchor)
        popup.show()

    def _on_profile_saved(self, profile: dict, capacity: int | None):
        self.settings["hauler_profile"] = profile
        self.settings["cargo_capacity_scu"] = capacity
        self._save_settings()
        self._set_status(f"Profile saved: {profile.get('ship') or 'no ship set'}.")
        self._profile_popup = None
        # Cargo capacity feeds the card summary's over-capacity warning
        # directly — re-render so a changed value shows up immediately
        # instead of waiting for the next scan.
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
        self._pending_scan = None
        self._render_results()
        self._set_status("Contracts cleared.")

    def _safe_reprocess(self):
        try:
            self._reprocess_contracts()
        except Exception as exc:
            self._set_status(f"Error: {exc}")

    def _reprocess_contracts(self):
        """Re-run parsing (locations + commodities) against every saved
        contract's own stored `raw_text`, in place — no rescan needed. Added
        2026-09-05 specifically so a parsing bug fix (e.g. the commodity-
        quantity summing fix the same day) doesn't require CLEAR + rescanning
        everything from the game; the raw OCR text needed to re-derive a
        contract is already persisted (same text the debug log/COPY ROUTE
        export already use), `_build_contract` just never gets called on it
        again after the initial scan.

        Preserves each contract's original `id`/`scanned_at` rather than
        taking the freshly-rebuilt ones — `route_done` entries are keyed
        `f"{contract_id}:{role}:{index}"` (`_toggle_route_done`), so keeping
        the same id is what lets an already-marked-done stop stay correctly
        matched after reprocessing, as long as the fix didn't change how many
        pickups/dropoffs that contract has (true for the quantity fix; a
        parsing change that adds/removes a stop would leave a stale
        `route_done` entry pointing at nothing — same outcome CLEAR-and-
        rescan already has today, not a new failure mode)."""
        contracts = self.settings.get("contracts", [])
        if not contracts:
            self._set_status("No contracts to reprocess.")
            return
        rebuilt = []
        traces: list[list[dict]] = []
        for old in contracts:
            trace: list[dict] = []
            new = self._build_contract(old.get("raw_text", ""), debug_trace=trace)
            if new is None:
                # Nothing usable left in the saved text (shouldn't happen —
                # it parsed once already — but never silently drop a
                # contract over it) — keep the old entry as-is.
                rebuilt.append(old)
                traces.append(trace)
                continue
            new["id"] = old.get("id", new["id"])
            new["scanned_at"] = old.get("scanned_at", new["scanned_at"])
            rebuilt.append(new)
            traces.append(trace)
        self.settings["contracts"] = rebuilt
        route_debug: dict = {}
        self._route_order = self._plan_route(rebuilt, route_debug=route_debug)
        self._log_reprocess_debug(rebuilt, traces, route_debug)
        self._save_settings()
        self._render_results()
        self._set_status(f"Reprocessed {len(rebuilt)} contract(s) from saved OCR text.")

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
            self._set_status("No capture region set — use SET SCAN AREA on the card first.")
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

        debug_trace: list[dict] = []
        contract = self._build_contract(raw_text, debug_trace=debug_trace)
        if contract is None:
            raise ValueError("No usable text could be OCR'd — try adjusting the region or brightness.")

        candidates = _candidate_phrases(raw_text)

        # Every scan now pauses for a review popup — added 2026-09-07 per
        # user direction, replacing the old "auto-add unless duplicate"
        # behavior. Route/manifest are unchanged until ACCEPT is clicked,
        # so there's nothing new to compare yet — an empty dict, not None,
        # keeps _log_scan_debug's entry shape consistent either way.
        contracts = self.settings.setdefault("contracts", [])
        self._pending_scan = contract
        duplicate = any(self._is_likely_duplicate(c, contract) for c in contracts)
        # Computed once here (not inside _show_review_popup) so the popup
        # and the debug log entry below always agree on the same grade —
        # _grade_contract() calls _plan_route() twice, not worth doing
        # again just to log it.
        self._pending_grade = self._grade_contract(contract, contracts)
        self._show_review_popup(contract, duplicate, self._pending_grade)
        self._set_status("Review the scan — ACCEPT or REJECT.")
        self._log_scan_debug(
            raw_text, candidates, contract, "pending_review", debug_trace, {},
            grade=self._pending_grade,
        )

    def _log_scan_debug(
        self, raw_text: str, candidates: list[tuple[str, str, int]], contract: dict, note: str,
        debug_trace: list[dict], route_debug: dict,
        grade: tuple[int | None, str, bool] | None = None,
    ) -> None:
        """Append one JSON line per scan to an always-on debug log, so real
        usage accumulates into a file the user can hand to an AI later to
        evaluate whether parsing/routing is holding up. Mirrors the level of
        detail this session's own live debugging relied on (console output +
        COPY ROUTE export) — see docs/DECISIONS.md, 2026-09-04."""
        entry = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "note": note,
            "raw_text": raw_text,
            "candidates": [{"phrase": p, "hint": h, "priority": pr} for p, h, pr in candidates],
            "contract": contract,
            # One entry per candidate phrase recording how (or whether) it
            # resolved — added 2026-09-05 to make every candidate's fate
            # visible, including ones that get silently dropped (missed both
            # exact/substring and fuzzy matching) with no trace anywhere else.
            # See DECISIONS.md, 2026-09-05.
            "resolution_trace": debug_trace,
            # Pulled out to the top level for easy grepping, derived from the
            # trace above (not string-matched against ambiguous_notes text,
            # which is fragile if that wording ever changes).
            "fuzzy_matches": [e for e in debug_trace if e.get("outcome") == "resolved" and e.get("method") == "fuzzy"],
            # Greedy (pre-2-opt) route + cost alongside the final one, so a
            # log review can tell whether 2-opt actually improved anything
            # on this scan instead of only seeing the final route in
            # isolation — added 2026-09-05. Empty on "duplicate_pending"
            # (route isn't replanned until the contract is actually added).
            "route_debug": route_debug,
            "route_snapshot": self._format_route_text(),
            # Confirm-gate/grading fields — added 2026-09-07 so a review
            # popup's decision can actually be reconstructed from the log
            # later instead of only seeing raw text/parsing. `None` when
            # grading wasn't run for this entry (e.g. REPROCESS).
            "grade": grade[0] if grade else None,
            "grade_reason": grade[1] if grade else None,
            "grade_capped": grade[2] if grade else None,
        }
        self._append_debug_log(entry)

    def _log_reprocess_debug(
        self, contracts: list[dict], traces: list[list[dict]], route_debug: dict,
    ) -> None:
        """Append one JSON line for a REPROCESS run (added 2026-09-05,
        alongside the REPROCESS button itself) — mirrors `_log_scan_debug`'s
        shape but covers every reprocessed contract at once instead of a
        single fresh scan, since REPROCESS re-parses everything already
        saved in one pass rather than adding one new contract. Without
        this, a REPROCESS run (or a location change picked up by it) left
        no trace anywhere reviewable — only a live scan did."""
        entry = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "note": "reprocessed",
            "contracts": contracts,
            "resolution_traces": traces,
            "fuzzy_matches": [
                e for trace in traces for e in trace
                if e.get("outcome") == "resolved" and e.get("method") == "fuzzy"
            ],
            "route_debug": route_debug,
            "route_snapshot": self._format_route_text(),
        }
        self._append_debug_log(entry)

    def _append_debug_log(self, entry: dict) -> None:
        try:
            log_path = paths.app_root() / DEBUG_LOG_FILENAME
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            logger.warning("Failed to write logistics_hub debug log entry", exc_info=True)

    def _add_contract(self, contract: dict, route_debug: dict | None = None) -> None:
        contracts = self.settings.setdefault("contracts", [])
        contracts.append(contract)
        self._save_settings()
        self._route_order = self._plan_route(contracts, route_debug=route_debug)
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

    def _show_review_popup(self, contract: dict, duplicate: bool, grade_info: tuple[int | None, str, bool]):
        pickups_text = self._entry_names(contract.get("pickups", []), self._locations.display_name)
        dropoffs_text = self._entry_names(contract.get("dropoffs", []), self._locations.display_name)
        reward = contract.get("reward")
        # `reward` is the raw extracted string (e.g. "87,250"), already
        # comma-formatted from OCR text — not an int, same as every other
        # place in this file that displays it (_contract_row, etc.).
        reward_text = f"{reward} aUEC" if reward else "reward unknown"
        scu = sum(_entry_scu(e) for e in contract.get("pickups", []))
        summary_text = f"{pickups_text} → {dropoffs_text}\n{reward_text}  ·  {scu} SCU"

        duplicate_warning = (
            "Looks like a duplicate of a contract already in your queue "
            "(same reward, shares a location)." if duplicate else None
        )

        grade, grade_reason, grade_capped = grade_info

        ship = (self.settings.get("hauler_profile") or {}).get("ship", "").strip()
        ratings = self.settings.get("ship_location_ratings", {})
        unrated_terminals = []
        if ship:
            seen_keys = set()
            for terminal in self._contract_terminals(contract):
                key = self._compat_key(ship, terminal)
                if key in ratings or key in seen_keys:
                    continue
                seen_keys.add(key)
                unrated_terminals.append((self._locations.display_name(terminal), terminal))

        # Recorded here (not just saved to the ratings DB) so
        # _log_review_outcome() can put "what was asked, what was
        # answered" into the debug log when ACCEPT/REJECT is clicked —
        # added 2026-09-07.
        self._pending_unrated_names = [name for name, _t in unrated_terminals]
        self._pending_ratings_given = []

        def on_rate(terminal: dict, good: bool, label: str):
            self._rate_compatibility(ship, terminal, good)
            self._pending_ratings_given.append({"location": label, "rating": "good" if good else "bad"})

        popup = _ReviewPopup(
            self._card_widget, summary_text, duplicate_warning,
            grade, grade_reason, grade_capped, unrated_terminals,
            on_rate, self._on_review_accept, self._on_review_reject,
        )
        # Now a real Qt.Window (see _ReviewPopup's 2026-09-07 note), which
        # — unlike Qt.Popup — has no implicit reference keeping it alive.
        # Without this, the popup was garbage-collected right after this
        # method returns, before the user could even see it. Cleared in
        # both outcome handlers below.
        self._review_popup = popup
        anchor = self._scan_btn.mapToGlobal(self._scan_btn.rect().bottomLeft())
        popup.move(anchor)
        popup.show()

    def _log_review_outcome(self, contract: dict, outcome: str) -> None:
        """Appended when ACCEPT/REJECT is actually clicked — separate from
        the 'pending_review' entry `_log_scan_debug` writes at scan time,
        since that entry is written before the user has seen the popup
        and can't know the outcome yet. Added 2026-09-07 alongside the
        grading/compatibility-DB feature so a real session's decisions
        (not just its OCR/parsing) show up in the debug log."""
        entry = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "note": f"review_{outcome}",
            "contract_id": contract.get("id"),
            "grade": self._pending_grade[0] if self._pending_grade else None,
            "grade_reason": self._pending_grade[1] if self._pending_grade else None,
            "grade_capped": self._pending_grade[2] if self._pending_grade else None,
            "compatibility_prompts_shown": self._pending_unrated_names,
            "compatibility_ratings_given": self._pending_ratings_given,
        }
        self._append_debug_log(entry)

    def _on_review_accept(self):
        if self._pending_scan is not None:
            self._log_review_outcome(self._pending_scan, "accepted")
            self._add_contract(self._pending_scan)
        self._pending_scan = None
        self._review_popup = None

    def _on_review_reject(self):
        if self._pending_scan is not None:
            self._log_review_outcome(self._pending_scan, "rejected")
        self._pending_scan = None
        self._review_popup = None
        self._set_status("Contract not added.")

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
        # In-game UI text captured at native resolution is often small —
        # a single contract line can be well under 20px tall in a typical
        # capture region. OCR engines (EasyOCR included) read text
        # substantially more reliably above a certain pixel-height floor;
        # upscaling before detection, not relying on EasyOCR's own
        # internal `mag_ratio` resizing alone, is standard OCR-preprocessing
        # practice for small source text. LANCZOS (not the default
        # nearest-neighbor) keeps character edges reasonably clean at 2x
        # rather than introducing new blockiness. This is a one-off manual
        # scan, not a real-time loop, so the extra processing time is an
        # easy trade for better accuracy.
        OCR_UPSCALE_FACTOR = 2
        gray = gray.resize(
            (gray.width * OCR_UPSCALE_FACTOR, gray.height * OCR_UPSCALE_FACTOR),
            Image.LANCZOS,
        )
        gray = ImageOps.autocontrast(gray)

        if self._reader is None:
            self._reader = easyocr.Reader(["en"], gpu=False, verbose=False)

        import numpy as np
        # detail=1 (not the previous detail=0) so each result carries its
        # bounding box, not just bare text — needed by _order_ocr_boxes()
        # below to read the panel in genuine left-to-right, top-to-bottom
        # order. Without this, text came back in whatever order EasyOCR's
        # own internal sort happened to produce, which does NOT respect
        # the contract panel's real two-column layout (mission narrative
        # text next to a separate PICK UP/DROP OFF list) — confirmed to be
        # the root cause behind the large majority of parsing bugs fixed
        # this session (split location names, orphaned words, role
        # misattribution), all of which were really downstream symptoms of
        # reading the two columns interleaved instead of one at a time.
        results = self._reader.readtext(np.array(gray), detail=1, allowlist=OCR_ALLOWLIST)
        # `gray.width`, not `pil_rgb.width` — bounding boxes from EasyOCR
        # are in the *upscaled* image's coordinate space, so the column-
        # gap threshold in _order_ocr_boxes needs to be computed against
        # that same scale, not the original pre-upscale capture width.
        lines = _order_ocr_boxes(results, gray.width)
        return "\n".join(lines)

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

    def _build_contract(self, raw_text: str, debug_trace: list[dict] | None = None) -> dict | None:
        """Build one contract from a scan's OCR text: pull every plausible
        location phrase, resolve each against real UEX terminal data, and
        split the distinct resolved terminals into pickups vs. drop-offs by
        role hint. A contract can have several of *either* — real panels use
        one pickup with several drop-offs (DROP OFF LOCATIONS (ANY ORDER))
        just as often as one drop-off with several pickups (PICK UP
        LOCATIONS (ANY ORDER)). Falls back to raw, unresolved candidate
        phrases if nothing resolved at all, so a scan still produces
        something reviewable instead of silently failing.

        `debug_trace`, if given, gets one entry appended per candidate
        recording its resolution outcome (`resolved` + which of the five
        resolution paths won, `ambiguous_unresolved`, or `dropped_no_match`
        — the last including a near-miss fuzzy score when one was attempted)
        for `_log_scan_debug`. Purely additive/observational — never affects
        which terminal a candidate actually resolves to."""
        candidates = _candidate_phrases(raw_text)  # list of (phrase, hint, priority)
        reward = _extract_reward(raw_text)
        trace: list[dict] = []

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
                # Two different UEX records can be the exact same real
                # place — a `terminals` kiosk and the `space_stations`/
                # `outposts`/`cities` record it structurally belongs to
                # (see `LocationService.same_physical_place()`) — and
                # `terminal_key()` alone can't tell. Confirmed real: "Seraphim
                # The" and "Seraphim Station" resolved to two different
                # records for the same real station, producing a duplicate
                # route stop that got visited twice for no reason. Check
                # already-resolved entries for a same-place match before
                # creating a new one, so both mentions land in the same
                # entry regardless of which specific record either resolved
                # to.
                for existing_key in order:
                    if self._locations.same_physical_place(terminal, resolved_by_key[existing_key][1]):
                        key = existing_key
                        # Prefer a structural (`space_stations`/`outposts`/
                        # `cities`) record as the merged entry's display
                        # terminal over a `terminals` kiosk record — a
                        # kiosk's own name/nickname is often the raw,
                        # unfriendly in-game label ("Admin - MIC-L2") while
                        # the structural record has the real place name
                        # ("MIC-L2 Long Forest Station"). Confirmed real:
                        # without this, merging could regress an
                        # already-correct display name to the uglier one
                        # just because of merge order.
                        existing_terminal = resolved_by_key[existing_key][1]
                        if existing_terminal.get("_endpoint") == "terminals" and terminal.get("_endpoint") != "terminals":
                            resolved_by_key[existing_key][1] = terminal
                        break
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
                # No exact/substring hit at all — for a candidate that
                # actually carries a real pickup/dropoff signal (never for
                # "neutral" text, same gating the ambiguous-note path below
                # uses), try a fuzzy match rather than silently dropping the
                # stop. OCR can garble a name just enough to miss substring
                # matching entirely ("Seraphim Staton") without being
                # unreadable — resolving it anyway, visibly flagged as
                # unconfirmed via the same amber-warning mechanism as an
                # ambiguous match, beats a contract missing a stop outright.
                if hint != "neutral":
                    fuzzy = self._locations.resolve_fuzzy(text)
                    if fuzzy is not None:
                        location, score = fuzzy
                        merge_resolved(text, location, hint, priority)
                        display = self._locations.display_name(location)
                        trace.append({
                            "phrase": text, "hint": hint, "outcome": "resolved",
                            "method": "fuzzy", "matched": display, "score": round(score, 3),
                        })
                        if text.lower() not in noted:
                            noted.add(text.lower())
                            ambiguous_notes.append(
                                f"{text!r} ({hint}) fuzzy-matched to {display} "
                                f"({score:.0%} confidence) — please verify"
                            )
                    else:
                        near_miss = self._locations.best_fuzzy_match(text)
                        trace.append({
                            "phrase": text, "hint": hint, "outcome": "dropped_no_match",
                            "near_miss": (
                                {"matched": self._locations.display_name(near_miss[0]), "score": round(near_miss[1], 3)}
                                if near_miss else None
                            ),
                        })
                else:
                    trace.append({"phrase": text, "hint": hint, "outcome": "dropped_no_match", "near_miss": None})
                continue
            if len(matches) > 1 and hint != "neutral":
                pending_ambiguous.append((text, hint, priority, matches))
                continue
            merge_resolved(text, matches[0], hint, priority)
            trace.append({
                "phrase": text, "hint": hint, "outcome": "resolved",
                "method": "exact_or_substring", "matched": self._locations.display_name(matches[0]),
            })

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
            method = "suffix_disambiguation"
            if disambiguated is None:
                already_confirmed = [
                    m for m in matches
                    if self._locations.terminal_key(m) in resolved_by_key
                ]
                if len(already_confirmed) == 1:
                    disambiguated = already_confirmed[0]
                    method = "already_confirmed_elsewhere"

            if disambiguated is not None:
                merge_resolved(text, disambiguated, hint, priority)
                trace.append({
                    "phrase": text, "hint": hint, "outcome": "resolved",
                    "method": method, "matched": self._locations.display_name(disambiguated),
                })
                continue

            options = ", ".join(self._locations.display_name(m) for m in matches[:5])
            trace.append({"phrase": text, "hint": hint, "outcome": "ambiguous_unresolved", "options": options})
            if text.lower() not in noted:
                noted.add(text.lower())
                ambiguous_notes.append(f"{text!r} ({hint}) could be: {options} — not auto-resolved")

        resolved: list[tuple[str, dict, str, set]] = [
            (resolved_by_key[k][0], resolved_by_key[k][1], resolved_by_key[k][2], resolved_by_key[k][4])
            for k in order
        ]

        if debug_trace is not None:
            debug_trace.extend(trace)

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
    def _entry_commodities(raw_text: str, entry: dict, role: str) -> list[tuple[str, str | None]]:
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
        qty_by_commodity = _commodity_quantities(raw_text)
        found: list[tuple[str, str | None]] = []
        seen: set[str] = set()
        for key in keys:
            for commodity, qty in _extract_commodities(raw_text, key, role, qty_by_commodity):
                ck = commodity.lower()
                if ck not in seen:
                    seen.add(ck)
                    found.append((commodity, qty))
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

    def _plan_route(self, contracts: list[dict], route_debug: dict | None = None) -> list[tuple[int, str, int]]:
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

        `route_debug`, if given, gets filled with the greedy route (before
        2-opt) alongside the final one plus both total costs — added
        2026-09-05 so a review of the debug log can tell whether 2-opt
        actually improved anything on a given scan, not just see the final
        route in isolation."""
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
                # Tie-break toward drop-off over pickup at equal cost (e.g.
                # two stops at the same real station, "same stop" cost 0) —
                # per user direction, clearing cargo you're already carrying
                # takes priority over loading more while you're standing at
                # a station that needs both. `min` is stable, so without
                # this the winner on a tie was just whichever node happened
                # to come first in `nodes` (pickups are built before
                # drop-offs per contract in `_stop_nodes`, so pickups won
                # every tie by accident, not by design).
                best = min(
                    candidates,
                    key=lambda idx: (
                        self._cost_to_node(contracts, nodes[idx], current_terminal, current_raw),
                        0 if nodes[idx][1] == "dropoff" else 1,
                    ),
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

        # Alternate 2-opt (segment reversal) and Or-opt (single-stop
        # relocation) until neither improves — 2-opt alone can never merge
        # two non-adjacent visits to the same real terminal (one a pickup
        # for one contract, one a dropoff for another) into a single stop,
        # since that requires moving one node past several others without
        # reversing anything between them, a different move type Or-opt
        # covers. Confirmed real on live data: Everus Harbor got visited
        # twice in one route when only 2-opt ran (see DECISIONS.md,
        # 2026-09-05). Each accepted move in either pass strictly lowers
        # cost, so this converges fast in practice — the round cap is a
        # termination safety net, not expected to bind.
        current = route
        rounds_run = 0
        for rounds_run in range(1, 6):
            after = self._two_opt(contracts, current, start_terminal, start_raw, pickups_needed)
            after = self._or_opt(contracts, after, start_terminal, start_raw, pickups_needed)
            if after == current:
                break
            current = after
        final = current

        if route_debug is not None:
            greedy_cost = self._route_cost(contracts, route, start_terminal, start_raw)
            final_cost = self._route_cost(contracts, final, start_terminal, start_raw)
            route_debug["greedy_order"] = [self._node_label(contracts, node) for node in route]
            route_debug["greedy_cost"] = round(greedy_cost, 1)
            route_debug["final_order"] = [self._node_label(contracts, node) for node in final]
            route_debug["final_cost"] = round(final_cost, 1)
            route_debug["optimized_improved_by"] = round(greedy_cost - final_cost, 1)
            route_debug["rounds_run"] = rounds_run

        return final

    def _node_label(self, contracts: list[dict], node) -> str:
        i, role, _j = node
        terminal = self._node_terminal(contracts, node)
        name = self._locations.display_name(terminal) if terminal else self._node_raw(contracts, node)
        return f"[{role.upper()}] {name} (contract {i})"

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

    def _or_opt(
        self,
        contracts: list[dict],
        seq: list,
        start_terminal: dict | None,
        start_raw: str | None,
        pickups_needed: list[int],
    ) -> list:
        """Or-opt local search: repeatedly try relocating a single stop to a
        different position in the route, keeping the move if it lowers total
        cost and doesn't put a drop-off before its own contract's pickup.
        Complements `_two_opt` above, which can only reverse segments — it
        can never merge two non-adjacent visits to the same real terminal
        (once as a pickup for one contract, once as a dropoff for another)
        into one stop, since that means moving one node past several others
        without reversing anything between them. Confirmed real on live data
        (see DECISIONS.md, 2026-09-05): Everus Harbor was visited twice in
        one route, `_two_opt` alone never found the merge. Runs until a full
        pass finds no improving move — same convergence pattern as
        `_two_opt`, same cost bound at real session stop-counts."""
        best = list(seq)
        best_cost = self._route_cost(contracts, best, start_terminal, start_raw)
        n = len(best)

        improved = True
        while improved:
            improved = False
            for i in range(n):
                node = best[i]
                remaining = best[:i] + best[i + 1:]
                # Stop scanning j as soon as `best` changes — `node`/
                # `remaining` were captured from the pre-move sequence, so
                # continuing to build candidates from them after a move
                # would silently discard the just-found improvement instead
                # of building on it. The outer `while improved` loop picks
                # up any further gains in the next full pass, same as
                # `_two_opt`'s own convergence pattern.
                for j in range(len(remaining) + 1):
                    candidate = remaining[:j] + [node] + remaining[j:]
                    if not self._respects_precedence(contracts, candidate, pickups_needed):
                        continue
                    cost = self._route_cost(contracts, candidate, start_terminal, start_raw)
                    if cost < best_cost - 1e-9:
                        best, best_cost = candidate, cost
                        improved = True
                        break
                if improved:
                    break
        return best

    def _cost_to_node(self, contracts: list[dict], node, from_terminal: dict | None, from_raw: str | None) -> float:
        term_b = self._node_terminal(contracts, node)
        if from_terminal and term_b:
            return self._terminal_cost(from_terminal, term_b)
        return COST_UNRESOLVED + self._text_cost(from_raw or "", self._node_raw(contracts, node))

    def _terminal_cost(self, a: dict, b: dict) -> float:
        if self._locations.same_physical_place(a, b):
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
    def _freight_manifest(contracts: list[dict]) -> dict:
        """Commodity name -> {"scu": total SCU across every contract
        hauling it, "contract_count": how many distinct contracts that is}.
        Read from each contract's *pickups* only — a pickup entry already
        holds that contract's contract-wide total for a commodity (see the
        2026-09-05 quantity-summing fix), so drop-offs would double-count
        the same freight split across multiple destinations. Within one
        contract, quantities are summed across its pickups first so a
        commodity appearing at two pickups in the same contract counts
        once at its true total rather than twice."""
        manifest: dict[str, dict] = {}
        for contract in contracts:
            contract_totals: dict[str, int] = {}
            for entry in contract.get("pickups", []):
                for c in entry.get("commodities") or []:
                    if isinstance(c, (list, tuple)):
                        name, qty = c
                    else:
                        name, qty = c, None
                    qty = int(qty) if qty and str(qty).isdigit() else 0
                    contract_totals[name] = contract_totals.get(name, 0) + qty
            for name, qty in contract_totals.items():
                row = manifest.setdefault(name, {"scu": 0, "contract_count": 0})
                row["scu"] += qty
                row["contract_count"] += 1
        return manifest

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
        endpoint, term_id = LocationService.terminal_key(terminal)
        return f"{ship.strip().lower()}::{endpoint}:{term_id}"

    @staticmethod
    def _contract_terminals(contract: dict) -> list[dict]:
        """Every *resolved* pickup/dropoff terminal in a contract — skips
        entries that never matched real UEX data, since there's nothing to
        key a compatibility rating on for those."""
        return [
            e["terminal"] for e in contract.get("pickups", []) + contract.get("dropoffs", [])
            if e.get("terminal")
        ]

    def _rate_compatibility(self, ship: str, terminal: dict, good: bool) -> None:
        ratings = self.settings.setdefault("ship_location_ratings", {})
        ratings[self._compat_key(ship, terminal)] = "good" if good else "bad"
        self._save_settings()

    def _grade_contract(self, contract: dict, existing_contracts: list[dict]) -> tuple[int | None, str, bool]:
        """0-100 score + one-line reason + whether a hard warning capped
        it, for a freshly-scanned contract — or `(None, prompt, False)` if
        the Hauler Profile isn't set yet, since grading never guesses at a
        ship/preferences it doesn't have. Shown as a percentage rather than
        a letter grade per user direction, 2026-09-07 — reads more
        precisely than 5 coarse bands.

        Three things cap the score regardless of how well everything else
        scores — the exact "90% great, one hard no" case that prompted
        this feature: a known-BAD ship/location match or a duplicate-
        freight overlap (both cap at `GRADE_CAP_ON_WARNING`), and combined
        cargo capacity overflow (cap at the stricter
        `CAPACITY_OVERFLOW_CAP` — physically can't complete the run as
        queued, a harder constraint than the other two). `capped` is
        returned separately from the score (not inferred from it) so the
        UI can flag it visually even when the capped score still looks
        decent at a glance, e.g. 55%."""
        profile = self.settings.get("hauler_profile") or {}
        ship = (profile.get("ship") or "").strip()
        if not ship:
            return None, "Set your PROFILE for a grade.", False

        ratings = self.settings.get("ship_location_ratings", {})
        reasons: list[str] = []
        points = 50  # neutral baseline
        cap_ceiling = 100  # lowered below if a hard-warning trigger fires; the strictest one wins

        bad_locations = [
            self._locations.display_name(t) for t in self._contract_terminals(contract)
            if ratings.get(self._compat_key(ship, t)) == "bad"
        ]
        if bad_locations:
            cap_ceiling = min(cap_ceiling, GRADE_CAP_ON_WARNING)
            # No emoji here — this line renders in the Orbitron display
            # font (FONT_DISPLAY), which doesn't cover ⚠ and rendered it
            # as a tofu box when tried live. `capped` itself (returned
            # separately below) is what drives the warning color in the
            # UI, so the text doesn't need to carry its own glyph.
            reasons.append(f"marked BAD for {ship} at {', '.join(bad_locations)}")

        # Combined peak cargo (everything already queued + this candidate)
        # against the manually-set ship capacity — added 2026-09-07 after
        # a live test showed a contract needing ~4x the user's actual
        # capacity still scored decently, since grading never checked this
        # at all (capacity checking already existed on the card's own
        # summary line, just never wired into grading — a real oversight,
        # not a deliberate scoring choice). Reuses the candidate route
        # already being planned for the detour-cost check below rather
        # than planning it twice.
        combined_contracts = existing_contracts + [contract]
        candidate_debug: dict = {}
        candidate_route = self._plan_route(combined_contracts, route_debug=candidate_debug)
        capacity = self.settings.get("cargo_capacity_scu")
        if capacity:
            peak = self._peak_cargo_scu(combined_contracts, candidate_route)
            if peak > capacity:
                cap_ceiling = min(cap_ceiling, CAPACITY_OVERFLOW_CAP)
                reasons.append(f"{peak} SCU peak exceeds {capacity} SCU capacity by {peak - capacity}")

        manifest = self._freight_manifest(existing_contracts + [contract])
        candidate_commodities = set()
        for entry in contract.get("pickups", []):
            for c in entry.get("commodities") or []:
                name = c[0] if isinstance(c, (list, tuple)) else c
                candidate_commodities.add(name)
        overlapping = sorted(
            name for name in candidate_commodities
            if manifest.get(name, {}).get("contract_count", 0) > 1
        )
        if overlapping:
            cap_ceiling = min(cap_ceiling, GRADE_CAP_ON_WARNING)
            reasons.append(f"{', '.join(overlapping)} already queued elsewhere")

        reward_digits = (contract.get("reward") or "").replace(",", "")
        reward_val = int(reward_digits) if reward_digits.isdigit() else 0
        scu = sum(_entry_scu(e) for e in contract.get("pickups", []))
        if reward_val and scu:
            per_scu = reward_val / scu
            if per_scu >= 500:
                points += 25
                reasons.append(f"{per_scu:.0f} aUEC/SCU (great)")
            elif per_scu >= 200:
                points += 10
                reasons.append(f"{per_scu:.0f} aUEC/SCU (good)")
            elif per_scu >= 80:
                reasons.append(f"{per_scu:.0f} aUEC/SCU (ok)")
            else:
                points -= 15
                reasons.append(f"{per_scu:.0f} aUEC/SCU (low)")
        else:
            reasons.append("reward or cargo unknown")

        baseline_debug: dict = {}
        self._plan_route(existing_contracts, route_debug=baseline_debug)
        # candidate_debug/candidate_route already computed above for the
        # capacity check — reused here rather than replanning a second time.
        marginal = candidate_debug.get("final_cost", 0.0) - baseline_debug.get("final_cost", 0.0)
        if marginal <= 50:
            points += 15
            reasons.append("minimal detour")
        elif marginal <= 150:
            points += 5
            reasons.append("moderate detour")
        else:
            points -= 15
            reasons.append("big detour")

        systems = {
            t.get("star_system_name") for t in self._contract_terminals(contract)
            if t.get("star_system_name")
        }
        current_terminal = self._current_location_terminal()
        current_system = current_terminal.get("star_system_name") if current_terminal else None

        if profile.get("region_pref") == "Current system only" and current_system and any(
            s != current_system for s in systems
        ):
            points -= 10
            reasons.append("crosses systems")

        if profile.get("risk") == "Safe systems only" and systems & RISKY_SYSTEMS:
            points -= 15
            reasons.append(f"routes through {'/'.join(systems & RISKY_SYSTEMS)}")

        points = max(0, min(100, points))
        capped = cap_ceiling < 100
        if capped:
            points = min(points, cap_ceiling)

        reason_text = "; ".join(reasons) if reasons else "no strong signal either way"
        return points, reason_text, capped

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


MODULE_CLASS = LogisticsHubModule
