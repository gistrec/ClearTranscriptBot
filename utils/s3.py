"""Utilities for uploading files to Yandex Cloud S3."""
import os
import boto3
import asyncio
import logging

from pathlib import Path
from typing import Optional

from utils.sentry import sentry_span


S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY")
S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY")
S3_ENDPOINT = os.environ.get("S3_ENDPOINT")
S3_BUCKET = os.environ.get("S3_BUCKET")

if not all([S3_ACCESS_KEY, S3_SECRET_KEY, S3_ENDPOINT, S3_BUCKET]):
    raise RuntimeError(
        "S3_ACCESS_KEY, S3_SECRET_KEY, S3_ENDPOINT and S3_BUCKET must be set"
    )


@sentry_span(op="s3.upload")
async def upload_file(
    file_path: str | Path, object_name: Optional[str] = None
) -> Optional[str]:
    """Upload *file_path* to Yandex Cloud S3.

    Returns the permanent object URL on success, or ``None`` on failure.
    """
    file_path = Path(file_path)
    if object_name is None:
        object_name = file_path.name

    def _upload() -> Optional[str]:
        try:
            session = boto3.session.Session(
                aws_access_key_id=S3_ACCESS_KEY,
                aws_secret_access_key=S3_SECRET_KEY,
            )
            s3 = session.client("s3", endpoint_url=S3_ENDPOINT)
            s3.upload_file(str(file_path), S3_BUCKET, object_name)
            return f"{S3_ENDPOINT}/{S3_BUCKET}/{object_name}"
        except Exception:
            logging.exception(f"Failed to upload {file_path} to S3")
            return None

    return await asyncio.to_thread(_upload)


@sentry_span(op="s3.signed_url")
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
        except Exception:
            logging.exception(f"Failed to generate signed URL for {object_name}")
            return None

    return await asyncio.to_thread(_sign)


@sentry_span(op="s3.download")
async def download_text(object_name: str) -> Optional[str]:
    """Download a text file from S3 and return its contents."""

    def _download() -> Optional[str]:
        try:
            session = boto3.session.Session(
                aws_access_key_id=S3_ACCESS_KEY,
                aws_secret_access_key=S3_SECRET_KEY,
            )
            s3 = session.client("s3", endpoint_url=S3_ENDPOINT)
            response = s3.get_object(Bucket=S3_BUCKET, Key=object_name)
            return response["Body"].read().decode("utf-8")
        except Exception:
            logging.exception(f"Failed to download {object_name} from S3")
            return None

    return await asyncio.to_thread(_download)


def object_name_from_url(plain_url: str) -> str:
    """Extract the S3 object key from a plain URL produced by upload_file."""
    prefix = f"{S3_ENDPOINT}/{S3_BUCKET}/"
    return plain_url.removeprefix(prefix)
