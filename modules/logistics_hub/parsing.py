"""Pure contract-text parsing for Logistics Hub: turns OCR'd mission-board
text into commodities, quantities, rewards and candidate location phrases.

No Qt, no UEX/network access, no module state — everything here is a plain
function of its arguments, which is what makes it directly testable
(tests/test_logistics_hub_parsing.py) and safe to call from any thread.
Loaded by modules/logistics_hub/module.py by file path (see the note there).
"""
import re

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
    # "Covalex Shipping" — the mission-giver company's own name, mentioned
    # in every Covalex contract's flavor text ("Covalex Shipping is a
    # limited liability corporation...") — substring-matches a real UEX
    # location literally named "Covalex Orison", producing a phantom
    # dropoff with no real cargo data ("cargo unknown") and, worse,
    # blocking Game.log verification's commodity/tonnage correction from
    # ever attaching (it can't match a dropoff name Game.log never
    # mentions). Confirmed real and repeated across two separate sessions'
    # debug logs (2026-09-07 and 2026-09-08) — see docs/DECISIONS.md.
    # "Covalex Shippina" is the same real phrase via a common OCR
    # letter-substitution typo; excluded alongside it pre-emptively even
    # though it's only ever been observed failing to match harmlessly so
    # far, since it's the identical underlying noise source.
    "covalex shipping", "covalex shippina",
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
