# mobiOverlay

Modular, always-on-top Star Citizen data overlay. Dark sci-fi HUD styled after
MobiGlas. Data comes from the UEX Corp API (community-sourced SC trade/economy
data) — no game memory reads, no log parsing (see docs/DECISIONS.md for why).

**Locked architecture decisions:**
- UI: PySide6/Qt (chosen for reliable one-file PyInstaller packaging)
- Modules: folder-per-module under `modules/`, auto-discovered at startup by mobiOverlay Core (the `host/` package)
- Cards: draggable/collapsible/closable, layout persisted to local JSON config
- mobiOverlay Core never imports module internals directly — only calls the module contract

**Docs, read only what's relevant to the task:**
- `docs/ARCHITECTURE.md` — module contract, mobiOverlay Core responsibilities, config schema
- `docs/modules/<name>.md` — scope for one specific module (only exists once that module is started)
- `docs/PROGRESS.md` — current status, what's done, what's next
- `docs/DECISIONS.md` — dated log of choices + rationale, append-only
- `docs/BACKLOG.md` — full ranked module backlog with community-interest evidence

Start any session by reading PROGRESS.md first to orient, then only the
ARCHITECTURE.md and module doc relevant to the task at hand.
