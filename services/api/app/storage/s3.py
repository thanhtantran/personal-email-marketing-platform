"""S3-compatible object storage client.

Works against any S3 API: managed object storage in production, a local
S3-compatible container for development. Calls are synchronous; async callers
run them in a threadpool so the event loop is never blocked.
"""

from __future__ import annotations

from functools import lru_cache

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError

from app.config import Settings, get_settings
from app.storage.base import ObjectInfo


class S3ObjectStorage:
    def __init__(self, settings: Settings) -> None:
        self._bucket = settings.object_storage_bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.object_storage_endpoint,
            aws_access_key_id=settings.object_storage_access_key,
            aws_secret_access_key=settings.object_storage_secret_key,
            region_name=settings.object_storage_region,
            use_ssl=settings.object_storage_use_tls,
            config=BotoConfig(signature_version="s3v4"),
        )

    def presign_put(
        self, key: str, *, expires_seconds: int, content_type: str = "text/csv"
    ) -> str:
        return self._client.generate_presigned_url(
            "put_object",
            Params={"Bucket": self._bucket, "Key": key, "ContentType": content_type},
            ExpiresIn=expires_seconds,
        )

    def head(self, key: str) -> ObjectInfo | None:
        try:
            response = self._client.head_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise
        return ObjectInfo(key=key, size=int(response.get("ContentLength", 0)))

    def put_bytes(self, key: str, data: bytes, *, content_type: str = "application/json") -> None:
        self._client.put_object(
            Bucket=self._bucket, Key=key, Body=data, ContentType=content_type
        )

    def get_bytes(self, key: str) -> bytes:
        response = self._client.get_object(Bucket=self._bucket, Key=key)
        return response["Body"].read()

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)


@lru_cache
def get_storage() -> S3ObjectStorage:
    return S3ObjectStorage(get_settings())
