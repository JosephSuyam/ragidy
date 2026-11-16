import asyncio
import time

from app.services.passwords import hash_password, needs_rehash, verify_password
from app.services.rate_limit import SlidingWindow
from app.services.tokens import sign, unsign

SECRET = "s" * 32


def test_password_hash_is_argon2id() -> None:
    async def run() -> tuple[str, bool, bool, bool]:
        hashed = await hash_password("correct horse")
        return (
            hashed,
            await verify_password(hashed, "correct horse"),
            await verify_password(hashed, "wrong"),
            await verify_password("not-a-hash", "correct horse"),
        )

    hashed, good, wrong, invalid = asyncio.run(run(), loop_factory=asyncio.SelectorEventLoop)
    assert hashed.startswith("$argon2id$")
    assert (good, wrong, invalid) == (True, False, False)
    assert not needs_rehash(hashed)


def test_unsign_rejects_tampered_and_expired() -> None:
    payload = {"state": "abc", "exp": time.time() + 60}
    value = sign(payload, SECRET)
    assert unsign(value, SECRET) == payload

    body, signature = value.split(".")
    tampered_body = sign({"state": "evil", "exp": payload["exp"]}, SECRET).split(".")[0]
    assert unsign(f"{tampered_body}.{signature}", SECRET) is None
    assert unsign(value, "x" * 32) is None
    assert unsign("garbage", SECRET) is None
    assert unsign(sign({"exp": time.time() - 1}, SECRET), SECRET) is None
    assert unsign(sign({"state": "no-exp"}, SECRET), SECRET) is None


def test_discard_forgets_key() -> None:
    window = SlidingWindow(60)
    assert window.hit("k", 1) is None
    retry_after = window.hit("k", 1)
    assert retry_after is not None and 0 < retry_after <= 60
    window.discard("k")
    assert window.hit("k", 1) is None
    window.discard("unknown")
    assert window.hit("k", 1) is not None
