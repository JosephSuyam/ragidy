from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.repositories.documents import count_documents
from app.schemas.me import Limits, MeResponse
from app.services.owners import CurrentOwner


async def get_me(db: AsyncSession, owner: CurrentOwner | None) -> MeResponse:
    tier = owner.tier if owner else "guest"
    limits = Limits.model_validate(get_settings().limits(tier))
    if owner is None:
        return MeResponse(
            tier=tier, email=None, limits=limits, document_count=0, guest_expires_at=None
        )
    return MeResponse(
        tier=tier,
        email=owner.email,
        limits=limits,
        document_count=await count_documents(db, owner.owner_id),
        guest_expires_at=owner.guest_expires_at,
    )
