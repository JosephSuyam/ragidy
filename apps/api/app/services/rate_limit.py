import threading
import time
from collections import deque
from functools import lru_cache
from ipaddress import IPv4Address, IPv6Network, ip_address
from math import ceil

from app.core.config import get_settings
from app.core.errors import AppError


def ip_key(host: str | None) -> str:
    """Rate-limit key for a client: the IPv4 address, or the IPv6 /64."""
    if host is None:
        return "unknown"
    try:
        addr = ip_address(host)
    except ValueError:
        return host
    if isinstance(addr, IPv4Address):
        return str(addr)
    if addr.ipv4_mapped is not None:
        return str(addr.ipv4_mapped)
    # int() drops any zone id, which IPv6Network would reject.
    return str(IPv6Network((int(addr), 64), strict=False))


class SlidingWindow:
    # shortcut: in-memory counters assume a single API process; move them to Postgres
    # when the API runs as more than one replica.
    def __init__(self, window_s: float) -> None:
        self._window_s = window_s
        self._hits: dict[str, deque[float]] = {}
        self._next_sweep = 0.0
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int) -> float | None:
        """Record a hit and return None, or return the Retry-After seconds when over limit."""
        now = time.monotonic()
        cutoff = now - self._window_s
        with self._lock:
            # Sweeping every key on each hit blocks the event loop (an IPv6 /48 is 65,536 keys),
            # so sweep once per window; memory stays bounded by keys seen in about two windows.
            if now >= self._next_sweep:
                self._next_sweep = now + self._window_s
                for stale_key in list(self._hits):
                    if not _prune(self._hits[stale_key], cutoff):
                        del self._hits[stale_key]
            stamps = _prune(self._hits.setdefault(key, deque()), cutoff)
            if len(stamps) >= limit:
                return stamps[0] + self._window_s - now
            stamps.append(now)
            return None

    def discard(self, key: str) -> None:
        """Forget every hit recorded for `key`."""
        with self._lock:
            self._hits.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._hits.clear()
            self._next_sweep = 0.0


def _prune(stamps: deque[float], cutoff: float) -> deque[float]:
    while stamps and stamps[0] <= cutoff:
        stamps.popleft()
    return stamps


guest_creations = SlidingWindow(3600)
auth_requests = SlidingWindow(60)
url_fetches = SlidingWindow(3600)


@lru_cache
def login_failures() -> SlidingWindow:
    """Failed logins keyed `f"{email}|{ip_key}"`; built on first use so settings are loaded."""
    return SlidingWindow(get_settings().login_failure_window_minutes * 60)


def rate_limited(retry_after: float) -> AppError:
    return AppError(
        429,
        "rate_limited",
        "Too many requests; try again later",
        {"Retry-After": str(ceil(retry_after))},
    )
