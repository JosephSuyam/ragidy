import pytest
from pydantic import ValidationError
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.core.config import SUPPORTED_UPLOAD_TYPES, Settings, TierLimits

AUTH_SECRET = "test-auth-secret-0123456789abcdef"
POSITIVE_INT_FIELDS = [
    "upload_max_mb_guest",
    "upload_max_mb_user",
    "max_docs_guest",
    "max_docs_user",
    "guest_ttl_days",
    "session_ttl_days",
    "rate_limit_auth_per_minute",
    "login_max_failures",
    "login_failure_window_minutes",
    "guest_create_per_ip_per_hour",
    "chat_messages_per_hour_guest",
    "chat_messages_per_hour_user",
]

pytestmark = pytest.mark.usefixtures("clean_env")


def load() -> Settings:
    return Settings(_env_file=None)


def only_error_on(field: str) -> str:
    return rf"^1 validation error for Settings\n{field}\n"


def test_defaults() -> None:
    settings = load()
    assert settings.upload_max_bytes_guest == 3145728
    assert settings.upload_max_bytes_user == 5242880
    # Defaults skip the before-validator, so check them against the allowlist here.
    expected_types = sorted(SUPPORTED_UPLOAD_TYPES)
    assert settings.upload_types_guest == settings.upload_types_user == expected_types
    assert (settings.max_docs_guest, settings.max_docs_user) == (3, 20)
    assert (settings.guest_ttl_days, settings.session_ttl_days) == (7, 30)
    assert settings.public_base_url == "http://localhost:5173"
    assert settings.trusted_proxies == []
    limits = (
        settings.rate_limit_auth_per_minute,
        settings.login_max_failures,
        settings.login_failure_window_minutes,
        settings.guest_create_per_ip_per_hour,
        settings.chat_messages_per_hour_guest,
        settings.chat_messages_per_hour_user,
    )
    assert limits == (10, 5, 15, 10, 20, 100)


def test_upload_types_parse_comma_separated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UPLOAD_TYPES_GUEST", " PDF, txt ")
    monkeypatch.setenv("UPLOAD_TYPES_USER", "md")
    settings = load()
    assert settings.upload_types_guest == ["pdf", "txt"]
    assert settings.upload_types_user == ["md"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("upload_types_guest", "pdf,exe"),
        ("upload_types_user", " , "),
        ("auth_secret", "short"),
        ("trusted_proxies", "nope"),
        ("public_base_url", "ftp://x"),
        ("public_base_url", "http://x/path"),
        ("public_base_url", "notaurl"),
        ("public_base_url", "http://u:p@x"),
        ("public_base_url", "http://x?q=1"),
        ("public_base_url", "http://x#frag"),
        ("public_base_url", "http://x:abc"),
        ("public_base_url", "http://x:99999"),
    ],
)
def test_invalid_values_rejected(monkeypatch: pytest.MonkeyPatch, field: str, value: str) -> None:
    monkeypatch.setenv(field.upper(), value)
    with pytest.raises(ValidationError, match=only_error_on(field)):
        load()


@pytest.mark.parametrize("field", POSITIVE_INT_FIELDS)
def test_positive_int_rejects_zero(monkeypatch: pytest.MonkeyPatch, field: str) -> None:
    monkeypatch.setenv(field.upper(), "0")
    with pytest.raises(ValidationError, match=only_error_on(field)):
        load()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://app.example.com/", "https://app.example.com"),
        ("HTTPS://App.Example.com", "https://app.example.com"),
        ("https://x:443", "https://x"),
        ("http://x:80/", "http://x"),
        ("http://localhost:5173", "http://localhost:5173"),
        ("http://[::1]:8000", "http://[::1]:8000"),
    ],
)
def test_public_base_url_normalized_to_origin(
    monkeypatch: pytest.MonkeyPatch, value: str, expected: str
) -> None:
    monkeypatch.setenv("PUBLIC_BASE_URL", value)
    assert load().public_base_url == expected


def test_trusted_proxies_parse_networks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRUSTED_PROXIES", "10.0.0.0/8, 192.168.1.1")
    assert load().trusted_proxies == ["10.0.0.0/8", "192.168.1.1/32"]


