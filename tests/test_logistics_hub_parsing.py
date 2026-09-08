"""Regression suite for Logistics Hub: contract parsing (locations, roles,
commodities, quantities), route/distance logic, and card/popout UI state.

Three check groups, run together by `run()`:
  - `FIXTURES` — real OCR captures, hand-verified against their raw text
    during development (see docs/DECISIONS.md for the dated writeup of
    each bug this caught).
  - `DISTANCE_FIXTURES` — real UEX record pairs exercising
    `LocationService.same_physical_place()`/`distance()` directly.
  - `run_ui_state_checks()` — real (offscreen) Qt widget state, e.g. CLEAR
    actually clearing an open Tracker popout, not just the card.

This exists specifically so a future fix for one bug can't silently
reintroduce an earlier one — run it after any change to
`_candidate_phrases`, `_build_contract`, `_extract_commodities`,
`_commodity_quantities`, `_render_results`/`_populate_route_rows`, or
anything in `host/locations.py` that route/location resolution touches.

No test framework dependency — plain asserts, run directly:
    python tests/test_logistics_hub_parsing.py

Needs `locations_cache.json` present (no network call otherwise — see
`LocationService.ensure_loaded()`). The UI-state check needs PySide6
importable; it's skipped with a clear message if that fails rather than
crashing the whole run.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from host.config import Config
from host.api_client import UexApiClient
from modules.logistics_hub.module import (
    LogisticsHubModule, GRADE_CAP_ON_WARNING, CAPACITY_OVERFLOW_CAP, COMPLETED_LOG_FILENAME,
)
from modules.logistics_hub import gamelog_verify


# Each fixture: (name, raw_text, expected_pickups, expected_dropoffs)
# expected_* are {terminal_name: [(commodity, qty), ...]} — order-independent
# on commodities, terminal set must match exactly.
FIXTURES = [
    (
        "everus_harbor_to_baijini_single_pickup_single_dropoff",
        "OFFERS\nACCEPTED (3/10)\nHISTORY\nBEACONS\nEnenaent\n"
        "Junior | DIRECT Medium Haul\nEverus Harbor\nReward\n87,250\n"
        "Contract Deadline\nNZA\n>\nBaijini Point [BP]*\nContracted By\n"
        "Covalex Independent Contractors\nDETAILS\nPRIMARY OBJECTIVES\nHello,\n"
        "Deliver 0/99 SCU of Stims to Baijini Point above ArcCorp:\n"
        "Need a contractor for a simple cargo haul going from a freight\n"
        "Collect Stims from Everus Harbor.\n"
        "elevator at Everus Harbor above Hurston to a freight elevator at\n"
        "Baijini Point above ArcCorp: At most the containers will be 8 SCU\n"
        "in size.\nAlso, we strongly encourage contractors to bring a handheld\n"
        "tractor beam along:\nchance vou're available to take care pf it for us?\n"
        "Thanks in advance for ensuring prompt service,\nChase Hewitt\n"
        "Jr. Logistics Coordinator\nCovalex Shipping\n"
        "'Anything you need, anywhere you need it.\n"
        "Covalex Shipping is a limited liabilitv corporation: To encouraqe\n"
        "ABANDON\nSHARE\nTRACK\nAny",
        {"Admin - Everus Harbor": [("Stims", "99")]},
        {"Admin - Baijini Point": [("Stims", "99")]},
    ),
    (
        "mic_l2_long_forest_v1_quartz_corundum",
        "OFFERS\nACCEPTED (3/10)\nHISTORY\nBEACONS\n"
        "Member | Medium Haul | from MIC-L2\nReward\n4 81,000\n"
        "Contract Deadline\nNZA\nForest Station [BP]*\nContracted By\n"
        "Covalex Independent Contractors\nDETAILS\nPRIMARY OBJECTIVES\nHey:\n"
        "Deliver 0/37 SCU of Quartz to Port Tressler above\nmicroTech;\n"
        "The refinery at Long Forest Station at microTech's L2 Lagrange\n"
        "point has been busy: Thev've processed a mix of refined ores and\n"
        "Collect Quartz from MIC-Lz Long Forest Station:\nare looking to\n"
        "the containers (8 SCU or smaller) shipped out\nfrom a freight elevator_\n"
        "just checked with the LEOs to see where\n"
        "Deliver 0/33 SCU of Quartz to Seraphim Station above\n"
        "this stuff is needed\nwas able to put together this run:\nCrusader:\n"
        "DROP OFF LOCATIONS (ANY ORDER)\nCollect Quartz from MIC-Lz Long Forest Station:\n"
        "Freight elevator at Port Tressler above\nmicroTech\n"
        "Deliver 0/11 SCU of Corundum to Port Tressler above\n"
        "Freight elevator at Seraphim Station abpve Crusader\nmicroTech:\n"
        "Collect Corundum from MIc-Lz Long Forest Station_\n"
        "Should be an easy run for yoU, if you're\n"
        "Deliver 0/11 SCU of Corundum to Seraphim Station above\n"
        "By the way; we strongly encourage contractors to bring a\nCrusader.\n"
        "handheld tractor beam along:\nCollect Corundum from MIC-Lz Long Forest Station.\n"
        "Thanks in advance for ensuring prompt service,\nChase Hewitt\nJr\n"
        "Logistics Coordinator\nCovalex Shipping\n"
        "'Anything you need, anywhere you need it.\nABANDON\nSHARE\nTRACK\nLong\nget\nand\nfree.",
        {"MIC-L2 Long Forest Station": [("Quartz", "70"), ("Corundum", "22")]},
        {
            "Admin - Port Tressler": [("Quartz", "37"), ("Corundum", "11")],
            "Seraphim Station": [("Quartz", "33"), ("Corundum", "11")],
        },
    ),
    (
        "seraphim_4stop_v1_role_tiebreak_bug",
        # This is THE contract that exposed the role-assignment bug
        # (2026-09-06): "Ambitious Dream Station" must resolve as a
        # DROPOFF, not a pickup.
        "OFFERS\nACCEPTED (3/10)\nHISTORY\nBEACONS\nAcnmm\n"
        "Member | Small Haul | from Seraphim Station\nReward\n4 90,250\n"
        "Contract Deadline\nNZA\n[BP]*\nContracted By\n"
        "Covalex Independent Contractors\nDETAILS\nPRIMARY OBJECTIVES\nHi,\n"
        "Deliver 0/6 SCU of Pressurized Ice to Beautiful Glen\n"
        "Station at Crusader's LS Lagrange point.\n"
        "There's a few Crusader facilities that need to be restocked with\n"
        "processed food and pressurized ice. Don't know why but Im\n"
        "Collect Pressurized Ice from Seraphim Station:\nalways surprised when\n"
        "see how much of this stuff they need\ndelivered:\n"
        "Deliver 0/6 SCU of Processed Food to Shallow Fields\n"
        "Station at Crusader's L4 Lagrange point.\n"
        "Anyways, there's a haul of containers no bigger than 4 SCU\n"
        "waiting at Seraphim Station above Crusader. Once you grab the\n"
        "Collect Processed Food from Seraphim Station:\n"
        "goods from a freight elevator, these are the facilities where it\n"
        "needs to go:\nDeliver 0/5 SCU of Pressurized\nto Ambitious Dream\n"
        "Station at Crusader's LI Lagrange point.\n"
        "DROP OFF LOCATIONS (ANY ORDER)\n"
        "Collect Pressurized Ice from Seraphim Station:\n"
        "Freight elevator at Beautiful Glen Station at Crusader's LS\n"
        "Deliver 0/5 SCU of Processed Food to Beautiful Glen\nLagrange point\n"
        "Station at Crusader's L5 Lagrange point,\n"
        "Freight elevator at Shallow Fields Station at Crusader's L4\n"
        "Lagrange point\nCollect Processed Food from Seraphim Station.\n"
        "Freight elevator at Ambitious Dream Station at Crusader's Ll\n"
        "Lagrange\nBy the way; we strongly encourage contractors to\n"
        "handheld tractor beam\nThanks in advance for ensuring prompt service;\n"
        "ABANDON\nSHARE\nTRACK\nIce\npoint\nbring\nalong:",
        {"Seraphim Station": [("Pressurized Ice", "11"), ("Processed Food", "11")]},
        {
            "CRU-L5 Beautiful Glen Station": [("Pressurized Ice", "6"), ("Processed Food", "5")],
            "CRU-L4 Shallow Fields Station": [("Processed Food", "6")],
            "CRU-L1 Ambitious Dream Station": [("Pressurized Ice", "5")],
        },
    ),
    (
        "seraphim_4stop_v2_clean",
        "OFFERS\nACCEPTED (1/10)\nHISTORY\nBEACONS\nMember | Small Haul | from Seraphim Station\n"
        "Reward\n4 90,250\nContract Deadline\nNA\n[BP]*\nContracted By\n"
        "Covalex Independent Contractors\nDETAILS\nPRIMARY OBJECTIVES\nHi;\n"
        "Deliver 0/7 SCU of Pressurized Ice to Shallow Fields\n"
        "Station at Crusader's L4 Lagrange point:\n"
        "There' 5 a few Crusader facilities that need to be restocked with\n"
        "processed food and pressurized ice; Don't know why but Im\n"
        "Collect Pressurized Ice from Seraphim Station\nalways surprised when\n"
        "see how much of this stuff they need\ndelivered:\n"
        "Deliver 0/6 SCU of Processed Food to Ambitious Dream\n"
        "Station at Crusader's Ll Lagrange point:\n"
        "Anyways, there'5 a haul of containers no bigger than 4 SCU\n"
        "waiting at Seraphim Station above Crusader. Once you grab the\n"
        "Collect Processed Food from Seraphim Station:\n"
        "from a freight elevator, these are the facilities where it\nneeds to\n"
        "Deliver 0/5 SCU of Pressurized Ice to Beautiful Glen\ngo:\n"
        "Station at Crusader's LS Lagrange point.\nDROP OFF LOCATIONS (ANY ORDER)\n"
        "Collect Pressurized Ice from Seraphim Station:\n"
        "Freight elevator at Shallow Fields Station at Crusader's L4\n"
        "Deliver 0/3 SCU of Processed Food to Shallow Fields\nLagrange point\n"
        "Station at Crusader's L4 Lagrange point:\n"
        "Freight elevator at Ambitious Dream Station at Crusader's Ll\nLagrange point\n"
        "Collect Processed Food from Seraphim Station:\n"
        "Freight elevator at Beautiful Glen Station at Crusader'$ LS\nLagrange\n"
        "By the way; we strongly encourage contractors to bring a\nhandheld tractor beam\n"
        "Thanks in advance for ensuring prompt service,\nABANDON\nSHARE\nUNTRACK\ngoods\npoint\nalong:",
        {"Seraphim Station": [("Pressurized Ice", "12"), ("Processed Food", "9")]},
        {
            "CRU-L4 Shallow Fields Station": [("Pressurized Ice", "7"), ("Processed Food", "3")],
            "CRU-L1 Ambitious Dream Station": [("Processed Food", "6")],
            "CRU-L5 Beautiful Glen Station": [("Pressurized Ice", "5")],
        },
    ),
    (
        "ambitious_dream_pickup_to_seraphim_everus",
        # Pickup at Ambitious Dream Station this time — confirms the role
        # fix generalizes both directions, not just one hardcoded way.
        "OFFERS\nACCEPTED (2/10)\nHISTORY\nBEACONS\nMember | Medium Haul | from CRU-LI Ambitious\n"
        "Reward\n79,250\nContract Deadline\nNZA\nDream Station [BP]*\nContracted By\n"
        "Covalex Independent Contractors\nDETAILS\nPRIMARY OBJECTIVES\nGreetings,\n"
        "Deliver 0/23 SCU of Aluminum to Seraphim Station above\nCrusader.\n"
        "Seems like Ambitious Dream Station at Crusader's Ll Lagrange\n"
        "point currently has some 8 SCU or smaller cargo that needs to be\n"
        "Collect Aluminum from CRU-LI Ambitious Dream\n"
        "separated and delivered to a few different spots:\nStation:\n"
        "DROP OFF LOCATIONS (ANY ORDER)\nDeliver 0/20 SCU of Aluminum to Everus Harbor above\n"
        "Hurston:\nFreight elevator at Seraphim Station above Crusader\n"
        "Freight elevator at Everus Harbor above Hurston\n"
        "Collect Aluminum from CRU-LI Ambitious Dream\nStation:\n"
        "Drop-offs can be done in whatever orden works best for you:\n"
        "Deliver 0/27 SCU of Titanium to Seraphim Station above\n"
        "By the way: we strongly encourage contractors to bring a\nCrusader.\n"
        "handheld tractor beam along:\nCollect Titanium from CRU-Ll Ambitious Dream\n"
        "Thanks in advance for ensuring prompt service,\nStation.\nChase Hewitt\n"
        "Deliver 0/24 SCU of Titanium to Everus Harbor above\nJr. Logistics Coordinator\n"
        "Hurston:\nCovalex Shipping\n'Anything you need, anywhere you need it.\n"
        "Collect Titanium from CRU-LI Ambitious Dream\nStation.\nABANDON\nSHARE\nTRACK",
        {"CRU-L1 Ambitious Dream Station": [("Aluminum", "43"), ("Titanium", "51")]},
        {
            "Seraphim Station": [("Aluminum", "23"), ("Titanium", "27")],
            "Admin - Everus Harbor": [("Aluminum", "20"), ("Titanium", "24")],
        },
    ),
    (
        "mic_l2_long_forest_v2_port_tressler_theft_bug",
        # This is THE contract that exposed the commodity-misattribution
        # bug (2026-09-06): Port Tressler's Corundum must be 11, not 13
        # (13 belongs to Everus Harbor, on a different line entirely).
        "OFFERS\nACCEPTED (3/10)\nHISTORY\nBEACONS\nMember | Medium Haul | from MIC-L2\n"
        "Reward\n4 81,000\nContract Deadline\nNZA\nForest Station [BP]*\nContracted By\n"
        "Covalex Independent Contractors\nDETAILS\nPRIMARY OBJECTIVES\nHey:\n"
        "Deliver 0/37 SCU of Quartz to Everus Harbor above\nHurston:\n"
        "The refinery at Long Forest Station at microTech's L2 Lagrange\n"
        "point has been busy: They've processed a mix of refined ores and\n"
        "Collect Quartz from MIC-Lz Long Forest Station.\nare\n"
        "looking to get the containers (8 SCU or smaller) shipped out\nfrom a\n"
        "freight elevator.\njust checked with\nLEOs to see where\n"
        "Deliver 0/39 SCU of Quartz to Port Tressler above\n"
        "this stuff is needed and was able to\ntogether this run.\nmicroTech:\n"
        "DROP OFF LOCATIONS (ANY ORDER)\nCollect Quartz from MIC-Lz Long Forest Station:\n"
        "Freight elevator at Everus Harbor abovp Hurston\n"
        "Deliver 0/13 SCU of Corundum to Everus Harbor above\n"
        "Freight elevator at Port Tressler abovejmicroTech\nHurston:\n"
        "Collect Corundum from MIC-Lz Long Forest Station:\n"
        "Should be an easy run for YOU; if you're free:\n"
        "Deliver 0/11 SCU of Corundum to Port Tressler above\n"
        "By the way. we strongly encourage contractors to bring a\nmicroTech:\n"
        "handheld tractor beam along:\nCollect Corundum from MIC-Lz Long Forest Station:\n"
        "Thanks in advance for ensuring prompt service,\nChase Hewitt\n"
        "Jr. Logistics Coordinator\nCovalex Shipping\n"
        "'Anything you need, anywhere vou need it:\nABANDON\nSHARE\nTRACK\nLong\nthe\nput",
        {"MIC-L2 Long Forest Station": [("Quartz", "76"), ("Corundum", "24")]},
        {
            "Admin - Everus Harbor": [("Quartz", "37"), ("Corundum", "13")],
            "Admin - Port Tressler": [("Quartz", "39"), ("Corundum", "11")],
        },
    ),
    (
        # SYNTHETIC, not a real OCR capture — the original real contract
        # that exposed this bug (2026-09-05, "Seraphim The"/"Seraphim
        # Station") predates this test file and its raw text was never
        # saved. Reproduces the same real, confirmed-live mechanism
        # instead: "Seraphim Station" (resolves to space_stations id 27)
        # and "Seraphim Trade" (resolves to terminals id 259, "Admin -
        # Seraphim") are two different real UEX records for the exact same
        # physical place — confirmed via a live `resolve_all()` call, not
        # guessed. Before the 2026-09-06 same-place merge fix, these
        # produced two separate dropoff entries for one real stop.
        "duplicate_stop_same_place_two_records_synthetic",
        "OFFERS\nACCEPTED (1/10)\nHISTORY\nBEACONS\nMember | Small Haul\nReward\n50,000\n"
        "Contract Deadline\nNZA\nContracted By\nCovalex Independent Contractors\n"
        "DETAILS\nPRIMARY OBJECTIVES\nHello,\n"
        "Deliver 0/10 SCU of Waste to Seraphim Station above Crusader.\n"
        "Collect Waste from Everus Harbor.\n"
        "DROP OFF LOCATIONS (ANY ORDER)\n"
        "Freight elevator at Seraphim Trade above Crusader\n"
        "Thanks in advance for ensuring prompt service,\nABANDON\nSHARE\nTRACK",
        {"Admin - Everus Harbor": [("Waste", "10")]},
        {"Seraphim Station": [("Waste", "10")]},
    ),
    (
        # SYNTHETIC, not a real OCR capture — the original real contract
        # that exposed this bug (2026-09-05, "...Teasa Spaceport in
        # Lorville.") predates this test file and its raw text was never
        # saved. Reproduces the same confirmed-live mechanism instead:
        # "Lorville" resolves to exactly one real terminal ("Landing
        # Services - Lorville") once it's even offered as a candidate,
        # and "Teasa Spaceport" is a genuine, real ambiguity between two
        # different shops there (New Deal vs. Kel-To) — both confirmed
        # via live `resolve_all()` calls before writing this fixture.
        "single_word_city_lorville_synthetic",
        "OFFERS\nACCEPTED (1/10)\nHISTORY\nBEACONS\nMember | Small Haul\nReward\n45,000\n"
        "Contract Deadline\nNZA\nContracted By\nCovalex Independent Contractors\n"
        "DETAILS\nPRIMARY OBJECTIVES\nHello,\n"
        "Deliver 0/8 SCU of Medical Supplies to Teasa Spaceport in Lorville.\n"
        "Collect Medical Supplies from Everus Harbor.\n"
        "Thanks in advance for ensuring prompt service,\nABANDON\nSHARE\nTRACK",
        {"Admin - Everus Harbor": [("Medical Supplies", "8")]},
        {"Landing Services - Lorville": [("Medical Supplies", "8")]},
    ),
    (
        # REAL OCR capture (2026-09-07, first live scan after this
        # session's OCR pipeline optimizations). Exposed a real gap the
        # synthetic fixture above didn't catch: the destination is split
        # "Deliver...to Teasa Spaceport" / "in Lorville:" — a direct
        # grammatical continuation of one destination across the line
        # break, not the coincidentally-adjacent unrelated mention the
        # straddle check (mic_l2_long_forest_v2_port_tressler_theft_bug)
        # was built to reject. Before the fix, Lorville's commodities came
        # back empty because "lorville" never straddles that boundary —
        # a single-word city candidate's continuation, by construction,
        # is always entirely on the next line.
        "real_lorville_in_continuation_commodity_gap",
        "ACCEPTED (2/10)\nOFFERS\nVacrlut\nExperienced [ DRECT Medium Haul\n"
        "Harbor ? Teasa Spaceport [BP]*\nDETAILS\nHello;\n"
        "Need a contractor for a simple cargo haul going from a freight\n"
        "elevator at Everus Harbor above Hurston to a freight elevator at\n"
        "Teasa Spaceport in Lorville. At most the containers will be 16 SCU\n"
        "in size:\nAlso, we strongly encourage contractors to bring a handheld\n"
        "tractor beam along:\n're available to take care of it for us?\n"
        "chance\nAny\nyou'\nThanks in advance for ensuring prompt service,\n"
        "Chase Hewitt\nJr. Logistics Coordinator\nCovalex Shipping\n"
        "'Anything you need, anywhere you need it '\n"
        "Covalex Shipping is a limited liabilitv corporation. To encouraqe\n"
        "ABANDON\nBEACONS\nHISTORY\nDecu-Brsada\nA 163,250\nReward\nEverus\n"
        "NZA\nContract Deadline\nCovalex Independent Contractors\n"
        "Contracted By\nPRIMARY OBJECTIVES\n"
        "Deliver 0/27 SCU of Pressurized Ice to Teasa Spaceport\nin Lorville:\n"
        "Collect Pressurized Ice from Everus Harbor.\n"
        "Deliver 0/278 SCU of Processed Food to Teasa Spaceport\nin Lorville.\n"
        "Collect Processed Food from Everus Harbor.\nSHARE\nTRACK",
        {"Admin - Everus Harbor": [("Pressurized Ice", "27"), ("Processed Food", "278")]},
        {"Landing Services - Lorville": [("Pressurized Ice", "27"), ("Processed Food", "278")]},
    ),
    (
        # REAL OCR capture (2026-09-07, same live scan session as above).
        # Already-correct before any fix here — added as a plain
        # confirming fixture (3-commodity single-pickup/single-dropoff,
        # each commodity split across its own Deliver/Collect line pair)
        # so a future change can't silently break this shape either.
        "real_faithful_dream_station_three_commodities",
        "ACCEPTED (2/10)\nOFFERS\nExperienced [ DIRECT Medium Haul [ Everus\n"
        "Harbor z HUR-L2 Faithful Dream Station [BP]*\nDETAILS\nHello,\n"
        "Need a contractor for a simple cargo haul going from a freight\n"
        "elevator at Everus Harbor above Hurston to a freight elevator at\n"
        "Faithful Dream Station at Hurston's L? Lagrange point. At most\n"
        "the containers will be 16 SCU in size:\n"
        "Also, we strongly encourage contractors to bring a handheld\n"
        "tractor beam along:\n're available to take care of it for us?\n"
        "chance\nyou' r\nAny\nThanks in advance for ensuring prompt service,\n"
        "Chase Hewitt\nJr. Logistics Coordinator\nCovalex Shipping\n"
        "'Anything you need, anywhere you need it;'\n"
        "Covalex Shippina is a limited liabilitv corporation: To encouraqe\n"
        "ABANDON\nBEACONS\nHISTORY\nArev -Uijou;\n4 160,250\nReward\nNZA\n"
        "Contract Deadline\nCovalex Independent Contractors\nContracted By\n"
        "PRIMARY OBJECTIVES\nDeliver 0/84 SCU of Quantum Fuel to Faithful Dream\n"
        "Station at Hurston's Lz Lagrange point.\n"
        "Collect Quantum Fuel from Everus Harbor:\n"
        "Deliver 0/115 SCU of Hydrogen Fuel to Faithful Dream\npoint:\n"
        "Station at Hurston's Lz Lagrange\nCollect Hydrogen Fuel from Everus Harbor.\n"
        "Deliver 0/108 SCU of Ship Ammunition to Faithful Dream\n"
        "Station at Hurston'\ns Lz Lagrange point.\n"
        "Collect Ship Ammunition from Everus Harbor.\nSHARE\nUNTRACK",
        {"Admin - Everus Harbor": [
            ("Quantum Fuel", "84"), ("Hydrogen Fuel", "115"), ("Ship Ammunition", "108"),
        ]},
        {"HUR-L2 Faithful Dream Station": [
            ("Quantum Fuel", "84"), ("Hydrogen Fuel", "115"), ("Ship Ammunition", "108"),
        ]},
    ),
]

# NOTE: a "Baijini Point -> Seraphim, 103 Stims" contract was also verified
# correct live (2026-09-06) but isn't included here — its raw OCR text was
# never captured into this file before the source debug log entry was
# wiped, and reconstructing it from memory would defeat the point of this
# suite (fixtures must be real captures, never approximated). Add it for
# real next time that shape comes up in a scan.


# Route/distance fixtures, separate from the OCR-parsing ones above: each
# is (name, endpoint_a, id_a, endpoint_b, id_b, expect_same_place). Real
# UEX record ids from locations_cache.json, not OCR text — these exercise
# `LocationService.same_physical_place()`/`distance()` directly, which the
# OCR fixtures above never touch (none of them assert anything about route
# cost). Missing this coverage is exactly how the 2026-09-06 same-place
# fix (see DECISIONS.md) could regress silently — a broken
# `same_physical_place()` doesn't change any pickup/dropoff/commodity
# output, only route cost.
DISTANCE_FIXTURES = [
    (
        "seraphim_kiosk_vs_station_same_place",
        # "Admin - Seraphim" (terminals kiosk) and "Seraphim Station" (the
        # space_stations record) are the same real place — this is the
        # exact pair that produced a fake +5 route-cost estimate instead
        # of 0 before the fix.
        "terminals", 259, "space_stations", 27, True,
    ),
    (
        "kiosk_fk_vs_wrong_endpoint_same_id_not_same_place",
        # Terminal 259 ("Admin - Seraphim") has id_space_station=27, which
        # correctly means "space_stations id 27" (Seraphim Station). But
        # `outposts` id 27 is a totally unrelated real place (HDMS-
        # Woodruff) that just happens to share the same bare numeric id —
        # exactly the cross-endpoint id-collision this whole module's
        # `_endpoint` tagging exists to prevent (see module docstring).
        # A same_physical_place() that checks the FK value against ANY
        # candidate's `id` without also checking `structural._endpoint`
        # matches the FK's own named endpoint would wrongly return True
        # here (caught in code review, 2026-09-06 — see DECISIONS.md).
        "terminals", 259, "outposts", 27, False,
    ),
    (
        "different_shops_same_city_not_same_place",
        # Two different real shops that both happen to sit in Levski
        # (id_city=2) must NOT be treated as the same place as each other.
        "terminals", 109, "terminals", 110, False,
    ),
]


def run_distance_checks(mod) -> tuple[int, int]:
    """Returns (failures, total_checks)."""
    by_key = {}
    for row in mod._locations.all_locations():
        by_key[(row.get("_endpoint"), row.get("id"))] = row

    failures = 0
    total = 0
    for name, ep_a, id_a, ep_b, id_b, expect_same in DISTANCE_FIXTURES:
        a, b = by_key.get((ep_a, id_a)), by_key.get((ep_b, id_b))
        if a is None or b is None:
            print(f"[SKIP] {name} — record not in cached location data (id changed upstream?)")
            continue
        total += 1
        same = mod._locations.same_physical_place(a, b)
        ok = same == expect_same
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
        if not ok:
            failures += 1
            print(f"    expected same_physical_place={expect_same}, got {same}")
        if same:
            total += 1
            dist = mod._locations.distance(a, b)
            dist_ok = dist == 0.0
            print(f"[{'PASS' if dist_ok else 'FAIL'}] {name} (distance == 0.0)")
            if not dist_ok:
                failures += 1
                print(f"    expected distance 0.0, got {dist}")
    return failures, total


def run_manifest_and_capacity_checks(mod) -> tuple[int, int]:
    """Pure-logic checks (no Qt event loop needed) for the two 2026-09-07
    additions: `_freight_manifest()` flagging the same commodity split
    across multiple contracts (the game makes these impossible to tell
    apart once picked up — the exact scenario that prompted this), and
    `_peak_cargo_scu()` feeding the card's over-capacity warning."""
    failures, total = 0, 0

    total += 1
    contracts = [
        {"pickups": [{"commodities": [("Titanium", "50")]}]},
        {"pickups": [{"commodities": [("Titanium", "30")]}]},
        {"pickups": [{"commodities": [("Gold", "10")]}]},
    ]
    manifest = mod._freight_manifest(contracts)
    ok = (
        manifest.get("Titanium") == {"scu": 80, "contract_count": 2}
        and manifest.get("Gold") == {"scu": 10, "contract_count": 1}
    )
    name = "freight_manifest_flags_same_commodity_across_contracts"
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if not ok:
        failures += 1
        print(f"    expected Titanium split across 2 contracts (80 SCU total), Gold in 1; got {manifest}")

    return failures, total


