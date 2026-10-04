"""Logistics Hub – OCR driven hauling mission board helper.

Captures a user‑selected region of the screen (over the in‑game mission
board), runs OCR against the captured image, and turns each scan into a
**contract** (one or more pickups, one or more drop‑offs, and a reward —
real contracts use both "DROP OFF LOCATIONS (ANY ORDER)" and "PICK UP
LOCATIONS (ANY ORDER)" panels). Contracts accumulate across scans —
scanning a second mission board page adds to the list instead of replacing
it — so several contracts can be queued up before planning one combined
route across every pickup and drop-off.

The module lives entirely under ``modules/logistics_hub/`` and intentionally
does **not** use any host‑side screen‑capture or OCR helpers. All new
third‑party dependencies are declared in the local :file:`requirements.txt`
so the base project stays clean.

Chosen OCR engine: **easyocr** – permissively licensed (Apache 2.0)
and fully pip‑installable on Windows, which avoids making the user
install a separate Tesseract binary. The tradeoff is a much heavier
download (it pulls in PyTorch and torchvision), so it may take a few
seconds on first use.

Route optimization: OCR'd location text is resolved against the shared
Core location service (``host/locations.py`` — every module gets its own
``LocationService`` instance, backed by a session-cached, disk-persisted
index over UEX's ``terminals``/``space_stations``/``outposts``/``cities``
data) to find the real terminal/planet/system a location name refers to,
then a nearest-neighbour + 2-opt visiting order is planned using **real
UEX travel distance** (``LocationService.distance()`` — point-to-point
via ``terminals_distances`` when both stops are trade terminals, orbit-
to-orbit via ``orbits_distances`` otherwise, queried lazily and cached
per-session, never bulk-prefetched) rather than a guessed hierarchy tier.
A pair with no determinable real distance (missing orbit/system data, or
the distance endpoints themselves failing) falls back to a coarse same-
terminal/body/system/different-system tier scaled into the same rough
numeric range, so a fallback edge doesn't look artificially cheap next to
a real-distance one in the same route. A location that can't be resolved
against UEX data at all falls back further, to a text-similarity
heuristic, so the module still produces *something* usable, clearly
marked as unresolved.

The route always starts from the CURRENT LOCATION picker's selection (a
searchable combo over the same location data), not an arbitrary contract's
pickup — and never visits a drop-off before every pickup on its own
contract has been visited, since cargo can't be delivered before it's
been collected.
"""
import importlib.util
import json
import os
import sys
import threading
import time
import uuid
from datetime import datetime, timezone

# File-path imports, not `from modules.logistics_hub import ...` —
# `modules/` is not guaranteed to be an importable package once frozen (see
# host/module_loader.py's own docstring: modules ship external to the exe,
# not on sys.path as a package). Same mechanism the host uses to load this
# very file.
def _load_sibling(name: str, filename: str):
    """Load a sibling .py file by path and register it in sys.modules under
    `name` (so another sibling can find it without loading it twice)."""
    spec = importlib.util.spec_from_file_location(name, os.path.join(os.path.dirname(__file__), filename))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


gamelog_verify = _load_sibling("mobioverlay_logistics_hub_gamelog_verify", "gamelog_verify.py")

ocr_module = _load_sibling("mobioverlay_logistics_hub_ocr", "ocr.py")

