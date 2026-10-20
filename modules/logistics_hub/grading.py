"""Logistics Hub contract grading: the 0-100 score for a freshly scanned
contract, the Freight Manifest, and the (ship, location) compatibility key.

No Qt and no module state — `grade_contract()` is handed the profile,
ratings and thresholds plus callables for route planning and cargo peaks,
so it is directly testable (tests/test_logistics_hub_parsing.py). Loaded by
modules/logistics_hub/module.py by file path.
"""
from host.locations import LocationService

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

# Default aUEC/SCU thresholds for the reward-efficiency part of grading —
# user-editable via the Hauler Profile's GRADING SCALE table
# (`self.settings["grading_thresholds"]`), these are only the fallback
# when nothing's been saved yet. First-pass guesses (500/200/80) were
# checked 2026-09-07 against this project's own 10 real captured contract
# fixtures and found to be miscalibrated low — every real contract in that
# set scored "good" or better, real observed range was ~520-4,300 — but
# rather than guess a second, equally unverified set of numbers, this is
# now the user's own call to tune, not something hardcoded from research
# that turned out unreliable.
DEFAULT_GRADING_THRESHOLDS = {"great": 500, "good": 200, "ok": 80}


def freight_manifest(contracts: list[dict]) -> dict:
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


def compat_key(ship: str, terminal: dict) -> str:
    endpoint, term_id = LocationService.terminal_key(terminal)
    return f"{ship.strip().lower()}::{endpoint}:{term_id}"


def contract_terminals(contract: dict) -> list[dict]:
    """Every *resolved* pickup/dropoff terminal in a contract — skips
    entries that never matched real UEX data, since there's nothing to
    key a compatibility rating on for those."""
    return [
        e["terminal"] for e in contract.get("pickups", []) + contract.get("dropoffs", [])
        if e.get("terminal")
    ]


def grade_contract(
    contract: dict,
    existing_contracts: list[dict],
    *,
    profile: dict | None,
    ratings: dict | None,
    capacity: int | None,
    thresholds: dict | None,
    current_terminal: dict | None,
    pickup_scu: int,
    display_name,
    plan_route,
    peak_cargo_scu,
) -> tuple[int | None, str, bool]:
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
    decent at a glance, e.g. 55%.

    Everything the module owns is passed in rather than read from `self`:
    `plan_route(contracts, route_debug=None)`, `peak_cargo_scu(contracts, route)` and
    `display_name(terminal)` are callables; `pickup_scu` is the candidate's total
    pickup SCU (parsing._entry_scu summed by the caller)."""
    profile = profile or {}
    ship = (profile.get("ship") or "").strip()
    if not ship:
        return None, "Set your PROFILE for a grade.", False

    ratings = ratings or {}
    reasons: list[str] = []
    points = 50  # neutral baseline
    cap_ceiling = 100  # lowered below if a hard-warning trigger fires; the strictest one wins

    bad_locations = [
        display_name(t) for t in contract_terminals(contract)
        if ratings.get(compat_key(ship, t)) == "bad"
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
    candidate_route = plan_route(combined_contracts, route_debug=candidate_debug)
    if capacity:
        peak = peak_cargo_scu(combined_contracts, candidate_route)
        if peak > capacity:
            cap_ceiling = min(cap_ceiling, CAPACITY_OVERFLOW_CAP)
            reasons.append(f"{peak} SCU peak exceeds {capacity} SCU capacity by {peak - capacity}")

    manifest = freight_manifest(existing_contracts + [contract])
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

    # Read fresh every call (not cached anywhere) so a change saved in
    # the Hauler Profile's GRADING SCALE table takes effect on the
    # very next scan, no restart needed.
    thresholds = thresholds or DEFAULT_GRADING_THRESHOLDS
    reward_digits = (contract.get("reward") or "").replace(",", "")
    reward_val = int(reward_digits) if reward_digits.isdigit() else 0
    scu = pickup_scu
    if reward_val and scu:
        per_scu = reward_val / scu
        if per_scu >= thresholds.get("great", DEFAULT_GRADING_THRESHOLDS["great"]):
            points += 25
            reasons.append(f"{per_scu:.0f} aUEC/SCU (great)")
        elif per_scu >= thresholds.get("good", DEFAULT_GRADING_THRESHOLDS["good"]):
            points += 10
            reasons.append(f"{per_scu:.0f} aUEC/SCU (good)")
        elif per_scu >= thresholds.get("ok", DEFAULT_GRADING_THRESHOLDS["ok"]):
            reasons.append(f"{per_scu:.0f} aUEC/SCU (ok)")
        else:
            points -= 15
            reasons.append(f"{per_scu:.0f} aUEC/SCU (low)")
    else:
        reasons.append("reward or cargo unknown")

    baseline_debug: dict = {}
    plan_route(existing_contracts, route_debug=baseline_debug)
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
        t.get("star_system_name") for t in contract_terminals(contract)
        if t.get("star_system_name")
    }
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
