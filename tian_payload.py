"""Tian Software application-payload codec for text and image messages.

This layer sits above lore_protocol.py. It handles the work Tian originally did
before packetization: application metadata, image compression and AES-GCM.
The ESP32/serial transport never needs to understand this format.
"""
from __future__ import annotations

import io
import os
import struct
import time
import zlib
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from PIL import Image

from lore_protocol import ContentType

SHARED_KEY = b"12345678901234567890123456789012"  # Demo/test key only.
APP_HEADER_FORMAT = ">Q"
APP_HEADER_SIZE = struct.calcsize(APP_HEADER_FORMAT)


@dataclass(frozen=True)
class PreparedPayload:
    content_type: ContentType
    encrypted: bytes
    original_size: int
    processed_size: int
    display_name: str


def encrypt(raw: bytes) -> bytes:
    nonce = os.urandom(12)
    cipher = AESGCM(SHARED_KEY).encrypt(nonce, raw, None)
    return nonce + cipher


def decrypt(encrypted: bytes) -> bytes:
    if len(encrypted) < 28:
        raise ValueError("encrypted payload is too short")
    nonce = encrypted[:12]
    return AESGCM(SHARED_KEY).decrypt(nonce, encrypted[12:], None)


def _pack_application(raw: bytes) -> bytes:
    return struct.pack(APP_HEADER_FORMAT, int(time.time() * 1000)) + raw


def _unpack_application(raw: bytes) -> tuple[int, bytes]:
    if len(raw) < APP_HEADER_SIZE:
        raise ValueError("application payload is missing timestamp")
    sent_at_ms = struct.unpack(APP_HEADER_FORMAT, raw[:APP_HEADER_SIZE])[0]
    return sent_at_ms, raw[APP_HEADER_SIZE:]


def prepare_text(text: str) -> PreparedPayload:
    raw = text.encode("utf-8")
    encrypted = encrypt(_pack_application(raw))
    return PreparedPayload(
        content_type=ContentType.TEXT,
        encrypted=encrypted,
        original_size=len(raw),
        processed_size=len(encrypted),
        display_name="text",
    )


def prepare_image(path: str | Path) -> PreparedPayload:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"image not found: {source}")

    original_size = source.stat().st_size
    image = Image.open(source).convert("RGB")
    image.thumbnail((240, 240))

    jpeg = io.BytesIO()
    image.save(jpeg, format="JPEG", quality=50)
    compressed = zlib.compress(jpeg.getvalue(), level=9)
    encrypted = encrypt(_pack_application(compressed))

    return PreparedPayload(
        content_type=ContentType.IMAGE,
        encrypted=encrypted,
        original_size=original_size,
        processed_size=len(encrypted),
        display_name=source.name,
    )


def decode_received(
    encrypted: bytes,
    content_type: ContentType,
    *,
    output_dir: str | Path = "received",
    output_stem: str = "received",
) -> dict:
    sent_at_ms, application = _unpack_application(decrypt(encrypted))

    if content_type == ContentType.TEXT:
        return {
            "type": "text",
            "sent_at_ms": sent_at_ms,
            "text": application.decode("utf-8", errors="replace"),
            "bytes": len(application),
        }

    if content_type == ContentType.IMAGE:
        jpeg = zlib.decompress(application)
        folder = Path(output_dir)
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{output_stem}.jpg"
        target.write_bytes(jpeg)
        with Image.open(io.BytesIO(jpeg)) as image:
            dimensions = image.size
        return {
            "type": "image",
            "sent_at_ms": sent_at_ms,
            "path": str(target.resolve()),
            "bytes": len(jpeg),
            "width": dimensions[0],
            "height": dimensions[1],
        }

    return {
        "type": "binary",
        "sent_at_ms": sent_at_ms,
        "bytes": len(application),
        "data": application,
    }
