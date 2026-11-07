import asyncio
import socket
import time
from ipaddress import ip_address
from typing import Any

import pytest

from app.core.errors import AppError
from app.services import url_fetch
from app.services.url_fetch import fetch_url

pytestmark = pytest.mark.usefixtures("app_env")

BLOCKED = (422, "url_blocked")
FAILED = (422, "url_fetch_failed")
TOO_LARGE = (413, "too_large")


def fetch(url: str, max_bytes: int = 1024) -> tuple[bytes, str]:
    return asyncio.run(fetch_url(url, max_bytes))


def fetch_error(url: str, max_bytes: int = 1024) -> tuple[int, str]:
    with pytest.raises(AppError) as info:
        fetch(url, max_bytes)
    return info.value.status, info.value.code


@pytest.fixture
def no_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail the test if `fetch_url` opens an HTTP client."""

    def forbid(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("unexpected connection")

    monkeypatch.setattr(url_fetch.httpx, "AsyncClient", forbid)


@pytest.fixture
def fake_dns(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[str]]:
    """Answer each `*.invalid` host once from the returned dict; a second lookup fails."""
    answers: dict[str, list[str]] = {}
    real = asyncio.BaseEventLoop.getaddrinfo

    async def getaddrinfo(self: asyncio.BaseEventLoop, host: Any, port: Any, **kwargs: Any) -> Any:
        if not str(host).endswith(".invalid"):
            return await real(self, host, port, **kwargs)
        if host not in answers:
            raise socket.gaierror(socket.EAI_NONAME, f"no fake answer for {host}")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in answers.pop(host)]

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", getaddrinfo)
    return answers


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://10.0.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://0.0.0.0/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://localhost/",
        "file:///etc/passwd",
        "ftp://ftp.example.com/file.txt",
        "http:///no-host",
        "http://u:p@example.com/",
    ],
)
@pytest.mark.usefixtures("no_connect")
def test_blocked_urls(url: str) -> None:
    assert fetch_error(url) == BLOCKED


@pytest.mark.parametrize(
    ("ip", "allowed"),
    [
        ("93.184.215.14", True),
        ("::ffff:93.184.215.14", True),
        ("2606:4700::1111", True),
        ("100.64.0.1", False),
        ("192.168.1.1", False),
        ("::ffff:10.0.0.1", False),
        ("fe80::1", False),
        ("ff0e::1", False),
        ("2606:4700:4700::1111", True),
        ("::7f00:1", False),
        ("fec0::1", False),
        ("64:ff9b::1", False),
    ],
)
def test_is_allowed(ip: str, allowed: bool) -> None:
    assert url_fetch._is_allowed(ip_address(ip)) is allowed


@pytest.mark.usefixtures("allow_loopback")
def test_follows_three_redirects_and_returns_final_url(http_server: str) -> None:
    assert fetch(f"{http_server}/redirect/3") == (b"done", f"{http_server}/redirect/0")


@pytest.mark.usefixtures("allow_loopback")
def test_fourth_redirect_fails(http_server: str) -> None:
    assert fetch_error(f"{http_server}/redirect/4") == FAILED


@pytest.mark.usefixtures("allow_loopback")
@pytest.mark.parametrize(
    "location", ["http://10.0.0.1/", "file:///etc/passwd", "http://u:p@127.0.0.1/"]
)
def test_redirect_hop_is_checked(http_server: str, location: str) -> None:
    assert fetch_error(f"{http_server}/to?url={location}") == BLOCKED


@pytest.mark.usefixtures("allow_loopback")
def test_connects_to_vetted_ip_with_original_host_header(
    http_server: str, fake_dns: dict[str, list[str]]
) -> None:
    # fake_dns answers once, so the fetch only works if it connects to the IP it vetted.
    fake_dns["pinned.invalid"] = ["127.0.0.1"]
    port = http_server.rsplit(":", 1)[1]
    url = f"http://pinned.invalid:{port}/host"
    assert fetch(url) == (f"pinned.invalid:{port}".encode(), url)


@pytest.mark.usefixtures("no_connect")
def test_any_private_ip_in_the_dns_answer_blocks(fake_dns: dict[str, list[str]]) -> None:
    fake_dns["mixed.invalid"] = ["93.184.215.14", "10.0.0.1"]
    assert fetch_error("http://mixed.invalid/") == BLOCKED


@pytest.mark.usefixtures("no_connect")
@pytest.mark.parametrize("host", ["a" * 64 + ".com", "a..b"])
def test_bad_dns_label_fails_before_lookup(host: str) -> None:
    with pytest.raises(AppError) as info:
        fetch(f"http://{host}/")
    assert (info.value.status, info.value.code) == FAILED
    assert isinstance(info.value.__cause__, UnicodeError)  # IDNA encoding, not a DNS answer


@pytest.mark.usefixtures("allow_loopback")
def test_every_hop_asks_for_an_uncompressed_body(http_server: str) -> None:
    assert fetch(f"{http_server}/identity/2")[0] == b"done"


@pytest.mark.usefixtures("allow_loopback")
def test_compressed_body_fails(http_server: str) -> None:
    assert fetch_error(f"{http_server}/gzip") == FAILED


@pytest.mark.usefixtures("allow_loopback")
@pytest.mark.parametrize("route", ["bytes", "chunked"])
def test_body_of_exactly_the_limit_is_accepted(http_server: str, route: str) -> None:
    assert fetch(f"{http_server}/{route}/10", max_bytes=10)[0] == b"a" * 10


@pytest.mark.usefixtures("allow_loopback")
@pytest.mark.parametrize("route", ["bytes", "chunked", "claims"])
def test_body_over_the_limit_is_too_large(http_server: str, route: str) -> None:
    assert fetch_error(f"{http_server}/{route}/11", max_bytes=10) == TOO_LARGE


@pytest.mark.usefixtures("allow_loopback")
def test_non_2xx_fails(http_server: str) -> None:
    assert fetch_error(f"{http_server}/missing") == FAILED


@pytest.mark.usefixtures("allow_loopback")
def test_timeout_fails(http_server: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("URL_FETCH_TIMEOUT_SECONDS", "0.2")
    started = time.monotonic()
    assert fetch_error(f"{http_server}/slow") == FAILED
    assert time.monotonic() - started < 1.5  # the server answers after 2 s
