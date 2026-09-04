"""Logistics Hub – OCR driven hauling mission board helper.

Captures a user‑selected region of the screen (over the in‑game mission
board), runs OCR against the captured image, extracts potential mission
stops, and recommends a visiting order based on a lightweight travel
heuristic.

The module lives entirely under ``modules/logistics_hub/`` and intentionally
does **not** use any host‑side screen‑capture or OCR helpers.  All new
third‑party dependencies are declared in the local :file:`requirements.txt`
so the base project stays clean.

Chosen OCR engine: **pytesseract** – small, permissively licensed
(Apache 2.0), and fine for UI text when the region is cropped tightly.
The tradeoff is that it requires a real Tesseract binary installed
separately on the machine.

Route optimization uses a simple nearest‑neighbour heuristic; it is not
guaranteed to be optimal, but it is deterministic and cheap.
"""
import re
import time
from pathlib import Path

from PySide6.QtCore import Qt, QRect, QPoint, QTimer, Signal
from PySide6.QtGui import (
    QGuiApplication,
    QImage,
    QPainter,
    QColor,
    QPen,
    QCursor,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from host import theme
from host.module_base import ModuleBase

# ---------------------------------------------------------------------------
# Optional third‑party dependencies – imported lazily so the module can still
# load if the user has not yet installed the local requirements.txt.
# ---------------------------------------------------------------------------
try:
    import pytesseract  # type: ignore
    from PIL import Image, ImageOps  # type: ignore

    OCR_AVAILABLE = True
except ImportError:
    pytesseract = None  # type: ignore
    Image = None  # type: ignore
    ImageOps = None  # type: ignore
    OCR_AVAILABLE = False

AUTO_RESCAN_MS = 5 * 60 * 1000  # 5 minutes, off by default


def _parse_ocr_line_to_stop(line: str) -> dict | None:
    """Best‑effort conversion of one OCR line into a mission stop record.

    This is intentionally tolerant because mission boards in Star Citizen can
    vary between different game patches, languages, and monitor resolutions.
    The returned dict uses the keys ``pickup``, ``dropoff``, ``reward`` and
    ``raw``.
    """
    clean = " ".join(line.split())
    if not clean:
        return None

    if not re.search(r"(pick\s?up|pickup|drop\s?off|deliver|delivery|source|to\s)", clean, re.I):
        return None

    # The last token‑ish sequence is the most likely location reference on
    # the row.  Keep it short so route display stays readable.
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9]*(?:\s+[A-Za-z0-9]+)*", clean)
    location = tokens[-1] if tokens else clean

    reward = None
    m = re.search(r"([\d,]+)\s*(?:aUEC|auec|credits|reward)", clean, re.I)
    if m:
        reward = m.group(1)

    return {
        "pickup": clean,
        "dropoff": location,
        "reward": reward,
        "raw": clean,
    }


class _RegionSelector(QWidget):
    """Full‑screen transparent widget used to drag‑draw a capture rectangle.

    Only shows on the screen where the cursor is at the moment the user
    clicks “SELECT REGION”.  Coordinates emitted in global desktop space.
    """

    selected = Signal(QRect)

    def __init__(self, screen):
        super().__init__()
        self._screen = screen
        self._start = None
        self._end = None

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setCursor(Qt.CrossCursor)
        self.setFocusPolicy(Qt.StrongFocus)

        geo = screen.geometry()
        self.setGeometry(geo)
        self.show()
        self.raise_()
        self.setFocus(Qt.OtherFocusReason)

    # ---- painting -----------------------------------------------------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        # Dim the whole screen slightly so the capture rectangle stands out.
        painter.fillRect(self.rect(), QColor(0, 0, 0, 70))

        if self._start is not None and self._end is not None:
            rect = QRect(self._start, self._end).normalized()

            # translucent cyan fill behind the future capture boundaries
            brush = QColor(theme.ACCENT_CYAN)
            brush.setAlpha(70)
            painter.fillRect(rect, brush)

            pen = QPen(QColor(theme.ACCENT_CYAN), 1, Qt.DashLine)
            painter.setPen(pen)
            painter.drawRect(rect.adjusted(0, 0, -1, -1))

    # ---- mouse/key handling -------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._start = event.position().toPoint()
            self._end = None
            self.update()

    def mouseMoveEvent(self, event):
        if self._start is not None:
            self._end = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):
        if (
            event.button() == Qt.LeftButton
            and self._start is not None
            and self._end is not None
        ):
            local_rect = QRect(self._start, self._end).normalized()
            global_top_left = self._screen.geometry().topLeft() + local_rect.topLeft()
            self.selected.emit(QRect(global_top_left, local_rect.size()))
        self._finish()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._finish()
        else:
            super().keyPressEvent(event)

    def _finish(self):
        self._start = None
        self._end = None
        self.close()
        self.deleteLater()


