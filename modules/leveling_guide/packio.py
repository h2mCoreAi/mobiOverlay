"""Import and export mobiGuide content. Pure Python, no Qt.

Guides are data only: JSON files. Nothing imported is ever executed, so a
shared guide can't run code on the player's machine. Imports are checked
before anything is installed.

What can be imported:
- a **pack** (.zip): a folder with pack.json, chapters/*.json and optionally
  contracts.json. Installed to <user dir>/packs/<pack id>/ and then offered
  in the "Game version" menu. A pack usually `extends` a bundled one.
- a **chapter** (.json): one chapter file. Installed to <user dir>/, where it
  loads on top of whichever pack is active (it can add a new chapter, or add
  objectives to an existing chapter by reusing its id).

What can be exported:
- your own objectives (from "+ ADD OBJECTIVE") as one chapter file anyone
  can import.
"""
from __future__ import annotations

import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

try:
    from . import guide as guide_mod
except ImportError:
    # Loaded by file path from module.py (the module loader doesn't import
    # modules as packages): use the guide module it already loaded.
    import sys as _sys
    guide_mod = _sys.modules["mobioverlay_leveling_guide_guide"]

MAX_FILE_BYTES = 20 * 1024 * 1024     # one JSON file (a contract catalog is ~0.5 MB)
MAX_ZIP_BYTES = 60 * 1024 * 1024      # everything in a pack, uncompressed
MAX_FILES = 500
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class ImportError_(ValueError):
    """Raised when content can't be imported; the message says why."""


def _read_json_bytes(data: bytes, name: str) -> dict:
    try:
        value = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ImportError_(f"{name} isn't valid JSON ({exc})") from None
    if not isinstance(value, dict):
        raise ImportError_(f"{name}: the top level must be a JSON object")
    return value


def _check_chapter(data: dict, name: str) -> list[str]:
    """Problems that make a chapter file unusable, plus per-objective ones."""
    if data.get("schema", guide_mod.SCHEMA_VERSION) != guide_mod.SCHEMA_VERSION:
        return [f"{name}: unsupported schema {data.get('schema')!r}"]
    meta = data.get("chapter")
    if not isinstance(meta, dict) or not meta.get("id") or not meta.get("title"):
        return [f"{name}: needs chapter.id and chapter.title"]
    problems = []
    objectives = data.get("objectives")
    if not isinstance(objectives, list) or not objectives:
        return [f"{name}: has no objectives"]
    for raw in objectives:
        _, errs = guide_mod._parse_objective(raw, meta["id"], name, False)
        problems += errs
    return problems


def import_chapter(src: Path, user_dir: Path) -> tuple[Path, list[str]]:
    """Install one chapter .json into user_dir. Returns (installed path,
    warnings). Raises ImportError_ if the file is unusable."""
    src = Path(src)
    if src.stat().st_size > MAX_FILE_BYTES:
        raise ImportError_(f"{src.name} is too large to be a guide chapter")
    data = _read_json_bytes(src.read_bytes(), src.name)
    if "chapter" not in data and ("patch" in data or "label" in data):
        raise ImportError_(f"{src.name} is a pack manifest; import the whole pack as a .zip")
    problems = _check_chapter(data, src.name)
    if problems and not any(isinstance(o, dict) for o in data.get("objectives") or []):
        raise ImportError_("; ".join(problems))
    fatal = [p for p in problems if "needs chapter" in p or "schema" in p or "no objectives" in p]
    if fatal:
        raise ImportError_("; ".join(fatal))
    user_dir.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", src.stem).strip("-") or "chapter"
    dest = user_dir / f"{stem}.json"
    n = 2
    while dest.exists():
        dest = user_dir / f"{stem}-{n}.json"
        n += 1
    dest.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return dest, problems


