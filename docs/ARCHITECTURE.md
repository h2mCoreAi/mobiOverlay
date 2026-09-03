# Architecture

## Layout

```
mobiOverlay/
  host/            # main window, card container, config, module loader, HTTP client
  modules/
    <module_name>/ # one folder per module, auto-discovered
  docs/
  config.json       # generated at runtime, git-ignored
```

## Module contract

Each module folder exposes an entry point (e.g. `modules/<name>/module.py`)
with a single class the host can instantiate. That class must provide:

- `module_id: str` — unique, stable, used as the config namespace key
- `display_name: str` — shown in the card picker
- `settings_schema` — declares what config keys this module reads/writes
  (merged into `config.json` under `modules.<module_id>`)
- `create_card(parent) -> Card` — builds and returns this module's card widget
- `refresh()` — fetch/update data on its own schedule; runs inside the host's
  error boundary, so a failure here degrades only this module's card

The host never reaches into a module's internals beyond this contract. Adding
module #2 means adding a new folder under `modules/` — zero edits to `host/`
or to any other module.

## Host responsibilities

- Discover and load modules from `modules/` at startup; catch and isolate
  per-module import/init failures (log + show error card state, don't crash)
- Own the window: always-on-top, drag, resize, opacity
- Own the card container: free-form positioning, collapse/expand, close/reopen
  via a card picker, persist layout to `config.json`
- Own the shared UEX API client (base URL, bearer token, rate-limit handling)
  and hand it to modules rather than each module managing its own HTTP client
- Own `config.json` read/write; modules only touch their own namespaced section

## Config schema (config.json)

```json
{
  "ui": { "opacity": 0.9, "always_on_top": true, "window_geometry": {} },
  "api": { "uex_token": "", "uex_base_url": "https://api.uexcorp.uk/2.0/" },
  "cards": { "<card_id>": { "x": 0, "y": 0, "collapsed": false, "visible": true } },
  "modules": { "<module_id>": { } }
}
```

## Card system

A reusable `Card` base widget (not one-off per module): title bar (click to
collapse/expand), close button, drag-to-reposition, consistent HUD styling.
Modules subclass or compose this to render their own content in the body.

## Packaging

PyInstaller. `host/` is bundled into the exe. `modules/` and `config.json`
are **not** — they live as real files next to the exe on disk, not frozen
inside it. This is a deliberate decision (2026-09-03, see DECISIONS.md):

- `modules/` external → adding/editing a module never requires rebuilding
  the exe, matching the original "drop a folder in, zero rebuild" goal.
  It also gives the community a way to audit what a module does (plain
  readable `.py`) before running it, which matters for an unsigned exe.
- `config.json` external → a PyInstaller onefile build extracts to a
  temp directory that's wiped and recreated every launch; anything written
  relative to that temp path would silently never persist between runs.

Both paths are resolved via `host/paths.py`'s `app_root()`: the exe's own
folder when frozen (`sys.frozen`), the project root when running from
source. Bundled, non-pluggable assets (fonts) keep using ordinary
`__file__`-relative paths — those are meant to travel inside the frozen
build, unlike modules/config.

Because `modules/` is external and not a real importable package once
frozen, the module loader imports each `modules/<name>/module.py` by file
path (`importlib.util.spec_from_file_location`), not as a dotted
`modules.<name>.module` package import — see `host/module_loader.py`.

Verify no personal machine paths get baked into the build or logged in
example configs before any public release.
