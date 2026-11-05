import pytest
from conftest import app_client, no_db

from app.services import rate_limit
from app.services.rate_limit import SlidingWindow, ip_key


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("203.0.113.7", "203.0.113.7"),
        ("2001:db8:1:2:aaaa::1", "2001:db8:1:2::/64"),
        ("::ffff:203.0.113.7", "203.0.113.7"),
        (None, "unknown"),
        ("testclient", "testclient"),
        ("", ""),
        ("fe80::1%eth0", "fe80::/64"),
    ],
)
def test_ip_key(host: str | None, expected: str) -> None:
    assert ip_key(host) == expected


def test_ipv6_same_64_shares_key_and_other_64_differs() -> None:
    assert ip_key("2001:db8:1:2::1") == ip_key("2001:db8:1:2:ffff:ffff:ffff:ffff")
    assert ip_key("2001:db8:1:2::1") != ip_key("2001:db8:1:3::1")


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    now = [1000.0]
    monkeypatch.setattr(rate_limit.time, "monotonic", lambda: now[0])
    return now


def test_window_allows_limit_hits_then_returns_retry_after(clock: list[float]) -> None:
    window = SlidingWindow(60)
    assert [window.hit("k", 2) for _ in range(2)] == [None, None]
    clock[0] += 10
    assert window.hit("k", 2) == 50
    assert window.hit("other", 2) is None


def test_window_prunes_hits_older_than_window(clock: list[float]) -> None:
    window = SlidingWindow(60)
    window.hit("k", 1)
    clock[0] += 59.9
    retry_after = window.hit("k", 1)
    assert retry_after is not None and 0 < retry_after <= 60
    clock[0] += 0.1
    assert window.hit("k", 1) is None


def test_window_sweeps_other_keys_at_most_once_per_window(clock: list[float]) -> None:
    window = SlidingWindow(60)
    window.hit("stale", 1)  # first hit sweeps and schedules the next sweep at 1060
    clock[0] += 1
    window.hit("later", 1)
    clock[0] = 1060
    window.hit("k", 5)
    assert "stale" not in window._hits and "later" in window._hits
    clock[0] = 1100  # "later" is stale now, but the next sweep is not due until 1120
    window.hit("k", 5)
    assert "later" in window._hits
    clock[0] = 1120
    window.hit("k", 5)
    assert "later" not in window._hits


def test_window_clear_resets(clock: list[float]) -> None:
    window = SlidingWindow(60)
    window.hit("k", 1)
    window.clear()
    assert window.hit("k", 1) is None


@pytest.mark.usefixtures("app_env")
@pytest.mark.parametrize("peer", ["10.0.0.1", "127.0.0.1"])
def test_spoofed_forwarded_for_from_untrusted_peer_does_not_change_key(peer: str) -> None:
    # Empty TRUSTED_PROXIES trusts no peer, not even uvicorn's default 127.0.0.1.
    with app_client(no_db, client=(peer, 1)) as client:
        response = client.get("/_test/ip", headers={"X-Forwarded-For": "9.9.9.9"})
    assert response.json() == {"key": peer}
