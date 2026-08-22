"""Binary framing and half-duplex reliability for the LoRe project.

The module deliberately knows nothing about images, encryption, serial ports, or
any particular LoRa library. A future ESP32 transport only needs to move the
encoded frame bytes between the laptop and the radio.
"""

from __future__ import annotations

import binascii
import secrets
import struct
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Iterable, Sequence


MAGIC_HEADER = 0xAA55
PROTOCOL_VERSION = 1
CHUNK_SIZE = 180

# magic, version, frame type, content type, source node, message ID,
# total/page count, packet/page index, payload length
HEADER_FORMAT = ">HBBBHIHHB"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
CRC_FORMAT = ">H"
CRC_SIZE = struct.calcsize(CRC_FORMAT)
MAX_PAYLOAD_SIZE = CHUNK_SIZE
MAX_NACK_INDEXES = CHUNK_SIZE // 2


class ProtocolError(ValueError):
    """Raised when a frame or a transfer violates the protocol."""


class FrameType(IntEnum):
    DATA = 1
    END = 2
    NACK = 3
    COMPLETE = 4


class ContentType(IntEnum):
    TEXT = 1
    IMAGE = 2
    BINARY = 3


class SenderState(IntEnum):
    READY = 1
    WAITING_FOR_RESPONSE = 2
    COMPLETE = 3
    FAILED = 4


