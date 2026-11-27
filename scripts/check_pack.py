"""Check mobiGuide patch packs against their game data.

    python scripts/check_pack.py                 # every bundled pack
    python scripts/check_pack.py 5.0-ptu         # one pack
    python scripts/check_pack.py 5.0-ptu --write # also store 'reconfirmed' in its pack.json

Adding a patch:
  1. mkdir modules/leveling_guide/packs/<id>/chapters and write pack.json
     ("extends": the previous pack, "patch", "channel", "label").
  2. python scripts/build_contract_catalog.py <scmdb version> --pack modules/leveling_guide/packs/<id>
  3. Add chapters for what's new; reuse an objective id to replace one.
  4. python scripts/check_pack.py <id> --write, fix every error.
Exit code 1 if any pack has errors.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from modules.leveling_guide import guide as guide_mod  # noqa: E402
from modules.leveling_guide.packcheck import check_pack  # noqa: E402

PACKS = ROOT / "modules" / "leveling_guide" / "packs"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("packs", nargs="*", help="pack ids (default: all bundled packs)")
    ap.add_argument("--write", action="store_true", help="write the reconfirmed list into each pack.json")
    args = ap.parse_args(argv)
    found, errors = guide_mod.discover_packs([PACKS])
    for e in errors:
        print("ERROR", e)
    ids = args.packs or sorted(found)
    failed = bool(errors)
    for pid in ids:
        r = check_pack(pid, [PACKS])
        print(f"== {pid}: {'OK' if r.ok else 'FAILED'}  ({len(r.errors)} errors, {len(r.warnings)} warnings, "
              f"{len(r.reconfirm)} inherited objectives re-confirmed, {len(r.stale)} not re-confirmed)")
        for e in r.errors:
            print("   ERROR", e)
        for w in r.warnings:
            print("   warn ", w)
        failed |= not r.ok
        if args.write and pid in found:
            manifest = found[pid].path / "pack.json"
            data = json.loads(manifest.read_text(encoding="utf-8"))
            data["reconfirmed"] = sorted(r.reconfirm)
            manifest.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"   wrote {len(r.reconfirm)} reconfirmed ids to {manifest.relative_to(ROOT)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
