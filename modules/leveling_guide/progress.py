"""Progress and custom-objective storage for the Leveling Guide. Pure Python.

Both files live next to config.json (app_root()), not inside modules/, so a
new build that replaces _internal/ keeps them:
- leveling_guide_progress.json: per-objective state, keyed by objective id,
  so adding, removing or reordering guide content keeps your progress.
- leveling_guide_custom.json: objectives added from the card.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from host.fileio import atomic_write_text, quarantine_corrupt
from host.paths import app_root

SCHEMA_VERSION = 1


def progress_path() -> Path:
    return app_root() / "leveling_guide_progress.json"


def custom_path() -> Path:
    return app_root() / "leveling_guide_custom.json"


def user_guides_dir() -> Path:
    return app_root() / "leveling_guide"


def _load_dict(path: Path, key: str, default):
    if not path.exists():
        return default
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        # Unreadable but not known-bad (locked by a sync client): refuse
        # rather than let the next save overwrite real data.
        raise
    except ValueError:
        raw = None
    value = raw.get(key) if isinstance(raw, dict) else None
    if not isinstance(value, type(default)):
        quarantine_corrupt(path)
        return default
    return value


class ProgressStore:
    def __init__(self, path: Path | None = None):
        self.path = path or progress_path()
        self._objectives: dict[str, dict] = {}
        self._current: str | None = None
        self._rep: dict[str, int] = {}        # "faction|ladder" -> reputation points
        self._log: list[dict] = []            # logged contract runs, newest last (for undo)
        self._goals: list[dict] = []
        self._earned = 0                      # aUEC from logged runs, all time
        self.load()

    def load(self):
        self._objectives = _load_dict(self.path, "objectives", {})
        self._current = None
        self._rep, self._log, self._goals, self._earned = {}, [], [], 0
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except ValueError:
                raw = None
            if isinstance(raw, dict):
                cur = raw.get("current")
                self._current = cur if isinstance(cur, str) else None
                rep = raw.get("reputation")
                if isinstance(rep, dict):
                    self._rep = {k: int(v) for k, v in rep.items() if isinstance(v, (int, float))}
                if isinstance(raw.get("log"), list):
                    self._log = [e for e in raw["log"] if isinstance(e, dict)][-500:]
                if isinstance(raw.get("goals"), list):
                    self._goals = [g for g in raw["goals"] if isinstance(g, dict) and g.get("id")]
                if isinstance(raw.get("earned_uec"), (int, float)):
                    self._earned = int(raw["earned_uec"])

    def save(self):
        payload = {"schema": SCHEMA_VERSION, "current": self._current, "objectives": self._objectives,
                   "reputation": self._rep, "earned_uec": self._earned, "goals": self._goals,
                   "log": self._log[-500:]}
        atomic_write_text(self.path, json.dumps(payload, indent=2))

    # -- reputation, logged contracts and goals ---------------------------
    def rep(self, key: str) -> int | None:
        return self._rep.get(key)

    def known_rep(self) -> dict[str, int]:
        return dict(self._rep)

    def set_rep(self, key: str, points: int):
        self._rep[key] = max(-1_000_000, int(points))
        self.save()

    def raise_rep_to(self, key: str, points: int):
        """Never lowers a known value (used when setup or a ticked rank-up
        tells us you're at least this far)."""
        if self._rep.get(key) is None or self._rep[key] < points:
            self._rep[key] = int(points)
            self.save()

    @property
    def earned_uec(self) -> int:
        return self._earned

    def log_run(self, contract: dict) -> dict:
        """Count one finished run of a catalog contract: its reputation goes
        onto every faction ladder it rewards, its pay onto earned aUEC."""
        gains = [[r["faction"], r["ladder"], int(r["amount"])] for r in contract.get("rep", [])]
        pay = int((contract.get("uec") or [0, 0])[1] or (contract.get("uec") or [0, 0])[0] or 0)
        for faction, ladder, amount in gains:
            key = f"{faction}|{ladder}"
            self._rep[key] = self._rep.get(key, 0) + amount
        self._earned += pay
        entry = {"key": contract.get("key") or contract.get("title"), "title": contract.get("title"),
                 "rep": gains, "uec": pay, "at": time.time()}
        self._log.append(entry)
        self.save()
        return entry

    def undo_last_run(self) -> dict | None:
        if not self._log:
            return None
        entry = self._log.pop()
        for faction, ladder, amount in entry.get("rep", []):
            key = f"{faction}|{ladder}"
            if key in self._rep:
                self._rep[key] -= int(amount)
        self._earned = max(0, self._earned - int(entry.get("uec") or 0))
        self.save()
        return entry

    def runs_logged(self, key: str) -> int:
        return sum(1 for e in self._log if e.get("key") == key)

    def last_run(self) -> dict | None:
        return self._log[-1] if self._log else None

    def goals(self) -> list[dict]:
        return list(self._goals)

    def goal(self, gid: str) -> dict | None:
        return next((g for g in self._goals if g.get("id") == gid), None)

    def add_goal(self, goal: dict) -> dict:
        goal = dict(goal)
        goal.setdefault("id", f"goal-{int(time.time() * 1000)}")
        goal.setdefault("created", time.time())
        goal.setdefault("earned_at_start", self._earned)
        self._goals.append(goal)
        self.save()
        return goal

    def update_goal(self, gid: str, **fields):
        goal = self.goal(gid)
        if goal is not None:
            goal.update(fields)
            self.save()

    def remove_goal(self, gid: str):
        self._goals = [g for g in self._goals if g.get("id") != gid]
        self.save()

    def goal_money(self, goal: dict) -> int:
        """Wallet estimate for a money or ship goal: what you said you had
        when you set it, plus everything logged since."""
        return int(goal.get("start_uec") or 0) + self._earned - int(goal.get("earned_at_start") or 0)

    # -- queries ---------------------------------------------------------
    def _state(self, oid: str) -> dict:
        st = self._objectives.get(oid)
        return st if isinstance(st, dict) else {}

    def is_done(self, oid: str) -> bool:
        return bool(self._state(oid).get("done"))

    def done_ids(self) -> set[str]:
        return {oid for oid, st in self._objectives.items() if isinstance(st, dict) and st.get("done")}

    def is_skipped(self, oid: str) -> bool:
        return bool(self._state(oid).get("skipped")) and not self.is_done(oid)

    def skipped_ids(self) -> set[str]:
        return {oid for oid, st in self._objectives.items()
                if isinstance(st, dict) and st.get("skipped") and not st.get("done")}

    def passed_ids(self) -> set[str]:
        """Done or skipped: what the guide treats as behind you."""
        return self.done_ids() | self.skipped_ids()

    def step(self, oid: str) -> int:
        value = self._state(oid).get("step", 0)
        return value if isinstance(value, int) and value >= 0 else 0

    def count(self, oid: str) -> int:
        value = self._state(oid).get("count", 0)
        return value if isinstance(value, int) and value >= 0 else 0

    @property
    def current(self) -> str | None:
        return self._current

    # -- mutation --------------------------------------------------------
    def _edit(self, oid: str) -> dict:
        st = self._objectives.get(oid)
        if not isinstance(st, dict):
            st = {}
            self._objectives[oid] = st
        return st

    def set_current(self, oid: str | None):
        if oid != self._current:
            self._current = oid
            self.save()

    def set_done(self, oid: str, done: bool = True):
        st = self._edit(oid)
        st["done"] = bool(done)
        st.pop("skipped", None)
        if done:
            st["done_at"] = time.time()
        else:
            st.pop("done_at", None)
        self.save()

    def set_skipped(self, oid: str, skipped: bool = True):
        st = self._edit(oid)
        if skipped:
            st["skipped"] = True
            st["done"] = False
        else:
            st.pop("skipped", None)
        self.save()

    def set_step(self, oid: str, index: int):
        self._edit(oid)["step"] = max(0, int(index))
        self.save()

    def add_count(self, oid: str, delta: int) -> int:
        st = self._edit(oid)
        st["count"] = max(0, self.count(oid) + int(delta))
        self.save()
        return st["count"]

    def reset(self, oid: str):
        if oid in self._objectives:
            del self._objectives[oid]
            self.save()

    def reset_all(self):
        self._objectives = {}
        self._current = None
        self._rep, self._log, self._goals, self._earned = {}, [], [], 0
        self.save()


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:40] or "objective"


