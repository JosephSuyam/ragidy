import asyncio
import socket
from ipaddress import IPv4Address, IPv6Address, ip_address

import httpx

from app.core.config import get_settings
from app.core.errors import AppError

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_MAX_REDIRECTS = 3


async def fetch_url(url: str, max_bytes: int) -> tuple[bytes, str]:
    """Fetch a public http(s) URL; return the body and the final URL after redirects."""
    try:
        async with asyncio.timeout(get_settings().url_fetch_timeout_seconds):
            return await _fetch(url, max_bytes)
    # UnicodeError: getaddrinfo's IDNA encoding rejects bad labels (`a..b`, a 64-char label).
    except (TimeoutError, httpx.HTTPError, socket.gaierror, UnicodeError) as exc:
        raise _failed() from exc


async def _fetch(url: str, max_bytes: int) -> tuple[bytes, str]:
    current = _parse(url)
    for _ in range(_MAX_REDIRECTS + 1):
        host = current.raw_host.decode("ascii")
        ip = await _resolve(host, current.port or (443 if current.scheme == "https" else 80))
        # Connect to the vetted IP, not the hostname, so a second DNS answer cannot swap it.
        # httpcore passes sni_hostname to TLS as server_hostname, so the cert is checked for `host`.
        target = current.copy_with(host=ip)
        extensions = {"sni_hostname": host} if current.scheme == "https" else {}
        # identity: a compressed body could decode far past max_bytes inside one chunk.
        headers = {"Host": current.netloc.decode("ascii"), "Accept-Encoding": "identity"}
        # A client per hop: a pooled TLS connection must not serve a different hostname.
        async with (
            httpx.AsyncClient(trust_env=False, follow_redirects=False, verify=True) as client,
            client.stream("GET", target, headers=headers, extensions=extensions) as response,
        ):
            location = response.headers.get("location")
            if response.status_code in _REDIRECT_STATUSES and location:
                current = _parse(location, current)
                continue
            if not response.is_success:
                raise _failed()
            return await _read(response, max_bytes), str(current)
    raise _failed()


def _parse(url_or_location: str, base: httpx.URL | None = None) -> httpx.URL:
    try:
        url = base.join(url_or_location) if base else httpx.URL(url_or_location)
    except httpx.InvalidURL as exc:
        raise _blocked() from exc
    if url.scheme not in {"http", "https"} or not url.raw_host or url.userinfo:
        raise _blocked()
    return url


async def _resolve(host: str, port: int) -> str:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    ips = [ip_address(info[4][0]) for info in infos]
    if not ips or not all(_is_allowed(ip) for ip in ips):
        raise _blocked()
    # IPv4 first: many hosts (and Docker networks) have no IPv6 route, and only one IP is tried.
    return str(min(ips, key=lambda ip: ip.version))


def _is_allowed(ip: IPv4Address | IPv6Address) -> bool:
    if isinstance(ip, IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    site_local = isinstance(ip, IPv6Address) and ip.is_site_local
    return ip.is_global and not (ip.is_multicast or ip.is_reserved or site_local)


async def _read(response: httpx.Response, max_bytes: int) -> bytes:
    if response.headers.get("content-encoding", "identity").strip().lower() != "identity":
        raise _failed()
    length = response.headers.get("content-length", "")
    if length.isdigit() and int(length) > max_bytes:
        raise _too_large()
    body = bytearray()
    async for chunk in response.aiter_raw():
        body += chunk
        if len(body) > max_bytes:
            raise _too_large()
    return bytes(body)


def _blocked() -> AppError:
    return AppError(422, "url_blocked", "This URL is not allowed")


def _failed() -> AppError:
    return AppError(422, "url_fetch_failed", "Could not fetch this URL")


def _too_large() -> AppError:
    return AppError(413, "too_large", "The fetched content is too large")