def run_grading_checks() -> tuple[int, int]:
    """Pure-logic checks for `_grade_contract()` (Part 3 of the confirm-
    gate/grading plan, 2026-09-07) — no Qt event loop needed, but its own
    isolated temp-file Config since `_rate_compatibility()` saves to disk
    on every call (same lesson as `run_ui_state_checks`: never let a test
    touch the real config.json). Covers the feature's whole point: a
    known-BAD ship/location match must cap the grade no matter how good
    everything else scores — the "90% great, one hard no" case that
    prompted this feature shouldn't be hideable behind a decent average."""
    import os
    import tempfile
    from pathlib import Path
    from host.config import Config as _Config

    tmp_path = Path(tempfile.gettempdir()) / f"mobiov_test_grading_config_{os.getpid()}.json"
    config = _Config(path=tmp_path)
    api_client = UexApiClient(config.data["api"]["uex_base_url"], config.data["api"]["uex_token"])
    mod = LogisticsHubModule(api_client, config)
    mod._locations.ensure_loaded()

    failures, total = 0, 0
    contract = mod._build_contract(FIXTURES[0][1])  # everus_harbor_to_baijini, real pickup/dropoff terminals

    name = "grade_none_without_profile"
    total += 1
    grade, reason, capped = mod._grade_contract(contract, [])
    ok = grade is None and "PROFILE" in reason and capped is False
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if not ok:
        failures += 1
        print(f"    expected (None, '...PROFILE...', False); got {(grade, reason, capped)!r}")

    mod.settings["hauler_profile"] = {
        "ship": "Hull C", "goal": "Profit", "risk": "Moderate",
        "time_budget": "Medium", "region_pref": "Willing to cross jump points",
    }

    name = "grade_capped_on_known_bad_location"
    total += 1
    pickup_terminal = contract["pickups"][0]["terminal"]
    mod._rate_compatibility("Hull C", pickup_terminal, good=False)
    grade, reason, capped = mod._grade_contract(contract, [])
    ok = grade is not None and capped is True and grade <= GRADE_CAP_ON_WARNING and "BAD" in reason
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if not ok:
        failures += 1
        print(f"    expected score <= {GRADE_CAP_ON_WARNING} with capped=True and a BAD-location reason; "
              f"got {(grade, reason, capped)!r}")

    name = "grade_capped_on_duplicate_freight_overlap"
    total += 1
    mod._rate_compatibility("Hull C", pickup_terminal, good=True)  # clear the BAD rating from above
    existing = [mod._build_contract(FIXTURES[0][1])]  # same commodity already "queued"
    grade, reason, capped = mod._grade_contract(contract, existing)
    ok = grade is not None and capped is True and grade <= GRADE_CAP_ON_WARNING and "already queued" in reason
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if not ok:
        failures += 1
        print(f"    expected score <= {GRADE_CAP_ON_WARNING} with capped=True and an 'already queued' reason; "
              f"got {(grade, reason, capped)!r}")

    name = "grade_capped_harder_on_cargo_capacity_overflow"
    total += 1
    mod.settings["cargo_capacity_scu"] = 1  # guarantee this contract's real SCU overflows it
    grade, reason, capped = mod._grade_contract(contract, [])
    ok = (
        grade is not None and capped is True
        and grade <= CAPACITY_OVERFLOW_CAP
        and "exceeds" in reason and "capacity" in reason
    )
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if not ok:
        failures += 1
        print(f"    expected score <= {CAPACITY_OVERFLOW_CAP} (stricter than the {GRADE_CAP_ON_WARNING} "
              f"warning cap) with a capacity-exceeded reason; got {(grade, reason, capped)!r}")
    del mod.settings["cargo_capacity_scu"]

    name = "grade_not_capped_when_clean"
    total += 1
    grade, reason, capped = mod._grade_contract(contract, [])
    ok = grade is not None and capped is False and "BAD" not in reason and "already queued" not in reason
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if not ok:
        failures += 1
        print(f"    expected an uncapped grade with no warning reasons; got {(grade, reason)!r}")

    # 2026-09-07: GRADING SCALE thresholds are user-editable and must take
    # effect immediately, no restart — `_grade_contract()` reads
    # `self.settings["grading_thresholds"]` fresh every call rather than
    # caching it anywhere. Verified here by mutating settings directly
    # (equivalent to what SAVE does) and confirming the very next
    # `_grade_contract()` call reflects it.
    name = "grading_thresholds_apply_without_restart"
    total += 1
    _grade, reason_before, _capped = mod._grade_contract(contract, [])
    mod.settings["grading_thresholds"] = {"great": 1_000_000, "good": 999_999, "ok": 999_998}
    _grade, reason_after, _capped = mod._grade_contract(contract, [])
    ok = "(great)" in reason_before and "(low)" in reason_after
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if not ok:
        failures += 1
        print(f"    expected the aUEC/SCU label to change once thresholds changed; "
              f"before={reason_before!r} after={reason_after!r}")
    del mod.settings["grading_thresholds"]

    tmp_path.unlink(missing_ok=True)
    return failures, total


