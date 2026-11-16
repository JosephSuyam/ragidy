import asyncio
from concurrent.futures import ThreadPoolExecutor

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_MAX_CONCURRENT_HASHES = 4

_hasher = PasswordHasher()
# Caps argon2's CPU and memory use; extra hashes queue here instead of in the default executor.
_pool = ThreadPoolExecutor(max_workers=_MAX_CONCURRENT_HASHES, thread_name_prefix="argon2")


async def hash_password(pw: str) -> str:
    return await asyncio.get_running_loop().run_in_executor(_pool, _hasher.hash, pw)


async def verify_password(hash: str, pw: str) -> bool:
    """True when `pw` matches `hash`; False on mismatch or an invalid hash."""
    try:
        return await asyncio.get_running_loop().run_in_executor(_pool, _hasher.verify, hash, pw)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(hash: str) -> bool:
    return _hasher.check_needs_rehash(hash)