class CustomObjectives:
    """Objectives the player adds from the card, stored in the same schema
    as the bundled chapter files (plus a 'chapter' field naming where each
    one goes)."""

    def __init__(self, path: Path | None = None):
        self.path = path or custom_path()
        self._objectives: list[dict] = _load_dict(self.path, "objectives", [])

    def save(self):
        payload = {"schema": SCHEMA_VERSION, "objectives": self._objectives}
        atomic_write_text(self.path, json.dumps(payload, indent=2))

    def all(self) -> list[dict]:
        return list(self._objectives)

    def add(self, title: str, steps: list[dict], chapter_id: str | None = None, why: str = "",
            kind: str = "task", goal_target: int = 0, goal_unit: str = "", existing_ids: set[str] | None = None) -> dict:
        taken = set(existing_ids or set()) | {o.get("id") for o in self._objectives}
        base = "my-" + _slug(title)
        oid, n = base, 2
        while oid in taken:
            oid, n = f"{base}-{n}", n + 1
        obj = {"id": oid, "title": title.strip(), "kind": kind, "why": why.strip(), "steps": steps,
               "tags": ["custom"]}
        if chapter_id:
            obj["chapter"] = chapter_id
        if kind == "grind":
            obj["goal"] = {"target": max(1, int(goal_target)), "unit": goal_unit.strip() or "times"}
        self._objectives.append(obj)
        self.save()
        return obj

    def remove(self, oid: str) -> bool:
        before = len(self._objectives)
        self._objectives = [o for o in self._objectives if o.get("id") != oid]
        if len(self._objectives) != before:
            self.save()
            return True
        return False
