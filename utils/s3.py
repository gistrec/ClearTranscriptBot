"""Utilities for uploading files to Yandex Cloud S3."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import boto3


def upload_file(file_path: str | Path, bucket: str, object_name: Optional[str] = None) -> str:
    """Upload *file_path* to *bucket* in Yandex Cloud S3.

    Parameters
    ----------
    file_path:
        Local path to the file to upload.
    bucket:
        Name of the destination S3 bucket.
    object_name:
        Name of the object in the bucket. Defaults to the file name.

    Returns
    -------
    str
        The S3 URI of the uploaded object.
    """
    file_path = Path(file_path)
    if object_name is None:
        object_name = file_path.name

    session = boto3.session.Session(
        aws_access_key_id=os.environ.get("YC_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("YC_SECRET_ACCESS_KEY"),
    )
    s3 = session.client("s3", endpoint_url=os.environ.get("YC_S3_ENDPOINT"))
    s3.upload_file(str(file_path), bucket, object_name)
    return f"s3://{bucket}/{object_name}"
