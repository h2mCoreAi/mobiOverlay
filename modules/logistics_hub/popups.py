"""Logistics Hub popup widgets: the clickable accept-reminder banner, the
screen-region selector, the contract review popup and the Hauler Profile
popup. Qt only — no OCR, parsing or route logic lives here; the module hands
each popup the data it shows and callbacks for what the user chose.

Loaded by modules/logistics_hub/module.py by file path.
"""
import importlib.util
import os
import sys

from PySide6.QtCore import Qt, QRect, Signal
from PySide6.QtGui import QColor, QIntValidator, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from host import theme


def _sibling(name: str, filename: str):
    """The already-loaded sibling module (module.py registers each one in
    sys.modules), or load it by file path if this file is imported alone."""
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(name, os.path.join(os.path.dirname(__file__), filename))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


DEFAULT_GRADING_THRESHOLDS = _sibling("mobioverlay_logistics_hub_grading", "grading.py").DEFAULT_GRADING_THRESHOLDS

# Hauler Profile choices (added 2026-09-07) — fixed, small option sets
# rather than free text, so grading (a later part of the same plan) has
# a closed set of values to branch on instead of parsing arbitrary text.
# Ship is the one free-text field (no reliable static ship-data source —
# see docs/DECISIONS.md) and doubles as the key for the ship/location
# compatibility feedback database.
PROFILE_GOAL_CHOICES = ["Profit", "Reputation", "Keep Busy"]
PROFILE_RISK_CHOICES = ["Safe systems only", "Moderate", "Will run risky routes for good pay"]
PROFILE_TIME_CHOICES = ["Quick (<30 min)", "Medium", "Long session"]
PROFILE_REGION_CHOICES = ["Current system only", "Willing to cross jump points"]

# How long after ACCEPT to wait before rechecking Game.log and, if it's
# still unmatched, showing the blinking in-game-accept reminder — added
# 2026-09-08. A placeholder guess, same spirit as gamelog_verify's window
# constant: expected to need tuning against real
# `nearest_haul_event_gap_seconds` data once more sessions run, hence a
# plain user-editable field (Hauler Profile popup) rather than something
# baked in harder. 0 disables the reminder entirely.
DEFAULT_ACCEPT_REMINDER_SECONDS = 30


