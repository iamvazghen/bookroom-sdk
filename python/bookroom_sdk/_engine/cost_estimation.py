"""Conservative provider estimates and bounded work-batch planning."""

import math
import os
from book_pipeline import MAX_REVISIONS, REPORT_SECTIONS


def estimate_usage(sections: list[dict]) -> dict:
    count = len(sections)
    source_chars = sum(len(section.get("source", "")) for section in sections)
    chapter_note_chars = max(1200 * count, int(source_chars * 0.22))
    section_calls = len(REPORT_SECTIONS) - 1
    revisions = MAX_REVISIONS
    units = []
    for index, section in enumerate(sections, start=1):
        length = len(section.get("source", ""))
        chapter_chars = length + max(1200, int(length * 0.22)) + revisions * (
            min(length, 42000) + min(int(length * 0.2), 16000))
        jev_bytes = min(length, 24000) + min(int(length * 0.2), 16000) + 3200
        units.append({"kind": "chapter", "index": index,
                      "gemini_input_tokens_estimate": math.ceil(chapter_chars / 4),
                      "jev_credits_estimate_worst_case": 5 * math.ceil(jev_bytes / 4096) * (1 + revisions)})
    for index in range(1, section_calls + 1):
        context = min(chapter_note_chars, 26000)
        digest_chars = context + 18000 + revisions * (context + 9000)
        units.append({"kind": "digest", "index": index,
                      "gemini_input_tokens_estimate": math.ceil(digest_chars / 4),
                      "jev_credits_estimate_worst_case": 0})
    for index in range(1, len(REPORT_SECTIONS) + 1):
        review_bytes = min(chapter_note_chars, 24000) + 5000 + 3200
        units.append({"kind": "report_review", "index": index,
                      "gemini_input_tokens_estimate": math.ceil(revisions * 18000 / 4),
                      "jev_credits_estimate_worst_case": 5 * math.ceil(review_bytes / 4096) * (1 + revisions)})
    return {
        "section_count": count, "source_characters": source_chars,
        "gemini_input_tokens_estimate": sum(unit["gemini_input_tokens_estimate"] for unit in units),
        "gemini_calls_worst_case": count + section_calls + revisions * (count + section_calls + len(REPORT_SECTIONS)),
        "digest_section_calls": section_calls,
        "jev_requests_worst_case": (count + len(REPORT_SECTIONS)) * (1 + revisions),
        "jev_questions_per_request": 5,
        "jev_credits_estimate_worst_case": sum(unit["jev_credits_estimate_worst_case"] for unit in units),
        "jev_credit_basis": "5 typed questions per request times ceil(estimated request bytes / 4096); retries assume every item needs each allowed revision.",
        "revision_rounds": revisions, "work_units": units,
    }


def enforce_budget(estimate: dict) -> None:
    """Plan sequential batches; caps apply to each batch, never silently to a single unit."""
    max_gemini = int(os.getenv("MAX_ESTIMATED_GEMINI_INPUT_TOKENS", "1500000"))
    max_jev = int(os.getenv("MAX_ESTIMATED_JEV_CREDITS", "12000"))
    if max_gemini <= 0 or max_jev <= 0:
        raise ValueError("Estimated provider batch caps must be positive integers.")
    units = estimate.get("work_units") or [{"kind": "book", "index": 1,
        "gemini_input_tokens_estimate": estimate["gemini_input_tokens_estimate"],
        "jev_credits_estimate_worst_case": estimate["jev_credits_estimate_worst_case"]}]
    batches = []
    current = {"units": [], "gemini_input_tokens_estimate": 0, "jev_credits_estimate_worst_case": 0}
    for unit in units:
        gemini = unit["gemini_input_tokens_estimate"]
        jev = unit["jev_credits_estimate_worst_case"]
        if gemini > max_gemini or jev > max_jev:
            limit = "Gemini input tokens" if gemini > max_gemini else "Jev credits"
            raise ValueError(f"One {unit['kind']} work unit exceeds the configured per-batch {limit} cap; split the source section or adjust the cap.")
        if current["units"] and (current["gemini_input_tokens_estimate"] + gemini > max_gemini or
                                 current["jev_credits_estimate_worst_case"] + jev > max_jev):
            batches.append(current)
            current = {"units": [], "gemini_input_tokens_estimate": 0, "jev_credits_estimate_worst_case": 0}
        current["units"].append({"kind": unit["kind"], "index": unit["index"]})
        current["gemini_input_tokens_estimate"] += gemini
        current["jev_credits_estimate_worst_case"] += jev
    if current["units"]:
        batches.append(current)
    estimate["batches"] = batches
    estimate["batch_count"] = len(batches)
    estimate["batch_gemini_input_token_cap"] = max_gemini
    estimate["batch_jev_credit_cap"] = max_jev
