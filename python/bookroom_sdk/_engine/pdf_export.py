"""Render the canonical Markdown study guide as a complete, Unicode PDF."""

from pathlib import Path
import re

from bs4 import BeautifulSoup, NavigableString, Tag
from markdown import markdown
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import HRFlowable, ListFlowable, ListItem, PageBreak, Paragraph, Preformatted, SimpleDocTemplate, Spacer, Table, TableStyle

from report_format import REPORT_SECTIONS, clean_heading, display_title, validate_report


def _register_fonts() -> tuple[str, str, str, str]:
    font_dir = Path(r"C:\Windows\Fonts")
    regular, bold, italic, bold_italic = (font_dir / name for name in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"))
    if regular.is_file() and bold.is_file() and italic.is_file():
        for name, path in (("BookArial", regular), ("BookArial-Bold", bold), ("BookArial-Italic", italic)):
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(name, str(path)))
        if bold_italic.is_file() and "BookArial-BoldItalic" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("BookArial-BoldItalic", str(bold_italic)))
        pdfmetrics.registerFontFamily("BookArial", normal="BookArial", bold="BookArial-Bold", italic="BookArial-Italic", boldItalic="BookArial-BoldItalic" if bold_italic.is_file() else "BookArial-Bold")
        return "BookArial", "BookArial-Bold", "BookArial-Italic", "BookArial"
    return "Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Helvetica"


def _inline(node) -> str:
    if isinstance(node, NavigableString):
        from xml.sax.saxutils import escape
        return escape(str(node))
    if not isinstance(node, Tag):
        return ""
    content = "".join(_inline(child) for child in node.children)
    name = node.name.lower()
    if name in ("strong", "b"):
        return f"<b>{content}</b>"
    if name in ("em", "i"):
        return f"<i>{content}</i>"
    if name == "code":
        return f'<font name="Courier">{content}</font>'
    if name == "br":
        return "<br/>"
    if name == "a":
        href = node.get("href", "")
        if href.startswith("#"):
            return content
        if href.startswith(("https://", "http://")):
            from xml.sax.saxutils import quoteattr
            return f"<link href={quoteattr(href)} color='#111111' underline='1'>{content}</link>"
        return content
    return content


def _styles():
    regular, bold, italic, code = _register_fonts()
    base = getSampleStyleSheet()
    ink, muted, rule, paper = (colors.HexColor(value) for value in ("#111111", "#666666", "#D8D8D8", "#F5F5F5"))
    body = ParagraphStyle("BookBody", parent=base["BodyText"], fontName=regular, fontSize=9.7, leading=15,
                          spaceAfter=8, textColor=ink, splitLongWords=1, allowWidows=0, allowOrphans=0)
    title = ParagraphStyle("BookTitle", parent=base["Title"], fontName=bold, fontSize=32, leading=38,
                           alignment=0, textColor=ink, spaceAfter=13, keepWithNext=True)
    subtitle = ParagraphStyle("BookSubtitle", parent=body, fontName=regular, fontSize=10, leading=14,
                              textColor=muted, spaceAfter=14)
    eyebrow = ParagraphStyle("BookEyebrow", parent=body, fontName=bold, fontSize=8, leading=11,
                             textColor=muted, spaceBefore=3, spaceAfter=7, tracking=1.1)
    toc_number = ParagraphStyle("BookTocNumber", parent=body, fontName=bold, fontSize=8.2, leading=12,
                                textColor=muted, spaceAfter=0)
    toc_title = ParagraphStyle("BookTocTitle", parent=body, fontName=regular, fontSize=9.2, leading=13,
                               textColor=ink, spaceAfter=0)
    h2 = ParagraphStyle("BookH2", parent=base["Heading2"], fontName=bold, fontSize=17, leading=22,
                        textColor=ink, spaceBefore=2, spaceAfter=9, keepWithNext=True)
    h3 = ParagraphStyle("BookH3", parent=base["Heading3"], fontName=bold, fontSize=11.5, leading=15,
                        textColor=ink, spaceBefore=11, spaceAfter=5, keepWithNext=False)
    quote = ParagraphStyle("BookQuote", parent=body, fontName=italic, leftIndent=12,
                           borderColor=rule, borderWidth=0.7, borderPadding=7, spaceBefore=4, spaceAfter=9)
    small = ParagraphStyle("BookSmall", parent=body, fontSize=8.3, leading=11, textColor=muted)
    meta = ParagraphStyle("BookMeta", parent=body, fontSize=10, leading=14, textColor=muted, spaceAfter=3)
    disclaimer = ParagraphStyle("BookDisclaimer", parent=body, fontSize=8, leading=11, textColor=muted,
                                leftIndent=0, borderColor=rule, borderWidth=0, spaceBefore=17, spaceAfter=0)
    code_style = ParagraphStyle("BookCode", parent=body, fontName=code, fontSize=8.5, leading=12,
                                backColor=paper, borderPadding=7, splitLongWords=1)
    return {"body": body, "title": title, "subtitle": subtitle, "eyebrow": eyebrow, "h2": h2,
            "h3": h3, "quote": quote, "small": small, "meta": meta, "disclaimer": disclaimer,
            "toc_number": toc_number, "toc_title": toc_title,
            "code": code_style, "regular": regular, "rule": rule}


