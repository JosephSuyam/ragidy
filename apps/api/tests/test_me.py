from dataclasses import asdict

import pytest
from conftest import app_client, no_db

from app.core.config import get_settings

pytestmark = pytest.mark.usefixtures("app_env")


def test_me_without_cookie_is_a_fresh_guest_and_runs_no_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAX_DOCS_GUEST", "2")
    with app_client(no_db) as client:
        response = client.get("/me")
    assert response.status_code == 200
    assert response.json() == {
        "tier": "guest",
        "email": None,
        "limits": asdict(get_settings().limits("guest")),
        "document_count": 0,
        "guest_expires_at": None,
    }
    assert response.json()["limits"]["max_docs"] == 2
