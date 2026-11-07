from pathlib import PurePosixPath

from fastapi import APIRouter, Request, Response
from fastapi.exceptions import RequestValidationError
from starlette.datastructures import UploadFile
from starlette.types import Message

from app.api.deps import DbSession, ReadOwner, client_ip_key, write_owner
from app.core.errors import AppError
from app.schemas.documents import DocumentOut, UrlIn
from app.services import documents

router = APIRouter(prefix="/documents", tags=["documents"])

# Allowance for multipart boundaries and part headers on top of the file size limit.
_MULTIPART_OVERHEAD = 16 * 1024


# No File/Form parameter: FastAPI would read and spool the whole body before the cap check.
@router.post("", status_code=202)
async def upload_document(
    request: Request, response: Response, db: DbSession, owner: ReadOwner
) -> DocumentOut:
    limits, max_bytes = documents.upload_limits(owner)
    await documents.check_cap(db, owner, limits.max_docs)
    data, filename = await _read_upload(request, max_bytes)
    source = PurePosixPath(filename.replace("\\", "/")).name or "upload"
    mime = documents.content_type(data, source, limits)
    doc = await documents.create_document(
        db, data, mime, source, limits.max_docs, lambda: write_owner(request, response, db, owner)
    )
    return DocumentOut.model_validate(doc)


@router.post("/url", status_code=202)
async def add_url(
    body: UrlIn, request: Request, response: Response, db: DbSession, owner: ReadOwner
) -> DocumentOut:
    limits, max_bytes = documents.upload_limits(owner)
    await documents.check_cap(db, owner, limits.max_docs)
    rate_key = str(owner.owner_id) if owner else client_ip_key(request)
    data, path = await documents.fetch_document_url(body.url, rate_key, max_bytes)
    mime = documents.content_type(data, path, limits)
    doc = await documents.create_document(
        db, data, mime, body.url, limits.max_docs, lambda: write_owner(request, response, db, owner)
    )
    return DocumentOut.model_validate(doc)


async def _read_upload(request: Request, max_bytes: int) -> tuple[bytes, str]:
    """The `file` part's bytes and filename; 413 as soon as the body passes the limit."""
    limit = max_bytes + _MULTIPART_OVERHEAD
    length = request.headers.get("content-length", "")
    if length.isdigit() and int(length) > limit:
        raise _too_large(max_bytes)
    received = 0

    async def receive() -> Message:
        nonlocal received
        message = await request.receive()
        received += len(message.get("body", b""))
        if received > limit:
            raise _too_large(max_bytes)
        return message

    form = await Request(request.scope, receive).form(max_files=1, max_fields=0)
    try:
        file = form.get("file")
        if not isinstance(file, UploadFile):
            raise RequestValidationError(
                [
                    {
                        "type": "missing",
                        "loc": ("body", "file"),
                        "msg": "Field required",
                        "input": None,
                    }
                ]
            )
        data = await file.read()
        filename = file.filename or ""
    finally:
        await form.close()
    if len(data) > max_bytes:
        raise _too_large(max_bytes)
    return data, filename


def _too_large(max_bytes: int) -> AppError:
    return AppError(413, "too_large", f"Files may be at most {max_bytes // (1024 * 1024)} MB")