def _blocks(markdown_text: str, styles: dict) -> list:
    # Source paths, generation timestamps, and model identifiers belong in
    # machine-side provenance, not in a reader-facing study guide.
    markdown_text = re.sub(r"^\*\*(?:Source|Generated|Model):\*\*.*(?:\n|$)", "", markdown_text, flags=re.MULTILINE)
    # Some extractor-generated source locators are embedded in prose as
    # identifiers such as 023_14_chapter_title. Humanize those references too.
    marker = re.compile(r"(?<![A-Za-z0-9])\d{3}_[A-Za-z0-9]+(?:_[A-Za-z0-9]+)+")
    markdown_text = marker.sub(lambda match: clean_heading(match.group(0)), markdown_text)
    html_text = markdown(markdown_text, extensions=["tables", "fenced_code", "sane_lists"])
    soup = BeautifulSoup(html_text, "html.parser")
    story = []
    section_headings = {heading for _, heading in REPORT_SECTIONS}
    rendered_cover_title = False
    contents_mode = False
    for element in soup.contents:
        if isinstance(element, NavigableString):
            if str(element).strip():
                story.append(Paragraph(_inline(element), styles["body"]))
            continue
        if not isinstance(element, Tag):
            continue
        name = element.name.lower()
        if name in ("h1", "h2", "h3", "h4"):
            raw_heading = element.get_text(" ", strip=True)
            heading = clean_heading(raw_heading)
            if name == "h1":
                if not rendered_cover_title:
                    label = " — Study Guide"
                    if heading.endswith(label):
                        heading = heading[:-len(label)].strip()
                    from xml.sax.saxutils import escape
                    story.append(Spacer(1, 25 * mm))
                    story.append(Paragraph("BOOKROOM  /  READING GUIDE", styles["eyebrow"]))
                    story.append(HRFlowable(width=34 * mm, thickness=1.1, color=colors.HexColor("#111111"),
                                            hAlign="LEFT", spaceBefore=3, spaceAfter=15))
                    story.append(Paragraph(escape(heading), styles["title"]))
                    rendered_cover_title = True
                else:
                    from xml.sax.saxutils import escape
                    story.append(Paragraph(escape(heading), styles["h3"]))
            elif name == "h2":
                if raw_heading == "Contents" or heading in section_headings:
                    story.append(PageBreak())
                    story.append(Paragraph(heading, styles["h2"]))
                    story.append(HRFlowable(width="100%", thickness=0.55, color=styles["rule"], spaceAfter=11))
                    contents_mode = raw_heading == "Contents"
                else:
                    from xml.sax.saxutils import escape
                    story.append(Paragraph(escape(heading), styles["h3"]))
            else:
                from xml.sax.saxutils import escape
                story.append(Paragraph(escape(heading), styles["h3"]))
        elif name == "p":
            text = element.get_text(" ", strip=True)
            if text.startswith("Author:"):
                author = text.partition(":")[2].strip()
                if author and author.lower() != "unknown author":
                    story.append(Paragraph(_inline(element), styles["meta"]))
            elif text.startswith(("Source:", "Generated:", "Model:")):
                continue
            else:
                story.append(Paragraph(_inline(element), styles["body"]))
        elif name in ("ul", "ol"):
            if contents_mode and name == "ul":
                entries = [item.get_text(" ", strip=True) for item in element.find_all("li", recursive=False)]
                rows = []
                for row_index in range((len(entries) + 1) // 2):
                    row = []
                    for column in range(2):
                        index = row_index * 2 + column
                        if index < len(entries):
                            row.extend((Paragraph(f"{index + 1:02d}", styles["toc_number"]),
                                        Paragraph(_inline(element.find_all("li", recursive=False)[index]), styles["toc_title"])))
                        else:
                            row.extend((Paragraph("", styles["toc_number"]), Paragraph("", styles["toc_title"])))
                    rows.append(row)
                if rows:
                    table = Table(rows, colWidths=[9 * mm, 70 * mm, 9 * mm, 82 * mm], hAlign="LEFT")
                    table.setStyle(TableStyle([
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 0),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                        ("TOPPADDING", (0, 0), (-1, -1), 7),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                        ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#E4E4E4")),
                    ]))
                    story.append(table)
                contents_mode = False
                continue
            items = []
            for item in element.find_all("li", recursive=False):
                inline = "".join(_inline(child) for child in item.children if not isinstance(child, Tag) or child.name not in ("ul", "ol"))
                items.append(ListItem(Paragraph(inline or " ", styles["body"]), leftIndent=10))
            if items:
                story.append(ListFlowable(items, bulletType="bullet" if name == "ul" else "1", leftIndent=18, bulletFontName=styles["regular"], bulletFontSize=8, spaceAfter=5))
        elif name == "pre":
            code_text = element.get_text().rstrip()
            if code_text:
                story.append(Preformatted(code_text, styles["code"], maxLineLength=105))
        elif name == "blockquote":
            for child in element.find_all("p", recursive=True):
                story.append(Paragraph(_inline(child), styles["disclaimer"]))
        elif name == "table":
            rows = []
            for row in element.find_all("tr"):
                cells = [Paragraph(_inline(cell), styles["small"]) for cell in row.find_all(["th", "td"], recursive=False)]
                if cells:
                    rows.append(cells)
            if rows:
                column_count = max(map(len, rows))
                rows = [row + [Paragraph("", styles["small"])] * (column_count - len(row)) for row in rows]
                table = Table(rows, repeatRows=1, hAlign="LEFT")
                table.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F2F2F2")),
                    ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D8D8D8")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]))
                story.extend((table, Spacer(1, 7)))
        elif name == "hr":
            story.extend((HRFlowable(width="100%", thickness=0.7, color=colors.HexColor("#cbd5ce")), Spacer(1, 8)))
        else:
            text = _inline(element)
            if text.strip():
                story.append(Paragraph(text, styles["body"]))
    return story


