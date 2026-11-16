from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.core.config import Tier


class Limits(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    max_upload_mb: int
    upload_types: list[str]
    max_docs: int
    chat_messages_per_hour: int


class MeResponse(BaseModel):
    tier: Tier
    email: str | None
    limits: Limits
    document_count: int
    guest_expires_at: datetime | None
