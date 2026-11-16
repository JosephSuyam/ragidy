import io
import zipfile

MIME_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "txt": "text/plain",
    "md": "text/markdown",
    "html": "text/html",
}


def detect_type(data: bytes, name: str) -> str | None:
    """Type name from the bytes; `name` (a filename or URL path) only splits md from txt."""
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                return "docx" if "word/document.xml" in archive.namelist() else None
        except zipfile.BadZipFile:
            return None
    if b"\x00" in data:
        return None
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None
    if not text.strip():
        return None
    head = text.lstrip()[:15].lower()
    if head.startswith(("<!doctype html", "<html", "<head", "<body")):
        return "html"
    return "md" if name.lower().endswith(".md") else "txt"
