"""Run every tests/test_*.py in its own process and report one summary.

Each test file stays standalone (plain asserts, `python tests/<file>.py`);
this just runs them all with the settings they need on any Windows console:
offscreen Qt (no visible window, no input hooks) and UTF-8 output.

    python tests/run_all.py            # all suites
    python tests/run_all.py notes api  # only files whose name contains a word

Exit code is 0 only if every selected suite passed.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
ROOT = TESTS_DIR.parent
TIMEOUT_S = 300


def main(argv: list[str]) -> int:
    files = sorted(TESTS_DIR.glob("test_*.py"))
    if argv:
        files = [f for f in files if any(word in f.stem for word in argv)]
    if not files:
        print("No test files matched.")
        return 1

    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONIOENCODING="utf-8")
    failed = []
    for path in files:
        start = time.monotonic()
        try:
            result = subprocess.run(
                [sys.executable, str(path)], cwd=ROOT, env=env,
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=TIMEOUT_S,
            )
            ok, summary_source = result.returncode == 0, result.stdout
            output = result.stdout + result.stderr
        except subprocess.TimeoutExpired as exc:
            ok, output = False, f"timed out after {TIMEOUT_S}s\n{exc.stdout or ''}{exc.stderr or ''}"
            summary_source = output
        elapsed = time.monotonic() - start
        # Suites log expected errors to stderr; the pass line is on stdout.
        last = next((line for line in reversed((summary_source or output).strip().splitlines()) if line.strip()), "")
        print(f"{'PASS' if ok else 'FAIL'}  {path.name:<40} {elapsed:5.1f}s  {last[:90]}")
        if not ok:
            failed.append((path.name, output))

    for name, output in failed:
        print(f"\n===== {name} output =====\n{output.rstrip()}")
    print(f"\n{len(files) - len(failed)}/{len(files)} test files passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
