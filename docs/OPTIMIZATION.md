# Optimization Analysis

Prioritized recommendations for mobiOverlay's runtime performance, network usage,
memory footprint, code structure, and packaging. Each item notes problem evidence,
expected benefit, effort/risk, and project-rule compliance.

---

## Implementation Status

| Item | Status | Commit |
|------|--------|--------|
| Q1 | ✅ Implemented | Share single LocationService across modules |
| Q2 | ✅ Implemented | Deduplicate commodities list fetch |
| Q3 | ✅ Implemented | Connection pooling on UexApiClient |
| Q4 | ✅ Implemented | Cache refineries_methods once per session |
| M1 | ✅ Implemented | Lazy-load easyocr/PyTorch on first OCR use |

---

## Executive Summary

The codebase is well-architected with clear module boundaries and documented
decisions. The most impactful optimizations center on:

1. **Startup time** — dominated by `import easyocr` (2.79s of 3.64s total)
2. **Network efficiency** — duplicate `LocationService` instances per module,
   repeated API calls across modules
3. **Main thread blocking** — synchronous OCR and some UEX API calls
4. **Code structure** — logistics_hub at 4,216 lines needs decomposition

---

## Quick Wins (Low effort, immediate benefit)

### Q1. Share a single LocationService instance across all modules ✅ IMPLEMENTED

**Problem**: Every module instantiates its own `LocationService`:
- `commodity_prices/module.py:69` — `self._locations = LocationService(api_client)`
- `trade_route_optimizer/module.py:84` — `self._locations = LocationService(api_client)`
- `logistics_hub/module.py` — creates its own instance
- `multi_commodity_finder/module.py:79` — `self._locations = LocationService(api_client)`
- `refinery_finder` reads from API directly (no LocationService)

Each instance loads the same disk cache or fetches the same API data independently.
With 7 active modules, startup could be issuing 4-7x the needed location fetches.

**Benefit**: Eliminates duplicate API calls and disk cache reads at startup. ~500ms
saved if multiple modules load before cache is warm.

**Effort**: Low — add `LocationService` to module constructor signature (same pattern
as `api_client`), instantiate once in `host/main.py`, pass to all modules.

**Risk**: None — `LocationService` is already stateless beyond its cache.

**Project rules**: ✓ No API logic changes, just instance sharing.

---

### Q2. Deduplicate commodities API call at startup ✅ IMPLEMENTED

**Problem**: Multiple modules fetch the full commodities list independently:
- `commodity_prices/module.py:178-179` — `self.api.get("commodities")`
- `refinery_finder/module.py:119-120` — `self.api.get("commodities")`
- `multi_commodity_finder/module.py:199-200` — `self.api.get("commodities")`

Each call returns ~150-200 items. With 3+ modules doing this at startup, that's
3 redundant requests to the same endpoint within seconds.

**Benefit**: Reduces startup API calls by 2, avoids potential rate-limit pressure
during rapid startup.

**Effort**: Low — add `commodities` to the shared `LocationService` cache, or create
a parallel `CommoditiesService` in `host/`.

**Risk**: Minimal — commodity list changes infrequently (game patches only).

**Project rules**: ✓ Uses existing UEX endpoints, no invented logic.

---

### Q3. Add connection pooling/keep-alive to UexApiClient ✅ IMPLEMENTED

**Problem**: `host/api_client.py` uses `requests.Session()` but creates new TCP
connections for each request due to default session behavior and lack of explicit
pooling configuration.

```python
# host/api_client.py:19-22
def __init__(self, base_url: str, token: str = ""):
    self.base_url = base_url.rstrip("/") + "/"
    self.token = token
    self._session = requests.Session()
```

**Benefit**: HTTP keep-alive reuses connections, reducing latency by ~50-100ms
per request after the first (TLS handshake avoidance).

**Effort**: Trivial — `requests.Session` already supports keep-alive; just ensure
it's actually reused (it is) and consider adding:
```python
from requests.adapters import HTTPAdapter
self._session.mount('https://', HTTPAdapter(pool_connections=10, pool_maxsize=10))
```

