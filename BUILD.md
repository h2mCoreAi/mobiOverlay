# Building mobiOverlay from source

You don't need to trust the prebuilt exe on the Releases page — everything
needed to build it yourself is in this repo, and it's the exact same
process the automated release build uses (`.github/workflows/release.yml`),
so a self-built copy and the one on Releases should be identical.

## Run from source (no build step)

Fastest way to try it without producing an exe at all:

```
git clone <repo-url>
cd mobiOverlay
pip install -r requirements.txt
python host/main.py
```

## Build your own exe

```
pip install -r requirements.txt
pip install pyinstaller
pyinstaller mobioverlay.spec
```

This produces `dist/mobiOverlay.exe`. **`modules/` is not bundled into the
exe on purpose** (see `docs/ARCHITECTURE.md`, "Packaging") — copy it next
to the exe before running:

```
cp -r modules dist/modules
```

Your final layout should look like:

```
dist/
  mobiOverlay.exe
  modules/
    price_lookup/
    trade_route_optimizer/
```

`config.json` isn't something you build or copy — it's created next to the
exe the first time you run it.

## Verifying a downloaded release build matches source

Every release ships a `.sha256` file alongside the zip. Check the tag's
GitHub Actions run log to see the exact commit and steps that produced it,
or just build the same tag yourself with the steps above and compare.