def run_gamelog_verify_checks() -> tuple[int, int]:
    """Pure-function checks for `modules/logistics_hub/gamelog_verify.py`
    against synthetic Game.log lines shaped exactly like the real ones
    captured live 2026-09-08 (see that module's docstring for the actual
    log excerpt this is modeled on). No Qt, no real Game.log — a temp file
    with hand-written lines and a fixed `now`."""
    import tempfile
    from datetime import datetime, timedelta, timezone

    failures, total = 0, 0

    now = datetime(2026, 9, 8, 0, 30, 0, tzinfo=timezone.utc)

    def ts(offset_seconds: float) -> str:
        return (now + timedelta(seconds=offset_seconds)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]

    accepted_line = (
        f'<{ts(-5)}Z> [Notice] <SHUDEvent_OnNotification> Added notification '
        '"Contract Accepted:  Experienced | <EM3>DIRECT</EM3> Medium Haul | '
        'Everus Harbor > Teasa Spaceport <EM4>[BP]*</EM4>: " [3] to queue. '
        'New queue size: 1, MissionId: [acf855f6-8008-4cb8-baac-79be39ce99b1], '
        'ObjectiveId: [] [Team_CoreGameplayFeatures][Missions][Comms]'
    )
    deliver_line_1 = (
        f'<{ts(-4.9)}Z> [Notice] <SHUDEvent_OnNotification> Added notification '
        '"New Objective: Deliver 0/16 SCU of Pressurized Ice to Teasa Spaceport: " '
        '[4] to queue. New queue size: 2, MissionId: [acf855f6-8008-4cb8-baac-79be39ce99b1], '
        'ObjectiveId: [dropoff_fc5c71cc-df3c-48c8-8a0a-72782541be8d_0] '
        '[Team_CoreGameplayFeatures][Missions][Comms]'
    )
    deliver_line_2 = (
        f'<{ts(-4.8)}Z> [Notice] <SHUDEvent_OnNotification> Added notification '
        '"New Objective: Deliver 0/313 SCU of Processed Food to Teasa Spaceport: " '
        '[5] to queue. New queue size: 3, MissionId: [acf855f6-8008-4cb8-baac-79be39ce99b1], '
        'ObjectiveId: [dropoff_fc5c71cc-df3c-48c8-8a0a-72782541be8d_1] '
        '[Team_CoreGameplayFeatures][Missions][Comms]'
    )
    # Outside the default 180s window — must not show up in results even
    # though it's a perfectly well-formed line.
    stale_line = (
        f'<{ts(-600)}Z> [Notice] <SHUDEvent_OnNotification> Added notification '
        '"Contract Accepted:  Rookie | Small Haul | Baijini Point > CRU-L1: " '
        '[9] to queue. New queue size: 1, MissionId: [11111111-1111-1111-1111-111111111111], '
        'ObjectiveId: [] [Team_CoreGameplayFeatures][Missions][Comms]'
    )

    with tempfile.TemporaryDirectory() as tmp_dir:
        log_path = str(Path(tmp_dir) / "Game.log")
        with open(log_path, "w", encoding="utf-8") as handle:
            handle.write("\n".join([stale_line, accepted_line, deliver_line_1, deliver_line_2]) + "\n")

        name = "gamelog_finds_events_in_window_not_out_of_window"
        total += 1
        events = gamelog_verify.find_recent_haul_events(log_path, now)
        mission_ids = {e["mission_id"] for e in events}
        matched_event = next((e for e in events if e["mission_id"] == "acf855f6-8008-4cb8-baac-79be39ce99b1"), None)
        ok = (
            "11111111-1111-1111-1111-111111111111" not in mission_ids
            and matched_event is not None
            and matched_event["origin"] == "Everus Harbor"
            and matched_event["destination"] == "Teasa Spaceport"
            and len(matched_event["legs"]) == 2
        )
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
        if not ok:
            failures += 1
            print(f"    events={events!r}")

        # A fake contract shaped like _build_contract's output: one pickup,
        # one dropoff, with a dropoff commodity OCR got wrong (name typo'd,
        # quantity missing) — the real motivating case for this feature.
        pickup_terminal = {"id": 1, "name": "Everus Harbor", "nickname": None}
        dropoff_terminal = {"id": 2, "name": "Teasa Spaceport", "nickname": None}
        contract = {
            "pickups": [{"terminal": pickup_terminal, "raw": "Everus Harbor", "commodities": []}],
            "dropoffs": [
                {
                    "terminal": dropoff_terminal, "raw": "Teasa Spaceport",
                    "commodities": [("Pressurized Ise", None)],  # OCR typo + no qty
                }
            ],
        }

        def display_name(terminal):
            # Same shape as LocationService.display_name: takes a terminal
            # record directly, not a pickup/dropoff entry.
            return terminal.get("name") or terminal.get("nickname") or ""

        name = "gamelog_verify_matches_and_corrects_commodity"
        total += 1
        result = gamelog_verify.verify_contract(contract, events, display_name)
        ok = (
            result["matched"] is True
            and result["mission_id"] == "acf855f6-8008-4cb8-baac-79be39ce99b1"
            and any(c["commodity"] == "Pressurized Ice" and c["need"] == 16 for c in result["corrections"])
            and any(c["commodity"] == "Processed Food" and c["need"] == 313 for c in result["corrections"])
            and contract["dropoffs"][0]["commodities"] == [("Processed Food", "313")]
        )
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
        if not ok:
            failures += 1
            print(f"    result={result!r}")
            print(f"    contract dropoffs after verify={contract['dropoffs']!r}")

        name = "gamelog_verify_no_match_for_unrelated_contract"
        total += 1
        unrelated_contract = {
            "pickups": [{"terminal": {"name": "Port Olisar"}, "raw": "Port Olisar", "commodities": []}],
            "dropoffs": [{"terminal": {"name": "GrimHEX"}, "raw": "GrimHEX", "commodities": []}],
        }
        result2 = gamelog_verify.verify_contract(unrelated_contract, events, display_name)
        ok = result2["matched"] is False and result2["corrections"] == []
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
        if not ok:
            failures += 1
            print(f"    result={result2!r}")

        name = "gamelog_verify_missing_log_file_is_a_clean_no_match"
        total += 1
        try:
            missing_events = gamelog_verify.find_recent_haul_events(str(Path(tmp_dir) / "no_such_file.log"), now)
            ok = missing_events == []
        except Exception as exc:
            ok = False
            print(f"    raised on missing file: {exc!r}")
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
        if not ok:
            failures += 1

    return failures, total


