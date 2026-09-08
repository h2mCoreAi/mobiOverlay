"""mobiNotes: tagged, paged, searchable local notes. No UEX API calls — see
docs/modules/mobi-notes.md for the full design writeup. `refresh()` is a
no-op (there's no remote data to fetch), matching Crosshair's shape.

Copy/paste is a first-class citizen here, not an afterthought: every note's
title/tags/body round-trip through the system clipboard as plain text via
COPY and PASTE AS NEW, on top of QTextEdit/QLineEdit's normal native
select-all/copy/paste behavior.
"""
import importlib.util
import os
import time

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QCompleter, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QMessageBox, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from host import theme
from host.module_base import ModuleBase

# File-path import, not `from .store import ...` — module_loader.py imports
# module.py by file path (spec_from_file_location), not as a real package
# member, so relative imports fail at runtime. Same pattern logistics_hub
# uses for its gamelog_verify.py sibling.
_store_spec = importlib.util.spec_from_file_location(
    "mobioverlay_mobi_notes_store",
    os.path.join(os.path.dirname(__file__), "store.py"),
)
_store_module = importlib.util.module_from_spec(_store_spec)
_store_spec.loader.exec_module(_store_module)
NotesStore = _store_module.NotesStore
STARTER_TAGS = _store_module.STARTER_TAGS

ALL_TAGS = "All Tags"
NEW_PAGE_SENTINEL = "+ New Page..."

_LABEL_SMALL = f'color: {theme.TEXT_MUTED}; font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(9)}px; letter-spacing: 2px;'
_COMBO_STYLE = f"""
    QComboBox {{
        background: {theme.BG_VOID}; color: {theme.TEXT_PRIMARY};
        border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px; padding: 4px 6px;
        font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(10)}px;
    }}
    QComboBox::drop-down {{ width: 18px; border: none; }}
"""
_LINE_STYLE = f"""
    QLineEdit {{
        background: {theme.BG_VOID}; color: {theme.TEXT_PRIMARY};
        border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px; padding: 4px 6px;
        font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(10)}px;
    }}
"""
_TEXT_STYLE = f"""
    QTextEdit {{
        background: {theme.BG_VOID}; color: {theme.TEXT_PRIMARY};
        border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px; padding: 6px;
        font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(10)}px;
    }}
"""
_ROW_STYLE = f"border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px; padding: 6px 8px;"
_ROW_PINNED_STYLE = f"border: 1px solid {theme.ACCENT_CYAN}; border-radius: {theme.RADIUS}px; padding: 6px 8px;"
_TITLE_STYLE = f'font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(11)}px; color: {theme.TEXT_PRIMARY}; font-weight: bold;'
_SUBTEXT_STYLE = f'font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(9)}px; color: {theme.TEXT_MUTED};'
_INFO_STYLE = f'color: {theme.TEXT_DIM}; font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(9)}px;'
_ICON_BTN_STYLE = f"""
    QPushButton {{
        background: transparent; color: {theme.TEXT_MUTED};
        border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px;
    }}
    QPushButton:hover {{ color: {theme.ACCENT_CYAN}; border-color: {theme.ACCENT_CYAN}; }}
"""
_ACTION_BTN_STYLE = f"""
    QPushButton {{
        background: {theme.BG_VOID}; color: {theme.ACCENT_CYAN};
        border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px;
        font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(9)}px; padding: 4px 6px;
    }}
    QPushButton:hover {{ border-color: {theme.ACCENT_CYAN}; }}
"""


def _format_note_for_clipboard(note: dict) -> str:
    lines = [note.get("title") or "(untitled)"]
    if note.get("tags"):
        lines.append("[" + ", ".join(note["tags"]) + "]")
    lines.append("")
    lines.append(note.get("body", ""))
    return "\n".join(lines)


