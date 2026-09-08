"""Regression suite for mobiNotes' NotesStore: CRUD and query methods
against a temp file, isolated from the real mobinotes_data.json.

No test framework dependency — plain asserts, run directly:
    python tests/test_mobi_notes_store.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.mobi_notes.store import NotesStore, STARTER_TAGS


def run() -> int:
    checks = 0

    tmp_path = Path(tempfile.mktemp(suffix=".json"))
    store = NotesStore(tmp_path)

    # -- add / persistence --------------------------------------------------
    n1 = store.add("Trade", "Test Note", "Body text here", ["Trade", "Salvage"], pinned=True)
    n2 = store.add("Fleet", "Other", "Ship stuff", ["Fleet"])
    assert len(store.all_notes()) == 2
    checks += 1

    reloaded = NotesStore(tmp_path)
    assert len(reloaded.all_notes()) == 2, "notes didn't survive a reload from disk"
    checks += 1

    # -- pages / tags ---------------------------------------------------------
    # No built-in default pages — pages() only returns pages that actually
    # have a note on them.
    assert set(store.pages()) == {"Trade", "Fleet"}
    checks += 1
    empty_store = NotesStore(Path(tempfile.mktemp(suffix=".json")))
    assert empty_store.pages() == [], "a fresh store should start with zero pages"
    checks += 1
    assert "Trade" in store.tags() and "Fleet" in store.tags()
    checks += 1
    assert set(STARTER_TAGS) <= set(store.tags())
    checks += 1

    # -- queries --------------------------------------------------------------
    assert [n["title"] for n in store.by_page("Trade")] == ["Test Note"]
    checks += 1
    assert [n["title"] for n in store.by_page("Fleet")] == ["Other"]
    checks += 1
    assert [n["title"] for n in store.by_tag("Salvage")] == ["Test Note"]
    checks += 1
    assert [n["title"] for n in store.search_text("ship")] == ["Other"]
    checks += 1
    assert [n["title"] for n in store.search_text("nonexistent")] == []
    checks += 1
    assert [n["title"] for n in store.pinned()] == ["Test Note"]
    checks += 1

    # search_text scoped to a pre-filtered pool (how the card actually calls it)
    trade_only = store.by_page("Trade")
    assert [n["title"] for n in store.search_text("test", trade_only)] == ["Test Note"]
    checks += 1

    # -- update -----------------------------------------------------------------
    updated = store.update(n1["id"], title="Renamed", pinned=False)
    assert updated["title"] == "Renamed"
    assert store.get(n1["id"])["title"] == "Renamed"
    assert store.get(n1["id"])["pinned"] is False
    checks += 1
    assert store.update("nonexistent-id", title="x") is None
    checks += 1

    # -- delete -----------------------------------------------------------------
    store.delete(n2["id"])
    assert len(store.all_notes()) == 1
    assert store.get(n2["id"]) is None
    checks += 1

    # -- rename_page --------------------------------------------------------
    n3 = store.add("Salvaging", "Home Base", "ARC-L4", ["home"])
    moved = store.rename_page("Salvaging", "General")
    assert moved == 1
    checks += 1
    assert store.by_page("Salvaging") == []
    checks += 1
    assert [n["title"] for n in store.by_page("General")] == ["Home Base"]
    checks += 1
    assert store.get(n3["id"])["page"] == "General"
    checks += 1
    assert store.rename_page("NoSuchPage", "Whatever") == 0
    checks += 1

    tmp_path.unlink(missing_ok=True)
    print(f"{checks}/{checks} mobiNotes store checks passed")
    return checks


if __name__ == "__main__":
    run()
