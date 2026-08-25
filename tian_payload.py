"""Tian Software application-payload codec for text and image messages.

This layer sits above lore_protocol.py. It handles the work Tian originally did
before packetization: application metadata, image compression and AES-GCM.
The ESP32/serial transport never needs to understand this format.

Trace dictionaries are intentionally observational only. They let the live
experiment show the classic Tian encode/decode process without changing the
reliability protocol.
"""
from __future__ import annotations

import io
import os
import struct
import time
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from PIL import Image

from lore_protocol import ContentType

SHARED_KEY = b"12345678901234567890123456789012"  # Demo/test key only.
APP_HEADER_FORMAT = ">Q"
APP_HEADER_SIZE = struct.calcsize(APP_HEADER_FORMAT)
TRACE_HEX_BYTES = 48

# Image filename metadata is inside the encrypted application payload. This is
# intentionally above lore_protocol.py: packet reliability does not need to know
# anything about filenames.
IMAGE_META_MAGIC = b"TIANIMG1"
IMAGE_NAME_LEN_FORMAT = ">H"
IMAGE_NAME_LEN_SIZE = struct.calcsize(IMAGE_NAME_LEN_FORMAT)


def hex_preview(data: bytes, limit: int = TRACE_HEX_BYTES) -> str:
    view = data[:limit]
    text = " ".join(f"{byte:02X}" for byte in view)
    if len(data) > limit:
        text += f" ... (+{len(data) - limit}B)"
    return text


@dataclass(frozen=True)
class PreparedPayload:
    content_type: ContentType
    encrypted: bytes
    original_size: int
    processed_size: int
    display_name: str
    trace: dict = field(default_factory=dict)


def encrypt(raw: bytes) -> bytes:
    nonce = os.urandom(12)
    cipher = AESGCM(SHARED_KEY).encrypt(nonce, raw, None)
    return nonce + cipher


def decrypt(encrypted: bytes) -> bytes:
    if len(encrypted) < 28:
        raise ValueError("encrypted payload is too short")
    nonce = encrypted[:12]
    return AESGCM(SHARED_KEY).decrypt(nonce, encrypted[12:], None)


def _pack_application(raw: bytes, sent_at_ms: int | None = None) -> bytes:
    timestamp = int(time.time() * 1000) if sent_at_ms is None else sent_at_ms
    return struct.pack(APP_HEADER_FORMAT, timestamp) + raw


def _unpack_application(raw: bytes) -> tuple[int, bytes]:
    if len(raw) < APP_HEADER_SIZE:
        raise ValueError("application payload is missing timestamp")
    sent_at_ms = struct.unpack(APP_HEADER_FORMAT, raw[:APP_HEADER_SIZE])[0]
    return sent_at_ms, raw[APP_HEADER_SIZE:]


def _safe_basename(name: str) -> str:
    """Keep only the basename so a transmitted name can never escape its folder."""
    return Path(name).name or "received.jpg"


def _pack_image_payload(filename: str, compressed_jpeg: bytes) -> bytes:
    safe_name = _safe_basename(filename)
    encoded_name = safe_name.encode("utf-8")
    if len(encoded_name) > 65535:
        raise ValueError("image filename is too long to transmit")
    return (
        IMAGE_META_MAGIC
        + struct.pack(IMAGE_NAME_LEN_FORMAT, len(encoded_name))
        + encoded_name
        + compressed_jpeg
    )


def _unpack_image_payload(application: bytes) -> tuple[str | None, bytes]:
    """Return embedded filename and compressed JPEG; accept old payloads too."""
    if not application.startswith(IMAGE_META_MAGIC):
        return None, application
    offset = len(IMAGE_META_MAGIC)
    if len(application) < offset + IMAGE_NAME_LEN_SIZE:
        raise ValueError("image metadata is truncated before filename length")
    name_len = struct.unpack(
        IMAGE_NAME_LEN_FORMAT,
        application[offset : offset + IMAGE_NAME_LEN_SIZE],
    )[0]
    offset += IMAGE_NAME_LEN_SIZE
    if len(application) < offset + name_len:
        raise ValueError("image metadata is truncated inside filename")
    filename = application[offset : offset + name_len].decode("utf-8", errors="replace")
    return _safe_basename(filename), application[offset + name_len :]


def _save_processed_image(jpeg: bytes, target: Path) -> int:
    """Preserve the transmitted filename while keeping its file format honest.

    Tian transports a resized JPEG internally. If the original filename used a
    non-JPEG extension, re-encode that received visual into the matching common
    image format before saving it under the original name.
    """
    suffix = target.suffix.lower()
    if suffix in {".jpg", ".jpeg", ".jfif", ""}:
        target.write_bytes(jpeg)
        return target.stat().st_size

    format_by_suffix = {
        ".png": "PNG",
        ".webp": "WEBP",
        ".bmp": "BMP",
        ".gif": "GIF",
        ".tif": "TIFF",
        ".tiff": "TIFF",
    }
    output_format = format_by_suffix.get(suffix)
    if output_format is None:
        # Unknown extension: preserve the exact requested name and the JPEG data.
        target.write_bytes(jpeg)
        return target.stat().st_size

    with Image.open(io.BytesIO(jpeg)) as image:
        image.save(target, format=output_format)
    return target.stat().st_size