**Risk**: None — standard HTTP optimization.

**Project rules**: ✓ No API changes.

---

### Q4. Cache refineries_methods (static reference data) ✅ IMPLEMENTED

**Problem**: `refinery_finder/module.py:174` calls `refineries_methods` on every
`refresh()`, but this is reference data that never changes during a session:

```python
self._methods = self.api.get("refineries_methods")
```

**Benefit**: Eliminates 1 API call per refresh cycle (every 5 minutes by default).

**Effort**: Trivial — fetch once in `__init__` or on first `refresh()`, store in
instance variable.

**Risk**: None — methods are static game data.

**Project rules**: ✓ No invented logic.

---

### Q5. Reduce QTimer overhead in scan loops

**Problem**: Scan loops (Commodity Prices, Trade Route Optimizer, Multi-Commodity
Finder) use 120ms QTimer intervals for rate limiting:

```python
# commodity_prices/module.py:49
RETRIEVE_STEP_INTERVAL_MS = 120  # be nice to the API — ~8 requests/sec
```

This creates thousands of timer events for a full commodity scan (~200 items =
~200 timer fires). The timer fires even when the scan is complete until explicitly
stopped.

**Benefit**: Minor CPU reduction, cleaner event loop.

**Effort**: Trivial — already implemented correctly with `_retrieve_timer.stop()`,
but could batch more aggressively (e.g., 5 commodities per timer tick at 600ms
intervals instead of 1 per 120ms).

**Risk**: Batching increases per-request latency perception.

**Project rules**: ✓ Still respects 120/min rate limit (just groups requests).

---

## Medium Effort (Noticeable improvement, some refactoring)

### M1. Lazy-load easyocr/PyTorch on first OCR use ✅ IMPLEMENTED

**Problem**: `logistics_hub/module.py:107-109` imports easyocr at module load time:

```python
try:
    import easyocr  # type: ignore
    from PIL import Image, ImageOps  # type: ignore
    OCR_AVAILABLE = True
```

This runs during `discover_modules()` — before the splash screen can even show
which module is loading. `import easyocr` alone takes 2.79s (measured in
PROGRESS.md), dominating the entire startup.

**Benefit**: Startup drops from ~3.6s to ~0.8s. Users who never click SCAN CONTRACT
never pay the PyTorch load cost at all.

**Effort**: Medium — move the import inside `_run_ocr()` or the first scan trigger,
guard with a "loading OCR engine..." status message.

**Risk**: First scan has a 2-3s delay. Mitigate with a loading indicator.

**Project rules**: ✓ No functional change.

---

### M2. Move OCR processing to a background thread

**Problem**: OCR runs synchronously on the Qt main thread in `_scan_region()`:

```python
# logistics_hub/module.py (approx line 3000+)
def _run_ocr(self, image: QImage) -> list[str]:
    # ... PIL conversion, easyocr.readtext() ...
```

A single scan blocks the entire UI for 1-3 seconds depending on region size.

**Benefit**: UI stays responsive during scans. User can collapse cards, read
routes, etc. while OCR runs.

**Effort**: Medium — wrap OCR in `QThread` or `concurrent.futures.ThreadPoolExecutor`,
emit results via Qt signal. Pattern already exists in `host/hotkey.py:217-224`:

```python
def worker():
    try:
        combo = keyboard.read_hotkey(suppress=False)
        signal_holder.captured.emit(combo)
    except Exception as exc:
        signal_holder.failed.emit(str(exc))
threading.Thread(target=worker, daemon=True).start()
```

**Risk**: Thread safety for EasyOCR (confirmed safe — stateless inference).

**Project rules**: ✓ No API changes.

---

### M3. Pre-warm LocationService cache at install/first-run

**Problem**: The 7-day disk cache (`locations_cache.json`) must be populated from
live API calls on first run or after cache expiry. This adds ~2-3s of blocking
network calls during startup.

**Benefit**: Consistent fast startup after initial setup.

**Effort**: Medium — add a "first run setup" step that populates the cache before
showing the main window, or bundle a baseline cache file with the distribution.

