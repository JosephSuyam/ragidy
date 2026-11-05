import threading
import time
from collections import deque
from ipaddress import IPv4Address, IPv6Network, ip_address


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
            stamps = self._hits.setdefault(key, deque())
            _prune(stamps, cutoff)
            if len(stamps) >= limit:
                return stamps[0] + self._window_s - now
            stamps.append(now)
            return None

    def clear(self) -> None:
        with self._lock:
            self._hits.clear()
            self._next_sweep = 0.0


def _prune(stamps: deque[float], cutoff: float) -> deque[float]:
    while stamps and stamps[0] <= cutoff:
        stamps.popleft()
    return stamps


guest_creations = SlidingWindow(3600)
