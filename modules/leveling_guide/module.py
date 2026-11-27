"""mobiGuide: a WoW-style leveling guide for Star Citizen. One objective at a
time, step by step, checked off by hand; chapters, a level/XP bar, grind
counters, and objectives you can add yourself.

Content is data (guide.py loads JSON chapter files), progress is a local
file (progress.py). The only network call is UEX's ship purchase prices for
"buy a ship" objectives, run off the GUI thread through refresh_job().
No Game.log reading and no game input: completion is always manual.
See docs/modules/leveling-guide.md.
"""
import importlib.util
import os
from html import escape
import sys
import time
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMenu, QMessageBox, QProgressBar, QPushButton, QSpinBox,
    QTextEdit, QVBoxLayout, QWidget,
)

from host import theme
from host.module_base import ModuleBase


def _load_sibling(name: str):
    # module_loader imports module.py by file path, so relative imports
    # don't work; same pattern as mobi_notes/store.py.
    spec = importlib.util.spec_from_file_location(
        f"mobioverlay_leveling_guide_{name}", os.path.join(os.path.dirname(__file__), f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    # dataclasses look the module up in sys.modules while building classes.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


guide_mod = _load_sibling("guide")
progress_mod = _load_sibling("progress")

BUNDLED_GUIDES = os.path.join(os.path.dirname(__file__), "guides")
PRICE_MAX_AGE_S = 30 * 60
KIND_LABELS = {"task": "TASK", "rank": "RANK UP", "grind": "GRIND", "purchase": "BUY"}

_LABEL_SMALL = theme.label_small()
_COMBO_STYLE = theme.field_style("QComboBox", theme.TEXT_PRIMARY, 10, padding="4px 6px", drop_down=18)
_LINE_STYLE = theme.field_style("QLineEdit", theme.TEXT_PRIMARY, 10, padding="4px 6px")
_TEXT_STYLE = theme.field_style("QTextEdit", theme.TEXT_PRIMARY, 10, padding="6px")
_SPIN_STYLE = theme.field_style("QSpinBox", theme.TEXT_PRIMARY, 10, padding="3px 6px")
_TITLE_STYLE = theme.text_style(12, color=theme.TEXT_PRIMARY, family=theme.FONT_DISPLAY, weight="bold")
_BODY_STYLE = theme.text_style(10, color=theme.TEXT_PRIMARY)
_MUTED_STYLE = theme.text_style(9, color=theme.TEXT_MUTED)
_DIM_STYLE = theme.text_style(9, color=theme.TEXT_DIM)
_AMBER_STYLE = theme.text_style(9, color=theme.ACCENT_AMBER, letter_spacing=1)
_CYAN_STYLE = theme.text_style(9, color=theme.ACCENT_CYAN, letter_spacing=1)
_LEVEL_STYLE = theme.text_style(14, color=theme.ACCENT_AMBER, family=theme.FONT_DISPLAY, weight=900)
# Scoped to the row's object name: an unscoped border rule on a container
# would also draw a box around every label inside it.
_STEP_STYLE = f"QLabel#lgRow {{ {theme.row_style('6px 8px')} {theme.text_style(10)} }}"
_STEP_CURRENT_STYLE = f"QLabel#lgRow {{ {theme.row_style('6px 8px', theme.ACCENT_CYAN)} {theme.text_style(10)} }}"
_ROW_STYLE = f"QLabel#lgRow {{ {theme.row_style('3px 6px')} {theme.text_style(9)} }}"
_ROW_CURRENT_STYLE = f"QLabel#lgRow {{ {theme.row_style('3px 6px', theme.ACCENT_CYAN)} {theme.text_style(9)} }}"
_ACTION_BTN = theme.action_btn_style()
_PRIMARY_BTN = f"""
    QPushButton {{
        background: {theme.ACCENT_CYAN_DIM}; color: {theme.ACCENT_CYAN};
        border: 1px solid {theme.ACCENT_CYAN}; border-radius: {theme.RADIUS}px; padding: 5px 0;
        font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(9)}px; letter-spacing: 1px;
    }}
    QPushButton:disabled {{ color: {theme.TEXT_DIM}; border: 1px solid {theme.BORDER_FLAT}; background: transparent; }}
"""
_ICON_BTN = f"""
    QPushButton {{
        background: transparent; color: {theme.TEXT_MUTED};
        border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px;
        font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(10)}px;
    }}
    QPushButton:hover {{ color: {theme.ACCENT_CYAN}; border-color: {theme.ACCENT_CYAN}; }}
    QPushButton:disabled {{ color: {theme.TEXT_DIM}; }}
"""
_XP_BAR = f"""
    QProgressBar {{
        background: {theme.BG_VOID}; border: 1px solid {theme.BORDER_FLAT};
        border-radius: 4px; height: 8px; text-align: center; color: transparent;
    }}
    QProgressBar::chunk {{ background: {theme.ACCENT_AMBER}; border-radius: 3px; }}
"""


def _label(text: str = "", style: str = _BODY_STYLE, wrap: bool = True) -> QLabel:
    lab = QLabel(text)
    lab.setStyleSheet(style)
    lab.setWordWrap(wrap)
    lab.setTextInteractionFlags(Qt.NoTextInteraction)
    return lab


def _button(text: str, style: str = _ACTION_BTN, tooltip: str = "") -> QPushButton:
    btn = QPushButton(text)
    btn.setStyleSheet(style)
    if tooltip:
        btn.setToolTip(tooltip)
    return btn


class AddObjectiveDialog(QDialog):
    """Add your own objective. Steps are one per line; anything after '=>'
    on a line is how you know that step is done."""

    def __init__(self, parent, chapters: list[tuple[str, str]], default_chapter: str | None):
        super().__init__(parent)
        self.setWindowTitle("Add objective")
        self.setMinimumWidth(380)
        form = QFormLayout(self)

        self.title_edit = QLineEdit()
        self.title_edit.setStyleSheet(_LINE_STYLE)
        self.title_edit.setPlaceholderText("e.g. Buy a Cutlass Black")
        form.addRow("Title", self.title_edit)

        self.chapter_combo = QComboBox()
        self.chapter_combo.setStyleSheet(_COMBO_STYLE)
        for cid, title in chapters:
            self.chapter_combo.addItem(title, cid)
        self.chapter_combo.addItem(guide_mod.CUSTOM_CHAPTER_TITLE, guide_mod.CUSTOM_CHAPTER_ID)
        idx = self.chapter_combo.findData(default_chapter) if default_chapter else -1
        self.chapter_combo.setCurrentIndex(idx if idx >= 0 else self.chapter_combo.count() - 1)
        form.addRow("Chapter", self.chapter_combo)

        kind_row = QHBoxLayout()
        self.kind_combo = QComboBox()
        self.kind_combo.setStyleSheet(_COMBO_STYLE)
        self.kind_combo.addItem("Task (do it once)", "task")
        self.kind_combo.addItem("Grind (repeat N times)", "grind")
        kind_row.addWidget(self.kind_combo, stretch=1)
        self.target_spin = QSpinBox()
        self.target_spin.setRange(1, 999)
        self.target_spin.setValue(5)
        self.target_spin.setStyleSheet(_SPIN_STYLE)
        kind_row.addWidget(self.target_spin)
        self.unit_edit = QLineEdit()
        self.unit_edit.setStyleSheet(_LINE_STYLE)
        self.unit_edit.setPlaceholderText("contracts")
        kind_row.addWidget(self.unit_edit)
        form.addRow("Type", kind_row)
        self.kind_combo.currentIndexChanged.connect(self._sync_kind)
        self._sync_kind()

        self.why_edit = QLineEdit()
        self.why_edit.setStyleSheet(_LINE_STYLE)
        self.why_edit.setPlaceholderText("Why it matters (optional)")
        form.addRow("Why", self.why_edit)

        self.steps_edit = QTextEdit()
        self.steps_edit.setStyleSheet(_TEXT_STYLE)
        self.steps_edit.setPlaceholderText(
            "One step per line. Optional: add '=> how you know it's done'.\n"
            "Fly to New Deal in Lorville\n"
            "Buy the ship => It shows at the ASOP terminal")
        self.steps_edit.setMinimumHeight(110)
        form.addRow("Steps", self.steps_edit)

        self.error_label = _label("", _AMBER_STYLE)
        form.addRow(self.error_label)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _sync_kind(self):
        is_grind = self.kind_combo.currentData() == "grind"
        self.target_spin.setVisible(is_grind)
        self.unit_edit.setVisible(is_grind)

    def steps(self) -> list[dict]:
        out = []
        for line in self.steps_edit.toPlainText().splitlines():
            line = line.strip()
            if not line:
                continue
            do, _, done = line.partition("=>")
            out.append({"do": do.strip(), "done_when": done.strip() or "Done."})
        return [s for s in out if s["do"]]

    def _on_accept(self):
        if not self.title_edit.text().strip():
            self.error_label.setText("Give it a title.")
            return
        if not self.steps():
            self.error_label.setText("Add at least one step.")
            return
        self.accept()

    def values(self) -> dict:
        return {
            "title": self.title_edit.text().strip(),
            "chapter_id": self.chapter_combo.currentData(),
            "kind": self.kind_combo.currentData(),
            "goal_target": self.target_spin.value(),
            "goal_unit": self.unit_edit.text().strip(),
            "why": self.why_edit.text().strip(),
            "steps": self.steps(),
        }


class LevelingGuideModule(ModuleBase):
    module_id = "leveling_guide"
    display_name = (
        f'<span style="color:{theme.TEXT_PRIMARY};">mobi</span>'
        f'<span style="color:{theme.ACCENT_CYAN};">Guide</span>'
    )

    def __init__(self, api_client, config, locations, progress=None, custom=None, guide_dirs=None):
        super().__init__(api_client, config, locations)
        self.settings.setdefault("show_optional", True)
        self.settings.setdefault("show_unlawful", False)
        self.settings.setdefault("compact", False)
        self.settings.setdefault("refresh_interval_seconds", 600)
        self.progress = progress or progress_mod.ProgressStore()
        self.custom = custom or progress_mod.CustomObjectives()
        self._guide_dirs = guide_dirs or [Path(BUNDLED_GUIDES), progress_mod.user_guides_dir()]
        self.guide = None
        self._viewing: str | None = None
        self._price_rows: list[dict] | None = None
        self._price_at = 0.0
        self._price_error = ""
        self.request_refresh = None  # injected by host after wrapping refresh()
        self.reload_guide()

    # ------------------------------------------------------------------
    # Content and state
    # ------------------------------------------------------------------
    def reload_guide(self):
        self.guide = guide_mod.load_guide(self._guide_dirs, self.custom.path)

    def _filters(self) -> tuple[bool, bool]:
        return bool(self.settings.get("show_optional")), bool(self.settings.get("show_unlawful"))

    def _visible(self, obj) -> bool:
        return guide_mod.is_visible(obj, *self._filters())

    def current_objective(self):
        """What the card shows: the objective you picked, else the guide's
        next one."""
        if self._viewing:
            obj = self.guide.get(self._viewing)
            if obj is not None:
                return obj
        saved = self.progress.current
        if saved:
            obj = self.guide.get(saved)
            if obj is not None and self._visible(obj) and saved not in self.progress.passed_ids():
                return obj
        return guide_mod.next_objective(self.guide, self.progress.passed_ids(), *self._filters())

    def _save_settings(self):
        self.config.set_module_settings(self.module_id, self.settings)

    # ------------------------------------------------------------------
    # Card
    # ------------------------------------------------------------------
    def create_card(self, container):
        card = container.add_card(self.module_id, self.display_name)
        layout = card.body_layout

        # -- level / XP ---------------------------------------------------
        top = QHBoxLayout()
        top.setSpacing(8)
        self.level_label = _label("LVL 1", _LEVEL_STYLE, wrap=False)
        top.addWidget(self.level_label)
        xp_col = QVBoxLayout()
        xp_col.setSpacing(2)
        self.xp_bar = QProgressBar()
        self.xp_bar.setStyleSheet(_XP_BAR)
        self.xp_bar.setTextVisible(False)
        self.xp_bar.setFixedHeight(8)
        xp_col.addWidget(self.xp_bar)
        self.xp_label = _label("", _DIM_STYLE, wrap=False)
        xp_col.addWidget(self.xp_label)
        top.addLayout(xp_col, stretch=1)
        self.menu_btn = _button("⚙", _ICON_BTN, "Options")
        self.menu_btn.setFixedSize(26, 26)
        self.menu_btn.clicked.connect(self._show_menu)
        top.addWidget(self.menu_btn)
        layout.addLayout(top)

        # -- chapter picker -------------------------------------------------
        chap_row = QHBoxLayout()
        chap_row.setSpacing(6)
        self.chapter_combo = QComboBox()
        self.chapter_combo.setStyleSheet(_COMBO_STYLE)
        self.chapter_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.chapter_combo.setMinimumContentsLength(18)
        self.chapter_combo.activated.connect(self._on_chapter_picked)
        chap_row.addWidget(self.chapter_combo, stretch=1)
        self.next_btn = _button("NEXT ▸", _ICON_BTN, "Jump to the guide's next objective")
        self.next_btn.setFixedHeight(26)
        self.next_btn.setMinimumWidth(56)
        self.next_btn.clicked.connect(self._on_jump_next)
        chap_row.addWidget(self.next_btn)
        layout.addLayout(chap_row)

        # -- current objective ----------------------------------------------
        self.badges_label = _label("", _CYAN_STYLE)
        layout.addWidget(self.badges_label)
        self.title_label = _label("", _TITLE_STYLE)
        layout.addWidget(self.title_label)
        self.why_label = _label("", _MUTED_STYLE)
        layout.addWidget(self.why_label)
        self.info_label = _label("", _AMBER_STYLE)
        self.info_label.setTextFormat(Qt.RichText)
        layout.addWidget(self.info_label)
        self.lock_label = _label("", _AMBER_STYLE)
        layout.addWidget(self.lock_label)

        steps_caption = _label("STEPS", _LABEL_SMALL, wrap=False)
        layout.addWidget(steps_caption)
        self.steps_layout = QVBoxLayout()
        self.steps_layout.setSpacing(4)
        layout.addLayout(self.steps_layout)

        # -- grind counter --------------------------------------------------
        self.counter_row = QWidget()
        counter = QHBoxLayout(self.counter_row)
        counter.setContentsMargins(0, 0, 0, 0)
        self.minus_btn = _button("−", _ICON_BTN, "Count one less")
        self.minus_btn.setFixedSize(28, 26)
        self.minus_btn.clicked.connect(lambda: self._on_count(-1))
        counter.addWidget(self.minus_btn)
        self.count_label = _label("", _BODY_STYLE, wrap=False)
        self.count_label.setAlignment(Qt.AlignCenter)
        counter.addWidget(self.count_label, stretch=1)
        self.plus_btn = _button("+1", _PRIMARY_BTN, "Count one more")
        self.plus_btn.setFixedSize(44, 26)
        self.plus_btn.clicked.connect(lambda: self._on_count(1))
        counter.addWidget(self.plus_btn)
        layout.addWidget(self.counter_row)

        # -- actions ----------------------------------------------------------
        actions = QHBoxLayout()
        actions.setSpacing(4)
        self.back_btn = _button("◀ BACK")
        self.back_btn.clicked.connect(self._on_back)
        actions.addWidget(self.back_btn)
        self.step_btn = _button("✓ STEP DONE", _PRIMARY_BTN)
        self.step_btn.clicked.connect(self._on_step_done)
        actions.addWidget(self.step_btn, stretch=2)
        self.skip_btn = _button("SKIP", tooltip="Move on without marking this done")
        self.skip_btn.clicked.connect(self._on_skip)
        actions.addWidget(self.skip_btn)
        layout.addLayout(actions)

        # -- objective list ---------------------------------------------------
        self.list_container = QWidget()
        list_layout = QVBoxLayout(self.list_container)
        list_layout.setContentsMargins(0, 4, 0, 0)
        list_layout.setSpacing(3)
        list_layout.addWidget(_label("IN THIS CHAPTER", _LABEL_SMALL, wrap=False))
        self.list_layout = QVBoxLayout()
        self.list_layout.setSpacing(3)
        list_layout.addLayout(self.list_layout)
        layout.addWidget(self.list_container)

        footer = QHBoxLayout()
        self.sources_btn = _button("SOURCES", tooltip="Where this objective's facts come from")
        self.sources_btn.clicked.connect(self._show_sources)
        footer.addWidget(self.sources_btn)
        self.add_btn = _button("+ ADD OBJECTIVE")
        self.add_btn.clicked.connect(self._on_add_objective)
        footer.addWidget(self.add_btn)
        layout.addLayout(footer)

        self.problems_label = _label("", _DIM_STYLE)
        layout.addWidget(self.problems_label)

        self.card = card
        self.render()
        return card

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    @staticmethod
    def _clear(layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                # Hide now: deleteLater() only runs on the next event-loop
                # pass, and until then the old row still paints in place.
                w.hide()
                w.deleteLater()

    def render(self):
        if not hasattr(self, "title_label"):
            return
        show_opt, show_unl = self._filters()
        done = self.progress.done_ids()
        passed = self.progress.passed_ids()
        compact = bool(self.settings.get("compact"))

        level, into, need = guide_mod.level_for_xp(guide_mod.total_xp(self.guide, done))
        self.level_label.setText(f"LVL {level}")
        self.xp_bar.setMaximum(need)
        self.xp_bar.setValue(into)
        visible_all = [o for o in self.guide.objectives if self._visible(o)]
        done_visible = sum(1 for o in visible_all if o.id in done)
        self.xp_label.setText(f"{into}/{need} XP · {done_visible}/{len(visible_all)} objectives")

        obj = self.current_objective()
        chapter = self.guide.chapter(obj.chapter_id) if obj else None

        self.chapter_combo.blockSignals(True)
        self.chapter_combo.clear()
        for c in self.guide.chapters:
            d, t = guide_mod.chapter_progress(c, done, show_opt, show_unl)
            if t == 0:
                continue
            mark = "✓ " if d == t else ""
            self.chapter_combo.addItem(f"{mark}{c.title}  ({d}/{t})", c.id)
        if chapter is not None:
            idx = self.chapter_combo.findData(chapter.id)
            if idx >= 0:
                self.chapter_combo.setCurrentIndex(idx)
        self.chapter_combo.blockSignals(False)

        self._clear(self.steps_layout)
        if obj is None:
            self.badges_label.setText("GUIDE COMPLETE")
            self.title_label.setText("Every visible objective is done.")
            self.why_label.setText("Turn on optional or outlaw content in ⚙, or add your own objective.")
            for w in (self.info_label, self.lock_label, self.counter_row):
                w.setVisible(False)
            for b in (self.back_btn, self.step_btn, self.skip_btn, self.sources_btn):
                b.setEnabled(False)
            self._render_list(None)
            self._render_problems()
            self._fit_card()
            return

        is_done = obj.id in done
        badges = [KIND_LABELS.get(obj.kind, obj.kind.upper())]
        if obj.optional:
            badges.append("OPTIONAL")
        if obj.unlawful:
            badges.append("ILLEGAL")
        if obj.custom:
            badges.append("YOURS")
        if is_done:
            badges.append("✓ DONE")
        elif obj.id in passed:
            badges.append("SKIPPED")
        if chapter is not None:
            badges.append(chapter.title.upper())
        self.badges_label.setText("  ·  ".join(badges))
        self.title_label.setText(obj.title)
        self.why_label.setText(obj.why)
        self.why_label.setVisible(bool(obj.why) and not compact)

        info = []
        if obj.reputation:
            rep = obj.reputation
            pts = f" ({rep['points']:,} rep)" if isinstance(rep.get("points"), int) else ""
            info.append(f"TARGET: {rep['faction']} · {rep['rank']}{pts}")
        if obj.reward:
            info.append(f"REWARD: {obj.reward}")
        if obj.cost:
            info.append(f"COST: {obj.cost}")
        if obj.ship:
            info.append(self._price_text(obj))
        self.info_label.setText("<br>".join(info))
        self.info_label.setVisible(bool(info) and not compact)

        missing = [r for r in obj.requires if r not in passed]
        if missing and not is_done:
            names = ", ".join(self.guide.get(r).title for r in missing if self.guide.get(r))
            self.lock_label.setText(f"⚠ Usually done after: {names}")
            self.lock_label.setVisible(not compact)
        else:
            self.lock_label.setVisible(False)

        step_index = min(self.progress.step(obj.id), len(obj.steps) - 1)
        for i, step in enumerate(obj.steps):
            if compact and i != step_index:
                continue
            self.steps_layout.addWidget(self._step_widget(i, step, step_index, is_done))

        is_grind = obj.kind == "grind"
        self.counter_row.setVisible(is_grind)
        if is_grind:
            count = self.progress.count(obj.id)
            unit = obj.goal_unit or "times"
            self.count_label.setText(f"{count} / {obj.goal_target} {unit}")
            self.count_label.setStyleSheet(_CYAN_STYLE if count >= obj.goal_target else _BODY_STYLE)
            self.minus_btn.setEnabled(count > 0)

        last = step_index >= len(obj.steps) - 1
        self.back_btn.setEnabled(step_index > 0 and not is_done)
        self.step_btn.setEnabled(True)
        if is_done:
            self.step_btn.setText("↺ UNDO DONE")
        elif last:
            self.step_btn.setText("✓ COMPLETE")
        else:
            self.step_btn.setText("✓ STEP DONE")
        self.skip_btn.setEnabled(not is_done)
        self.sources_btn.setEnabled(bool(obj.sources))
        self._render_list(chapter if not compact else None)
        self.list_container.setVisible(not compact)
        self._render_problems()
        self._fit_card()

    def _fit_card(self):
        # The step list and objective list change height with every render;
        # re-fit the card so nothing gets clipped (a manual size still wins).
        card = getattr(self, "card", None)
        if card is not None:
            card.apply_size()

    def _step_widget(self, i: int, step, current: int, objective_done: bool) -> QLabel:
        # One rich-text label per row: word-wrapped labels inside a nested
        # layout don't report their height reliably and got squeezed.
        is_current = i == current and not objective_done
        finished = objective_done or i < current
        mark = "✓" if finished else f"{i + 1}."
        color = theme.TEXT_DIM if finished else theme.TEXT_PRIMARY
        parts = [f'<span style="color:{color};">{escape(mark)} {escape(step.do)}</span>']
        if step.where and not finished:
            parts.append(f'<span style="color:{theme.TEXT_MUTED};">WHERE: {escape(step.where)}</span>')
        if is_current:
            parts.append(f'<span style="color:{theme.ACCENT_CYAN};">DONE WHEN: {escape(step.done_when)}</span>')
        row = QLabel("<br>".join(parts))
        row.setObjectName("lgRow")
        row.setTextFormat(Qt.RichText)
        row.setWordWrap(True)
        row.setTextInteractionFlags(Qt.NoTextInteraction)
        row.setStyleSheet(_STEP_CURRENT_STYLE if is_current else _STEP_STYLE)
        return row

    def _render_list(self, chapter):
        self._clear(self.list_layout)
        if chapter is None:
            return
        done = self.progress.done_ids()
        passed = self.progress.passed_ids()
        current = self.current_objective()
        for obj in chapter.objectives:
            if not self._visible(obj):
                continue
            is_current = current is not None and obj.id == current.id
            if obj.id in done:
                mark, color = "✓", theme.TEXT_DIM
            elif obj.id in passed:
                mark, color = "–", theme.TEXT_DIM
            else:
                mark, color = ("▸" if is_current else "○"), theme.TEXT_PRIMARY
            row = QLabel(f'<span style="color:{color};">{mark} {escape(obj.title)}</span>')
            row.setObjectName("lgRow")
            row.setTextFormat(Qt.RichText)
            row.setWordWrap(True)
            row.setTextInteractionFlags(Qt.NoTextInteraction)
            row.setCursor(Qt.PointingHandCursor)
            row.setToolTip("Click to open. Right-click to mark done or not done.")
            row.setStyleSheet(_ROW_CURRENT_STYLE if is_current else _ROW_STYLE)
            row.mousePressEvent = lambda event, oid=obj.id: (
                self._toggle_done(oid) if event.button() == Qt.RightButton else self._view(oid))
            self.list_layout.addWidget(row)

    def _render_problems(self):
        errors = self.guide.errors
        self.problems_label.setVisible(bool(errors))
        if errors:
            self.problems_label.setText(f"⚠ {len(errors)} guide content problem(s), hover for details")
            self.problems_label.setToolTip("\n".join(errors[:30]))

    def _price_text(self, obj) -> str:
        name = obj.ship.get("display") or obj.ship.get("uex_name")
        if self._price_rows is None:
            return f"PRICE: {name}: {self._price_error or 'loading from UEX…'}"
        best = guide_mod.cheapest_listing(self._price_rows, obj.ship["uex_name"])
        if best is None:
            return f"PRICE: {name}: not listed on UEX right now"
        return f"PRICE (UEX, live): {best['price_buy']:,} aUEC at {best.get('terminal_name') or 'unknown shop'}"

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _view(self, oid: str):
        self._viewing = oid
        self.progress.set_current(oid)
        self.render()
        self._maybe_fetch_prices()

    def _advance(self):
        """After finishing or skipping: go to the guide's next objective."""
        self._viewing = None
        nxt = guide_mod.next_objective(self.guide, self.progress.passed_ids(), *self._filters())
        self.progress.set_current(nxt.id if nxt else None)
        self.render()
        self._maybe_fetch_prices()

    def _on_step_done(self):
        obj = self.current_objective()
        if obj is None:
            return
        if self.progress.is_done(obj.id):
            self.progress.set_done(obj.id, False)
            self.progress.set_step(obj.id, 0)
            self._viewing = obj.id
            self.render()
            return
        step = self.progress.step(obj.id)
        if step < len(obj.steps) - 1:
            self.progress.set_step(obj.id, step + 1)
            self.render()
            return
        self.progress.set_done(obj.id, True)
        self._advance()

    def _on_back(self):
        obj = self.current_objective()
        if obj is not None:
            self.progress.set_step(obj.id, max(0, self.progress.step(obj.id) - 1))
            self.render()

    def _on_skip(self):
        obj = self.current_objective()
        if obj is not None:
            self.progress.set_skipped(obj.id, True)
            self._advance()

    def _on_count(self, delta: int):
        obj = self.current_objective()
        if obj is not None and obj.kind == "grind":
            self.progress.add_count(obj.id, delta)
            self.render()

    def _toggle_done(self, oid: str):
        self.progress.set_done(oid, not self.progress.is_done(oid))
        self.render()

    def _on_jump_next(self):
        self._advance()

    def _on_chapter_picked(self, index: int):
        chapter = self.guide.chapter(self.chapter_combo.itemData(index))
        if chapter is None:
            return
        passed = self.progress.passed_ids()
        visible = [o for o in chapter.objectives if self._visible(o)]
        target = next((o for o in visible if o.id not in passed), visible[0] if visible else None)
        if target is not None:
            self._view(target.id)

    def _show_sources(self):
        obj = self.current_objective()
        if obj is None or not obj.sources:
            return
        menu = QMenu(self.card)
        for url in obj.sources:
            act = menu.addAction(url)
            act.triggered.connect(lambda _=False, u=url: QDesktopServices.openUrl(QUrl(u)))
        menu.exec(self.sources_btn.mapToGlobal(self.sources_btn.rect().bottomLeft()))

    def _show_menu(self):
        menu = QMenu(self.card)
        for key, text in (("show_optional", "Show optional objectives"),
                          ("show_unlawful", "Show outlaw (illegal) content"),
                          ("compact", "Compact mode (current step only)")):
            act = menu.addAction(text)
            act.setCheckable(True)
            act.setChecked(bool(self.settings.get(key)))
            act.toggled.connect(lambda on, k=key: self._set_option(k, on))
        menu.addSeparator()
        obj = self.current_objective()
        if obj is not None:
            menu.addAction("Reset this objective").triggered.connect(lambda: self._reset_objective(obj.id))
            if obj.custom:
                menu.addAction("Delete this objective (yours)").triggered.connect(lambda: self._delete_custom(obj.id))
        menu.addAction("Reload guide files").triggered.connect(self._reload)
        menu.addAction("Open my guide folder").triggered.connect(self._open_user_folder)
        menu.addSeparator()
        menu.addAction("Reset ALL progress…").triggered.connect(self._reset_all)
        menu.exec(self.menu_btn.mapToGlobal(self.menu_btn.rect().bottomLeft()))

    def _set_option(self, key: str, on: bool):
        self.settings[key] = bool(on)
        self._save_settings()
        self._viewing = None
        self.render()

    def _reset_objective(self, oid: str):
        self.progress.reset(oid)
        self._viewing = oid
        self.render()

    def _reset_all(self):
        answer = QMessageBox.question(self.card, "Reset progress",
                                      "Clear every checkmark, step and counter? This can't be undone.")
        if answer == QMessageBox.Yes:
            self.progress.reset_all()
            self._viewing = None
            self.render()

    def _reload(self):
        self.reload_guide()
        self.render()

    def _open_user_folder(self):
        folder = progress_mod.user_guides_dir()
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _on_add_objective(self):
        current = self.current_objective()
        chapters = [(c.id, c.title) for c in self.guide.chapters if c.id != guide_mod.CUSTOM_CHAPTER_ID]
        dialog = AddObjectiveDialog(self.card, chapters, current.chapter_id if current else None)
        if dialog.exec() != QDialog.Accepted:
            return
        v = dialog.values()
        chapter_id = None if v["chapter_id"] == guide_mod.CUSTOM_CHAPTER_ID else v["chapter_id"]
        obj = self.custom.add(v["title"], v["steps"], chapter_id=chapter_id, why=v["why"], kind=v["kind"],
                              goal_target=v["goal_target"], goal_unit=v["goal_unit"],
                              existing_ids={o.id for o in self.guide.objectives})
        self.reload_guide()
        self._view(obj["id"])

    def _delete_custom(self, oid: str):
        answer = QMessageBox.question(self.card, "Delete objective", "Delete this objective you added?")
        if answer == QMessageBox.Yes and self.custom.remove(oid):
            self.progress.reset(oid)
            self.reload_guide()
            self._advance()

    # ------------------------------------------------------------------
    # ModuleBase refresh: UEX ship prices only
    # ------------------------------------------------------------------
    def _needs_prices(self) -> bool:
        obj = self.current_objective()
        if obj is None or not obj.ship:
            return False
        return self._price_rows is None or time.time() - self._price_at > PRICE_MAX_AGE_S

    def _maybe_fetch_prices(self):
        if self._needs_prices() and self.request_refresh is not None:
            self.request_refresh()

    def refresh(self):
        self.finish_refresh(self.refresh_job()())

    def refresh_job(self):
        if not self._needs_prices():
            return lambda: None

        def fetch():
            # A UEX failure must not put the whole guide card into its error
            # state: only the price line depends on it.
            try:
                return {"rows": self.api.get("vehicles_purchases_prices_all")}
            except Exception as exc:  # noqa: BLE001
                return {"error": str(exc) or exc.__class__.__name__}
        return fetch

    def finish_refresh(self, data):
        if not data:
            return
        if "error" in data:
            self._price_error = "UEX unavailable, will retry"
            self._price_at = time.time() - PRICE_MAX_AGE_S + 60  # retry in about a minute
        else:
            self._price_rows = list(data["rows"] or [])
            self._price_at = time.time()
            self._price_error = ""
        self.render()


MODULE_CLASS = LevelingGuideModule
