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
import json
import logging
import re
import time

from host.paths import app_root

logger = logging.getLogger("mobioverlay.locations")

CACHE_PATH = app_root() / "locations_cache.json"
CACHE_MAX_AGE_SECONDS = 7 * 24 * 60 * 60  # 1 week — SC locations don't churn daily

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

    def systems(self) -> list[dict]:
        self.ensure_loaded()
        return list(self._systems or [])

    def available_systems(self) -> list[dict]:
        return [s for s in self.systems() if s.get("is_available")]
