"""Shared UEX location data — star systems, terminals, space stations,
outposts, and cities — used by any module that needs to resolve, search,
or display a real Star Citizen place (Commodity Prices, Trade Route
Optimizer, and Logistics Hub each built their own version of this
independently; this is the one shared implementation, same tier as
`api_client.py`).

Fetched once per session (or loaded from an on-disk cache, see
`CACHE_MAX_AGE_SECONDS`) and kept in memory. Modules build their own
picker widgets from the data this returns — this module has no PySide6
dependency and no UI of its own.

**Why endpoint-tagging matters (read before touching dedup logic):**
`terminals`, `space_stations`, `outposts`, and `cities` each have their
own independent id sequence on UEX's side. `terminals` id 17 is "Bud's
Growery"; `space_stations` id 17 is a completely different real place,
"MIC-L1 Shallow Frontier Station". Deduping by a bare numeric id silently
drops or merges unrelated locations — every row is tagged with its
source endpoint at fetch time (`_endpoint`), and every dedup/lookup key
in this module uses `(endpoint, id)`, never a bare id. This was a real,
silently-wrong bug found and fixed the hard way in Logistics Hub before
this shared service existed — see docs/DECISIONS.md, 2026-09-04.
"""
import difflib
import json
import logging
import re
import time

from host.paths import app_root

logger = logging.getLogger("mobioverlay.locations")

CACHE_PATH = app_root() / "locations_cache.json"
CACHE_MAX_AGE_SECONDS = 7 * 24 * 60 * 60  # 1 week — SC locations don't churn daily

# Cache version: bumped when the schema or resolution logic changes in a way
# that would make old cached data produce wrong results. A stale-versioned
# cache is treated as invalid regardless of age — this prevents users from
# getting stuck on a broken id space after a fix (exactly the "Seraphim
# Station → GrimHEX" bug that prompted this, 2026-09-20).
CACHE_VERSION = 2  # v2: 2026-09-20, added alias support + hauling-terminal preference

# Known aliases: OCR text from Star Citizen → UEX terminal name/nickname.
# Used when the in-game contract text uses a different name than UEX's own
# data (e.g. "Beautiful Glen Station" vs "CRU-L5 Beautiful Glen Station",
# or a station renamed in-game but not yet updated in UEX). The key is
# normalized (lowercase, alphanumeric only); the value is the target to
# look up in the name index. Add entries here when OCR text consistently
# maps to the wrong UEX record or no record at all.
LOCATION_ALIASES = {
    # Beautiful Glen Station: in-game contract text says "Beautiful Glen
    # Station" but UEX's space_stations record is "CRU-L5 Beautiful Glen
    # Station" with nickname "CRU-L5". The Admin terminal is "Admin - CRU-L5".
    "beautifulglenstation": "CRU-L5 Beautiful Glen Station",
    "beautifulglen": "CRU-L5 Beautiful Glen Station",
    # Add more as discovered — the pattern is: in-game text that doesn't
    # match UEX's name/nickname verbatim → the actual UEX name to resolve to.
}

# `terminals` goes first: its nicknames tend to be the fuller, friendlier
# name ("Port Tressler", "HDMS-Edmond") for the very same real place that
# the structural endpoints label tersely ("Tressler", "Edmond") — the
# first endpoint to claim a given nickname/name wins that slot. See the
# module docstring above for why endpoint tagging (not the name itself)
# is what actually disambiguates two different real places.
LOCATION_ENDPOINTS = ("terminals", "space_stations", "outposts", "cities")


