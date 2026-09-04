# Module: Crosshair

Status: built and working, host-verified via UI Automation + screenshot.
Not from the UEX-backed backlog — a standalone request, since Star
Citizen's own crosshair reticle has a habit of disappearing mid-session.

## Scope

Draws a small fixed reticle dead-center on the primary display, with a
card in the normal card system to show/hide it and nudge its position in
1px increments (for fine calibration, not dragging).

- The reticle (`_CrosshairOverlay` in `modules/crosshair/module.py`) is
  **not** rendered inside the card — it's its own separate top-level
  widget, frameless/always-on-top/click-through
  (`Qt.WA_TransparentForMouseEvents`, critical — it must never intercept
  a mouse click meant for aiming), positioned at the primary screen's
  center plus a persisted `(offset_x, offset_y)`. The card only holds
  controls: Show/Hide toggle, ▲▼◀▶ nudge buttons (1px per click), Reset
  to Center, and a live `OFFSET  X ±n  Y ±n` readout.
- No UEX API calls at all — `refresh()` is a no-op, purely local visual
  state persisted to `config.json` under `modules.crosshair`
  (`offset_x`, `offset_y`; `visible` under the module's own settings via
  `_apply_state()`).
- Uses `QGuiApplication.primaryScreen()` for centering — on this dev
  machine that's deliberately the *opposite* choice from
  `_default_launch_position()` (which picks a non-primary screen for the
  main overlay window itself, see `feedback_gui_testing_dont_touch_gaming_monitor`
  in memory) — the primary display is the gaming monitor here, which is
  exactly where a crosshair needs to be centered.

## Verified

- Card loads and renders without error (2026-09-04)
- Reticle overlay positions itself exactly on the primary screen's true
  center — confirmed by comparing the overlay window's own rect center
  against `System.Windows.Forms.Screen` primary-monitor bounds via
  PowerShell, both measured the same way, both landing on the same point
- Reticle screenshot-confirmed rendering correctly (cyan "+" with a
  center gap, not a solid cross covering the aim point)
- Nudge buttons confirmed to update `offset_x`/`offset_y` in
  `config.json` and move the overlay — rapid back-to-back UI Automation
  `Invoke()` calls with no delay between them only registered one click
  (known automation-timing flakiness, not an app bug — confirmed by
  redoing the same clicks with a small delay between each, which
  registered all of them correctly)

## Not yet verified

- Click-through behavior (`WA_TransparentForMouseEvents`) against a real
  mouse click while the game is running underneath it — this session's
  established caution around not risking stray clicks into the live game
  meant this wasn't tested with an actual click, only reasoned about from
  documented Qt behavior for top-level windows
- Whether it stays on top of Star Citizen specifically the same way the
  main overlay window does (same window-flag pattern, so expected to
  work, but not independently confirmed with the game running)
