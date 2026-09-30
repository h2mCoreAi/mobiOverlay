"""Test UexApiClient request deduplication (M5 optimization).

Verifies that:
1. Concurrent identical requests share a single network call
2. Short-TTL cache prevents repeated calls within the window
3. Different params produce different requests
4. Errors are cached and re-raised

No test framework dependency — plain asserts, run directly:
    python tests/test_api_client_dedupe.py
"""
import sys
import time
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from host.api_client import UexApiClient, DEDUPE_TTL_SECONDS, UexApiError


def test_concurrent_requests_dedupe():
    """Concurrent identical requests should share one network call."""
    client = UexApiClient("https://api.example.com/")
    call_count = 0
    results = []
    errors = []

    def mock_do_get(endpoint, params):
        nonlocal call_count
        call_count += 1
        time.sleep(0.1)  # Simulate network latency
        return [{"id": 1, "name": "test"}]

    client._do_get = mock_do_get

    def make_request():
        try:
            result = client.get("commodities")
            results.append(result)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=make_request) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert call_count == 1, f"Expected 1 network call, got {call_count}"
    assert len(results) == 5, f"Expected 5 results, got {len(results)}"
    assert len(errors) == 0, f"Unexpected errors: {errors}"
    assert all(r == [{"id": 1, "name": "test"}] for r in results)
    print("✓ test_concurrent_requests_dedupe passed")


def test_ttl_cache():
    """Rapid sequential calls should hit the cache."""
    client = UexApiClient("https://api.example.com/")
    call_count = 0

    def mock_do_get(endpoint, params):
        nonlocal call_count
        call_count += 1
        return [{"id": call_count}]

    client._do_get = mock_do_get

    result1 = client.get("commodities")
    result2 = client.get("commodities")

    assert call_count == 1, f"Expected 1 network call, got {call_count}"
    assert result1 == result2, "Cache should return same result"
    print("✓ test_ttl_cache passed")


def test_ttl_cache_expires():
    """Cache should expire after TTL."""
    client = UexApiClient("https://api.example.com/")
    call_count = 0

    def mock_do_get(endpoint, params):
        nonlocal call_count
        call_count += 1
        return [{"id": call_count}]

    client._do_get = mock_do_get

    result1 = client.get("commodities")
    time.sleep(DEDUPE_TTL_SECONDS + 0.1)
    result2 = client.get("commodities")

    assert call_count == 2, f"Expected 2 network calls after TTL, got {call_count}"
    assert result1 == [{"id": 1}]
    assert result2 == [{"id": 2}]
    print("✓ test_ttl_cache_expires passed")


def test_different_params_not_dedupe():
    """Different params should produce different requests."""
    client = UexApiClient("https://api.example.com/")
    call_count = 0

    def mock_do_get(endpoint, params):
        nonlocal call_count
        call_count += 1
        return [{"id": call_count, "params": params}]

    client._do_get = mock_do_get

    result1 = client.get("commodities", {"system": "Stanton"})
    result2 = client.get("commodities", {"system": "Pyro"})

    assert call_count == 2, f"Different params should not dedupe, got {call_count} calls"
    print("✓ test_different_params_not_dedupe passed")


def test_concurrent_error_shared():
    """Concurrent callers should share the same error from a failed request."""
    client = UexApiClient("https://api.example.com/")
    call_count = 0
    errors = []

    def mock_do_get(endpoint, params):
        nonlocal call_count
        call_count += 1
        time.sleep(0.1)  # Simulate network latency
        raise UexApiError("Test error")

    client._do_get = mock_do_get

    def make_request():
        try:
            client.get("commodities")
        except UexApiError as e:
            errors.append(e)

    threads = [threading.Thread(target=make_request) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert call_count == 1, f"Expected 1 network call even on error, got {call_count}"
    assert len(errors) == 5, f"All callers should get error, got {len(errors)}"
    print("✓ test_concurrent_error_shared passed")


def test_sequential_errors_not_cached():
    """Sequential errors should NOT be cached (they might be transient)."""
    client = UexApiClient("https://api.example.com/")
    call_count = 0

    def mock_do_get(endpoint, params):
        nonlocal call_count
        call_count += 1
        raise UexApiError("Test error")

    client._do_get = mock_do_get

    for _ in range(3):
        try:
            client.get("commodities")
        except UexApiError:
            pass

    assert call_count == 3, f"Sequential errors should retry, got {call_count} calls"
    print("✓ test_sequential_errors_not_cached passed")


def run():
    """Run all tests."""
    test_concurrent_requests_dedupe()
    test_ttl_cache()
    test_ttl_cache_expires()
    test_different_params_not_dedupe()
    test_concurrent_error_shared()
    test_sequential_errors_not_cached()
    print("\nAll API client dedupe tests passed!")


if __name__ == "__main__":
    run()
