# Module: mobiNotes

Status: built and live-verified (2026-09-08). See DECISIONS.md for the
build writeup and what copy/paste specifically covers.

Not from the UEX-backed backlog — a standalone request. No API calls at
all; purely local data, same shape as the Crosshair module in that
respect. Originated from a shelved "salvage module" conversation (see
DECISIONS.md, 2026-09-08) — UEX has no salvage-relevant endpoints, so
attention moved to a lightweight organizational tool instead.

## Why not just borrow an existing open-source notes app

Researched ReText (Python/PyQt6), QOwnNotes (C++/Qt), and Zim Desktop
Wiki (Python/GTK) as candidate sources to lift code from. All three are
GPL-licensed (copyleft) — decided against pulling their code in to avoid
GPL obligations on this module. Borrowing **ideas only**, not code:
QOwnNotes' tagging/full-text-search feature set and Zim's page-based
organization model informed the design below, written fresh.

## Scope (v1)

Deliberately lightweight — no markdown rendering, no code/syntax preview,
no wiki-style backlinks/graph (that's the part of Zim/QOwnNotes explicitly
not being copied). Just organized plain-text notes.

- **Pages** — a note belongs to one page (a string field, not a separate
  file/table). Adding a new page is just a new string value, no schema
  change. **There are no built-in default pages** (changed 2026-09-08,
  see DECISIONS.md) — a fresh install starts with zero pages, and the
  card's entire main UI (list/editor/search) stays hidden behind a
  "create your first page" prompt until one exists. Pages can be
  renamed (moves every note on it) or deleted (with a confirm, taking
  its notes with it).
- **Tags** — free-form, cut across pages. A small starter tag set
  (Trade, Combat, Mining, Salvage, Org, Fleet, Bug/Reminder) ships as
  suggestions, not a fixed enum.
- **Search** — free-text filter across title/body/tags, plus tag-based
  filtering. No indexing needed at this scale (local JSON, not expected
  to grow past a few hundred notes).
- **Pinning** — a note can be pinned to always show at the top of the
  card, ahead of search/tag filtering.

## Data model — built for incremental extension, not a rewrite

```json
{
  "schema_version": 1,
  "notes": [
    {
      "id": "uuid",
      "page": "Trade",
      "title": "string",
      "body": "string",
      "tags": ["Trade", "Salvage"],
      "pinned": false,
      "created": 0,
      "modified": 0,
      "meta": {}
    }
  ]
}
```

- `meta: {}` is the deliberate escape hatch — location tag, a
  cross-module reference (e.g. link to a specific Trade Route Optimizer
  route or Refinery Finder terminal), or any future per-note field lands
  here without touching the schema or breaking notes written before that
  field existed.
- `schema_version` at the root — cheap insurance for a future format
  migration instead of a breaking change.
- Pages are a field, not a structural split, so page management (add,
  rename, delete) never touches storage format.

## Storage layer — isolated from UI

A `NotesStore` class (`modules/mobi_notes/store.py`) owns all
read/write/query logic — load/save the JSON file, and query methods
(`by_page`, `by_tag`, `search_text`, `pinned`). Nothing else touches the
file directly. The card renders whatever a `NotesStore` query returns;
adding a new query type later (by date, by location, by linked module)
extends the store, not the UI.

This mirrors the existing module contract (`module_id`, `create_card`,
`refresh`) — store/query/UI stay cleanly separated so tag suggestions,
location tagging (via the shared `LocationService`), pinning, or
cross-module links can be added incrementally later without a rewrite.

## Explicitly out of scope for v1

- Markdown rendering or any rich text
- Code/syntax preview
- Wiki-style backlinks or a note graph
- Cross-module quick-links (`meta` field reserves space for this later,
  not built now)
- Location tagging via `LocationService` (same — reserved in `meta`,
  not built now)

## Resolved during build (2026-09-08)

- **Page switcher is a QComboBox, not tabs.** A horizontal tab strip risked
  overflow/wrapping as pages accumulate on a narrow card; a dropdown (plus
  a `+ New Page...` sentinel item that prompts for a name) scales to any
  number of pages with no layout work. Revisit as real tabs later if a
  user strongly prefers clicking over selecting.
