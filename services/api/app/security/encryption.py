"""Envelope encryption for provider credentials.

Each secret is encrypted with a randomly generated 256-bit data key, and that
data key is itself wrapped with the key-encryption key (KEK) resolved from
``ENCRYPTION_KEY_REF``. The serialized envelope carries both wrapped data key and
payload, so a single ``key_version`` column selects the KEK needed to open it
(docs/decisions/0004-secret-encryption.md).

Local development uses a mounted secret file; production must reference an
external KMS/secret manager, which ``Settings.require_production_safety``
enforces. Plaintext never reaches the database, an API response, or a log line.
"""

from __future__ import annotations

import base64
import binascii
import os
from collections.abc import Mapping
from functools import lru_cache

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import Settings, get_settings

KEY_BYTES = 32
NONCE_BYTES = 12
TAG_BYTES = 16
FILE_PREFIX = "file://"


class EncryptionKeyError(Exception):
    """Raised when key material cannot be resolved or an envelope cannot be opened."""


def load_key_material(ref: str) -> bytes:
    """Resolve a key reference into exactly :data:`KEY_BYTES` bytes.

    Accepted forms are a ``file://`` path to a mounted secret, a 64-character hex
    string, or a base64 string. Anything else is rejected loudly rather than
    silently deriving a weak key.
    """
    value = ref.strip()
    if not value:
        raise EncryptionKeyError("ENCRYPTION_KEY_REF is empty")
    if value.startswith(FILE_PREFIX):
        path = value[len(FILE_PREFIX) :]
        try:
            with open(path, "rb") as handle:  # noqa: PTH123 - explicit operator path
                material = handle.read().strip()
        except OSError as exc:
            raise EncryptionKeyError(f"cannot read encryption key file '{path}'") from exc
        return _coerce_material(material, source=path)
    return _coerce_material(value.encode("utf-8"), source="ENCRYPTION_KEY_REF")


def _coerce_material(material: bytes, *, source: str) -> bytes:
    if len(material) == KEY_BYTES:
        return material
    text = material.decode("utf-8", errors="ignore").strip()
    if len(text) == KEY_BYTES * 2:
        try:
            return binascii.unhexlify(text)
        except binascii.Error:
            pass
    try:
        decoded = base64.b64decode(text, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise EncryptionKeyError(
            f"key material from '{source}' is not {KEY_BYTES} raw bytes, hex or base64"
        ) from exc
    if len(decoded) != KEY_BYTES:
        raise EncryptionKeyError(
            f"key material from '{source}' must decode to {KEY_BYTES} bytes"
        )
    return decoded


class SecretBox:
    """AES-256-GCM envelope encryption bound to one key version."""

    def __init__(self, key: bytes, *, key_version: int) -> None:
        if len(key) != KEY_BYTES:
            raise EncryptionKeyError(f"key must be {KEY_BYTES} bytes")
        self._kek = AESGCM(key)
        self.key_version = key_version
        # Bind the version into the AEAD so a ciphertext cannot be reinterpreted
        # under a different key version.
        self._aad = f"key_version={key_version}".encode("ascii")

    def encrypt(self, plaintext: str) -> str:
        """Return a base64 envelope: nonce || wrapped data key || nonce || ciphertext."""
        data_key = os.urandom(KEY_BYTES)
        wrap_nonce = os.urandom(NONCE_BYTES)
        wrapped = self._kek.encrypt(wrap_nonce, data_key, self._aad)
        payload_nonce = os.urandom(NONCE_BYTES)
        payload = AESGCM(data_key).encrypt(payload_nonce, plaintext.encode("utf-8"), self._aad)
        return base64.b64encode(wrap_nonce + wrapped + payload_nonce + payload).decode("ascii")

    def decrypt(self, envelope: str) -> str:
        try:
            raw = base64.b64decode(envelope, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise EncryptionKeyError("credential envelope is not valid base64") from exc
        wrap_len = NONCE_BYTES + KEY_BYTES + TAG_BYTES
        if len(raw) < wrap_len + NONCE_BYTES + TAG_BYTES:
            raise EncryptionKeyError("credential envelope is truncated")
        wrap_nonce = raw[:NONCE_BYTES]
        wrapped = raw[NONCE_BYTES:wrap_len]
        payload_nonce = raw[wrap_len : wrap_len + NONCE_BYTES]
        payload = raw[wrap_len + NONCE_BYTES :]
        try:
            data_key = self._kek.decrypt(wrap_nonce, wrapped, self._aad)
            return AESGCM(data_key).decrypt(payload_nonce, payload, self._aad).decode("utf-8")
        except (InvalidTag, ValueError) as exc:
            raise EncryptionKeyError(
                f"credential envelope could not be opened with key version {self.key_version}"
            ) from exc


class SecretBoxProvider:
    """Holds the known key versions and selects one for encryption or decryption."""

    def __init__(self, keys: Mapping[int, bytes], *, active_version: int) -> None:
        if active_version not in keys:
            raise EncryptionKeyError(f"active key version {active_version} has no key material")
        self._boxes = {
            version: SecretBox(material, key_version=version)
            for version, material in keys.items()
        }
        self._active_version = active_version

    @property
    def active_version(self) -> int:
        return self._active_version

    @property
    def active(self) -> SecretBox:
        """The box used for new writes."""
        return self._boxes[self._active_version]

    def box_for(self, key_version: int) -> SecretBox:
        box = self._boxes.get(key_version)
        if box is None:
            raise EncryptionKeyError(f"no key material configured for version {key_version}")
        return box

    @classmethod
    def from_settings(cls, settings: Settings) -> SecretBoxProvider:
        version = settings.encryption_key_version
        return cls(
            {version: load_key_material(settings.encryption_key_ref)},
            active_version=version,
        )


@lru_cache
def get_secret_box_provider() -> SecretBoxProvider:
    return SecretBoxProvider.from_settings(get_settings())