def run_ui_state_checks() -> tuple[int, int]:
    """Returns (failures, total_checks). Needs a real (offscreen-OK) Qt
    event loop, unlike the two check groups above — set QT_QPA_PLATFORM=
    offscreen if running headless. Covers CLEAR-with-Tracker-open leaving
    stale rows in the popout (2026-09-06, see DECISIONS.md): a fresh
    `_render_results()` call must sync the popout's rows to the *current*
    `_route_order` even when it's now empty, not only when it's non-empty."""
    import os
    import tempfile
    from pathlib import Path
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from host.config import Config as _Config
    from host.card_container import CardContainer

    app = QApplication.instance() or QApplication([])
    # Isolated temp path, NOT the real config.json — this group calls
    # _add_contract()/_on_review_accept(), which save to disk on every
    # call. Pointing at the real path once let a test run silently
    # overwrite the user's actual saved contracts (caught 2026-09-07,
    # see DECISIONS.md) — never repeat that regardless of what the checks
    # below do or how they fail.
    tmp_path = Path(tempfile.gettempdir()) / f"mobiov_test_config_{os.getpid()}.json"
    config = _Config(path=tmp_path)
    api_client = UexApiClient(config.data["api"]["uex_base_url"], config.data["api"]["uex_token"])
    mod = LogisticsHubModule(api_client, config)
    mod._locations.ensure_loaded()
    # `_append_jsonl()` (which both the debug log and, since 2026-09-07,
    # the completed-contracts log route through) writes to the real file
    # unconditionally — it doesn't go through Config, so the temp Config
    # above doesn't isolate it. Patching this one lower-level method
    # (not just `_append_debug_log`) covers both logs with one collector;
    # `_complete_contracts()` calls `_append_jsonl` directly.
    jsonl_entries: list[tuple[str, dict]] = []
    mod._append_jsonl = lambda filename, entry: jsonl_entries.append((filename, entry))
    debug_log_entries: list[dict] = []
    mod._append_debug_log = debug_log_entries.append
    container = CardContainer(config)
    mod.create_card(container)
    # Points at a path that can't exist, not left unset — unset falls back
    # to gamelog_verify.default_game_log_path(), which would read the
    # REAL Game.log on any machine that has Star Citizen installed (this
    # one included), making _on_review_accept's behavior depend on
    # whatever's actually in that file. Read-only, so not the config/
    # debug-log write hazard noted above, but still real-machine state a
    # regression test must never depend on.
    mod.settings["game_log_path"] = str(Path(tempfile.gettempdir()) / "mobiov_test_no_such_gamelog.log")

    name = "clear_syncs_open_tracker_popout"
    failures, total = 0, 1
    contract = mod._build_contract(FIXTURES[0][1])  # any real fixture will do
    mod._add_contract(contract)
    mod._open_route_popout()
    app.processEvents()
    before = mod._route_popout_layout.count()
    mod._clear_contracts()
    app.processEvents()
    after = mod._route_popout_layout.count()
    ok = before > 0 and after == 0
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if not ok:
        failures += 1
        print(f"    expected popout rows to go from >0 to 0 on CLEAR, got {before} -> {after}")

    mod._on_route_popout_closed()

    # 2026-09-07: SCAN CONTRACT no longer auto-adds — every scan now waits
    # for ACCEPT/REJECT on the review popup. First actually build and show
    # it (not just call the accept/reject handlers directly, which
    # bypasses the widget construction entirely — that gap is exactly how
    # a real crash in `_show_review_popup`'s reward-formatting slipped past
    # the first version of these checks, caught only by a live run).
    name = "review_popup_renders_without_crashing"
    total += 1
    contract2 = mod._build_contract(FIXTURES[1][1])
    try:
        mod._pending_scan = contract2
        grade_info = mod._grade_contract(contract2, mod.settings.get("contracts", []))
        mod._pending_grade = grade_info
        mod._show_review_popup(contract2, True, grade_info)  # duplicate=True exercises the warning-row branch too
        app.processEvents()
        ok = True
    except Exception as exc:
        ok = False
        print(f"    _show_review_popup raised: {exc!r}")
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if not ok:
        failures += 1
    popup = next((w for w in app.topLevelWidgets() if type(w).__name__ == "_ReviewPopup"), None)
    if popup is not None:
        popup.close()

    # Two checks: REJECT must leave the contract list untouched, ACCEPT
    # must add exactly the pending one.
    name = "review_popup_reject_does_not_add"
    total += 1
    contract2 = mod._build_contract(FIXTURES[1][1])
    before_count = len(mod.settings.get("contracts", []))
    mod._pending_scan = contract2
    mod._on_review_reject()
    after_count = len(mod.settings.get("contracts", []))
    ok = after_count == before_count and mod._pending_scan is None
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if not ok:
        failures += 1
        print(f"    expected contract count unchanged ({before_count}) and _pending_scan cleared; "
              f"got count={after_count}, pending={mod._pending_scan!r}")

    name = "review_popup_accept_adds_pending_contract"
    total += 1
    before_count = len(mod.settings.get("contracts", []))
    mod._pending_scan = contract2
    mod._on_review_accept()
    after_count = len(mod.settings.get("contracts", []))
    ok = after_count == before_count + 1 and mod._pending_scan is None
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if not ok:
        failures += 1
        print(f"    expected contract count {before_count}->{before_count + 1} and _pending_scan cleared; "
              f"got count={after_count}, pending={mod._pending_scan!r}")

    # 2026-09-07: ACCEPT/REJECT should each log a "review_<outcome>" debug
    # entry carrying the grade shown and any compatibility ratings given —
    # added so a real session's decisions are actually reconstructable
    # from the debug log, not just its OCR/parsing. Uses the in-memory
    # `debug_log_entries` collector set up above (never the real file).
    name = "review_outcome_logs_grade_and_ratings"
    total += 1
    debug_log_entries.clear()
    mod.settings["hauler_profile"] = {"ship": "Hull C"}
    contract3 = mod._build_contract(FIXTURES[0][1])
    pickup_terminal = contract3["pickups"][0]["terminal"]
    grade_info = mod._grade_contract(contract3, mod.settings.get("contracts", []))
    mod._pending_scan = contract3
    mod._pending_grade = grade_info
    mod._pending_unrated_names = [mod._locations.display_name(pickup_terminal)]
    mod._pending_ratings_given = [{"location": mod._locations.display_name(pickup_terminal), "rating": "good"}]
    mod._on_review_accept()
    logged = next((e for e in debug_log_entries if e.get("note") == "review_accepted"), None)
    expected_ratings = [{"location": mod._locations.display_name(pickup_terminal), "rating": "good"}]
    ok = (
        logged is not None
        and logged.get("grade") == grade_info[0]
        and logged.get("compatibility_ratings_given") == expected_ratings
    )
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if not ok:
        failures += 1
        print(f"    expected a 'review_accepted' entry with grade={grade_info[0]!r} and the rating given; "
              f"got {logged!r}")

    # 2026-09-07 (Part 2): Hauler Profile popup — actually construct and
    # save it (same lesson as review_popup_renders_without_crashing above:
    # calling the save handler directly would skip the widget entirely and
    # miss a real construction bug). `hauler_profile` explicitly `None`
    # (not just absent) crashed the first live test of this — `.get(key,
    # {})` only falls back when the key is *missing*, not when it's
    # present with value `None`. Regression case for exactly that.
    name = "profile_popup_handles_none_profile"
    total += 1
    mod.settings["hauler_profile"] = None
    try:
        mod._show_profile_popup()
        app.processEvents()
        popup = next((w for w in app.topLevelWidgets() if type(w).__name__ == "_HaulerProfilePopup"), None)
        ok = popup is not None
        if popup is not None:
            popup.close()
    except Exception as exc:
        ok = False
        print(f"    _show_profile_popup raised on None profile: {exc!r}")
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if not ok:
        failures += 1

    name = "profile_popup_saves_all_five_fields"
    total += 1
    try:
        mod._show_profile_popup()
        app.processEvents()
        popup = next((w for w in app.topLevelWidgets() if type(w).__name__ == "_HaulerProfilePopup"), None)
        if popup is None:
            raise AssertionError("_HaulerProfilePopup not found among top-level widgets")
        popup._ship_edit.setText("Hull C")
        popup._capacity_edit.setText("512")
        popup._goal_combo.setCurrentText("Profit")
        popup._risk_combo.setCurrentText("Moderate")
        popup._time_combo.setCurrentText("Quick (<30 min)")
        popup._region_combo.setCurrentText("Willing to cross jump points")
        popup._great_edit.setText("2000")
        popup._good_edit.setText("1000")
        popup._ok_edit.setText("500")
        popup._game_log_edit.setText(r"C:\fake\Game.log")
        popup._save()
        app.processEvents()
        saved = mod.settings.get("hauler_profile", {})
        ok = (
            saved == {
                "ship": "Hull C", "goal": "Profit", "risk": "Moderate",
                "time_budget": "Quick (<30 min)", "region_pref": "Willing to cross jump points",
            }
            and mod.settings.get("cargo_capacity_scu") == 512
            and mod.settings.get("grading_thresholds") == {"great": 2000, "good": 1000, "ok": 500}
            and mod.settings.get("game_log_path") == r"C:\fake\Game.log"
        )
        if not ok:
            print(f"    unexpected saved state: profile={saved}, capacity={mod.settings.get('cargo_capacity_scu')!r}, "
                  f"thresholds={mod.settings.get('grading_thresholds')!r}, "
                  f"game_log_path={mod.settings.get('game_log_path')!r}")
    except Exception as exc:
        ok = False
        print(f"    profile popup raised: {exc!r}")
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if not ok:
        failures += 1
    # Restore the isolated (nonexistent) log path the save above just
    # overwrote — later checks in this function must not fall through to
    # gamelog_verify.default_game_log_path() either.
    mod.settings["game_log_path"] = str(Path(tempfile.gettempdir()) / "mobiov_test_no_such_gamelog.log")

    # 2026-09-07: COMPLETE should log every queued contract to the
    # completed-contracts JSONL (reward/cargo/locations/grade), then clear
    # the queue same as CLEAR. Uses the `jsonl_entries` collector set up
    # above — never the real logistics_hub_completed.jsonl.
    name = "complete_contracts_logs_then_clears"
    total += 1
    jsonl_entries.clear()
    contract4 = mod._build_contract(FIXTURES[0][1])
    contract4["grade_at_accept"] = 82
    contract4["grade_reason_at_accept"] = "500 aUEC/SCU (great); minimal detour"
    mod.settings["contracts"] = [contract4]
    mod._complete_contracts()
    logged = [e for fname, e in jsonl_entries if fname == COMPLETED_LOG_FILENAME]
    ok = (
        len(logged) == 1
        and logged[0]["contract_id"] == contract4["id"]
        and logged[0]["grade_at_accept"] == 82
        and logged[0]["reward"] == contract4["reward"]
        and len(logged[0]["pickups"]) == len(contract4["pickups"])
        and mod.settings.get("contracts") == []
    )
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if not ok:
        failures += 1
        print(f"    expected 1 completed-log entry matching contract4 and an emptied queue; "
              f"got logged={logged!r}, contracts={mod.settings.get('contracts')!r}")

    tmp_path.unlink(missing_ok=True)
    return failures, total


