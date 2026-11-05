# Build context: repo root. docker build -f infrastructure/docker/api.Dockerfile .
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY apps/api/pyproject.toml apps/api/uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY apps/api/alembic.ini ./
COPY apps/api/alembic ./alembic
COPY apps/api/app ./app

FROM python:3.12-slim
RUN useradd --create-home --uid 1000 ragidy
WORKDIR /app
COPY --from=build --chown=ragidy /app /app
ENV PATH="/app/.venv/bin:$PATH"
USER ragidy
EXPOSE 8000
CMD ["fastapi", "run", "app/main.py", "--port", "8000", "--no-proxy-headers"]