class MobiNotesModule(ModuleBase):
    module_id = "mobi_notes"
    display_name = (
        f'<span style="color:{theme.TEXT_PRIMARY};">mobi</span>'
        f'<span style="color:{theme.ACCENT_CYAN};">Notes</span>'
    )

    def __init__(self, api_client, config):
        super().__init__(api_client, config)
        self.store = NotesStore()
        # No default pages — a fresh install has none at all; the first
        # thing the card does is force creating one (see create_card's
        # empty-state prompt below). current_page stays None until then.
        self.settings.setdefault("current_page", None)
        self._selected_id: str | None = None
        self.request_refresh = None  # injected by host after wrapping refresh()

    # ------------------------------------------------------------------
    # Card construction
    # ------------------------------------------------------------------
    def create_card(self, container):
        card = container.add_card(self.module_id, self.display_name)
        outer_layout = card.body_layout

        # -- empty state: shown instead of everything else until at least
        # one page exists. Creating a page is the first thing this card
        # can be used for — there's no default page to fall back on.
        self._empty_state = QWidget()
        empty_layout = QVBoxLayout(self._empty_state)
        empty_layout.setSpacing(8)
        empty_msg = QLabel("No pages yet. Create one to start taking notes.")
        empty_msg.setWordWrap(True)
        empty_msg.setStyleSheet(_INFO_STYLE)
        empty_layout.addWidget(empty_msg)
        self.create_first_page_btn = QPushButton("+ CREATE FIRST PAGE")
        self.create_first_page_btn.setStyleSheet(_ACTION_BTN_STYLE)
        self.create_first_page_btn.clicked.connect(self._prompt_new_page)
        empty_layout.addWidget(self.create_first_page_btn)
        outer_layout.addWidget(self._empty_state)

        # -- main content: everything below is hidden until a page exists.
        self._content_widget = QWidget()
        layout = QVBoxLayout(self._content_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        outer_layout.addWidget(self._content_widget)

        # -- page + search/filter row -----------------------------------
        top_row = QHBoxLayout()
        top_row.setSpacing(6)
        self.page_combo = QComboBox()
        self.page_combo.setStyleSheet(_COMBO_STYLE)
        top_row.addWidget(self.page_combo, stretch=1)
        self.rename_page_btn = QPushButton("✎")
        self.rename_page_btn.setFixedSize(24, 24)
        self.rename_page_btn.setToolTip("Rename this page")
        self.rename_page_btn.setStyleSheet(_ICON_BTN_STYLE)
        top_row.addWidget(self.rename_page_btn)
        self.delete_page_btn = QPushButton("✕")
        self.delete_page_btn.setFixedSize(24, 24)
        self.delete_page_btn.setToolTip("Delete this page and its notes")
        self.delete_page_btn.setStyleSheet(_ICON_BTN_STYLE)
        top_row.addWidget(self.delete_page_btn)
        self.tag_combo = QComboBox()
        self.tag_combo.setStyleSheet(_COMBO_STYLE)
        top_row.addWidget(self.tag_combo, stretch=1)
        layout.addLayout(top_row)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search title / body / tags...")
        self.search_box.setStyleSheet(_LINE_STYLE)
        layout.addWidget(self.search_box)

        list_label = QLabel("NOTES")
        list_label.setStyleSheet(_LABEL_SMALL)
        layout.addWidget(list_label)
        self._list_layout = QVBoxLayout()
        self._list_layout.setSpacing(6)
        layout.addLayout(self._list_layout)

        # -- editor ---------------------------------------------------------
        editor_label = QLabel("EDITOR")
        editor_label.setStyleSheet(_LABEL_SMALL)
        layout.addWidget(editor_label)

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Title")
        self.title_edit.setStyleSheet(_LINE_STYLE)
        layout.addWidget(self.title_edit)

        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText("Tags, comma separated")
        self.tags_edit.setStyleSheet(_LINE_STYLE)
        completer = QCompleter(STARTER_TAGS)
        self.tags_edit.setCompleter(completer)
        layout.addWidget(self.tags_edit)

        self.body_edit = QTextEdit()
        self.body_edit.setPlaceholderText("Body — Ctrl+A/Ctrl+C/Ctrl+V all work natively")
        self.body_edit.setStyleSheet(_TEXT_STYLE)
        self.body_edit.setMinimumHeight(90)
        layout.addWidget(self.body_edit)

        editor_footer = QHBoxLayout()
        self.pinned_check = QCheckBox("Pinned")
        self.pinned_check.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-family: \"{theme.FONT_MONO}\"; font-size: {theme.fpx(9)}px;")
        editor_footer.addWidget(self.pinned_check)
        editor_footer.addStretch()
        layout.addLayout(editor_footer)

        btn_row1 = QHBoxLayout()
        btn_row1.setSpacing(4)
        self.new_btn = QPushButton("NEW")
        self.save_btn = QPushButton("SAVE")
        self.delete_btn = QPushButton("DELETE")
        for b in (self.new_btn, self.save_btn, self.delete_btn):
            b.setStyleSheet(_ACTION_BTN_STYLE)
            btn_row1.addWidget(b)
        layout.addLayout(btn_row1)

        btn_row2 = QHBoxLayout()
        btn_row2.setSpacing(4)
        self.copy_btn = QPushButton("COPY NOTE")
        self.paste_new_btn = QPushButton("PASTE AS NEW")
        for b in (self.copy_btn, self.paste_new_btn):
            b.setStyleSheet(_ACTION_BTN_STYLE)
            btn_row2.addWidget(b)
        layout.addLayout(btn_row2)

        # -- wiring -----------------------------------------------------
        self.page_combo.currentTextChanged.connect(self._on_page_changed)
        self.rename_page_btn.clicked.connect(self._on_rename_page)
        self.delete_page_btn.clicked.connect(self._on_delete_page)
        self.tag_combo.currentTextChanged.connect(self._render_list)
        self.search_box.textChanged.connect(self._render_list)
        self.new_btn.clicked.connect(self._on_new)
        self.save_btn.clicked.connect(self._on_save)
        self.delete_btn.clicked.connect(self._on_delete)
        self.copy_btn.clicked.connect(self._on_copy_current)
        self.paste_new_btn.clicked.connect(self._on_paste_as_new)

        self.card = card
        self._populate_pickers()
        self._render_list()
        self._clear_editor()
        self._update_empty_state()
        return card

    def _update_empty_state(self):
        has_pages = bool(set(self.store.pages()) | set(self.settings.get("custom_pages", [])))
        self._empty_state.setVisible(not has_pages)
        self._content_widget.setVisible(has_pages)

    # ------------------------------------------------------------------
    # ModuleBase contract — no remote data, nothing to fetch
    # ------------------------------------------------------------------
    def refresh(self):
        pass

    # ------------------------------------------------------------------
    # Pickers
    # ------------------------------------------------------------------
    def _populate_pickers(self):
        # store.pages() only returns pages that already have a note on them
        # — a page just created via + New Page has none yet, so it would
        # otherwise vanish from the list the instant it's created, before
        # its first note is ever saved. custom_pages (persisted per-module
        # settings) keeps it visible in the meantime. There are no built-in
        # default pages — an empty list here means the empty-state prompt
        # (see _update_empty_state) is showing instead of this UI at all.
        pages = sorted(set(self.store.pages()) | set(self.settings.get("custom_pages", [])))
        current = self.settings.get("current_page")
        if current not in pages:
            current = pages[0] if pages else None

        self.page_combo.blockSignals(True)
        self.page_combo.clear()
        self.page_combo.addItems(pages)
        self.page_combo.addItem(NEW_PAGE_SENTINEL)
        if current:
            self.page_combo.setCurrentText(current)
        self.page_combo.blockSignals(False)

        self.settings["current_page"] = current

        self.tag_combo.blockSignals(True)
        self.tag_combo.clear()
        self.tag_combo.addItem(ALL_TAGS)
        self.tag_combo.addItems(self.store.tags())
        self.tag_combo.blockSignals(False)

        completer = QCompleter(self.store.tags())
        self.tags_edit.setCompleter(completer)

    def _on_page_changed(self, page: str):
        if page == NEW_PAGE_SENTINEL:
            self._prompt_new_page()
            return
        self.settings["current_page"] = page
        self.config.set_module_settings(self.module_id, self.settings)
        self._render_list()

    def _prompt_new_page(self):
        name, ok = QInputDialog.getText(self.card, "New Page", "Page name:")
        name = name.strip()
        if not ok or not name:
            # Revert the combo back to whatever real page was selected
            # before (if any — there may be none yet).
            previous = self.settings.get("current_page")
            if previous:
                self.page_combo.setCurrentText(previous)
            return
        custom_pages = self.settings.setdefault("custom_pages", [])
        if name not in custom_pages:
            custom_pages.append(name)
        self.settings["current_page"] = name
        self.config.set_module_settings(self.module_id, self.settings)
        self._populate_pickers()
        self.page_combo.setCurrentText(name)
        self._update_empty_state()
        self._render_list()

    def _on_rename_page(self):
        old_name = self.settings.get("current_page")
        if not old_name:
            return
        new_name, ok = QInputDialog.getText(self.card, "Rename Page", "New name:", text=old_name)
        new_name = new_name.strip()
        if not ok or not new_name or new_name == old_name:
            return

        self.store.rename_page(old_name, new_name)

        custom_pages = self.settings.setdefault("custom_pages", [])
        if old_name in custom_pages:
            custom_pages.remove(old_name)
        if new_name not in custom_pages:
            custom_pages.append(new_name)

        self.settings["current_page"] = new_name
        self.config.set_module_settings(self.module_id, self.settings)
        self._populate_pickers()
        self.page_combo.setCurrentText(new_name)
        self._clear_editor()
        self._render_list()

    def _on_delete_page(self):
        page = self.settings.get("current_page")
        if not page:
            return
        notes_on_page = self.store.by_page(page)

        message = f"Delete page \"{page}\""
        if notes_on_page:
            message += f" and its {len(notes_on_page)} note(s)"
        message += "? This can't be undone."
        confirm = QMessageBox.question(self.card, "Delete Page", message)
        if confirm != QMessageBox.Yes:
            return

        for note in notes_on_page:
            self.store.delete(note["id"])

        custom_pages = self.settings.setdefault("custom_pages", [])
        if page in custom_pages:
            custom_pages.remove(page)

        self._populate_pickers()
        remaining_pages = sorted(set(self.store.pages()) | set(self.settings.get("custom_pages", [])))
        remaining = remaining_pages[0] if remaining_pages else None
        self.settings["current_page"] = remaining
        self.config.set_module_settings(self.module_id, self.settings)
        if remaining:
            self.page_combo.setCurrentText(remaining)
        self._clear_editor()
        self._update_empty_state()
        self._render_list()

    # ------------------------------------------------------------------
    # List rendering
    # ------------------------------------------------------------------
    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _current_notes(self) -> list[dict]:
        page = self.settings.get("current_page")
        if not page:
            return []
        notes = self.store.by_page(page)
        tag = self.tag_combo.currentText() if hasattr(self, "tag_combo") else ALL_TAGS
        if tag and tag != ALL_TAGS:
            notes = [n for n in notes if tag in n.get("tags", [])]
        query = self.search_box.text() if hasattr(self, "search_box") else ""
        notes = self.store.search_text(query, notes)
        pinned = [n for n in notes if n.get("pinned")]
        rest = [n for n in notes if not n.get("pinned")]
        pinned.sort(key=lambda n: n.get("modified", 0), reverse=True)
        rest.sort(key=lambda n: n.get("modified", 0), reverse=True)
        return pinned + rest

    def _render_list(self):
        self._clear_layout(self._list_layout)
        notes = self._current_notes()
        if not notes:
            self._list_layout.addWidget(self._info_label("No notes on this page yet."))
            return
        for note in notes:
            self._list_layout.addWidget(self._note_row(note))

    def _note_row(self, note: dict) -> QWidget:
        box = QWidget()
        box.setStyleSheet(_ROW_PINNED_STYLE if note.get("pinned") else _ROW_STYLE)
        outer = QHBoxLayout(box)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        title_text = ("📌 " if note.get("pinned") else "") + (note.get("title") or "(untitled)")
        title = QLabel(title_text)
        title.setStyleSheet(_TITLE_STYLE)
        title.setWordWrap(True)
        text_col.addWidget(title)
        sub_text = ", ".join(note.get("tags", [])) or "no tags"
        sub = QLabel(sub_text)
        sub.setStyleSheet(_SUBTEXT_STYLE)
        text_col.addWidget(sub)
        outer.addLayout(text_col, stretch=1)

        copy_btn = QPushButton("⧉")
        copy_btn.setFixedSize(22, 22)
        copy_btn.setToolTip("Copy this note to clipboard")
        copy_btn.setStyleSheet(_ICON_BTN_STYLE)
        copy_btn.clicked.connect(lambda: self._copy_note(note))
        outer.addWidget(copy_btn)

        # Clicking the row (not the copy button) loads it into the editor.
        box.mousePressEvent = lambda event, n=note: self._load_into_editor(n)
        return box

    def _info_label(self, text: str) -> QWidget:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet(_INFO_STYLE)
        return label

    # ------------------------------------------------------------------
    # Editor actions
    # ------------------------------------------------------------------
    def _clear_editor(self):
        self._selected_id = None
        self.title_edit.clear()
        self.tags_edit.clear()
        self.body_edit.clear()
        self.pinned_check.setChecked(False)

    def _load_into_editor(self, note: dict):
        self._selected_id = note["id"]
        self.title_edit.setText(note.get("title", ""))
        self.tags_edit.setText(", ".join(note.get("tags", [])))
        self.body_edit.setPlainText(note.get("body", ""))
        self.pinned_check.setChecked(bool(note.get("pinned")))

    def _on_new(self):
        self._clear_editor()
        self.title_edit.setFocus()

    def _parse_tags(self) -> list[str]:
        raw = self.tags_edit.text()
        return [t.strip() for t in raw.split(",") if t.strip()]

    def _on_save(self):
        page = self.settings.get("current_page")
        if not page:
            return
        title = self.title_edit.text().strip()
        body = self.body_edit.toPlainText()
        tags = self._parse_tags()
        pinned = self.pinned_check.isChecked()
        if not title and not body:
            return
        if self._selected_id:
            self.store.update(self._selected_id, title=title, body=body, tags=tags, pinned=pinned)
        else:
            note = self.store.add(page, title, body, tags, pinned)
            self._selected_id = note["id"]
        self._populate_pickers()
        self._render_list()

    def _on_delete(self):
        if not self._selected_id:
            return
        confirm = QMessageBox.question(
            self.card, "Delete Note", "Delete this note? This can't be undone.",
        )
        if confirm != QMessageBox.Yes:
            return
        self.store.delete(self._selected_id)
        self._clear_editor()
        self._render_list()

    # ------------------------------------------------------------------
    # Copy / paste
    # ------------------------------------------------------------------
    def _copy_note(self, note: dict):
        QGuiApplication.clipboard().setText(_format_note_for_clipboard(note))

    def _on_copy_current(self):
        note = {
            "title": self.title_edit.text(),
            "tags": self._parse_tags(),
            "body": self.body_edit.toPlainText(),
        }
        self._copy_note(note)

    def _on_paste_as_new(self):
        page = self.settings.get("current_page")
        if not page:
            return
        text = QGuiApplication.clipboard().text()
        if not text:
            return
        lines = text.splitlines()
        first = lines[0].strip() if lines else ""
        title = (first[:60] + "...") if len(first) > 60 else first
        body = text
        note = self.store.add(page, title or f"Pasted {time.strftime('%H:%M:%S')}", body, [], False)
        self._render_list()
        self._load_into_editor(note)


MODULE_CLASS = MobiNotesModule