from PySide6.QtCore import Qt, QRect, QRectF, QPoint, QTimer, Signal, QObject
from PySide6.QtGui import (
    QGuiApplication,
    QImage,
    QPainter,
    QPainterPath,
    QColor,
    QPen,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QCompleter,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizeGrip,
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from host import paths, theme
from host.locations import LocationService
from host.module_base import ModuleBase

import logging

logger = logging.getLogger("mobioverlay.logistics_hub")

# ---------------------------------------------------------------------------
# OCR dependencies are loaded lazily on first scan, not at module import time.
# `import easyocr` alone takes ~2.8s (loads PyTorch) — deferring it to first
# actual use cuts startup from ~3.6s to ~0.8s. Users who never click SCAN
# CONTRACT never pay the cost at all.
# ---------------------------------------------------------------------------
_ocr_modules: dict | None = None  # populated by _ensure_ocr_loaded()
_ocr_load_error: str | None = None  # set if import fails


def _ensure_ocr_loaded() -> bool:
    """Lazily import easyocr and PIL on first use. Returns True if available."""
    global _ocr_modules, _ocr_load_error
    if _ocr_modules is not None:
        return True
    if _ocr_load_error is not None:
        return False
    try:
        import easyocr  # type: ignore
        from PIL import Image, ImageOps  # type: ignore
        import numpy as np
        _ocr_modules = {
            "easyocr": easyocr,
            "Image": Image,
            "ImageOps": ImageOps,
            "np": np,
        }
        logger.info("OCR engine loaded successfully")
        return True
    except Exception as e:
        # Not just ImportError: a broken torch install in a frozen build
        # raises OSError (DLL load failed) here, which used to escape
        # _safe_scan() and leave the SCAN button disabled for good.
        _ocr_load_error = str(e)
        if getattr(sys, "frozen", False) and isinstance(e, ImportError):
            _ocr_load_error = (
                f"{e} (the lite build leaves the OCR engine out — "
                "use the full mobiOverlay.exe for contract scanning)"
            )
        logger.warning("OCR dependencies not available: %s", e)
        return False


class _OcrSignalBridge(QObject):
    """Signal bridge for marshaling OCR results from a background thread
    back to the Qt main thread.

    Unlike QThread, this uses a plain threading.Thread for the actual work,
    which avoids the Qt6Core.dll crash that occurs when easyocr/PyTorch/OpenMP
    initializes inside a QThread on Windows. The Reader is created on the
    main thread; only the stateless inference runs in the background.
    """
    finished = Signal(str)  # raw_text
    error = Signal(str)  # error message


COPY_ROUTE_CONFIRM_MS = 1500  # how long the COPY ROUTE button shows "COPIED" before reverting

DEBUG_LOG_FILENAME = "logistics_hub_debug.jsonl"  # always-on scan history, see docs/DECISIONS.md
# Separate from the debug log above — that one is a firehose of every
# scan (including rejected/duplicate ones) meant for debugging parsing;
# this one is a clean, append-only record of contracts you actually
# finished, meant for later analysis (session totals, aUEC/hour, etc.).
# See docs/DECISIONS.md, 2026-09-07.
COMPLETED_LOG_FILENAME = "logistics_hub_completed.jsonl"
# The debug log stores the full raw OCR text and route snapshot of every
# scan, forever. Past this size it's rotated to `<name>.1` (replacing any
# older rotation) so it can't grow without bound. The completed log is
# never rotated — it's the user's own record.
DEBUG_LOG_MAX_BYTES = 5 * 1024 * 1024

# Contract grading (score, Freight Manifest, ship/location compatibility key)
# lives in grading.py; its tunables are re-bound here for the Hauler Profile UI.
grading = _load_sibling("mobioverlay_logistics_hub_grading", "grading.py")
GRADE_CAP_ON_WARNING = grading.GRADE_CAP_ON_WARNING
CAPACITY_OVERFLOW_CAP = grading.CAPACITY_OVERFLOW_CAP
RISKY_SYSTEMS = grading.RISKY_SYSTEMS
DEFAULT_GRADING_THRESHOLDS = grading.DEFAULT_GRADING_THRESHOLDS

# Restricts what EasyOCR can output to characters that can actually appear
# in a contract panel — letters, digits, and every punctuation mark
# observed across this session's real captures (periods, commas, colons,
# semicolons, apostrophes/quotes, hyphens, slashes for "0/37", parens,
# brackets for "[BP]*", asterisks, underscores — a documented real OCR
# artifact standing in for a period — plus basic sentence punctuation).
# Restricting a classifier's output space to only valid characters can
# only remove wrong options, never introduce new ones — but an
# *incomplete* list could suppress a real, legitimate character, so this
# is deliberately generous rather than minimal. Empirically inconclusive
# in this session's own synthetic testing (no measurable difference on
# clean synthetic text — the real benefit is against genuine OCR
# hallucination artifacts, like a reward-icon glyph misread as a stray
# symbol, which synthetic text can't reproduce); needs a real scan to
# actually confirm, same as the earlier column-ordering change.
# Now extracted to ocr.py for background-thread use — kept here for
# backwards compatibility with any code that references it directly.
OCR_ALLOWLIST = ocr_module.OCR_ALLOWLIST

# Route ordering (greedy + 2-opt + Or-opt over real UEX distances) lives in
# routing.py, loaded by file path like the siblings above; the fallback-cost
# tiers are re-bound here for the debug-log code that reports edge sources.
routing = _load_sibling("mobioverlay_logistics_hub_routing", "routing.py")
COST_SAME_TERMINAL = routing.COST_SAME_TERMINAL
COST_SAME_BODY = routing.COST_SAME_BODY
COST_SAME_SYSTEM = routing.COST_SAME_SYSTEM
COST_DIFFERENT_SYSTEM = routing.COST_DIFFERENT_SYSTEM
COST_UNRESOLVED = routing.COST_UNRESOLVED


def _virtual_desktop_rect() -> QRect | None:
    """Return the union of all Qt screen geometries (multi‑monitor aware)."""
    screens = QGuiApplication.screens()
    if not screens:
        return None
    rect = screens[0].geometry()
    for sc in screens[1:]:
        rect = rect.united(sc.geometry())
    return rect


# Delegation to the extracted OCR module — kept here for backwards
# compatibility with any code that references it directly.
def _order_ocr_boxes(results: list, image_width: int) -> list[str]:
    """Reorder EasyOCR's `detail=1` results into reading order. Delegated to ocr.py."""
    return ocr_module.order_ocr_boxes(results, image_width)


# Pure contract-text parsing lives in parsing.py (same file-path import
# mechanism as above); the names are re-bound here so existing references
# (and tests/test_logistics_hub_parsing.py) keep working unchanged.
parsing = _load_sibling("mobioverlay_logistics_hub_parsing", "parsing.py")
_PICKUP_COMMODITY_RE = parsing._PICKUP_COMMODITY_RE
_DROPOFF_COMMODITY_RE = parsing._DROPOFF_COMMODITY_RE
_find_delivery_match = parsing._find_delivery_match
_complete_commodity_name = parsing._complete_commodity_name
_commodity_quantities = parsing._commodity_quantities
_extract_commodities = parsing._extract_commodities
_CARGO_UNKNOWN = parsing._CARGO_UNKNOWN
_cargo_label = parsing._cargo_label
_entry_scu = parsing._entry_scu
_all_commodity_names = parsing._all_commodity_names
_extract_reward = parsing._extract_reward
_total_reward = parsing._total_reward
_PHRASE_STOPWORDS = parsing._PHRASE_STOPWORDS
_DROPOFF_SECTION_RE = parsing._DROPOFF_SECTION_RE
_PICKUP_SECTION_RE = parsing._PICKUP_SECTION_RE
_PICKUP_HINT_RE = parsing._PICKUP_HINT_RE
_DROPOFF_HINT_RE = parsing._DROPOFF_HINT_RE
_candidate_phrases = parsing._candidate_phrases


# Popup widgets live in popups.py. Names are re-bound here for the card code
# below (and for the choice lists the Hauler Profile table shares).
popups = _load_sibling("mobioverlay_logistics_hub_popups", "popups.py")
_ReminderBanner = popups._ReminderBanner
_RegionSelector = popups._RegionSelector
_ReviewPopup = popups._ReviewPopup
_HaulerProfilePopup = popups._HaulerProfilePopup
PROFILE_GOAL_CHOICES = popups.PROFILE_GOAL_CHOICES
PROFILE_RISK_CHOICES = popups.PROFILE_RISK_CHOICES
PROFILE_TIME_CHOICES = popups.PROFILE_TIME_CHOICES
PROFILE_REGION_CHOICES = popups.PROFILE_REGION_CHOICES
DEFAULT_ACCEPT_REMINDER_SECONDS = popups.DEFAULT_ACCEPT_REMINDER_SECONDS




class LogisticsHubModule(ModuleBase):
    module_id = "logistics_hub"
    # Rich-text, styled like the main window's own wordmark (see
    # host/main_window.py's _TitleBar) — Card's title_label (host/card.py)
    # renders whatever it's given as HTML and no longer forces uppercase,
    # so this mixed-case branding survives intact.
    display_name = (
        f'<span style="color:{theme.TEXT_PRIMARY};">mobi</span>'
        f'<span style="color:{theme.ACCENT_CYAN};">Logistics</span>'
    )

    def __init__(self, api_client, config, locations):
        super().__init__(api_client, config, locations)
        # This module is on-demand only (SCAN CONTRACT) — the host's generic
        # periodic-refresh timer would otherwise call refresh() every
        # DEFAULT_REFRESH_SECONDS and re-OCR whatever's on screen at that
        # moment (desktop, chat, menus...), silently appending garbage
        # "contracts". 0 tells host/main.py to skip starting that timer for
        # this module; explicit user config can still override it.
        self.settings.setdefault("refresh_interval_seconds", 0)
        self._selector = None
        self._card_widget = None
        self._copy_route_revert_timer: QTimer | None = None
        self._route_popout: QWidget | None = None
        # Mirrored onto the Tracker popout's own banner too, if it's open
        # when a reminder fires — see `_reminder_banners()`. `None` means
        # no reminder is currently active.
        self._reminder_text: str | None = None
        self._popout_reminder_banner: QPushButton | None = None
        self._route_popout_layout: QVBoxLayout | None = None
        self._route_popout_opacity_slider: QSlider | None = None
        self._reader = None
        # Background OCR state (M2 optimization)
        self._ocr_running = False
        self._ocr_signal_bridge: _OcrSignalBridge | None = None
        # Shared Core service now provided by host (host/locations.py) —
        # self.locations is set in ModuleBase.__init__. Keep a private
        # alias for compatibility with existing code that uses
        # self._locations throughout this module.
        self._locations = self.locations
        self._location_choices: dict[str, dict] = {}  # display name -> terminal row, for the picker
        self._pending_scan: dict | None = None  # scanned, awaiting ACCEPT/REJECT in the review popup
        # Debug-log context for the currently-open review popup — set in
        # `refresh()`/`_show_review_popup()`, read back by
        # `_log_review_outcome()` when ACCEPT/REJECT is actually clicked
        # (which happens later, asynchronously, so it can't be logged in
        # the same call that shows the popup). See docs/DECISIONS.md,
        # 2026-09-07.
        self._pending_grade: tuple[int | None, str, bool] | None = None
        self._pending_unrated_names: list[str] = []
        self._pending_ratings_given: list[dict] = []
        # Both now real Qt.Window widgets (2026-09-07 fix, see _ReviewPopup/
        # _HaulerProfilePopup) — need an explicit reference held somewhere
        # or they're garbage-collected the instant the showing method
        # returns, since (unlike Qt.Popup) nothing else keeps one alive.
        self._review_popup: QWidget | None = None
        self._profile_popup: QWidget | None = None
        # A "node" is one stop to visit: (contract_index, "pickup"/"dropoff",
        # index within that role's list) — a contract can have several
        # pickups or several drop-offs (real panels use both DROP OFF
        # LOCATIONS (ANY ORDER) and PICK UP LOCATIONS (ANY ORDER)).
        self._route_order: list[tuple[int, str, int]] = []
        # host/main.py calls refresh() once automatically right after every
        # module's card is created (its "initial fetch"). For this module
        # that means OCR-ing whatever's on screen at the last saved region
        # before the user has touched anything — useless (and often wrong)
        # if the game isn't even open yet. Treat that first automatic call
        # as a no-op; only an explicit SCAN click or the opt-in auto-rescan
        # timer should trigger a real capture. This is a module-local
        # workaround, not a core change — main.py's shared startup-refresh
        # behavior is unchanged for every other module.
        self._started = False

    # ------------------------------------------------------------------
    # Card construction
    # ------------------------------------------------------------------
    def create_card(self, container):
        card = container.add_card(self.module_id, self.display_name)
        self._card_widget = card
        layout = card.body_layout

        # ---- current location picker ----------------------------------
        # The route planner needs a starting point — without one it can
        # only guess (previously it silently started from whichever
        # contract's pickup happened to be scanned first, which is only
        # right by coincidence). Same editable-combo-with-completer pattern
        # trade_route_optimizer uses for its terminal picker.
        location_row = QHBoxLayout()
        location_label = QLabel("LOCATION")
        location_label.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-family: {theme.FONT_MONO}; "
            f"font-size: {theme.fpx(9)}px; letter-spacing: 1px;"
        )
        location_row.addWidget(location_label)

        self._location_combo = QComboBox()
        self._location_combo.setEditable(True)
        self._location_combo.setInsertPolicy(QComboBox.NoInsert)
        self._location_combo.setStyleSheet(
            f"""
            QComboBox {{
                background: {theme.BG_VOID}; color: {theme.ACCENT_CYAN};
                border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px;
                padding: 4px 22px 4px 6px; font-family: "{theme.FONT_DISPLAY}"; font-weight: 700;
                font-size: {theme.fpx(11)}px;
            }}
            QComboBox::drop-down {{
                width: 18px; border: none;
            }}
            """
        )
        location_completer = QCompleter(self._location_combo.model(), self._location_combo)
        location_completer.setCaseSensitivity(Qt.CaseInsensitive)
        location_completer.setFilterMode(Qt.MatchContains)
        location_completer.setCompletionMode(QCompleter.PopupCompletion)
        self._location_combo.setCompleter(location_completer)
        # textActivated (not currentTextChanged) — same reasoning as
        # trade_route_optimizer's terminal combo: this one's editable/
        # searchable, so currentTextChanged would fire (and try to resolve
        # a location, replan, and error) on every keystroke.
        self._location_combo.textActivated.connect(self._on_location_selected)
        location_row.addWidget(self._location_combo, 1)
        layout.addLayout(location_row)

        # ---- action tabs (SCAN / SETUP) ------------------------------
        # Redesigned 2026-09-08 per user direction: five workflow buttons
        # plus three setup buttons in two flat rows had gotten noisy as the
        # card grew feature by feature this session. Grouped into tabs
        # instead — same buttons, same handlers, just organized: SCAN for
        # the things done every contract, SETUP for the things set up once
        # (or rarely revisited) per session. CONTRACTS/MANIFEST/ROUTE below
        # stay exactly as they were — this only touches the button rows.
        action_tabs = QTabWidget()
        action_tabs.setStyleSheet(
            f"""
            QTabWidget::pane {{
                border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px;
                top: -1px;
            }}
            QTabBar::tab {{
                background: {theme.BG_VOID}; color: {theme.TEXT_MUTED};
                border: 1px solid {theme.BORDER_FLAT}; border-bottom: none;
                border-top-left-radius: {theme.RADIUS}px; border-top-right-radius: {theme.RADIUS}px;
                padding: 4px 12px; margin-right: 2px;
                font-family: {theme.FONT_DISPLAY}; font-weight: 700;
                font-size: {theme.fpx(9)}px; letter-spacing: 1px;
            }}
            QTabBar::tab:selected {{
                background: {theme.BG_PANEL}; color: {theme.ACCENT_CYAN};
            }}
            """
        )
        # Card sizing depends on `card.apply_size()` re-running any time
        # visible content changes size (see its own docstring — this is
        # the same pattern collapse/error-state transitions already use);
        # a tab switch changes which row of buttons is visible/sized the
        # same way, so it needs the same nudge or the card can be left
        # sized for whichever tab happened to be active at creation.
        action_tabs.currentChanged.connect(lambda _index: card.apply_size())
        layout.addWidget(action_tabs)

        scan_tab = QWidget()
        scan_tab_layout = QVBoxLayout(scan_tab)
        scan_tab_layout.setContentsMargins(6, 6, 6, 6)

        setup_tab = QWidget()
        setup_tab_layout = QVBoxLayout(setup_tab)
        setup_tab_layout.setContentsMargins(6, 6, 6, 6)

        # ---- region status row --------------------------------------
        region_row = QHBoxLayout()
        self._region_label = QLabel("Region: not set")
        self._region_label.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-family: {theme.FONT_MONO}; "
            f"font-size: {theme.fpx(9)}px; letter-spacing: 1px;"
        )
        region_row.addWidget(self._region_label, 1)

        select_btn = QPushButton("SET SCAN AREA")
        select_btn.setStyleSheet(self._button_style())
        select_btn.clicked.connect(self._select_region)
        region_row.addWidget(select_btn)

        profile_btn = QPushButton("PROFILE")
        profile_btn.setToolTip(
            "Your ship + hauling preferences — set once, used to grade "
            "future scans. Doesn't affect parsing or routing."
        )
        profile_btn.setStyleSheet(self._button_style())
        profile_btn.clicked.connect(self._show_profile_popup)
        region_row.addWidget(profile_btn)

        # CLEAR LOG — added 2026-09-08 for testing the Game.log verify
        # feature: wiping logistics_hub_debug.jsonl used to mean closing
        # the app and deleting the file by hand between test scans. Only
        # ever touches the debug log (this scan's raw OCR/candidates/
        # resolution trace/gamelog_verify diagnostics) — never the
        # contract queue, config, or logistics_hub_completed.jsonl.
        clear_log_btn = QPushButton("CLEAR LOG")
        clear_log_btn.setToolTip(
            "Wipes logistics_hub_debug.jsonl (this scan's raw OCR text, "
            "candidates, resolution trace, and Game.log verify result). "
            "Does not touch your contract queue or completed-contracts log."
        )
        clear_log_btn.setStyleSheet(self._button_style())
        clear_log_btn.clicked.connect(self._clear_debug_log)
        region_row.addWidget(clear_log_btn)
        setup_tab_layout.addLayout(region_row)
        action_tabs.addTab(setup_tab, "SETUP")

        # ---- action row ---------------------------------------------
        action_row = QHBoxLayout()
        self._status_label = QLabel("Ready")
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet(
            f"color: {theme.TEXT_PRIMARY}; font-family: {theme.FONT_MONO}; "
            f"font-size: {theme.fpx(9)}px;"
        )
        action_row.addWidget(self._status_label, 1)

        self._scan_btn = QPushButton("SCAN CONTRACT")
        self._scan_btn.setToolTip(
            "Captures the region as one contract. Location phrases found in "
            "the text are checked against real UEX data — the first match "
            "becomes the pickup, the rest become drop-offs. Frame one "
            "mission's detail panel per scan."
        )
        self._scan_btn.setStyleSheet(self._button_style())
        self._scan_btn.clicked.connect(self._safe_scan)
        action_row.addWidget(self._scan_btn)

        self._copy_route_btn = QPushButton("COPY ROUTE")
        self._copy_route_btn.setToolTip("Copies the suggested route (and full contract details) to the clipboard as plain text.")
        self._copy_route_btn.setStyleSheet(self._button_style())
        self._copy_route_btn.clicked.connect(self._copy_route_to_clipboard)
        action_row.addWidget(self._copy_route_btn)

        # Re-parses every saved contract from its own stored OCR text and
        # replans the route — no rescan needed. Added 2026-09-05 so a
        # parsing/quantity fix can be picked up on contracts already sitting
        # in this session without CLEAR + rescanning them all from the game.
        reprocess_btn = QPushButton("REPROCESS")
        reprocess_btn.setToolTip(
            "Re-parses every saved contract from its own stored OCR text "
            "(locations + commodities) and replans the route — no rescan "
            "needed. Useful after a parsing fix."
        )
        reprocess_btn.setStyleSheet(self._button_style())
        reprocess_btn.clicked.connect(self._safe_reprocess)
        action_row.addWidget(reprocess_btn)

        # COMPLETE — added 2026-09-07 per user request, replacing "just
        # click CLEAR when done" with something that actually keeps a
        # record. Distinct from CLEAR on purpose: CLEAR stays the discard-
        # without-a-trace button (wrong scan, duplicate, mistake) so it
        # never has to second-guess whether a given contract was really
        # finished; COMPLETE only ever logs contracts you're explicitly
        # saying you delivered.
        complete_btn = QPushButton("COMPLETE")
        complete_btn.setToolTip(
            "Logs every contract currently in the queue as completed "
            "(reward, cargo, locations, the grade it scored when accepted) "
            "to logistics_hub_completed.jsonl, then clears the queue."
        )
        complete_btn.setStyleSheet(self._button_style())
        complete_btn.clicked.connect(self._complete_contracts)
        action_row.addWidget(complete_btn)

        # CLEAR is placed last, away from SCAN/COPY, since it's destructive
        # and the user has accidentally hit it reaching for the other two.
        clear_btn = QPushButton("CLEAR")
        clear_btn.setToolTip("Discards every contract in the queue without logging them as completed.")
        clear_btn.setStyleSheet(self._button_style())
        clear_btn.clicked.connect(self._clear_contracts)
        action_row.addWidget(clear_btn)
        scan_tab_layout.addLayout(action_row)
        # Inserted before SETUP (added above, when SETUP happened to be
        # built first) so SCAN — the tab used every contract — is the one
        # shown by default, not whichever tab construction order left last.
        action_tabs.insertTab(0, scan_tab, "SCAN")
        action_tabs.setCurrentWidget(scan_tab)

        # ---- accept reminder banner (hidden until needed) ---------------
        # Added 2026-09-08: if Game.log still hasn't confirmed a contract
        # ACCEPT_REMINDER_SECONDS after ACCEPT, this blinks until physically
        # clicked — a safety net for the easy-to-forget "accept it in-game
        # too" step, without ever touching game input itself. `_ReminderBanner`
        # (a QLabel subclass, not QPushButton — see its docstring, 2026-09-09
        # clipping fix) so any click on it — not just a precise target —
        # dismisses it, and the text actually wraps in a narrow popout.
        self._reminder_banner = _ReminderBanner(self._dismiss_accept_reminder)
        self._reminder_banner.setVisible(False)
        self._reminder_blink_timer = QTimer()
        self._reminder_blink_timer.setInterval(500)
        self._reminder_blink_timer.timeout.connect(self._toggle_reminder_blink)
        self._reminder_blink_on = False
        layout.addWidget(self._reminder_banner)

        # ---- contracts list (own scroll area — see 2026-09-04 DECISIONS ---
        # entry: this used to share one scroll area with the ROUTE section
        # below it, and a freshly-scanned contract could leave that shared
        # viewport scrolled into ROUTE instead, hiding CONTRACTS. Two
        # independent scroll areas means each keeps its own scroll position
        # and neither can push the other out of view.
        contracts_title_row = QHBoxLayout()
        self._contracts_title = QLabel("CONTRACTS")
        self._contracts_title.setStyleSheet(self._title_style())
        contracts_title_row.addWidget(self._contracts_title, 1)

        # Lives here (not next to the ROUTE title below) and is created
        # once rather than rebuilt on every _render_results call — it used
        # to be rebuilt inside the ROUTE section each render, which was
        # fragile (see DECISIONS.md 2026-09-04: a clear-loop bug orphaned
        # the old one on every second+ render, leaving a stale copy
        # floating at its last position on top of the new one).
        self._tracker_btn = QPushButton("TRACKER")
        self._tracker_btn.setStyleSheet(self._button_style())
        self._tracker_btn.clicked.connect(self._toggle_route_popout)
        self._tracker_btn.setVisible(False)
        contracts_title_row.addWidget(self._tracker_btn)
        layout.addLayout(contracts_title_row)

        # At-a-glance summary (total reward, peak cargo capacity needed) —
        # added 2026-09-05 after reviewing the card from a player's
        # perspective: everything else here needs scrolling through the
        # contract/route lists to answer "how much am I making" or "what
        # size cargo hold do I need for this run." Lives outside both
        # scroll areas so it's visible without touching either. Created
        # once, text set in `_render_results()`.
        self._summary_label = QLabel("")
        self._summary_label.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-family: {theme.FONT_MONO}; "
            f"font-size: {theme.fpx(9)}px; letter-spacing: 0.5px;"
        )
        layout.addWidget(self._summary_label)

        self._contracts_scroll = QScrollArea()
        self._contracts_scroll.setWidgetResizable(True)
        self._contracts_scroll.setStyleSheet(
            f"QScrollArea {{ background: transparent; border: 1px solid {theme.BORDER_FLAT}; "
            f"border-radius: {theme.RADIUS}px; }}"
        )
        self._contracts_widget = QWidget()
        self._contracts_layout = QVBoxLayout(self._contracts_widget)
        self._contracts_layout.setContentsMargins(8, 8, 8, 8)
        self._contracts_layout.setSpacing(4)
        self._contracts_scroll.setWidget(self._contracts_widget)
        self._contracts_scroll.setMinimumHeight(90)
        self._contracts_scroll.setMaximumHeight(160)
        layout.addWidget(self._contracts_scroll)

        # ---- freight manifest (running list of what's being hauled) -----
        # Added 2026-09-07 per user direction: a running total of every
        # commodity across all active contracts, so a duplicate — the same
        # freight picked up under two different contracts, which the game
        # makes very hard to tell apart once it's in the hold — is caught
        # by eye right after a scan, before it's a problem at the pickup
        # terminal. See docs/DECISIONS.md.
        manifest_title = QLabel("FREIGHT MANIFEST")
        manifest_title.setStyleSheet(self._title_style())
        layout.addWidget(manifest_title)

        self._manifest_scroll = QScrollArea()
        self._manifest_scroll.setWidgetResizable(True)
        self._manifest_scroll.setStyleSheet(
            f"QScrollArea {{ background: transparent; border: 1px solid {theme.BORDER_FLAT}; "
            f"border-radius: {theme.RADIUS}px; }}"
        )
        self._manifest_widget = QWidget()
        self._manifest_layout = QVBoxLayout(self._manifest_widget)
        self._manifest_layout.setContentsMargins(8, 8, 8, 8)
        self._manifest_layout.setSpacing(4)
        self._manifest_scroll.setWidget(self._manifest_widget)
        self._manifest_scroll.setMinimumHeight(60)
        self._manifest_scroll.setMaximumHeight(140)
        layout.addWidget(self._manifest_scroll)

        # ---- scrollable route list --------------------------------------
        self._results_scroll = QScrollArea()
        self._results_scroll.setWidgetResizable(True)
        self._results_scroll.setStyleSheet(
            f"QScrollArea {{ background: transparent; border: 1px solid {theme.BORDER_FLAT}; "
            f"border-radius: {theme.RADIUS}px; }}"
        )

        self._results_widget = QWidget()
        self._results_layout = QVBoxLayout(self._results_widget)
        self._results_layout.setContentsMargins(8, 8, 8, 8)
        self._results_layout.setSpacing(4)
        self._results_scroll.setWidget(self._results_widget)

        layout.addWidget(self._results_scroll, 1)

        self._results_scroll.setMinimumHeight(180)
        self._results_scroll.setMaximumHeight(360)

        self._refresh_region_label()
        self._populate_location_combo()
        # Contracts persist across restarts, but _route_order is in-memory
        # only and starts empty — without recomputing it here, a relaunch
        # shows every persisted contract but an empty ROUTE section until
        # the next scan or location change happens to replan it.
        contracts = self.settings.get("contracts", [])
        if contracts:
            self._route_order = self._plan_route(contracts)
        self._render_results()
        card.apply_size()
        return card

    @staticmethod
    def _button_style() -> str:
        return (
            f"background: {theme.BG_VOID}; color: {theme.ACCENT_CYAN}; "
            f"border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px; "
            f"padding: 4px 8px; font-family: {theme.FONT_DISPLAY}; font-weight: 700; "
            f"font-size: {theme.fpx(11)}px;"
        )

    # ------------------------------------------------------------------
    # UI helpers
    # ------------------------------------------------------------------
    def _refresh_region_label(self):
        region = self.settings.get("region")
        if region:
            text = f"XY {region.get('x')},{region.get('y')}  {region.get('w')}×{region.get('h')}"
        else:
            text = "Region: not set"
        self._region_label.setText(text)

    def _set_status(self, msg: str):
        if getattr(self, "_status_label", None) is not None:
            self._status_label.setText(msg)

    def _reminder_banners(self) -> list[QPushButton]:
        """Every live reminder banner widget — the card's own (always
        present) plus the Tracker popout's (only while it's open). Added
        2026-09-08: a real gap the user found — the card banner is
        invisible if mobiOverlay is stowed to its pill while the Tracker
        popout is open (a real workflow: scan, accept, pop out, then stow
        to get it out of the way), so the reminder needs to live wherever
        you're actually likely to be looking, not just one fixed place."""
        banners = [self._reminder_banner]
        popout_banner = getattr(self, "_popout_reminder_banner", None)
        if popout_banner is not None:
            banners.append(popout_banner)
        return banners

    def _show_accept_reminder(self, text: str):
        """Blinks every live reminder banner (card + Tracker popout, if
        open) until physically clicked — either one dismisses both, since
        they're the same reminder. Also expands and raises the card —
        showing this while the card is collapsed would defeat the entire
        point (the Tracker popout, being always-on-top, doesn't have this
        problem). Called only from `_recheck_accept_reminder`, never
        directly from `_on_review_accept` (the reminder only ever fires
        after Game.log has had a chance — and failed — to confirm the
        contract, not on ACCEPT itself). `self._reminder_text` is kept so
        a Tracker popout opened *after* this fires still shows it
        (`_open_route_popout` checks this on creation)."""
        self._reminder_text = text
        for banner in self._reminder_banners():
            banner.setText(text)
            banner.setVisible(True)
        self._reminder_blink_on = False
        self._toggle_reminder_blink()
        self._reminder_blink_timer.start()
        if self._card_widget is not None:
            self._card_widget.set_collapsed(False)
            self._card_widget.raise_()

    def _toggle_reminder_blink(self):
        self._reminder_blink_on = not self._reminder_blink_on
        bg = theme.ACCENT_AMBER if self._reminder_blink_on else theme.BG_VOID
        style = (
            f"background: {bg}; color: {theme.BG_VOID if self._reminder_blink_on else theme.ACCENT_AMBER}; "
            f"border: 2px solid {theme.ACCENT_AMBER}; border-radius: {theme.RADIUS}px; "
            f"padding: 6px 8px; font-family: {theme.FONT_DISPLAY}; font-weight: 800; "
            f"font-size: {theme.fpx(10)}px; letter-spacing: 1px;"
        )
        for banner in self._reminder_banners():
            banner.setStyleSheet(style)

    def _dismiss_accept_reminder(self):
        self._reminder_text = None
        self._reminder_blink_timer.stop()
        for banner in self._reminder_banners():
            banner.setVisible(False)

    def _clear_error_state(self):
        """Make sure the card body (with the SET SCAN AREA button) is visible
        even if the host previously put this card into its error state due to
        a missing capture region."""
        card = getattr(self, "_card_widget", None)
        if card is not None:
            card.clear_error()

    def _select_region(self):
        desktop = _virtual_desktop_rect()
        if desktop is None:
            return
        selector = _RegionSelector(desktop)
        selector.selected.connect(self._on_region_selected)
        self._selector = selector  # keep a reference so the GC doesn't reap it

    def _on_region_selected(self, rect: QRect):
        self.settings["region"] = {
            "x": rect.x(),
            "y": rect.y(),
            "w": rect.width(),
            "h": rect.height(),
        }
        self._save_settings()
        self._refresh_region_label()
        self._set_status("Region saved.")

    def _populate_location_combo(self):
        """Fill the current-location picker from the shared Core location
        service (host/locations.py) — synchronous, same pattern
        trade_route_optimizer uses to populate its system/terminal combos
        in create_card(). Restores the last-saved location, if any.

        Only shows available locations (is_available=1) by default —
        decommissioned/hidden POIs like Benson Mining Outpost, Bud's Growery,
        etc. are filtered out. OCR resolution still uses the full index
        (resolve_for_hauling doesn't filter) so contracts mentioning those
        places can still be parsed; this filter is for the picker UI only."""
        self._location_choices = {}
        for row in self._locations.available_locations():
            label = self._locations.search_label(row)
            if label in self._location_choices and self._location_choices[label] is not row:
                # Two distinct locations produced the same label (rare, but
                # possible across systems) — disambiguate rather than
                # silently dropping one from the picker. This is a picker-UI
                # concern, not something the shared service decides for us.
                system = row.get("star_system_name")
                if system:
                    label = f"{label} [{system}]"
            self._location_choices[label] = row
        names = sorted(self._location_choices.keys())

        self._location_combo.blockSignals(True)
        self._location_combo.clear()
        self._location_combo.addItems(names)
        saved_name = self.settings.get("current_location_name", "")
        if saved_name in self._location_choices:
            self._location_combo.setCurrentText(saved_name)
        else:
            self._location_combo.setCurrentText("")
        self._location_combo.blockSignals(False)

    def _on_location_selected(self, name: str):
        terminal = self._location_choices.get(name)
        if terminal is None:
            self._set_status(f"Unknown location: {name}")
            return
        self.settings["current_location_name"] = name
        self.settings["current_location"] = terminal
        self._save_settings()
        # Phase 5 (docs/DECISIONS.md, 2026-09-04): also publish to the
        # shared, non-module-namespaced slot so other modules (Trade Route
        # Optimizer, Commodity Prices) can default their own system filters
        # from wherever the player actually is, without a real inter-module
        # dependency wiring — they just read Config.shared_location() once.
        self.config.set_shared_location(terminal, name)
        self._set_status(f"Location set: {name}")
        # Where we start from just changed — replan immediately rather than
        # waiting for the next scan, so the picker feels responsive.
        contracts = self.settings.get("contracts", [])
        if contracts:
            self._route_order = self._plan_route(contracts)
            self._render_results()

    def _show_profile_popup(self):
        # `.get(key, {})` only falls back when the key is *absent* — the
        # key can legitimately be present with value `None` (e.g. never
        # set, or explicitly cleared), which crashed this the first time
        # it was live-tested. `or {}` covers both cases, same pattern
        # `_grade_contract()` already uses for the same field.
        profile = self.settings.get("hauler_profile") or {}
        capacity = self.settings.get("cargo_capacity_scu")
        thresholds = self.settings.get("grading_thresholds")
        game_log_path = self.settings.get("game_log_path") or gamelog_verify.default_game_log_path()
        reminder_seconds = self.settings.get("accept_reminder_seconds", DEFAULT_ACCEPT_REMINDER_SECONDS)
        popup = _HaulerProfilePopup(
            self._card_widget, profile, capacity, thresholds, game_log_path, reminder_seconds,
            self._on_profile_saved,
        )
        # Same reference-keeping fix as _review_popup below — a real
        # Qt.Window has no implicit reference keeping it alive once this
        # method returns.
        self._profile_popup = popup
        anchor = self._card_widget.mapToGlobal(self._card_widget.rect().topLeft())
        popup.move(anchor)
        popup.show()

    def _on_profile_saved(
        self, profile: dict, capacity: int | None, thresholds: dict, game_log_path: str | None,
        accept_reminder_seconds: int,
    ):
        self.settings["hauler_profile"] = profile
        self.settings["cargo_capacity_scu"] = capacity
        self.settings["grading_thresholds"] = thresholds
        self.settings["game_log_path"] = game_log_path
        self.settings["accept_reminder_seconds"] = accept_reminder_seconds
        self._save_settings()
        self._set_status(f"Profile saved: {profile.get('ship') or 'no ship set'}.")
        self._profile_popup = None
        # Cargo capacity feeds the card summary's over-capacity warning
        # directly — re-render so a changed value shows up immediately
        # instead of waiting for the next scan.
        self._render_results()

    def _current_location_terminal(self) -> dict | None:
        return self.settings.get("current_location")

    def _save_settings(self):
        self.config.set_module_settings(self.module_id, self.settings)

    def _clear_contracts(self):
        self.settings["contracts"] = []
        self.settings["route_done"] = []
        self._save_settings()
        self._route_order = []
        self._pending_scan = None
        self._render_results()
        self._set_status("Contracts cleared.")

    def _complete_contracts(self):
        """Logs every contract currently in the queue to
        `logistics_hub_completed.jsonl` (reward, cargo, locations, the
        grade it scored when accepted), then clears the queue exactly
        like CLEAR does — added 2026-09-07 per user request, replacing a
        plain CLEAR (which left no record at all) as the "I'm done with
        these" action. CLEAR itself is untouched and still exists for
        discarding contracts that were never actually completed (wrong
        scan, duplicate, mistake) without polluting this log."""
        contracts = self.settings.get("contracts", [])
        if not contracts:
            self._set_status("No contracts to complete.")
            return

        now = time.strftime("%Y-%m-%d %H:%M:%S")
        for contract in contracts:
            entry = {
                "timestamp": now,
                "contract_id": contract.get("id"),
                "scanned_at": contract.get("scanned_at"),
                "completed_at": now,
                "reward": contract.get("reward"),
                "grade_at_accept": contract.get("grade_at_accept"),
                "grade_reason_at_accept": contract.get("grade_reason_at_accept"),
                "pickups": [
                    {
                        "location": self._locations.display_name(e["terminal"]) if e.get("terminal") else e.get("raw"),
                        "commodities": _cargo_label(e.get("commodities")),
                    }
                    for e in contract.get("pickups", [])
                ],
                "dropoffs": [
                    {
                        "location": self._locations.display_name(e["terminal"]) if e.get("terminal") else e.get("raw"),
                        "commodities": _cargo_label(e.get("commodities")),
                    }
                    for e in contract.get("dropoffs", [])
                ],
            }
            self._append_jsonl(COMPLETED_LOG_FILENAME, entry)

        count = len(contracts)
        self._clear_contracts()
        self._set_status(f"Completed {count} contract{'s' if count != 1 else ''} — logged and cleared.")

    def _safe_reprocess(self):
        try:
            self._reprocess_contracts()
        except Exception as exc:
            self._set_status(f"Error: {exc}")

    def _reprocess_contracts(self):
        """Re-run parsing (locations + commodities) against every saved
        contract's own stored `raw_text`, in place — no rescan needed. Added
        2026-09-05 specifically so a parsing bug fix (e.g. the commodity-
        quantity summing fix the same day) doesn't require CLEAR + rescanning
        everything from the game; the raw OCR text needed to re-derive a
        contract is already persisted (same text the debug log/COPY ROUTE
        export already use), `_build_contract` just never gets called on it
        again after the initial scan.

        Preserves each contract's original `id`/`scanned_at` rather than
        taking the freshly-rebuilt ones — `route_done` entries are keyed
        `f"{contract_id}:{role}:{index}"` (`_toggle_route_done`), so keeping
        the same id is what lets an already-marked-done stop stay correctly
        matched after reprocessing, as long as the fix didn't change how many
        pickups/dropoffs that contract has (true for the quantity fix; a
        parsing change that adds/removes a stop would leave a stale
        `route_done` entry pointing at nothing — same outcome CLEAR-and-
        rescan already has today, not a new failure mode)."""
        contracts = self.settings.get("contracts", [])
        if not contracts:
            self._set_status("No contracts to reprocess.")
            return
        rebuilt = []
        traces: list[list[dict]] = []
        for old in contracts:
            trace: list[dict] = []
            new = self._build_contract(old.get("raw_text", ""), debug_trace=trace)
            if new is None:
                # Nothing usable left in the saved text (shouldn't happen —
                # it parsed once already — but never silently drop a
                # contract over it) — keep the old entry as-is.
                rebuilt.append(old)
                traces.append(trace)
                continue
            new["id"] = old.get("id", new["id"])
            new["scanned_at"] = old.get("scanned_at", new["scanned_at"])
            rebuilt.append(new)
            traces.append(trace)
        self.settings["contracts"] = rebuilt
        route_debug: dict = {}
        self._route_order = self._plan_route(rebuilt, route_debug=route_debug)
        self._log_reprocess_debug(rebuilt, traces, route_debug)
        self._save_settings()
        self._render_results()
        self._set_status(f"Reprocessed {len(rebuilt)} contract(s) from saved OCR text.")

    def _format_route_text(self) -> str:
        """Plain-text export of the current contracts + suggested route —
        primarily for debugging (so raw OCR text and resolution status are
        included alongside the clean names, not just what the card shows),
        but kept in the shipped app since it's also just a handy way to
        get a route out of the overlay and into a notepad/Discord message."""
        contracts = self.settings.get("contracts", [])
        lines = [
            f"Logistics Hub — Route Export ({time.strftime('%Y-%m-%d %H:%M:%S')})",
        ]

        start_terminal = self._current_location_terminal()
        start_name = self._locations.display_name(start_terminal) if start_terminal else "(not set)"
        lines.append(f"Starting location: {start_name}")
        lines.append("")

        lines.append(f"CONTRACTS ({len(contracts)})")
        if not contracts:
            lines.append("  (none)")
        for idx, contract in enumerate(contracts, start=1):
            reward = contract.get("reward")
            reward_text = f" · {reward} aUEC" if reward else ""
            lines.append(f"  {idx}. scanned {contract.get('scanned_at', '?')}{reward_text}")
            for role_key, role_label in (("pickups", "PICKUP"), ("dropoffs", "DROPOFF")):
                for entry in contract.get(role_key, []):
                    terminal = entry.get("terminal")
                    name = self._locations.display_name(terminal) if terminal else f"{entry.get('raw', '??')} [UNRESOLVED]"
                    cargo = f" ({_cargo_label(entry.get('commodities'))})"
                    raw = entry.get("raw", "??")
                    lines.append(f"     [{role_label}] {name}{cargo}  (OCR text: {raw!r})")
            for note in contract.get("ambiguous", []):
                lines.append(f"     [AMBIGUOUS] {note}")
            raw_text = contract.get("raw_text")
            if raw_text:
                lines.append("     --- raw OCR text for this scan ---")
                for raw_line in raw_text.splitlines():
                    lines.append(f"     | {raw_line}")
        lines.append("")

        lines.append("ROUTE")
        if not self._route_order:
            lines.append("  (none)")
        total_cost = 0.0
        prev_terminal, prev_raw = start_terminal, start_name
        for step, node in enumerate(self._route_order, start=1):
            i, role, j = node
            contract = contracts[i] if i < len(contracts) else None
            if contract is None:
                continue
            key = "pickups" if role == "pickup" else "dropoffs"
            items = contract.get(key, [])
            entry = items[j] if j < len(items) else {}
            terminal = entry.get("terminal")
            name = self._locations.display_name(terminal) if terminal else f"{entry.get('raw', '??')} [UNRESOLVED]"
            cargo = f" — {_cargo_label(entry.get('commodities'))}"
            role_tag = "PICKUP" if role == "pickup" else "DROPOFF"

            # Per-edge cost, and whether it's a real UEX distance or a
            # fallback estimate — lets a live test actually verify a route
            # that "looks" wrong (e.g. revisiting a stop) against real
            # numbers instead of just eyeballing the stop order.
            if prev_terminal and terminal:
                edge_cost = self._terminal_cost(prev_terminal, terminal)
                real = self._locations.distance(prev_terminal, terminal) is not None
                source = "same stop" if edge_cost == COST_SAME_TERMINAL else ("real dist" if real else "est.")
            else:
                edge_cost = COST_UNRESOLVED + self._text_cost(prev_raw or "", entry.get("raw", ""))
                source = "text-match est."
            total_cost += edge_cost
            lines.append(f"  {step}. [{role_tag}] {name}{cargo}  [+{edge_cost:.0f} {source}, running {total_cost:.0f}]")

            prev_terminal, prev_raw = terminal, name

        return "\n".join(lines)

    def _copy_route_to_clipboard(self):
        text = self._format_route_text()
        QGuiApplication.clipboard().setText(text)
        self._set_status("Route copied to clipboard.")

        if self._copy_route_revert_timer is not None:
            self._copy_route_revert_timer.stop()
        self._copy_route_btn.setText("COPIED")
        self._copy_route_revert_timer = QTimer()
        self._copy_route_revert_timer.setSingleShot(True)
        self._copy_route_revert_timer.timeout.connect(self._revert_copy_route_btn)
        self._copy_route_revert_timer.start(COPY_ROUTE_CONFIRM_MS)

    def _revert_copy_route_btn(self):
        self._copy_route_btn.setText("COPY ROUTE")
        self._copy_route_revert_timer = None

    def _safe_scan(self):
        """Start an OCR scan with inference in a background thread.

        IMPORTANT: easyocr.Reader must be created on the MAIN THREAD.
        Creating it inside a QThread crashes Qt6Core.dll on Windows due to
        PyTorch/OpenMP initialization conflicts. We use a plain threading.Thread
        for inference only, with a QObject signal bridge to marshal results
        back to the main thread.

        Flow:
        1. Screen capture + QPixmap→PIL on main thread
        2. Load easyocr.Reader on main thread (first scan only, may briefly block)
        3. Preprocess + inference in background threading.Thread
        4. Results marshaled back via _OcrSignalBridge signals
        """
        # Prevent starting a second scan while one is in progress
        if getattr(self, "_ocr_running", False):
            self._set_status("Scan already in progress...")
            return

        if not self._started:
            self._started = True
            self._set_status("Ready — click SCAN CONTRACT to capture one.")
            return

        region = self.settings.get("region")
        if not region:
            self._set_status("No capture region set — use SET SCAN AREA on the card first.")
            self._clear_error_state()
            return

        btn = getattr(self, "_scan_btn", None)
        if btn is not None:
            btn.setEnabled(False)

        # Load OCR dependencies on main thread
        if not _ensure_ocr_loaded():
            self._set_status(
                f"easyocr/Pillow not available: {_ocr_load_error or 'unknown error'}"
            )
            self._restore_scan_button()
            return

        # Load easyocr.Reader on MAIN THREAD (first scan only)
        # This avoids the Qt6Core.dll crash from PyTorch/OpenMP init in QThread
        if self._reader is None:
            if btn is not None:
                btn.setText("LOADING OCR…")
            self._set_status("Loading OCR engine (first scan)...")
            QApplication.processEvents()  # Show status before blocking
            try:
                easyocr = _ocr_modules["easyocr"]
                self._reader = easyocr.Reader(["en"], gpu=False, verbose=False)
            except Exception as exc:
                self._set_status(f"Failed to load OCR engine: {exc}")
                logger.exception("Failed to load easyocr.Reader")
                self._restore_scan_button()
                return

        if btn is not None:
            btn.setText("SCANNING…")
        self._set_status("Capturing screen...")

        # Capture screen immediately (must be on main thread)
        try:
            pix = self._grab_region(region)
            pil_rgb = self._pixmap_to_pil(pix)
        except Exception as exc:
            self._set_status(f"Error capturing screen: {exc}")
            self._restore_scan_button()
            return

        # Start background inference thread (plain threading.Thread, not QThread)
        self._ocr_running = True
        self._set_status("Scanning...")

        # Signal bridge lives on main thread, receives results via queued signals
        self._ocr_signal_bridge = _OcrSignalBridge()
        self._ocr_signal_bridge.finished.connect(self._on_ocr_finished)
        self._ocr_signal_bridge.error.connect(self._on_ocr_error)

        # Capture references for the worker thread
        reader = self._reader
        signal_bridge = self._ocr_signal_bridge

        def ocr_worker():
            try:
                Image = _ocr_modules["Image"]
                ImageOps = _ocr_modules["ImageOps"]
                np = _ocr_modules["np"]

                gray = ocr_module.preprocess_image(pil_rgb, ImageOps, Image)
                raw_text = ocr_module.run_ocr(reader, gray, np)
                signal_bridge.finished.emit(raw_text)
            except Exception as e:
                logger.exception("OCR worker error")
                signal_bridge.error.emit(str(e))

        thread = threading.Thread(target=ocr_worker, daemon=True)
        thread.start()

    def _pixmap_to_pil(self, pixmap):
        """Convert QPixmap to PIL RGB image. Must run on main thread.

        IMPORTANT: Makes a full copy of image bytes before QImage goes out
        of scope — QImage.bits() returns a view that becomes invalid once
        the QImage is garbage collected.
        """
        if not _ensure_ocr_loaded():
            raise RuntimeError(
                f"easyocr/Pillow not available: {_ocr_load_error or 'unknown error'}\n"
                "Run: pip install -r modules/logistics_hub/requirements.txt"
            )
        Image = _ocr_modules["Image"]

        qimg = pixmap.toImage().convertToFormat(QImage.Format_RGBA8888)
        # CRITICAL: copy bytes immediately — qimg.bits() is a view into qimg's
        # internal buffer, which becomes invalid when qimg is garbage collected.
        # Using bytes() or bytearray() creates an independent copy.
        width, height = qimg.width(), qimg.height()
        buf = bytearray(qimg.bits())  # Full copy, not a view

        pil_rgba = Image.frombuffer(
            "RGBA", (width, height), bytes(buf), "raw", "RGBA", 0, 1
        )
        return pil_rgba.convert("RGB")

    def _on_ocr_finished(self, raw_text: str):
        """Handle successful OCR completion (called on main thread via signal)."""
        self._ocr_running = False
        self._ocr_signal_bridge = None

        try:
            self._process_ocr_result(raw_text)
        except Exception as exc:
            self._set_status(f"Error: {exc}")
            logger.exception("Error processing OCR result")
        finally:
            self._restore_scan_button()

    def _on_ocr_error(self, error_msg: str):
        """Handle OCR worker error (called on main thread via signal)."""
        self._ocr_running = False
        self._ocr_signal_bridge = None
        self._set_status(f"OCR Error: {error_msg}")
        self._restore_scan_button()

    def _restore_scan_button(self):
        """Restore scan button to normal state."""
        btn = getattr(self, "_scan_btn", None)
        if btn is not None:
            btn.setText("SCAN CONTRACT")
            btn.setEnabled(True)

    def _process_ocr_result(self, raw_text: str):
        """Process OCR text into a contract and show review popup.

        This contains the logic that was previously in refresh() after
        the OCR call — now called from the background thread's callback.
        """
        logger.info("logistics_hub OCR raw text:\n%s", raw_text)

        debug_trace: list[dict] = []
        contract = self._build_contract(raw_text, debug_trace=debug_trace)
        if contract is None:
            raise ValueError("No usable text could be OCR'd — try adjusting the region or brightness.")

        candidates = _candidate_phrases(raw_text)

        contracts = self.settings.setdefault("contracts", [])
        self._pending_scan = contract
        duplicate = any(self._is_likely_duplicate(c, contract) for c in contracts)
        self._pending_grade = self._grade_contract(contract, contracts)
        self._show_review_popup(contract, duplicate, self._pending_grade)
        self._set_status("Review the scan — ACCEPT or REJECT.")
        self._log_scan_debug(
            raw_text, candidates, contract, "pending_review", debug_trace, {},
            grade=self._pending_grade,
        )

    # ------------------------------------------------------------------
    # ModuleBase refresh
    # ------------------------------------------------------------------
    def refresh(self):
        """Start an OCR scan via _safe_scan() — see that method's docstring.

        This is the ModuleBase contract entry point. Background OCR runs in
        a QThread so the UI stays responsive during the 1-3s inference time.
        Results are delivered via signals to _on_ocr_finished().
        """
        self._safe_scan()

    def _log_scan_debug(
        self, raw_text: str, candidates: list[tuple[str, str, int]], contract: dict, note: str,
        debug_trace: list[dict], route_debug: dict,
        grade: tuple[int | None, str, bool] | None = None,
    ) -> None:
        """Append one JSON line per scan to an always-on debug log, so real
        usage accumulates into a file the user can hand to an AI later to
        evaluate whether parsing/routing is holding up. Mirrors the level of
        detail this session's own live debugging relied on (console output +
        COPY ROUTE export) — see docs/DECISIONS.md, 2026-09-04."""
        entry = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "note": note,
            "raw_text": raw_text,
            "candidates": [{"phrase": p, "hint": h, "priority": pr} for p, h, pr in candidates],
            "contract": contract,
            # One entry per candidate phrase recording how (or whether) it
            # resolved — added 2026-09-05 to make every candidate's fate
            # visible, including ones that get silently dropped (missed both
            # exact/substring and fuzzy matching) with no trace anywhere else.
            # See DECISIONS.md, 2026-09-05.
            "resolution_trace": debug_trace,
            # Pulled out to the top level for easy grepping, derived from the
            # trace above (not string-matched against ambiguous_notes text,
            # which is fragile if that wording ever changes).
            "fuzzy_matches": [e for e in debug_trace if e.get("outcome") == "resolved" and e.get("method") == "fuzzy"],
            # Greedy (pre-2-opt) route + cost alongside the final one, so a
            # log review can tell whether 2-opt actually improved anything
            # on this scan instead of only seeing the final route in
            # isolation — added 2026-09-05. Empty on "duplicate_pending"
            # (route isn't replanned until the contract is actually added).
            "route_debug": route_debug,
            "route_snapshot": self._format_route_text(),
            # Confirm-gate/grading fields — added 2026-09-07 so a review
            # popup's decision can actually be reconstructed from the log
            # later instead of only seeing raw text/parsing. `None` when
            # grading wasn't run for this entry (e.g. REPROCESS).
            "grade": grade[0] if grade else None,
            "grade_reason": grade[1] if grade else None,
            "grade_capped": grade[2] if grade else None,
        }
        self._append_debug_log(entry)

    def _log_reprocess_debug(
        self, contracts: list[dict], traces: list[list[dict]], route_debug: dict,
    ) -> None:
        """Append one JSON line for a REPROCESS run (added 2026-09-05,
        alongside the REPROCESS button itself) — mirrors `_log_scan_debug`'s
        shape but covers every reprocessed contract at once instead of a
        single fresh scan, since REPROCESS re-parses everything already
        saved in one pass rather than adding one new contract. Without
        this, a REPROCESS run (or a location change picked up by it) left
        no trace anywhere reviewable — only a live scan did."""
        entry = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "note": "reprocessed",
            "contracts": contracts,
            "resolution_traces": traces,
            "fuzzy_matches": [
                e for trace in traces for e in trace
                if e.get("outcome") == "resolved" and e.get("method") == "fuzzy"
            ],
            "route_debug": route_debug,
            "route_snapshot": self._format_route_text(),
        }
        self._append_debug_log(entry)

    def _append_debug_log(self, entry: dict) -> None:
        log_path = paths.app_root() / DEBUG_LOG_FILENAME
        try:
            if log_path.stat().st_size > DEBUG_LOG_MAX_BYTES:
                os.replace(log_path, log_path.with_name(DEBUG_LOG_FILENAME + ".1"))
        except OSError:
            pass  # missing (nothing to rotate) or locked — just append
        self._append_jsonl(DEBUG_LOG_FILENAME, entry)

    def _append_jsonl(self, filename: str, entry: dict) -> None:
        try:
            log_path = paths.app_root() / filename
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            logger.warning("Failed to write logistics_hub %s entry", filename, exc_info=True)

    def _clear_debug_log(self) -> None:
        """Wipes DEBUG_LOG_FILENAME only — never COMPLETED_LOG_FILENAME,
        which is a deliberately durable record of contracts actually
        delivered (see its own module-level comment). Added 2026-09-08 so
        testing the Game.log verify feature doesn't need closing the app
        and deleting the file by hand between scans."""
        try:
            log_path = paths.app_root() / DEBUG_LOG_FILENAME
            log_path.write_text("", encoding="utf-8")
            self._set_status(f"Debug log cleared at {time.strftime('%H:%M:%S')}.")
        except OSError as exc:
            logger.warning("Failed to clear %s", DEBUG_LOG_FILENAME, exc_info=True)
            self._set_status(f"Could not clear debug log: {exc}")

    def _add_contract(
        self, contract: dict, route_debug: dict | None = None, verify_result: dict | None = None,
    ) -> None:
        contracts = self.settings.setdefault("contracts", [])
        contracts.append(contract)
        self._save_settings()
        self._route_order = self._plan_route(contracts, route_debug=route_debug)
        self._render_results()
        status = f"Added contract ({len(contracts)} total) at {time.strftime('%H:%M:%S')}"
        # Shown even on a non-match — a silent skip here is exactly what
        # produced the "why didn't Game.log help" confusion this status
        # line exists to prevent (see docs/DECISIONS.md, 2026-09-08). The
        # full detail (candidates considered, scores, log path) is always
        # in the debug log; this line is just the at-a-glance version.
        if verify_result is not None:
            if verify_result.get("matched"):
                status += (
                    f" — Game.log verified, {len(verify_result['corrections'])} field(s) corrected."
                    if verify_result["corrections"] else " — Game.log verified, matches OCR."
                )
            elif verify_result.get("reason") == "game_log_unavailable":
                status += " — Game.log not found, not verified."
            else:
                status += " — Game.log: no matching contract found, not verified."
        self._set_status(status)

    @classmethod
    def _is_likely_duplicate(cls, a: dict, b: dict) -> bool:
        """Same reward, scanned again — but OCR noise varies scan to scan,
        so two captures of the *same real contract* can each resolve a
        slightly different set of pickups (one scan lost HDMS-Perlman,
        another lost Shubin, on two otherwise-identical scans of the same
        contract — confirmed real). Requiring the *entire* location set to
        match exactly missed that case entirely. Reward equality is
        already a strong signal on its own (two different real contracts
        rarely pay the exact same amount) — only need *some* resolved
        location in common on top of that, not a perfect set match."""
        if a.get("reward") != b.get("reward") or not a.get("reward"):
            return False
        a_locs = cls._location_keys(a)
        b_locs = cls._location_keys(b)
        return bool(a_locs & b_locs)

    @staticmethod
    def _location_keys(contract: dict) -> frozenset:
        return frozenset(
            LogisticsHubModule._locations_terminal_key_or_raw(e)
            for e in contract.get("pickups", []) + contract.get("dropoffs", [])
        )

    @staticmethod
    def _locations_terminal_key_or_raw(entry: dict):
        terminal = entry.get("terminal")
        if terminal:
            return LocationService.terminal_key(terminal)
        return entry.get("raw", "").lower()

    def _show_review_popup(self, contract: dict, duplicate: bool, grade_info: tuple[int | None, str, bool]):
        pickups_text = self._entry_names(contract.get("pickups", []), self._locations.display_name)
        dropoffs_text = self._entry_names(contract.get("dropoffs", []), self._locations.display_name)
        reward = contract.get("reward")
        # `reward` is the raw extracted string (e.g. "87,250"), already
        # comma-formatted from OCR text — not an int, same as every other
        # place in this file that displays it (_contract_row, etc.).
        reward_text = f"{reward} aUEC" if reward else "reward unknown"
        scu = sum(_entry_scu(e) for e in contract.get("pickups", []))
        summary_text = f"{pickups_text} → {dropoffs_text}\n{reward_text}  ·  {scu} SCU"

        duplicate_warning = (
            "Looks like a duplicate of a contract already in your queue "
            "(same reward, shares a location)." if duplicate else None
        )

        grade, grade_reason, grade_capped = grade_info

        ship = (self.settings.get("hauler_profile") or {}).get("ship", "").strip()
        ratings = self.settings.get("ship_location_ratings", {})
        unrated_terminals = []
        if ship:
            seen_keys = set()
            for terminal in self._contract_terminals(contract):
                key = self._compat_key(ship, terminal)
                if key in ratings or key in seen_keys:
                    continue
                seen_keys.add(key)
                unrated_terminals.append((self._locations.display_name(terminal), terminal))

        # Recorded here (not just saved to the ratings DB) so
        # _log_review_outcome() can put "what was asked, what was
        # answered" into the debug log when ACCEPT/REJECT is clicked —
        # added 2026-09-07.
        self._pending_unrated_names = [name for name, _t in unrated_terminals]
        self._pending_ratings_given = []

        def on_rate(terminal: dict, good: bool, label: str):
            self._rate_compatibility(ship, terminal, good)
            self._pending_ratings_given.append({"location": label, "rating": "good" if good else "bad"})

        popup = _ReviewPopup(
            self._card_widget, summary_text, duplicate_warning,
            grade, grade_reason, grade_capped, unrated_terminals,
            on_rate, self._on_review_accept, self._on_review_reject,
        )
        # Now a real Qt.Window (see _ReviewPopup's 2026-09-07 note), which
        # — unlike Qt.Popup — has no implicit reference keeping it alive.
        # Without this, the popup was garbage-collected right after this
        # method returns, before the user could even see it. Cleared in
        # both outcome handlers below.
        self._review_popup = popup
        anchor = self._scan_btn.mapToGlobal(self._scan_btn.rect().bottomLeft())
        popup.move(anchor)
        popup.show()

    def _log_review_outcome(self, contract: dict, outcome: str, verify_result: dict | None = None) -> None:
        """Appended when ACCEPT/REJECT is actually clicked — separate from
        the 'pending_review' entry `_log_scan_debug` writes at scan time,
        since that entry is written before the user has seen the popup
        and can't know the outcome yet. Added 2026-09-07 alongside the
        grading/compatibility-DB feature so a real session's decisions
        (not just its OCR/parsing) show up in the debug log.

        `verify_result`, only set on ACCEPT, is `_verify_against_gamelog`'s
        return value — whether Game.log confirmed this contract and what,
        if anything, it corrected. See docs/DECISIONS.md."""
        entry = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "note": f"review_{outcome}",
            "contract_id": contract.get("id"),
            "grade": self._pending_grade[0] if self._pending_grade else None,
            "grade_reason": self._pending_grade[1] if self._pending_grade else None,
            "grade_capped": self._pending_grade[2] if self._pending_grade else None,
            "compatibility_prompts_shown": self._pending_unrated_names,
            "compatibility_ratings_given": self._pending_ratings_given,
            "gamelog_verify": verify_result,
        }
        self._append_debug_log(entry)

    def _verify_against_gamelog(self, contract: dict) -> dict:
        """Cross-checks a freshly-scanned contract, right before it's added
        to the queue, against Star Citizen's own Game.log record of the
        contract you just accepted in-game. Game.log wins whenever it
        reports something (destination/commodity/tonnage) — OCR fills in
        anything the log doesn't cover (reward, per-box detail). See
        `modules/logistics_hub/gamelog_verify.py` and docs/DECISIONS.md
        for the full design.

        Best-effort only: a missing/unreadable log or no confident match
        within the time window leaves the OCR-built contract untouched —
        this never blocks or delays ACCEPT.

        Always returns `log_path`/`log_path_source`/`log_file_exists`/
        `events_in_window` on top of whatever `gamelog_verify.verify_contract`
        adds — added 2026-09-08 after a live first test surfaced "why
        didn't Game.log help here" with nothing in the debug log to answer
        it from. This is the full record of what the verify step actually
        saw, every time, not just when it succeeds."""
        configured_path = self.settings.get("game_log_path")
        log_path = configured_path or gamelog_verify.default_game_log_path()
        base = {
            "log_path": log_path,
            "log_path_source": "settings" if configured_path else "default_lookup",
            "log_file_exists": bool(log_path and os.path.isfile(log_path)),
        }
        if not base["log_file_exists"]:
            return {
                **base, "matched": False, "mission_id": None, "title": None, "corrections": [],
                "reason": "game_log_unavailable", "events_in_window": 0, "candidates_considered": [],
            }
        try:
            now = datetime.now(timezone.utc)
            # Read straight from config.json's modules.logistics_hub block
            # (self.settings *is* that block — see host/config.py) rather
            # than a fixed constant, so tuning this doesn't need a code
            # change/rebuild — just edit
            # config.json -> modules.logistics_hub.game_log_verify_window_seconds
            # and relaunch. Added 2026-09-08 per user direction, expecting
            # to need real tuning as more real sessions run (see
            # nearest_haul_event_gap_seconds below, logged for exactly
            # that purpose) without it turning into a code-edit each time.
            window_seconds = self.settings.get(
                "game_log_verify_window_seconds", gamelog_verify.DEFAULT_WINDOW_SECONDS
            )
            events = gamelog_verify.find_recent_haul_events(log_path, now, window_seconds=window_seconds)
            # Every other contract's already-claimed real mission, so the
            # same accept can never be attached to two different scanned
            # contracts — added 2026-09-08 after real evidence of exactly
            # that (two back-to-back hauls from the same station both
            # matched the same real mission_id). `is not contract` excludes
            # only this contract's own prior claim (a re-verify shouldn't
            # be blocked by its own earlier match), not everyone else's.
            claimed_mission_ids = {
                c["gamelog_mission_id"]
                for c in self.settings.get("contracts", [])
                if c.get("gamelog_mission_id") and c is not contract
            }
            result = gamelog_verify.verify_contract(
                contract, events, self._locations.display_name, exclude_mission_ids=claimed_mission_ids,
            )
            if result.get("matched"):
                contract["gamelog_mission_id"] = result["mission_id"]
            # Logged unconditionally (not just on a miss) so a real
            # distribution builds up in the debug log over time — see
            # gamelog_verify.nearest_haul_event_gap_seconds's own docstring
            # and docs/DECISIONS.md, 2026-09-08. This is how the next
            # window-size decision gets to be data instead of another guess.
            nearest_gap = gamelog_verify.nearest_haul_event_gap_seconds(log_path, now)
            return {
                **base, "events_in_window": len(events),
                "window_seconds": window_seconds,
                "nearest_haul_event_gap_seconds": nearest_gap,
                **result,
            }
        except Exception as exc:  # never let a verification bug block ACCEPT
            logger.warning("Game.log verification failed: %s", exc)
            return {
                **base, "matched": False, "mission_id": None, "title": None, "corrections": [],
                "reason": f"error: {exc}", "events_in_window": 0, "candidates_considered": [],
            }

    def _on_review_accept(self):
        if self._pending_scan is not None:
            verify_result = self._verify_against_gamelog(self._pending_scan)
            self._log_review_outcome(self._pending_scan, "accepted", verify_result)
            # Stashed on the contract itself (not just the transient debug
            # log) so COMPLETE can report what a contract actually scored
            # when it was accepted, even long after this scan's debug
            # entries are gone — added 2026-09-07 alongside COMPLETE.
            if self._pending_grade is not None:
                self._pending_scan["grade_at_accept"] = self._pending_grade[0]
                self._pending_scan["grade_reason_at_accept"] = self._pending_grade[1]
            contract_id = self._pending_scan.get("id")
            self._add_contract(self._pending_scan, verify_result=verify_result)
            self._schedule_accept_reminder(contract_id, verify_result)
        self._pending_scan = None
        self._review_popup = None

    def _schedule_accept_reminder(self, contract_id: str | None, verify_result: dict) -> None:
        """Queues a one-shot delayed recheck of Game.log for a contract
        that didn't verify immediately at ACCEPT — added 2026-09-08. Most
        real accepts won't verify instantly (the log line can lag, or you
        haven't clicked Accept in-game yet at the exact moment you click
        ACCEPT here), so this gives Game.log a second, later chance before
        ever bothering you — the reminder only fires if it's STILL
        unmatched after the delay, not on every miss. No-op if already
        matched (nothing to recheck) or the reminder is disabled (0s)."""
        if verify_result.get("matched") or not contract_id:
            return
        delay_seconds = self.settings.get("accept_reminder_seconds", DEFAULT_ACCEPT_REMINDER_SECONDS)
        if not delay_seconds or delay_seconds <= 0:
            return
        QTimer.singleShot(delay_seconds * 1000, lambda: self._recheck_accept_reminder(contract_id))

    def _recheck_accept_reminder(self, contract_id: str) -> None:
        """Fires once, `accept_reminder_seconds` after ACCEPT. Re-verifies
        against Game.log (mutating the contract's dropoffs in place on a
        match, exactly like the original verify at ACCEPT — this is really
        just that same check running again, later); shows the blinking
        reminder only if it's still unmatched. Silently no-ops if the
        contract isn't in the queue anymore (CLEAR/COMPLETE ran first) —
        nothing to remind about."""
        contract = next(
            (c for c in self.settings.get("contracts", []) if c.get("id") == contract_id), None
        )
        if contract is None:
            return
        verify_result = self._verify_against_gamelog(contract)
        self._append_debug_log({
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "note": "accept_reminder_recheck",
            "contract_id": contract_id,
            "gamelog_verify": verify_result,
        })
        if verify_result.get("matched"):
            if verify_result.get("corrections"):
                self._save_settings()
                self._render_results()
            return
        reward = contract.get("reward")
        pickups_text = self._entry_names(contract.get("pickups", []), self._locations.display_name)
        self._show_accept_reminder(
            f"⚠ DID YOU ACCEPT '{pickups_text}' ({reward or '?'} aUEC) IN-GAME? CLICK TO DISMISS"
        )

    def _on_review_reject(self):
        if self._pending_scan is not None:
            self._log_review_outcome(self._pending_scan, "rejected")
        self._pending_scan = None
        self._review_popup = None
        self._set_status("Contract not added.")

    # ------------------------------------------------------------------
    # Screen capture / OCR
    # ------------------------------------------------------------------
    def _grab_region(self, region: dict):
        x, y, w, h = int(region["x"]), int(region["y"]), int(region["w"]), int(region["h"])
        point = QPoint(x, y)
        screen = QGuiApplication.screenAt(point)
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            raise RuntimeError("No screen is available for capture.")

        local_x = x - screen.geometry().x()
        local_y = y - screen.geometry().y()
        return screen.grabWindow(0, local_x, local_y, w, h)

    def _ocr(self, pixmap):
        """Runs EasyOCR over the given QPixmap and returns raw text.
        
        OCR modules (easyocr, PIL, numpy) are loaded lazily by _ensure_ocr_loaded()
        before this method is called. Access them via _ocr_modules dict.
        """
        # Get lazily-loaded modules
        Image = _ocr_modules["Image"]
        ImageOps = _ocr_modules["ImageOps"]
        easyocr = _ocr_modules["easyocr"]
        np = _ocr_modules["np"]

        # Convert QPixmap → QImage → PIL image. In PySide6/Qt6, QImage.bits()
        # already returns a correctly-sized Python memoryview (unlike PyQt5's
        # sip.voidptr, which needed .setsize() to become buffer-like) — wrap
        # it in bytes() and hand it straight to PIL.
        qimg = pixmap.toImage().convertToFormat(QImage.Format_RGBA8888)
        buf = bytes(qimg.bits())
        pil_rgba = Image.frombuffer(
            "RGBA", (qimg.width(), qimg.height()), buf, "raw", "RGBA", 0, 1
        )
        pil_rgb = pil_rgba.convert("RGB")

        # Preprocess a little for the OCR engine.
        gray = ImageOps.grayscale(pil_rgb)
        # In-game UI text captured at native resolution is often small —
        # a single contract line can be well under 20px tall in a typical
        # capture region. OCR engines (EasyOCR included) read text
        # substantially more reliably above a certain pixel-height floor;
        # upscaling before detection, not relying on EasyOCR's own
        # internal `mag_ratio` resizing alone, is standard OCR-preprocessing
        # practice for small source text. LANCZOS (not the default
        # nearest-neighbor) keeps character edges reasonably clean at 2x
        # rather than introducing new blockiness. This is a one-off manual
        # scan, not a real-time loop, so the extra processing time is an
        # easy trade for better accuracy.
        OCR_UPSCALE_FACTOR = 2
        gray = gray.resize(
            (gray.width * OCR_UPSCALE_FACTOR, gray.height * OCR_UPSCALE_FACTOR),
            Image.LANCZOS,
        )
        gray = ImageOps.autocontrast(gray)

        if self._reader is None:
            self._reader = easyocr.Reader(["en"], gpu=False, verbose=False)

        # detail=1 (not the previous detail=0) so each result carries its
        # bounding box, not just bare text — needed by _order_ocr_boxes()
        # below to read the panel in genuine left-to-right, top-to-bottom
        # order. Without this, text came back in whatever order EasyOCR's
        # own internal sort happened to produce, which does NOT respect
        # the contract panel's real two-column layout (mission narrative
        # text next to a separate PICK UP/DROP OFF list) — confirmed to be
        # the root cause behind the large majority of parsing bugs fixed
        # this session (split location names, orphaned words, role
        # misattribution), all of which were really downstream symptoms of
        # reading the two columns interleaved instead of one at a time.
        results = self._reader.readtext(np.array(gray), detail=1, allowlist=OCR_ALLOWLIST)
        # `gray.width`, not `pil_rgb.width` — bounding boxes from EasyOCR
        # are in the *upscaled* image's coordinate space, so the column-
        # gap threshold in _order_ocr_boxes needs to be computed against
        # that same scale, not the original pre-upscale capture width.
        lines = _order_ocr_boxes(results, gray.width)
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Location resolution now lives in the shared Core service
    # (host/locations.py, self._locations) — a mission's drop-off is very
    # often a pure delivery point (a space station/outpost/city) with no
    # commodity trading kiosk at all, and different location endpoints
    # have colliding raw ids for unrelated real places, both handled
    # there once for every module instead of per-module. See
    # docs/DECISIONS.md, 2026-09-04, for the full history.
    # ------------------------------------------------------------------

    def _disambiguate_by_suffix(self, text: str, matches: list[dict], raw_text: str) -> dict | None:
        """When a bare phrase matches several distinct real places that
        differ only by a trailing code/number ("ArcCorp Mining Area" ->
        045/048/056/061/141), the *contract text itself* often does
        contain the disambiguating suffix somewhere — just not attached to
        this exact candidate string (a different mention, a line away, or
        the phrase regex genuinely can't include a digit). Rather than
        guess, check each candidate's own distinguishing suffix (its
        normalized name/nickname with the ambiguous phrase's own prefix
        stripped) against every line of the raw text individually — line-
        by-line, not the whole text concatenated, so two unrelated digits
        that happen to sit at a line boundary can't coincidentally form a
        false match. Only resolves if the suffix is long enough to be
        meaningful and exactly one candidate's suffix is actually found;
        any other outcome (zero or multiple matches) stays ambiguous.
        """
        phrase_norm = self._locations.normalize(text)
        lines_norm = [self._locations.normalize(line) for line in raw_text.splitlines()]

        found: dict | None = None
        found_count = 0
        for candidate in matches:
            suffix = None
            for key in ("name", "nickname"):
                label = candidate.get(key)
                if not label:
                    continue
                label_norm = self._locations.normalize(label)
                if label_norm.startswith(phrase_norm) and len(label_norm) > len(phrase_norm):
                    suffix = label_norm[len(phrase_norm):]
                    break
            if not suffix or len(suffix) < 2:
                continue
            if any(suffix in line for line in lines_norm):
                found_count += 1
                found = candidate
                if found_count > 1:
                    return None

        return found if found_count == 1 else None

    def _build_contract(self, raw_text: str, debug_trace: list[dict] | None = None) -> dict | None:
        """Build one contract from a scan's OCR text: pull every plausible
        location phrase, resolve each against real UEX terminal data, and
        split the distinct resolved terminals into pickups vs. drop-offs by
        role hint. A contract can have several of *either* — real panels use
        one pickup with several drop-offs (DROP OFF LOCATIONS (ANY ORDER))
        just as often as one drop-off with several pickups (PICK UP
        LOCATIONS (ANY ORDER)). Falls back to raw, unresolved candidate
        phrases if nothing resolved at all, so a scan still produces
        something reviewable instead of silently failing.

        `debug_trace`, if given, gets one entry appended per candidate
        recording its resolution outcome (`resolved` + which of the five
        resolution paths won, `ambiguous_unresolved`, or `dropped_no_match`
        — the last including a near-miss fuzzy score when one was attempted)
        for `_log_scan_debug`. Purely additive/observational — never affects
        which terminal a candidate actually resolves to."""
        candidates = _candidate_phrases(raw_text)  # list of (phrase, hint, priority)
        reward = _extract_reward(raw_text)
        trace: list[dict] = []

        # Resolve every candidate against real UEX data, deduped by
        # terminal id (falling back to normalized text for records with no
        # id) so a second OCR mention of the same real place can *upgrade*
        # an earlier neutral-hinted match to pickup/dropoff instead of being
        # silently discarded — losing that hint was a real bug: an
        # OCR-garbled second mention ("MIC-Lz Long Forest Station") sat
        # right next to "Collect", the clearest pickup signal in the whole
        # panel, and got dropped for resolving to the same id as an
        # earlier, hint-less mention.
        resolved_by_key: dict = {}
        order: list = []
        # A bare phrase can genuinely match more than one distinct real
        # place — "ArcCorp Mining Area" alone matches both "...045" and
        # "...056" — usually because OCR separated the distinguishing
        # suffix onto a different line entirely. Silently picking one is
        # worse than admitting the parser isn't sure: only note this for
        # candidates that actually got a real pickup/dropoff hint (a
        # "neutral" ambiguous match was never going anywhere anyway and
        # would just be noise here).
        ambiguous_notes: list[str] = []
        noted: set[str] = set()

        def merge_resolved(text: str, terminal: dict, hint: str, priority: int) -> None:
            key = self._locations.terminal_key(terminal)
            if key not in resolved_by_key:
                # Two different UEX records can be the exact same real
                # place — a `terminals` kiosk and the `space_stations`/
                # `outposts`/`cities` record it structurally belongs to
                # (see `LocationService.same_physical_place()`) — and
                # `terminal_key()` alone can't tell. Confirmed real: "Seraphim
                # The" and "Seraphim Station" resolved to two different
                # records for the same real station, producing a duplicate
                # route stop that got visited twice for no reason. Check
                # already-resolved entries for a same-place match before
                # creating a new one, so both mentions land in the same
                # entry regardless of which specific record either resolved
                # to.
                for existing_key in order:
                    if self._locations.same_physical_place(terminal, resolved_by_key[existing_key][1]):
                        key = existing_key
                        # Prefer a structural (`space_stations`/`outposts`/
                        # `cities`) record as the merged entry's display
                        # terminal over a `terminals` kiosk record — a
                        # kiosk's own name/nickname is often the raw,
                        # unfriendly in-game label ("Admin - MIC-L2") while
                        # the structural record has the real place name
                        # ("MIC-L2 Long Forest Station"). Confirmed real:
                        # without this, merging could regress an
                        # already-correct display name to the uglier one
                        # just because of merge order.
                        existing_terminal = resolved_by_key[existing_key][1]
                        if existing_terminal.get("_endpoint") == "terminals" and terminal.get("_endpoint") != "terminals":
                            resolved_by_key[existing_key][1] = terminal
                        break
            if key not in resolved_by_key:
                # 5th element: every raw OCR spelling that resolved to this
                # same real place ("Long Forest Station", and separately
                # "Forest Station" once disambiguated) — commodity
                # extraction needs *all* of them, not just whichever won
                # the display text, since a garbled mention that's missing
                # a word can still be the only line mentioning a
                # particular commodity for this stop.
                resolved_by_key[key] = [text, terminal, hint, priority, {text}]
                order.append(key)
                return
            resolved_by_key[key][4].add(text)
            if priority > resolved_by_key[key][3]:
                # Same real place reached via a *differently-worded*
                # candidate (e.g. "Shallow Frontier Station" from one line
                # vs. bare "Shallow Frontier" from another) — these never
                # share a text-based dedup key, so the priority check has
                # to happen again here too, not just inside
                # `_candidate_phrases`. Confirmed real: a lookback-mishinted
                # "dropoff" mention blocked a later, correct, higher-
                # priority "pickup" mention of the very same terminal.
                resolved_by_key[key][2] = hint
                resolved_by_key[key][3] = priority

        # Pass 1: every candidate that resolves to exactly one real place —
        # these are the ground truth the ambiguous pass below leans on.
        # Use resolve_for_hauling() for hauling-contract-aware resolution:
        # checks aliases, prefers Admin terminals, validates against OCR text.
        pending_ambiguous: list[tuple[str, str, int, list[dict]]] = []
        for text, hint, priority in candidates:
            matches = self._locations.resolve_for_hauling(text)
            if not matches:
                # No exact/substring hit at all — for a candidate that
                # actually carries a real pickup/dropoff signal (never for
                # "neutral" text, same gating the ambiguous-note path below
                # uses), try a fuzzy match rather than silently dropping the
                # stop. OCR can garble a name just enough to miss substring
                # matching entirely ("Seraphim Staton") without being
                # unreadable — resolving it anyway, visibly flagged as
                # unconfirmed via the same amber-warning mechanism as an
                # ambiguous match, beats a contract missing a stop outright.
                if hint != "neutral":
                    # Use resolve_fuzzy_for_hauling to auto-promote structural
                    # records (space_stations/outposts/cities) to their Admin
                    # terminals, same as resolve_for_hauling does.
                    fuzzy = self._locations.resolve_fuzzy_for_hauling(text)
                    if fuzzy is not None:
                        location, score = fuzzy
                        merge_resolved(text, location, hint, priority)
                        display = self._locations.display_name(location)
                        trace.append({
                            "phrase": text, "hint": hint, "outcome": "resolved",
                            "method": "fuzzy", "matched": display, "score": round(score, 3),
                        })
                        if text.lower() not in noted:
                            noted.add(text.lower())
                            ambiguous_notes.append(
                                f"{text!r} ({hint}) fuzzy-matched to {display} "
                                f"({score:.0%} confidence) — please verify"
                            )
                    else:
                        near_miss = self._locations.best_fuzzy_match(text)
                        trace.append({
                            "phrase": text, "hint": hint, "outcome": "dropped_no_match",
                            "near_miss": (
                                {"matched": self._locations.display_name(near_miss[0]), "score": round(near_miss[1], 3)}
                                if near_miss else None
                            ),
                        })
                else:
                    trace.append({"phrase": text, "hint": hint, "outcome": "dropped_no_match", "near_miss": None})
                continue
            if len(matches) > 1 and hint != "neutral":
                pending_ambiguous.append((text, hint, priority, matches))
                continue
            merge_resolved(text, matches[0], hint, priority)
            trace.append({
                "phrase": text, "hint": hint, "outcome": "resolved",
                "method": "exact_or_substring", "matched": self._locations.display_name(matches[0]),
            })

        # Pass 2: try to disambiguate what's left, now that we know which
        # real places this contract has *already* confirmed unambiguously.
        # Two independent checks, either is enough to resolve:
        #  - a distinguishing suffix particular to one candidate appears
        #    somewhere in the text ("ArcCorp Mining Area" -> "...061" seen
        #    on another line);
        #  - one of the ambiguous options was *already* confirmed by a
        #    different, unambiguous mention elsewhere in this same
        #    contract ("Forest Station" alone is ambiguous between "Wide
        #    Forest Station"/"Long Forest Station", but this contract's
        #    OTHER mentions already unambiguously confirmed "Long Forest
        #    Station" — a real place appearing twice under two different
        #    OCR-garbled spellings is far more likely than two unrelated
        #    real places both showing up in one contract by coincidence).
        for text, hint, priority, matches in pending_ambiguous:
            disambiguated = self._disambiguate_by_suffix(text, matches, raw_text)
            method = "suffix_disambiguation"
            if disambiguated is None:
                already_confirmed = [
                    m for m in matches
                    if self._locations.terminal_key(m) in resolved_by_key
                ]
                if len(already_confirmed) == 1:
                    disambiguated = already_confirmed[0]
                    method = "already_confirmed_elsewhere"

            if disambiguated is not None:
                merge_resolved(text, disambiguated, hint, priority)
                trace.append({
                    "phrase": text, "hint": hint, "outcome": "resolved",
                    "method": method, "matched": self._locations.display_name(disambiguated),
                })
                continue

            options = ", ".join(self._locations.display_name(m) for m in matches[:5])
            trace.append({"phrase": text, "hint": hint, "outcome": "ambiguous_unresolved", "options": options})
            if text.lower() not in noted:
                noted.add(text.lower())
                ambiguous_notes.append(f"{text!r} ({hint}) could be: {options} — not auto-resolved")

        resolved: list[tuple[str, dict, str, set]] = [
            (resolved_by_key[k][0], resolved_by_key[k][1], resolved_by_key[k][2], resolved_by_key[k][4])
            for k in order
        ]

        if debug_trace is not None:
            debug_trace.extend(trace)

        if not resolved and not candidates:
            return None

        if resolved:
            pickups = [
                {"raw": text, "terminal": terminal, "_aka": aka}
                for text, terminal, hint, aka in resolved if hint == "pickup"
            ]
            dropoffs = [
                {"raw": text, "terminal": terminal, "_aka": aka}
                for text, terminal, hint, aka in resolved if hint == "dropoff"
            ]
            # A resolved but merely "neutral" match (e.g. the contractor's
            # own company name happening to also be a real UEX shop/company
            # record) is noise, not a mission stop — only fall back to it
            # if a role would otherwise be completely empty.
            neutrals = [
                {"raw": text, "terminal": terminal, "_aka": aka}
                for text, terminal, hint, aka in resolved if hint == "neutral"
            ]
            if not pickups and not dropoffs:
                # Nothing got a real role hint at all — best guess: first
                # resolved location is the pickup, the rest are drop-offs.
                pickups = neutrals[:1]
                dropoffs = neutrals[1:]
            elif not pickups:
                pickups = neutrals[:1]
            elif not dropoffs:
                dropoffs = neutrals[:1]
        else:
            # Nothing resolved against UEX data — keep the module useful by
            # falling back to raw text, clearly marked unresolved in the UI.
            pickups = [{"raw": candidates[0][0], "terminal": None}]
            dropoffs = [{"raw": c, "terminal": None} for c, _hint, _priority in candidates[1:3]]

        if not pickups:
            pickups = [{"raw": "?", "terminal": None}]
        if not dropoffs:
            # Always have at least one drop-off slot, even if unresolved,
            # so the route always has somewhere to go besides the pickup —
            # but never invent one out of a candidate that's actually a
            # commodity name ("Ship Ammunition"), not a place at all.
            pickup_raws = {p["raw"].lower() for p in pickups}
            commodity_names = _all_commodity_names(raw_text)
            remaining = [
                (c, h) for c, h, _priority in candidates
                if c.lower() not in pickup_raws and c.lower() not in commodity_names
            ]
            fallback = next((c for c, h in remaining if h == "dropoff"), None)
            if fallback is None and remaining:
                fallback = remaining[0][0]
            dropoffs = [{
                "raw": fallback if fallback is not None else "(unresolved — no location text found)",
                "terminal": None,
            }]

        for entry in pickups:
            entry["commodities"] = self._entry_commodities(raw_text, entry, "pickup")
        for entry in dropoffs:
            entry["commodities"] = self._entry_commodities(raw_text, entry, "dropoff")
        # `_aka` (a set) was only needed to widen the commodity search above
        # — drop it before this contract gets persisted to config.json,
        # since a set isn't JSON-serializable.
        for entry in pickups + dropoffs:
            entry.pop("_aka", None)

        return {
            "id": uuid.uuid4().hex[:8],
            "pickups": pickups,
            "dropoffs": dropoffs,
            "reward": reward,
            "scanned_at": time.strftime("%H:%M:%S"),
            "ambiguous": ambiguous_notes,
            "raw_text": raw_text,
        }

    @staticmethod
    def _entry_commodities(raw_text: str, entry: dict, role: str) -> list[tuple[str, str | None]]:
        """Try every name this location is known by — every raw OCR
        spelling that resolved to it (`_aka`, including ones that only
        got there via disambiguation and would otherwise be lost — a
        garbled mention missing a word, like "Forest Station" instead of
        "Long Forest Station", can still be the only line mentioning a
        particular commodity for this stop), plus its real terminal
        nickname/name — since the commodity-bearing line ("Collect X from
        Y") doesn't always use the same wording as whichever candidate
        happened to win resolution."""
        keys = list(entry.get("_aka") or [entry["raw"]])
        terminal = entry.get("terminal")
        if terminal:
            for k in (terminal.get("nickname"), terminal.get("name")):
                if k:
                    keys.append(k)
        qty_by_commodity = _commodity_quantities(raw_text)
        found: list[tuple[str, str | None]] = []
        seen: set[str] = set()
        for key in keys:
            for commodity, qty in _extract_commodities(raw_text, key, role, qty_by_commodity):
                ck = commodity.lower()
                if ck not in seen:
                    seen.add(ck)
                    found.append((commodity, qty))
        return found

    # ------------------------------------------------------------------
    # Route heuristic (implementation lives in routing.py)
    # ------------------------------------------------------------------
    def _plan_route(self, contracts: list[dict], route_debug: dict | None = None) -> list[tuple[int, str, int]]:
        """Visiting order over every contract's stops, starting from the
        CURRENT LOCATION picker's terminal. See routing.RoutePlanner."""
        return routing.RoutePlanner(self._locations).plan_route(
            contracts, self._current_location_terminal(), route_debug)

    def _terminal_cost(self, a: dict, b: dict) -> float:
        return routing.RoutePlanner(self._locations).terminal_cost(a, b)

    @staticmethod
    def _text_cost(a: str, b: str) -> float:
        return routing.RoutePlanner.text_cost(a, b)

    # ------------------------------------------------------------------
    # Result rendering
    # ------------------------------------------------------------------
    @staticmethod
    def _clear_layout(layout: QVBoxLayout | QHBoxLayout):
        """Remove and delete every item in `layout`, recursing into nested
        sub-layouts (e.g. route_title_row below, added via addLayout).
        `takeAt(i).widget()` is None for a sub-layout item, so a shallow
        clear leaves that sub-layout's widgets orphaned — still alive,
        still parented to the container, but no longer positioned by any
        layout — where they float at their last geometry and can visually
        cover whatever gets laid out over them on the next render."""
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
                continue
            sub_layout = item.layout()
            if sub_layout is not None:
                LogisticsHubModule._clear_layout(sub_layout)

    def _render_results(self):
        # Clear any previous contents.
        self._clear_layout(self._results_layout)

        contracts = self.settings.get("contracts", [])
        self._contracts_title.setText(f"CONTRACTS ({len(contracts)})")
        self._populate_contracts_rows(self._contracts_layout, contracts)
        self._populate_manifest_rows(self._manifest_layout, contracts)

        if contracts:
            reward = _total_reward(contracts)
            peak_scu = self._peak_cargo_scu(contracts)
            plural = "s" if len(contracts) != 1 else ""
            summary = f"{len(contracts)} contract{plural} · {reward:,} aUEC · {peak_scu} SCU peak cargo"
            capacity = self.settings.get("cargo_capacity_scu")
            over_capacity = bool(capacity) and peak_scu > capacity
            if capacity:
                if over_capacity:
                    summary += f"  ⚠ EXCEEDS {capacity} SCU CAPACITY BY {peak_scu - capacity}"
                else:
                    summary += f"  (of {capacity} SCU)"
            self._summary_label.setText(summary)
            self._summary_label.setStyleSheet(
                f"color: {theme.ACCENT_AMBER if over_capacity else theme.TEXT_MUTED}; "
                f"font-family: {theme.FONT_MONO}; font-size: {theme.fpx(9)}px; "
                f"letter-spacing: 0.5px; font-weight: {700 if over_capacity else 400};"
            )
        else:
            self._summary_label.setText("")

        self._tracker_btn.setVisible(bool(self._route_order))
        self._tracker_btn.setText("RETURN TO CARD" if self._route_popout is not None else "TRACKER")

        # Keep an already-open Tracker popout in sync unconditionally, even
        # when there are now zero stops — this used to live inside the
        # `if self._route_order:` block below, which CLEAR (or any other
        # action that empties the route) skips entirely, silently leaving
        # the popout showing whatever stale stops it had before the clear
        # until the next scan happens to repopulate it. Confirmed real
        # (2026-09-06): clicking CLEAR with the Tracker open looked like
        # old contracts "weren't fully cleared."
        if self._route_popout is not None:
            self._populate_route_rows(self._route_popout_layout, contracts, transparent_bg=True)

        if self._route_order:
            route_title = QLabel("ROUTE")
            route_title.setStyleSheet(self._title_style())
            self._results_layout.addWidget(route_title)

            # Full per-stop list, inline on the card — re-added 2026-09-07.
            # A 2026-09-05 attempt at this same thing hit rows that stayed
            # invisible until the Tracker popout had been opened once, and
            # was reverted rather than chased blind (no way to run the real
            # Qt UI in that pass). This time verified live in the running
            # app (not just code-reviewed) — see docs/DECISIONS.md,
            # 2026-09-07, for what the actual cause turned out to be. The
            # Tracker popout still exists alongside this as an optional
            # always-on-top detached window for while the game has focus;
            # both stay in sync via the same `_populate_route_rows` call.
            self._populate_route_rows(self._results_layout, contracts)
            if self._route_popout is not None:
                self._results_layout.addWidget(self._info_label(
                    "Also open in the detached Tracker window."
                ))

        self._results_layout.addWidget(self._info_label(
            "Best-effort OCR + UEX matching. Verify against the actual "
            "in-game contracts before committing to a route."
        ))

        if self._card_widget is not None:
            self._card_widget.apply_size()

    def _populate_route_rows(
        self, target_layout: QVBoxLayout, contracts: list[dict], transparent_bg: bool = False
    ):
        while target_layout.count():
            item = target_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        route_done = set(self.settings.get("route_done", []))
        for idx, node in enumerate(self._route_order, start=1):
            described = self._describe_stop(contracts, node)
            if described is None:
                continue
            label, route_key = described
            target_layout.addWidget(
                self._route_row(
                    f"{idx}. {label}",
                    route_key,
                    done=route_key in route_done,
                    transparent_bg=transparent_bg,
                )
            )

    def _stop_entry(self, contracts: list[dict], node) -> tuple[dict, str] | None:
        """The pickup/dropoff entry dict + role a route node points at, or
        `None` if the node's contract/index no longer exists (shouldn't
        happen for a route built from the current contract list, but never
        crash the card over a stale node). Shared lookup behind
        `_describe_stop` and `_peak_cargo_scu` below — was previously
        duplicated inline in `_populate_route_rows` only."""
        i, role, j = node
        contract = contracts[i] if i < len(contracts) else None
        if contract is None:
            return None
        key = "pickups" if role == "pickup" else "dropoffs"
        items = contract.get(key, [])
        entry = items[j] if j < len(items) else {}
        return entry, role

    def _describe_stop(self, contracts: list[dict], node) -> tuple[str, str] | None:
        """One route node as `(display_text, route_key)` — `display_text`
        has no numbering prefix, so both the numbered route list and the
        unnumbered NEXT STOP banner can use it as-is."""
        resolved = self._stop_entry(contracts, node)
        if resolved is None:
            return None
        entry, role = resolved
        i, _role, j = node
        contract = contracts[i]
        terminal = entry.get("terminal")
        raw = entry.get("raw", "??")
        label_text = self._locations.display_name(terminal) if terminal else None
        display = label_text or f"{raw} (unresolved)"
        role_tag = "PICKUP" if role == "pickup" else "DROPOFF"
        cargo_text = f" — {_cargo_label(entry.get('commodities'))}"
        route_key = f"{contract.get('id')}:{role}:{j}"
        return f"[{role_tag}] {display}{cargo_text}", route_key

    def _peak_cargo_scu(self, contracts: list[dict], route_order: list | None = None) -> int:
        """The largest amount of cargo actually in the hold at any point
        along the *planned* route — not a flat sum of every pickup, which
        would overstate the ship size needed whenever some cargo gets
        dropped off before more is picked up. Walks `route_order` (defaults
        to `self._route_order`, the currently-active route — pass an
        explicit route, e.g. from a hypothetical candidate-included
        `_plan_route()` call, to check a contract not yet added) in order,
        +SCU on a pickup, -SCU on a dropoff, tracking the running peak."""
        if route_order is None:
            route_order = self._route_order
        current = 0
        peak = 0
        for node in route_order:
            resolved = self._stop_entry(contracts, node)
            if resolved is None:
                continue
            entry, role = resolved
            scu = _entry_scu(entry)
            current += scu if role == "pickup" else -scu
            peak = max(peak, current)
        return peak

    def _toggle_route_popout(self):
        if self._route_popout is not None:
            self._on_route_popout_closed()
        else:
            self._open_route_popout()

    def _make_always_on_top_window(
        self, title_html: str, on_close, geometry: dict | None, opacity_pct: int
    ) -> tuple[QWidget, QVBoxLayout, QSlider]:
        """Shared shell for a detached, always-on-top, frameless window
        (only the ROUTE popout uses this today — the CONTRACTS list popup
        was tried and reverted, see DECISIONS.md). Frameless means there's
        no OS title bar and no OS close button, so both are built here:
        a small header styled like mobiOverlay's own main window
        (host/main_window.py's _TitleBar), draggable the same way, with a
        close button wired to `on_close` instead of a Qt close event.

        Opacity fades only the window's own void background, not the
        header/content on top of it — same per-pixel-alpha technique as
        host/main_window.py's MainWindow.paintEvent (setWindowOpacity was
        tried first and rejected: it dims the *entire* rendered surface
        uniformly, including text, which is exactly what was asked not to
        happen)."""
        win = QWidget()
        # WindowDoesNotAcceptFocus: this is Qt.Window (not Qt.Tool like the
        # main window), which on Windows can grab OS foreground focus both
        # on first show and whenever an always-on-top window's z-order gets
        # re-evaluated — plausible cause of the game occasionally losing
        # focus while this is open. Mouse clicks (slider, close button,
        # route-stop toggling) are unaffected; only keyboard/foreground
        # activation is blocked. Added 2026-09-05, see DECISIONS.md.
        win.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
        win.setAttribute(Qt.WA_TranslucentBackground, True)
        win.resize(420, 480)
        win.setMinimumSize(240, 160)
        if geometry:
            win.setGeometry(geometry["x"], geometry["y"], geometry["w"], geometry["h"])

        paint_state = {"opacity": opacity_pct / 100.0}

        def win_paint_event(event):
            painter = QPainter(win)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setCompositionMode(QPainter.CompositionMode_Source)
            painter.fillRect(win.rect(), Qt.transparent)
            color = QColor(theme.BG_VOID)
            color.setAlphaF(paint_state["opacity"])
            path = QPainterPath()
            path.addRoundedRect(QRectF(win.rect()), theme.RADIUS, theme.RADIUS)
            painter.fillPath(path, color)
            # Same border treatment as a Logistics Hub Card (see
            # card.py's _apply_border) — full opacity regardless of the
            # window fade above, since chrome (not content) shouldn't wash
            # out. Stroked on an inset rect, not the fill rect, so the 1px
            # line isn't half-clipped at the window's true edge.
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            stroke_path = QPainterPath()
            stroke_rect = QRectF(win.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
            stroke_path.addRoundedRect(stroke_rect, theme.RADIUS, theme.RADIUS)
            painter.setPen(QPen(QColor(theme.ACCENT_CYAN), 1))
            painter.drawPath(stroke_path)
            painter.end()

        win.paintEvent = win_paint_event

        outer = QVBoxLayout(win)
        outer.setContentsMargins(1, 1, 1, 1)
        outer.setSpacing(0)

        header = QWidget()
        header.setFixedHeight(30)
        header.setStyleSheet(f"background: {theme.BG_PANEL}; border-bottom: 1px solid {theme.BORDER_FLAT};")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 0, 8, 0)

        title_label = QLabel(title_html)
        title_label.setTextInteractionFlags(Qt.NoTextInteraction)
        title_label.setStyleSheet(
            f"font-family: {theme.FONT_DISPLAY}; font-weight: 700; "
            f"font-size: {theme.fpx(10)}px; letter-spacing: 1px;"
        )
        header_layout.addWidget(title_label)
        header_layout.addStretch()

        # Own opacity control — fully local to this window instance, no
        # shared config, no coupling to the main window's or any card's
        # opacity setting. Persisted to module settings on close.
        opacity_slider = QSlider(Qt.Horizontal)
        opacity_slider.setFixedWidth(70)
        opacity_slider.setRange(30, 100)
        opacity_slider.setValue(opacity_pct)
        opacity_slider.setToolTip("Tracker window opacity (independent of the rest of the UI)")

        def on_opacity_changed(v):
            paint_state["opacity"] = v / 100.0
            win.update()

        opacity_slider.valueChanged.connect(on_opacity_changed)
        header_layout.addWidget(opacity_slider)

        close_btn = QPushButton("✕")
        close_btn.setObjectName("cardIconBtn")
        close_btn.setFixedSize(20, 20)
        close_btn.clicked.connect(on_close)
        header_layout.addWidget(close_btn)

        drag_state = {"offset": None}

        def header_mouse_press(event):
            if event.button() == Qt.LeftButton:
                drag_state["offset"] = event.globalPosition().toPoint() - win.pos()

        def header_mouse_move(event):
            if drag_state["offset"] is not None:
                win.move(event.globalPosition().toPoint() - drag_state["offset"])

        def header_mouse_release(event):
            drag_state["offset"] = None

        header.mousePressEvent = header_mouse_press
        header.mouseMoveEvent = header_mouse_move
        header.mouseReleaseEvent = header_mouse_release

        outer.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            f"""
            QScrollArea {{ background: transparent; border: 1px solid {theme.BORDER_FLAT};
                border-radius: {theme.RADIUS}px; }}
            QScrollBar:vertical {{ background: {theme.BG_VOID}; width: 8px; margin: 2px;
                border-radius: 4px; }}
            QScrollBar::handle:vertical {{ background: {theme.BORDER_FLAT}; border-radius: 4px;
                min-height: 24px; }}
            QScrollBar::handle:vertical:hover {{ background: {theme.ACCENT_CYAN}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
            QScrollBar:horizontal {{ height: 0px; }}
            """
        )
        # QScrollArea's internal viewport widget autofills with the
        # palette's (grey) Base color regardless of the QSS "background:
        # transparent" above, which only styles the frame — this is what
        # was showing as an opaque grey card behind every row. Both the
        # viewport and the content widget it hosts need to opt out too.
        scroll.viewport().setAutoFillBackground(False)
        scroll.viewport().setStyleSheet("background: transparent;")
        content = QWidget()
        content.setAutoFillBackground(False)
        content.setStyleSheet("background: transparent;")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(6, 6, 6, 6)
        content_layout.setSpacing(2)
        scroll.setWidget(content)
        outer.addWidget(scroll)

        grip_row = QHBoxLayout()
        grip_row.setContentsMargins(0, 0, 4, 2)
        grip_row.addStretch()
        size_grip = QSizeGrip(win)
        size_grip.setFixedSize(14, 14)
        size_grip.setStyleSheet("background: transparent;")

        def grip_paint_event(event):
            painter = QPainter(size_grip)
            painter.setRenderHint(QPainter.Antialiasing)
            pen = QPen(QColor(theme.ACCENT_CYAN), 1.5)
            painter.setPen(pen)
            w, h = size_grip.width(), size_grip.height()
            # Three diagonal strokes fanning from the bottom-right corner —
            # the drag-resize affordance, styled to match the window's
            # cyan chrome instead of the OS's default grey dot grip.
            for offset in (3, 7, 11):
                painter.drawLine(w - 2, h - offset, w - offset, h - 2)
            painter.end()

        size_grip.paintEvent = grip_paint_event
        grip_row.addWidget(size_grip)
        outer.addLayout(grip_row)

        return win, content_layout, opacity_slider

    def _open_route_popout(self):
        geometry = self.settings.get("tracker_geometry")
        opacity_pct = self.settings.get("tracker_opacity_pct", 100)
        title_html = (
            f'<span style="color:{theme.TEXT_PRIMARY};">mobi</span>'
            f'<span style="color:{theme.ACCENT_CYAN};">Logistics</span>'
        )
        popout, content_layout, opacity_slider = self._make_always_on_top_window(
            title_html, self._on_route_popout_closed, geometry, opacity_pct
        )
        self._route_popout_opacity_slider = opacity_slider

        self._route_popout = popout
        self._route_popout_layout = content_layout

        # Own reminder banner, added 2026-09-08 — inserted into the
        # popout's OUTER layout (index 1: right after the header, before
        # the scroll area), never into `content_layout` itself, since
        # `_populate_route_rows()` clears `content_layout` completely on
        # every render and would delete a banner living there.
        self._popout_reminder_banner = _ReminderBanner(self._dismiss_accept_reminder)
        self._popout_reminder_banner.setVisible(False)
        popout.layout().insertWidget(1, self._popout_reminder_banner)
        # A reminder already active when the Tracker is opened (e.g. it
        # fired while the popout was closed) must show up here too, not
        # just wait for the next `_show_accept_reminder`/blink tick.
        if self._reminder_text is not None:
            self._popout_reminder_banner.setText(self._reminder_text)
            self._popout_reminder_banner.setVisible(True)

        popout.show()
        self._render_results()

    def _on_route_popout_closed(self):
        if self._route_popout is not None:
            geo = self._route_popout.geometry()
            self.settings["tracker_geometry"] = {
                "x": geo.x(), "y": geo.y(), "w": geo.width(), "h": geo.height(),
            }
            if self._route_popout_opacity_slider is not None:
                self.settings["tracker_opacity_pct"] = self._route_popout_opacity_slider.value()
            self._save_settings()
            self._route_popout.close()
        self._route_popout = None
        self._route_popout_layout = None
        self._route_popout_opacity_slider = None
        self._popout_reminder_banner = None
        self._render_results()

    def _populate_contracts_rows(self, target_layout: QVBoxLayout, contracts: list[dict]):
        while target_layout.count():
            item = target_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        if not contracts:
            target_layout.addWidget(self._info_label(
                "No contracts yet. Frame one mission's pickup/drop-off "
                "text and click SCAN CONTRACT."
            ))
        else:
            for c in contracts:
                target_layout.addWidget(self._contract_row(c))
                for note in c.get("ambiguous", []):
                    target_layout.addWidget(self._ambiguous_row(note))

    @staticmethod
    def _freight_manifest(contracts: list[dict]) -> dict:
        """Commodity name -> total SCU and contract count. See grading.freight_manifest."""
        return grading.freight_manifest(contracts)

    # ------------------------------------------------------------------
    # Ship/location compatibility feedback DB + contract grading
    # (Part 3 of the confirm-gate/grading plan, 2026-09-07 — see
    # docs/DECISIONS.md). No reliable static source exists for which
    # locations physically support which ships (checked against real
    # sources, an AI-generated table was found partly fabricated) — so
    # instead of guessing, this asks GOOD/BAD once per (ship, location)
    # pair it hasn't seen, remembers the answer, and starts empty rather
    # than wrong.
    # ------------------------------------------------------------------
    @staticmethod
    def _compat_key(ship: str, terminal: dict) -> str:
        return grading.compat_key(ship, terminal)

    @staticmethod
    def _contract_terminals(contract: dict) -> list[dict]:
        """Every resolved pickup/dropoff terminal in a contract. See grading.contract_terminals."""
        return grading.contract_terminals(contract)

    def _rate_compatibility(self, ship: str, terminal: dict, good: bool) -> None:
        ratings = self.settings.setdefault("ship_location_ratings", {})
        ratings[self._compat_key(ship, terminal)] = "good" if good else "bad"
        self._save_settings()

    def _grade_contract(self, contract: dict, existing_contracts: list[dict]) -> tuple[int | None, str, bool]:
        """0-100 score + one-line reason + whether a hard warning capped it, or
        `(None, prompt, False)` without a Hauler Profile. See grading.grade_contract."""
        return grading.grade_contract(
            contract,
            existing_contracts,
            profile=self.settings.get("hauler_profile"),
            ratings=self.settings.get("ship_location_ratings"),
            capacity=self.settings.get("cargo_capacity_scu"),
            thresholds=self.settings.get("grading_thresholds"),
            current_terminal=self._current_location_terminal(),
            pickup_scu=sum(_entry_scu(e) for e in contract.get("pickups", [])),
            display_name=self._locations.display_name,
            plan_route=self._plan_route,
            peak_cargo_scu=self._peak_cargo_scu,
        )

    def _populate_manifest_rows(self, target_layout: QVBoxLayout, contracts: list[dict]):
        while target_layout.count():
            item = target_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        manifest = self._freight_manifest(contracts)
        if not manifest:
            target_layout.addWidget(self._info_label(
                "Nothing hauled yet — commodities appear here once a "
                "contract is scanned."
            ))
            return

        for name in sorted(manifest.keys()):
            row = manifest[name]
            scu, count = row["scu"], row["contract_count"]
            if count > 1:
                target_layout.addWidget(self._ambiguous_row(
                    f"{name} — {scu} SCU total, split across {count} "
                    "contracts — the game will not let you tell these "
                    "apart once picked up"
                ))
            else:
                label = QLabel(f"{name} — {scu} SCU" if scu else name)
                label.setWordWrap(True)
                label.setStyleSheet(
                    f"background: {theme.BG_PANEL}; color: {theme.TEXT_PRIMARY}; "
                    f"border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px; "
                    f"padding: 5px 8px; font-family: {theme.FONT_MONO}; "
                    f"font-size: {theme.fpx(10)}px;"
                )
                target_layout.addWidget(label)

    @staticmethod
    def _title_style() -> str:
        return (
            f"color: {theme.ACCENT_CYAN}; font-family: {theme.FONT_DISPLAY}; "
            f"font-weight: 800; font-size: {theme.fpx(11)}px; letter-spacing: 2px;"
        )

    @staticmethod
    def _entry_names(entries: list[dict], display_name) -> str:
        names = []
        for e in entries:
            base = display_name(e["terminal"]) if e.get("terminal") else f"{e.get('raw', '??')} (unresolved)"
            names.append(f"{base} ({_cargo_label(e.get('commodities'))})")
        return " / ".join(names) if names else "??"

    def _contract_row(self, contract: dict) -> QWidget:
        pickups_text = self._entry_names(contract.get("pickups", []), self._locations.display_name)
        dropoffs_text = self._entry_names(contract.get("dropoffs", []), self._locations.display_name)
        reward = contract.get("reward")
        reward_text = f"  ·  {reward} aUEC" if reward else ""

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(4)

        label = QLabel(f"{pickups_text} → {dropoffs_text}{reward_text}")
        label.setWordWrap(True)
        label.setStyleSheet(
            f"background: {theme.BG_PANEL}; color: {theme.TEXT_PRIMARY}; "
            f"border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px; "
            f"padding: 5px 8px; font-family: {theme.FONT_MONO}; "
            f"font-size: {theme.fpx(10)}px;"
        )
        row_layout.addWidget(label, 1)

        remove_btn = QPushButton("✕")
        remove_btn.setToolTip("Remove this contract")
        remove_btn.setFixedWidth(22)
        remove_btn.setStyleSheet(
            f"background: {theme.BG_VOID}; color: {theme.ACCENT_AMBER}; "
            f"border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px; "
            f"font-family: {theme.FONT_MONO}; font-size: {theme.fpx(10)}px;"
        )
        remove_btn.clicked.connect(lambda: self._remove_contract(contract.get("id")))
        row_layout.addWidget(remove_btn)

        return row

    def _remove_contract(self, contract_id: str | None):
        contracts = self.settings.get("contracts", [])
        self.settings["contracts"] = [c for c in contracts if c.get("id") != contract_id]
        self._save_settings()
        if self.settings["contracts"]:
            self._route_order = self._plan_route(self.settings["contracts"])
        else:
            self._route_order = []
        self._render_results()
        self._set_status("Contract removed.")

    def _route_row(self, text: str, route_key: str, done: bool, transparent_bg: bool = False) -> QWidget:
        row = QLabel(text)
        row.setWordWrap(True)
        row.setCursor(Qt.PointingHandCursor)
        row.setToolTip("Click to mark this stop done/skipped")
        # In the Tracker popout, each row's own solid background would sit
        # as an opaque "card" on top of the window's faded void, making the
        # opacity slider barely visible — transparent here so the row's
        # background fades with the window while the text itself (drawn on
        # top by Qt, not affected by a background fill) stays fully legible.
        bg = "transparent" if transparent_bg else theme.BG_VOID
        if done:
            row.setStyleSheet(
                f"background: {bg}; color: {theme.TEXT_DIM}; "
                f"border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px; "
                f"padding: 5px 8px; font-family: {theme.FONT_MONO}; "
                f"font-size: {theme.fpx(10)}px; text-decoration: line-through;"
            )
        else:
            row.setStyleSheet(
                f"background: {bg}; color: {theme.ACCENT_CYAN}; "
                f"border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px; "
                f"padding: 5px 8px; font-family: {theme.FONT_MONO}; "
                f"font-size: {theme.fpx(10)}px;"
            )
        row.mousePressEvent = lambda event: self._toggle_route_done(route_key)
        return row

    def _toggle_route_done(self, route_key: str):
        route_done = set(self.settings.get("route_done", []))
        if route_key in route_done:
            route_done.discard(route_key)
        else:
            route_done.add(route_key)
        self.settings["route_done"] = list(route_done)
        self._save_settings()
        self._render_results()

    def _ambiguous_row(self, text: str) -> QWidget:
        """A location phrase that matched more than one distinct real
        place (see the `ambiguous` note in `_build_contract`) — surfaced
        visibly rather than silently guessing one and possibly being
        wrong. Amber, same as the card's own error-state accent."""
        row = QLabel(f"⚠ {text}")
        row.setWordWrap(True)
        row.setStyleSheet(
            f"background: {theme.ACCENT_AMBER_DIM}; color: {theme.ACCENT_AMBER}; "
            f"border: 1px solid {theme.ACCENT_AMBER}; border-radius: {theme.RADIUS}px; "
            f"padding: 5px 8px; font-family: {theme.FONT_MONO}; "
            f"font-size: {theme.fpx(9)}px;"
        )
        return row

    def _info_label(self, text: str) -> QWidget:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-family: {theme.FONT_MONO}; "
            f"font-size: {theme.fpx(8)}px;"
        )
        return label


MODULE_CLASS = LogisticsHubModule
