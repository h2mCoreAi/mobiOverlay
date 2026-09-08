# mobiThrottle

Ports ThrottleWatch (a separate, already-shipping standalone SC overlay —
`D:\Documents\Mitch\Star Citizen\ThrottleWatch\throttle_watch.py`, Tkinter)
into mobiOverlay as a native module. Not a copy/paste port — rewritten
against mobiOverlay's actual stack (PySide6, `host/` services, config.json
module namespace) since several of ThrottleWatch's mechanisms exist only to
work around limitations Qt doesn't have.

**Built, live-verified, and user-confirmed working 2026-09-08** with a
real throttle — see docs/DECISIONS.md (2026-09-08 entries) for the full
build/verification writeup and the follow-up usability fix, and
docs/PROGRESS.md for the summary. `modules/mobi_throttle/module.py`.
Everything below was the architecture written *before* any code existed;
it held up unchanged through implementation except where a note below
says otherwise.

**Follow-up fix (same day, from real use):** the Axis/Hold-time/Home Chirp
count/cooldown fields used stock `QSpinBox`/`QDoubleSpinBox` — their
native up/down arrows are only a few px tall and were hard to click
reliably (direct user feedback after testing live). Replaced with a
custom `_Stepper` widget (`[−] value [+]`, 26×24px buttons, same styling
family as Crosshair's nudge buttons) giving each a proper click target.
See docs/DECISIONS.md, 2026-09-08, "tiny spinbox arrows replaced with a
stepper" for the full writeup, including a `Signal(float)`-coerces-int
gotcha caught along the way.

## What carries over vs. what gets dropped

Carries over (same user-facing behavior, reimplemented):
- Live throttle-axis bar (track, ticks, knob, deadzone/deflection coloring)
- Draggable position, resizable, vertical/horizontal orientation
- Two saved positions (SCM/NAV) with a hotkey to jump between them
- Device/axis picker with reverse-axis option
- Home Chirp (audible beep crossing center)
- Bar/line color + opacity customization

Dropped as redundant once this is a mobiOverlay module, not a standalone app:
- **The separate Settings Toplevel window** — replaced entirely by the
  module's card. All configuration lives in `card.body`, opened/closed the
  same way every other module's config is (no separate window to manage).
- **The "Open Settings" hotkey** — meaningless once Settings isn't a
  separate window; mobiOverlay's own Stow/Deploy hotkey already brings the
  whole app forward.
- **Its own tray icon** — mobiOverlay already has a taskbar/window
  presence; a second independent tray icon would be a confusing redundant
  affordance for the same app.
- **The two-window transparent-color-key trick + `SetWindowRgn`/
  `CreateRoundRectRgn` panel-shaping** (`Overlay._apply_window_shape`,
  `RECT`, the whole `bg_win`/`root` split) — this existed only because
  Tkinter on Windows has no real per-pixel alpha compositing. Qt does
  (`Qt.WA_TranslucentBackground`): one `QWidget` with a `paintEvent` drawing
  a real semi-transparent rounded panel replaces both windows and every
  Win32 shape-clipping call.
- **Manual `SetProcessDpiAwareness` dance** — Qt6 is per-monitor-DPI-aware
  by default; nothing to opt into.
- **Standalone `config.json`/its own dependency-missing `messagebox`
  hard-exit** — settings move into mobiOverlay's `config.json` under
  `modules.mobi_throttle`; a missing device puts the card into its error
  state (retry button) via the existing per-module error boundary instead
  of `sys.exit(1)`.

## Floating bar widget

`_ThrottleBar(QWidget)` in `modules/mobi_throttle/module.py`, following the
exact separation Crosshair already established (`_CrosshairOverlay` is a
standalone top-level widget the card only controls, not embeds):

- `Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool`,
  `Qt.WA_TranslucentBackground` for real alpha (see above).
- Own `mousePressEvent`/`mouseMoveEvent`/`mouseReleaseEvent`: left-drag
  moves, right-drag resizes — same UX as ThrottleWatch, no second window
  needed to catch clicks on "empty" pixels since there's only one window.
- `paintEvent` draws background panel (rounded rect, `bg_color` +
  `bg_opacity`), track, tick marks, and knob — same layout math as
  ThrottleWatch (`TRACK_MARGIN`, `TICK_COUNT`, deadzone-to-amber gradient
  via `value_to_color`/`lerp_color`), ported as plain functions since none
  of that logic is Tk-specific. `line_opacity` applies via the painter's
  alpha channel per-element rather than a second window's `-alpha`.
- Defaults to mobiOverlay's theme colors (`theme.ACCENT_CYAN` /
  `theme.BG_PANEL`) instead of ThrottleWatch's hardcoded hex copies of the
  same palette — same visual result, one source of truth. Still fully
  user-overridable via the card's color pickers.

## Axis polling

