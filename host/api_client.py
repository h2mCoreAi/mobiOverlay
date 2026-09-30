"""Shared UEX Corp API client, handed to every module instead of each
module managing its own HTTP session.
"""
import threading
import time
from concurrent.futures import Future

import requests
from requests.adapters import HTTPAdapter


# Short TTL for deduplication cache (seconds). Prevents repeated identical
# GET requests when multiple modules refresh simultaneously at startup or
# when a user clicks several cards' refresh buttons in quick succession.
# UEX rate limit is 120/min — this helps stay well under that threshold.
DEDUPE_TTL_SECONDS = 2.0


class UexApiError(Exception):
    """Generic UEX API failure — network error, bad JSON, non-ok status."""


class UexRateLimitError(UexApiError):
    """UEX's own rate limit was hit (status: requests_limit_reached).
    Kept distinct from UexApiError so callers can show a specific,
    actionable message instead of a generic failure.
    """


class UexApiClient:
    def __init__(self, base_url: str, token: str = ""):
        self.base_url = base_url.rstrip("/") + "/"
        self.token = token
        self._session = requests.Session()
        # Connection pooling: reuse TCP connections across requests,
        # avoiding TLS handshake overhead (~50-100ms) on subsequent calls.
        # pool_connections: number of connection pools to cache
        # pool_maxsize: max connections to save in the pool per host
        adapter = HTTPAdapter(pool_connections=10, pool_maxsize=10)
        self._session.mount('https://', adapter)
        self._session.mount('http://', adapter)

        # Request deduplication: prevents duplicate identical GET requests
        # when multiple callers ask for the same endpoint+params at once.
        # Two mechanisms work together:
        #   1. In-flight sharing: concurrent calls for the same key share a
        #      single Future (only one actual HTTP request fires).
        #   2. Short-TTL cache: a completed result is reused for DEDUPE_TTL_SECONDS
        #      so rapid sequential calls don't each hit the network.
        self._dedupe_lock = threading.Lock()
        self._inflight: dict[str, Future[list[dict]]] = {}
        self._cache: dict[str, tuple[float, list[dict] | Exception]] = {}

    def _cache_key(self, endpoint: str, params: dict | None) -> str:
        """Build a stable, hashable key for dedupe cache lookup."""
        sorted_params = tuple(sorted((params or {}).items()))
        return f"{endpoint}|{sorted_params}"

    def get(self, endpoint: str, params: dict | None = None) -> list[dict]:
        """Fetch data from a UEX endpoint with automatic request deduplication.

        Concurrent or rapid-fire calls for the same endpoint+params share
        a single network request (in-flight) or reuse a recently-fetched
        result (short-TTL cache). This helps avoid redundant API calls and
        stay within UEX's 120/min rate limit.
        """
        key = self._cache_key(endpoint, params)
        now = time.monotonic()

        with self._dedupe_lock:
            # Check short-TTL cache first
            if key in self._cache:
                ts, result = self._cache[key]
                if now - ts < DEDUPE_TTL_SECONDS:
                    if isinstance(result, Exception):
                        raise result
                    return result
                # Expired — remove stale entry
                del self._cache[key]

            # Check if an in-flight request already exists for this key
            if key in self._inflight:
                future = self._inflight[key]
                # Will wait outside the lock
            else:
                # No in-flight request — we'll make one (outside the lock)
                future = None

        if future is not None:
            # Another caller is already fetching this — wait for their result
            return future.result()

        # We're the one making the actual request
        new_future: Future[list[dict]] = Future()
        with self._dedupe_lock:
            # Double-check: another thread might have started while we were outside
            if key in self._inflight:
                future = self._inflight[key]
            else:
                self._inflight[key] = new_future
                future = None

        if future is not None:
            return future.result()

        # Actually make the network call (outside any lock)
        try:
            result = self._do_get(endpoint, params)
            new_future.set_result(result)
        except Exception as exc:
            new_future.set_exception(exc)
            with self._dedupe_lock:
                if key in self._inflight:
                    del self._inflight[key]
            raise

        # Cache result and clean up in-flight
        with self._dedupe_lock:
            self._cache[key] = (time.monotonic(), result)
            if key in self._inflight:
                del self._inflight[key]

        return result

    def _do_get(self, endpoint: str, params: dict | None) -> list[dict]:
        """Perform the actual HTTP GET request (no deduplication logic)."""
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        url = self.base_url + endpoint.lstrip("/") + "/"
        try:
            resp = self._session.get(url, params=params, headers=headers, timeout=10)
            resp.raise_for_status()
            payload = resp.json()
        except requests.RequestException as exc:
            raise UexApiError(f"UEX API request failed: {exc}") from exc
        except ValueError as exc:
            raise UexApiError(f"UEX API returned invalid JSON: {exc}") from exc

        status = payload.get("status")
        if status == "requests_limit_reached":
            raise UexRateLimitError(
                "UEX rate limit reached — wait a moment, then retry."
            )
        if status != "ok":
            raise UexApiError(f"UEX API error response: {payload}")
        return payload.get("data", [])
