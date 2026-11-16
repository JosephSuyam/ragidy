import uuid

import pytest
from conftest import EMAIL, app_client, no_db

DETAIL_KEYS = {"type", "loc", "msg"}


@pytest.mark.usefixtures("app_env")
def test_login_nul_password_422_does_not_echo_input() -> None:
    secret = uuid.uuid4().hex
    with app_client(no_db) as client:
        response = client.post(
            "/auth/login", json={"email": EMAIL, "password": f"secret\x00pw-{secret}"}
        )

    assert response.status_code == 422, response.text
    assert secret not in response.text
    detail = response.json()["detail"]
    assert [item["loc"] for item in detail] == [["body", "password"]]
    assert all(set(item) == DETAIL_KEYS for item in detail)


@pytest.mark.usefixtures("app_env")
def test_short_register_password_422_does_not_echo_input() -> None:
    secret = uuid.uuid4().hex
    with app_client(no_db) as client:
        response = client.post("/auth/register", json={"email": EMAIL, "password": secret[:7]})

    assert response.status_code == 422, response.text
    assert secret[:7] not in response.text
    detail = response.json()["detail"]
    assert [item["loc"] for item in detail] == [["body", "password"]]
    assert all(set(item) == DETAIL_KEYS for item in detail)
