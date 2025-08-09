"""Utilities for uploading files to Yandex Cloud S3."""
import os
from pathlib import Path
from typing import Optional

import boto3

S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY")
S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY")
S3_ENDPOINT = os.environ.get("S3_ENDPOINT")
S3_BUCKET = os.environ.get("S3_BUCKET")

if not all([S3_ACCESS_KEY, S3_SECRET_KEY, S3_ENDPOINT, S3_BUCKET]):
    raise RuntimeError(
        "S3_ACCESS_KEY, S3_SECRET_KEY, S3_ENDPOINT and S3_BUCKET must be set"
    )


def upload_file(file_path: str | Path, object_name: Optional[str] = None) -> str:
    """Upload *file_path* to Yandex Cloud S3.

    Parameters
    ----------
    file_path:
        Local path to the file to upload.
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
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
    )
    s3 = session.client("s3", endpoint_url=S3_ENDPOINT)
    s3.upload_file(str(file_path), S3_BUCKET, object_name)
    return f"{S3_ENDPOINT}/{S3_BUCKET}/{object_name}"
