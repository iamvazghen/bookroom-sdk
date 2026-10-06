"""PDF chapter extraction with optional, explicitly enabled Tesseract OCR."""

import csv
from collections import OrderedDict
import io
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
try:  # PyMuPDF renamed the top-level module; prefer the supported name so the
    # deprecated `fitz` alias (which prints a warning on import) is not used.
    import pymupdf as fitz
except ImportError:  # pragma: no cover - very old PyMuPDF
    import fitz
from utils import sanitize_filename

OCR_ENABLED = os.getenv("OCR_ENABLED", "false").lower() == "true"
OCR_LANGUAGE = os.getenv("OCR_LANGUAGE", "eng")
OCR_SUPPORTED_LANGUAGES = {"eng", "deu", "spa", "fra"}


def _configure_tesseract() -> str | None:
    configured = os.getenv("TESSERACT_CMD", "").strip()
    binary = shutil.which(configured) if configured else shutil.which("tesseract")
    if configured and Path(configured).is_file():
        binary = str(Path(configured).resolve())
    if not binary and os.name == "nt":
        candidates = [Path(os.getenv("ProgramFiles", r"C:\Program Files")) / "Tesseract-OCR" / "tesseract.exe",
                      Path(os.getenv("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Tesseract-OCR" / "tesseract.exe"]
        binary = next((str(path) for path in candidates if path.is_file()), None)
    if binary:
        # PyMuPDF invokes the executable by name; put its folder on this app process's PATH.
        binary_dir = str(Path(binary).resolve().parent)
        current = os.environ.get("PATH", "").split(os.pathsep)
        if binary_dir.casefold() not in {part.casefold() for part in current}:
            os.environ["PATH"] = binary_dir + os.pathsep + os.environ.get("PATH", "")
    return binary


def available_ocr_languages() -> list[str]:
    binary = _configure_tesseract()
    if not binary:
        return []
    try:
        result = subprocess.run([binary, "--list-langs"], capture_output=True, text=True, timeout=10, check=True)
    except (OSError, subprocess.SubprocessError):
        return []
    return [line.strip() for line in result.stdout.splitlines()[1:] if line.strip() in OCR_SUPPORTED_LANGUAGES]


class TOCNode:
    def __init__(self, level: int, title: str, page: int, idx: int):
        self.level, self.title, self.page, self.idx = level, title, page, idx
        self.end_page = None
        self.children, self.text, self.summary, self.parent = [], None, None, None

    def is_leaf(self) -> bool:
        return len(self.children) == 0

    def get_filename(self) -> str:
        sanitized = sanitize_filename(self.title, max_length=60) if self.title else "untitled"
        return f"{self.idx:03d}_{sanitized}"


def build_toc_tree(toc: list) -> list:
    nodes = [TOCNode(level, title, page, idx) for idx, (level, title, page) in enumerate(toc, start=1)]
    for index, node in enumerate(nodes):
        for following in nodes[index + 1:]:
            if following.level <= node.level:
                node.end_page = following.page
                break
    roots, stack = [], []
    for node in nodes:
        while stack and stack[-1][0] >= node.level:
            stack.pop()
        if stack:
            node.parent = stack[-1][1]
            node.parent.children.append(node)
        else:
            roots.append(node)
        stack.append((node.level, node))
    return roots


def collect_leaf_nodes(roots: list) -> list:
    leaves = []
    def visit(node):
        if node.is_leaf():
            leaves.append(node)
        else:
            for child in node.children:
                visit(child)
    for root in roots:
        visit(root)
    return leaves


def extract_text_for_page_range(doc, start_page: int, end_page: int, doc_length: int) -> str:
    return "".join(doc[i].get_text() for i in range(start_page - 1, min(end_page - 1, doc_length)) if i >= 0).strip()


def extract_text_for_node(doc, node: TOCNode, doc_length: int) -> str:
    stop = node.end_page - 1 if node.end_page else doc_length
    return "".join(doc[i].get_text() for i in range(max(0, node.page - 1), min(stop, doc_length))).strip()


def get_ancestor_intro_texts(doc, node: TOCNode, doc_length: int) -> str:
    intros, current = [], node
    while current.parent is not None:
        parent = current.parent
        if not parent.children or parent.children[0] != current:
            break
        first_child = parent.children[0]
        if parent.page < first_child.page:
            text = extract_text_for_page_range(doc, parent.page, first_child.page, doc_length)
            if text:
                intros.insert(0, f"[Context from: {parent.title}]\n{text}")
        current = parent
    return "\n\n".join(intros)


def _ocr_range(doc, start: int, stop: int, language: str | None = None) -> str:
    return _ocr_range_with_confidence(doc, start, stop, language)[0]


def _ocr_range_with_confidence(doc, start: int, stop: int, language: str | None = None) -> tuple[str, float | None]:
    binary = _configure_tesseract()
    if not binary:
        raise RuntimeError("This appears to be a scanned PDF. OCR is enabled, but Tesseract was not found. Install Tesseract OCR and set TESSDATA_PREFIX, or disable OCR_ENABLED.")
    pieces, confidences = [], []
    for index in range(max(0, start - 1), min(len(doc), stop - 1)):
        page = doc[index]
        pixmap = page.get_pixmap(dpi=200, alpha=False)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as image_file:
                temp_path = Path(image_file.name)
            pixmap.save(str(temp_path))
            result = subprocess.run([binary, str(temp_path), "stdout", "-l", language or OCR_LANGUAGE, "tsv"],
                                    capture_output=True, text=True, timeout=180, check=True)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Tesseract OCR timed out while processing a scanned page. Reduce the scan resolution or split the PDF.") from exc
        except subprocess.CalledProcessError as exc:
            details = (exc.stderr or "").strip()
            raise RuntimeError(f"Tesseract OCR failed: {details[:500] or 'unknown engine error'}") from exc
        finally:
            if temp_path:
                temp_path.unlink(missing_ok=True)
        line_words: OrderedDict[tuple[str, str, str, str], list[str]] = OrderedDict()
        try:
            for row in csv.DictReader(io.StringIO(result.stdout), delimiter="\t"):
                word = (row.get("text") or "").strip()
                if not word:
                    continue
                key = (row.get("page_num", ""), row.get("block_num", ""), row.get("par_num", ""), row.get("line_num", ""))
                line_words.setdefault(key, []).append(word)
                try:
                    confidence = float(row.get("conf", "-1"))
                except ValueError:
                    continue
                if confidence >= 0:
                    confidences.append(confidence)
        except csv.Error as exc:
            raise RuntimeError("Tesseract returned malformed OCR confidence data.") from exc
        pieces.extend(" ".join(words) for words in line_words.values())
    confidence = round(sum(confidences) / len(confidences), 1) if confidences else None
    return "\n".join(pieces).strip(), confidence


def extract_pdf_content(pdf_path: str, min_word_count: int = 200, *, ocr_enabled: bool | None = None,
                        ocr_language: str | None = None) -> list:
    ocr_enabled = OCR_ENABLED if ocr_enabled is None else bool(ocr_enabled)
    ocr_language = ocr_language or OCR_LANGUAGE
    doc = fitz.open(pdf_path)
    toc = doc.get_toc()
    if not toc:
        if not ocr_enabled:
            doc.close()
            raise ValueError(f"PDF file '{pdf_path}' has no table of contents. Enable OCR for page-group extraction of outline-free PDFs.")
        pages_per_section = 8
        nodes = []
        for idx, start_page in enumerate(range(1, len(doc) + 1, pages_per_section), start=1):
            stop_page = min(len(doc) + 1, start_page + pages_per_section)
            node = TOCNode(1, f"Scanned pages {start_page}-{stop_page - 1}", start_page, idx)
            node.end_page = stop_page
            nodes.append(node)
    else:
        nodes = collect_leaf_nodes(build_toc_tree(toc))
    length = len(doc)
    results = []
    skipped_short_sections = 0
    tesseract_available = bool(_configure_tesseract()) if ocr_enabled else False
    for node in nodes:
        if node.end_page is None:
            node.end_page = length + 1
        intro = get_ancestor_intro_texts(doc, node, length)
        own = extract_text_for_node(doc, node, length)
        combined = f"{intro}\n\n---\n\n{own}" if intro else own
        used_ocr = False
        ocr_confidence = None
        if len(combined.split()) < min_word_count and ocr_enabled:
            if tesseract_available:
                own, ocr_confidence = _ocr_range_with_confidence(doc, node.page, node.end_page, ocr_language)
                combined = f"{intro}\n\n---\n\n{own}" if intro else own
                used_ocr = True
            else:
                # A text-based book may still have short front/back-matter
                # outline entries. Do not let one such entry abort extraction
                # of every selectable-text chapter.
                skipped_short_sections += 1
        if len(combined.split()) >= min_word_count:
            node.text = " ".join(combined.split())
            results.append({"node": node, "text": node.text, "ocr_used": used_ocr, "ocr_confidence": ocr_confidence})
    doc.close()
    if not results and ocr_enabled and skipped_short_sections:
        raise RuntimeError("This PDF has no extractable sections meeting the minimum word count. OCR is enabled, but Tesseract was not found. Install Tesseract OCR and set TESSDATA_PREFIX, or disable OCR_ENABLED.")
    if not results and not ocr_enabled:
        raise ValueError("No selectable text was found in the PDF. It may be scanned; enable OCR_ENABLED=true and install Tesseract to process scanned books.")
    return results