def test_trusted_proxies_build_uvicorn_proxy_middleware(monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression: network objects here crashed ProxyHeadersMiddleware at startup.
    monkeypatch.setenv("TRUSTED_PROXIES", "10.0.0.0/8, 2001:db8::/32")
    ProxyHeadersMiddleware(app=None, trusted_hosts=load().trusted_proxies)  # type: ignore[arg-type]


def test_errors_never_leak_secret_values(monkeypatch: pytest.MonkeyPatch) -> None:
    auth_marker = "AUTHMARKER" * 4
    github_marker = "GITHUBSECRETMARKER"
    monkeypatch.setenv("AUTH_SECRET", auth_marker)
    monkeypatch.setenv("OAUTH_GOOGLE_CLIENT_ID", "id")
    monkeypatch.setenv("OAUTH_GITHUB_CLIENT_SECRET", github_marker)
    with pytest.raises(ValidationError, match="OAUTH_GOOGLE_CLIENT_SECRET") as exc:
        load()
    assert "input_value" not in str(exc.value)
    assert auth_marker not in str(exc.value)
    assert github_marker not in str(exc.value)


def test_short_auth_secret_error_omits_value(monkeypatch: pytest.MonkeyPatch) -> None:
    short_marker = "SHORTMARKER"
    monkeypatch.setenv("AUTH_SECRET", short_marker)
    with pytest.raises(ValidationError, match=only_error_on("auth_secret")) as exc:
        load()
    assert short_marker not in str(exc.value)


@pytest.mark.parametrize("provider", ["google", "github"])
def test_oauth_client_id_requires_auth_secret(
    monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    monkeypatch.setenv(f"OAUTH_{provider.upper()}_CLIENT_ID", "id")
    monkeypatch.setenv(f"OAUTH_{provider.upper()}_CLIENT_SECRET", "secret")
    with pytest.raises(ValidationError, match="AUTH_SECRET is required"):
        load()


@pytest.mark.parametrize("provider", ["google", "github"])
def test_oauth_client_id_requires_client_secret(
    monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    monkeypatch.setenv("AUTH_SECRET", AUTH_SECRET)
    monkeypatch.setenv(f"OAUTH_{provider.upper()}_CLIENT_ID", "id")
    with pytest.raises(ValidationError, match=f"OAUTH_{provider.upper()}_CLIENT_SECRET"):
        load()


@pytest.mark.parametrize("provider", ["google", "github"])
def test_oauth_fully_configured_loads(monkeypatch: pytest.MonkeyPatch, provider: str) -> None:
    monkeypatch.setenv("AUTH_SECRET", AUTH_SECRET)
    monkeypatch.setenv(f"OAUTH_{provider.upper()}_CLIENT_ID", "id")
    monkeypatch.setenv(f"OAUTH_{provider.upper()}_CLIENT_SECRET", "secret")
    settings = load()
    assert getattr(settings, f"oauth_{provider}_client_id") == "id"


@pytest.mark.parametrize(
    ("field", "value"), [("llm_provider", "UNKNOWNLLM"), ("embed_provider", "UNKNOWNEMBED")]
)
def test_unknown_provider_rejected(monkeypatch: pytest.MonkeyPatch, field: str, value: str) -> None:
    monkeypatch.setenv(field.upper(), value)
    with pytest.raises(ValidationError, match=only_error_on(field)) as exc:
        load()
    assert value not in str(exc.value)


def test_embed_provider_accepts_google(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMBED_PROVIDER", "google")
    assert load().embed_provider == "google"


def test_limits_map_per_tier_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    tier_env = {
        "UPLOAD_MAX_MB_GUEST": "2",
        "UPLOAD_MAX_MB_USER": "9",
        "UPLOAD_TYPES_GUEST": "pdf",
        "UPLOAD_TYPES_USER": "md,txt",
        "MAX_DOCS_GUEST": "4",
        "MAX_DOCS_USER": "40",
        "CHAT_MESSAGES_PER_HOUR_GUEST": "6",
        "CHAT_MESSAGES_PER_HOUR_USER": "60",
    }
    for name, value in tier_env.items():
        monkeypatch.setenv(name, value)
    settings = load()
    assert settings.limits("guest") == TierLimits(2, ["pdf"], 4, 6)
    assert settings.limits("user") == TierLimits(9, ["md", "txt"], 40, 60)


@pytest.mark.parametrize(
    ("url", "secure"), [("https://app.example.com", True), ("http://localhost:5173", False)]
)
def test_cookie_secure_follows_public_base_url_scheme(
    monkeypatch: pytest.MonkeyPatch, url: str, secure: bool
) -> None:
    monkeypatch.setenv("PUBLIC_BASE_URL", url)
    assert load().cookie_secure is secure
