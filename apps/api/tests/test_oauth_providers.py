from typing import Any

import pytest

from app.core.oauth import PROVIDERS, Identity


@pytest.mark.parametrize(
    ("email_verified", "expected"),
    [(True, True), (False, False), ("true", False), (None, False)],
)
def test_google_identity_uses_email_verified(email_verified: Any, expected: bool) -> None:
    info = {"sub": 1234, "email": "alice@example.com", "email_verified": email_verified}
    identity = PROVIDERS["google"].to_identity([info])
    assert identity == Identity("1234", "alice@example.com", expected)


PRIMARY_UNVERIFIED = {"email": "old@example.com", "primary": True, "verified": False}
VERIFIED_SECONDARY = {"email": "work@example.com", "primary": False, "verified": True}
PRIMARY_VERIFIED = {"email": "alice@example.com", "primary": True, "verified": True}


@pytest.mark.parametrize(
    ("emails", "expected"),
    [
        (
            [PRIMARY_UNVERIFIED, VERIFIED_SECONDARY, PRIMARY_VERIFIED],
            Identity("42", "alice@example.com", True),
        ),
        ([PRIMARY_UNVERIFIED, VERIFIED_SECONDARY], Identity("42", None, False)),
        (
            [{"email": "x@example.com", "primary": "true", "verified": "true"}],
            Identity("42", None, False),
        ),
        ([], Identity("42", None, False)),
    ],
)
def test_github_identity_uses_primary_verified_email(
    emails: list[dict[str, Any]], expected: Identity
) -> None:
    assert PROVIDERS["github"].to_identity([{"id": 42, "login": "alice"}, emails]) == expected
