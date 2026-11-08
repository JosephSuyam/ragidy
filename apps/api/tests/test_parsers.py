import asyncio
import io
import zipfile
from typing import Any

import pytest
from llama_index.core import Document, MockEmbedding
from pypdf import PageObject, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.core import providers
from app.core.filetypes import MIME_TYPES
from app.rag import parsers
from app.rag.chunking import chunk
from app.rag.errors import IngestionError
from app.rag.ingestion import ingest_document
from app.rag.parsers import parse

PDF, DOCX, HTML, TXT, MD = (MIME_TYPES[t] for t in ("pdf", "docx", "html", "txt", "md"))
UNREADABLE = "The file could not be read."
DOCX_PART = "word/document.xml"
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def make_pdf(*pages: str, user_password: str | None = None) -> bytes:
    writer = PdfWriter()
    helvetica = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    for text in pages:
        page = writer.add_blank_page(200, 200)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): helvetica})}
        )
        content = DecodedStreamObject()
        content.set_data(f"BT /F1 12 Tf 10 100 Td ({text}) Tj ET".encode())
        page.replace_contents(content)
    if user_password is not None:
        writer.encrypt(user_password=user_password, owner_password="owner", algorithm="RC4-128")
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def make_docx(xml: bytes | None, **extra: bytes) -> bytes:
    """A DOCX zip whose word/document.xml is `xml` (left out when None), plus `extra` parts."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        if xml is not None:
            archive.writestr(DOCX_PART, xml)
        for name, data in extra.items():
            archive.writestr(name, data)
    return out.getvalue()


def docx_xml(*paragraphs: str, prolog: str = "") -> str:
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    document = f'<w:document xmlns:w="{W_NS}"><w:body>{body}</w:body></w:document>'
    return f'<?xml version="1.0"?>{prolog}{document}'


def assert_rejected(data: bytes, mime: str, message: str) -> None:
    with pytest.raises(IngestionError) as exc:
        parse(data, mime, "s")
    assert str(exc.value) == message


def test_pdf_gives_one_document_per_page_numbered_from_one() -> None:
    documents = parse(make_pdf("Hello page one", "Second page"), PDF, "report.pdf")

    assert [d.text for d in documents] == ["Hello page one", "Second page"]
    assert [d.metadata for d in documents] == [
        {"source": "report.pdf", "page": 1},
        {"source": "report.pdf", "page": 2},
    ]


def test_pdf_with_owner_password_only_opens_with_the_empty_password() -> None:
    documents = parse(make_pdf("Locked edits", user_password=""), PDF, "s")

    assert [d.text for d in documents] == ["Locked edits"]


def test_pdf_with_user_password_is_rejected() -> None:
    assert_rejected(make_pdf("Secret", user_password="pw"), PDF, "The PDF is password-protected.")


def test_pdf_over_the_page_cap_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(parsers, "MAX_PDF_PAGES", 2)

    assert len(parse(make_pdf("a", "b"), PDF, "s")) == 2
    assert_rejected(make_pdf("a", "b", "c"), PDF, "The PDF has more than 2 pages.")


TOO_MUCH_TEXT = "The document has too much text."


@pytest.mark.parametrize(
    ("data", "mime"),
    [
        pytest.param(b"abcdef", TXT, id="txt"),
        pytest.param(make_pdf("abc", "def"), PDF, id="pdf-total-over-pages"),
    ],
)
def test_text_over_the_char_cap_is_rejected(
    monkeypatch: pytest.MonkeyPatch, data: bytes, mime: str
) -> None:
    monkeypatch.setattr(parsers, "MAX_TEXT_CHARS", 6)
    assert sum(len(d.text) for d in parse(data, mime, "s")) == 6

    monkeypatch.setattr(parsers, "MAX_TEXT_CHARS", 5)
    assert_rejected(data, mime, TOO_MUCH_TEXT)


def test_pdf_stops_extracting_once_over_the_char_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(parsers, "MAX_TEXT_CHARS", 3)
    extracted: list[str] = []
    extract_text = PageObject.extract_text

    def spy(page: PageObject, *args: Any, **kwargs: Any) -> str:
        extracted.append(extract_text(page, *args, **kwargs))
        return extracted[-1]

    monkeypatch.setattr(PageObject, "extract_text", spy)

    assert_rejected(make_pdf("abcd", "never read"), PDF, TOO_MUCH_TEXT)
    assert extracted == ["abcd"]


@pytest.mark.parametrize(
    ("data", "mime"),
    [
        pytest.param(b"a\x00b", TXT, id="txt"),
        pytest.param(make_pdf("a\\000b"), PDF, id="pdf"),  # pypdf maps the octal escape to NUL
    ],
)
def test_nul_characters_are_removed(data: bytes, mime: str) -> None:
    # Regression: Postgres text columns reject NUL, so storing the chunk failed.
    assert [d.text for d in parse(data, mime, "s")] == ["ab"]


def test_garbage_pdf_is_unreadable() -> None:
    assert_rejected(b"%PDF-1.7 not really a pdf", PDF, UNREADABLE)


def test_docx_joins_runs_into_paragraph_lines() -> None:
    xml = docx_xml("First paragraph", "Second paragraph").replace(
        "First paragraph", "First </w:t></w:r><w:r><w:t>paragraph"
    )

    documents = parse(make_docx(xml.encode()), DOCX, "notes.docx")

    assert [(d.text, d.metadata) for d in documents] == [
        ("First paragraph\nSecond paragraph", {"source": "notes.docx", "page": None})
    ]


ENTITY_PROLOG = '<!DOCTYPE w:document [<!ENTITY x "expanded">]>'


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "utf-16-le"])
def test_docx_with_a_doctype_is_rejected_in_any_encoding(encoding: str) -> None:
    # Regression: expat auto-detects UTF-16, so a UTF-16 DOCTYPE once slipped past a byte check.
    xml = docx_xml("&x;", prolog=ENTITY_PROLOG).encode(encoding)

    assert_rejected(make_docx(xml), DOCX, UNREADABLE)


@pytest.mark.parametrize("encoding", ["utf-16", "utf-16-le"])
def test_docx_xml_must_be_utf8_even_without_a_doctype(encoding: str) -> None:
    assert_rejected(make_docx(docx_xml("plain").encode(encoding)), DOCX, UNREADABLE)


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(b"PK\x03\x04 truncated", id="bad-zip"),
        pytest.param(make_docx(None, **{"word/other.xml": b"<x/>"}), id="missing-part"),
        pytest.param(make_docx(b"<w:document"), id="malformed-xml"),
    ],
)
def test_broken_docx_is_unreadable(data: bytes) -> None:
    assert_rejected(data, DOCX, UNREADABLE)


def test_docx_over_the_xml_cap_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    xml = docx_xml("a" * 200).encode()
    monkeypatch.setattr(parsers, "MAX_DOCX_XML_BYTES", len(xml))

    assert parse(make_docx(xml), DOCX, "s")[0].text == "a" * 200
    assert_rejected(make_docx(xml + b" "), DOCX, "The document is too large to read.")


def test_html_drops_script_and_style_and_keeps_block_lines() -> None:
    html = (
        "<html><head><style>p { color: red }</style><script>alert('x')</script></head>"
        "<body><h1>Title</h1><p>One <b>bold</b> line</p><div>Two</div></body></html>"
    )

    documents = parse(html.encode(), HTML, "https://example.com/page")

    assert [(d.text, d.metadata) for d in documents] == [
        ("Title\nOne bold line\nTwo", {"source": "https://example.com/page", "page": None})
    ]


@pytest.mark.parametrize("mime", [TXT, MD])
def test_text_strips_the_utf8_bom(mime: str) -> None:
    documents = parse("﻿# Notes\ncafé".encode(), mime, "notes")

    assert [(d.text, d.metadata) for d in documents] == [
        ("# Notes\ncafé", {"source": "notes", "page": None})
    ]


@pytest.mark.parametrize("mime", [TXT, MD, HTML])
def test_invalid_utf8_text_is_rejected(mime: str) -> None:
    assert_rejected(b"caf\xe9", mime, "The file is not valid UTF-8 text.")


def test_unknown_mime_is_unsupported() -> None:
    assert_rejected(b"\x89PNG", "image/png", "Unsupported file type.")


def test_chunk_drops_whitespace_documents_and_copies_metadata() -> None:
    real = Document(text="Hello world.", metadata={"source": "a", "page": 3})
    chunks = chunk([Document(text=" \n\t ", metadata={"source": "blank"}), real])

    assert chunks == [("Hello world.", {"source": "a", "page": 3})]
    assert chunks[0][1] is not real.metadata


def test_chunk_splits_long_text_with_each_chunk_keeping_metadata() -> None:
    text = " ".join(f"Sentence number {i} is here." for i in range(400))

    chunks = chunk([Document(text=text, metadata={"source": "a", "page": None})])

    assert len(chunks) > 1
    assert all(t.strip() and m == {"source": "a", "page": None} for t, m in chunks)


def test_ingest_document_embeds_each_chunk(mock_embeddings: list[MockEmbedding]) -> None:
    chunks = asyncio.run(ingest_document(make_pdf("Alpha", "Beta"), PDF, "report.pdf"))

    assert [(c.text, c.metadata) for c in chunks] == [
        ("Alpha", {"source": "report.pdf", "page": 1}),
        ("Beta", {"source": "report.pdf", "page": 2}),
    ]
    assert all(len(c.embedding) == 8 for c in chunks)


def test_ingest_document_without_text_fails_before_embedding(
    mock_embeddings: list[MockEmbedding],
) -> None:
    with pytest.raises(IngestionError) as exc:
        asyncio.run(ingest_document(b"  \n ", TXT, "blank.txt"))

    assert str(exc.value) == "The document has no readable text."
    assert mock_embeddings == []


def test_ingest_document_lets_parser_errors_through(mock_embeddings: list[MockEmbedding]) -> None:
    with pytest.raises(IngestionError, match="^Unsupported file type.$"):
        asyncio.run(ingest_document(b"x", "image/png", "x.png"))


def test_ingest_document_propagates_provider_errors_unwrapped(
    app_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    outage = ConnectionError("embedding provider down")

    class FailingEmbedding:
        async def aget_text_embedding_batch(self, texts: list[str]) -> list[list[float]]:
            raise outage

    monkeypatch.setattr(providers, "get_embed_model", lambda settings: FailingEmbedding())

    with pytest.raises(ConnectionError) as exc:
        asyncio.run(ingest_document(b"Some text.", TXT, "a.txt"))

    assert exc.value is outage
