from __future__ import annotations

import struct
from typing import Iterable

from lore_protocol import CRC_SIZE, HEADER_SIZE, Frame, FrameType


def hex_preview(data: bytes, limit: int = 48) -> str:
    view = data[:limit]
    text = " ".join(f"{value:02X}" for value in view)
    if len(data) > limit:
        text += f" ... (+{len(data)-limit}B)"
    return text


def frame_metadata(raw: bytes) -> dict:
    frame = Frame.decode(raw)
    encoded_crc = struct.unpack(">H", raw[-CRC_SIZE:])[0]
    return {
        "frame_type": frame.frame_type.name,
        "content_type": frame.content_type.name,
        "source_node_id": frame.source_node_id,
        "message_id": f"0x{frame.message_id:08X}",
        "total_packets": frame.total_packets,
        "packet_index": frame.packet_index,
        "payload_bytes": len(frame.payload),
        "header_bytes": HEADER_SIZE,
        "crc_bytes": CRC_SIZE,
        "frame_bytes": len(raw),
        "crc16": f"0x{encoded_crc:04X}",
        "frame_hex": hex_preview(raw),
    }


def transfer_summary(raw_frames: Iterable[bytes]) -> dict:
    raws = list(raw_frames)
    frames = [Frame.decode(raw) for raw in raws]
    data = [frame for frame in frames if frame.frame_type == FrameType.DATA]
    if frames:
        first = frames[0]
        message_id = f"0x{first.message_id:08X}"
        content_type = first.content_type.name
    else:
        message_id = "-"
        content_type = "-"
    return {
        "message_id": message_id,
        "content_type": content_type,
        "data_frames": len(data),
        "data_indexes": [frame.packet_index for frame in data],
        "encoded_window_bytes": sum(len(raw) for raw in raws),
        "frame_count": len(raws),
        # Full frame metadata is still retained for panel TRACE/metadata views.
        # The node terminal no longer prints these a second time because its
        # [TX]/[RX] lines are the prioritized per-frame experiment record.
        "frames": [frame_metadata(raw) for raw in raws],
    }


def print_trace_block(title: str, trace: dict, prefix: str = "[EXPRIMT]") -> None:
    print(f"\n{prefix} === {title} ===", flush=True)
    preferred = [
        "direction", "content_type", "display_name", "source_path", "sent_at_ms",
        "raw_bytes", "raw_preview", "original_bytes", "original_dimensions",
        "rgb_thumbnail", "jpeg_quality", "jpeg_bytes", "compression",
        "compressed_bytes", "application_header_bytes", "application_bytes",
        "encryption", "encrypted_bytes", "decryption", "decrypted_application_bytes",
        "application_bytes", "result", "decoded_bytes", "text_preview",
        "decompression", "dimensions", "saved_path",
    ]
    printed = set()
    for key in preferred:
        if key in trace and key not in printed:
            print(f"{prefix} {key}: {trace[key]}", flush=True)
            printed.add(key)
    for key, value in trace.items():
        if key in printed or key.endswith("_hex"):
            continue
        print(f"{prefix} {key}: {value}", flush=True)
    for key, value in trace.items():
        if key.endswith("_hex"):
            print(f"{prefix} {key}: {value}", flush=True)


def print_transfer_summary(summary: dict, title: str = "TRANSMISSION WINDOW") -> None:
    """Print only the transmission-window summary on Tian node terminals.

    Per-frame details are intentionally NOT printed here anymore. The live node
    already prints every frame as [TX] or [RX], with the protocol command first
    (DATA/END/NACK/COMPLETE) followed by message/content/frame information.
    Keeping only one per-frame line makes direction and protocol state easy to
    scan while full frame metadata remains available to the panel TRACE view.
    """

    print(f"\n[EXPRIMT] === {title} ===", flush=True)
    print(
        f"[EXPRIMT] message_id={summary.get('message_id')} content={summary.get('content_type')}",
        flush=True,
    )
    print(
        f"[EXPRIMT] DATA frames={summary.get('data_frames')} indexes={summary.get('data_indexes')} "
        f"all_frames={summary.get('frame_count')} encoded_window={summary.get('encoded_window_bytes')}B",
        flush=True,
    )
    if "tx_delay_name" in summary:
        print(
            f"[EXPRIMT] tx_delay={summary.get('tx_delay_name')} "
            f"inter_frame_delay={summary.get('inter_frame_delay_ms', 0)}ms",
            flush=True,
        )
