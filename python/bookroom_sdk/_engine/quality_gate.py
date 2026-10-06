"""Independently evaluate every whole-book section; retain reports on revision truncation."""

import json
import hashlib
from pathlib import Path
from book_pipeline import REPORT_SECTIONS, _jev_evaluate, _note_chunks, _relevant_notes, MAX_REVISIONS, JEV_ENABLED
from gemini_provider import generate
from report_format import validate_report
from resumable_pipeline import JobCancelled


def _aggregate_chapter_reviews(chapters: list[dict]) -> dict:
    """Represent the full chapter-summaries category using every chapter's Jev result."""
    if not chapters or any(not isinstance(chapter, dict) or not chapter.get("attempts") for chapter in chapters):
        raise ValueError("Full chapter-summaries review requires a Jev result for every source part.")
    final = [chapter["attempts"][-1] for chapter in chapters]
    if any(not item.get("enabled") for item in final):
        raise ValueError("Full chapter-summaries review requires Jev to be enabled for every source part.")
    names = ("faithfulness", "coverage", "clarity", "structure")
    scores = {name: min(float(item.get("scores", {}).get(name, 0) or 0) for item in final) for name in names}
    confidence = {name: min(float(item.get("confidence", {}).get(name, 0) or 0) for item in final) for name in names}
    passed = all(item.get("passed") is True for item in final)
    focus = next((item.get("focus", "unknown") for item in final if not item.get("passed")), "none")
    return {"enabled": True, "passed": passed, "scores": scores, "confidence": confidence,
            "focus": focus, "jev_focus": "none" if passed else focus, "usage": {},
            "evaluation_scope": "all_source_parts", "source_parts_reviewed": len(final),
            "revision_skipped": "Individual source parts were already revised and evaluated by Jev." if not passed else None}


def _atomic_text(path: Path, content: str) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(content, encoding="utf-8")
    temp.replace(path)


def _atomic_json(path: Path, data: dict) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def _revision_prompt(heading: str, source: str, current: str, evaluation: dict, *, compact=False) -> str:
    source_cap, current_cap = (6000, 2500) if compact else (12000, 5000)
    word_limit = 100 if compact else 180
    return f"""Revise only the {heading} section using the Jev evaluation. Scores are 0-4; prioritize {evaluation.get('focus', 'the lowest dimension')}. Improve the identified weakness while retaining useful supported content. Use only the chapter-note evidence below; never invent quotes, people, books, or facts. Preserve 'Not applicable' if warranted. Return only the complete revised section body, with no heading, in at most {word_limit} words and with no trailing whitespace.

Scores: {json.dumps(evaluation.get('scores', {}))}
Confidence: {json.dumps(evaluation.get('confidence', {}))}
Chapter notes (evidence):
{source[:source_cap]}
Current section:
{current[:current_cap]}
"""


def evaluate_and_revise_report(report_path: Path, *, progress=None, should_cancel=None, on_work_unit=None) -> list[dict]:
    report_path = Path(report_path)
    source_path = report_path.with_name("chapter-notes.md")
    evaluation_path = report_path.with_name("evaluations.json")
    source = source_path.read_text(encoding="utf-8")
    chunks = _note_chunks(source)
    state = json.loads(evaluation_path.read_text(encoding="utf-8")) if evaluation_path.exists() else {}
    records = state.setdefault("report_sections", [])
    completed = {record.get("section_key"): record for record in records if isinstance(record, dict)}
    heading_lines = {f"## {heading}" for _, heading in REPORT_SECTIONS}

    for index, (key, heading) in enumerate(REPORT_SECTIONS, start=1):
        if should_cancel and should_cancel():
            raise JobCancelled("Cancelled after saving completed evaluations.")
        if on_work_unit:
            on_work_unit("report_review", index)
        report = report_path.read_text(encoding="utf-8")
        lines = report.splitlines(keepends=True)
        target = f"## {heading}"
        try:
            start = next(i for i, line in enumerate(lines) if line.rstrip("\r\n") == target)
        except StopIteration as exc:
            raise ValueError(f"Required report section is missing and cannot be evaluated: {heading}") from exc
        end = next((i for i in range(start + 1, len(lines)) if lines[i].rstrip("\r\n") in heading_lines), len(lines))
        current = "".join(lines[start + 1:end]).strip()
        evidence = _relevant_notes(heading, chunks, 24000, query_text=current) or source[:24000]
        aggregate_chapters = key == "chapter_summaries" and len(current) > 16000 and JEV_ENABLED
        evidence_hash = hashlib.sha256((source + current if aggregate_chapters else evidence).encode("utf-8")).hexdigest()
        previous = completed.get(key)
        previous_attempts = previous.get("attempts", []) if previous else []
        previous_passed = bool(previous_attempts and previous_attempts[-1].get("passed"))
        if previous and previous.get("evidence_sha256") == evidence_hash and previous_passed:
            if progress:
                progress(f"Jev review already saved for {heading} with matching evidence.", stage="quality_gate", completed=index, total=len(REPORT_SECTIONS))
            continue
        history = []
        if aggregate_chapters:
            history.append({"attempt": 1, **_aggregate_chapter_reviews(state.get("sections", []))})
        for attempt in range(0 if aggregate_chapters else MAX_REVISIONS + 1):
            evaluation = _jev_evaluate(heading, evidence, current)
            history.append({"attempt": attempt + 1, **evaluation})
            if not JEV_ENABLED or evaluation.get("passed") or attempt >= MAX_REVISIONS:
                break
            if len(current) > 12000:
                history[-1]["revision_skipped"] = "Section exceeds the safe one-session revision size; its source chapters were evaluated individually and the complete content was preserved."
                break
            try:
                current = generate(_revision_prompt(heading, evidence, current, evaluation), temperature=0.15, max_output_tokens=768)
            except ValueError as exc:
                if "truncated" not in str(exc).lower():
                    raise
                try:
                    current = generate(_revision_prompt(heading, evidence, current, evaluation, compact=True), temperature=0.1, max_output_tokens=512)
                except ValueError as retry_exc:
                    if "truncated" not in str(retry_exc).lower():
                        raise
                    history[-1]["revision_skipped"] = "Gemini truncated both full and compact revision attempts; original section retained."
                    break
            # Some revisions echo the section heading despite asking for body
            # text only. Keep the canonical heading from the report template.
            current = "\n".join(line for line in current.splitlines() if line.rstrip() not in heading_lines)
        current = "\n".join(line.rstrip() for line in current.splitlines()).strip()
        replacement = ["\n", current + "\n"] if current else ["\n"]
        report = "".join(lines[:start + 1] + replacement + lines[end:])
        errors = validate_report(report)
        if errors:
            raise ValueError("Jev revision broke report formatting: " + "; ".join(errors))
        _atomic_text(report_path, report)
        records[:] = [record for record in records if record.get("section_key") != key]
        record = {"section_key": key, "section": heading, "evidence_sha256": evidence_hash, "attempts": history}
        records.append(record)
        completed[key] = record
        state["report_section_categories_processed"] = len(records)
        state["report_section_count"] = sum(any(attempt.get("enabled") is True for attempt in record["attempts"]) for record in records)
        state["revision_truncation_fallbacks"] = sum(bool(attempt.get("revision_skipped")) for record in records for attempt in record["attempts"])
        _atomic_json(evaluation_path, state)
        if progress:
            progress(f"Jev reviewed {heading} ({index}/{len(REPORT_SECTIONS)}).", stage="quality_gate", completed=index, total=len(REPORT_SECTIONS))
    return records
