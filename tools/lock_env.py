"""Comment out provider keys in the local .env files.

Run after a live run has finished, so a deployed demo can never reach a
credential that happens to sit in a working copy. The line is replaced with a
commented form that keeps the variable name visible, so it is obvious what was
removed and how to restore it.

    python tools/lock_env.py            # comment the keys out
    python tools/lock_env.py --dry-run  # show what would change
    python tools/lock_env.py --restore  # put them back

Only these names are ever touched:

    GEMINI_API_KEY  MINIMAX_API_KEY  TYPESAFE_API_KEY
    GEMINI_ENABLED  JEV_ENABLED
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

TARGETS = ("GEMINI_API_KEY", "MINIMAX_API_KEY", "TYPESAFE_API_KEY")
FILES = (Path(r"D:\summarizer\src\.env"), Path(r"D:\summarizer-sdk\.env"))


def process(path: Path, dry_run: bool, restore: bool) -> tuple[int, list[str]]:
    if not path.is_file():
        return 0, [f"{path.name}: not present"]
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines()
    notes: list[str] = []
    changed = 0

    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if restore:
            # # NAME=<value>  ->  NAME=<value>
            match = re.match(r"^#\s*(" + "|".join(TARGETS) + r")\s*=\s*(\S+)\s*$", stripped)
            if match:
                out.append(f"{match.group(1)}={match.group(2)}")
                changed += 1
                continue
        else:
            match = re.match(r"^(" + "|".join(TARGETS) + r")\s*=\s*(\S.*)$", stripped)
            if match and not stripped.startswith("#"):
                out.append(f"# {match.group(1)}={match.group(2)}")
                changed += 1
                notes.append(f"{match.group(1)} commented out")
                continue
        out.append(line)

    if changed and not dry_run:
        path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return changed, notes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--restore", action="store_true")
    args = parser.parse_args()

    total = 0
    for path in FILES:
        changed, notes = process(path, args.dry_run, args.restore)
        total += changed
        label = "would change" if args.dry_run else "changed"
        print(f"{path}: {label} {changed} line(s)")
        for note in notes:
            print(f"    {note}")
    print(f"\ntotal lines {label}: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
