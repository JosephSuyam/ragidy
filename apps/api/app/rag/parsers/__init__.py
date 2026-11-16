import io
import logging
import zipfile
from collections.abc import Callable
from html.parser import HTMLParser
from xml.etree import ElementTree

from llama_index.core import Document
from pypdf import PdfReader

from app.core.filetypes import MIME_TYPES
from app.rag.errors import IngestionError

logger = logging.getLogger(__name__)

# pypdf caps each decompressed stream at 75 MB but not the page count.
MAX_PDF_PAGES = 1000
MAX_DOCX_XML_BYTES = 20 * 1024 * 1024
# Bounds memory and embedding cost: a small compressed PDF can expand to gigabytes of text.
MAX_TEXT_CHARS = 5_000_000

_DOCX_XML = "word/document.xml"
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_UNREADABLE = "The file could not be read."


def _document(text: str, source: str, page: int | None = None) -> Document:
    # Postgres text rejects NUL, and pypdf emits it for some fonts.
    return Document(text=text.replace("\x00", ""), metadata={"source": source, "page": page})


def _check_text_size(chars: int) -> None:
    if chars > MAX_TEXT_CHARS:
        raise IngestionError("The document has too much text.")


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise IngestionError("The file is not valid UTF-8 text.") from exc


def _parse_text(data: bytes, source: str) -> list[Document]:
    return [_document(_decode(data), source)]


def _parse_pdf(data: bytes, source: str) -> list[Document]:
    try:
        reader = PdfReader(io.BytesIO(data))
        # Owner-password-only PDFs open with an empty user password.
        locked = reader.is_encrypted and not reader.decrypt("")
        page_count = 0 if locked else len(reader.pages)
    except Exception:
        logger.warning("Unreadable PDF", exc_info=True)
        raise IngestionError(_UNREADABLE) from None
    if locked:
        raise IngestionError("The PDF is password-protected.")
    if page_count > MAX_PDF_PAGES:
        raise IngestionError(f"The PDF has more than {MAX_PDF_PAGES} pages.")
    documents: list[Document] = []
    chars = 0
    try:
        for number, page in enumerate(reader.pages, start=1):
            documents.append(_document(page.extract_text(), source, number))
            chars += len(documents[-1].text)
            if chars > MAX_TEXT_CHARS:
                break
    except Exception:
        logger.warning("Unreadable PDF page", exc_info=True)
        raise IngestionError(_UNREADABLE) from None
    _check_text_size(chars)
    return documents


def _read_docx_xml(data: bytes) -> bytes:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            info = archive.getinfo(_DOCX_XML)
            too_large = info.file_size > MAX_DOCX_XML_BYTES
            with archive.open(info) as part:
                xml = b"" if too_large else part.read(MAX_DOCX_XML_BYTES + 1)
    except Exception:
        logger.warning("Unreadable DOCX archive", exc_info=True)
        raise IngestionError(_UNREADABLE) from None
    if too_large or len(xml) > MAX_DOCX_XML_BYTES:
        raise IngestionError("The document is too large to read.")
    return xml


def _parse_docx(data: bytes, source: str) -> list[Document]:
    xml = _read_docx_xml(data)
    # ElementTree expands internal entities, so reject any DOCTYPE. Expat still auto-detects
    # UTF-16 (BOM or NUL bytes) over encoding="utf-8", so require strict UTF-8 without NUL too.
    try:
        xml.decode("utf-8")
        if b"\x00" in xml or b"<!DOCTYPE" in xml:
            raise ValueError("DOCTYPE or non-UTF-8 XML")
        root = ElementTree.fromstring(xml, parser=ElementTree.XMLParser(encoding="utf-8"))
    except (ValueError, ElementTree.ParseError):
        logger.warning("Unreadable DOCX XML", exc_info=True)
        raise IngestionError(_UNREADABLE) from None
    paragraphs = (
        "".join(node.text or "" for node in paragraph.iter(f"{_W}t"))
        for paragraph in root.iter(f"{_W}p")
    )
    return [_document("\n".join(paragraphs), source)]


class _HTMLText(HTMLParser):
    _SKIP = frozenset({"script", "style"})
    _BLOCK = frozenset(
        {"br", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "p", "section", "td", "tr"}
    )

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)


def _parse_html(data: bytes, source: str) -> list[Document]:
    parser = _HTMLText()
    parser.feed(_decode(data))
    parser.close()
    lines = (line.strip() for line in "".join(parser.parts).splitlines())
    return [_document("\n".join(line for line in lines if line), source)]


_PARSERS: dict[str, Callable[[bytes, str], list[Document]]] = {
    MIME_TYPES["pdf"]: _parse_pdf,
    MIME_TYPES["docx"]: _parse_docx,
    MIME_TYPES["html"]: _parse_html,
    MIME_TYPES["txt"]: _parse_text,
    MIME_TYPES["md"]: _parse_text,
}


def parse(data: bytes, mime: str, source: str) -> list[Document]:
    """One Document per PDF page (page is 1-based), else one (page None); untrusted input."""
    parser = _PARSERS.get(mime)
    if parser is None:
        raise IngestionError("Unsupported file type.")
    documents = parser(data, source)
    _check_text_size(sum(len(document.text) for document in documents))
    return documents
