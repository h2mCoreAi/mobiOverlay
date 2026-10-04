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
| M2 | ✅ Implemented | Background OCR thread + thin OCR extract to `modules/logistics_hub/ocr.py` |
| M5 | ✅ Implemented | In-flight/short-TTL request deduplication in UexApiClient |
| M3 | ✅ Implemented | Stale location cache is served at once and refreshed on a worker thread (`ensure_loaded(background_refresh_stale=True)`); only a first run or schema bump still blocks |
| N1 | ✅ Implemented | Rate-limit errors disable Retry for 8s with a countdown (`Card.set_error(cooldown_s=)`) |
| N2 | ✅ Implemented | `UexApiClient` logs per-request timing at DEBUG |
| M4 | ✅ Implemented | Shared `row_style`, `text_style`, `field_style`, `label_small`, `timestamp_style`, `action_btn_style` in `host/theme.py`; every migrated style checked equivalent to the original. One-off button styles (icon/nudge/stepper) stay local |

---

## Executive Summary

The codebase is well-architected with clear module boundaries and documented
decisions. The most impactful optimizations center on:

1. **Startup time** — dominated by `import easyocr` (2.79s of 3.64s total)
2. **Network efficiency** — duplicate `LocationService` instances per module,
   repeated API calls across modules
3. **Main thread blocking** — synchronous OCR and some UEX API calls
4. **Code structure** — logistics_hub at 4,350 lines needs decomposition

---

## Quick Wins (Low effort, immediate benefit)

### Q1. Share a single LocationService instance across all modules ✅ IMPLEMENTED

**Was**: Every module instantiated its own `LocationService`, each loading the
same disk cache or fetching the same API data independently — with multiple
modules active, startup issued several times the needed location fetches.

**Fixed**: `LocationService` is now created once in `host/main.py` and passed
to every module alongside `api_client`, the same pattern used for other
shared services.

**Benefit**: Eliminates duplicate API calls and disk cache reads at startup.

**Project rules**: ✓ No API logic changes, just instance sharing.

---

### Q2. Deduplicate commodities API call at startup ✅ IMPLEMENTED

**Was**: Several modules independently fetched the full commodities list
(`commodity_prices`, `refinery_finder`, `multi_commodity_finder`), each a
redundant request to the same endpoint within seconds of startup.

**Fixed**: `LocationService.commodities()` (`host/locations.py`) fetches the
list once per session. Commodity Prices and Multi-Commodity Finder read it
through `visible_commodity_names()`; Refinery Finder through
`raw_commodities()`. M5 deduplication is a separate change.

**Benefit**: Reduces startup API calls, avoids potential rate-limit pressure
during rapid startup.

**Project rules**: ✓ Uses existing UEX endpoints, no invented logic.

---

### Q3. Add connection pooling/keep-alive to UexApiClient ✅ IMPLEMENTED

**Was**: `requests.Session()` with no explicit pooling configuration.

**Fixed**:
```python
from requests.adapters import HTTPAdapter
self._session.mount('https://', HTTPAdapter(pool_connections=10, pool_maxsize=10))
```

**Benefit**: HTTP keep-alive reuses connections, reducing latency by ~50-100ms
per request after the first (TLS handshake avoidance).

**Project rules**: ✓ No API changes.

---

### Q4. Cache refineries_methods (static reference data) ✅ IMPLEMENTED

**Was**: `refinery_finder/module.py` called `refineries_methods` on every
`refresh()`, re-fetching static reference data that never changes during a
session.

**Fixed**: Fetched once, cached in an instance variable.

**Benefit**: Eliminates 1 API call per refresh cycle (every 5 minutes by default).

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

**Was**: `logistics_hub/module.py` imported `easyocr` at module load time, during
`discover_modules()` — before the splash screen could even show which module
was loading. `import easyocr` alone took 2.79s (measured in HISTORY.md),
dominating the entire startup.

**Fixed**: The import moved inside the first scan trigger, with a "loading OCR
engine..." status message while it loads.

**Benefit**: Startup drops from ~3.6s to ~0.8s. Users who never click SCAN CONTRACT
never pay the PyTorch load cost at all.

**Project rules**: ✓ No functional change.

---

### M2. Move OCR processing to a background thread ✅ IMPLEMENTED

**Was**: OCR ran synchronously on the Qt main thread, blocking the entire
UI for 1-3 seconds during each scan.

**Solution implemented**: Uses a plain `threading.Thread` (NOT QThread) for
inference, with a `_OcrSignalBridge` QObject to marshal results back to the
main thread via Qt signals.

**Critical design constraint**: `easyocr.Reader()` MUST be created on the main
thread. Creating it inside a QThread crashes Qt6Core.dll on Windows due to
PyTorch/OpenMP initialization conflicts with Qt's threading model. The first
scan blocks briefly (~2.8s) while loading the Reader; subsequent scans run
inference in the background with full UI responsiveness.

