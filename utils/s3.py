"""Utilities for uploading files to Yandex Cloud S3."""
import os
import boto3
import asyncio
import logging
import sentry_sdk

from pathlib import Path
from typing import Optional


S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY")
S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY")
S3_ENDPOINT = os.environ.get("S3_ENDPOINT")
S3_BUCKET = os.environ.get("S3_BUCKET")

if not all([S3_ACCESS_KEY, S3_SECRET_KEY, S3_ENDPOINT, S3_BUCKET]):
    raise RuntimeError(
        "S3_ACCESS_KEY, S3_SECRET_KEY, S3_ENDPOINT and S3_BUCKET must be set"
    )


async def upload_file(
    file_path: str | Path, object_name: Optional[str] = None
) -> tuple[str | None, str | None]:
    """Upload *file_path* to Yandex Cloud S3.

    Returns a tuple of ``(plain_url, signed_url)`` where *plain_url* is the
    permanent object URL and *signed_url* is a one-hour signed URL suitable
    for passing to external services like Replicate.
    Returns ``None`` if the upload failed.
    """
    file_path = Path(file_path)
    if object_name is None:
        object_name = file_path.name

    def _upload() -> tuple[str | None, str | None]:
        try:
            session = boto3.session.Session(
                aws_access_key_id=S3_ACCESS_KEY,
                aws_secret_access_key=S3_SECRET_KEY,
            )
            s3 = session.client("s3", endpoint_url=S3_ENDPOINT)
            s3.upload_file(str(file_path), S3_BUCKET, object_name)

            plain_url = f"{S3_ENDPOINT}/{S3_BUCKET}/{object_name}"
            signed_url = s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": S3_BUCKET, "Key": object_name},
                ExpiresIn=3600,
            )

            return plain_url, signed_url
        except Exception as e:
            logging.error(f"Failed to upload {file_path} to S3: {e}")

            if os.getenv("ENABLE_SENTRY") == "1":
                sentry_sdk.capture_exception(e)

            return None, None

    return await asyncio.to_thread(_upload)


async def get_signed_url(object_name: str, expires_in: int = 3600) -> Optional[str]:
    """Generate a fresh presigned URL for an existing S3 object."""

    def _sign() -> Optional[str]:
        try:
            session = boto3.session.Session(
                aws_access_key_id=S3_ACCESS_KEY,
                aws_secret_access_key=S3_SECRET_KEY,
            )
            s3 = session.client("s3", endpoint_url=S3_ENDPOINT)
            return s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": S3_BUCKET, "Key": object_name},
                ExpiresIn=expires_in,
            )
        except Exception as e:
            logging.error(f"Failed to generate signed URL for {object_name}: {e}")

            if os.getenv("ENABLE_SENTRY") == "1":
                sentry_sdk.capture_exception(e)

            return None

    return await asyncio.to_thread(_sign)


def object_name_from_url(plain_url: str) -> str:
    """Extract the S3 object key from a plain URL produced by upload_file."""
    prefix = f"{S3_ENDPOINT}/{S3_BUCKET}/"
    return plain_url.removeprefix(prefix)
