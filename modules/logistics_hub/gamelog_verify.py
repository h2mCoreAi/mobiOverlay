"""Verifies a freshly-OCR'd hauling contract against Star Citizen's own
``Game.log`` at the moment it's accepted — see docs/DECISIONS.md for the
full design/verification write-up.

Star Citizen writes several real signals into Game.log the instant a
contract is accepted, well before its `MissionEnded`/payout lines:

  ``Contract Accepted:  <title>: `` — the friendly title, which for the
  common "<rank> | <DIRECT?> <size> Haul | <Origin> > <Destination>"
  template names both stops directly.

  ``New Objective: Deliver <have>/<need> <unit> of <commodity> to
  <destination>: `` — fired once per drop-off leg, giving an exact
  tonnage/commodity/destination the OCR pass has to guess at from a
  screenshot.

Both carry a ``MissionId:`` that ties every line for one contract
together. Real example (this session, live log)::

    <2026-09-08T00:29:36.673Z> [Notice] <SHUDEvent_OnNotification> Added
      notification "Contract Accepted:  Experienced | <EM3>DIRECT</EM3>
      Medium Haul | Everus Harbor > Teasa Spaceport <EM4>[BP]*</EM4>: "
      [3] to queue. New queue size: 1, MissionId: [acf855f6-...],
      ObjectiveId: [] [Team_CoreGameplayFeatures][Missions][Comms]
    <2026-09-08T00:29:36.673Z> [Notice] <SHUDEvent_OnNotification> Added
      notification "New Objective: Deliver 0/16 SCU of Pressurized Ice to
      Teasa Spaceport: " [4] to queue. ... MissionId: [acf855f6-...],
      ObjectiveId: [dropoff_fc5c71cc-..._0] [...]

This module is intentionally narrow: a one-shot "does the log confirm what
OCR found, and can it correct anything" check run once, at ACCEPT. It does
NOT track live progress, payout, or per-box manifests — see the sc-overlay
project (github.com/SubliminalsTV-Projects/sc-overlay) for that much larger
surface, which this deliberately does not attempt to replicate.

Log wins whenever it reports something (destination name, commodity,
tonnage) — OCR fills in anything the log doesn't cover (reward, per-box
detail). No match found (contract not yet accepted in-game, log
unavailable, or nothing in the time window) leaves the OCR-built contract
untouched — this is a best-effort correction, never a hard requirement.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone

# Common install location — the only candidate worth guessing at. Anything
# else needs the user to set `game_log_path` in settings (Hauler Profile
# popup, GAME.LOG PATH field).
_DEFAULT_CANDIDATES = [
    r"C:\Program Files\Roberts Space Industries\StarCitizen\LIVE\Game.log",
]

_LINE_TS_RE = re.compile(r"^<(?P<ts>[0-9T:.\-]+)Z?>")
_EM_TAG_RE = re.compile(r"</?EM\d+>")

# `.*?` before MissionId (not a tighter bound) because CIG's own notification
# text can itself contain "]" (e.g. "<EM4>[BP]*</EM4>"), so anchoring on the
# first "]" after the quoted text would truncate mid-title.
_CONTRACT_ACCEPTED_RE = re.compile(
    r'Added notification "Contract Accepted:\s*(?P<title>.*?):\s*"\s*\[\d+\].*?'
    r"MissionId: \[(?P<mission_id>[0-9a-fA-F-]+)\]"
)
_DELIVER_RE = re.compile(
    r'Added notification "New Objective: Deliver (?P<have>\d+)/(?P<need>\d+) '
    r"(?P<unit>SCU|[Bb]oxes|[Ii]tems) of (?P<commodity>.+?) to (?P<destination>.+?):\s*"
    r'"\s*\[\d+\].*?MissionId: \[(?P<mission_id>[0-9a-fA-F-]+)\]'
)

# How far from "now" (wall clock, at the moment ACCEPT is clicked) a log
# line can be and still count as "this scan" — generous because there's no
# guarantee the player clicked Accept in-game and in mobiOverlay at the
# same instant, only that they're the same session, close in time.
DEFAULT_WINDOW_SECONDS = 180


def default_game_log_path() -> str | None:
    for candidate in _DEFAULT_CANDIDATES:
        if os.path.isfile(candidate):
            return candidate
    return None


_TRAILING_MARKER_RE = re.compile(r"\s*\[[A-Za-z]+\]\*?\s*$")


def _clean_title(title: str) -> str:
    """Strips CIG's `<EM3>..</EM3>` emphasis tags and a trailing reward-type
    marker like " [BP]*" (Blueprint) that rides along on the destination
    half of the title in the real observed line — neither is part of an
    actual place name."""
    cleaned = _EM_TAG_RE.sub("", title).strip()
    return _TRAILING_MARKER_RE.sub("", cleaned).strip()


def _parse_ts(raw: str) -> datetime | None:
    try:
        return datetime.strptime(raw.rstrip("Z"), "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _tail_lines(log_path: str, max_bytes: int = 500_000) -> list[str]:
    """Reads only the last `max_bytes` of the log — it can run into the
    hundreds of MB over a session, and only the last few minutes are ever
    relevant to a just-clicked ACCEPT. Never raises: an unreadable/missing
    file just means "nothing found", same as no match."""
    try:
        size = os.path.getsize(log_path)
        with open(log_path, "rb") as handle:
            if size > max_bytes:
                handle.seek(size - max_bytes)
            data = handle.read()
        return data.decode("utf-8", errors="ignore").splitlines()
    except OSError:
        return []


def find_recent_haul_events(
    log_path: str, now: datetime, window_seconds: int = DEFAULT_WINDOW_SECONDS
) -> list[dict]:
    """Scans the tail of Game.log for Contract Accepted / Deliver lines
    within `window_seconds` of `now`, grouped by mission id.

    Returns a list of::

        {"mission_id": str, "title": str | None, "origin": str | None,
         "destination": str | None, "legs": [{"commodity", "need", "unit",
         "destination"}, ...]}

    `origin`/`destination` on the top-level entry come from the "Origin >
    Destination" title template when present; `legs` is only ever
    populated from actual "Deliver" lines, which is why it can be empty
    even for a real hauling contract (log line arrives slightly async).
    """
    accepted: dict[str, dict] = {}
    legs_by_mission: dict[str, list[dict]] = {}

    for line in _tail_lines(log_path):
        ts_match = _LINE_TS_RE.match(line)
        if not ts_match:
            continue
        ts = _parse_ts(ts_match.group("ts"))
        if ts is None or abs((now - ts).total_seconds()) > window_seconds:
            continue

        match = _CONTRACT_ACCEPTED_RE.search(line)
        if match:
            title = _clean_title(match.group("title"))
            origin = destination = None
            for part in title.split("|"):
                if ">" in part:
                    left, right = part.split(">", 1)
                    origin, destination = left.strip(), right.strip()
                    break
            accepted[match.group("mission_id")] = {
                "mission_id": match.group("mission_id"),
                "title": title,
                "origin": origin,
                "destination": destination,
            }
            continue

        match = _DELIVER_RE.search(line)
        if match:
            legs_by_mission.setdefault(match.group("mission_id"), []).append(
                {
                    "commodity": match.group("commodity").strip(),
                    "need": int(match.group("need")),
                    "unit": match.group("unit").lower(),
                    "destination": match.group("destination").strip(),
                }
            )

    events = []
    for mission_id in set(accepted) | set(legs_by_mission):
        entry = dict(
            accepted.get(
                mission_id,
                {"mission_id": mission_id, "title": None, "origin": None, "destination": None},
            )
        )
        entry["legs"] = legs_by_mission.get(mission_id, [])
        events.append(entry)
    return events


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _names_overlap(a: str, b: str) -> bool:
    return bool(a) and bool(b) and (a in b or b in a)


def _entry_display_name(entry: dict, display_name) -> str:
    """Same lookup `_entry_names()`/`_contract_row()` use in module.py:
    `display_name` (LocationService.display_name) takes a terminal record,
    not a pickup/dropoff entry — an entry wraps one in `entry["terminal"]`
    and falls back to its raw OCR text when nothing resolved."""
    terminal = entry.get("terminal")
    return display_name(terminal) if terminal else (entry.get("raw") or "")


def verify_contract(contract: dict, log_events: list[dict], display_name) -> dict:
    """Tries to match one Game.log haul event to `contract` (as built by
    `_build_contract` from OCR) and reports what it found. Never mutates
    `contract` itself, and never raises — the caller decides whether/how
    to apply `corrections`.

    `display_name` is `LocationService.display_name`, passed in rather than
    imported so this stays a plain function, testable with fake data and no
    Qt/host dependency.

    Matching is name-overlap scoring, not an exact join — OCR's resolved
    location names and the log's raw destination text are never guaranteed
    to be worded identically ("Teasa Spaceport" vs. a fuller UEX display
    name), so a substring-either-way match on normalized text is the same
    tolerance this module already uses elsewhere (`_candidate_phrases`,
    `LocationService.resolve_fuzzy`).

    Always returns a `reason` and `candidates_considered` (every log event
    that was scored, its title/mission_id and score, highest first) even on
    a match — added 2026-09-08 after a live first test raised "why didn't
    this help" with nothing in the debug log to answer it. This is the
    thing to read when a scan surfaces something OCR couldn't auto-resolve
    and you're wondering why Game.log didn't fill the gap: this function
    only ever *corrects a dropoff's commodity/tonnage*, and only for a
    dropoff OCR already resolved to a real location — it never resolves an
    unmatched/ambiguous location candidate itself. A location OCR couldn't
    resolve at all needs a different fix (better candidate/fuzzy matching
    in `_build_contract`), not this pass.
    """
    dropoff_names = [_normalize(_entry_display_name(e, display_name)) for e in contract.get("dropoffs", [])]
    pickup_names = [_normalize(_entry_display_name(e, display_name)) for e in contract.get("pickups", [])]

    scored: list[tuple[int, dict]] = []
    for event in log_events:
        score = 0
        ev_destination = _normalize(event.get("destination") or "")
        ev_origin = _normalize(event.get("origin") or "")
        if any(_names_overlap(ev_destination, name) for name in dropoff_names):
            score += 2
        if any(_names_overlap(ev_origin, name) for name in pickup_names):
            score += 2
        for leg in event.get("legs", []):
            leg_destination = _normalize(leg["destination"])
            if any(_names_overlap(leg_destination, name) for name in dropoff_names):
                score += 1
        scored.append((score, event))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    candidates_considered = [
        {"mission_id": event["mission_id"], "title": event.get("title"), "score": score}
        for score, event in scored
    ]

    if not log_events:
        return {
            "matched": False,
            "mission_id": None,
            "title": None,
            "corrections": [],
            "reason": "no_log_events_in_window",
            "candidates_considered": [],
            "dropoff_names_tried": dropoff_names,
            "pickup_names_tried": pickup_names,
        }

    best_score, best_event = scored[0]
    if best_score == 0:
        return {
            "matched": False,
            "mission_id": None,
            "title": None,
            "corrections": [],
            "reason": "no_name_overlap_with_any_candidate",
            "candidates_considered": candidates_considered,
            "dropoff_names_tried": dropoff_names,
            "pickup_names_tried": pickup_names,
        }

    corrections: list[dict] = []
    for leg in best_event.get("legs", []):
        leg_destination_norm = _normalize(leg["destination"])
        for entry in contract.get("dropoffs", []):
            entry_name = _entry_display_name(entry, display_name)
            if not _names_overlap(leg_destination_norm, _normalize(entry_name)):
                continue
            existing = entry.get("commodities") or []
            already_matches = any(
                isinstance(c, (list, tuple))
                and c[0].lower() == leg["commodity"].lower()
                and str(c[1]) == str(leg["need"])
                for c in existing
            )
            if already_matches:
                continue
            corrections.append(
                {
                    "destination": entry_name,
                    "commodity": leg["commodity"],
                    "need": leg["need"],
                    "unit": leg["unit"],
                    "previous_commodities": existing,
                }
            )
            entry["commodities"] = [(leg["commodity"], str(leg["need"]))]

    return {
        "matched": True,
        "mission_id": best_event["mission_id"],
        "title": best_event.get("title"),
        "corrections": corrections,
        "reason": "matched_with_corrections" if corrections else "matched_no_corrections_needed",
        "candidates_considered": candidates_considered,
        "dropoff_names_tried": dropoff_names,
        "pickup_names_tried": pickup_names,
    }
