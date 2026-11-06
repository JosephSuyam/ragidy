import pytest
from conftest import ORIGIN, app_client, no_db

pytestmark = pytest.mark.usefixtures("app_env")

MISMATCH = {"code": "origin_mismatch", "detail": "Request origin is not allowed"}


def test_post_without_origin_403() -> None:
    with app_client(no_db) as client:
        del client.headers["Origin"]
        response = client.post("/auth/logout")
    assert response.status_code == 403
    assert response.json() == MISMATCH


@pytest.mark.parametrize(
    "origin", ["https://evil.example", "http://localhost:5174", f"{ORIGIN}/", "null"]
)
def test_post_wrong_origin_403(origin: str) -> None:
    with app_client(no_db) as client:
        response = client.post("/auth/logout", headers={"Origin": origin})
    assert response.status_code == 403
    assert response.json() == MISMATCH
    assert "set-cookie" not in response.headers


def test_get_without_origin_passes() -> None:
    with app_client(no_db) as client:
        del client.headers["Origin"]
        response = client.get("/health")
    assert response.status_code == 200


def test_matching_origin_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://app.example.com")
    with app_client(no_db) as client:
        assert client.post("/auth/logout").status_code == 403
        response = client.post("/auth/logout", headers={"Origin": "https://app.example.com"})
    assert response.status_code == 204
