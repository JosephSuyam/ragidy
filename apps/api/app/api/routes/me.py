from fastapi import APIRouter

from app.api.deps import DbSession, ReadOwner
from app.schemas.me import MeResponse
from app.services.me import get_me

router = APIRouter(tags=["me"])


@router.get("/me")
async def me(db: DbSession, owner: ReadOwner) -> MeResponse:
    return await get_me(db, owner)
