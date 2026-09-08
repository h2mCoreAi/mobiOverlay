"""NotesStore: owns all read/write/query logic for mobiNotes' local JSON
file. Nothing else touches the file directly — the card renders whatever a
query method returns. See docs/modules/mobi-notes.md for the data model.

Storage lives at app_root()/mobinotes_data.json — external to the module
folder, same reasoning as config.json (host/paths.py): a PyInstaller
onefile build's temp extraction dir doesn't persist between launches, so
this has to live next to the exe/project root, not inside modules/.
"""
import json
import time
import uuid
from pathlib import Path

from host.paths import app_root

SCHEMA_VERSION = 1
STARTER_TAGS = ["Trade", "Combat", "Mining", "Salvage", "Org", "Fleet", "Bug/Reminder"]


def data_path() -> Path:
    return app_root() / "mobinotes_data.json"


class NotesStore:
    def __init__(self, path: Path | None = None):
        self.path = path or data_path()
        self._notes: list[dict] = []
        self.load()

    # -- persistence ------------------------------------------------------
    def load(self):
        if not self.path.exists():
            self._notes = []
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            self._notes = []
            return
        self._notes = raw.get("notes", [])

    def save(self):
        payload = {"schema_version": SCHEMA_VERSION, "notes": self._notes}
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # -- mutation -----------------------------------------------------------
    def add(self, page: str, title: str, body: str, tags: list[str], pinned: bool = False) -> dict:
        now = time.time()
        note = {
            "id": str(uuid.uuid4()),
            "page": page,
            "title": title,
            "body": body,
            "tags": tags,
            "pinned": pinned,
            "created": now,
            "modified": now,
            "meta": {},
        }
        self._notes.append(note)
        self.save()
        return note

    def update(self, note_id: str, **fields) -> dict | None:
        note = self.get(note_id)
        if note is None:
            return None
        note.update(fields)
        note["modified"] = time.time()
        self.save()
        return note

    def delete(self, note_id: str):
        self._notes = [n for n in self._notes if n["id"] != note_id]
        self.save()

    def rename_page(self, old_name: str, new_name: str) -> int:
        """Moves every note on `old_name` onto `new_name`. Returns the
        count of notes moved. Does not touch any module settings
        (current_page/custom_pages) — the caller (module.py) owns that,
        since it's UI-facing state this store doesn't know about."""
        moved = 0
        now = time.time()
        for note in self._notes:
            if note.get("page") == old_name:
                note["page"] = new_name
                note["modified"] = now
                moved += 1
        if moved:
            self.save()
        return moved

    # -- queries ------------------------------------------------------------
    def get(self, note_id: str) -> dict | None:
        return next((n for n in self._notes if n["id"] == note_id), None)

    def all_notes(self) -> list[dict]:
        return list(self._notes)

    def by_page(self, page: str) -> list[dict]:
        return [n for n in self._notes if n.get("page") == page]

    def by_tag(self, tag: str) -> list[dict]:
        return [n for n in self._notes if tag in n.get("tags", [])]

    def search_text(self, query: str, notes: list[dict] | None = None) -> list[dict]:
        pool = self._notes if notes is None else notes
        if not query:
            return list(pool)
        q = query.lower()
        return [
            n for n in pool
            if q in n.get("title", "").lower()
            or q in n.get("body", "").lower()
            or any(q in t.lower() for t in n.get("tags", []))
        ]

    def pinned(self, notes: list[dict] | None = None) -> list[dict]:
        pool = self._notes if notes is None else notes
        return [n for n in pool if n.get("pinned")]

    def pages(self) -> list[str]:
        """Pages actually in use — there are no built-in defaults. A page
        only exists because a note is on it, or module.py's own
        custom_pages tracking is holding a spot for a just-created, still-
        empty one (see module.py's _populate_pickers)."""
        return sorted({n.get("page") for n in self._notes if n.get("page")})

    def tags(self) -> list[str]:
        used = {t for n in self._notes for t in n.get("tags", [])}
        return sorted(set(STARTER_TAGS) | used)
