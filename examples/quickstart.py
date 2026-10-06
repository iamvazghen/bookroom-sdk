"""End-to-end example: one book, every artifact.

    python examples/quickstart.py book.epub

The only credentials required are the LLM key and the JEv key.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Run straight from a checkout without installing.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

from bookroom_sdk import Bookroom, errors  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python quickstart.py <book.epub|book.pdf>")
        return 2
    source = Path(sys.argv[1])
    if not source.is_file():
        print(f"no such file: {source}")
        return 2

    # The only two credentials. In your own code these would be your real keys
    # or, better, entries in a secret manager.
    llm_api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("BOOKROOM_LLM_API_KEY")
    if not llm_api_key:
        print("set GEMINI_API_KEY (or BOOKROOM_LLM_API_KEY) first")
        return 2
    jev_api_key = os.environ.get("TYPESAFE_API_KEY") or os.environ.get("BOOKROOM_JEV_API_KEY")

    # 1. Only the two keys. Every endpoint, model and threshold has a default;
    #    pass any of them to override:
    #
    #        room = Bookroom(
    #            llm_api_key=llm_api_key,
    #            jev_api_key=jev_api_key,
    #            llm_base_url="https://your-proxy.internal/v1beta",  # optional
    #        )
    #
    # Here we read the same settings from the environment, which is what you
    # want in a deployed service. The LLM and JEv keys are the only things the
    # environment has to contain.
    room = Bookroom.from_env(llm_api_key=llm_api_key, jev_api_key=jev_api_key)

    # 2. Confirm the credentials before spending anything.
    health = room.check()
    print(f"llm    : {health.llm.get('status')} ({health.llm.get('model')})")
    print(f"review : {health.review.get('status')} ({health.review.get('model')})")
    if not health.ok:
        print("credentials are not ready; stopping before a paid run")
        return 1

    # 3. See what it will cost before running it.
    plan = room.summarize.preflight(source)
    print(f"\nsections        : {plan.section_count}")
    print(f"work batches    : {plan.batch_count}")
    print(f"llm input tokens: {plan.estimated_llm_input_tokens:,} (estimate)")
    print(f"review credits  : {plan.estimated_jev_credits:,} (worst case)")

    # 4. Run the whole job: notes, digest, JEv review on all 16
    #    categories, and every export.
    try:
        report = room.summarize.study_guide(
            source,
            progress=lambda message, **kw: print(f"  ... {message}"),
        )
    except errors.QuotaError as exc:
        print(f"\nquota reached; wait {exc.retry_after_seconds}s and re-run to resume")
        return 1
    except errors.BookroomError as exc:
        print(f"\n{type(exc).__name__}: {exc}")
        return 1

    print(f"\nreport     : {report.markdown.path}")
    print(f"pdf        : {report.pdf.path if report.pdf else 'not produced'}")
    print(f"output dir : {report.output_dir}")

    if report.quality:
        quality = report.quality
        print(f"\nreview     : {quality.categories_passed}/{quality.categories_reviewed} "
              f"categories at or above {quality.threshold}")
        for section, focus in list(quality.focus.items())[:5]:
            print(f"  {section}: {focus}")

    print("\nartifacts:")
    for artifact in report.artifacts:
        size = Path(artifact.path).stat().st_size if artifact.exists() else 0
        print(f"  {artifact.name:<20} {artifact.media_type:<24} {size:,} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
