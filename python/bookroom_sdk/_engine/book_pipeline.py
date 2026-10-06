"""Book extraction and separate, bounded Gemini sessions for each report section."""

import json
import os
from pathlib import Path
import re
from dotenv import load_dotenv
from epub_extractor import extract_epub_content
from pdf_extractor import OCR_ENABLED, OCR_LANGUAGE, extract_pdf_content
from gemini_provider import generate
from report_format import REPORT_SECTIONS, render_report, validate_report

load_dotenv(Path(__file__).with_name(".env"))
PROMPT_VERSION = "2"
MIN_WORD_COUNT = int(os.getenv("MIN_WORD_COUNT", "200"))
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "output"))
MAX_REVISIONS = max(0, min(3, int(os.getenv("JEV_MAX_REVISIONS", "2"))))
QUALITY_THRESHOLD = float(os.getenv("JEV_SCORE_THRESHOLD", "3.5"))
CONFIDENCE_THRESHOLD = float(os.getenv("JEV_CONFIDENCE_THRESHOLD", "0.55"))
JEV_ENABLED = os.getenv("JEV_ENABLED", "false").lower() == "true"
JEV_API_KEY = os.getenv("TYPESAFE_API_KEY", "")
JEV_BASE_URL = os.getenv("JEV_BASE_URL", "https://api.typesafe.ai/v1").rstrip("/")
JEV_MODEL = os.getenv("JEV_MODEL", "jev-latest")
SCORE_CRITERIA = ["0: materially incorrect, unsupported, or unusable", "1: serious unsupported claims or major omissions", "2: mixed quality; important corrections needed", "3: accurate and useful with minor gaps", "4: strongly source-grounded, complete for its purpose, clear, and well structured"]
STOPWORDS = set("a an and are as at be by for from has have in into is it of on or that the this to was were with book chapter section about author their they them these those how what when where which".split())
MAX_SOURCE_CHARS = 24000


def _split_long_sections(sections: list[dict]) -> list[dict]:
    """Bound every source prompt while retaining the complete extracted text."""
    result = []
    for section in sections:
        source = section["source"]
        if len(source) <= MAX_SOURCE_CHARS:
            result.append(section)
            continue
        parts = []
        remaining = source
        while len(remaining) > MAX_SOURCE_CHARS:
            boundary = remaining.rfind(" ", 0, MAX_SOURCE_CHARS + 1)
            if boundary < MAX_SOURCE_CHARS // 2:
                boundary = MAX_SOURCE_CHARS
            parts.append(remaining[:boundary])
            remaining = remaining[boundary:]
            if remaining.startswith(" "):
                remaining = remaining[1:]
        if remaining:
            parts.append(remaining)
        for index, part in enumerate(parts, start=1):
            result.append({**section, "title": f"{section['title']} (part {index} of {len(parts)})",
                           "source": part, "locator": f"{section['locator']}, part {index} of {len(parts)}"})
    return result


def _extract(path: Path, options: dict | None = None) -> list[dict]:
    options = options or {}
    if path.suffix.lower() == ".epub":
        return _split_long_sections([{"title": Path(item.get("filename", "Section")).stem, "source": item["text"], "locator": item.get("filename", "")} for item in extract_epub_content(str(path), MIN_WORD_COUNT)])
    if path.suffix.lower() == ".pdf":
        result = []
        use_ocr = options.get("ocr_enabled", OCR_ENABLED)
        language = options.get("ocr_language", OCR_LANGUAGE)
        for item in extract_pdf_content(str(path), MIN_WORD_COUNT, ocr_enabled=use_ocr, ocr_language=language):
            node = item["node"]
            start = max(1, int(node.page))
            end = int(node.end_page) - 1 if node.end_page else start
            result.append({"title": str(node.get_filename()), "source": item["text"], "locator": f"PDF pages {start}-{max(start, end)}",
                           "ocr_used": bool(item.get("ocr_used")), "ocr_confidence": item.get("ocr_confidence")})
        return _split_long_sections(result)
    raise ValueError("Only EPUB and PDF files are supported; scanned PDFs require OCR to be enabled and Tesseract language data installed")