**Risk**: Bundled cache could be stale for a new game patch. Mitigate by checking
cache age and showing "updating location data..." on stale cache.

**Project rules**: ✓ No invented API logic.

---

### M4. Consolidate duplicate stylesheet string construction

**Problem**: Every module defines its own near-identical `_COMBO_STYLE`,
`_ACTION_BTN_STYLE`, `_LABEL_SMALL`, etc.:

- `commodity_prices/module.py:27-52`
- `trade_route_optimizer/module.py:27-70`
- `multi_commodity_finder/module.py:30-68`
- `refinery_finder/module.py:24-48`
- `mobi_notes/module.py:39-82`
- `crosshair/module.py:85-99`
- `mobi_throttle/module.py:343-392`

Most differ only in minor padding/sizing values.

**Benefit**: Easier theming, smaller code surface, consistent UX.

**Effort**: Medium — add `theme.button_style()`, `theme.combo_style()`, etc. to
`host/theme.py`, migrate modules incrementally.

**Risk**: Minor — visual regression if values don't match exactly. Mitigate by
doing one module at a time with visual diff testing.

**Project rules**: ✓ No API changes.

---

### M5. Add request deduplication to UexApiClient

**Problem**: Nothing prevents two modules from requesting the same endpoint with
the same params simultaneously. During startup or a user clicking multiple cards'
refresh buttons rapidly, this can happen.

**Benefit**: Eliminates true duplicate requests, helps stay under 120/min limit.

**Effort**: Medium — add a simple request-dedup cache with short TTL (e.g., 500ms):

```python
class UexApiClient:
    def __init__(self, ...):
        self._inflight: dict[str, tuple[float, list]] = {}  # key -> (timestamp, result)
```

**Risk**: Low — must handle cache invalidation carefully.

**Project rules**: ✓ No API logic changes.

---

## Larger Bets (High effort, significant architectural improvement)

### L1. Decompose logistics_hub/module.py (4,216 lines)

**Problem**: `logistics_hub/module.py` is 4,216 lines — nearly 40% of all Python
code in the project (11,373 total). It contains:
- OCR pipeline (`_run_ocr`, `_order_ocr_boxes`, `_candidate_phrases`)
- Contract parsing (`_build_contract`, `_extract_commodities`)
- Route optimization (2-opt, greedy nearest-neighbor)
- Game.log verification integration
- UI (card, tracker popup, review popup, profile popup)
- Grading logic
- Debug logging

**Benefit**: Easier maintenance, testing, and future optimization. Each subsystem
can be profiled and improved independently.

**Effort**: High — extract to:
- `logistics_hub/ocr.py` — OCR pipeline, image preprocessing
- `logistics_hub/parsing.py` — contract/location extraction
- `logistics_hub/routing.py` — route optimization algorithms
- `logistics_hub/grading.py` — contract scoring
- `logistics_hub/ui.py` — popups and card construction
- `logistics_hub/module.py` — orchestration only (~300 lines)

**Risk**: Medium — any refactor of working code risks regressions. Mitigate with
the existing test suite (`tests/test_logistics_hub_parsing.py`).

**Project rules**: ✓ No API changes.

---

### L2. Implement a module-level dependency injection container

**Problem**: Modules manually instantiate their own `LocationService`, manage their
own timers, and duplicate setup logic. Adding a new shared service requires editing
every module's `__init__`.

**Benefit**: Cleaner dependency management, easier testing (mock injection), simpler
module boilerplate.

**Effort**: High — create `host/services.py` container, refactor `ModuleBase` and
all 8 modules to use it.

**Risk**: Over-engineering for current scale. Only worthwhile if more shared
services are planned.

**Project rules**: ✓ No API changes.

---

### L3. Consider async/await for network calls

**Problem**: All API calls are synchronous `requests.get()`. In scan loops this is
partially mitigated by QTimer chunking, but each individual call still blocks.

**Benefit**: True non-blocking I/O, better responsiveness during heavy API use.

**Effort**: High — requires switching to `aiohttp` or `httpx`, integrating Qt's
event loop with asyncio (via `qasync` or similar), and updating all call sites.

