"""Shared e2e setup: the stack's base URL, the Ollama stub, and a wait for the stack."""

import os
import time
from collections.abc import Iterator

import httpx
import ollama_stub
import pytest

HEALTH_TIMEOUT_S = 120
HEALTH_INTERVAL_S = 2


@pytest.fixture(scope="session")
def base_url() -> str:
    # Overrides the pytest-playwright fixture so page.goto("/") resolves against the stack.
    return os.environ.get("E2E_BASE_URL", "").rstrip("/")


@pytest.fixture(scope="session")
def stack(base_url: str) -> Iterator[str]:
    server = ollama_stub.start()
    try:
        _wait_healthy(base_url)
        yield base_url
    finally:
        server.shutdown()
        server.server_close()


def _wait_healthy(base_url: str) -> None:
    deadline = time.monotonic() + HEALTH_TIMEOUT_S
    while True:
        try:
            if httpx.get(f"{base_url}/api/health", timeout=5).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        if time.monotonic() > deadline:
            pytest.fail(f"{base_url}/api/health not ready after {HEALTH_TIMEOUT_S}s")
        time.sleep(HEALTH_INTERVAL_S)