- **`refresh()` is a no-op**, confirmed — matches Crosshair's shape exactly,
  there's no remote data to fetch.
- **Copy/paste, the feature this module was specifically asked to make
  easy** (not in the original scoping doc — added per direct user
  request):
  - The body field is a real `QTextEdit`, title/tags are `QLineEdit` —
    native Ctrl+A/Ctrl+C/Ctrl+V/Ctrl+X all work with zero extra code,
    unlike a custom-painted text widget would need.
  - **COPY NOTE** button formats the open note (title, `[tags]`, blank
    line, body) as plain text onto the real system clipboard via
    `QGuiApplication.clipboard()` — verified live pasting into an
    external app isn't needed to prove this; reading the clipboard back
    via `System.Windows.Forms.Clipboard` from a separate PowerShell
    process after a real UI Automation click confirmed the exact
    expected text landed there.
  - Each note row in the list also gets its own small ⧉ icon button —
    copies that note without first opening it in the editor.
  - **PASTE AS NEW** reads the clipboard, uses its first line (capped at
    60 chars) as the title and the full clipboard text as the body,
    creates the note on the current page. Meant for the common case of
    copying a chunk of Discord/Spectrum/chat text straight into a note.
    Verified live: set real clipboard content from PowerShell, clicked
    the button via UI Automation, confirmed the resulting note in
    `mobinotes_data.json` matched exactly.

## Verification (2026-09-08)

Live-tested against the real running app, not just unit-style checks:
`NotesStore` CRUD/query methods exercised directly (add/update/delete,
`by_page`/`search_text`/`pinned`/`pages`/`tags`) with correct results;
full app launch with all 6 modules discovered with no contract/duplicate-
id errors; a real note entered and saved via UI Automation (typed into
the actual `QLineEdit`/`QTextEdit` controls, clicked the real SAVE
button) round-tripped correctly to `mobinotes_data.json` on disk,
including a multi-line body and comma-parsed tags; COPY NOTE and PASTE
AS NEW both confirmed against the real system clipboard, not a stub.
Screenshotted (via `PrintWindow`, this project's standard technique) at
each step. One real bug caught during this: module.py's original
`from .store import ...` failed at runtime because `module_loader.py`
imports each module by file path, not as a real package member — no
relative imports work there. Fixed with the same file-path-import
pattern `logistics_hub/module.py` already uses for its
`gamelog_verify.py` sibling.

## Page management (added 2026-09-08, after initial build)

Real usage surfaced three gaps within the same session, all fixed:

- **Bug: a newly-created empty page vanished immediately.** `store.pages()`
  only returns pages with at least one note on them, but a page just
  created via `+ New Page...` has none yet — the picker rebuild silently
  dropped it and reverted to another page before its first note was ever
  saved. Fixed with a `custom_pages` list in the module's own persisted
  settings, unioned with `store.pages()` everywhere the picker is built —
  a page now stays visible from the moment it's created.
- **Feature: rename a page.** `NotesStore.rename_page(old, new)` moves
  every note on `old` onto `new` in one bulk update (new `modified`
  timestamp on each). The card's ✎ button next to the page dropdown
  prompts for the new name and updates `custom_pages` to match.
- **Feature: delete a page.** The card's ✕ button next to the page
  dropdown confirms (naming how many notes will go with it), deletes
  every note on that page, and removes it from `custom_pages`.
- **Decision: removed the 5 built-in default pages entirely** (Trade/
  Fleet/Org/Builds/Missions — leftover from the original scoping doc's
  example list). User feedback: those defaults being "always there"
  regardless of use felt backwards — creating your first page should be
  the first thing the module makes you do, not an optional extra on top
  of pages you never asked for. `store.pages()` now returns only pages
  that genuinely have notes; the card shows an empty-state prompt
  ("No pages yet. Create one to start taking notes." + a
  **+ CREATE FIRST PAGE** button) instead of the normal list/editor UI
  until at least one page exists (via `custom_pages` or a real note).
  Deleting the last remaining page returns to that same empty state.

## Open questions / not yet decided

- Whether the page switcher should become a real tab strip instead of a
  dropdown once there's real usage to judge against.
- Location tagging via `LocationService` and cross-module links — both
  still reserved in `meta`, not built.