def prepare_text(text: str) -> PreparedPayload:
    raw = text.encode("utf-8")
    sent_at_ms = int(time.time() * 1000)
    application = _pack_application(raw, sent_at_ms)
    encrypted = encrypt(application)
    return PreparedPayload(
        content_type=ContentType.TEXT,
        encrypted=encrypted,
        original_size=len(raw),
        processed_size=len(encrypted),
        display_name="text",
        trace={
            "direction": "ENCODE",
            "content_type": "TEXT",
            "display_name": "text",
            "sent_at_ms": sent_at_ms,
            "raw_bytes": len(raw),
            "raw_preview": text[:120],
            "raw_hex": hex_preview(raw),
            "application_header_bytes": APP_HEADER_SIZE,
            "application_bytes": len(application),
            "application_hex": hex_preview(application),
            "encryption": "AES-GCM (12B nonce + cipher + 16B tag)",
            "encrypted_bytes": len(encrypted),
            "encrypted_hex": hex_preview(encrypted),
        },
    )


def prepare_image(path: str | Path) -> PreparedPayload:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"image not found: {source}")

    original_size = source.stat().st_size
    source_bytes = source.read_bytes()
    image = Image.open(source).convert("RGB")
    original_dimensions = image.size
    image.thumbnail((240, 240))
    processed_dimensions = image.size

    jpeg = io.BytesIO()
    image.save(jpeg, format="JPEG", quality=50)
    jpeg_bytes = jpeg.getvalue()
    compressed = zlib.compress(jpeg_bytes, level=9)
    image_payload = _pack_image_payload(source.name, compressed)
    sent_at_ms = int(time.time() * 1000)
    application = _pack_application(image_payload, sent_at_ms)
    encrypted = encrypt(application)

    return PreparedPayload(
        content_type=ContentType.IMAGE,
        encrypted=encrypted,
        original_size=original_size,
        processed_size=len(encrypted),
        display_name=source.name,
        trace={
            "direction": "ENCODE",
            "content_type": "IMAGE",
            "display_name": source.name,
            "source_path": str(source),
            "sent_at_ms": sent_at_ms,
            "original_bytes": original_size,
            "original_dimensions": f"{original_dimensions[0]}x{original_dimensions[1]}",
            "source_hex": hex_preview(source_bytes),
            "rgb_thumbnail": f"{processed_dimensions[0]}x{processed_dimensions[1]}",
            "jpeg_quality": 50,
            "jpeg_bytes": len(jpeg_bytes),
            "jpeg_hex": hex_preview(jpeg_bytes),
            "compression": "zlib level 9",
            "compressed_bytes": len(compressed),
            "compressed_hex": hex_preview(compressed),
            "filename_metadata": source.name,
            "filename_metadata_bytes": len(image_payload) - len(compressed),
            "application_header_bytes": APP_HEADER_SIZE,
            "application_bytes": len(application),
            "encryption": "AES-GCM (12B nonce + cipher + 16B tag)",
            "encrypted_bytes": len(encrypted),
            "encrypted_hex": hex_preview(encrypted),
        },
    )


def decode_received(
    encrypted: bytes,
    content_type: ContentType,
    *,
    output_dir: str | Path = "received",
    output_stem: str = "received",
) -> dict:
    decrypted_application = decrypt(encrypted)
    sent_at_ms, application = _unpack_application(decrypted_application)
    trace = {
        "direction": "DECODE",
        "content_type": content_type.name,
        "encrypted_bytes": len(encrypted),
        "encrypted_hex": hex_preview(encrypted),
        "decryption": "AES-GCM authenticated decrypt",
        "decrypted_application_bytes": len(decrypted_application),
        "application_header_bytes": APP_HEADER_SIZE,
        "sent_at_ms": sent_at_ms,
        "application_bytes": len(application),
        "application_hex": hex_preview(application),
    }

    if content_type == ContentType.TEXT:
        text = application.decode("utf-8", errors="replace")
        trace.update({
            "result": "UTF-8 text",
            "decoded_bytes": len(application),
            "text_preview": text[:120],
        })
        return {
            "type": "text",
            "sent_at_ms": sent_at_ms,
            "text": text,
            "bytes": len(application),
            "trace": trace,
        }

    if content_type == ContentType.IMAGE:
        filename, compressed = _unpack_image_payload(application)
        jpeg = zlib.decompress(compressed)
        folder = Path(output_dir)
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / (filename if filename else f"{output_stem}.jpg")
        saved_bytes = _save_processed_image(jpeg, target)
        with Image.open(io.BytesIO(jpeg)) as image:
            dimensions = image.size
        trace.update({
            "filename": filename or target.name,
            "decompression": "zlib -> JPEG",
            "jpeg_bytes": len(jpeg),
            "jpeg_hex": hex_preview(jpeg),
            "dimensions": f"{dimensions[0]}x{dimensions[1]}",
            "saved_bytes": saved_bytes,
            "saved_path": str(target.resolve()),
        })
        return {
            "type": "image",
            "sent_at_ms": sent_at_ms,
            "filename": filename or target.name,
            "path": str(target.resolve()),
            "bytes": saved_bytes,
            "width": dimensions[0],
            "height": dimensions[1],
            "trace": trace,
        }

    trace.update({"result": "binary", "decoded_bytes": len(application)})
    return {
        "type": "binary",
        "sent_at_ms": sent_at_ms,
        "bytes": len(application),
        "data": application,
        "trace": trace,
    }