def _require_uint(name: str, value: int, bits: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ProtocolError(f"{name} must be an integer")
    if not 0 <= value <= (1 << bits) - 1:
        raise ProtocolError(f"{name} does not fit in uint{bits}: {value}")


def crc16(data: bytes) -> int:
    """Return CRC-16/CCITT-FALSE for header and payload bytes."""

    return binascii.crc_hqx(data, 0xFFFF)


@dataclass(frozen=True)
class Frame:
    frame_type: FrameType
    content_type: ContentType
    source_node_id: int
    message_id: int
    total_packets: int = 0
    packet_index: int = 0
    payload: bytes = b""
    version: int = PROTOCOL_VERSION

    def __post_init__(self) -> None:
        try:
            frame_type = FrameType(self.frame_type)
            content_type = ContentType(self.content_type)
        except ValueError as exc:
            raise ProtocolError(str(exc)) from exc

        object.__setattr__(self, "frame_type", frame_type)
        object.__setattr__(self, "content_type", content_type)

        _require_uint("version", self.version, 8)
        _require_uint("source_node_id", self.source_node_id, 16)
        _require_uint("message_id", self.message_id, 32)
        _require_uint("total_packets", self.total_packets, 16)
        _require_uint("packet_index", self.packet_index, 16)

        if not isinstance(self.payload, bytes):
            raise ProtocolError("payload must be bytes")
        if len(self.payload) > MAX_PAYLOAD_SIZE:
            raise ProtocolError(
                f"payload is {len(self.payload)} bytes; maximum is {MAX_PAYLOAD_SIZE}"
            )

        if self.frame_type == FrameType.DATA:
            if self.total_packets == 0:
                raise ProtocolError("DATA frame total_packets cannot be zero")
            if self.packet_index >= self.total_packets:
                raise ProtocolError("DATA packet_index must be below total_packets")
            if len(self.payload) > CHUNK_SIZE:
                raise ProtocolError(
                    f"DATA payload is {len(self.payload)} bytes; chunk size is {CHUNK_SIZE}"
                )

        if self.frame_type in (FrameType.END, FrameType.COMPLETE) and self.payload:
            raise ProtocolError(f"{self.frame_type.name} frame must not have a payload")

        if self.frame_type == FrameType.NACK and len(self.payload) % 2:
            raise ProtocolError("NACK payload must contain uint16 packet indexes")

    def encode(self) -> bytes:
        header = struct.pack(
            HEADER_FORMAT,
            MAGIC_HEADER,
            self.version,
            int(self.frame_type),
            int(self.content_type),
            self.source_node_id,
            self.message_id,
            self.total_packets,
            self.packet_index,
            len(self.payload),
        )
        body = header + self.payload
        return body + struct.pack(CRC_FORMAT, crc16(body))

    @classmethod
    def decode(cls, packet: bytes) -> "Frame":
        if not isinstance(packet, bytes):
            raise ProtocolError("encoded packet must be bytes")
        if len(packet) < HEADER_SIZE + CRC_SIZE:
            raise ProtocolError("packet is shorter than the protocol header")

        header = packet[:HEADER_SIZE]
        (
            magic,
            version,
            frame_type,
            content_type,
            source_node_id,
            message_id,
            total_packets,
            packet_index,
            payload_length,
        ) = struct.unpack(HEADER_FORMAT, header)

        if magic != MAGIC_HEADER:
            raise ProtocolError(f"invalid magic header: 0x{magic:04X}")
        if version != PROTOCOL_VERSION:
            raise ProtocolError(
                f"unsupported protocol version {version}; expected {PROTOCOL_VERSION}"
            )

        expected_size = HEADER_SIZE + payload_length + CRC_SIZE
        if len(packet) != expected_size:
            raise ProtocolError(
                f"invalid frame length {len(packet)}; expected {expected_size}"
            )

        body = packet[:-CRC_SIZE]
        expected_crc = struct.unpack(CRC_FORMAT, packet[-CRC_SIZE:])[0]
        actual_crc = crc16(body)
        if actual_crc != expected_crc:
            raise ProtocolError(
                f"CRC mismatch: received 0x{expected_crc:04X}, calculated 0x{actual_crc:04X}"
            )

        payload = packet[HEADER_SIZE:-CRC_SIZE]
        try:
            return cls(
                frame_type=FrameType(frame_type),
                content_type=ContentType(content_type),
                source_node_id=source_node_id,
                message_id=message_id,
                total_packets=total_packets,
                packet_index=packet_index,
                payload=payload,
                version=version,
            )
        except ValueError as exc:
            raise ProtocolError(f"unknown frame field value: {exc}") from exc


def new_message_id() -> int:
    """Create a non-zero 32-bit message identifier."""

    return secrets.randbelow(0xFFFFFFFF) + 1


def make_data_frames(
    payload: bytes,
    content_type: ContentType,
    source_node_id: int = 0,
    message_id: int | None = None,
) -> list[Frame]:
    if not isinstance(payload, bytes):
        raise ProtocolError("message payload must be bytes")

    chunks = [
        payload[offset : offset + CHUNK_SIZE]
        for offset in range(0, len(payload), CHUNK_SIZE)
    ]
    if not chunks:
        chunks = [b""]
    if len(chunks) > 0xFFFF:
        raise ProtocolError("message requires more than 65,535 DATA frames")

    actual_message_id = new_message_id() if message_id is None else message_id
    return [
        Frame(
            frame_type=FrameType.DATA,
            content_type=content_type,
            source_node_id=source_node_id,
            message_id=actual_message_id,
            total_packets=len(chunks),
            packet_index=index,
            payload=chunk,
        )
        for index, chunk in enumerate(chunks)
    ]


def make_end_frame(data_frame: Frame, round_number: int) -> Frame:
    if data_frame.frame_type != FrameType.DATA:
        raise ProtocolError("END metadata must be copied from a DATA frame")
    return Frame(
        frame_type=FrameType.END,
        content_type=data_frame.content_type,
        source_node_id=data_frame.source_node_id,
        message_id=data_frame.message_id,
        total_packets=data_frame.total_packets,
        packet_index=round_number,
    )


def encode_missing_indexes(indexes: Sequence[int]) -> bytes:
    for index in indexes:
        _require_uint("missing packet index", index, 16)
    if not indexes:
        return b""
    return struct.pack(f">{len(indexes)}H", *indexes)


def decode_missing_indexes(payload: bytes) -> list[int]:
    if len(payload) % 2:
        raise ProtocolError("NACK payload length must be divisible by two")
    if not payload:
        return []
    return list(struct.unpack(f">{len(payload) // 2}H", payload))


@dataclass
class ReceiveSession:
    source_node_id: int
    message_id: int
    content_type: ContentType
    total_packets: int
    packets: dict[int, bytes] = field(default_factory=dict)

    @classmethod
    def from_frame(cls, frame: Frame) -> "ReceiveSession":
        if frame.frame_type not in (FrameType.DATA, FrameType.END):
            raise ProtocolError("a receive session must start from DATA or END")
        if frame.total_packets == 0:
            raise ProtocolError("message total_packets cannot be zero")
        session = cls(
            source_node_id=frame.source_node_id,
            message_id=frame.message_id,
            content_type=frame.content_type,
            total_packets=frame.total_packets,
        )
        if frame.frame_type == FrameType.DATA:
            session.accept(frame)
        return session

    def _validate_message(self, frame: Frame) -> None:
        if frame.source_node_id != self.source_node_id:
            raise ProtocolError("source node changed during a message")
        if frame.message_id != self.message_id:
            raise ProtocolError("frame belongs to a different message")
        if frame.content_type != self.content_type:
            raise ProtocolError("content type changed during a message")
        if frame.total_packets != self.total_packets:
            raise ProtocolError("total packet count changed during a message")

    def accept(self, frame: Frame) -> None:
        if frame.frame_type != FrameType.DATA:
            raise ProtocolError("receive session only stores DATA frames")
        self._validate_message(frame)
        existing = self.packets.get(frame.packet_index)
        if existing is not None and existing != frame.payload:
            raise ProtocolError("duplicate packet index contains different data")
        self.packets[frame.packet_index] = frame.payload

    def missing_indexes(self) -> list[int]:
        return [
            index
            for index in range(self.total_packets)
            if index not in self.packets
        ]

    @property
    def is_complete(self) -> bool:
        return len(self.packets) == self.total_packets and not self.missing_indexes()

    def reconstruct(self) -> bytes:
        missing = self.missing_indexes()
        if missing:
            raise ProtocolError(f"cannot reconstruct; missing packet indexes: {missing}")
        return b"".join(self.packets[index] for index in range(self.total_packets))

    def response_frames(self, responder_node_id: int) -> list[Frame]:
        missing = self.missing_indexes()
        if not missing:
            return [
                Frame(
                    frame_type=FrameType.COMPLETE,
                    content_type=self.content_type,
                    source_node_id=responder_node_id,
                    message_id=self.message_id,
                )
            ]

        pages = [
            missing[offset : offset + MAX_NACK_INDEXES]
            for offset in range(0, len(missing), MAX_NACK_INDEXES)
        ]
        return [
            Frame(
                frame_type=FrameType.NACK,
                content_type=self.content_type,
                source_node_id=responder_node_id,
                message_id=self.message_id,
                total_packets=len(pages),
                packet_index=page_index,
                payload=encode_missing_indexes(page),
            )
            for page_index, page in enumerate(pages)
        ]


@dataclass
class SenderSession:
    data_frames: list[Frame]
    max_retransmission_rounds: int = 5
    state: SenderState = SenderState.READY
    retransmission_round: int = 0

    def __post_init__(self) -> None:
        if not self.data_frames:
            raise ProtocolError("sender session needs at least one DATA frame")
        first = self.data_frames[0]
        if first.frame_type != FrameType.DATA:
            raise ProtocolError("sender session contains a non-DATA frame")
        for expected_index, frame in enumerate(self.data_frames):
            if frame.frame_type != FrameType.DATA:
                raise ProtocolError("sender session contains a non-DATA frame")
            if (
                frame.message_id != first.message_id
                or frame.content_type != first.content_type
                or frame.source_node_id != first.source_node_id
                or frame.total_packets != len(self.data_frames)
                or frame.packet_index != expected_index
            ):
                raise ProtocolError("inconsistent DATA frame sequence")

    @property
    def message_id(self) -> int:
        return self.data_frames[0].message_id

    def _end_frame(self) -> Frame:
        return make_end_frame(self.data_frames[0], self.retransmission_round)

    def initial_window(self) -> list[Frame]:
        if self.state != SenderState.READY:
            raise ProtocolError("initial window has already been sent")
        self.state = SenderState.WAITING_FOR_RESPONSE
        return [*self.data_frames, self._end_frame()]

    def retry_end_window(self) -> list[Frame]:
        if self.state != SenderState.WAITING_FOR_RESPONSE:
            raise ProtocolError("sender is not waiting for a response")
        return [self._end_frame()]

    def handle_response(self, frames: Iterable[Frame]) -> list[Frame]:
        if self.state != SenderState.WAITING_FOR_RESPONSE:
            raise ProtocolError("sender is not waiting for a response")

        responses = list(frames)
        if not responses:
            raise ProtocolError("empty response window")
        for frame in responses:
            if frame.message_id != self.message_id:
                raise ProtocolError("response belongs to a different message")

        if any(frame.frame_type == FrameType.COMPLETE for frame in responses):
            if len(responses) != 1 or responses[0].frame_type != FrameType.COMPLETE:
                raise ProtocolError("COMPLETE cannot be mixed with other responses")
            self.state = SenderState.COMPLETE
            return []

        if any(frame.frame_type != FrameType.NACK for frame in responses):
            raise ProtocolError("response window must contain only NACK frames")

        page_count = responses[0].total_packets
        if page_count == 0:
            raise ProtocolError("NACK page count cannot be zero")
        pages: dict[int, Frame] = {}
        for frame in responses:
            if frame.total_packets != page_count:
                raise ProtocolError("NACK page count changed within response")
            if frame.packet_index >= page_count:
                raise ProtocolError("NACK page index is out of range")
            pages[frame.packet_index] = frame
        if set(pages) != set(range(page_count)):
            raise ProtocolError("NACK response is missing one or more pages")

        missing: list[int] = []
        for page_index in range(page_count):
            missing.extend(decode_missing_indexes(pages[page_index].payload))
        missing = sorted(set(missing))
        if not missing:
            raise ProtocolError("NACK did not request any packet")
        if missing[-1] >= len(self.data_frames):
            raise ProtocolError("NACK requested a packet outside this message")

        self.retransmission_round += 1
        if self.retransmission_round > self.max_retransmission_rounds:
            self.state = SenderState.FAILED
            raise ProtocolError("maximum retransmission rounds exceeded")

        self.state = SenderState.WAITING_FOR_RESPONSE
        return [
            *(self.data_frames[index] for index in missing),
            self._end_frame(),
        ]


@dataclass(frozen=True)
class SimulationEvent:
    turn: int
    direction: str
    frame_type: FrameType
    packet_index: int
    delivered: bool
    note: str = ""


@dataclass(frozen=True)
class SimulationResult:
    message_id: int
    total_packets: int
    reconstructed_payload: bytes
    retransmission_rounds: int
    events: tuple[SimulationEvent, ...]


def simulate_half_duplex_transfer(
    payload: bytes,
    content_type: ContentType,
    *,
    sender_node_id: int = 1,
    receiver_node_id: int = 2,
    message_id: int | None = None,
    drop_data_once: Iterable[int] = (),
    drop_first_end: bool = False,
    drop_first_response: bool = False,
    max_turns: int = 20,
) -> SimulationResult:
    """Run a deterministic half-duplex transfer without radio hardware.

    Loss options are intentionally one-shot. They make it possible to verify
    retransmission and control-frame timeouts before the ESP32 transport exists.
    """

    data_frames = make_data_frames(
        payload,
        content_type,
        source_node_id=sender_node_id,
        message_id=message_id,
    )
    sender = SenderSession(data_frames)
    receiver: ReceiveSession | None = None
    drop_indexes = set(drop_data_once)
    invalid_drop_indexes = [
        index
        for index in drop_indexes
        if not isinstance(index, int) or isinstance(index, bool) or index < 0
    ]
    if invalid_drop_indexes:
        raise ProtocolError(f"invalid drop indexes: {invalid_drop_indexes}")
    out_of_range_drop_indexes = sorted(
        index for index in drop_indexes if index >= len(data_frames)
    )
    if out_of_range_drop_indexes:
        raise ProtocolError(
            "drop indexes outside this message: "
            f"{out_of_range_drop_indexes}; maximum is {len(data_frames) - 1}"
        )

    dropped_data: set[int] = set()
    end_was_dropped = False
    response_was_dropped = False
    events: list[SimulationEvent] = []
    outbound = sender.initial_window()

    for turn in range(1, max_turns + 1):
        # Sender owns the radio in this window. Receiver is in RX mode.
        end_arrived = False
        for frame in outbound:
            delivered = True
            note = ""
            if (
                frame.frame_type == FrameType.DATA
                and frame.packet_index in drop_indexes
                and frame.packet_index not in dropped_data
            ):
                delivered = False
                dropped_data.add(frame.packet_index)
                note = "simulated one-time DATA loss"
            elif frame.frame_type == FrameType.END and drop_first_end and not end_was_dropped:
                delivered = False
                end_was_dropped = True
                note = "simulated one-time END loss"

            events.append(
                SimulationEvent(
                    turn=turn,
                    direction="sender->receiver",
                    frame_type=frame.frame_type,
                    packet_index=frame.packet_index,
                    delivered=delivered,
                    note=note,
                )
            )
            if not delivered:
                continue

            if frame.frame_type == FrameType.DATA:
                if receiver is None:
                    receiver = ReceiveSession.from_frame(frame)
                else:
                    receiver.accept(frame)
            elif frame.frame_type == FrameType.END:
                if receiver is None:
                    receiver = ReceiveSession.from_frame(frame)
                else:
                    receiver._validate_message(frame)
                end_arrived = True

        # Both radios are listening if END was lost. Sender later times out and
        # briefly takes TX ownership again to repeat END.
        if not end_arrived:
            outbound = sender.retry_end_window()
            continue

        assert receiver is not None
        responses = receiver.response_frames(receiver_node_id)

        # Receiver now owns the radio; sender has switched to RX mode.
        delivered_responses: list[Frame] = []
        drop_this_response_window = drop_first_response and not response_was_dropped
        for response in responses:
            delivered = not drop_this_response_window
            note = ""
            if not delivered:
                note = "simulated one-time response-window loss"
            events.append(
                SimulationEvent(
                    turn=turn,
                    direction="receiver->sender",
                    frame_type=response.frame_type,
                    packet_index=response.packet_index,
                    delivered=delivered,
                    note=note,
                )
            )
            if delivered:
                delivered_responses.append(response)
        if drop_this_response_window:
            response_was_dropped = True

        if not delivered_responses:
            outbound = sender.retry_end_window()
            continue

        outbound = sender.handle_response(delivered_responses)
        if sender.state == SenderState.COMPLETE:
            return SimulationResult(
                message_id=sender.message_id,
                total_packets=len(data_frames),
                reconstructed_payload=receiver.reconstruct(),
                retransmission_rounds=sender.retransmission_round,
                events=tuple(events),
            )

    raise ProtocolError(f"transfer did not complete within {max_turns} half-duplex turns")
