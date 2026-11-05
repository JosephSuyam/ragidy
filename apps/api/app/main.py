from fastapi import FastAPI

from app.api.routes import health
from app.core.logging import configure_logging

configure_logging()
app = FastAPI(title="Ragidy")
app.include_router(health.router)
