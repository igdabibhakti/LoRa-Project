"""Length-prefixed serial transport for encoded LoRe frames.

This module is intentionally protocol-agnostic. It transports one encoded Frame
at a time using a 2-byte big-endian length prefix. The same envelope can be
implemented on the ESP32 later.
"""

from __future__ import annotations

import struct
from typing import Protocol


LENGTH_FORMAT = ">H"
LENGTH_SIZE = struct.calcsize(LENGTH_FORMAT)
MAX_SERIAL_FRAME = 1024


class ByteStream(Protocol):
    def read(self, size: int) -> bytes: ...
    def write(self, data: bytes) -> int | None: ...
    def flush(self) -> None: ...


class SerialTransportError(IOError):
    pass


def _read_exact(stream: ByteStream, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = stream.read(size - len(data))
        if not chunk:
            raise SerialTransportError(
                f"serial stream ended/timed out after {len(data)} of {size} bytes"
            )
        data.extend(chunk)
    return bytes(data)


def encode_serial_envelope(frame_bytes: bytes) -> bytes:
    if not isinstance(frame_bytes, bytes):
        raise TypeError("frame_bytes must be bytes")
    if not frame_bytes:
        raise SerialTransportError("cannot send an empty frame")
    if len(frame_bytes) > MAX_SERIAL_FRAME:
        raise SerialTransportError(
            f"frame is {len(frame_bytes)} bytes; serial maximum is {MAX_SERIAL_FRAME}"
        )
    return struct.pack(LENGTH_FORMAT, len(frame_bytes)) + frame_bytes


def decode_serial_envelope(envelope: bytes) -> bytes:
    if len(envelope) < LENGTH_SIZE:
        raise SerialTransportError("serial envelope is missing its length prefix")
    frame_length = struct.unpack(LENGTH_FORMAT, envelope[:LENGTH_SIZE])[0]
    frame = envelope[LENGTH_SIZE:]
    if frame_length == 0 or frame_length > MAX_SERIAL_FRAME:
        raise SerialTransportError(f"invalid serial frame length: {frame_length}")
    if len(frame) != frame_length:
        raise SerialTransportError(
            f"serial envelope contains {len(frame)} frame bytes; expected {frame_length}"
        )
    return frame


class FramedSerialTransport:
    """Blocking frame transport over any pyserial-like byte stream."""

    def __init__(self, stream: ByteStream) -> None:
        self.stream = stream

    def send_frame(self, frame_bytes: bytes) -> None:
        envelope = encode_serial_envelope(frame_bytes)
        written = self.stream.write(envelope)
        if written is not None and written != len(envelope):
            raise SerialTransportError(
                f"serial write accepted {written} of {len(envelope)} bytes"
            )
        self.stream.flush()

    def receive_frame(self) -> bytes:
        prefix = _read_exact(self.stream, LENGTH_SIZE)
        frame_length = struct.unpack(LENGTH_FORMAT, prefix)[0]
        if frame_length == 0 or frame_length > MAX_SERIAL_FRAME:
            raise SerialTransportError(f"invalid serial frame length: {frame_length}")
        return _read_exact(self.stream, frame_length)