class LogisticsHubModule(ModuleBase):
    module_id = "logistics_hub"
    display_name = "Logistics Hub"

    def __init__(self, api_client, config):
        super().__init__(api_client, config)
        self._selector = None
        self._timer = None
        self._stops = []
        self._order = []
        self._card_widget = None

    # ------------------------------------------------------------------
    # Card construction
    # ------------------------------------------------------------------
    def create_card(self, container):
        card = container.add_card(self.module_id, self.display_name)
        self._card_widget = card
        layout = card.body_layout

        # ---- region status row --------------------------------------
        region_row = QHBoxLayout()
        self._region_label = QLabel("Region: not set")
        self._region_label.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-family: {theme.FONT_MONO}; "
            f"font-size: {theme.fpx(9)}px; letter-spacing: 1px;"
        )
        region_row.addWidget(self._region_label, 1)

        select_btn = QPushButton("SELECT REGION")
        select_btn.setStyleSheet(
            f"background: {theme.BG_VOID}; color: {theme.ACCENT_CYAN}; "
            f"border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px; "
            f"padding: 4px 8px; font-family: {theme.FONT_DISPLAY}; font-weight: 700; "
            f"font-size: {theme.fpx(11)}px;"
        )
        select_btn.clicked.connect(self._select_region)
        region_row.addWidget(select_btn)
        layout.addLayout(region_row)

        # ---- action row ---------------------------------------------
        action_row = QHBoxLayout()
        self._status_label = QLabel("Ready")
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet(
            f"color: {theme.TEXT_PRIMARY}; font-family: {theme.FONT_MONO}; "
            f"font-size: {theme.fpx(9)}px;"
        )
        action_row.addWidget(self._status_label, 1)

        scan_btn = QPushButton("SCAN MISSION BOARD")
        scan_btn.setStyleSheet(
            f"background: {theme.BG_VOID}; color: {theme.ACCENT_CYAN}; "
            f"border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px; "
            f"padding: 4px 8px; font-family: {theme.FONT_DISPLAY}; font-weight: 700; "
            f"font-size: {theme.fpx(11)}px;"
        )
        scan_btn.clicked.connect(self._safe_scan)
        action_row.addWidget(scan_btn)
        layout.addLayout(action_row)

        # ---- optional auto-rescan toggle -----------------------------
        auto_row = QHBoxLayout()
        self._auto_check = QCheckBox("AUTO RESCAN")
        self._auto_check.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-family: {theme.FONT_MONO}; "
            f"font-size: {theme.fpx(9)}px;"
        )
        self._auto_check.setChecked(bool(self.settings.get("auto_rescan")))
        self._auto_check.toggled.connect(self._toggle_auto_rescan)
        auto_row.addWidget(self._auto_check)
        auto_row.addStretch()
        layout.addLayout(auto_row)

        # ---- scrollable stops / route list ---------------------------
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
        self._results_scroll.setMaximumHeight(320)

        # Timer for opt-in 5-minute auto rescanning.
        self._timer = QTimer(card)
        self._timer.setInterval(AUTO_RESCAN_MS)
        self._timer.timeout.connect(self._safe_scan)
        if self.settings.get("auto_rescan"):
            self._timer.start()

        self._refresh_region_label()
        card.apply_size()
        return card

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
        if self._status_label is not None:
            self._status_label.setText(msg)

    def _clear_error_state(self):
        """Make sure the card body (with the SELECT REGION button) is visible
        even if the host previously put this card into its error state due to
        a missing capture region."""
        card = getattr(self, "_card_widget", None)
        if card is not None:
            card.clear_error()

    def _select_region(self):
        screen = QGuiApplication.screenAt(QCursor.pos())
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:  # practically never happens on Windows
            return
        selector = _RegionSelector(screen)
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

    def _toggle_auto_rescan(self, enabled: bool):
        self.settings["auto_rescan"] = bool(enabled)
        self._save_settings()
        if enabled:
            self._timer.start()
            self._set_status("Auto rescan enabled.")
        else:
            self._timer.stop()
            self._set_status("Auto rescan disabled.")

    def _save_settings(self):
        self.config.set_module_settings(self.module_id, self.settings)

    def _safe_scan(self):
        try:
            self.refresh()
        except Exception as exc:
            self._set_status(f"Error: {exc}")

    # ------------------------------------------------------------------
    # ModuleBase refresh
    # ------------------------------------------------------------------
    def refresh(self):
        """Read the selected region, run OCR, parse stops, and show the
        recommended visiting order."""
        region = self.settings.get("region")
        if not region:
            self._set_status("No capture region set — use SELECT REGION on the card first.")
            self._clear_error_state()
            return
        if not OCR_AVAILABLE:
            raise RuntimeError(
                "pytesseract/PIL not installed. Run:\n"
                "  pip install -r modules/logistics_hub/requirements.txt"
            )

        pix = self._grab_region(region)
        raw_text = self._ocr(pix)

        stops = [
            parsed
            for candidate in raw_text.splitlines()
            if (parsed := _parse_ocr_line_to_stop(candidate))
        ]

        if not stops:
            raise ValueError("No mission stops could be OCR'd — try adjusting the region or brightness.")

        self._stops = stops
        self._order = self._plan_route(stops)
        self._render_results()
        self._set_status(
            f"Scanned {len(stops)} stop(s) at {time.strftime('%H:%M:%S')}"
        )

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
        """Runs Tesseract over the given QPixmap and returns raw text."""
        # Convert QPixmap → QImage → PIL image.
        qimg = pixmap.toImage().convertToFormat(QImage.Format_RGBA8888)
        ptr = qimg.bits()
        ptr.setsize(qimg.sizeInBytes())
        pil_rgba = Image.frombuffer(
            "RGBA", (qimg.width(), qimg.height()), ptr, "raw", "RGBA", 0, 1
        )
        pil_rgb = pil_rgba.convert("RGB")

        gray = ImageOps.grayscale(pil_rgb)
        gray = ImageOps.autocontrast(gray)
        return pytesseract.image_to_string(gray)

    # ------------------------------------------------------------------
    # Route heuristic
    # ------------------------------------------------------------------
    def _plan_route(self, stops: list[dict]) -> list[int]:
        """Nearest‑neighbour visiting order using a crude travel‑cost metric.

        “Travel” cost is inferred from how much the two location labels
        share system/planet tokens.  It is intentionally simple; a real
        in‑game distance table would need UEX coordinates that we do not
        have from an OCR pass.
        """
        n = len(stops)
        if n <= 2:
            return list(range(n))

        visited = [False] * n
        order = [0]
        visited[0] = True
        current = 0

        for _ in range(n - 1):
            best = None
            best_cost = None
            for nxt in range(n):
                if visited[nxt]:
                    continue
                cost = self._location_cost(
                    stops[current].get("dropoff", ""),
                    stops[nxt].get("dropoff", ""),
                )
                if best_cost is None or cost < best_cost:
                    best_cost = cost
                    best = nxt
            visited[best] = True
            order.append(best)
            current = best

        return order

    @staticmethod
    def _location_cost(a: str, b: str) -> int:
        """A back‑of‑the‑envelope “travel distance”.

        We check whether the two texts look like the same system, same
        planet/city cluster, or something entirely different.  Not accurate
        to SC’s real layout, but enough to push obviously related stops next
        to each other.
        """
        if not a or not b:
            return 3

        a_low = a.lower()
        b_low = b.lower()
        if a_low == b_low:
            return 0

        known_systems = {
            "stanton", "pyro", "nyx", "crusader", "orison",
            "hurston", "microtech", "arcorp", "terra",
        }
        asys = [s for s in known_systems if s in a_low]
        bsys = [s for s in known_systems if s in b_low]

        if asys and bsys:
            if asys[0] == bsys[0]:
                return 1
            return 4

        tokens_a = set(re.findall(r"[a-z0-9']+", a_low))
        tokens_b = set(re.findall(r"[a-z0-9']+", b_low))
        if tokens_a & tokens_b:
            return 2
        return 3

    # ------------------------------------------------------------------
    # Result rendering
    # ------------------------------------------------------------------
    def _render_results(self):
        # Clear any previous contents.
        while self._results_layout.count():
            item = self._results_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        title = QLabel("SUGGESTED ORDER")
        title.setStyleSheet(
            f"color: {theme.ACCENT_CYAN}; font-family: {theme.FONT_DISPLAY}; "
            f"font-weight: 800; font-size: {theme.fpx(11)}px; letter-spacing: 2px;"
        )
        self._results_layout.addWidget(title)

        for idx, stop_idx in enumerate(self._order, start=1):
            stop = self._stops[stop_idx]
            drop = stop.get("dropoff") or "??"
            reward = stop.get("reward")
            if reward:
                row_text = f"{idx}.  {drop}  ·  {reward} aUEC"
            else:
                row_text = f"{idx}.  {drop}"

            row = QLabel(row_text)
            row.setWordWrap(True)
            row.setStyleSheet(
                f"background: {theme.BG_PANEL}; color: {theme.TEXT_PRIMARY}; "
                f"border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px; "
                f"padding: 5px 8px; font-family: {theme.FONT_MONO}; "
                f"font-size: {theme.fpx(10)}px;"
            )
            self._results_layout.addWidget(row)

        extra = QLabel("")
        extra.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-family: {theme.FONT_MONO}; "
            f"font-size: {theme.fpx(8)}px;"
        )
        extra.setWordWrap(True)
        extra.setText(
            "Best‑effort OCR/order. Mission‑board text changes between patches;\n"
            "verify the final list against the actual available contracts."
        )
        self._results_layout.addWidget(extra)

        # Let the host know the card's content size may have changed.
        if self._card_widget is not None:
            self._card_widget.apply_size()


MODULE_CLASS = LogisticsHubModule