class _ReminderBanner(QLabel):
    """A clickable, word-wrapping stand-in for the accept-reminder banner.

    Was a QPushButton — Qt doesn't wrap QPushButton text regardless of
    stylesheet, which clipped the message in the narrower Tracker popout
    (see docs/PROGRESS.md, 2026-09-08 known issue). QLabel supports real
    word-wrap; `mousePressEvent` below preserves the original "any click
    anywhere on it dismisses" behavior a QPushButton gave for free.
    """

    def __init__(self, on_click):
        super().__init__("")
        self._on_click = on_click
        self.setWordWrap(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setAlignment(Qt.AlignCenter)

    def mousePressEvent(self, event):
        self._on_click()
        super().mousePressEvent(event)

    def click(self):
        """Programmatic dismiss, matching the QPushButton API this replaced."""
        self._on_click()


class _RegionSelector(QWidget):
    """Full‑screen transparent widget used to drag‑draw a capture rectangle.

    Only shows on the screen where the cursor is at the moment the user
    clicks “SET SCAN AREA”.  Coordinates emitted in global desktop space.
    """

    selected = Signal(QRect)

    def __init__(self, desktop_rect: QRect):
        super().__init__()
        self._desktop_rect = desktop_rect
        self._start = None
        self._end = None

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setCursor(Qt.CrossCursor)
        self.setFocusPolicy(Qt.StrongFocus)

        self.setGeometry(desktop_rect)
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
            global_top_left = self.geometry().topLeft() + local_rect.topLeft()
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


class _ReviewPopup(QWidget):
    """Shown after every scan (not just duplicates) — added 2026-09-07 per
    user direction: SCAN CONTRACT used to add straight to the queue/route,
    only pausing for a duplicate. Now every scan pauses here first. Same
    themed `Qt.Popup` shell `_DuplicatePopup` used (closes on an outside
    click, matches the rest of the app's HUD styling instead of a plain
    QMessageBox) — generalized to show the contract summary and (later,
    once the grading pass lands) a 0-100 score, not just a duplicate
    warning. The duplicate warning line still appears here when relevant,
    folded into this one popup instead of a separate flow."""

    def __init__(
        self, parent_widget, summary_text: str, duplicate_warning: str | None,
        grade: int | None, grade_reason: str, grade_capped: bool,
        unrated_terminals: list[tuple[str, dict]], on_rate, on_accept, on_reject,
    ):
        # A real top-level window, not Qt.Popup — added 2026-09-07 after a
        # live test showed Qt.Popup auto-closes on any outside click or
        # focus loss (e.g. tabbing away to check something), silently
        # discarding an in-progress compatibility rating and forcing a
        # rescan. This decision needs to survive that; only ACCEPT/REJECT
        # should ever close it. Positioned manually below (popup.move()),
        # same as before.
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_StyledBackground, True)
        border_color = theme.ACCENT_AMBER if duplicate_warning else theme.BORDER_FLAT
        self.setStyleSheet(f"""
            _ReviewPopup {{
                background: {theme.BG_PANEL}; border: 1px solid {border_color};
                border-radius: {theme.RADIUS}px;
            }}
        """)
        self._on_rate = on_rate
        self._on_accept = on_accept
        self._on_reject = on_reject

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        self.setMaximumWidth(420)

        title = QLabel("Add this contract?")
        title.setStyleSheet(
            f"color: {theme.TEXT_PRIMARY}; font-family: {theme.FONT_DISPLAY}; "
            f"font-weight: 700; font-size: {theme.fpx(11)}px;"
        )
        layout.addWidget(title)

        summary = QLabel(summary_text)
        summary.setWordWrap(True)
        summary.setStyleSheet(
            f"color: {theme.TEXT_PRIMARY}; font-family: {theme.FONT_MONO}; "
            f"font-size: {theme.fpx(10)}px;"
        )
        layout.addWidget(summary)

        if grade is not None:
            # Amber whenever a hard warning capped the score, regardless of
            # what the number still looks like — the cap can still land
            # somewhere that looks decent (e.g. 55%), and that's exactly
            # the "90% great, one hard no, hidden behind a decent-looking
            # score" case this feature exists to prevent. Otherwise amber
            # only for a low score on its own merits.
            grade_color = theme.ACCENT_AMBER if (grade_capped or grade < 50) else theme.ACCENT_CYAN
            grade_label = QLabel(f"GRADE: {grade}% — {grade_reason}")
            grade_label.setWordWrap(True)
            grade_label.setStyleSheet(
                f"color: {grade_color}; font-family: {theme.FONT_DISPLAY}; "
                f"font-weight: 800; font-size: {theme.fpx(11)}px;"
            )
            layout.addWidget(grade_label)
        else:
            hint = QLabel(grade_reason)  # "Set your PROFILE for a grade."
            hint.setStyleSheet(
                f"color: {theme.TEXT_DIM}; font-family: {theme.FONT_MONO}; "
                f"font-size: {theme.fpx(9)}px;"
            )
            layout.addWidget(hint)

        if duplicate_warning:
            warn = QLabel(f"⚠ {duplicate_warning}")
            warn.setWordWrap(True)
            warn.setStyleSheet(
                f"background: {theme.ACCENT_AMBER_DIM}; color: {theme.ACCENT_AMBER}; "
                f"border: 1px solid {theme.ACCENT_AMBER}; border-radius: {theme.RADIUS}px; "
                f"padding: 5px 8px; font-family: {theme.FONT_MONO}; "
                f"font-size: {theme.fpx(9)}px;"
            )
            layout.addWidget(warn)

        for label_text, terminal in unrated_terminals:
            row = QHBoxLayout()
            q = QLabel(f"Compatible with your ship at {label_text}?")
            q.setWordWrap(True)
            q.setStyleSheet(
                f"color: {theme.TEXT_MUTED}; font-family: {theme.FONT_MONO}; "
                f"font-size: {theme.fpx(9)}px;"
            )
            row.addWidget(q, 1)
            good_btn = QPushButton("✅")
            bad_btn = QPushButton("❌")
            small_btn_style = (
                f"background: {theme.BG_VOID}; border: 1px solid {theme.BORDER_FLAT}; "
                f"border-radius: {theme.RADIUS}px; padding: 2px 6px; font-size: {theme.fpx(10)}px;"
            )
            good_btn.setStyleSheet(small_btn_style)
            bad_btn.setStyleSheet(small_btn_style)
            good_btn.clicked.connect(
                lambda _checked, t=terminal, lbl=label_text, g=good_btn, b=bad_btn: self._rate(t, True, lbl, g, b)
            )
            bad_btn.clicked.connect(
                lambda _checked, t=terminal, lbl=label_text, g=good_btn, b=bad_btn: self._rate(t, False, lbl, g, b)
            )
            row.addWidget(good_btn)
            row.addWidget(bad_btn)
            layout.addLayout(row)

        btn_row = QHBoxLayout()
        accept_btn = QPushButton("ACCEPT")
        reject_btn = QPushButton("REJECT")
        btn_style = (
            f"background: {theme.BG_VOID}; color: {theme.ACCENT_CYAN}; "
            f"border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px; "
            f"padding: 4px 10px; font-family: {theme.FONT_DISPLAY}; font-weight: 700; "
            f"font-size: {theme.fpx(10)}px;"
        )
        accept_btn.setStyleSheet(btn_style)
        reject_btn.setStyleSheet(btn_style)
        accept_btn.clicked.connect(self._accept)
        reject_btn.clicked.connect(self._reject)
        btn_row.addWidget(accept_btn)
        btn_row.addWidget(reject_btn)
        layout.addLayout(btn_row)

    def _rate(self, terminal: dict, good: bool, label: str, good_btn: QPushButton, bad_btn: QPushButton):
        # Saves immediately, doesn't close the popup — you can rate several
        # locations before deciding ACCEPT/REJECT. Doesn't affect *this*
        # popup's already-shown grade (recomputing live isn't worth the
        # complexity for a rating that mainly pays off on the *next* scan
        # of the same location) — just disables the row so it's clear the
        # answer was recorded.
        self._on_rate(terminal, good, label)
        good_btn.setEnabled(False)
        bad_btn.setEnabled(False)
        # 2026-09-07: both buttons used to just grey out identically on
        # click, with no way to tell which one had actually registered
        # (a live test confirmed the click did work, but looked like it
        # hadn't). The chosen button now stays bright with a colored
        # border; the other visibly dims further than Qt's default
        # disabled look.
        chosen, other = (good_btn, bad_btn) if good else (bad_btn, good_btn)
        chosen_color = theme.ACCENT_CYAN if good else theme.ACCENT_AMBER
        chosen.setStyleSheet(
            f"background: {theme.BG_VOID}; border: 2px solid {chosen_color}; "
            f"border-radius: {theme.RADIUS}px; padding: 2px 6px; font-size: {theme.fpx(10)}px;"
        )
        other.setStyleSheet(
            f"background: {theme.BG_VOID}; border: 1px solid {theme.BORDER_FLAT}; "
            f"border-radius: {theme.RADIUS}px; padding: 2px 6px; font-size: {theme.fpx(10)}px; "
            f"color: {theme.TEXT_DIM};"
        )

    def _accept(self):
        self._on_accept()
        self.close()

    def _reject(self):
        self._on_reject()
        self.close()


