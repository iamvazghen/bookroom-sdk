"""Extraction: turn an EPUB or PDF into addressable sections."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from . import bootstrap, errors
from .config import Config, SummarizeOptions
from .results import Document, Section, guard

SUPPORTED_SUFFIXES = (".pdf", ".epub")


def _require_supported(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise errors.UnsupportedSourceError(f"No such file: {resolved}")
    if resolved.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise errors.UnsupportedSourceError(
            f"Unsupported source '{resolved.name}'. Bookroom reads EPUB and PDF; got '{resolved.suffix or 'no extension'}'."
        )
    return resolved


class ExtractAPI:
    """Read a book and expose its sections, locators and OCR signal."""

    def __init__(self, config: Config):
        self.config = config

    def _pipeline_sections(self, path: Path, options: SummarizeOptions) -> list[dict[str, Any]]:
        """Use the application's own splitter so SDK and application agree exactly.

        ``book_pipeline._extract`` dereferences ``path.suffix`` directly, so it
        must receive a Path rather than a string.
        """
        pipeline = bootstrap.module("book_pipeline", self.config)
        payload = pipeline._extract(path, options=options.as_dict())
        return list(payload or [])

    @guard
    def extract(
        self,
        source: str | os.PathLike[str],
        *,
        options: SummarizeOptions | dict[str, Any] | None = None,
        include_text: bool = False,
    ) -> Document:
        """Extract every section that meets the minimum word count."""
        path = _require_supported(Path(source))
        prefs = SummarizeOptions.parse(options)
        raw_sections = self._pipeline_sections(path, prefs)

        sections = tuple(
            Section(
                title=str(item.get("title") or "Untitled"),
                text=str(item.get("source") or ""),
                locator=str(item.get("locator") or ""),
                ocr_used=bool(item.get("ocr_used")),
                ocr_confidence=item.get("ocr_confidence"),
            )
            for item in raw_sections
        )
        if not sections:
            raise errors.ExtractionError(
                "No sections met the minimum word count. Lower min_word_count or use a different file."
            )

        report_format = bootstrap.module("report_format", self.config)
        title = report_format.display_title(path.stem)
        return Document(
            path=str(path),
            kind=path.suffix.lower().lstrip("."),
            title=title,
            sections=sections,
        )

    @guard
    def extract_epub(self, source: str | os.PathLike[str], *, min_word_count: int | None = None) -> Document:
        """Extract an EPUB through the application's dedicated EPUB reader."""
        path = _require_supported(Path(source))
        if path.suffix.lower() != ".epub":
            raise errors.UnsupportedSourceError(f"Expected an EPUB file, got {path.suffix or 'no extension'}")
        extractor = bootstrap.module("epub_extractor", self.config)
        limit = self.config.min_word_count if min_word_count is None else int(min_word_count)
        items = extractor.extract_epub_content(str(path), limit)
        report_format = bootstrap.module("report_format", self.config)
        sections = tuple(
            Section(
                title=report_format.clean_heading(str(item.get("filename") or "Section")),
                text=str(item.get("text") or ""),
                locator=str(item.get("filename") or ""),
            )
            for item in (items or [])
        )
        if not sections:
            raise errors.ExtractionError("No EPUB sections met the minimum word count.")
        return Document(path=str(path), kind="epub",
                        title=report_format.display_title(path.stem), sections=sections)

    @guard
    def extract_pdf(self, source: str | os.PathLike[str], *, min_word_count: int | None = None,
                    ocr_enabled: bool | None = None, ocr_language: str | None = None) -> Document:
        """Extract a PDF, optionally running Tesseract OCR on scanned pages."""
        path = _require_supported(Path(source))
        if path.suffix.lower() != ".pdf":
            raise errors.UnsupportedSourceError(f"Expected a PDF file, got {path.suffix or 'no extension'}")
        extractor = bootstrap.module("pdf_extractor", self.config)
        limit = self.config.min_word_count if min_word_count is None else int(min_word_count)
        use_ocr = self.config.ocr_enabled if ocr_enabled is None else bool(ocr_enabled)
        language = ocr_language or self.config.ocr_language
        items = extractor.extract_pdf_content(str(path), limit, ocr_enabled=use_ocr,
                                              ocr_language=language)
        report_format = bootstrap.module("report_format", self.config)
        sections: list[Section] = []
        for item in (items or []):
            node = item["node"]
            start = max(1, int(node.page))
            end = int(node.end_page) - 1 if node.end_page else start
            sections.append(Section(
                title=report_format.clean_heading(str(node.get_filename())),
                text=str(item.get("text") or ""),
                locator=f"PDF pages {start}-{max(start, end)}",
                ocr_used=bool(item.get("ocr_used")),
                ocr_confidence=item.get("ocr_confidence"),
            ))
        if not sections:
            raise errors.ExtractionError(
                "No PDF sections met the minimum word count. For a scanned PDF, enable OCR and install Tesseract."
            )
        return Document(path=str(path), kind="pdf",
                        title=report_format.display_title(path.stem), sections=tuple(sections))

    # ------------------------------------------------------------- structure
    @guard
    def outline(self, source: str | os.PathLike[str]) -> list[dict[str, Any]]:
        """Return the PDF table of contents as a flat (level, title, page) list."""
        path = _require_supported(Path(source))
        if path.suffix.lower() != ".pdf":
            raise errors.UnsupportedSourceError("outline() is only meaningful for PDFs")
        try:
            import fitz
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise errors.ExtractionError("PyMuPDF (fitz) is required to read a PDF outline") from exc
        with fitz.open(str(path)) as document:
            return [{"level": level, "title": title, "page": page}
                    for level, title, page in document.get_toc()]

    @guard
    def ocr_languages(self) -> list[str]:
        """OCR languages Tesseract has installed (empty when unavailable)."""
        extractor = bootstrap.module("pdf_extractor", self.config)
        return list(extractor.available_ocr_languages())

    @guard
    def metadata(self, source: str | os.PathLike[str]) -> dict[str, Any]:
        """Document metadata; author is read from the PDF when present."""
        path = _require_supported(Path(source))
        data: dict[str, Any] = {"path": str(path), "kind": path.suffix.lower().lstrip("."),
                                "name": path.name, "size_bytes": path.stat().st_size, "author": None,
                                "title": path.stem}
        if path.suffix.lower() == ".pdf":
            try:
                import fitz
                with fitz.open(str(path)) as document:
                    meta = document.metadata or {}
                    pages = len(document)
                data.update({
                    "title": meta.get("title") or path.stem,
                    "author": meta.get("author"),
                    "pages": pages,
                })
            except Exception:  # noqa: BLE001 - metadata is optional
                pass
        return data
