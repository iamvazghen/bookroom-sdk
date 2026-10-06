"""Derive the time-savings model published in the README.

Every number in the README's "Results" section comes from this script, so it can
be re-run and checked rather than trusted. The corpus statistics are measured
from real books by ``measure_books.py``; only the reading speed and the digest
time are assumptions, and both are stated.

Run:  python tools/time_model.py
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# Measured, not assumed. From tools/measure_books.py over 25 real books
# (8,170 pages): median 321 words per page, median 257 pages per book.
# --------------------------------------------------------------------------
WORDS_PER_PAGE = 321.0
MEDIAN_PAGES_PER_BOOK = 257.0

# Assumptions, stated openly.
READING_WPM = 250          # adult, non-fiction, silent reading
DIGEST_MINUTES = 10        # the engine's own design target: a ten-minute digest
REVIEW_MINUTES = 10        # skimming the notes, concept map and claim audit
PAGES_PER_DAY = 10
DAYS_PER_YEAR = 365


def read_minutes(pages: float, wpm: float = READING_WPM) -> float:
    return pages * WORDS_PER_PAGE / wpm


def model(label: str, pages: float, wpm: float) -> dict:
    reading = read_minutes(pages, wpm)
    saved_per_book = reading - DIGEST_MINUTES - REVIEW_MINUTES
    books_per_year = (PAGES_PER_DAY * DAYS_PER_YEAR) / pages
    saved_per_year = saved_per_book * books_per_year
    return {
        "label": label,
        "pages": pages,
        "wpm": wpm,
        "words": pages * WORDS_PER_PAGE,
        "read_min": reading,
        "bookroom_min": DIGEST_MINUTES + REVIEW_MINUTES,
        "saved_book_min": saved_per_book,
        "books_year": books_per_year,
        "saved_year_min": saved_per_year,
    }


def hours(value: float) -> float:
    return value / 60.0


def main() -> int:
    pages_per_year = PAGES_PER_DAY * DAYS_PER_YEAR
    print("=" * 78)
    print("BOOKROOM TIME-SAVINGS MODEL")
    print("=" * 78)
    print(f"words per page (measured, 25 books) : {WORDS_PER_PAGE:.0f}")
    print(f"pages per book  (measured, median)   : {MEDIAN_PAGES_PER_BOOK:.0f}")
    print(f"reading speed   (assumption)         : {READING_WPM} words/min")
    print(f"bookroom time   (assumption)         : {DIGEST_MINUTES} min digest "
          f"+ {REVIEW_MINUTES} min review")
    print(f"reading habit                      : {PAGES_PER_DAY} pages/day "
          f"x {DAYS_PER_YEAR} days = {pages_per_year:,} pages/year")
    print()

    scenarios = [
        model("short book, fast reader", 150, 300),
        model("median book, average reader", MEDIAN_PAGES_PER_BOOK, READING_WPM),
        model("long book, careful reader", 500, 200),
    ]

    header = (f"{'scenario':<30}{'pages':>6}{'read':>9}{'bookroom':>10}"
              f"{'saved/book':>12}{'books/yr':>10}{'saved/yr':>11}")
    print(header)
    print("-" * len(header))
    for row in scenarios:
        print(f"{row['label']:<30}{row['pages']:>6.0f}"
              f"{hours(row['read_min']):>8.1f}h{hours(row['bookroom_min']):>9.0f}m"
              f"{hours(row['saved_book_min']):>11.1f}h{row['books_year']:>10.1f}"
              f"{hours(row['saved_year_min']):>10.0f}h")
    print()

    mid = scenarios[1]
    print("=" * 78)
    print("HEADLINE (median book, average reader)")
    print("=" * 78)
    print(f"words in a median book        : {mid['words']:,.0f}")
    print(f"time to read it              : {hours(mid['read_min']):.1f} hours "
          f"({mid['read_min']:.0f} minutes)")
    print(f"time with Bookroom           : {mid['bookroom_min']:.0f} minutes")
    print(f"time saved per book          : {hours(mid['saved_book_min']):.1f} hours "
          f"({mid['saved_book_min']:.0f} minutes)")
    print()
    print(f"pages read per year           : {pages_per_year:,}")
    print(f"books per year at this habit  : {mid['books_year']:.1f}")
    print(f"time saved per year          : {hours(mid['saved_year_min']):.0f} hours")
    print(f"  as working days (8h)       : {hours(mid['saved_year_min']) / 8:.1f} days")
    print(f"  as calendar days (24h)     : {hours(mid['saved_year_min']) / 24:.1f} days")
    print()
    print("Scope of the claim: this is *replacement* time - the time you would")
    print("have spent reading a book you now only need summarised. It is not a")
    print("claim that you never read. Coverage is the larger benefit: the same")
    print("14 books a year leave behind a structured, searchable artifact rather")
    print("than a fading impression.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
