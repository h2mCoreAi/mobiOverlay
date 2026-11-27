# mobiOverlay

**Read `AGENTS.md` first.** It is the canonical onboarding file for every AI
agent: what mobiOverlay is and who it's for, the data charter, repo layout,
safety rules, multi-agent rules and conventions. Then read `docs/PROGRESS.md`
(one-page status, open work, branch plan). This file is only a pointer and a
safety summary; if it ever disagrees with `AGENTS.md`, `AGENTS.md` wins.

In one line: a fast, safe, read-only Star Citizen companion HUD (PySide6,
always-on-top, MobiGlas-styled) showing UEX trade data and a verified
leveling guide, for any player.

## Quick commands

```bash
python host/main.py                         # run from source
python tests/run_all.py                     # all tests, offscreen
python scripts/decisions_index.py <keyword> # search docs/DECISIONS.md
pyinstaller mobioverlay.spec --noconfirm    # build (onedir)
```

## Safety rules (summary; full text in AGENTS.md)

1. **Never force-kill SC processes**; only kill mobiOverlay
2. **Never leave the overlay running unattended** alongside SC
3. **Never send hotkey keystrokes** while SC may be live
4. **Never move the overlay onto the owner's primary/gaming monitor while
   testing** (an agent-testing rule, not a product rule)
5. **Never embed UEX tokens** in distributed code
6. **Never invent game/API logic** UEX or the game doesn't provide (one
   exception: Logistics Hub's route ordering over real UEX distances)
7. **Never run two mobiOverlay instances** at once
8. **Never push to `master`** without the owner's explicit OK in the
   current session; work on an `<agent>/<topic>` branch
