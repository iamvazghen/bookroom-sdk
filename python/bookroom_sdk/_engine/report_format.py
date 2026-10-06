"""Canonical Markdown report layout and deterministic format checks."""

from datetime import datetime, timezone
import re
from typing import Mapping


REPORT_SECTIONS = (
    ("hook", "The Book in One Paragraph"),
    ("thesis", "Thesis and Core Arguments"),
    ("chapter_summaries", "Chapter-by-Chapter Summaries"),
    ("takeaways", "Top Takeaways"),
    ("quotes_anecdotes", "Quotes and Anecdotes"),
    ("argument_flow", "Argument Flow"),
    ("concept_map", "Concept Map"),
    ("actor_theme_map", "Actors and Themes"),
    ("timeline", "Timeline or Process Map"),
    ("glossary", "Glossary"),
    ("faq", "Reader Questions and Answers"),
    ("eli15", "Explain It Simply"),
    ("critical_questions", "Critical Questions and Limitations"),
    ("application", "How to Apply the Book"),
    ("further_reading", "Further Reading"),
    ("reflection", "Personal Reflection Prompts"),
)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9 -]", "", text.lower()).strip().replace(" ", "-")


def display_title(text: str) -> str:
    """Turn upload-derived identifiers into a clean, human-facing title."""
    value = str(text).strip()
    value = re.sub(r"^[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}__", "", value)
    value = re.sub(r"^_*OceanofPDF\.com_*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\.(pdf|epub)$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"_+", " ", value)
    value = re.sub(r"\s+", " ", value).strip(" _-")
    value = re.sub(r"\s+-\s+", ": ", value)
    return value or "Untitled Book"


def clean_heading(text: str) -> str:
    """Remove extraction IDs and filename punctuation from chapter headings."""
    value = str(text).strip()
    had_extraction_prefix = bool(re.match(r"^\d{3}_", value))
    value = re.sub(r"^\d{3}_", "", value)
    if "_" in value:
        value = value.replace("_", " ")
        value = re.sub(r"\s+", " ", value).strip()
        value = value.title()
    elif had_extraction_prefix and value:
        value = value[0].upper() + value[1:]
    return value


def render_report(
    title: str,
    sections: Mapping[str, str],
    *,
    author: str = "Unknown author",
    source_name: str = "Unknown source",
    model: str = "gemini-3.8-flash",
    generated_at: datetime | None = None,
) -> str:
    """Render a complete, consistently ordered Markdown study guide."""
    timestamp = generated_at or datetime.now(timezone.utc)
    lines = [
        f"# {display_title(title)} — Study Guide",
        "",
        f"**Author:** {author}",
        f"**Source:** {source_name}",
        f"**Generated:** {timestamp.astimezone(timezone.utc).isoformat()}",
        f"**Model:** `{model}`",
        "",
        "> AI-generated study aid. Verify important claims against the cited source locations.",
        "",
        "## Contents",
    ]
    for _, heading in REPORT_SECTIONS:
        lines.append(f"- [{heading}](#{_slug(heading)})")
    lines.append("")
    for key, heading in REPORT_SECTIONS:
        raw_body = sections.get(key, "").strip()
        body = "\n".join(line.rstrip() for line in raw_body.splitlines())
        lines.extend((f"## {heading}", "", body or "_Not generated._", ""))
    return "\n".join(lines).rstrip() + "\n"


def validate_report(markdown: str) -> list[str]:
    """Return Markdown layout problems; [] means all deterministic checks pass."""
    errors = []
    if not markdown.strip().startswith("# "):
        errors.append("Report must start with a level-one title")
    headings = re.findall(r"^## (.+)$", markdown, flags=re.MULTILINE)
    for _, heading in REPORT_SECTIONS:
        if headings.count(heading) != 1:
            errors.append(f"Expected exactly one '## {heading}' heading")
    for line_number, line in enumerate(markdown.splitlines(), start=1):
        if line.rstrip() != line:
            errors.append(f"Trailing whitespace on line {line_number}")
    anchors = {_slug(heading) for heading in headings}
    for target in re.findall(r"\]\(#([^)]*)\)", markdown):
        if target not in anchors:
            errors.append(f"Contents link points to missing heading: #{target}")
    return errors
