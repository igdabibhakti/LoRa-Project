"""Interactive LoRe text/image demo using the reliable protocol simulator."""

import io
import os
import struct
import time
import zlib

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from PIL import Image

from lore_protocol import (
    CRC_SIZE,
    HEADER_SIZE,
    ContentType,
    FrameType,
    ProtocolError,
    make_data_frames,
    simulate_half_duplex_transfer,
)


SHARED_KEY = b"12345678901234567890123456789012"  # Demo key only; replace before deployment.
APPLICATION_HEADER_FORMAT = ">Q"


def print_hexdump(byte_data: bytes, max_bytes: int = 64, title: str = "HEX DUMP") -> None:
    """Print a conventional offset/hex/ASCII view."""

    print(
        f"\n--- [{title}] "
        f"(Menampilkan {min(len(byte_data), max_bytes)} dari {len(byte_data)} Bytes) ---"
    )
    view_data = byte_data[:max_bytes]
    for offset in range(0, len(view_data), 16):
        chunk = view_data[offset : offset + 16]
        hex_part = " ".join(f"{byte:02X}" for byte in chunk)
        ascii_part = "".join(chr(byte) if 32 <= byte <= 126 else "." for byte in chunk)
        print(f"{offset:04X}  {hex_part:<48}  |{ascii_part}|")
    if len(byte_data) > max_bytes:
        print(f"... ({len(byte_data) - max_bytes} bytes berikutnya tidak ditampilkan)")


def pack_application_payload(raw_data: bytes, sent_at_ms: int | None = None) -> bytes:
    """Add one send timestamp to the message, not to every radio packet."""

    actual_sent_at = int(time.time() * 1000) if sent_at_ms is None else sent_at_ms
    return struct.pack(APPLICATION_HEADER_FORMAT, actual_sent_at) + raw_data


def unpack_application_payload(payload: bytes) -> tuple[int, bytes]:
    header_size = struct.calcsize(APPLICATION_HEADER_FORMAT)
    if len(payload) < header_size:
        raise ValueError("application payload is missing its timestamp")
    sent_at_ms = struct.unpack(APPLICATION_HEADER_FORMAT, payload[:header_size])[0]
    return sent_at_ms, payload[header_size:]


def encryption(raw_data: bytes) -> bytes:
    aes = AESGCM(SHARED_KEY)
    nonce = os.urandom(12)
    cipher = aes.encrypt(nonce, raw_data, None)
    return nonce + cipher


def decryption(encrypted_data: bytes) -> bytes:
    if len(encrypted_data) < 28:  # 12-byte nonce + 16-byte GCM tag
        raise ValueError("encrypted payload is too short")
    aes = AESGCM(SHARED_KEY)
    nonce = encrypted_data[:12]
    cipher = encrypted_data[12:]
    return aes.decrypt(nonce, cipher, None)


def compress_and_pack_image(file_path: str) -> bytes:
    original_size = os.path.getsize(file_path)
    print(
        f"\n[Gambar] Ukuran file asli: {original_size} bytes "
        f"({original_size / 1024:.2f} KB)"
    )

    with open(file_path, "rb") as file:
        print_hexdump(
            file.read(),
            max_bytes=48,
            title="Hex Dump: File Gambar Asli Sebelum Diproses",
        )

    image = Image.open(file_path).convert("RGB")
    image.thumbnail((240, 240))

    jpeg_buffer = io.BytesIO()
    image.save(jpeg_buffer, format="JPEG", quality=50)
    jpeg_bytes = jpeg_buffer.getvalue()
    compressed_bytes = zlib.compress(jpeg_bytes, level=9)

    print(
        f"[Gambar] JPEG 240 px Q50: {len(jpeg_bytes)} bytes; "
        f"JPEG + zlib: {len(compressed_bytes)} bytes"
    )
    print_hexdump(
        compressed_bytes,
        max_bytes=48,
        title="Hex Dump: Payload Terkompresi (Siap Enkripsi)",
    )
    return compressed_bytes


def decompress_and_restore_image(
    raw_bytes: bytes,
    target_file: str = "foto_terima.jpg",
    upscale_file: str = "foto_upscale.png",
    show_image: bool = True,
) -> None:
    jpeg_bytes = zlib.decompress(raw_bytes)

    with open(target_file, "wb") as file:
        file.write(jpeg_bytes)
    print(f"\n[Penerima] JPEG disimpan: '{target_file}' ({len(jpeg_bytes)} bytes)")
    print_hexdump(jpeg_bytes, max_bytes=48, title="Hex Dump: File JPEG Terdekripsi")

    image = Image.open(io.BytesIO(jpeg_bytes))
    scale = min(480 / image.width, 480 / image.height)
    display_size = (
        max(1, round(image.width * scale)),
        max(1, round(image.height * scale)),
    )
    upscaled = image.resize(display_size, Image.Resampling.LANCZOS)
    upscaled.save(upscale_file)
    print(
        f"[Penerima] Preview proporsional disimpan: '{upscale_file}' "
        f"({display_size[0]}x{display_size[1]} px)"
    )
    if show_image:
        upscaled.show()


