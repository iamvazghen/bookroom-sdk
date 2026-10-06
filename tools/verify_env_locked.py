"""Confirm no provider credential is still active in any local .env file."""

import re
from pathlib import Path

FILES = (Path(r"D:\summarizer\src\.env"), Path(r"D:\summarizer-sdk\.env"))
PATTERN = re.compile(r"(API_KEY|SECRET|TOKEN)\s*=\s*(\S+)")

problems = 0
for path in FILES:
    if not path.is_file():
        print(f"{path}: not present")
        continue
    active, commented = [], []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not stripped:
            continue
        is_commented = stripped.startswith("#")
        body = stripped.lstrip("#").strip() if is_commented else stripped
        match = PATTERN.search(body)
        if not match or not match.group(2).strip():
            continue
        label = f"{match.group(1)}"
        if is_commented:
            commented.append(f"line {number}: {label}")
        else:
            active.append(f"line {number}: {label} = STILL ACTIVE")
    status = "clean - no active credentials" if not active else "PROBLEM"
    print(f"{path}: {status}")
    for item in active:
        print(f"    {item}")
    if commented:
        print(f"    commented out: {', '.join(commented)}")
    problems += len(active)

print()
print("RESULT:", "all credentials are disabled" if problems == 0
      else f"{problems} credential(s) still active")
raise SystemExit(1 if problems else 0)
