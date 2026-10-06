"""Build a real EPUB and a real PDF for verification.

Nothing here is mocked: the EPUB is written with ebooklib and the PDF with
PyMuPDF, so the SDK's extraction path runs against genuine files.
"""

from __future__ import annotations

from pathlib import Path

_PARAGRAPH = (
    "Attention is the scarce resource that most work quietly exhausts. The argument here is not that "
    "people lack time, but that they lack the ability to hold a problem in mind long enough for it to "
    "yield its structure. A chapter that states this plainly is easier to act on than one that gestures "
    "at it, which is why concrete examples carry the weight that abstraction cannot. "
)


def _body(paragraphs: int = 6) -> str:
    text = (_PARAGRAPH * paragraphs).strip()
    words = len(text.split())
    assert words >= 200, f"fixture section must clear MIN_WORD_COUNT, got {words} words"
    return text


def build_epub(path: Path, chapters: int = 4) -> Path:
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_identifier("bookroom-sdk-fixture")
    book.set_title("The Discipline of Attention")
    book.set_language("en")

    items = []
    for index in range(1, chapters + 1):
        title = f"Chapter {index}: A Working Thesis"
        item = epub.EpubHtml(title=title, file_name=f"chap_{index:03d}.xhtml", lang="en")
        item.content = f"<h1>{title}</h1>" + "".join(
            f"<p>{_PARAGRAPH}</p>" for _ in range(6)
        )
        item.add_item(epub.EpubNcx())
        item.add_item(epub.EpubNav())
        book.add_item(item)
        items.append(item)

    book.toc = tuple(items)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = list(items)
    path.parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(path), book)
    return path


def build_pdf(path: Path, pages: int = 12) -> Path:
    import fitz

    path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    for number in range(1, pages + 1):
        page = document.new_page()
        page.insert_text((72, 90), f"Chapter {number}", fontsize=18)
        page.insert_textbox(fitz.Rect(72, 120, 520, 760), _body(5), fontsize=10, align=0)
    document.set_toc([[1, f"Chapter {n}", n * 2 - 1] for n in range(1, pages // 2 + 1)])
    document.set_metadata({"title": "The Discipline of Attention", "author": "A. Fixture"})
    document.save(str(path))
    document.close()
    return path


if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    print(build_epub(here / "fixtures" / "attention.epub"))
    print(build_pdf(here / "fixtures" / "attention.pdf"))
