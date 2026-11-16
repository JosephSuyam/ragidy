"""Shared e2e setup: skip without E2E_BASE_URL, start the Ollama stub, wait for the stack."""

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
    url = os.environ.get("E2E_BASE_URL", "").rstrip("/")
    if not url:
        pytest.skip("E2E_BASE_URL is not set; start the e2e stack first")
    return url


@pytest.fixture(scope="session")
def stack(base_url: str) -> Iterator[str]:
    server = ollama_stub.start()
    try:
        _wait_healthy(base_url)
        yield base_url
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def client(stack: str) -> Iterator[httpx.Client]:
    # A new client per test means a new cookie jar, so each test is its own guest.
    with httpx.Client(base_url=stack, headers={"Origin": stack}, timeout=60) as http:
        yield http


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