Own `QTimer` at `POLL_HZ` (60Hz) inside the module, independent of the
host's refresh cycle — matches Crosshair's precedent of `refresh()` being a
no-op for purely-local/high-frequency state. `refresh()` itself becomes a
periodic reconnect check (was `RECONNECT_INTERVAL` polling in
ThrottleWatch's `update_loop`) so the host's own refresh timer/manual
button still does something meaningful (verify the device is still there)
without being the thing driving the 60Hz bar redraw.

Device enumeration/lookup (`list_joysticks`, `find_joystick` using pygame)
ports over near-verbatim — pure pygame API calls, nothing Tk-specific.
`pygame-ce` gets added to `requirements.txt` (lightweight next to
Logistics Hub's PyTorch dependency).

## Hotkeys

Reuses `host/hotkey.py`'s `GlobalHotkey` as-is — it's already a direct port
of ThrottleWatch's own `HotkeyState`/reconcile-watchdog design (see that
file's docstring), proven and already living in `host/`. No host changes
needed: the module just instantiates two of its own `GlobalHotkey`
instances (bar visibility toggle, position toggle — the third,
Open-Settings, is dropped per above). Each installs its own
`keyboard.hook()`; Windows supports multiple low-level hooks per process
without conflict, so nothing needs to be shared/merged with mobiOverlay's
own Stow/Deploy `GlobalHotkey` instance.

The card's hotkey-capture fields follow the same pattern as
`main_window.py`'s `_HotkeyField` (click → `GlobalHotkey.capture_combo()` →
signal back to the GUI thread), adapted to bind to the module's own
`GlobalHotkey` instances instead of the main window's.

## Config

Everything ThrottleWatch's standalone `config.json` held (bar
x/y/width/height, bg/line color+opacity, orientation, axis_index,
device_guid/device_name, axis_reverse, home_chirp_*, position_1/2 +
enabled flags, position_hold_ms, hotkey combos) moves into
`config.json`'s `modules.mobi_throttle` namespace, read/written via
`self.settings` / `config.set_module_settings()` like every other module —
no separate file.

**Nice-to-have, not required for v1:** on first run, if a standalone
ThrottleWatch `config.json` is found at a well-known path, offer to import
its settings so an existing user's tuned position/colors/hotkeys carry
over instead of starting from defaults. Skip if it adds meaningful
complexity — defaults are fine for a first cut.

## Card layout (`create_card`)

Mirrors the old Settings dialog's sections, now inline in `card.body`:
1. **Bar** — SHOW/HIDE toggle button (replaces the visibility hotkey as a
   manual control, same as Crosshair's toggle button).
2. **Device** — combo (Auto + detected), Refresh, Axis stepper, Reverse
   checkbox, Apply.
3. **Appearance** — Orientation combo, bg/line opacity sliders, bg/line
   color buttons opening `QColorDialog` (the custom live eyedropper is
   dropped for v1 — `QColorDialog` covers the same need with an existing
   Qt widget instead of hand-rolled `GetPixel` polling; can revisit later
   if it's actually missed).
4. **Hotkeys** — two capture fields (toggle, position-toggle) + hold-ms
   stepper for the position hotkey.
5. **Positions** — SCM/NAV Set/Go buttons + Enabled checkboxes, same
   semantics as before (at least one must stay enabled).
6. **Home Chirp** — Enabled checkbox, beep-count stepper, cooldown
   stepper.

## Not scoped / open questions for later

- Whether to keep both Reverse-axis (bool) config knobs given orientation
  now also flips visually — likely both stay, they're orthogonal.
- Whether the ThrottleWatch config import (above) is worth building at all.

## Status

Built, live-verified, and confirmed working by the user with a real
throttle (2026-09-08) — "working well." One real usability bug found in
that test and fixed same day (tiny spinbox arrows → the `_Stepper`
widget, see above).

**Click-through toggle added (2026-09-08, direct user request):** a
"Click-through (disable drag/resize)" checkbox in the card, so every
mouse event passes straight through to the game underneath instead of
reaching the bar's drag/resize handlers. Requested because an accidental
left-click-drag on the bar mid-flight was moving it while playing.
Defaults off (so drag/resize still work out of the box); persists to
`config.json` as `click_through`.

First implementation (`Qt.WA_TransparentForMouseEvents`, the same
mechanism Crosshair's reticle uses) didn't actually work when toggled at
runtime — reported by the user same day. Root cause: that Qt attribute
only reliably reaches the native window's real `WS_EX_TRANSPARENT`
extended style at window-*creation* time on this Qt/Windows combination;
toggling it later on an already-shown widget silently no-ops. Fixed by
setting `WS_EX_TRANSPARENT` directly via `GetWindowLongW`/
`SetWindowLongW` on the widget's real HWND, which Windows checks live on
every hit-test. Full writeup in docs/DECISIONS.md, 2026-09-08 (two
entries — original add, then the same-day fix). **Confirmed working by
the user with a real click, same day** — "works great."
