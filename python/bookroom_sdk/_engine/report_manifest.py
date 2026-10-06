"""Write a non-sensitive, reproducible manifest beside each study guide."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from gemini_provider import MODEL


def write_manifest(report_path: Path, source_path: Path, *, jev_enabled: bool) -> Path:
    report_path = Path(report_path)
    source_path = Path(source_path)
    digest = hashlib.sha256()
    with source_path.open("rb") as source_file:
        for block in iter(lambda: source_file.read(1024 * 1024), b""):
            digest.update(block)
    evaluations_path = report_path.with_name("evaluations.json")
    evaluations = json.loads(evaluations_path.read_text(encoding="utf-8")) if evaluations_path.exists() else {}
    records = evaluations.get("sections", [])
    report_records = evaluations.get("report_sections", [])
    latest = [record.get("attempts", [])[-1] for record in report_records if isinstance(record, dict) and record.get("attempts")]
    passed = sum(bool(attempt.get("passed")) for attempt in latest)
    ocr_records = [record for record in records if isinstance(record, dict) and record.get("ocr_used")]
    confidences = [record.get("ocr_confidence") for record in ocr_records if isinstance(record.get("ocr_confidence"), (int, float))]
    manifest = {
        "schema_version": "1.0",
        "source_file": source_path.name,
        "source_sha256": digest.hexdigest(),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "generation_provider": "Google Gemini API",
        "generation_model": MODEL,
        "jev_evaluation_enabled": jev_enabled,
        "report_section_categories_evaluated": evaluations.get("report_section_count", 0),
        "report_section_categories_passed": passed,
        "report_section_categories_below_threshold": max(0, len(latest) - passed),
        "quality_score_threshold": evaluations.get("threshold"),
        "quality_revision_limit": evaluations.get("max_revisions"),
        "evaluation_records": len(records),
        "ocr_sections": len(ocr_records),
        "mean_ocr_confidence": round(sum(confidences) / len(confidences), 1) if confidences else None,
        "study_guide": report_path.name,
        "chapter_notes": "chapter-notes.md",
        "evaluations": "evaluations.json",
    }
    manifest_path = report_path.with_name("manifest.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest_path
