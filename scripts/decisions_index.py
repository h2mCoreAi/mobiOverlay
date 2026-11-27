"""Print a one-line-per-entry index of docs/DECISIONS.md, optionally
filtered by keywords, so an agent can find the entries it needs without
loading the whole (several-thousand-line) log.

    python scripts/decisions_index.py                 # every entry
    python scripts/decisions_index.py taskbar pill    # titles or bodies mentioning any word
    python scripts/decisions_index.py --since 2026-10-01

Each line is `line-number  date  title`; read that entry with an offset
into the file instead of reading it all.
"""
import re
import sys
from pathlib import Path

DECISIONS = Path(__file__).resolve().parent.parent / "docs" / "DECISIONS.md"
ENTRY_RE = re.compile(r"^- \*\*(\d{4}-\d{2}-\d{2})\s*[—-]+\s*(.*)")


def entries(lines: list[str]):
    """Yield (line_no, date, title, body) for each top-level dated entry."""
    starts = [i for i, line in enumerate(lines) if ENTRY_RE.match(line)]
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        date, rest = ENTRY_RE.match(lines[start]).groups()
        # Titles are bold and may wrap onto the next line(s).
        title = rest
        j = start + 1
        while "**" not in title and j < end:
            title += " " + lines[j].strip()
            j += 1
        title = title.split("**")[0].strip()
        yield start + 1, date, title, "\n".join(lines[start:end])


def main(argv: list[str]) -> int:
    since = None
    if "--since" in argv:
        i = argv.index("--since")
        since = argv[i + 1] if i + 1 < len(argv) else None
        argv = argv[:i] + argv[i + 2:]
    words = [w.lower() for w in argv]
    lines = DECISIONS.read_text(encoding="utf-8").splitlines()
    shown = 0
    for line_no, date, title, body in entries(lines):
        if since and date < since:
            continue
        if words and not any(w in body.lower() for w in words):
            continue
        print(f"{line_no:>5}  {date}  {title}")
        shown += 1
    print(f"-- {shown} entries", file=sys.stderr)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main(sys.argv[1:]))
