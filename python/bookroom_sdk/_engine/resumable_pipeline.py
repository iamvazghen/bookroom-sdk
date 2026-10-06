"""Checkpointed generation so a book survives retries and app restarts."""

import hashlib
import json
import os
from pathlib import Path
import re
import book_pipeline as pipeline
from report_format import display_title


class JobCancelled(Exception):
    """Raised between provider operations after saving completed work."""


def _atomic_json(path: Path, data: dict) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def _atomic_text(path: Path, text: str) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(text, encoding="utf-8")
    temp.replace(path)


def generate_resumable_report(source_path: str, *, options=None, progress=None, should_cancel=None, on_work_unit=None) -> Path:
    source_path = Path(source_path)
    options = options or {}
    sections = pipeline._extract(source_path, options=options)
    if not sections:
        raise ValueError("No sections met the minimum word count. Try lowering MIN_WORD_COUNT or use another file.")
    storage_name = source_path.stem
    title = display_title(storage_name)
    author = "Unknown author"
    if source_path.suffix.lower() == ".pdf":
        try:
            import pymupdf as fitz  # preferred name; the `fitz` alias warns on import
        except ImportError:  # pragma: no cover - very old PyMuPDF
            import fitz
        try:
            with fitz.open(source_path) as source_pdf:
                metadata = source_pdf.metadata or {}
            if metadata.get("title", "").strip():
                title = display_title(metadata["title"])
            if metadata.get("author", "").strip():
                author = metadata["author"].strip()
        except Exception:
            # Metadata is optional; a cleaned filename remains a reliable fallback.
            pass
    slug = options.get("output_slug") or re.sub(r"[^A-Za-z0-9._-]+", "_", storage_name).strip("._") or "book"
    output_dir = Path(os.getenv("OUTPUT_DIR", "output")) / slug
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_path = output_dir / ".pipeline-cache.json"
    source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    cache = {}
    if cache_path.exists():
        try:
            prior = json.loads(cache_path.read_text(encoding="utf-8"))
            if prior.get("source_sha256") == source_hash and prior.get("options", {}) == options:
                cache = prior
        except (OSError, json.JSONDecodeError):
            cache = {}
    if not cache:
        cache = {"source_sha256": source_hash, "options": options, "chapter_notes": {}, "digest": None}
    digest_count = len(pipeline.REPORT_SECTIONS) - 1
    total = len(sections) + digest_count + len(pipeline.REPORT_SECTIONS)
    if progress:
        progress("Extracted book structure.", stage="extract", completed=0, total=total)
    note_lines, chapter_eval_records = [], []
    for index, section in enumerate(sections, start=1):
        if should_cancel and should_cancel():
            raise JobCancelled("Cancelled after saving completed section work.")
        if on_work_unit:
            on_work_unit("chapter", index)
        identity = hashlib.sha256((pipeline.PROMPT_VERSION + "\0" + section["locator"] + "\0" + section["source"] + "\0" + json.dumps(options, sort_keys=True)).encode("utf-8")).hexdigest()
        saved = cache["chapter_notes"].get(identity)
        if saved:
            note, history = saved["note"], saved["evaluations"]
        else:
            if progress:
                progress(f"Summarizing chapter {index}/{len(sections)}: {section['title']}", stage="chapter_summaries", completed=index - 1, total=total)
            note, history = pipeline._summarize_section(section, options=options)
            cache["chapter_notes"][identity] = {"title": section["title"], "locator": section["locator"], "note": note, "evaluations": history}
            _atomic_json(cache_path, cache)
        confidence = section.get("ocr_confidence")
        confidence_note = f" Average word confidence: {confidence:.1f}/100." if isinstance(confidence, (int, float)) else " Confidence was unavailable."
        ocr_note = f"\n**Text extraction:** Tesseract OCR.{confidence_note} Verify recognized names and numbers against the page image." if section.get("ocr_used") else ""
        note_lines.append(f"## {section['title']}\n\n**Source locator:** {section['locator'] or 'Unavailable'}{ocr_note}\n\n{note}")
        chapter_eval_records.append({"section": section["title"], "locator": section["locator"],
                                     "ocr_used": bool(section.get("ocr_used")), "ocr_confidence": section.get("ocr_confidence"),
                                     "attempts": history})
        _atomic_text(output_dir / "partial-chapter-notes.md", "\n\n".join(note_lines))
        if progress:
            progress(f"Finished chapter {index}/{len(sections)}: {section['title']}", stage="chapter_summaries", completed=index, total=total)
    chapter_notes = "\n\n".join(note_lines)
    _atomic_text(output_dir / "chapter-notes.md", chapter_notes)
    if should_cancel and should_cancel():
        raise JobCancelled("Cancelled after saving completed chapter notes.")
    digest_key = hashlib.sha256((pipeline.PROMPT_VERSION + "\0" + chapter_notes + json.dumps(options, sort_keys=True)).encode("utf-8")).hexdigest()
    digest_cache = cache.get("digest") or {}
    digest = digest_cache.get("content") if digest_cache.get("key") == digest_key else None
    if not digest:
        if progress:
            progress("Generating digest sections independently.", stage="digest", completed=len(sections), total=total)
        fallbacks = list(digest_cache.get("fallback_sections", [])) if digest_cache.get("key") == digest_key else []
        saved_sections = dict(digest_cache.get("sections", {})) if digest_cache.get("key") == digest_key else {}

        def save_digest_section(key: str, content: str) -> None:
            saved_sections[key] = content
            cache["digest"] = {"key": digest_key, "sections": saved_sections, "fallback_sections": fallbacks}
            _atomic_json(cache_path, cache)

        digest = pipeline._build_digest(title, chapter_notes, options=options, fallbacks=fallbacks,
                                        progress=(lambda msg, stage="digest", completed=0, total=1: progress(msg, stage=stage, completed=len(sections) + completed, total=len(sections) + digest_count + len(pipeline.REPORT_SECTIONS))) if progress else None,
                                        saved_sections=saved_sections, on_section_done=save_digest_section,
                                        on_work_unit=on_work_unit)
        cache["digest"] = {"key": digest_key, "content": digest, "sections": saved_sections, "fallback_sections": fallbacks}
        _atomic_json(cache_path, cache)
    generated = {}
    for key, heading in pipeline.REPORT_SECTIONS:
        if key == "chapter_summaries":
            generated[key] = chapter_notes
        else:
            target = "The Book in One Paragraph" if key == "hook" else heading
            match = re.search(rf"###\s+{re.escape(target)}\s*\n(.*?)(?=\n###\s+|\Z)", digest, re.S)
            generated[key] = match.group(1).strip() if match else ""
    source_label = f"{title}{source_path.suffix.lower()}"
    report = pipeline.render_report(title, generated, author=author, source_name=source_label)
    errors = pipeline.validate_report(report)
    if errors:
        raise ValueError("Generated report failed format validation: " + "; ".join(errors))
    report_path = output_dir / "study-guide.md"
    _atomic_text(report_path, report)
    evaluation_path = output_dir / "evaluations.json"
    existing = {}
    if evaluation_path.exists():
        try:
            existing = json.loads(evaluation_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    existing.update({"enabled": pipeline.JEV_ENABLED, "threshold": pipeline.QUALITY_THRESHOLD, "max_revisions": pipeline.MAX_REVISIONS,
                     "sections": chapter_eval_records, "format_errors": [], "digest_fallback_sections": (cache.get("digest") or {}).get("fallback_sections", [])})
    existing.setdefault("report_sections", [])
    _atomic_json(evaluation_path, existing)
    if progress:
        progress("Whole-book report saved; Jev category review is next.", stage="quality_gate", completed=len(sections) + digest_count, total=total)
    return report_path