class _HaulerProfilePopup(QWidget):
    """Ship + hauling-preference profile, set once and edited whenever —
    added 2026-09-07 (Part 2 of the confirm-gate/grading plan, see
    docs/DECISIONS.md). Not re-asked per scan; a later grading pass reads
    these five fields from `self.settings["hauler_profile"]` to score a
    freshly-scanned contract. Real top-level window, not Qt.Popup — same
    2026-09-07 fix as `_ReviewPopup` (Qt.Popup auto-closes on any outside
    click/focus loss, which would silently discard an in-progress edit
    here too); only SAVE closes it."""

    def __init__(
        self, parent_widget, profile: dict, capacity: int | None, thresholds: dict | None,
        game_log_path: str | None, accept_reminder_seconds: int, on_save,
    ):
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            _HaulerProfilePopup {{
                background: {theme.BG_PANEL}; border: 1px solid {theme.BORDER_FLAT};
                border-radius: {theme.RADIUS}px;
            }}
        """)
        self._on_save = on_save
        self.setMinimumWidth(320)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        title = QLabel("HAULER PROFILE")
        title.setStyleSheet(
            f"color: {theme.ACCENT_CYAN}; font-family: {theme.FONT_DISPLAY}; "
            f"font-weight: 800; font-size: {theme.fpx(11)}px; letter-spacing: 2px;"
        )
        layout.addWidget(title)

        ship_row = QHBoxLayout()
        ship_label = QLabel("SHIP")
        ship_label.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-family: {theme.FONT_MONO}; "
            f"font-size: {theme.fpx(9)}px; letter-spacing: 1px;"
        )
        ship_row.addWidget(ship_label)
        self._ship_edit = QLineEdit(profile.get("ship", ""))
        self._ship_edit.setPlaceholderText("Ship (e.g. Hull C)")
        self._ship_edit.setStyleSheet(
            f"""
            QLineEdit {{
                background: {theme.BG_VOID}; color: {theme.ACCENT_CYAN};
                border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px;
                padding: 4px 6px; font-family: "{theme.FONT_DISPLAY}"; font-weight: 700;
                font-size: {theme.fpx(11)}px;
            }}
            """
        )
        ship_row.addWidget(self._ship_edit, 1)
        layout.addLayout(ship_row)

        # Moved here from the card face, 2026-09-07, per user request —
        # sits with the ship it's actually describing (a hold size only
        # means something in the context of a specific ship) rather than
        # as an unrelated standalone field on the card. Manual entry, not
        # a ship picker — the user's actual hold size depends on cargo-
        # grid loadout, which UEX's static vehicle data can't reflect.
        capacity_row = QHBoxLayout()
        capacity_label = QLabel("CARGO CAPACITY")
        capacity_label.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-family: {theme.FONT_MONO}; "
            f"font-size: {theme.fpx(9)}px; letter-spacing: 1px;"
        )
        capacity_row.addWidget(capacity_label)
        self._capacity_edit = QLineEdit(str(capacity) if capacity else "")
        self._capacity_edit.setValidator(QIntValidator(0, 100000, self._capacity_edit))
        self._capacity_edit.setPlaceholderText("SCU")
        self._capacity_edit.setStyleSheet(
            f"""
            QLineEdit {{
                background: {theme.BG_VOID}; color: {theme.ACCENT_CYAN};
                border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px;
                padding: 4px 6px; font-family: "{theme.FONT_DISPLAY}"; font-weight: 700;
                font-size: {theme.fpx(11)}px;
            }}
            """
        )
        capacity_row.addWidget(self._capacity_edit, 1)
        layout.addLayout(capacity_row)

        self._goal_combo = self._add_row(layout, "GOAL", PROFILE_GOAL_CHOICES, profile.get("goal"))
        self._risk_combo = self._add_row(layout, "RISK TOLERANCE", PROFILE_RISK_CHOICES, profile.get("risk"))
        self._time_combo = self._add_row(layout, "SESSION TIME", PROFILE_TIME_CHOICES, profile.get("time_budget"))
        self._region_combo = self._add_row(layout, "REGION", PROFILE_REGION_CHOICES, profile.get("region_pref"))

        # GRADING SCALE — added 2026-09-07 per user direction, replacing
        # hardcoded aUEC/SCU thresholds that turned out to be miscalibrated
        # against this project's own real captured contracts (see
        # docs/DECISIONS.md). User-tunable instead of guessed a second
        # time. `_grade_contract()` reads `self.settings["grading_
        # thresholds"]` fresh on every scan — saving here takes effect on
        # the very next scan, no restart needed.
        scale_title = QLabel("GRADING SCALE (aUEC/SCU)")
        scale_title.setStyleSheet(
            f"color: {theme.ACCENT_CYAN}; font-family: {theme.FONT_DISPLAY}; "
            f"font-weight: 800; font-size: {theme.fpx(10)}px; letter-spacing: 1px;"
        )
        layout.addWidget(scale_title)
        merged_thresholds = {**DEFAULT_GRADING_THRESHOLDS, **(thresholds or {})}
        self._great_edit = self._add_number_row(layout, "GREAT ≥", merged_thresholds["great"])
        self._good_edit = self._add_number_row(layout, "GOOD ≥", merged_thresholds["good"])
        self._ok_edit = self._add_number_row(layout, "OK ≥", merged_thresholds["ok"])

        # GAME.LOG PATH — added alongside the OCR+Game.log verification
        # feature (see docs/DECISIONS.md): every ACCEPT now cross-checks
        # what OCR found against Star Citizen's own Game.log, which needs
        # to know where that file is. Pre-filled with the common install
        # path when it exists; BROWSE lets a different install location
        # (or a backup log for testing) override it.
        log_title = QLabel("GAME.LOG PATH")
        log_title.setStyleSheet(
            f"color: {theme.ACCENT_CYAN}; font-family: {theme.FONT_DISPLAY}; "
            f"font-weight: 800; font-size: {theme.fpx(10)}px; letter-spacing: 1px;"
        )
        layout.addWidget(log_title)
        log_row = QHBoxLayout()
        self._game_log_edit = QLineEdit(game_log_path or "")
        self._game_log_edit.setPlaceholderText("Path to Game.log")
        self._game_log_edit.setStyleSheet(
            f"""
            QLineEdit {{
                background: {theme.BG_VOID}; color: {theme.ACCENT_CYAN};
                border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px;
                padding: 4px 6px; font-family: "{theme.FONT_MONO}";
                font-size: {theme.fpx(9)}px;
            }}
            """
        )
        log_row.addWidget(self._game_log_edit, 1)
        browse_btn = QPushButton("BROWSE")
        browse_btn.setStyleSheet(
            f"background: {theme.BG_VOID}; color: {theme.ACCENT_CYAN}; "
            f"border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px; "
            f"padding: 4px 8px; font-family: {theme.FONT_DISPLAY}; font-weight: 700; "
            f"font-size: {theme.fpx(9)}px;"
        )
        browse_btn.clicked.connect(self._browse_game_log)
        log_row.addWidget(browse_btn)
        layout.addLayout(log_row)

        # ACCEPT REMINDER — added 2026-09-08 alongside the delayed-recheck
        # feature: if Game.log still hasn't confirmed a contract this many
        # seconds after ACCEPT, the card shows a blinking reminder to
        # actually accept it in-game (easy to forget when you're just
        # testing/reviewing). 0 disables it entirely. Deliberately a plain
        # number field here, not a slider/combo — this is expected to need
        # real tuning against `nearest_haul_event_gap_seconds` data as more
        # sessions run, same reasoning as the verify window itself.
        reminder_row = QHBoxLayout()
        reminder_label = QLabel("ACCEPT REMINDER (sec, 0=off)")
        reminder_label.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-family: {theme.FONT_MONO}; "
            f"font-size: {theme.fpx(9)}px; letter-spacing: 1px;"
        )
        reminder_row.addWidget(reminder_label)
        self._reminder_edit = QLineEdit(str(accept_reminder_seconds))
        self._reminder_edit.setValidator(QIntValidator(0, 3600, self._reminder_edit))
        self._reminder_edit.setStyleSheet(
            f"""
            QLineEdit {{
                background: {theme.BG_VOID}; color: {theme.ACCENT_CYAN};
                border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px;
                padding: 4px 6px; font-family: "{theme.FONT_DISPLAY}"; font-weight: 700;
                font-size: {theme.fpx(11)}px;
            }}
            """
        )
        reminder_row.addWidget(self._reminder_edit, 1)
        layout.addLayout(reminder_row)

        save_btn = QPushButton("SAVE")
        save_btn.setStyleSheet(
            f"background: {theme.BG_VOID}; color: {theme.ACCENT_CYAN}; "
            f"border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px; "
            f"padding: 4px 10px; font-family: {theme.FONT_DISPLAY}; font-weight: 700; "
            f"font-size: {theme.fpx(10)}px;"
        )
        save_btn.clicked.connect(self._save)
        layout.addWidget(save_btn)

    def _add_row(self, layout: QVBoxLayout, label_text: str, choices: list[str], current: str | None) -> QComboBox:
        row = QHBoxLayout()
        label = QLabel(label_text)
        label.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-family: {theme.FONT_MONO}; "
            f"font-size: {theme.fpx(9)}px; letter-spacing: 1px;"
        )
        row.addWidget(label)

        combo = QComboBox()
        combo.addItems(choices)
        if current in choices:
            combo.setCurrentText(current)
        combo.setStyleSheet(
            f"""
            QComboBox {{
                background: {theme.BG_VOID}; color: {theme.ACCENT_CYAN};
                border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px;
                padding: 4px 22px 4px 6px; font-family: "{theme.FONT_DISPLAY}"; font-weight: 700;
                font-size: {theme.fpx(10)}px;
            }}
            QComboBox::drop-down {{ width: 18px; border: none; }}
            """
        )
        row.addWidget(combo, 1)
        layout.addLayout(row)
        return combo

    def _add_number_row(self, layout: QVBoxLayout, label_text: str, value: int) -> QLineEdit:
        row = QHBoxLayout()
        label = QLabel(label_text)
        label.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-family: {theme.FONT_MONO}; "
            f"font-size: {theme.fpx(9)}px; letter-spacing: 1px;"
        )
        row.addWidget(label)

        edit = QLineEdit(str(value))
        edit.setValidator(QIntValidator(0, 1_000_000, edit))
        edit.setStyleSheet(
            f"""
            QLineEdit {{
                background: {theme.BG_VOID}; color: {theme.ACCENT_CYAN};
                border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px;
                padding: 4px 6px; font-family: "{theme.FONT_DISPLAY}"; font-weight: 700;
                font-size: {theme.fpx(11)}px;
            }}
            """
        )
        row.addWidget(edit, 1)
        layout.addLayout(row)
        return edit

    def _browse_game_log(self):
        start_dir = os.path.dirname(self._game_log_edit.text().strip()) or ""
        path, _ = QFileDialog.getOpenFileName(self, "Select Game.log", start_dir, "Log files (*.log);;All files (*)")
        if path:
            self._game_log_edit.setText(path)

    def _save(self):
        capacity_text = self._capacity_edit.text().strip()
        reminder_text = self._reminder_edit.text().strip()
        self._on_save(
            {
                "ship": self._ship_edit.text().strip(),
                "goal": self._goal_combo.currentText(),
                "risk": self._risk_combo.currentText(),
                "time_budget": self._time_combo.currentText(),
                "region_pref": self._region_combo.currentText(),
            },
            int(capacity_text) if capacity_text else None,
            {
                "great": int(self._great_edit.text() or DEFAULT_GRADING_THRESHOLDS["great"]),
                "good": int(self._good_edit.text() or DEFAULT_GRADING_THRESHOLDS["good"]),
                "ok": int(self._ok_edit.text() or DEFAULT_GRADING_THRESHOLDS["ok"]),
            },
            self._game_log_edit.text().strip() or None,
            int(reminder_text) if reminder_text else DEFAULT_ACCEPT_REMINDER_SECONDS,
        )
        self.close()
