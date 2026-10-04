# mobiOverlay

Modular, always-on-top Star Citizen data overlay. Dark sci-fi HUD styled after
MobiGlas. Data comes from the UEX Corp API (community-sourced SC trade/economy
data) — no game memory reads, no log parsing by default (see docs/DECISIONS.md
for why), except one opt-in exception: Logistics Hub can optionally cross-check
scanned contracts against the player's own `Game.log` for post-accept
verification (user-configured path, never a trigger or data source on its own
— see AGENTS.md).

**See `AGENTS.md` for full AI agent onboarding** — safety rules, coding
conventions, testing, and common tasks. This file is a quick reference.

---

## Locked architecture decisions

- UI: PySide6/Qt (chosen for reliable one-file PyInstaller packaging)
- Modules: folder-per-module under `modules/`, auto-discovered at startup
- Cards: draggable/collapsible/closable, layout persisted to `config.json`
- mobiOverlay Core (`host/`) never imports module internals — only calls the contract

---

## Docs to read

| When | Read |
|------|------|
| First | `AGENTS.md` — full onboarding, safety rules |
| Every session | `docs/PROGRESS.md` — one-page status |
| For old session notes | `docs/HISTORY.md` — archive, not the status |
| For architecture | `docs/ARCHITECTURE.md` — contracts, services |
| For a specific module | `docs/modules/<name>.md` |
| For past decisions | `docs/DECISIONS.md` — append-only log |
| For what's next | `docs/BACKLOG.md` — ranked module candidates |

---

## Quick commands

```bash
# Run from source
python host/main.py

# Run tests (each file is standalone, plain asserts)
python tests/test_logistics_hub_parsing.py
python tests/test_api_client_dedupe.py
python tests/test_core_persistence.py
python tests/test_pill_hover_unlock.py
python tests/test_mobi_notes_store.py
python tests/test_logistics_hub_routing.py
python tests/test_background_scans.py
python tests/test_price_cache.py
python tests/test_commodity_prices_cache.py

# Build exe
pyinstaller mobioverlay.spec --noconfirm
```

---

## Safety rules (summary — see AGENTS.md for full list)

1. **Never force-kill SC processes** — only kill mobiOverlay
2. **Never leave overlay running unattended** alongside SC
3. **Never send hotkey keystrokes** while SC may be live
4. **Never move overlay** onto the primary/gaming monitor
5. **Never embed UEX tokens** in distributed code
6. **Never invent API logic** UEX doesn't compute (one documented exception:
   Logistics Hub's 2-opt route ordering over real UEX distances — see AGENTS.md)
7. **Never run two mobiOverlay instances** at once
8. **Never push directly to `master`** without asking the owner first
   (work on a PR branch by default — see AGENTS.md)