class LocationService:
    def __init__(self, api_client):
        self.api = api_client
        self._name_index: dict[str, dict] | None = None  # normalized name -> row
        self._locations: list[dict] | None = None  # deduped, one entry per real place
        self._systems: list[dict] | None = None
        # Distance lookups are queried lazily, one pair (or one system-pair
        # table) at a time, and cached only in memory for this session —
        # never bulk-prefetched (see `distance()`/`_orbit_distance_table()`
        # below), since pre-pulling every possible pair across ~70 systems
        # would mean querying data almost never used.
        self._distance_cache: dict[tuple, float | None] = {}
        self._orbit_tables: dict[tuple, dict | None] = {}
        self._friendly_names: dict[str, str] | None = None  # normalized nickname -> best display_name, see friendly_label()
        # Commodities cache — fetched once per session on first call to
        # commodities(), shared across all modules that need the list
        # (commodity_prices, refinery_finder, multi_commodity_finder).
        # Avoids 3+ redundant API calls at startup.
        self._commodities: list[dict] | None = None

    # ------------------------------------------------------------------
    # Loading / caching
    # ------------------------------------------------------------------
    def ensure_loaded(self, force_refresh: bool = False):
        """Populate the in-memory index — from the disk cache if it's
        still fresh, otherwise from the live UEX API (and re-cache the
        result). A no-op if already loaded this session, unless
        force_refresh is set."""
        if self._locations is not None and not force_refresh:
            return
        if force_refresh:
            self._friendly_names = None
        if not force_refresh and self._load_from_disk():
            return
        self._fetch_from_api()
        self._save_to_disk()

    def _load_from_disk(self) -> bool:
        if not CACHE_PATH.exists():
            return False
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError):
            logger.warning("locations: cache file unreadable, will refetch", exc_info=True)
            return False

        cache_version = payload.get("cache_version", 1)
        if cache_version < CACHE_VERSION:
            logger.info(
                "locations: cache version %d is outdated (current=%d), refetching",
                cache_version, CACHE_VERSION,
            )
            return False

        fetched_at = payload.get("fetched_at", 0)
        if time.time() - fetched_at > CACHE_MAX_AGE_SECONDS:
            logger.info("locations: cache is stale (>%ds old), refetching", CACHE_MAX_AGE_SECONDS)
            return False

        self._systems = payload.get("systems", [])
        self._locations = payload.get("locations", [])
        self._rebuild_name_index()
        logger.info(
            "locations: loaded %d locations from cache (%ds old)",
            len(self._locations), int(time.time() - fetched_at),
        )
        return True

    def _save_to_disk(self):
        payload = {
            "cache_version": CACHE_VERSION,
            "fetched_at": time.time(),
            "systems": self._systems,
            "locations": self._locations,
        }
        try:
            with open(CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(payload, f)
        except OSError:
            logger.warning("locations: failed to write cache file", exc_info=True)

    def _fetch_from_api(self):
        locations_by_key: dict = {}
        name_index: dict[str, dict] = {}

        try:
            systems = self.api.get("star_systems")
        except Exception:
            logger.warning("locations: could not fetch star_systems from UEX API", exc_info=True)
            self._systems = []
            self._locations = []
            self._name_index = {}
            return

        self._systems = systems

        for system in systems:
            if not system.get("is_available") or not system.get("id"):
                continue
            for endpoint in LOCATION_ENDPOINTS:
                try:
                    rows = self.api.get(endpoint, {"id_star_system": system["id"]})
                except Exception:
                    logger.warning(
                        "locations: could not fetch %s for system %s",
                        endpoint, system.get("name"), exc_info=True,
                    )
                    continue
                for row in rows:
                    row["_endpoint"] = endpoint
                    key = self.terminal_key(row)
                    locations_by_key.setdefault(key, row)
                    for name_key in ("nickname", "name"):
                        label = row.get(name_key)
                        if label:
                            name_index.setdefault(self.normalize(label), row)

        self._locations = list(locations_by_key.values())
        self._name_index = name_index
        logger.info(
            "locations: resolved %d unique locations (%d searchable names) from UEX API",
            len(self._locations), len(name_index),
        )

    def _rebuild_name_index(self):
        index: dict[str, dict] = {}
        for row in self._locations or []:
            for name_key in ("nickname", "name"):
                label = row.get(name_key)
                if label:
                    index.setdefault(self.normalize(label), row)
        self._name_index = index

    # ------------------------------------------------------------------
    # Lookup helpers
    # ------------------------------------------------------------------
    @staticmethod
    def normalize(text: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", text.lower())

    @staticmethod
    def terminal_key(terminal: dict):
        """A dedup/lookup key that's actually unique across all four
        location endpoints — see the module docstring. Falls back to
        object identity if a row somehow has no id (shouldn't happen for
        real UEX rows)."""
        term_id = terminal.get("id")
        if term_id is None:
            return id(terminal)
        return (terminal.get("_endpoint"), term_id)

    @staticmethod
    def same_physical_place(a: dict, b: dict) -> bool:
        """True if `a` and `b` are the same real place even though they're
        different UEX records — a `terminals` kiosk sitting inside a
        station/outpost/city links back to that structural record via
        `id_space_station`/`id_outpost`/`id_city`. Confirmed real: "Admin -
        Seraphim" (a `terminals` commodity kiosk, id 259) and "Seraphim
        Station" (the `space_stations` record, id 27) are the same place
        in-game, but `terminal_key()` treats them as unrelated — a route
        cost lookup between them then falls back to a coarse distance
        estimate instead of recognizing "already here," making a genuinely
        farther stop look cheaper by comparison."""
        if LocationService.terminal_key(a) == LocationService.terminal_key(b):
            return True
        # Each FK only means what it says when `structural` actually comes
        # from the endpoint it names — `id_space_station` is meaningless
        # against an `outposts`/`cities` record that happens to reuse the
        # same bare numeric id (exactly the cross-endpoint id-collision
        # this whole module's `_endpoint` tagging exists to prevent, see
        # the module docstring — missed here on the first pass).
        for kiosk, structural, fk, endpoint in (
            (a, b, "id_space_station", "space_stations"), (a, b, "id_outpost", "outposts"), (a, b, "id_city", "cities"),
            (b, a, "id_space_station", "space_stations"), (b, a, "id_outpost", "outposts"), (b, a, "id_city", "cities"),
        ):
            if (
                kiosk.get("_endpoint") == "terminals"
                and structural.get("_endpoint") == endpoint
                and kiosk.get(fk)
                and kiosk.get(fk) == structural.get("id")
            ):
                return True
        return False

    @staticmethod
    def display_name(terminal: dict) -> str:
        """Human-readable label for a location record.

        `nickname` is sometimes the whole friendly name already ("Port
        Tressler", "Terra Mills") and sometimes just a terse lagrange-
        point code ("MIC-L1", with the actual readable label — "MIC-L1
        Shallow Frontier Station" — living in `name`, prefixed by that
        same code). Stripping the nickname-as-prefix from `name` is right
        for the second case but wrong for the first. Distinguish them
        cheaply: a genuine short code is uppercase with no spaces;
        anything with a space or lowercase letters is a real name, used
        as-is.
        """
        name = terminal.get("name") or ""
        nickname = terminal.get("nickname") or ""
        looks_like_code = bool(nickname) and " " not in nickname and nickname == nickname.upper()
        if nickname and not looks_like_code:
            return nickname
        cleaned = re.sub(r"^Admin - ", "", name)
        if nickname and cleaned.startswith(nickname + " "):
            cleaned = cleaned[len(nickname) + 1:]
        return cleaned or nickname or name or "?"

    @classmethod
    def search_label(cls, terminal: dict) -> str:
        """Combo/search item text: the readable name plus its short code
        in parentheses when it has one ("Shallow Frontier Station
        (MIC-L1)"). `display_name` alone drops the code for anything but
        a trade terminal, which makes searching by the in-game code a
        player actually sees find nothing — both need to live in the same
        string for either to be searchable via simple substring matching.
        """
        display = cls.display_name(terminal)
        nickname = terminal.get("nickname") or ""
        looks_like_code = bool(nickname) and " " not in nickname and nickname == nickname.upper()
        if looks_like_code and nickname.lower() != display.lower():
            return f"{display} ({nickname})"
        return display

    def _friendly_name_index(self) -> dict[str, str]:
        """Normalized nickname -> longest known display_name for that
        nickname, across every endpoint. Built once per session (invalidated
        alongside the rest of the index on a force_refresh) and cached.

        Exists because a real place's fullest name doesn't always live on
        its `terminals` record: a terminal's own `name` is sometimes just a
        bare admin/kiosk label (`"Admin - CRU-L5"`) with a short-code
        `nickname` (`"CRU-L5"`) and nothing descriptive at all, while a
        sibling `space_stations`/`outposts`/`cities` record for the exact
        same physical place (same nickname) carries the actual in-game name
        (`"CRU-L5 Beautiful Glen Station"`). See `friendly_label()`.

        Deliberately only pulls from the non-`terminals` endpoints: two
        *different* terminals at the same station (e.g. "Landing Services -
        CRU-L5", "Live Fire Weapons - CRU-L5") are themselves longer than
        the real place name but describe a facility, not the place — using
        "longest name wins" across all endpoints would pick one of those
        instead of the actual station/outpost/city name."""
        if self._friendly_names is not None:
            return self._friendly_names
        self.ensure_loaded()
        index: dict[str, str] = {}
        for row in self._locations or []:
            if row.get("_endpoint") == "terminals":
                continue
            nickname = row.get("nickname") or ""
            if not nickname:
                continue
            key = self.normalize(nickname)
            candidate = self.display_name(row)
            if key not in index or len(candidate) > len(index[key]):
                index[key] = candidate
        self._friendly_names = index
        return index

    def friendly_label(self, terminal: dict) -> str:
        """Like `search_label()`, but for a terminal whose own record has no
        descriptive name of its own — just a short code repeated as both
        `name` (kiosk-prefixed) and `nickname`. Borrows the fuller name a
        sibling non-terminal record has for the same physical place (same
        normalized nickname) via `_friendly_name_index()`, so a
        terminals-only picker (e.g. Trade Route Optimizer's origin combo)
        stays searchable by the place's actual in-game name, not just its
        short code. Falls back to `search_label()` unchanged whenever the
        terminal's own name is already at least as descriptive, or it has
        no nickname to look up."""
        nickname = terminal.get("nickname") or ""
        if not nickname:
            return self.search_label(terminal)
        own_display = self.display_name(terminal)
        best = self._friendly_name_index().get(self.normalize(nickname))
        if not best or len(best) <= len(own_display):
            return self.search_label(terminal)
        looks_like_code = " " not in nickname and nickname == nickname.upper()
        if looks_like_code and nickname.lower() != best.lower():
            return f"{best} ({nickname})"
        return best

    def resolve(self, text: str) -> dict | None:
        """Best-effort single match — the first hit from `resolve_all`, if
        any. Callers that need to know whether a phrase is *ambiguous*
        (matches more than one distinct real place — e.g. "ArcCorp Mining
        Area" alone matches both "ArcCorp Mining Area 045" and "...056")
        should use `resolve_all` instead and check its length; silently
        picking one of several real candidates can confidently show the
        wrong place rather than an honest "not sure which one"."""
        matches = self.resolve_all(text)
        return matches[0] if matches else None

    # A short nickname/code (2-3 chars, e.g. Port Olisar's "PO") is prone to
    # coincidentally appearing *inside* unrelated text purely by chance —
    # confirmed for real: "DROP OFF" normalizes to "dropoff", which
    # contains "po" (the tail of "dro**p**" + the head of "**o**ff"), so it
    # substring-matched Port Olisar even though the OCR text had nothing to
    # do with it. Exact matches are always trusted regardless of length —
    # this only guards the fuzzy substring pass.
    MIN_SUBSTRING_KEY_LEN = 4

    def resolve_all(self, text: str) -> list[dict]:
        """Every distinct known location whose name/nickname matches
        `text` — exact normalized match first (always a single result when
        it hits), otherwise every substring match in either direction
        (skipping keys shorter than `MIN_SUBSTRING_KEY_LEN` — see above),
        deduped by `terminal_key` (two index entries can point at the same
        real record via its nickname and its name)."""
        self.ensure_loaded()
        if not self._name_index:
            return []
        norm = self.normalize(text)
        if not norm:
            return []
        if norm in self._name_index:
            return [self._name_index[norm]]
        matches: list[dict] = []
        seen_keys = set()
        for key, row in self._name_index.items():
            if not key or len(key) < self.MIN_SUBSTRING_KEY_LEN:
                continue
            if key in norm or norm in key:
                k = self.terminal_key(row)
                if k not in seen_keys:
                    seen_keys.add(k)
                    matches.append(row)
        return matches

    def best_fuzzy_match(self, text: str) -> tuple[dict, float] | None:
        """The single best-scoring known location name/nickname for `text`,
        with **no cutoff applied** — `resolve_fuzzy()` below is the cutoff-
        enforcing wrapper callers should normally use. Exposed separately so
        a caller building a debug trace can record *how close* a dropped
        candidate came (e.g. "closest was X at 81%, cutoff is 85%") instead
        of only ever seeing a bare miss. Returns `(location, score)` (score
        0-1, `difflib.SequenceMatcher` ratio), or `None` only if the index
        or `text` itself is empty."""
        self.ensure_loaded()
        if not self._name_index:
            return None
        norm = self.normalize(text)
        if not norm:
            return None
        best_row: dict | None = None
        best_score = 0.0
        matcher = difflib.SequenceMatcher(a=norm)
        for key, row in self._name_index.items():
            if not key:
                continue
            matcher.set_seq2(key)
            score = matcher.ratio()
            if score > best_score:
                best_score = score
                best_row = row
        return (best_row, best_score) if best_row is not None else None

    def resolve_fuzzy(self, text: str, cutoff: float = 0.85) -> tuple[dict, float] | None:
        """Best-effort fuzzy match against the same name index `resolve_all`
        uses, for callers willing to accept an unconfirmed guess and surface
        it as such (see Logistics Hub's `_build_contract`, which appends an
        amber-warning note alongside any fuzzy resolution). Returns
        `(location, score)` for the single best-scoring name at or above
        `cutoff` (0-1, `difflib.SequenceMatcher` ratio), or `None` if nothing
        clears it.

        Deliberately **not** folded into `resolve()`/`resolve_all()` — every
        other caller (Trade Route Optimizer's terminal picker, Commodity
        Prices' nickname lookup, this module's own CURRENT LOCATION combo)
        has no way to show an uncertainty warning, so a fuzzy guess there
        would look exactly as confident as a real match. This stays an
        explicit opt-in for callers that can display that distinction.

        Default cutoff of 0.85 is deliberately strict, not the more common
        0.6-0.75 range — verified against a real captured contract (see
        DECISIONS.md): OCR debris "Tech's Ll" (mangled from "microTech's Ll
        Lagrange point", not a real location at all) scored 0.77 against an
        unrelated real shop named "Teach's" and would have added a spurious
        stop at a lower cutoff. Every genuine OCR-garbled name tested so far
        (dropped/altered letters, not debris) scored 0.87+."""
        best = self.best_fuzzy_match(text)
        return best if best and best[1] >= cutoff else None

    def resolve_for_hauling(self, text: str) -> list[dict]:
        """Hauling-contract-aware resolution: resolves OCR text to terminal
        records suitable for cargo/freight operations.

        Key differences from plain `resolve_all()`:
        1. **Aliases first**: checks `LOCATION_ALIASES` for known in-game
           text that doesn't match UEX naming (e.g. "Beautiful Glen Station"
           → "CRU-L5 Beautiful Glen Station").
        2. **Prefers Admin terminals**: for hauling contracts, the actual
           stop is the "Admin - X" commodity kiosk, not the structural
           space_station/outpost/city record. When both exist for the same
           place, the Admin terminal is what UEX's commodity/route APIs use.
        3. **Validates matches**: rejects any candidate whose name/nickname
           doesn't fuzzy-match the OCR text (cutoff 0.6), preventing false
           positives like "Seraphim Station" → GrimHEX just because they
           share a normalized substring.

        Returns an empty list if no valid match is found (same contract as
        `resolve_all()`). Callers should fall back to `resolve_fuzzy()` if
        this returns empty and they're willing to accept an unconfirmed guess.
        """
        self.ensure_loaded()
        if not self._name_index:
            return []
        norm = self.normalize(text)
        if not norm:
            return []

        # Step 1: Check aliases first — known game-text-to-UEX-name mappings
        alias_target = LOCATION_ALIASES.get(norm)
        if alias_target:
            alias_matches = self.resolve_all(alias_target)
            if alias_matches:
                return self._filter_and_prefer_admin(alias_matches, text, try_admin_lookup=True)

        # Step 2: Normal resolution
        matches = self.resolve_all(text)
        if not matches:
            return []

        # Step 3: Filter and prefer Admin terminals
        return self._filter_and_prefer_admin(matches, text, try_admin_lookup=True)

    def _filter_and_prefer_admin(
        self, matches: list[dict], ocr_text: str, try_admin_lookup: bool = False
    ) -> list[dict]:
        """Filter matches to those that actually match the OCR text, then
        prefer Admin terminals for hauling. Returns filtered+sorted list.

        If try_admin_lookup is True and a structural record (space_station/
        outpost/city) matches, also look up its Admin terminal and include
        that in the results. This handles "Seraphim Station" → Admin - Seraphim
        for hauling contracts where the Admin terminal is the real target.
        """
        # Validate: reject matches whose name/nickname doesn't resemble the
        # OCR text at all — prevents "Seraphim Station" matching GrimHEX just
        # because a space_station id happens to be in the index.
        validated = []
        norm_ocr = self.normalize(ocr_text)
        matcher = difflib.SequenceMatcher(a=norm_ocr)

        # Track seen keys to avoid duplicates when adding Admin terminals
        seen_keys = set()

        # First pass: collect Admin terminals to add (via FK lookup)
        # These bypass the fuzzy validation since they're validated through
        # their structural record.
        admin_from_fk: list[tuple[dict, float]] = []

        for m in matches:
            name = m.get("name") or ""
            nickname = m.get("nickname") or ""
            # Check if either name or nickname fuzzy-matches the OCR text
            best_score = 0.0
            for label in (name, nickname):
                if not label:
                    continue
                norm_label = self.normalize(label)
                if not norm_label:
                    continue
                # Exact or substring match is always valid
                if norm_label in norm_ocr or norm_ocr in norm_label:
                    best_score = 1.0
                    break
                # Fuzzy match as fallback
                matcher.set_seq2(norm_label)
                best_score = max(best_score, matcher.ratio())
            if best_score >= 0.6:
                key = self.terminal_key(m)
                if key not in seen_keys:
                    seen_keys.add(key)
                    validated.append((m, best_score))

                # If this is a structural record and try_admin_lookup is True,
                # also try to find its Admin terminal. The Admin terminal is
                # validated by the FK relationship, not by fuzzy matching the
                # OCR text (e.g. "Shallow Fields Station" → "Admin - CRU-L4"
                # via id_space_station FK, even though those names don't match).
                if try_admin_lookup and m.get("_endpoint") in ("space_stations", "outposts", "cities"):
                    admin = self.find_admin_terminal_for_station(m)
                    if admin:
                        admin_key = self.terminal_key(admin)
                        if admin_key not in seen_keys:
                            # Queue for addition (don't add to seen_keys yet,
                            # in case the Admin terminal also appears directly
                            # in matches with a higher score)
                            admin_from_fk.append((admin, 0.95))

        # Add Admin terminals from FK lookup
        for admin, score in admin_from_fk:
            admin_key = self.terminal_key(admin)
            if admin_key not in seen_keys:
                seen_keys.add(admin_key)
                validated.append((admin, score))

        if not validated:
            return []

        # Sort: prefer Admin terminals (actual commodity kiosks) for hauling,
        # then by fuzzy match score
        def sort_key(item):
            m, score = item
            name = m.get("name") or ""
            is_admin = name.startswith("Admin - ")
            is_terminal = m.get("_endpoint") == "terminals"
            # Higher score is better, Admin terminals are preferred
            return (not is_admin, not is_terminal, -score)

        validated.sort(key=sort_key)
        return [m for m, _score in validated]

    def find_admin_terminal_for_station(self, station: dict) -> dict | None:
        """Given a space_station/outpost/city record, find its corresponding
        Admin terminal (the commodity kiosk). Returns None if not found.

        This is the reverse of `same_physical_place()`: given a structural
        record, find the trading kiosk that references it via id_space_station/
        id_outpost/id_city. Used when resolution returns a structural record
        but the caller needs the actual Admin terminal for API calls."""
        self.ensure_loaded()
        station_endpoint = station.get("_endpoint")
        station_id = station.get("id")
        if not station_endpoint or station_id is None:
            return None

        fk_mapping = {
            "space_stations": "id_space_station",
            "outposts": "id_outpost",
            "cities": "id_city",
        }
        fk_key = fk_mapping.get(station_endpoint)
        if not fk_key:
            return None

        for loc in self._locations or []:
            if (
                loc.get("_endpoint") == "terminals"
                and loc.get(fk_key) == station_id
                and (loc.get("name") or "").startswith("Admin - ")
            ):
                return loc
        return None

    def search(self, query: str, limit: int = 50) -> list[dict]:
        """All unique locations whose search_label contains `query`
        (case-insensitive substring), for building a picker's filtered
        list without a full Qt QCompleter. Empty query returns everything
        (still capped at `limit`)."""
        self.ensure_loaded()
        q = query.lower()
        results = [
            row for row in (self._locations or [])
            if q in self.search_label(row).lower()
        ]
        return results[:limit]

    def all_locations(self) -> list[dict]:
        self.ensure_loaded()
        return list(self._locations or [])

    # ------------------------------------------------------------------
    # Facilities — what a location actually has (refinery, cargo center,
    # loading dock, etc.), not just prices. Confirmed live (2026-09-08):
    # every `terminals` row already carries these as `is_*`/`has_*` boolean
    # flags (0/1) — no separate endpoint needed. Only meaningful for
    # `terminals`-endpoint rows; the structural endpoints
    # (space_stations/outposts/cities) don't carry these flags themselves
    # (a station's terminals do, individually). Centralized here rather
    # than in one module so any future module can filter/display the same
    # facility set without re-deriving which raw flags matter and what to
    # call them — see docs/DECISIONS.md, 2026-09-08.
    # ------------------------------------------------------------------
    FACILITY_FLAGS = {
        "is_refinery": "Refinery",
        "is_cargo_center": "Cargo Center",
        "is_habitation": "Habitation",
        "is_medical": "Medical",
        "is_food": "Food",
        "is_shop_fps": "FPS Shop",
        "is_shop_vehicle": "Vehicle Shop",
        "is_refuel": "Refuel",
        "is_repair": "Repair",
        "is_jump_point": "Jump Point",
        "has_loading_dock": "Loading Dock",
        "has_docking_port": "Docking Port",
        "has_freight_elevator": "Freight Elevator",
    }

    @classmethod
    def facilities(cls, terminal: dict) -> set[str]:
        """Human-readable facility names this terminal record reports
        having (e.g. {"Refinery", "Loading Dock"}). Empty set for a
        non-`terminals` row or a terminal with none of the tracked flags —
        never raises on a missing/falsy flag."""
        return {
            label for flag, label in cls.FACILITY_FLAGS.items()
            if terminal.get(flag)
        }

    def systems(self) -> list[dict]:
        self.ensure_loaded()
        return list(self._systems or [])

    def available_systems(self) -> list[dict]:
        return [s for s in self.systems() if s.get("is_available")]

    # ------------------------------------------------------------------
    # Commodities — shared cache across modules (Q2 optimization)
    # ------------------------------------------------------------------
    def commodities(self) -> list[dict]:
        """All commodities from UEX's `commodities` endpoint, cached for the
        session. Avoids multiple modules (commodity_prices, refinery_finder,
        multi_commodity_finder) each fetching the same ~150-200 item list
        independently at startup."""
        if self._commodities is not None:
            return self._commodities
        try:
            self._commodities = self.api.get("commodities")
        except Exception:
            logger.warning("locations: could not fetch commodities from UEX API", exc_info=True)
            self._commodities = []
        return self._commodities

    def visible_commodity_names(self) -> list[str]:
        """Sorted list of visible commodity names — the common query pattern
        used by commodity pickers across multiple modules."""
        return sorted({
            row["name"] for row in self.commodities()
            if row.get("is_visible") and row.get("name")
        })

    def raw_commodities(self) -> list[dict]:
        """Commodities where is_raw == 1 (for refinery_finder)."""
        return [
            {"id": row["id"], "name": row["name"]}
            for row in self.commodities()
            if row.get("is_raw") == 1 and row.get("is_visible") and row.get("name") and row.get("id") is not None
        ]

    # ------------------------------------------------------------------
    # Real travel distance (Phase 3 of the location-service plan — see
    # docs/DECISIONS.md) — queried lazily per pair/system-pair, never
    # bulk-prefetched, and cached only for this session (not the 7-day
    # disk cache the location index itself uses, since callers ask for
    # specific pairs on demand, not "give me everything").
    # ------------------------------------------------------------------
    def distance(self, a: dict, b: dict) -> float | None:
        """Real travel distance between two locations, or None if it
        genuinely can't be determined (missing orbit/system data on either
        record, or the UEX API call itself failed) — callers should have a
        fallback for that case, this never estimates.

        Uses `terminals_distances` (point-to-point) when both locations
        are `terminals`-endpoint records — the only case with that
        granularity — since collapsing everything to orbit-level would
        make two different terminals on the *same* planet look equally
        close, throwing away real precision. Otherwise falls back to
        `orbits_distances` (planet/orbit-level, but works for any location
        and covers cross-system pairs too) via each record's `id_orbit`.
        """
        if self.same_physical_place(a, b):
            return 0.0

        key_a, key_b = self.terminal_key(a), self.terminal_key(b)
        cache_key = (key_a, key_b)
        if cache_key in self._distance_cache:
            return self._distance_cache[cache_key]
        reverse_key = (key_b, key_a)
        if reverse_key in self._distance_cache:
            value = self._distance_cache[reverse_key]
            self._distance_cache[cache_key] = value
            return value

        value = self._fetch_distance(a, b)
        self._distance_cache[cache_key] = value
        return value

    def _fetch_distance(self, a: dict, b: dict) -> float | None:
        if (
            a.get("_endpoint") == "terminals" and b.get("_endpoint") == "terminals"
            and a.get("id") is not None and b.get("id") is not None
        ):
            try:
                resp = self.api.get(
                    "terminals_distances",
                    {"id_terminal_origin": a["id"], "id_terminal_destination": b["id"]},
                )
            except Exception:
                logger.warning("locations: terminals_distances lookup failed", exc_info=True)
                resp = None
            if isinstance(resp, dict) and resp.get("distance") is not None:
                try:
                    return float(resp["distance"])
                except (TypeError, ValueError):
                    pass

        sys_a, sys_b = a.get("id_star_system"), b.get("id_star_system")
        orbit_a, orbit_b = a.get("id_orbit"), b.get("id_orbit")
        if not (sys_a and sys_b and orbit_a and orbit_b):
            return None
        table = self._orbit_distance_table(sys_a, sys_b)
        if not table:
            return None
        return table.get((orbit_a, orbit_b), table.get((orbit_b, orbit_a)))

    def _orbit_distance_table(self, sys_a, sys_b) -> dict | None:
        """One `orbits_distances` call covers *every* orbit pair between
        two systems (or within one, if sys_a == sys_b) — cached per
        system-pair so a whole session's worth of cross-body cost lookups
        for the same couple of systems costs one real API call, not one
        per pair."""
        key = tuple(sorted((sys_a, sys_b)))
        if key in self._orbit_tables:
            return self._orbit_tables[key]
        try:
            rows = self.api.get(
                "orbits_distances",
                {"id_star_system_origin": sys_a, "id_star_system_destination": sys_b},
            )
        except Exception:
            logger.warning("locations: orbits_distances lookup failed", exc_info=True)
            self._orbit_tables[key] = None
            return None
        table: dict = {}
        for row in rows:
            oa, ob, dist = row.get("id_orbit_origin"), row.get("id_orbit_destination"), row.get("distance")
            if oa is None or ob is None or dist is None:
                continue
            try:
                table[(oa, ob)] = float(dist)
            except (TypeError, ValueError):
                continue
        self._orbit_tables[key] = table
        return table