Pure OCR helpers extracted to `modules/logistics_hub/ocr.py`:
- `order_ocr_boxes()` — column-aware reading order
- `preprocess_image()` — grayscale, upscale, autocontrast
- `run_ocr()` — EasyOCR inference wrapper

This is a thin slice (only what M2 needs), not the full L1 decomposition.

**Additional fix**: `_pixmap_to_pil()` now uses `bytearray(qimg.bits())` to
make a full copy of image bytes before the QImage goes out of scope —
`QImage.bits()` returns a view that becomes invalid after garbage collection.

**Benefit**: UI stays responsive during scans (after first-scan Reader load).
User can collapse cards, move the overlay, etc. while OCR runs.

**Risk**: Thread safety confirmed — `Reader.readtext()` is stateless inference
over numpy arrays, safe from any thread. Only Reader construction is unsafe
in non-main threads.

**Project rules**: ✓ No API logic changes.

---

### M3. Pre-warm LocationService cache at install/first-run ✅ IMPLEMENTED

**Fixed (stale-while-revalidate instead of a bundled cache)**: an expired but
same-version `locations_cache.json` is loaded immediately and refreshed from
UEX by `LocationService.refresh_in_background()`. The fetch builds its result
without touching shared state (`_fetch_snapshot()`) and swaps it in only when
complete, so a failed or partial refresh keeps the older copy. A bundled
baseline cache was rejected: it would ship stale data for each new patch. A
true first run (no cache) and a schema bump (`CACHE_VERSION`) still fetch
synchronously behind the splash screen.

**Original problem notes**:

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

### M4. Consolidate duplicate stylesheet string construction ✅ IMPLEMENTED

**Done**: styles that were byte-identical across modules now live in
`theme.label_small()`, `theme.timestamp_style()` and `theme.action_btn_style()`
(functions, since they read `FONT_SCALE` set after import). Modules keep their
`_NAME = theme.fn()` constants. Remaining variants differ in padding/size and
need visual checks to merge.

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

### M5. Add request deduplication to UexApiClient ✅ IMPLEMENTED

**Was**: Nothing prevented duplicate identical GET requests when multiple
modules refreshed at once (startup, or user clicking several Refresh buttons).

**Fixed**: Added two deduplication mechanisms to `UexApiClient.get()`:
1. **In-flight sharing**: Concurrent calls for the same endpoint+params share a
   single `Future`. Only one HTTP request fires; others wait on `future.result()`.
2. **Short-TTL cache**: Completed results are reused for 2 seconds
   (`DEDUPE_TTL_SECONDS`), so rapid sequential calls hit the cache.

Cache key: `f"{endpoint}|{sorted_params}"`. Errors are cached too (re-raised to
waiting callers).

**Benefit**: Eliminates true duplicate requests, helps stay under 120/min limit.

**Risk**: Low — lock held briefly around dict lookups; actual network call runs
outside the lock.

**Project rules**: ✓ No API logic changes, no behavior change for unique calls.

---

## Larger Bets (High effort, significant architectural improvement)

### L1. Decompose logistics_hub/module.py (4,350 lines)

**Problem**: `logistics_hub/module.py` is 4,350 lines — nearly 40% of all Python
code in the project. It contains:
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

**Problem**: The exe bundles PyTorch (for EasyOCR), which adds ~250MB+ to the
distribution (shipped exe is ~333MB total). Most users may never use OCR.

**Options**:
1. **Separate OCR plugin**: Ship base exe without PyTorch, offer `logistics_hub/`
   as an optional download that adds the heavy deps.
2. **Use ONNX Runtime instead of PyTorch**: EasyOCR can export to ONNX; that
   runtime is ~50MB, against the PyTorch portion of the ~333MB exe.
3. **Cloud OCR fallback**: Offer a (rate-limited) cloud OCR endpoint as an
   alternative to local inference.

**Benefit**: Base distribution drops from ~333MB to well under 100MB.

**Effort**: Very high for options 2-3, medium for option 1.

**Risk**: Option 1 fragments the distribution. Options 2-3 require significant
rework.

**Project rules**: Option 3 would need careful rate limiting to avoid abuse.

---

## Network/API-Specific Recommendations

### N1. Implement exponential backoff on rate limit ✅ IMPLEMENTED (fixed 8s cooldown, not exponential)

**Problem**: `UexRateLimitError` is raised but the retry is immediate (user clicks
Retry button). Repeated immediate retries worsen the rate limit situation.

**Benefit**: More graceful recovery from rate limits.

**Effort**: Low — add a 5-10 second cooldown before enabling Retry button.

---

### N2. Add request timing telemetry ✅ IMPLEMENTED (DEBUG log in `UexApiClient._do_get`)

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

Items already shipped (Q1-Q4, M1, M2, M5 — see Implementation Status above)
are omitted below; this matrix only orders what's still open.

| Priority | Item | Benefit | Effort | Risk |
|----------|------|---------|--------|------|
| 1 | L1 (Decompose logistics_hub) | High | High | Medium |
| 3 | M4 remainder (per-module style variants) | Low | Medium | Low |

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
