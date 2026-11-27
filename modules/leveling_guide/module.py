"""mobiGuide: a WoW-style leveling guide for Star Citizen. One objective at a
time, step by step, checked off by hand; per-patch guide packs, categories
for every part of the game, a level/XP bar, reputation tracking with the
best repeatable contracts for each rank, goals (rank, aUEC or a ship), and
objectives you can add yourself.

Content is data (guide.py loads patch packs; contracts.py reads each pack's
contract catalog), progress is a local file (progress.py). The only network
call is UEX's ship purchase prices, run off the GUI thread through
refresh_job().
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
    QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox,
    QProgressBar, QPushButton, QRadioButton, QSpinBox, QStackedWidget,
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
contracts_mod = _load_sibling("contracts")
packio_mod = _load_sibling("packio")

BUNDLED_PACKS = os.path.join(os.path.dirname(__file__), "packs")
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
_STEP_STYLE = f"QLabel#lgRow {{ {theme.row_style('6px 8px')} {theme.text_style(10, color=theme.TEXT_PRIMARY)} }}"
_STEP_CURRENT_STYLE = f"QLabel#lgRow {{ {theme.row_style('6px 8px', theme.ACCENT_CYAN)} {theme.text_style(10, color=theme.TEXT_PRIMARY)} }}"
_ROW_STYLE = f"QLabel#lgRow {{ {theme.row_style('3px 6px')} {theme.text_style(9, color=theme.TEXT_PRIMARY)} }}"
_ROW_CURRENT_STYLE = f"QLabel#lgRow {{ {theme.row_style('3px 6px', theme.ACCENT_CYAN)} {theme.text_style(9, color=theme.TEXT_PRIMARY)} }}"
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


HOW_TO_HTML = """
<p><b>Pick your game version and a category</b> at the top. Packs exist per
patch; categories cover hauling, mining, salvage, combat and more.</p>
<p><b>GUIDE:</b> follow the highlighted step, do it in game, press
<b>I DID THIS STEP</b>. The <b>DONE WHEN</b> line tells you how to know it worked.</p>
<p><b>Rank-ups:</b> the card shows your reputation and the best repeatable
contracts for it. Click a contract when you finish one; your reputation and
earnings update. <b>SET</b> corrects the number to what the game shows.</p>
<p><b>CONTRACTS:</b> set a goal (a rank, an amount of aUEC, or a ship) and the
card lists the contracts that get you there fastest, with how many runs are left.</p>
<p><b>Already done something?</b> Click its box in the checklist, or
&#9881; &rarr; <i>Mark this chapter done</i>. <b>SKIP</b> moves on without XP.</p>
<p><b>Flying?</b> &#9881; &rarr; <i>Compact mode</i> shows only the current step.</p>
<p>Objectives marked <b>CHECKED ON &lt;patch&gt;</b> were verified on an older
patch and not yet re-confirmed for the one you picked.</p>
<p>mobiGuide never reads the game. It only knows what you tick and log.</p>
"""


class SetupWizard(QDialog):
    """First-run questionnaire: game version, experience, ranks already
    held, categories to focus on, display options, then how to use it.
    Everything is built from the active pack, so new patches, categories and
    factions appear here without code changes."""

    def __init__(self, parent, packs: list, current_pack: str | None, ladders, categories, settings: dict):
        super().__init__(parent)
        self.setWindowTitle("mobiGuide setup")
        self.setMinimumWidth(460)
        outer = QVBoxLayout(self)
        self.step_label = _label("", _CYAN_STYLE, wrap=False)
        outer.addWidget(self.step_label)
        self.pages = QStackedWidget()
        outer.addWidget(self.pages, stretch=1)

        # 1. version and experience
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.addWidget(_label("Welcome to mobiGuide", _TITLE_STYLE))
        lay.addWidget(_label(
            "A step-by-step guide through every part of Star Citizen, like a leveling guide, "
            "with goals and repeatable contracts. A few quick pages set it up for you.", _MUTED_STYLE))
        lay.addWidget(_label("Which game version do you play?", _BODY_STYLE))
        self.pack_combo = QComboBox()
        self.pack_combo.setStyleSheet(_COMBO_STYLE)
        for pack in packs:
            self.pack_combo.addItem(pack.label, pack.id)
        idx = self.pack_combo.findData(current_pack)
        self.pack_combo.setCurrentIndex(max(0, idx))
        lay.addWidget(self.pack_combo)
        lay.addSpacing(6)
        lay.addWidget(_label("How much have you played?", _BODY_STYLE))
        self.new_radio = QRadioButton("I'm new: start from waking up in a city")
        self.basics_radio = QRadioButton("I know the basics: flying, landing and taking contracts")
        group = QButtonGroup(self)
        for r in (self.new_radio, self.basics_radio):
            r.setStyleSheet(_BODY_STYLE)
            group.addButton(r)
            lay.addWidget(r)
        self.new_radio.setChecked(True)
        lay.addStretch()
        self.pages.addWidget(page)

        # 2. ranks already held
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.addWidget(_label("Where are you already?", _TITLE_STYLE))
        lay.addWidget(_label(
            "Pick the rank you already hold. Everything up to it is ticked off and the "
            "card starts counting your reputation from there. Not sure? Leave it at Not started.",
            _MUTED_STYLE))
        grid = QGridLayout()
        self.rank_combos: dict[str, QComboBox] = {}
        for row, (faction, ladder, ranks) in enumerate(ladders):
            name = faction if ladder in ("FactionReputation", "") else f"{faction} ({guide_mod.ladder_name(ladder)})"
            grid.addWidget(_label(name, _BODY_STYLE, wrap=False), row, 0)
            combo = QComboBox()
            combo.setStyleSheet(_COMBO_STYLE)
            combo.addItem("Not started", None)
            for rank, points in ranks:
                combo.addItem(f"{rank} ({points:,})", points)
            grid.addWidget(combo, row, 1)
            self.rank_combos[guide_mod.rep_key(faction, ladder)] = combo
        lay.addLayout(grid)
        lay.addStretch()
        self.pages.addWidget(page)

        # 3. focus and display
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.addWidget(_label("What do you want to do?", _TITLE_STYLE))
        lay.addWidget(_label("Untick categories you don't care about. They are hidden, not deleted.",
                             _MUTED_STYLE))
        focus = set(settings.get("focus") or [])
        self.category_checks: dict[str, QCheckBox] = {}
        grid = QGridLayout()
        shown = [c for c in categories if c.id not in guide_mod.ALWAYS_SHOWN_CATEGORIES and c.id != "outlaw"]
        for i, cat in enumerate(shown):
            box = QCheckBox(cat.title)
            box.setStyleSheet(_BODY_STYLE)
            box.setToolTip(cat.summary)
            box.setChecked(not focus or cat.id in focus)
            self.category_checks[cat.id] = box
            grid.addWidget(box, i // 2, i % 2)
        lay.addLayout(grid)
        lay.addSpacing(6)
        self.outlaw_check = QCheckBox("Include outlaw (illegal) work")
        self.optional_check = QCheckBox("Show optional side objectives")
        self.compact_check = QCheckBox("Compact mode: only the current step (good while flying)")
        self.outlaw_check.setChecked(bool(settings.get("show_unlawful")))
        self.optional_check.setChecked(bool(settings.get("show_optional", True)))
        self.compact_check.setChecked(bool(settings.get("compact")))
        for box in (self.outlaw_check, self.optional_check, self.compact_check):
            box.setStyleSheet(_BODY_STYLE)
            lay.addWidget(box)
        lay.addStretch()
        self.pages.addWidget(page)

        # 4. how to use
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.addWidget(_label("How to use it", _TITLE_STYLE))
        how = _label(HOW_TO_HTML, _BODY_STYLE)
        how.setTextFormat(Qt.RichText)
        lay.addWidget(how)
        lay.addStretch()
        self.pages.addWidget(page)

        buttons = QHBoxLayout()
        self.cancel_btn = _button("CANCEL")
        self.back_btn = _button("◀ BACK")
        self.next_btn = _button("NEXT ▸", _PRIMARY_BTN)
        buttons.addWidget(self.cancel_btn)
        buttons.addStretch()
        buttons.addWidget(self.back_btn)
        buttons.addWidget(self.next_btn)
        for b in (self.cancel_btn, self.back_btn, self.next_btn):
            b.setMinimumWidth(100)
        outer.addLayout(buttons)
        self.cancel_btn.clicked.connect(self.reject)
        self.back_btn.clicked.connect(lambda: self.go(self.pages.currentIndex() - 1))
        self.next_btn.clicked.connect(self._on_next)
        self.go(0)

    def go(self, index: int):
        index = max(0, min(index, self.pages.count() - 1))
        self.pages.setCurrentIndex(index)
        last = index == self.pages.count() - 1
        self.back_btn.setEnabled(index > 0)
        self.next_btn.setText("START GUIDE" if last else "NEXT ▸")
        self.step_label.setText(f"SETUP  {index + 1} / {self.pages.count()}")

    def _on_next(self):
        if self.pages.currentIndex() == self.pages.count() - 1:
            self.accept()
        else:
            self.go(self.pages.currentIndex() + 1)

    def values(self) -> dict:
        chosen = {cid for cid, box in self.category_checks.items() if box.isChecked()}
        return {
            "pack": self.pack_combo.currentData(),
            "knows_basics": self.basics_radio.isChecked(),
            "reached": {k: c.currentData() for k, c in self.rank_combos.items() if c.currentData() is not None},
            # Everything ticked means no filter, so categories added later show up too.
            "focus": [] if len(chosen) == len(self.category_checks) else sorted(chosen),
            "show_unlawful": self.outlaw_check.isChecked(),
            "show_optional": self.optional_check.isChecked(),
            "compact": self.compact_check.isChecked(),
        }


class GoalDialog(QDialog):
    """New goal: reach a rank, save up aUEC, or buy a ship."""

    def __init__(self, parent, catalog, known_rep: dict, ships: list[str]):
        super().__init__(parent)
        self.setWindowTitle("New goal")
        self.setMinimumWidth(400)
        self.catalog = catalog
        self.known_rep = known_rep
        form = QFormLayout(self)
        self.kind_combo = QComboBox()
        self.kind_combo.setStyleSheet(_COMBO_STYLE)
        self.kind_combo.addItem("Reach a rank", "rank")
        self.kind_combo.addItem("Save up aUEC", "money")
        self.kind_combo.addItem("Buy a ship", "ship")
        form.addRow("Goal", self.kind_combo)

        self.faction_combo = QComboBox()
        self.ladder_combo = QComboBox()
        self.rank_combo = QComboBox()
        for c in (self.faction_combo, self.ladder_combo, self.rank_combo):
            c.setStyleSheet(_COMBO_STYLE)
        for f in (catalog.all_factions() if catalog else []):
            self.faction_combo.addItem(f, f)
        self.current_rep = QSpinBox()
        self.current_rep.setRange(-1_000_000, 10_000_000)
        self.current_rep.setStyleSheet(_SPIN_STYLE)
        form.addRow("Faction", self.faction_combo)
        form.addRow("Ladder", self.ladder_combo)
        form.addRow("Target rank", self.rank_combo)
        form.addRow("Your rep now", self.current_rep)

        self.amount_edit = QLineEdit()
        self.amount_edit.setStyleSheet(_LINE_STYLE)
        self.amount_edit.setPlaceholderText("e.g. 2500000")
        form.addRow("Target aUEC", self.amount_edit)
        self.ship_combo = QComboBox()
        self.ship_combo.setEditable(True)
        self.ship_combo.setStyleSheet(_COMBO_STYLE)
        self.ship_combo.addItems(ships)
        self.ship_combo.setToolTip("The ship's name as UEX lists it, e.g. Cutlass Black")
        form.addRow("Ship", self.ship_combo)
        self.wallet_edit = QLineEdit()
        self.wallet_edit.setStyleSheet(_LINE_STYLE)
        self.wallet_edit.setPlaceholderText("Your aUEC now (optional)")
        form.addRow("Wallet now", self.wallet_edit)
        self._rows = {"rank": (self.faction_combo, self.ladder_combo, self.rank_combo, self.current_rep),
                      "money": (self.amount_edit, self.wallet_edit), "ship": (self.ship_combo, self.wallet_edit)}
        self.form = form

        self.error_label = _label("", _AMBER_STYLE)
        form.addRow(self.error_label)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

        self.kind_combo.currentIndexChanged.connect(self._sync)
        self.faction_combo.currentIndexChanged.connect(self._fill_ladders)
        self.ladder_combo.currentIndexChanged.connect(self._fill_ranks)
        self._fill_ladders()
        self._sync()

    def _sync(self):
        kind = self.kind_combo.currentData()
        for k, widgets in self._rows.items():
            for w in widgets:
                visible = k == kind or (w is self.wallet_edit and kind in ("money", "ship"))
                w.setVisible(visible)
                label = self.form.labelForField(w)
                if label is not None:
                    label.setVisible(visible)

    def _fill_ladders(self):
        self.ladder_combo.blockSignals(True)
        self.ladder_combo.clear()
        faction = self.faction_combo.currentData()
        for ladder in (self.catalog.ladders_for(faction) if self.catalog and faction else []):
            self.ladder_combo.addItem(guide_mod.ladder_name(ladder), ladder)
        self.ladder_combo.blockSignals(False)
        self._fill_ranks()

    def _fill_ranks(self):
        self.rank_combo.clear()
        ladder = self.ladder_combo.currentData()
        for rank, points in (self.catalog.rank_names(ladder) if self.catalog and ladder else []):
            if points > 0:
                self.rank_combo.addItem(f"{rank} ({points:,})", (rank, points))
        faction = self.faction_combo.currentData()
        known = self.known_rep.get(guide_mod.rep_key(faction or "", ladder or ""))
        self.current_rep.setValue(int(known or 0))

    @staticmethod
    def _int(text: str) -> int | None:
        digits = "".join(ch for ch in text if ch.isdigit())
        return int(digits) if digits else None

    def _on_accept(self):
        kind = self.kind_combo.currentData()
        if kind == "rank" and self.rank_combo.currentData() is None:
            self.error_label.setText("Pick a faction, ladder and rank.")
            return
        if kind == "money" and not self._int(self.amount_edit.text()):
            self.error_label.setText("Enter how much aUEC you want.")
            return
        if kind == "ship" and not self.ship_combo.currentText().strip():
            self.error_label.setText("Pick or type a ship.")
            return
        self.accept()

    def values(self) -> dict:
        kind = self.kind_combo.currentData()
        wallet = self._int(self.wallet_edit.text()) or 0
        if kind == "rank":
            rank, points = self.rank_combo.currentData()
            faction, ladder = self.faction_combo.currentData(), self.ladder_combo.currentData()
            return {"kind": "rank", "faction": faction, "ladder": ladder, "rank": rank, "target": points,
                    "current_rep": self.current_rep.value(),
                    "label": f"{faction}: {rank}"}
        if kind == "money":
            amount = self._int(self.amount_edit.text())
            return {"kind": "money", "target": amount, "start_uec": wallet, "label": f"Save {amount:,} aUEC"}
        ship = self.ship_combo.currentText().strip()
        return {"kind": "ship", "ship": ship, "start_uec": wallet, "label": f"Buy a {ship}"}


class LevelingGuideModule(ModuleBase):
    module_id = "leveling_guide"
    display_name = (
        f'<span style="color:{theme.TEXT_PRIMARY};">mobi</span>'
        f'<span style="color:{theme.ACCENT_CYAN};">Guide</span>'
    )
    ROW_BOX_WIDTH = 26     # px from a checklist row's left edge that count as its box
    CONTRACT_ROWS = 5      # repeatable contracts shown under a rank-up
    GOAL_ROWS = 8          # contracts shown in the Contracts view

    def __init__(self, api_client, config, locations, progress=None, custom=None, pack_roots=None, extra_dirs=None):
        super().__init__(api_client, config, locations)
        for key, value in (("show_optional", True), ("show_unlawful", False), ("compact", False),
                           ("focus", []), ("setup_done", False), ("refresh_interval_seconds", 600),
                           ("view", "now"), ("category", ""), ("pack", None), ("goal", None),
                           ("f_type", ""), ("f_system", ""), ("f_unlocked", False)):
            self.settings.setdefault(key, value)
        self.progress = progress or progress_mod.ProgressStore()
        self.custom = custom or progress_mod.CustomObjectives()
        self._pack_roots = pack_roots or [Path(BUNDLED_PACKS), progress_mod.user_guides_dir() / "packs"]
        self._extra_dirs = [progress_mod.user_guides_dir()] if extra_dirs is None else extra_dirs
        self.guide = None
        self.packs: dict = {}
        self.categories: list = []
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
        self.packs, _ = guide_mod.discover_packs(self._pack_roots)
        self.guide = guide_mod.load_pack(self.settings.get("pack"), self._pack_roots, self._extra_dirs,
                                         self.custom.path, catalog_loader=contracts_mod.load_catalog)
        if self.guide.pack is not None:
            self.settings["pack"] = self.guide.pack.id
        self.categories = contracts_mod.parse_categories(self.guide.categories)

    def _filters(self) -> tuple[bool, bool, frozenset]:
        return (bool(self.settings.get("show_optional")), bool(self.settings.get("show_unlawful")),
                frozenset(self.settings.get("focus") or []))

    def _visible(self, obj) -> bool:
        if not guide_mod.is_visible(obj, *self._filters()):
            return False
        cat = self.settings.get("category")
        return not cat or cat in obj.categories or not obj.categories

    def _category(self):
        cid = self.settings.get("category")
        return next((c for c in self.categories if c.id == cid), None)

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
        return self._next_visible()

    def _next_visible(self):
        passed = self.progress.passed_ids()
        remaining = [o for o in self.guide.objectives if o.id not in passed and self._visible(o)]
        for obj in remaining:
            if guide_mod.is_unlocked(obj, passed):
                return obj
        return remaining[0] if remaining else None

    def _save_settings(self):
        self.config.set_module_settings(self.module_id, self.settings)

    def known_rep(self) -> dict[str, int]:
        """Reputation the player has told us or logged, plus what finished
        rank-up objectives imply (you're at least that far)."""
        known = self.progress.known_rep()
        done = self.progress.done_ids()
        for obj in self.guide.objectives:
            rep = obj.reputation
            if obj.id in done and rep and isinstance(rep.get("points"), int):
                key = guide_mod.rep_key(rep["faction"], rep.get("ladder", ""))
                known[key] = max(known.get(key, rep["points"]), rep["points"])
        return known

    # ------------------------------------------------------------------
    # Card
    # ------------------------------------------------------------------
    def create_card(self, container):
        card = container.add_card(self.module_id, self.display_name)
        layout = card.body_layout

        # -- level / XP -----------------------------------------------------
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

        # -- first-run banner: a label plus a button row, so it sizes reliably
        self.setup_text = QLabel(
            "<b>New to mobiGuide?</b> A one-minute setup picks your game version, ticks off "
            "what you've already done and chooses what to show.")
        self.setup_text.setObjectName("lgRow")
        self.setup_text.setTextFormat(Qt.RichText)
        self.setup_text.setWordWrap(True)
        self.setup_text.setStyleSheet(_STEP_CURRENT_STYLE)
        layout.addWidget(self.setup_text)
        self.setup_buttons = QWidget()
        sb = QHBoxLayout(self.setup_buttons)
        sb.setContentsMargins(0, 0, 0, 0)
        self.setup_btn = _button("START SETUP", _PRIMARY_BTN)
        self.setup_btn.clicked.connect(self.run_setup)
        sb.addWidget(self.setup_btn, stretch=2)
        self.setup_later_btn = _button("NOT NOW", tooltip="Setup stays in the ⚙ menu")
        self.setup_later_btn.clicked.connect(self._dismiss_setup)
        sb.addWidget(self.setup_later_btn, stretch=1)
        layout.addWidget(self.setup_buttons)

        # -- view switch, version and category ------------------------------
        nav = QHBoxLayout()
        nav.setSpacing(4)
        self.now_tab = _button("NOW", tooltip="Just the next thing to do")
        self.guide_tab = _button("FULL GUIDE", tooltip="Every step, chapter and objective")
        self.contracts_tab = _button("CONTRACTS", tooltip="Goals and repeatable contracts")
        self.now_tab.clicked.connect(lambda: self.set_view("now"))
        self.guide_tab.clicked.connect(lambda: self.set_view("guide"))
        self.contracts_tab.clicked.connect(lambda: self.set_view("contracts"))
        nav.addWidget(self.now_tab, stretch=1)
        nav.addWidget(self.guide_tab, stretch=1)
        nav.addWidget(self.contracts_tab, stretch=1)
        layout.addLayout(nav)
        self.cat_widget = QWidget()
        cat_row = QHBoxLayout(self.cat_widget)
        cat_row.setContentsMargins(0, 0, 0, 0)
        cat_row.setSpacing(6)
        self.category_combo = QComboBox()
        self.category_combo.setStyleSheet(_COMBO_STYLE)
        self.category_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.category_combo.setMinimumContentsLength(14)
        self.category_combo.activated.connect(self._on_category_picked)
        cat_row.addWidget(self.category_combo, stretch=1)
        self.pack_label = _label("", _DIM_STYLE, wrap=False)
        self.pack_label.setToolTip("Game version this guide is for. Change it in ⚙.")
        cat_row.addWidget(self.pack_label)
        layout.addWidget(self.cat_widget)

        # -- contract filter row: shown wherever a contract list is
        self.filter_row = QWidget()
        fr = QHBoxLayout(self.filter_row)
        fr.setContentsMargins(0, 0, 0, 0)
        fr.setSpacing(4)
        self.type_combo = QComboBox()
        self.system_combo = QComboBox()
        for combo, tip in ((self.type_combo, "Only this kind of contract"),
                           (self.system_combo, "Only contracts offered in this system")):
            combo.setStyleSheet(_COMBO_STYLE)
            combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(8)
            combo.setToolTip(tip)
            fr.addWidget(combo, stretch=1)
        self.type_combo.activated.connect(lambda i: self._set_filter("f_type", self.type_combo.itemData(i) or ""))
        self.system_combo.activated.connect(lambda i: self._set_filter("f_system", self.system_combo.itemData(i) or ""))
        self.unlocked_check = QCheckBox("Unlocked")
        self.unlocked_check.setStyleSheet(_MUTED_STYLE)
        self.unlocked_check.setToolTip("Hide contracts your known rank can't take yet")
        self.unlocked_check.toggled.connect(lambda on: self._set_filter("f_unlocked", bool(on)))
        fr.addWidget(self.unlocked_check)
        layout.addWidget(self.filter_row)

        # ================= NOW view =================
        self.now_view = QWidget()
        nl = QVBoxLayout(self.now_view)
        nl.setContentsMargins(0, 0, 0, 0)
        nl.setSpacing(6)
        self.now_where = _label("", _CYAN_STYLE)
        nl.addWidget(self.now_where)
        self.now_bar = QProgressBar()
        self.now_bar.setStyleSheet(_XP_BAR.replace(theme.ACCENT_AMBER, theme.ACCENT_CYAN))
        self.now_bar.setTextVisible(False)
        self.now_bar.setFixedHeight(6)
        nl.addWidget(self.now_bar)
        self.now_title = _label("", _TITLE_STYLE)
        nl.addWidget(self.now_title)
        self.now_step = _label("", _DIM_STYLE, wrap=False)
        nl.addWidget(self.now_step)
        self.now_body = QLabel()
        self.now_body.setObjectName("lgRow")
        self.now_body.setTextFormat(Qt.RichText)
        self.now_body.setWordWrap(True)
        self.now_body.setStyleSheet(_STEP_CURRENT_STYLE)
        nl.addWidget(self.now_body)
        self.now_info = _label("", _AMBER_STYLE)
        self.now_info.setTextFormat(Qt.RichText)
        nl.addWidget(self.now_info)
        self.now_count_row = QWidget()
        ncr = QHBoxLayout(self.now_count_row)
        ncr.setContentsMargins(0, 0, 0, 0)
        self.now_count = _label("", _BODY_STYLE, wrap=False)
        ncr.addWidget(self.now_count, stretch=1)
        self.now_plus = _button("+1", _PRIMARY_BTN, "Count one more")
        self.now_plus.setFixedSize(44, 26)
        self.now_plus.clicked.connect(lambda: self._on_count(1))
        ncr.addWidget(self.now_plus)
        nl.addWidget(self.now_count_row)
        self.now_done_btn = _button("✓ DONE", _PRIMARY_BTN, "Finished this step: show me the next one")
        self.now_done_btn.setMinimumHeight(34)
        self.now_done_btn.clicked.connect(self._on_step_done)
        nl.addWidget(self.now_done_btn)
        now_actions = QHBoxLayout()
        now_actions.setSpacing(4)
        self.now_back_btn = _button("◀ BACK", tooltip="Go back one step")
        self.now_back_btn.clicked.connect(self._on_back)
        now_actions.addWidget(self.now_back_btn)
        self.now_skip_btn = _button("SKIP", tooltip="Skip this objective for now (no XP). It stays unticked.")
        self.now_skip_btn.clicked.connect(self._on_skip)
        now_actions.addWidget(self.now_skip_btn)
        nl.addLayout(now_actions)
        self.now_next = _label("", _DIM_STYLE)
        nl.addWidget(self.now_next)
        layout.addWidget(self.now_view)

        # ================= GUIDE view =================
        self.guide_view = QWidget()
        gl = QVBoxLayout(self.guide_view)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.setSpacing(6)
        chap_row = QHBoxLayout()
        chap_row.setSpacing(6)
        self.chapter_combo = QComboBox()
        self.chapter_combo.setStyleSheet(_COMBO_STYLE)
        self.chapter_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.chapter_combo.setMinimumContentsLength(16)
        self.chapter_combo.activated.connect(self._on_chapter_picked)
        chap_row.addWidget(self.chapter_combo, stretch=1)
        self.next_btn = _button("NEXT ▸", _ICON_BTN, "Jump to the guide's next objective")
        self.next_btn.setFixedHeight(26)
        self.next_btn.setMinimumWidth(56)
        self.next_btn.clicked.connect(self._on_jump_next)
        chap_row.addWidget(self.next_btn)
        gl.addLayout(chap_row)

        self.badges_label = _label("", _CYAN_STYLE)
        gl.addWidget(self.badges_label)
        self.title_label = _label("", _TITLE_STYLE)
        gl.addWidget(self.title_label)
        self.why_label = _label("", _MUTED_STYLE)
        gl.addWidget(self.why_label)
        self.info_label = _label("", _AMBER_STYLE)
        self.info_label.setTextFormat(Qt.RichText)
        gl.addWidget(self.info_label)
        self.lock_label = _label("", _AMBER_STYLE)
        gl.addWidget(self.lock_label)

        gl.addWidget(_label("STEPS", _LABEL_SMALL, wrap=False))
        self.steps_layout = QVBoxLayout()
        self.steps_layout.setSpacing(4)
        gl.addLayout(self.steps_layout)

        # reputation tracker for rank-ups
        self.rep_box = QWidget()
        rl = QVBoxLayout(self.rep_box)
        rl.setContentsMargins(0, 2, 0, 0)
        rl.setSpacing(4)
        rep_head = QHBoxLayout()
        self.rep_label = _label("", _CYAN_STYLE)
        rep_head.addWidget(self.rep_label, stretch=1)
        self.rep_set_btn = _button("SET", _ICON_BTN, "Type in the reputation the game shows")
        self.rep_set_btn.setFixedSize(44, 24)
        self.rep_set_btn.clicked.connect(self._on_set_rep)
        rep_head.addWidget(self.rep_set_btn)
        rl.addLayout(rep_head)
        self.rep_bar = QProgressBar()
        self.rep_bar.setStyleSheet(_XP_BAR.replace(theme.ACCENT_AMBER, theme.ACCENT_CYAN))
        self.rep_bar.setTextVisible(False)
        self.rep_bar.setFixedHeight(6)
        rl.addWidget(self.rep_bar)
        rl.addWidget(_label("REPEAT FOR REPUTATION · click one when you finish it", _LABEL_SMALL))
        self.rep_rows = QVBoxLayout()
        self.rep_rows.setSpacing(3)
        rl.addLayout(self.rep_rows)
        gl.addWidget(self.rep_box)

        # plain counter for grinds without reputation data
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
        gl.addWidget(self.counter_row)

        actions = QHBoxLayout()
        actions.setSpacing(4)
        self.back_btn = _button("◀ BACK", tooltip="Go back one step")
        self.back_btn.clicked.connect(self._on_back)
        actions.addWidget(self.back_btn)
        self.step_btn = _button("✓ I DID THIS STEP", _PRIMARY_BTN, "Mark the highlighted step done")
        self.step_btn.clicked.connect(self._on_step_done)
        actions.addWidget(self.step_btn, stretch=2)
        self.skip_btn = _button("SKIP", tooltip="Skip this objective for now (no XP). It stays unticked.")
        self.skip_btn.clicked.connect(self._on_skip)
        actions.addWidget(self.skip_btn)
        gl.addLayout(actions)

        self.list_container = QWidget()
        list_layout = QVBoxLayout(self.list_container)
        list_layout.setContentsMargins(0, 4, 0, 0)
        list_layout.setSpacing(3)
        list_layout.addWidget(_label("IN THIS CHAPTER", _LABEL_SMALL, wrap=False))
        self.list_layout = QVBoxLayout()
        self.list_layout.setSpacing(3)
        list_layout.addLayout(self.list_layout)
        gl.addWidget(self.list_container)

        footer = QHBoxLayout()
        self.sources_btn = _button("SOURCES", tooltip="Where this objective's facts come from")
        self.sources_btn.clicked.connect(self._show_sources)
        footer.addWidget(self.sources_btn)
        self.add_btn = _button("+ ADD OBJECTIVE")
        self.add_btn.clicked.connect(self._on_add_objective)
        footer.addWidget(self.add_btn)
        gl.addLayout(footer)
        layout.addWidget(self.guide_view)

        # ================= CONTRACTS view =================
        self.contracts_view = QWidget()
        cl = QVBoxLayout(self.contracts_view)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(6)
        goal_row = QHBoxLayout()
        goal_row.setSpacing(4)
        self.goal_combo = QComboBox()
        self.goal_combo.setStyleSheet(_COMBO_STYLE)
        self.goal_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.goal_combo.setMinimumContentsLength(14)
        self.goal_combo.activated.connect(self._on_goal_picked)
        goal_row.addWidget(self.goal_combo, stretch=1)
        self.new_goal_btn = _button("+ GOAL", _ICON_BTN, "Set a new goal")
        self.new_goal_btn.setFixedHeight(26)
        self.new_goal_btn.setMinimumWidth(56)
        self.new_goal_btn.clicked.connect(self._on_new_goal)
        goal_row.addWidget(self.new_goal_btn)
        self.del_goal_btn = _button("✕", _ICON_BTN, "Delete this goal")
        self.del_goal_btn.setFixedSize(26, 26)
        self.del_goal_btn.clicked.connect(self._on_delete_goal)
        goal_row.addWidget(self.del_goal_btn)
        cl.addLayout(goal_row)
        self.goal_title = _label("", _TITLE_STYLE)
        cl.addWidget(self.goal_title)
        goal_head = QHBoxLayout()
        self.goal_label = _label("", _CYAN_STYLE)
        goal_head.addWidget(self.goal_label, stretch=1)
        self.goal_set_btn = _button("SET", _ICON_BTN, "Type in the number the game shows")
        self.goal_set_btn.setFixedSize(44, 24)
        self.goal_set_btn.clicked.connect(self._on_set_goal_value)
        goal_head.addWidget(self.goal_set_btn)
        cl.addLayout(goal_head)
        self.goal_bar = QProgressBar()
        self.goal_bar.setStyleSheet(_XP_BAR.replace(theme.ACCENT_AMBER, theme.ACCENT_CYAN))
        self.goal_bar.setTextVisible(False)
        self.goal_bar.setFixedHeight(6)
        cl.addWidget(self.goal_bar)
        self.contracts_caption = _label("", _LABEL_SMALL)
        cl.addWidget(self.contracts_caption)
        self.goal_rows = QVBoxLayout()
        self.goal_rows.setSpacing(3)
        cl.addLayout(self.goal_rows)
        self.contracts_note = _label("", _DIM_STYLE)
        cl.addWidget(self.contracts_note)
        layout.addWidget(self.contracts_view)

        # -- shared footer ----------------------------------------------------
        bottom = QHBoxLayout()
        self.undo_btn = _button("↶ UNDO LAST RUN", tooltip="Take back the last contract you logged")
        self.undo_btn.clicked.connect(self._on_undo_run)
        bottom.addWidget(self.undo_btn)
        layout.addLayout(bottom)
        self.earned_label = _label("", _DIM_STYLE)
        layout.addWidget(self.earned_label)
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

    def _fit_card(self):
        # Content height changes with every render; re-fit so nothing is
        # clipped (a manual size still wins).
        card = getattr(self, "card", None)
        if card is not None:
            card.apply_size()

    def render(self):
        if not hasattr(self, "title_label"):
            return
        view = self.settings.get("view") or "guide"
        show_banner = not self.settings.get("setup_done") and not self.settings.get("setup_dismissed")
        self.setup_text.setVisible(show_banner)
        self.setup_buttons.setVisible(show_banner)
        self.now_tab.setStyleSheet(_PRIMARY_BTN if view == "now" else _ACTION_BTN)
        self.guide_tab.setStyleSheet(_PRIMARY_BTN if view == "guide" else _ACTION_BTN)
        self.contracts_tab.setStyleSheet(_PRIMARY_BTN if view == "contracts" else _ACTION_BTN)
        pack = self.guide.pack
        self.pack_label.setText(pack.label if pack else "no pack")
        self._render_header()
        self._render_categories()
        self.now_view.setVisible(view == "now")
        self.guide_view.setVisible(view == "guide")
        self.contracts_view.setVisible(view == "contracts")
        self.cat_widget.setVisible(view != "now")
        self._render_guide()          # always: keeps the hidden widgets current
        if view == "now":
            self._render_now()
            self._render_filters(False)
        elif view == "guide":
            self._render_filters(self.rep_box.isVisibleTo(self.card))
        else:
            self._render_contracts()
            self._render_filters(True)
        self.undo_btn.setEnabled(self.progress.last_run() is not None)
        last = self.progress.last_run()
        self.undo_btn.setToolTip(f"Take back: {last['title']}" if last else "Nothing logged yet")
        self.earned_label.setText(f"Logged earnings: {self.progress.earned_uec:,} aUEC"
                                  if self.progress.earned_uec else "")
        self.earned_label.setVisible(bool(self.progress.earned_uec))
        errors = self.guide.errors
        self.problems_label.setVisible(bool(errors))
        if errors:
            self.problems_label.setText(f"⚠ {len(errors)} guide content problem(s), hover for details")
            self.problems_label.setToolTip("\n".join(errors[:30]))
        self._fit_card()

    def contract_filter(self):
        return contracts_mod.ContractFilter(
            types=frozenset([self.settings["f_type"]]) if self.settings.get("f_type") else frozenset(),
            system=self.settings.get("f_system") or "",
            unlocked_only=bool(self.settings.get("f_unlocked")))

    def _render_filters(self, visible: bool):
        catalog = self.guide.catalog
        self.filter_row.setVisible(visible and catalog is not None)
        if not visible or catalog is None:
            return
        for combo, items, key, everything in ((self.type_combo, catalog.types(), "f_type", "All types"),
                                              (self.system_combo, catalog.systems(), "f_system", "All systems")):
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(everything, "")
            for item in items:
                combo.addItem(item, item)
            idx = combo.findData(self.settings.get(key) or "")
            combo.setCurrentIndex(max(0, idx))
            combo.blockSignals(False)
        self.unlocked_check.blockSignals(True)
        self.unlocked_check.setChecked(bool(self.settings.get("f_unlocked")))
        self.unlocked_check.blockSignals(False)

    def _set_filter(self, key: str, value):
        self.settings[key] = value
        self._save_settings()
        self.render()

    def _render_header(self):
        done = self.progress.done_ids()
        level, into, need = guide_mod.level_for_xp(guide_mod.total_xp(self.guide, done))
        self.level_label.setText(f"LVL {level}")
        self.xp_bar.setMaximum(need)
        self.xp_bar.setValue(into)
        visible = [o for o in self.guide.objectives if guide_mod.is_visible(o, *self._filters())]
        done_visible = sum(1 for o in visible if o.id in done)
        self.xp_label.setText(f"{into}/{need} XP · {done_visible}/{len(visible)} objectives")

    def _render_categories(self):
        self.category_combo.blockSignals(True)
        self.category_combo.clear()
        self.category_combo.addItem("All categories", "")
        catalog = self.guide.catalog
        for cat in self.categories:
            has_guide = bool(self.guide.chapters_in(cat.id))
            has_contracts = bool(catalog and any(cat.matches(c) for c in catalog.contracts))
            if has_guide or has_contracts:
                self.category_combo.addItem(cat.title, cat.id)
        idx = self.category_combo.findData(self.settings.get("category") or "")
        self.category_combo.setCurrentIndex(max(0, idx))
        self.category_combo.blockSignals(False)

    # -- guide view ------------------------------------------------------------
    def _render_guide(self):
        show_opt, show_unl, focus = self._filters()
        done = self.progress.done_ids()
        passed = self.progress.passed_ids()
        compact = bool(self.settings.get("compact"))
        obj = self.current_objective()
        chapter = self.guide.chapter(obj.chapter_id) if obj else None

        self.chapter_combo.blockSignals(True)
        self.chapter_combo.clear()
        for c in self.guide.chapters_in(self.settings.get("category")):
            d, t = guide_mod.chapter_progress(c, done, show_opt, show_unl, focus)
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
        self._clear(self.rep_rows)
        if obj is None:
            cat = self._category()
            self.badges_label.setText("NOTHING LEFT HERE")
            self.title_label.setText("Every visible objective in this view is done." if not cat else
                                     f"No guide objectives left in {cat.title}.")
            self.why_label.setText("Try the CONTRACTS tab for repeatable work, pick another category, "
                                   "turn on optional or outlaw content in ⚙, or add your own objective.")
            self.why_label.setVisible(True)
            for w in (self.info_label, self.lock_label, self.counter_row, self.rep_box):
                w.setVisible(False)
            for b in (self.back_btn, self.step_btn, self.skip_btn, self.sources_btn):
                b.setEnabled(False)
            self._render_list(None)
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
        if not self.guide.is_verified(obj):
            info.append(f"CHECKED ON {obj.verified_patch}: not yet re-confirmed for "
                        f"{self.guide.pack.label if self.guide.pack else 'this version'}")
        if obj.reputation:
            rep = obj.reputation
            pts = f" ({rep['points']:,} rep)" if isinstance(rep.get("points"), int) else ""
            info.append(f"TARGET: {rep['faction']} · {rep['rank']}{pts}")
        if obj.reward:
            info.append(f"REWARD: {escape(obj.reward)}")
        if obj.cost:
            info.append(f"COST: {escape(obj.cost)}")
        if obj.ship:
            info.append(self._price_text(obj.ship.get("display") or obj.ship.get("uex_name"), obj.ship["uex_name"]))
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

        tracked = self._render_rep_tracker(obj, compact)
        is_grind = obj.kind == "grind" and not tracked
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
            self.step_btn.setText("↺ NOT DONE YET")
        elif last:
            self.step_btn.setText("✓ FINISH OBJECTIVE")
        else:
            self.step_btn.setText("✓ I DID THIS STEP")
        self.skip_btn.setEnabled(not is_done)
        self.sources_btn.setEnabled(bool(obj.sources))
        self._render_list(chapter if not compact else None)
        self.list_container.setVisible(not compact)

    def _render_now(self):
        """The simple view: where you are, what to do now, one big button."""
        show_opt, show_unl, focus = self._filters()
        done = self.progress.done_ids()
        obj = self.current_objective()
        if obj is None:
            self.now_where.setText("ALL CAUGHT UP")
            self.now_bar.setVisible(False)
            self.now_title.setText("Nothing left to do in this view.")
            self.now_step.setVisible(False)
            self.now_body.setText("Open <b>CONTRACTS</b> for repeatable work to earn money or reputation, "
                                  "or <b>FULL GUIDE</b> to pick another chapter or category.")
            for w in (self.now_info, self.now_count_row, self.now_next):
                w.setVisible(False)
            for b in (self.now_done_btn, self.now_back_btn, self.now_skip_btn):
                b.setEnabled(False)
            self.now_done_btn.setText("✓ DONE")
            return
        chapter = self.guide.chapter(obj.chapter_id)
        is_done = obj.id in done
        d, t = guide_mod.chapter_progress(chapter, done, show_opt, show_unl, focus) if chapter else (0, 0)
        self.now_where.setText(f"{chapter.title.upper() if chapter else 'GUIDE'}  ·  {d} OF {t} DONE")
        self.now_bar.setVisible(t > 0)
        self.now_bar.setMaximum(max(1, t))
        self.now_bar.setValue(min(d, t))
        self.now_title.setText(obj.title)

        step_index = min(self.progress.step(obj.id), len(obj.steps) - 1)
        step = obj.steps[step_index]
        self.now_step.setVisible(True)
        self.now_step.setText("OBJECTIVE COMPLETE" if is_done else f"STEP {step_index + 1} OF {len(obj.steps)}")
        parts = [f'<span style="color:{theme.TEXT_PRIMARY};">{escape(step.do)}</span>']
        if step.where and not is_done:
            parts.append(f'<span style="color:{theme.TEXT_MUTED};">WHERE: {escape(step.where)}</span>')
        if not is_done:
            parts.append(f'<span style="color:{theme.ACCENT_CYAN};">DONE WHEN: {escape(step.done_when)}</span>')
        self.now_body.setText("<br>".join(parts))

        info = []
        if not self.guide.is_verified(obj):
            info.append(f"⚠ Not re-checked for {self.guide.pack.label if self.guide.pack else 'this version'} "
                        f"(last checked {escape(str(obj.verified_patch))})")
        rep = obj.reputation
        catalog = self.guide.catalog
        if rep and isinstance(rep.get("points"), int) and catalog is not None:
            key = guide_mod.rep_key(rep["faction"], rep.get("ladder", ""))
            known = self.known_rep()
            have = known.get(key)
            if have is None:
                info.append(f"GOAL: {escape(rep['faction'])} · {escape(rep['rank'])} "
                            f"({rep['points']:,} rep). Set your current rep in FULL GUIDE.")
            else:
                info.append(f"GOAL: {escape(rep['rank'])}: {have:,} / {rep['points']:,} · "
                            f"{max(0, rep['points'] - have):,} to go")
            best = contracts_mod.for_reputation(catalog, rep["faction"], rep.get("ladder", ""), known,
                                                bool(self.settings.get("show_unlawful")), None, 1,
                                                self.contract_filter())
            if best:
                c = best[0]["contract"]
                info.append(f"BEST CONTRACT TO REPEAT: {escape(c['title'])} (+{best[0]['gain']:,} rep)")
        if obj.cost:
            info.append(f"COST: {escape(obj.cost)}")
        if obj.ship:
            info.append(self._price_text(obj.ship.get("display") or obj.ship.get("uex_name"), obj.ship["uex_name"]))
        self.now_info.setText("<br>".join(info))
        self.now_info.setVisible(bool(info))

        is_grind = obj.kind == "grind" and not (rep and isinstance(rep.get("points"), int) and catalog is not None)
        self.now_count_row.setVisible(is_grind)
        if is_grind:
            count = self.progress.count(obj.id)
            self.now_count.setText(f"{count} / {obj.goal_target} {obj.goal_unit or 'times'}")

        last = step_index >= len(obj.steps) - 1
        self.now_done_btn.setEnabled(True)
        self.now_done_btn.setText("↺ NOT DONE YET" if is_done else
                                  "✓ DONE: FINISH OBJECTIVE" if last else "✓ DONE: NEXT STEP")
        self.now_back_btn.setEnabled(step_index > 0 and not is_done)
        self.now_skip_btn.setEnabled(not is_done)

        passed = self.progress.passed_ids()
        later = [o for o in self.guide.objectives if o.id not in passed and o.id != obj.id and self._visible(o)]
        idx = next((i for i, o in enumerate(self.guide.objectives) if o.id == obj.id), -1)
        nxt = next((o for o in later if self.guide.objectives.index(o) > idx), later[0] if later else None)
        self.now_next.setText(f"NEXT UP: {nxt.title}" if nxt and last else "")
        self.now_next.setVisible(bool(nxt) and last)

    def _render_rep_tracker(self, obj, compact: bool) -> bool:
        """Reputation progress plus the best repeatable contracts for a
        rank-up. Returns False when there's nothing to track."""
        rep = obj.reputation
        catalog = self.guide.catalog
        if not rep or not isinstance(rep.get("points"), int) or catalog is None:
            self.rep_box.setVisible(False)
            return False
        faction, ladder, target = rep["faction"], rep.get("ladder", ""), rep["points"]
        key = guide_mod.rep_key(faction, ladder)
        known = self.known_rep()
        current = known.get(key)
        rows = contracts_mod.for_reputation(catalog, faction, ladder, known,
                                            bool(self.settings.get("show_unlawful")), None, self.CONTRACT_ROWS,
                                            self.contract_filter())
        if not rows and current is None:
            self.rep_box.setVisible(False)
            return False
        self.rep_box.setVisible(True)
        shown = current if current is not None else 0
        remaining = max(0, target - shown)
        status = "TARGET REACHED" if remaining == 0 else f"{remaining:,} to go"
        guess = "" if current is not None else " (not set: press SET)"
        self.rep_label.setText(f"{guide_mod.ladder_name(ladder).upper()}: {shown:,} / {target:,} · {status}{guess}")
        self.rep_bar.setMaximum(max(1, target))
        self.rep_bar.setValue(min(target, max(0, shown)))
        for r in rows:
            self.rep_rows.addWidget(self._contract_row(r, remaining, rep_amount=True))
        if not rows:
            self.rep_rows.addWidget(_label("No repeatable contracts match: clear the filters above, or none "
                                           f"exist for this in the {catalog.label} data.", _DIM_STYLE))
        return True

    def _contract_row(self, row: dict, remaining: int, rep_amount: bool) -> QLabel:
        c = row["contract"]
        gain = row["gain"]
        bits = [escape(c.get("giver") or "")]
        bits.append(f"+{gain:,} rep" if rep_amount else f"{gain:,} aUEC")
        if rep_amount and contracts_mod.fmt_uec(c):
            bits.append(contracts_mod.fmt_uec(c))
        if remaining > 0 and gain > 0:
            bits.append(f"≈{contracts_mod.runs_needed(remaining, gain)} to go")
        runs = self.progress.runs_logged(c["key"])
        if runs:
            bits.append(f"done ×{runs}")
        if c.get("illegal"):
            bits.append("ILLEGAL")
        if c.get("conflicts"):
            bits.append("⚠ sources differ")
        unlocked = row["unlocked"]
        req = c.get("requires")
        if unlocked is False and req:
            bits.append(f"needs {req['rank']}")
        elif unlocked is None and req:
            bits.append(f"needs {req['rank']}?")
        title_color = theme.TEXT_DIM if unlocked is False else theme.TEXT_PRIMARY
        label = QLabel(f'<span style="color:{theme.ACCENT_CYAN};">+1</span> '
                       f'<span style="color:{title_color};">{escape(c["title"])}</span><br>'
                       f'<span style="color:{theme.TEXT_MUTED};">{" · ".join(bits)}</span>')
        label.setObjectName("lgRow")
        label.setTextFormat(Qt.RichText)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.NoTextInteraction)
        label.setCursor(Qt.PointingHandCursor)
        label.setStyleSheet(_ROW_STYLE)
        systems = ", ".join(c.get("systems") or []) or "unknown systems"
        tip = [f"Click when you finish one: adds its reputation and pay.",
               f"{c.get('type') or 'Contract'}{' (type inferred)' if c.get('type_inferred') else ''} · {systems}",
               "Sources: " + ", ".join(c.get("sources") or ["SCMDB"])]
        if req and (req.get("from_title") or req.get("source")):
            tip.append(f"Rank gate {req['rank']}: " + ("from the contract title" if req.get("from_title") else req["source"]))
        for conflict in c.get("conflicts") or []:
            tip.append(f"⚠ {conflict}")
        label.setToolTip("\n".join(tip))
        label.mousePressEvent = lambda event, cc=c: self.log_run(cc)
        return label

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
            mark = "☑" if obj.id in done else "☐"
            color = theme.TEXT_DIM if obj.id in passed else theme.TEXT_PRIMARY
            box_color = theme.ACCENT_CYAN if obj.id in done else theme.TEXT_MUTED
            row = QLabel(f'<span style="color:{box_color};">{mark}</span> '
                         f'<span style="color:{color};">{escape(obj.title)}</span>')
            row.setObjectName("lgRow")
            row.setTextFormat(Qt.RichText)
            row.setWordWrap(True)
            row.setTextInteractionFlags(Qt.NoTextInteraction)
            row.setCursor(Qt.PointingHandCursor)
            row.setToolTip("Click the box to mark done or not done. Click the title to open it.")
            row.setStyleSheet(_ROW_CURRENT_STYLE if is_current else _ROW_STYLE)
            row.mousePressEvent = lambda event, oid=obj.id: self._on_row_clicked(
                oid, event.position().x(), event.button() == Qt.RightButton)
            self.list_layout.addWidget(row)

    # -- contracts view -----------------------------------------------------
    def active_goal(self) -> dict | None:
        gid = self.settings.get("goal")
        return self.progress.goal(gid) if gid else None

    def goal_status(self, goal: dict) -> tuple[int, int | None, str]:
        """(current, target or None if unknown yet, unit)"""
        if goal["kind"] == "rank":
            key = guide_mod.rep_key(goal["faction"], goal["ladder"])
            return int(self.known_rep().get(key) or 0), int(goal["target"]), "rep"
        current = self.progress.goal_money(goal)
        if goal["kind"] == "money":
            return current, int(goal["target"]), "aUEC"
        best = guide_mod.cheapest_listing(self._price_rows or [], goal.get("ship", ""))
        return current, (best["price_buy"] if best else None), "aUEC"

    def _render_contracts(self):
        self._clear(self.goal_rows)
        catalog = self.guide.catalog
        goals = self.progress.goals()
        self.goal_combo.blockSignals(True)
        self.goal_combo.clear()
        self.goal_combo.addItem("No goal: browse contracts", None)
        for g in goals:
            self.goal_combo.addItem(g.get("label") or g["id"], g["id"])
        goal = self.active_goal()
        idx = self.goal_combo.findData(goal["id"] if goal else None)
        self.goal_combo.setCurrentIndex(max(0, idx))
        self.goal_combo.blockSignals(False)
        self.del_goal_btn.setEnabled(goal is not None)
        if catalog is None:
            self.goal_title.setText("No contract data for this version")
            for w in (self.goal_label, self.goal_set_btn, self.goal_bar, self.contracts_caption):
                w.setVisible(False)
            self.contracts_note.setText("This pack has no contracts.json. See scripts/build_contract_catalog.py.")
            return
        known = self.known_rep()
        unlawful = bool(self.settings.get("show_unlawful"))
        cat = self._category()
        flt = self.contract_filter()
        for w in (self.goal_label, self.goal_set_btn, self.goal_bar):
            w.setVisible(goal is not None)
        if goal is None:
            self.goal_title.setText(cat.title if cat else "All repeatable contracts")
            self.goal_title.setVisible(True)
            rows = contracts_mod.for_money(catalog, known, unlawful, cat, self.GOAL_ROWS * 2, flt)
            self.contracts_caption.setText("BEST PAYING · click one when you finish it")
            remaining = 0
            rep_mode = False
        else:
            current, target, unit = self.goal_status(goal)
            self.goal_title.setText(goal.get("label") or "Goal")
            if target is None:
                self.goal_label.setText(f"{current:,} aUEC · ship price: {self._price_error or 'loading from UEX…'}")
                remaining = 0
            else:
                remaining = max(0, target - current)
                done_text = "GOAL REACHED" if remaining == 0 else f"{remaining:,} {unit} to go"
                self.goal_label.setText(f"{current:,} / {target:,} {unit} · {done_text}")
                self.goal_bar.setMaximum(max(1, target))
                self.goal_bar.setValue(min(target, max(0, current)))
            if goal["kind"] == "rank":
                rows = contracts_mod.for_reputation(catalog, goal["faction"], goal["ladder"], known, unlawful,
                                                    None, self.GOAL_ROWS, flt)
                self.contracts_caption.setText("BEST FOR THIS RANK · click one when you finish it")
                rep_mode = True
            else:
                rows = contracts_mod.for_money(catalog, known, unlawful, cat, self.GOAL_ROWS, flt)
                where = f" IN {cat.title.upper()}" if cat else ""
                self.contracts_caption.setText(f"BEST PAYING{where} · click one when you finish it")
                rep_mode = False
        self.contracts_caption.setVisible(True)
        for r in rows:
            self.goal_rows.addWidget(self._contract_row(r, remaining, rep_amount=rep_mode))
        if not rows:
            self.goal_rows.addWidget(_label("No repeatable contracts match. Try another category, "
                                            "or allow outlaw work in ⚙.", _DIM_STYLE))
        self.contracts_note.setText(
            f"Contract data: {catalog.label} ({catalog.version}). Pay and reputation are the game's "
            "base values; \"needs\" is the rank the contract asks for. Unknown ranks show \"?\": set them "
            "in setup or on a rank-up.")

    def _price_text(self, name: str, uex_name: str) -> str:
        if self._price_rows is None:
            return f"PRICE: {escape(name)}: {self._price_error or 'loading from UEX…'}"
        best = guide_mod.cheapest_listing(self._price_rows, uex_name)
        if best is None:
            return f"PRICE: {escape(name)}: not listed on UEX right now"
        return f"PRICE (UEX, live): {best['price_buy']:,} aUEC at {escape(best.get('terminal_name') or 'unknown shop')}"

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def set_view(self, view: str):
        self.settings["view"] = view
        self._save_settings()
        self.render()
        self._maybe_fetch_prices()

    def _on_category_picked(self, index: int):
        self.settings["category"] = self.category_combo.itemData(index) or ""
        self._save_settings()
        self._viewing = None
        self.render()

    def _view(self, oid: str):
        self._viewing = oid
        self.progress.set_current(oid)
        self.render()
        self._maybe_fetch_prices()

    def _advance(self):
        """After finishing or skipping: go to the guide's next objective."""
        self._viewing = None
        nxt = self._next_visible()
        self.progress.set_current(nxt.id if nxt else None)
        self.render()
        self._maybe_fetch_prices()

    def _mark_done(self, oid: str, done: bool = True):
        self.progress.set_done(oid, done)
        obj = self.guide.get(oid)
        rep = obj.reputation if obj else None
        if done and rep and isinstance(rep.get("points"), int):
            self.progress.raise_rep_to(guide_mod.rep_key(rep["faction"], rep.get("ladder", "")), rep["points"])

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
        self._mark_done(obj.id)
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
        self._mark_done(oid, not self.progress.is_done(oid))
        self.render()

    def _on_row_clicked(self, oid: str, x: float, right_button: bool = False):
        if right_button or x <= self.ROW_BOX_WIDTH:
            self._toggle_done(oid)
        else:
            self._view(oid)

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

    def log_run(self, contract: dict):
        self.progress.log_run(contract)
        self.render()

    def _on_undo_run(self):
        if self.progress.undo_last_run() is not None:
            self.render()

    def _on_set_rep(self):
        obj = self.current_objective()
        if obj is None or not obj.reputation:
            return
        rep = obj.reputation
        key = guide_mod.rep_key(rep["faction"], rep.get("ladder", ""))
        current = self.known_rep().get(key) or 0
        value, ok = QInputDialog.getInt(self.card, "Set reputation",
                                        f"{rep['faction']} · {guide_mod.ladder_name(rep.get('ladder', ''))}\n"
                                        "Reputation the game shows now:", int(current), -1_000_000, 10_000_000)
        if ok:
            self.progress.set_rep(key, value)
            self.render()

    def _on_new_goal(self):
        ships = sorted({o.ship["uex_name"] for o in self.guide.objectives if o.ship})
        dialog = GoalDialog(self.card, self.guide.catalog, self.known_rep(), ships)
        if dialog.exec() != QDialog.Accepted:
            return
        self.add_goal(dialog.values())

    def add_goal(self, values: dict) -> dict:
        values = dict(values)
        current_rep = values.pop("current_rep", None)
        goal = self.progress.add_goal(values)
        if goal["kind"] == "rank" and current_rep is not None:
            self.progress.set_rep(guide_mod.rep_key(goal["faction"], goal["ladder"]), int(current_rep))
        self.settings["goal"] = goal["id"]
        self.settings["view"] = "contracts"
        self._save_settings()
        self.render()
        self._maybe_fetch_prices()
        return goal

    def _on_goal_picked(self, index: int):
        self.settings["goal"] = self.goal_combo.itemData(index)
        self._save_settings()
        self.render()
        self._maybe_fetch_prices()

    def _on_delete_goal(self):
        goal = self.active_goal()
        if goal is None:
            return
        if QMessageBox.question(self.card, "Delete goal", f"Delete \"{goal.get('label')}\"?") == QMessageBox.Yes:
            self.progress.remove_goal(goal["id"])
            self.settings["goal"] = None
            self._save_settings()
            self.render()

    def _on_set_goal_value(self):
        goal = self.active_goal()
        if goal is None:
            return
        if goal["kind"] == "rank":
            key = guide_mod.rep_key(goal["faction"], goal["ladder"])
            current = self.known_rep().get(key) or 0
            value, ok = QInputDialog.getInt(self.card, "Set reputation", "Reputation the game shows now:",
                                            int(current), -1_000_000, 10_000_000)
            if ok:
                self.progress.set_rep(key, value)
        else:
            value, ok = QInputDialog.getInt(self.card, "Set wallet", "aUEC in your wallet now:",
                                            int(self.progress.goal_money(goal)), 0, 2_000_000_000)
            if ok:
                self.progress.update_goal(goal["id"], start_uec=value, earned_at_start=self.progress.earned_uec)
        self.render()

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
        versions = menu.addMenu("Game version")
        for pack in sorted(self.packs.values(), key=lambda p: (guide_mod._version_key(p.patch), p.id), reverse=True):
            act = versions.addAction(pack.label)
            act.setCheckable(True)
            act.setChecked(self.guide.pack is not None and pack.id == self.guide.pack.id)
            act.triggered.connect(lambda _=False, pid=pack.id: self.set_pack(pid))
        menu.addSeparator()
        for key, text in (("show_optional", "Show optional objectives"),
                          ("show_unlawful", "Show outlaw (illegal) content"),
                          ("compact", "Compact mode (current step only)")):
            act = menu.addAction(text)
            act.setCheckable(True)
            act.setChecked(bool(self.settings.get(key)))
            act.toggled.connect(lambda on, k=key: self._set_option(k, on))
        menu.addSeparator()
        menu.addAction("Run setup again…").triggered.connect(self.run_setup)
        menu.addAction("How to use mobiGuide").triggered.connect(self.show_how_to)
        menu.addSeparator()
        obj = self.current_objective()
        if obj is not None:
            menu.addAction("Mark this chapter done").triggered.connect(lambda: self.mark_chapter_done(obj.chapter_id))
            menu.addAction("Reset this objective").triggered.connect(lambda: self._reset_objective(obj.id))
            if obj.custom:
                menu.addAction("Delete this objective (yours)").triggered.connect(lambda: self._delete_custom(obj.id))
        menu.addSeparator()
        menu.addAction("Import guide (pack .zip or chapter .json)…").triggered.connect(self._on_import)
        menu.addAction("Export my objectives as a chapter…").triggered.connect(self._on_export_custom)
        if self.guide.pack is not None and self.guide.pack.path is not None:
            menu.addAction(f"Export pack \"{self.guide.pack.label}\" as .zip…").triggered.connect(self._on_export_pack)
        menu.addAction("Reload guide files").triggered.connect(self._reload)
        menu.addAction("Open my guide folder").triggered.connect(self._open_user_folder)
        menu.addSeparator()
        menu.addAction("Reset ALL progress…").triggered.connect(self._reset_all)
        menu.exec(self.menu_btn.mapToGlobal(self.menu_btn.rect().bottomLeft()))

    def set_pack(self, pack_id: str):
        self.settings["pack"] = pack_id
        self._save_settings()
        self.reload_guide()
        self._viewing = None
        self.render()

    def _set_option(self, key: str, on: bool):
        self.settings[key] = bool(on)
        self._save_settings()
        self._viewing = None
        self.render()

    # -- setup and help --------------------------------------------------
    def run_setup(self):
        packs = sorted(self.packs.values(), key=lambda p: (p.channel != "live", [-n for n in guide_mod._version_key(p.patch)]))
        wizard = SetupWizard(self.card, packs, self.settings.get("pack"), guide_mod.ladder_choices(self.guide),
                             self.categories, self.settings)
        if wizard.exec() == QDialog.Accepted:
            self.apply_setup(wizard.values())

    def apply_setup(self, answers: dict) -> int:
        """Apply questionnaire answers; returns how many objectives it ticked."""
        if answers.get("pack") and answers["pack"] != self.settings.get("pack"):
            self.settings["pack"] = answers["pack"]
            self.reload_guide()
        reached = answers.get("reached") or {}
        to_mark = guide_mod.ids_done_for(self.guide, bool(answers.get("knows_basics")), reached)
        marked = 0
        for oid in sorted(to_mark):
            if not self.progress.is_done(oid):
                self._mark_done(oid, True)
                marked += 1
        for key, points in reached.items():
            self.progress.raise_rep_to(key, int(points))
        for key in ("focus", "show_unlawful", "show_optional", "compact"):
            if key in answers:
                self.settings[key] = answers[key]
        self.settings["setup_done"] = True
        self._save_settings()
        self._advance()
        return marked

    def _dismiss_setup(self):
        self.settings["setup_dismissed"] = True
        self._save_settings()
        self.render()

    def show_how_to(self):
        box = QMessageBox(self.card)
        box.setWindowTitle("How to use mobiGuide")
        box.setTextFormat(Qt.RichText)
        box.setText(HOW_TO_HTML)
        box.exec()

    def mark_chapter_done(self, chapter_id: str):
        chapter = self.guide.chapter(chapter_id)
        if chapter is None:
            return
        for obj in chapter.objectives:
            if self._visible(obj) and not self.progress.is_done(obj.id):
                self._mark_done(obj.id, True)
        self._advance()

    def _reset_objective(self, oid: str):
        self.progress.reset(oid)
        self._viewing = oid
        self.render()

    def _reset_all(self):
        answer = QMessageBox.question(self.card, "Reset progress",
                                      "Clear every checkmark, step, counter, logged run, reputation "
                                      "value and goal? This can't be undone.")
        if answer == QMessageBox.Yes:
            self.progress.reset_all()
            self.settings["goal"] = None
            self._viewing = None
            self.render()

    def _reload(self):
        self.reload_guide()
        self.render()

    # -- import / export ---------------------------------------------------
    def import_file(self, path: Path) -> tuple[str, list[str]]:
        """Install a pack .zip or chapter .json. Returns (what happened,
        warnings); raises packio_mod.ImportError_ with a readable reason."""
        path = Path(path)
        user_dir = progress_mod.user_guides_dir()
        if path.suffix.lower() == ".zip":
            dest, warnings = packio_mod.import_pack(path, user_dir / "packs", self._pack_roots)
            self.reload_guide()
            pack = self.packs.get(dest.name)
            msg = f"Installed guide pack \"{pack.label if pack else dest.name}\". Pick it in ⚙ → Game version."
        else:
            dest, warnings = packio_mod.import_chapter(path, user_dir)
            self.reload_guide()
            msg = f"Installed chapter {dest.name}. It loads on top of every game version."
        self.render()
        return msg, warnings

    def _on_import(self):
        path, _ = QFileDialog.getOpenFileName(self.card, "Import a mobiGuide guide", "",
                                              "mobiGuide guides (*.zip *.json)")
        if not path:
            return
        try:
            msg, warnings = self.import_file(Path(path))
        except packio_mod.ImportError_ as exc:
            QMessageBox.warning(self.card, "Import failed", f"Nothing was installed.\n\n{exc}")
            return
        if warnings:
            msg += "\n\nNotes:\n" + "\n".join(warnings[:10])
        QMessageBox.information(self.card, "Guide imported", msg)

    def _on_export_custom(self):
        objectives = self.custom.all()
        if not objectives:
            QMessageBox.information(self.card, "Nothing to export",
                                    "Add objectives with + ADD OBJECTIVE first; those are what gets exported.")
            return
        path, _ = QFileDialog.getSaveFileName(self.card, "Export my objectives", "my-mobiguide-objectives.json",
                                              "Chapter file (*.json)")
        if path:
            patch = self.guide.pack.patch if self.guide.pack else ""
            packio_mod.export_custom_chapter(objectives, Path(path), patch=patch)
            QMessageBox.information(self.card, "Exported", f"Saved {len(objectives)} objectives to {path}.")

    def _on_export_pack(self):
        pack = self.guide.pack
        if pack is None or pack.path is None:
            return
        path, _ = QFileDialog.getSaveFileName(self.card, "Export guide pack", f"mobiguide-{pack.id}.zip",
                                              "Guide pack (*.zip)")
        if path:
            packio_mod.export_pack(pack.path, Path(path))
            QMessageBox.information(self.card, "Exported", f"Saved pack {pack.label} to {path}.")

    def _open_user_folder(self):
        folder = progress_mod.user_guides_dir()
        (folder / "packs").mkdir(parents=True, exist_ok=True)
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
        wanted = False
        if (self.settings.get("view") or "guide") == "guide":
            obj = self.current_objective()
            wanted = obj is not None and bool(obj.ship)
        else:
            goal = self.active_goal()
            wanted = goal is not None and goal.get("kind") == "ship"
        if not wanted:
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