def create_pdf(markdown_path: Path, pdf_path: Path | None = None) -> Path:
    """Create a PDF containing every validated section in the Markdown report."""
    markdown_path = Path(markdown_path)
    pdf_path = Path(pdf_path) if pdf_path else markdown_path.with_suffix(".pdf")
    content = markdown_path.read_text(encoding="utf-8")
    problems = validate_report(content)
    if problems:
        raise ValueError("Markdown report failed validation: " + "; ".join(problems))
    missing = [heading for _, heading in REPORT_SECTIONS if f"## {heading}" not in content]
    if missing:
        raise ValueError("Markdown report is missing required sections: " + ", ".join(missing))
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    styles = _styles()
    story = _blocks(content, styles)

    raw_title = re.search(r"^#\s+(.+)$", content, flags=re.MULTILINE)
    book_title = (raw_title.group(1) if raw_title else markdown_path.stem).removesuffix(" — Study Guide")
    book_title = display_title(book_title)

    def page_footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(styles["regular"], 8)
        canvas.setFillColor(colors.HexColor("#666666"))
        canvas.setStrokeColor(styles["rule"])
        canvas.setLineWidth(0.5)
        canvas.line(20 * mm, 16 * mm, A4[0] - 20 * mm, 16 * mm)
        canvas.drawString(20 * mm, 10.5 * mm, book_title)
        canvas.drawRightString(A4[0] - 20 * mm, 10.5 * mm, str(doc.page))
        canvas.restoreState()

    document = SimpleDocTemplate(str(pdf_path), pagesize=A4, rightMargin=20 * mm, leftMargin=20 * mm,
                                 topMargin=22 * mm, bottomMargin=22 * mm, title=book_title,
                                 author="Book Summarizer")
    document.build(story, onFirstPage=page_footer, onLaterPages=page_footer)
    if not pdf_path.is_file() or pdf_path.stat().st_size < 500:
        raise RuntimeError("PDF export did not produce a valid document")
    return pdf_path
