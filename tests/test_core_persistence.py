"""Regression suite for Core persistence and resilience: config.json
recovery and atomic saves, the location cache never persisting a failed
UEX fetch, and the API client's rate-limit detection.

No test framework dependency and no network access — plain asserts, run
directly:
    python tests/test_core_persistence.py
"""
import json
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from host import locations as locations_mod
from host.api_client import UexApiClient, UexApiError, UexRateLimitError
from host.config import Config


def test_config_recovers_from_corrupt_file() -> int:
    tmp = Path(tempfile.mkdtemp())
    path = tmp / "config.json"
    path.write_text('{"ui": {"window_opacity": 0.5', encoding="utf-8")

    config = Config(path)
    assert config.data["ui"]["window_opacity"] == 0.92, "corrupt config should fall back to defaults"
    backups = list(tmp.glob("config.json.corrupt-*"))
    assert len(backups) == 1, "corrupt config wasn't preserved for recovery"

    config.data["ui"]["window_opacity"] = 0.6
    config.save()
    assert json.loads(path.read_text(encoding="utf-8"))["ui"]["window_opacity"] == 0.6
    assert not list(tmp.glob("*.tmp")), "atomic save left a temp file behind"
    return 3


def test_config_repairs_wrong_typed_section() -> int:
    tmp = Path(tempfile.mkdtemp())
    path = tmp / "config.json"
    path.write_text('{"ui": null, "cards": {"x": {"collapsed": true}}}', encoding="utf-8")
    config = Config(path)
    assert config.data["ui"]["font_scale"] == 1.15, "null ui section should be replaced by defaults"
    assert config.data["cards"]["x"]["collapsed"] is True, "valid sections must survive"
    return 2


class _FakeApi:
    """Answers star_systems with one system; every other endpoint either
    returns one row or raises, per `fail`."""

    def __init__(self, fail_endpoints=()):
        self.fail_endpoints = set(fail_endpoints)
        self.calls = 0

    def get(self, endpoint, params=None):
        self.calls += 1
        if endpoint in self.fail_endpoints:
            raise UexApiError(f"{endpoint} down")
        if endpoint == "star_systems":
            return [{"id": 1, "name": "Stanton", "is_available": 1}]
        return [{"id": 10, "name": f"{endpoint} row", "nickname": "", "is_available": 1}]


def _with_cache_path(fn):
    original = locations_mod.CACHE_PATH
    locations_mod.CACHE_PATH = Path(tempfile.mkdtemp()) / "locations_cache.json"
    try:
        return fn(locations_mod.CACHE_PATH)
    finally:
        locations_mod.CACHE_PATH = original


def test_failed_fetch_is_not_cached() -> int:
    def body(cache_path):
        svc = locations_mod.LocationService(_FakeApi(fail_endpoints={"star_systems"}))
        svc.ensure_loaded()
        assert svc.all_locations() == []
        assert not cache_path.exists(), "an empty, failed fetch was written to the 7-day cache"
        return 1
    return _with_cache_path(body)


def test_partial_fetch_prefers_older_complete_cache() -> int:
    def body(cache_path):
        stale = {
            "cache_version": locations_mod.CACHE_VERSION,
            "fetched_at": time.time() - locations_mod.CACHE_MAX_AGE_SECONDS - 60,
            "systems": [{"id": 1, "name": "Stanton", "is_available": 1}],
            "locations": [{"id": 99, "name": "Old Complete Row", "_endpoint": "terminals"}],
        }
        cache_path.write_text(json.dumps(stale), encoding="utf-8")
        svc = locations_mod.LocationService(_FakeApi(fail_endpoints={"outposts"}))
        svc.ensure_loaded()
        names = [row["name"] for row in svc.all_locations()]
        assert names == ["Old Complete Row"], f"expected the stale complete cache, got {names}"
        assert json.loads(cache_path.read_text(encoding="utf-8"))["fetched_at"] == stale["fetched_at"], \
            "a partial fetch overwrote the cache"
        return 2
    return _with_cache_path(body)


def test_failed_fetch_retries_later() -> int:
    def body(cache_path):
        api = _FakeApi(fail_endpoints={"star_systems"})
        svc = locations_mod.LocationService(api)
        svc.ensure_loaded()
        calls_after_first = api.calls
        svc.ensure_loaded()
        assert api.calls == calls_after_first, "retry wasn't throttled"
        api.fail_endpoints.clear()
        svc._last_fetch_attempt -= locations_mod.FETCH_RETRY_SECONDS + 1
        svc.ensure_loaded()
        assert len(svc.all_locations()) == len(locations_mod.LOCATION_ENDPOINTS)
        assert cache_path.exists(), "the successful retry should be cached"
        return 2
    return _with_cache_path(body)


def test_commodities_failure_not_cached() -> int:
    api = MagicMock()
    api.get.side_effect = [UexApiError("down"), [{"id": 1, "name": "Gold", "is_visible": 1}]]
    svc = locations_mod.LocationService(api)
    assert svc.commodities() == []
    assert svc.visible_commodity_names() == ["Gold"], "commodities() stayed empty after a failed first fetch"
    return 1


def _client_with_response(status_code: int, payload) -> UexApiClient:
    client = UexApiClient("https://api.example.com/")
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = status_code < 400
    resp.json.return_value = payload
    if status_code >= 400:
        import requests
        resp.raise_for_status.side_effect = requests.HTTPError(f"{status_code}")
    client._session.get = MagicMock(return_value=resp)
    return client


def test_rate_limit_detected_on_http_error() -> int:
    for status, payload in ((429, {}), (403, {"status": "requests_limit_reached"})):
        client = _client_with_response(status, payload)
        try:
            client.get("commodities")
        except UexRateLimitError:
            pass
        else:
            raise AssertionError(f"HTTP {status} rate limit not raised as UexRateLimitError")
    return 2


def test_non_dict_payload_is_api_error() -> int:
    client = _client_with_response(200, ["unexpected"])
    try:
        client.get("commodities")
    except UexApiError:
        return 1
    raise AssertionError("a non-dict payload should raise UexApiError")


def run() -> int:
    checks = 0
    for test in (
        test_config_recovers_from_corrupt_file,
        test_config_repairs_wrong_typed_section,
        test_failed_fetch_is_not_cached,
        test_partial_fetch_prefers_older_complete_cache,
        test_failed_fetch_retries_later,
        test_commodities_failure_not_cached,
        test_rate_limit_detected_on_http_error,
        test_non_dict_payload_is_api_error,
    ):
        checks += test()
        print(f"[PASS] {test.__name__}")
    print(f"\n{checks}/{checks} core persistence checks passed")
    return checks


if __name__ == "__main__":
    run()
