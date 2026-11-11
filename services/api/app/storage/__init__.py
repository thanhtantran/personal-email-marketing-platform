"""Object storage boundary for staged uploads and optional assets."""

from app.storage.base import ObjectInfo, ObjectStorage
from app.storage.s3 import S3ObjectStorage, get_storage

__all__ = ["ObjectInfo", "ObjectStorage", "S3ObjectStorage", "get_storage"]