def parse_drop_indexes(raw_value: str) -> set[int]:
    if not raw_value.strip():
        return set()
    try:
        indexes = {int(part.strip()) for part in raw_value.split(",")}
    except ValueError as exc:
        raise ValueError("gunakan angka dipisahkan koma, misalnya 3,6") from exc
    if any(index < 0 for index in indexes):
        raise ValueError("nomor paket tidak boleh negatif")
    return indexes


def print_transfer_events(events) -> None:
    current_turn = None
    for event in events:
        if event.turn != current_turn:
            current_turn = event.turn
            print(f"\n--- Half-duplex turn {current_turn} ---")
        direction = (
            "TX A -> RX B"
            if event.direction == "sender->receiver"
            else "RX A <- TX B"
        )
        status = "OK" if event.delivered else "HILANG"
        if event.frame_type == FrameType.DATA:
            frame_name = f"DATA #{event.packet_index}"
        elif event.frame_type == FrameType.NACK:
            frame_name = f"NACK page #{event.packet_index}"
        else:
            frame_name = event.frame_type.name
        suffix = f" ({event.note})" if event.note else ""
        print(f"{direction:<14} {frame_name:<18} {status}{suffix}")


def main() -> None:
    print(f"{15 * '='} LORA RELIABLE TRANSFER DEMO {15 * '='}")
    choice = input("Pilih mode (1. Chat teks, 2. File gambar): ").strip()

    if choice == "1":
        content_type = ContentType.TEXT
        message = input("Ketik pesan chat: ")
        real_data = message.encode("utf-8")
        print_hexdump(real_data, max_bytes=48, title="Hex Dump: Teks Mentah (UTF-8)")
    elif choice == "2":
        content_type = ContentType.IMAGE
        photo_path = input("Masukkan nama/path file gambar: ").strip()
        real_data = compress_and_pack_image(photo_path)
    else:
        print("Mode tidak valid!")
        return

    application_data = pack_application_payload(real_data)
    encrypted_data = encryption(application_data)
    print_hexdump(
        encrypted_data,
        max_bytes=48,
        title="Hex Dump: Data Terenkripsi AES-GCM (Nonce + Cipher + Tag)",
    )

    demo_message_id = 0x12345678
    preview_frames = make_data_frames(
        encrypted_data,
        content_type,
        source_node_id=1,
        message_id=demo_message_id,
    )
    first_encoded = preview_frames[0].encode()
    print(
        f"\nHeader protokol: {HEADER_SIZE} B; CRC: {CRC_SIZE} B; "
        f"payload maksimum: 180 B"
    )
    print_hexdump(
        first_encoded,
        max_bytes=len(first_encoded),
        title="Paket DATA #0 lengkap",
    )

    raw_drop_indexes = input(
        "\nSimulasikan paket DATA hilang sekali "
        "(contoh 3,6; Enter = tanpa kehilangan): "
    )
    drop_indexes = parse_drop_indexes(raw_drop_indexes)
    out_of_range = sorted(
        index for index in drop_indexes if index >= len(preview_frames)
    )
    if out_of_range:
        raise ValueError(
            f"paket {out_of_range} di luar rentang 0..{len(preview_frames) - 1}"
        )

    result = simulate_half_duplex_transfer(
        encrypted_data,
        content_type,
        sender_node_id=1,
        receiver_node_id=2,
        message_id=demo_message_id,
        drop_data_once=drop_indexes,
    )
    print_transfer_events(result.events)

    decrypted_application = decryption(result.reconstructed_payload)
    sent_at_ms, received_data = unpack_application_payload(decrypted_application)
    print(
        f"\nTransfer selesai: message_id=0x{result.message_id:08X}, "
        f"{result.total_packets} DATA packet, "
        f"{result.retransmission_rounds} retransmission round"
    )
    print(f"Timestamp pengirim (sekali per pesan): {sent_at_ms} ms sejak Unix epoch")

    if content_type == ContentType.TEXT:
        print_hexdump(received_data, max_bytes=48, title="Payload teks didekripsi")
        print(f'\nPesan chat masuk: "{received_data.decode("utf-8")}"')
    else:
        decompress_and_restore_image(received_data)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, ProtocolError) as error:
        print(f"\n[ERROR] {error}")
