# mobiOverlay

A modular, always-on-top Star Citizen data overlay styled after the in-game
MobiGlas. Dark sci-fi HUD with cyan/amber accents. Data comes from the
[UEX Corp API](https://uexcorp.uk/) (community-sourced SC trade/economy data).

## Quick Start

1. **Download** the latest `mobiOverlay-vX.X.X-windows.zip` from
   [Releases](../../releases)
2. **Extract** `mobiOverlay.exe` anywhere (e.g. `C:\Games\mobiOverlay\`)
3. **Run** `mobiOverlay.exe`

That's it — one file, all 8 modules included. No separate folders needed.

### Windows SmartScreen Warning

You'll likely see "Windows protected your PC" on first run — this is normal
for unsigned executables. Click **More info** → **Run anyway**.

The exe is built automatically by GitHub Actions from public source code.
You can verify the build by checking the Actions log for the release tag,
or [build it yourself](BUILD.md).

## Features

### Modules

All modules are included and load automatically:

| Module | Description |
|--------|-------------|
| **Commodity Prices** | Best buy/sell prices for any commodity across all systems |
| **Trade Route Optimizer** | Find profitable routes from your current terminal |
| **Logistics Hub** | OCR-based hauling contract reader with route planning |
| **Refinery Finder** | Compare refinery yields and capacities by raw ore |
| **Multi-Commodity Finder** | Find terminals that trade multiple commodities at once |
| **Crosshair** | Customizable centered reticle overlay |
| **mobiNotes** | In-game notepad with pages, tags, and search |
| **mobiThrottle** | Throttle axis visualization with saved positions (its two hotkeys are unset until you set them in the card) |

### Window Controls

- **Stow to pill** (`▬` button or global hotkey) — shrinks the overlay to a
  small pill showing just the wordmark; click to restore
- **Minimize / maximize** (`🗕` / `🗖` buttons, or double-click the title bar
  to maximize) — normal Windows behavior; the overlay has a taskbar entry
- **System tray icon** — right-click for Show/Stow/Quit; recover the overlay
  if the pill lands somewhere invisible
- **Global hotkey** (Settings, no default — empty until you set one) —
  toggle stow/deploy while Star Citizen has focus
- **Click-through pill** (Settings) — when enabled, clicks pass through the
  stowed pill to the game. Rest the cursor on the pill for a moment and it
  lights up and becomes clickable (click to redeploy, or drag it); it goes
  back to click-through when the cursor leaves. The hotkey and tray still work

### Card Management

- **Drag** the title bar to move the window
- **Drag** card headers to reposition individual cards (snap to grid)
- **Resize** the window via the corner grip, or cards via their resize handles
- **Stow** cards (hide without closing) via their header button
- **Deploy** stowed cards from the TRAY panel
- **Collapse All / Expand All** (`▾ ALL` / `▸ ALL`) — toggle all cards at once

### Settings

- **Window Opacity** — how see-through the empty space around cards is
- **Card Opacity** — how see-through card backgrounds are
- **Text Size** — Small / Normal / Large / Extra Large (applies on relaunch)
- **Global Hotkey** — click the field, press a key combo, Escape to cancel
- **Debug Console** — shows log output (applies on relaunch)
- **Relaunch** — restart the overlay to apply settings

## Logistics Hub First-Scan Note

The first scan after launching takes **10-30 seconds** while the OCR engine
initializes. Subsequent scans are fast. On first-ever use, it also downloads
a ~100MB language model (cached in `~/.EasyOCR/` afterward).

## Troubleshooting

### Star Citizen keyboard stops working

If WASD, menus, or other keyboard input stops responding in Star Citizen:

1. **Quit mobiOverlay** (Task Manager → `mobiOverlay.exe`, or right-click tray → Quit)
2. **Quit Star Citizen normally** and relaunch

The global hotkey uses a low-level keyboard hook that can interfere with
exclusive-fullscreen games if the overlay crashes or isn't closed cleanly.

**Don't run two copies of mobiOverlay at once** — the single-instance guard
prevents this, but if you somehow bypass it, two keyboard hooks will race.

### Overlay disappeared

Check the **system tray** (notification area) — the mobiOverlay icon is there.
Double-click or right-click → Show mobiOverlay.

If you stowed to pill and can't find it (e.g. it landed in a multi-monitor gap),
use the system tray or the global hotkey to restore.

## Files

```
mobiOverlay/
  mobiOverlay.exe          # The whole application — all 8 modules bundled inside
  config.json              # Your layout/settings (created on first run)
  locations_cache.json     # UEX location cache (auto-refreshes weekly)
  mobinotes_data.json      # mobiNotes storage (if you use that module)
  logistics_hub_debug.jsonl  # OCR debug log (if you use Logistics Hub)
  logistics_hub_completed.jsonl  # Contracts you marked COMPLETE
  .mobioverlay.lock        # Single-instance guard (safe to ignore)
```

## Building from Source

See [BUILD.md](BUILD.md) for full instructions. Short version:

```bash
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
pip install pyinstaller
pyinstaller mobioverlay.spec --noconfirm
```

Output: `dist/mobiOverlay.exe` (~333 MB).

## Privacy

- No game memory reads, no log parsing (except optional Game.log verification
  in Logistics Hub, which you enable by setting the path yourself)
- No telemetry, no network calls except to the public UEX Corp API
- No UEX auth token embedded — the app uses only anonymous public endpoints

## License

[MIT](LICENSE)
