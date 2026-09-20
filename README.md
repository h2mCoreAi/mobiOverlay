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

## Modules

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
| **mobiThrottle** | Throttle axis visualization with saved positions |

### Logistics Hub First-Scan Note

The first scan after launching takes **10-30 seconds** while the OCR engine
initializes. Subsequent scans are fast. On first-ever use, it also downloads
a ~100MB language model (cached in `~/.EasyOCR/` afterward).

## Using the Overlay

- **Drag** the title bar to move the window
- **Drag** card headers to reposition individual cards
- **Resize** the window via the corner grip, or cards via their resize handles
- **Stow** cards (hide without closing) via their header button; **Deploy**
  them from the TRAY panel
- **Minimize** the whole app to a small pill with `▬` (or press the global hotkey)
- **Settings** (gear icon): window/card opacity, text size, global hotkey

Cards snap to a grid when dragged, and layout persists to `config.json` next
to the exe.

> **Troubleshooting SC input:** If Star Citizen stops responding to keyboard
> input (WASD, menus, etc.), quit mobiOverlay first — the global hotkey uses a
> low-level keyboard hook that can interfere with exclusive-fullscreen games.
> Don't run two copies of mobiOverlay at once.

## Files

```
mobiOverlay/
  mobiOverlay.exe    # The whole application — all 8 modules bundled inside
  config.json        # Created on first run, stores your layout/settings
```

Module source code is bundled inside the exe. To inspect or modify modules,
see the `modules/` folder in the [source repository](../../).

## Building from Source

See [BUILD.md](BUILD.md) for full instructions. Short version:

```bash
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
pip install pyinstaller
pyinstaller mobioverlay.spec --noconfirm
```

The resulting `dist/mobiOverlay.exe` is a complete single-file build.

## Privacy

- No game memory reads, no log parsing (except optional Game.log verification
  in Logistics Hub, which you enable by setting the path yourself)
- No telemetry, no network calls except to the public UEX Corp API
- No UEX auth token embedded — the app uses only anonymous public endpoints

## License

[MIT](LICENSE)
