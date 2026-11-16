from app.core import providers
from app.core.config import get_settings


async def embed_query(text: str) -> list[float]:
    """Embed a search query with the configured embed model; provider errors propagate unchanged."""
    return await providers.get_embed_model(get_settings()).aget_query_embedding(text)
