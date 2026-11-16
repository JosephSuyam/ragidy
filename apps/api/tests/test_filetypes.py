import io
import zipfile

import pytest

from app.core.config import SUPPORTED_UPLOAD_TYPES
from app.core.filetypes import MIME_TYPES, detect_type


def zip_bytes(*names: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name in names:
            archive.writestr(name, "<w:document/>")
    return buffer.getvalue()


def test_every_supported_type_has_a_mime_type() -> None:
    assert set(MIME_TYPES) == SUPPORTED_UPLOAD_TYPES


@pytest.mark.parametrize(
    ("data", "name", "expected"),
    [
        (b"%PDF-1.7\n%binary", "scan.txt", "pdf"),
        (zip_bytes("[Content_Types].xml", "word/document.xml"), "report.zip", "docx"),
        (zip_bytes("[Content_Types].xml", "xl/workbook.xml"), "sheet.docx", None),
        (b"PK\x03\x04not really a zip", "report.docx", None),
        (b"\xef\xbb\xbf \r\n\t<!DOCTYPE HTML><p>hi</p>", "page", "html"),
        (b"  <html lang='en'>", "page.txt", "html"),
        (b"<head><title>t</title></head>", "page", "html"),
        (b"\xef\xbb\xbf\n  <BODY>hi</BODY>", "page.md", "html"),
        (b"", "notes.txt", None),
        (b"\xef\xbb\xbf \r\n\t", "notes.md", None),
        (b"# Title\n", "notes.md", "md"),
        (b"# Title\n", "NOTES.MD", "md"),
        (b"# Title\n", "notes.txt", "txt"),
        (b"plain words", "", "txt"),
        (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR", "image.txt", None),
        (b"caf\xe9", "latin1.txt", None),
        (b"text\x00with a NUL", "notes.txt", None),
    ],
)
def test_detect_type_from_bytes(data: bytes, name: str, expected: str | None) -> None:
    assert detect_type(data, name) == expected