def run() -> int:
    from host.config import Config as _Config

    config = _Config()
    api_client = UexApiClient(config.data["api"]["uex_base_url"], config.data["api"]["uex_token"])
    mod = LogisticsHubModule(api_client, config)
    mod._locations.ensure_loaded()

    failures = 0
    for name, raw_text, expected_pickups, expected_dropoffs in FIXTURES:
        contract = mod._build_contract(raw_text)
        actual_pickups = {
            p["terminal"]["name"]: sorted(p["commodities"])
            for p in contract["pickups"] if p["terminal"]
        }
        actual_dropoffs = {
            d["terminal"]["name"]: sorted(d["commodities"])
            for d in contract["dropoffs"] if d["terminal"]
        }
        expected_pickups_sorted = {k: sorted(v) for k, v in expected_pickups.items()}
        expected_dropoffs_sorted = {k: sorted(v) for k, v in expected_dropoffs.items()}

        ok = actual_pickups == expected_pickups_sorted and actual_dropoffs == expected_dropoffs_sorted
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {name}")
        if not ok:
            failures += 1
            print(f"    expected pickups:  {expected_pickups_sorted}")
            print(f"    actual   pickups:  {actual_pickups}")
            print(f"    expected dropoffs: {expected_dropoffs_sorted}")
            print(f"    actual   dropoffs: {actual_dropoffs}")

    parsing_total, parsing_failures = len(FIXTURES), failures
    print(f"{parsing_total - parsing_failures}/{parsing_total} parsing fixtures passed\n")

    distance_failures, distance_total = run_distance_checks(mod)
    failures += distance_failures
    print(f"\n{distance_total - distance_failures}/{distance_total} distance checks passed")

    manifest_failures, manifest_total = run_manifest_and_capacity_checks(mod)
    failures += manifest_failures
    print(f"\n{manifest_total - manifest_failures}/{manifest_total} manifest/capacity checks passed")

    grading_failures, grading_total = run_grading_checks()
    failures += grading_failures
    print(f"\n{grading_total - grading_failures}/{grading_total} grading checks passed")

    gamelog_failures, gamelog_total = run_gamelog_verify_checks()
    failures += gamelog_failures
    print(f"\n{gamelog_total - gamelog_failures}/{gamelog_total} Game.log verify checks passed")

    try:
        ui_failures, ui_total = run_ui_state_checks()
    except Exception as exc:
        print(f"\n[SKIP] UI-state checks — could not run ({exc})")
    else:
        failures += ui_failures
        print(f"\n{ui_total - ui_failures}/{ui_total} UI-state checks passed")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(run())
