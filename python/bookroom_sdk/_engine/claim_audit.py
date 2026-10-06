"""Create a transparent lexical evidence trace for report claims.

This is a review aid, not semantic fact verification: lexical overlap cannot prove a
claim true and a low-overlap claim is marked for human review, never auto-rejected.
"""

import re
from collections import Counter

STOP = set("a an and are as at be been but by can could did do does for from had has have how i if in into is it its may might of on or our should that the their them then there these this those to was were what when where which who will with would you your".split())
INFERENCE = re.compile(r"\b(i infer|we infer|may suggest|might suggest|likely|perhaps|it seems|possibly|could indicate)\b", re.I)


def _terms(text: str) -> Counter:
    return Counter(word for word in re.findall(r"[a-zA-Z0-9]{3,}", text.lower()) if word not in STOP)


def _chapters(chapter_notes: str) -> list[dict]:
    blocks = re.split(r"(?m)^##\s+", chapter_notes)
    result = []
    for block in blocks:
        lines = block.splitlines()
        if not lines:
            continue
        title = lines[0].strip()
        loc = re.search(r"(?m)^\*\*Source locator:\*\*\s*(.+)$", block)
        content = re.sub(r"(?m)^\*\*Source locator:\*\*.*$", "", "\n".join(lines[1:])).strip()
        result.append({"title": title, "locator": loc.group(1).strip() if loc else "Unavailable", "text": content, "terms": _terms(content)})
    return result


def audit_claims(report_markdown: str, chapter_notes: str, *, min_overlap: float = 0.18) -> dict:
    sources = _chapters(chapter_notes)
    claims = []
    section = ""
    in_chapters = False
    for line in report_markdown.splitlines():
        heading = re.match(r"^##\s+(.+)$", line)
        if heading:
            section = heading.group(1)
            in_chapters = section == "Chapter-by-Chapter Summaries"
            continue
        if in_chapters or not line.strip() or line.startswith(("#", ">", "|")):
            continue
        for sentence in re.split(r"(?<=[.!?])\s+", line.strip().lstrip("-* ")):
            sentence = sentence.strip()
            terms = _terms(sentence)
            if len(terms) < 4:
                continue
            best, best_score = None, 0.0
            for source in sources:
                shared = sum((terms & source["terms"]).values())
                score = shared / max(1, sum(terms.values()))
                if score > best_score:
                    best, best_score = source, score
            inferred = bool(INFERENCE.search(sentence))
            claims.append({"section": section, "claim": sentence, "status": "explicit_inference" if inferred else "source_overlap_found" if best_score >= min_overlap else "low_overlap_review",
                           "lexical_overlap": round(best_score, 3), "evidence_locator": best["locator"] if best else None,
                           "evidence_section": best["title"] if best else None,
                           "review_note": "Lexical match is not proof of support; inspect source and claim."})
    return {"schema_version": "1.0", "method": "sentence-level lexical overlap against chapter notes; not semantic verification",
            "claim_count": len(claims), "source_section_count": len(sources), "claims": claims}