def _jev_evaluate(title: str, source: str, draft: str) -> dict:
    if not JEV_ENABLED:
        return {"enabled": False, "passed": None, "scores": {}, "focus": "Jev evaluation disabled"}
    if not JEV_API_KEY:
        raise ValueError("JEV_ENABLED=true but TYPESAFE_API_KEY is missing")
    import httpx
    response = httpx.post(f"{JEV_BASE_URL}/systemone", headers={"Authorization": f"Bearer {JEV_API_KEY}"}, json={
        "model": JEV_MODEL, "state": {"section": title, "source_text": source[:24000], "candidate_summary": draft[:16000]},
        "questions": {
            "faithfulness": {"type": "score", "instructions": "Evaluate factual support against only the source; penalize invented specifics.", "criteria": SCORE_CRITERIA},
            "coverage": {"type": "score", "instructions": "Evaluate preservation of central claims and qualifications.", "criteria": SCORE_CRITERIA},
            "clarity": {"type": "score", "instructions": "Evaluate clarity, coherence, concision, and audience fit.", "criteria": SCORE_CRITERIA},
            "structure": {"type": "score", "instructions": "Evaluate organization and usefulness as study notes.", "criteria": SCORE_CRITERIA},
            "revision_focus": {"type": "choice", "instructions": "Choose the most important improvement, or none if it meets a high standard.", "criteria": {"faithfulness": "Unsupported or distorted claim", "coverage": "Important idea missing", "clarity": "Confusing or repetitive", "structure": "Poor organization", "none": "No material revision"}},
        },
    }, timeout=90)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Jev returned an invalid response object")
    answers = payload.get("answers") or {}
    if not isinstance(answers, dict):
        answers = {}
    names = ("faithfulness", "coverage", "clarity", "structure")
    answer_items = {name: answers.get(name) if isinstance(answers.get(name), dict) else {} for name in (*names, "revision_focus")}
    scores = {name: answer_items[name].get("score") for name in names}
    confidence = {name: answer_items[name].get("confidence", 0) for name in names}
    jev_focus = answer_items["revision_focus"].get("choice", "unknown")
    valid = all(isinstance(value, (int, float)) for value in scores.values())
    focus = jev_focus
    if jev_focus == "none" and valid:
        if min(scores.values()) < QUALITY_THRESHOLD:
            focus = min(scores, key=scores.get)
        elif min(confidence.values()) < CONFIDENCE_THRESHOLD:
            focus = min(confidence, key=confidence.get)
    passed = valid and min(scores.values()) >= QUALITY_THRESHOLD and min(confidence.values()) >= CONFIDENCE_THRESHOLD and jev_focus == "none"
    return {"enabled": True, "model": payload.get("model", JEV_MODEL), "scores": scores, "confidence": confidence, "focus": focus, "jev_focus": jev_focus, "passed": passed, "usage": payload.get("usage", {})}


def _preferences(options: dict | None) -> str:
    options = options or {}
    language, level = options.get("language", "English"), options.get("reading_level", "general")
    length, kind = options.get("digest_length", "standard"), options.get("book_type", "auto")
    rules = {"brief": "Be concise; target a five-minute digest.", "standard": "Target a readable ten-minute digest.", "deep": "Give fuller explanations and nuance for a deep dive."}
    return f"Write body text in {language}, preserving required Markdown headings verbatim. Audience level: {level}. {rules.get(length, rules['standard'])} Book type emphasis: {kind}. Source fidelity overrides style."


def _summarize_section(section: dict, options: dict | None = None) -> tuple[str, list[dict]]:
    prefs = _preferences(options)
    prompt = f"""{prefs}
Create concise study notes for this book section. Use only source; preserve qualifications and causal links; paraphrase, do not reproduce long passages. Include a summary, key ideas, useful details/examples, and source locator `{section['locator']}`. Mark inferences clearly.

SECTION: {section['title']}
SOURCE:
{section['source'][:50000]}
"""
    try:
        draft = generate(prompt, temperature=0.2, max_output_tokens=4096)
    except ValueError as exc:
        if "truncated" not in str(exc).lower():
            raise
        compact = f"{prefs}\nSummarize this book section in at most 700 words. Return concise Markdown. Include locator {section['locator']}.\nSection: {section['title']}\nSource:\n{section['source'][:24000]}"
        try:
            draft = generate(compact, temperature=0.15, max_output_tokens=2048)
        except ValueError as retry_exc:
            if "truncated" not in str(retry_exc).lower():
                raise
            draft = f"### Concise source excerpt (automatic fallback; generation was truncated)\n\n{section['source'][:5000]}\n\nSource locator: {section['locator']}"
    history = []
    for attempt in range(MAX_REVISIONS + 1):
        evaluation = _jev_evaluate(section["title"], section["source"], draft)
        history.append({"attempt": attempt + 1, **evaluation})
        if not JEV_ENABLED or evaluation["passed"] or attempt >= MAX_REVISIONS:
            break
        try:
            draft = generate(f"{prefs}\nRevise only this chapter summary using the source. Focus on {evaluation['focus']}; scores: {json.dumps(evaluation['scores'])}. Correct unsupported or missing details, retain important qualifications, and preserve locator {section['locator']}. Return the complete summary in at most 700 words.\nSOURCE:\n{section['source'][:26000]}\nDRAFT:\n{draft[:8000]}", temperature=0.15, max_output_tokens=2048)
        except ValueError as exc:
            if "truncated" not in str(exc).lower():
                raise
            try:
                draft = generate(f"{prefs}\nMake a compact correction to this chapter summary. Focus on {evaluation['focus']}; scores: {json.dumps(evaluation['scores'])}. Use only the source, keep the locator {section['locator']}, and return no more than 400 words.\nSOURCE:\n{section['source'][:8000]}\nSUMMARY:\n{draft[:3000]}", temperature=0.1, max_output_tokens=1024)
                history[-1]["revision_compacted"] = True
            except ValueError as retry_exc:
                if "truncated" not in str(retry_exc).lower():
                    raise
                history[-1]["revision_skipped"] = "Gemini truncated both full and compact chapter revisions; original chapter notes retained."
                break
    return draft, history


