"""Measure real, full-length books from the local library.

The time model in the README depends on pages-per-book and words-per-page. Both
are measured here from actual books rather than assumed, and the measurements
are printed so the README's arithmetic can be checked against them.
"""

from __future__ import annotations

import statistics
from pathlib import Path

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz

DOWNLOADS = Path(r"C:\Users\iamva\Downloads")
MIN_PAGES = 80          # full-length books only
MAX_BOOKS = 25


def candidate_pdfs() -> list[Path]:
    files = []
    for path in sorted(DOWNLOADS.glob("*.pdf")):
        try:
            if path.stat().st_size < 200_000:   # skip leaflets and scans-as-image
                continue
        except OSError:
            continue
        files.append(path)
    return files


def measure(path: Path) -> dict | None:
    try:
        document = fitz.open(str(path))
    except Exception:  # noqa: BLE001
        return None
    try:
        pages = len(document)
        if pages < MIN_PAGES:
            return None
        # Sample pages evenly; counting every page of a 600-page book is slow
        # and the ratio does not change materially across a single book.
        step = max(1, pages // 20)
        sampled = list(range(0, pages, step))[:20]
        words = sum(len(document[i].get_text().split()) for i in sampled)
        return {
            "name": path.name,
            "pages": pages,
            "sampled_pages": len(sampled),
            "words_per_page": words / max(1, len(sampled)),
        }
    finally:
        document.close()


def main() -> int:
    rows = []
    for path in candidate_pdfs():
        if len(rows) >= MAX_BOOKS:
            break
        row = measure(path)
        if row and row["words_per_page"] > 0:
            rows.append(row)

    if not rows:
        print("no full-length books found")
        return 1

    print(f"{'book':<54} {'pages':>7} {'w/page':>8}")
    print("-" * 74)
    for row in rows:
        print(f"{row['name'][:52]:<54} {row['pages']:>7,} {row['words_per_page']:>8.0f}")

    ratios = [r["words_per_page"] for r in rows]
    pages = [r["pages"] for r in rows]
    print("-" * 74)
    print(f"books measured       : {len(rows)}")
    print(f"median words/page    : {statistics.median(ratios):.0f}")
    print(f"median pages/book    : {statistics.median(pages):.0f}")
    print(f"mean   pages/book    : {statistics.mean(pages):.0f}")
    print(f"min/max pages        : {min(pages)} / {max(pages)}")
    print(f"total pages measured : {sum(pages):,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
