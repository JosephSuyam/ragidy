import asyncio
import io
import os
import uuid
from collections.abc import Iterator
from contextlib import suppress

import boto3
import pytest
from botocore.exceptions import ClientError
from botocore.response import StreamingBody
from botocore.stub import Stubber

from app.core import storage

S3_ENV = ("S3_ENDPOINT_URL", "S3_BUCKET", "S3_REGION", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY")
PUT = {"Bucket": "ragidy", "Key": "documents/1", "Body": b"hello", "ContentType": "text/plain"}


def put(key: str = "documents/1", data: bytes = b"hello", content_type: str = "text/plain") -> None:
    asyncio.run(storage.put_object(key, data, content_type))


@pytest.fixture
def stub(app_env: None, monkeypatch: pytest.MonkeyPatch) -> Iterator[Stubber]:
    """The storage client with stubbed S3 responses; every queued response must be used."""
    client = boto3.client(
        "s3",
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
        config=storage._CONFIG,
    )
    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: client)
    with Stubber(client) as stubber:
        yield stubber
        stubber.assert_no_pending_responses()


def test_put_creates_missing_bucket_and_retries(stub: Stubber) -> None:
    stub.add_client_error("put_object", "NoSuchBucket", http_status_code=404, expected_params=PUT)
    stub.add_response("create_bucket", {}, {"Bucket": "ragidy"})
    stub.add_response("put_object", {}, PUT)
    put()


def test_put_tolerates_bucket_created_concurrently(stub: Stubber) -> None:
    stub.add_client_error("put_object", "NoSuchBucket", http_status_code=404, expected_params=PUT)
    stub.add_client_error("create_bucket", "BucketAlreadyOwnedByYou", http_status_code=409)
    stub.add_response("put_object", {}, PUT)
    put()


def test_put_raises_other_errors_without_creating_a_bucket(stub: Stubber) -> None:
    stub.add_client_error("put_object", "AccessDenied", http_status_code=403, expected_params=PUT)
    with pytest.raises(ClientError, match="AccessDenied"):
        put()


def test_delete_object(stub: Stubber) -> None:
    stub.add_response("delete_object", {}, {"Bucket": "ragidy", "Key": "documents/1"})
    asyncio.run(storage.delete_object("documents/1"))


def test_get_object_returns_body_and_content_type(stub: Stubber) -> None:
    body = StreamingBody(io.BytesIO(b"hello"), 5)
    stub.add_response(
        "get_object",
        {"Body": body, "ContentType": "text/plain"},
        {"Bucket": "ragidy", "Key": "documents/1"},
    )

    assert asyncio.run(storage.get_object("documents/1")) == (b"hello", "text/plain")


def test_get_object_raises_for_a_missing_key(stub: Stubber) -> None:
    stub.add_client_error("get_object", "NoSuchKey", http_status_code=404)
    with pytest.raises(ClientError, match="NoSuchKey"):
        asyncio.run(storage.get_object("documents/1"))


@pytest.fixture(scope="session")
def s3_env() -> dict[str, str]:
    """S3_* from the environment at session start, before `clean_env` strips them."""
    if "S3_ACCESS_KEY_ID" not in os.environ:
        reason = "S3_* env vars are not set; export them to run against SeaweedFS (make s3)"
        if os.environ.get("CI"):
            pytest.fail(reason)
        pytest.skip(reason)
    return {name: os.environ[name] for name in S3_ENV if name in os.environ}


@pytest.mark.integration
def test_seaweedfs_round_trip_in_a_new_bucket(
    s3_env: dict[str, str], app_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in s3_env.items():
        monkeypatch.setenv(name, value)
    bucket = f"ragidy-test-{uuid.uuid4().hex[:12]}"
    monkeypatch.setenv("S3_BUCKET", bucket)
    s3 = storage._client()
    try:
        put("documents/a", b"%PDF-1.7", "application/pdf")  # NoSuchBucket, then created
        put("documents/b", b"hello", "text/plain")

        head = s3.head_object(Bucket=bucket, Key="documents/a")
        assert head["ContentType"] == "application/pdf"
        got = s3.get_object(Bucket=bucket, Key="documents/b")
        assert (got["Body"].read(), got["ContentType"]) == (b"hello", "text/plain")

        asyncio.run(storage.delete_object("documents/a"))
        with pytest.raises(ClientError) as info:
            s3.head_object(Bucket=bucket, Key="documents/a")
        assert info.value.response["Error"]["Code"] == "404"
    finally:
        with suppress(ClientError):
            s3.delete_object(Bucket=bucket, Key="documents/a")
            s3.delete_object(Bucket=bucket, Key="documents/b")
            s3.delete_bucket(Bucket=bucket)