def _note_chunks(chapter_notes: str) -> list[tuple[str, str]]:
    chunks = []
    for part in re.split(r"(?m)(?=^## )", chapter_notes):
        if part.strip():
            chunks.append((part.splitlines()[0].removeprefix("## ").strip(), part.strip()))
    return chunks


def _relevant_notes(heading: str, chunks: list[tuple[str, str]], limit: int, *, query_text: str = "") -> str:
    query = {w.lower() for w in re.findall(r"[A-Za-z]{4,}", f"{heading} {query_text}")} - STOPWORDS
    ranked = []
    for title, text in chunks:
        words = set(re.findall(r"[A-Za-z]{4,}", (title + " " + text).lower())) - STOPWORDS
        ranked.append((len(query & words) / max(1, len(query)), title, text))
    chosen, remaining = [], limit
    for score, title, text in sorted(ranked, reverse=True):
        if remaining <= 0:
            break
        part = text[:remaining]
        if len(part) < len(text) and len(part) > 200:
            part = part.rsplit(" ", 1)[0]
        chosen.append((score, title, part))
        remaining -= len(part)
        if len(chosen) >= 8:
            break
    return "\n\n".join(text for _, _, text in sorted(chosen, key=lambda row: row[1]))


def _section_instruction(key: str, heading: str) -> str:
    instructions = {"hook": "One compelling paragraph on the book and why it matters.", "thesis": "Thesis and 3-7 central arguments.", "takeaways": "5-10 actionable takeaways or mental models.", "quotes_anecdotes": "Only short quotes in notes; otherwise label paraphrases.", "argument_flow": "Trace problem, evidence, and solution.", "concept_map": "Nested Markdown bullets showing concepts and relationships.", "actor_theme_map": "Actors/stakeholders or characters, themes, and evidence.", "timeline": "Timeline or process steps; mark not applicable if unsupported.", "glossary": "Key terms with 1-2 sentence definitions.", "faq": "5-8 likely reader questions with concise answers.", "eli15": "Explain difficult ideas simply to a curious 15-year-old.", "critical_questions": "Limits, assumptions, contested claims; no invented criticism.", "application": "Concrete steps and checklists supported by the book.", "further_reading": "Only resources in notes; otherwise state none were identified.", "reflection": "Personal reflection prompts tied to the ideas."}
    return instructions.get(key, f"Produce the requested content for {heading}.")


def _build_digest(title: str, chapter_notes: str, options: dict | None = None, *, fallbacks=None, progress=None,
                  saved_sections=None, on_section_done=None, on_work_unit=None) -> str:
    prefs, chunks, output = _preferences(options), _note_chunks(chapter_notes), []
    requests = [(key, heading) for key, heading in REPORT_SECTIONS if key != "chapter_summaries"]
    for index, (key, heading) in enumerate(requests, start=1):
        if on_work_unit:
            on_work_unit("digest", index)
        if saved_sections and key in saved_sections:
            output.append(f"### {heading}\n{saved_sections[key]}")
            if progress:
                progress(f"Restored digest section {index}/{len(requests)}: {heading}", stage="digest", completed=index, total=len(requests))
            continue
        if progress:
            progress(f"Generating digest section {index}/{len(requests)}: {heading}", stage="digest", completed=index - 1, total=len(requests))
        result, last_error = None, None
        for max_tokens, limit in ((3000, 26000), (1800, 16000), (1000, 9000)):
            context = _relevant_notes(heading, chunks, limit)
            prompt = f"""{prefs}
Write ONLY the content for this one study-guide section; do not emit a heading. Use only the notes and cite chapter titles/page ranges for factual claims where possible. Keep it focused and concise.

Book: {title}
Section: {heading}
Task: {_section_instruction(key, heading)}
Chapter notes:
{context}
"""
            try:
                result = generate(prompt, temperature=0.2, max_output_tokens=max_tokens)
                break
            except ValueError as exc:
                if "truncated" not in str(exc).lower():
                    raise
                last_error = exc
        if result is None:
            context = _relevant_notes(heading, chunks, 4500)
            result = f"_Concise fallback from chapter notes; Gemini truncated this section in three attempts._\n\n{context}"
            if fallbacks is not None:
                fallbacks.append({"section": key, "reason": str(last_error)})
        result = result.strip()
        output.append(f"### {heading}\n{result}")
        if on_section_done:
            on_section_done(key, result)
    return "\n\n".join(output)


def generate_book_report(source_path: str, progress=None) -> Path:
    from resumable_pipeline import generate_resumable_report
    return generate_resumable_report(source_path, progress=progress)