def _safe_members(zf: zipfile.ZipFile) -> list[tuple[zipfile.ZipInfo, PurePosixPath]]:
    members = []
    total = 0
    for info in zf.infolist():
        if info.is_dir():
            continue
        path = PurePosixPath(info.filename.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts or ":" in info.filename:
            raise ImportError_(f"unsafe path in zip: {info.filename}")
        if path.suffix.lower() != ".json":
            continue  # data only: anything that isn't JSON is ignored
        if info.file_size > MAX_FILE_BYTES:
            raise ImportError_(f"{info.filename} is too large")
        total += info.file_size
        members.append((info, path))
    if total > MAX_ZIP_BYTES:
        raise ImportError_("the pack is too large")
    if len(members) > MAX_FILES:
        raise ImportError_("the pack has too many files")
    return members


def import_pack(src: Path, packs_dir: Path, known_pack_roots: list[Path] | None = None,
                replace: bool = False) -> tuple[Path, list[str]]:
    """Install a pack .zip into packs_dir/<id>/. The zip may hold the pack at
    its root or inside one folder. Only .json files are taken. Returns
    (installed folder, warnings). Raises ImportError_ if it's unusable."""
    src = Path(src)
    try:
        zf = zipfile.ZipFile(src)
    except (zipfile.BadZipFile, OSError) as exc:
        raise ImportError_(f"{src.name} isn't a readable .zip ({exc})") from None
    with zf:
        members = _safe_members(zf)
        manifests = [p for _, p in members if p.name == "pack.json"]
        if len(manifests) != 1:
            raise ImportError_("the zip must contain exactly one pack.json")
        root = manifests[0].parent
        manifest_info = next(i for i, p in members if p == manifests[0])
        manifest = _read_json_bytes(zf.read(manifest_info), "pack.json")
        pid = manifest.get("id")
        if not isinstance(pid, str) or not _SAFE_ID.match(pid):
            raise ImportError_("pack.json needs an 'id' made of letters, digits, '.', '_' or '-'")
        if not manifest.get("label") or not manifest.get("patch"):
            raise ImportError_("pack.json needs 'label' and 'patch'")
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp) / pid
            for info, path in members:
                try:
                    rel = path.relative_to(root)
                except ValueError:
                    continue  # outside the pack folder
                if rel.parts and rel.parts[0] not in ("chapters",) and rel.name not in ("pack.json", "contracts.json"):
                    continue
                target = stage.joinpath(*rel.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zf.read(info))
            warnings: list[str] = []
            for chapter in sorted((stage / "chapters").glob("*.json")) if (stage / "chapters").is_dir() else []:
                warnings += _check_chapter(_read_json_bytes(chapter.read_bytes(), chapter.name), chapter.name)
            # Load it the way the card will, with the bundled packs available
            # for `extends`, to catch broken inheritance before installing.
            roots = list(known_pack_roots or []) + [Path(tmp)]
            loaded = guide_mod.load_pack(pid, roots)
            if loaded.pack is None or loaded.pack.id != pid:
                raise ImportError_("the pack couldn't be loaded: " + "; ".join(loaded.errors[:5]))
            if not loaded.objectives:
                raise ImportError_("the pack has no objectives")
            warnings += loaded.errors
            dest = packs_dir / pid
            if dest.exists():
                if not replace:
                    raise ImportError_(f"a pack called {pid!r} is already installed")
                shutil.rmtree(dest)
            packs_dir.mkdir(parents=True, exist_ok=True)
            shutil.copytree(stage, dest)
    return dest, warnings


def export_custom_chapter(custom_objectives: list[dict], dest: Path, title: str = "Shared objectives",
                          chapter_id: str = "shared-objectives", patch: str = "") -> Path:
    """Write your own objectives as one chapter file others can import."""
    objectives = []
    for o in custom_objectives:
        o = {k: v for k, v in o.items() if k != "chapter"}
        o["tags"] = [t for t in o.get("tags", []) if t != "custom"]
        objectives.append(o)
    data = {"schema": guide_mod.SCHEMA_VERSION,
            "chapter": {"id": chapter_id, "title": title, "order": 9000, "patch": patch,
                        "summary": "Objectives shared by another mobiGuide player."},
            "objectives": objectives}
    dest = Path(dest)
    dest.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return dest


def export_pack(pack_dir: Path, dest_zip: Path) -> Path:
    """Zip a pack folder (pack.json, chapters/, contracts.json) for sharing."""
    pack_dir, dest_zip = Path(pack_dir), Path(dest_zip)
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(pack_dir.rglob("*.json")):
            zf.write(path, str(PurePosixPath(pack_dir.name, *path.relative_to(pack_dir).parts)))
    return dest_zip
