import asyncio
from contextlib import suppress
from functools import lru_cache
from typing import TYPE_CHECKING
from uuid import UUID

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.core.config import get_settings

if TYPE_CHECKING:
    from types_boto3_s3.client import S3Client

_CONFIG = Config(
    s3={"addressing_style": "path"},
    # boto3 >= 1.36 sends CRC checksums by default; S3-compatible stores like SeaweedFS reject them.
    request_checksum_calculation="when_required",
    response_checksum_validation="when_required",
    # Standard mode retries connection errors, throttling and 5xx: 3 attempts in total.
    retries={"mode": "standard", "max_attempts": 3},
    connect_timeout=10,
    read_timeout=60,
)


def document_key(id: UUID) -> str:
    """The object key of a document's raw file (ADR 0002)."""
    return f"documents/{id}"


@lru_cache
def _client() -> "S3Client":
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        region_name=settings.s3_region,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key.get_secret_value(),
        config=_CONFIG,
    )


def _put(key: str, data: bytes, content_type: str) -> None:
    client, bucket = _client(), get_settings().s3_bucket
    try:
        client.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "NoSuchBucket":
            raise
        # shortcut: no LocationConstraint, so AWS outside us-east-1 needs the bucket made first.
        # A concurrent upload may have created it already.
        with suppress(client.exceptions.BucketAlreadyOwnedByYou):
            client.create_bucket(Bucket=bucket)
        client.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)


async def put_object(key: str, data: bytes, content_type: str) -> None:
    await asyncio.to_thread(_put, key, data, content_type)


async def delete_object(key: str) -> None:
    await asyncio.to_thread(_client().delete_object, Bucket=get_settings().s3_bucket, Key=key)


def _get(key: str) -> tuple[bytes, str]:
    obj = _client().get_object(Bucket=get_settings().s3_bucket, Key=key)
    with obj["Body"] as body:
        return body.read(), obj["ContentType"]


async def get_object(key: str) -> tuple[bytes, str]:
    """The object's bytes and its stored Content-Type."""
    return await asyncio.to_thread(_get, key)