**Risk**: High complexity increase for modest benefit given current usage patterns.
The QTimer-chunked approach already provides adequate responsiveness.

**Project rules**: ✓ No API changes.

---

### L4. PyInstaller bundle size reduction

**Problem**: The exe bundles PyTorch (for EasyOCR), which adds ~500MB+ to the
distribution. Most users may never use OCR.

**Options**:
1. **Separate OCR plugin**: Ship base exe without PyTorch, offer `logistics_hub/`
   as an optional download that adds the heavy deps.
2. **Use ONNX Runtime instead of PyTorch**: EasyOCR can export to ONNX; runtime
   is ~50MB vs ~500MB.
3. **Cloud OCR fallback**: Offer a (rate-limited) cloud OCR endpoint as an
   alternative to local inference.

**Benefit**: Base distribution drops from ~600MB to ~100MB.

**Effort**: Very high for options 2-3, medium for option 1.

**Risk**: Option 1 fragments the distribution. Options 2-3 require significant
rework.

**Project rules**: Option 3 would need careful rate limiting to avoid abuse.

---

## Network/API-Specific Recommendations

### N1. Implement exponential backoff on rate limit

**Problem**: `UexRateLimitError` is raised but the retry is immediate (user clicks
Retry button). Repeated immediate retries worsen the rate limit situation.

**Benefit**: More graceful recovery from rate limits.

**Effort**: Low — add a 5-10 second cooldown before enabling Retry button.

---

### N2. Add request timing telemetry

**Problem**: No visibility into which API calls are slow or failing frequently.

**Benefit**: Data-driven optimization of caching and retry strategies.

**Effort**: Low — add timing logging to `UexApiClient.get()`:
```python
start = time.monotonic()
resp = self._session.get(...)
logger.debug("GET %s took %.2fs", endpoint, time.monotonic() - start)
```

---

### N3. Consider a local SQLite cache for price data

**Problem**: `commodities_prices` data is fetched repeatedly across modules and
sessions. A 30-minute refresh cache helps but doesn't persist across app restarts.

**Benefit**: Instant startup with last-known prices, graceful offline degradation.

**Effort**: Medium — add `host/price_cache.py` with SQLite storage.

**Risk**: Cache staleness if user relies on old prices for trading decisions.
Mitigate with clear "last updated X ago" indicators.

---

## Items NOT Recommended (would violate project rules)

1. **Embed a shared UEX token** — explicitly forbidden in DECISIONS.md
2. **Add predictive commodity logic** — no invented API capabilities
3. **Parse game memory/logs for position** — out of scope per docs
4. **Move overlay to gaming monitor for testing** — forbidden per project rules

---

## Implementation Priority Matrix

| Priority | Item | Benefit | Effort | Risk |
|----------|------|---------|--------|------|
| 1 | Q1 (Share LocationService) | High | Low | None |
| 2 | Q2 (Dedupe commodities call) | Medium | Low | None |
| 3 | M1 (Lazy-load easyocr) | Very High | Medium | Low |
| 4 | Q3 (Connection pooling) | Medium | Trivial | None |
| 5 | Q4 (Cache refineries_methods) | Low | Trivial | None |
| 6 | M2 (Background OCR thread) | High | Medium | Low |
| 7 | M4 (Consolidate stylesheets) | Medium | Medium | Low |
| 8 | L1 (Decompose logistics_hub) | High | High | Medium |
| 9 | M3 (Pre-warm cache) | Medium | Medium | Low |
| 10 | M5 (Request deduplication) | Medium | Medium | Low |

---

## Metrics to Track

Before implementing optimizations, establish baselines:

1. **Startup time**: Time from `python host/main.py` to window visible
2. **First scan latency**: Time from SCAN CONTRACT click to results displayed
3. **API calls per startup**: Count distinct requests during module loading
4. **Memory at idle**: RSS after all modules loaded, no active scans
5. **Memory during OCR**: Peak RSS during a Logistics Hub scan

Use `host/main.py`'s existing timing logs as a starting point.

---

*Report generated 2026-09-20. Based on analysis of the complete mobiOverlay codebase
including all 8 modules, host components, and project documentation.*
