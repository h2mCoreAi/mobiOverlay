"""Tests for host/price_cache.py (SQLite-backed key/value cache).

No Qt, no network:
    python tests/test_price_cache.py
"""
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from host.price_cache import PriceCache


def _cache():
    d = Path(tempfile.mkdtemp())
    return d, PriceCache(d / "price_cache.sqlite3")


def test_roundtrip_and_overwrite() -> int:
    d, c = _cache()
    assert c.load("k") is None, "empty cache should miss"
    payload = {"Gold": [{"id_terminal": 1, "price_buy": 10.5}], "Iron": []}
    before = time.time()
    assert c.save("k", payload)
    fetched_at, got = c.load("k")
    assert got == payload and before - 1 <= fetched_at <= time.time() + 1
    assert c.save("k", {"x": 1}, fetched_at=123.0)
    assert c.load("k") == (123.0, {"x": 1}), "second save should replace the first"
    assert c.load("other") is None
    return 5


def test_corrupt_file_is_quarantined_and_cache_recovers() -> int:
    d, c = _cache()
    c.path.write_bytes(b"this is not a sqlite database" * 50)
    assert c.load("k") is None, "unreadable cache must read as a miss, not raise"
    assert c.save("k", [1, 2, 3]), "cache should rebuild after quarantining"
    assert c.load("k")[1] == [1, 2, 3]
    assert len(list(d.glob("price_cache.sqlite3.corrupt-*"))) == 1, "bad file wasn't preserved"
    return 3


def test_unserializable_payload_returns_false() -> int:
    d, c = _cache()
    assert c.save("k", {"x": object()}) is False
    assert c.load("k") is None
    return 2


def test_usable_from_several_threads() -> int:
    d, c = _cache()
    errors = []

    def work(i):
        try:
            for j in range(10):
                assert c.save(f"k{i}", {"n": j})
                assert c.load(f"k{i}")[1]["n"] == j
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors, errors
    return 1


def run() -> int:
    checks = 0
    for t in (test_roundtrip_and_overwrite, test_corrupt_file_is_quarantined_and_cache_recovers,
              test_unserializable_payload_returns_false, test_usable_from_several_threads):
        checks += t()
        print(f"[PASS] {t.__name__}")
    print(f"\n{checks}/{checks} price cache checks passed")
    return checks


if __name__ == "__main__":
    run()
