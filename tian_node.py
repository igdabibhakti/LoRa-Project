"""Transport-independent bidirectional Tian node runtime.

A TianNode can initiate a reliable transfer and receive/reassemble transfers.
It only consumes and produces encoded LoRe Frame bytes. The actual transport
(simulator today, USB serial/ESP32 later) is deliberately outside this module.
"""

from __future__ import annotations

from dataclasses import dataclass

from lore_protocol import (
    ContentType,
    Frame,
    FrameType,
    ProtocolError,
    ReceiveSession,
    SenderSession,
    SenderState,
    make_data_frames,
)


@dataclass(frozen=True)
class ReceivedMessage:
    source_node_id: int
    message_id: int
    content_type: ContentType
    payload: bytes


class TianNode:
    """One logical LoRe node capable of sending and receiving.

    Only one outbound transfer is active at a time because the target radio link
    is half-duplex. Multiple inbound message IDs can still be tracked safely.
    """

    def __init__(self, node_id: int, max_retransmission_rounds: int = 5) -> None:
        if not isinstance(node_id, int) or isinstance(node_id, bool):
            raise ProtocolError("node_id must be an integer")
        if not 0 <= node_id <= 0xFFFF:
            raise ProtocolError("node_id must fit in uint16")

        self.node_id = node_id
        self.max_retransmission_rounds = max_retransmission_rounds
        self.sender: SenderSession | None = None
        self.receive_sessions: dict[tuple[int, int], ReceiveSession] = {}
        self.received_messages: list[ReceivedMessage] = []
        self._nack_pages: dict[int, dict[int, Frame]] = {}

    @property
    def outbound_busy(self) -> bool:
        return self.sender is not None and self.sender.state == SenderState.WAITING_FOR_RESPONSE

    def start_transfer(
        self,
        payload: bytes,
        content_type: ContentType,
        *,
        message_id: int | None = None,
    ) -> list[bytes]:
        """Start an outbound transfer and return the first TX window."""

        if self.outbound_busy:
            raise ProtocolError("node already has an outbound transfer in progress")

        frames = make_data_frames(
            payload,
            content_type,
            source_node_id=self.node_id,
            message_id=message_id,
        )
        self.sender = SenderSession(
            frames,
            max_retransmission_rounds=self.max_retransmission_rounds,
        )
        return [frame.encode() for frame in self.sender.initial_window()]

    def retry_after_timeout(self) -> list[bytes]:
        """Repeat END after a response timeout.

        The transport owns the timeout clock; TianNode owns the protocol action.
        """

        if not self.outbound_busy or self.sender is None:
            raise ProtocolError("node is not waiting for an outbound response")
        return [frame.encode() for frame in self.sender.retry_end_window()]

    def handle_encoded_frame(self, encoded: bytes) -> list[bytes]:
        """Process one received frame and return any frames Tian should transmit."""

        frame = Frame.decode(encoded)

        if frame.frame_type in (FrameType.DATA, FrameType.END):
            return self._handle_inbound_message_frame(frame)
        if frame.frame_type in (FrameType.NACK, FrameType.COMPLETE):
            return self._handle_outbound_response(frame)
        raise ProtocolError(f"unsupported frame type: {frame.frame_type}")

    def _handle_inbound_message_frame(self, frame: Frame) -> list[bytes]:
        key = (frame.source_node_id, frame.message_id)
        session = self.receive_sessions.get(key)

        if session is None:
            session = ReceiveSession.from_frame(frame)
            self.receive_sessions[key] = session
        elif frame.frame_type == FrameType.DATA:
            session.accept(frame)
        else:
            session._validate_message(frame)

        if frame.frame_type != FrameType.END:
            return []

        responses = session.response_frames(self.node_id)

        if session.is_complete:
            if not any(
                message.source_node_id == session.source_node_id
                and message.message_id == session.message_id
                for message in self.received_messages
            ):
                self.received_messages.append(
                    ReceivedMessage(
                        source_node_id=session.source_node_id,
                        message_id=session.message_id,
                        content_type=session.content_type,
                        payload=session.reconstruct(),
                    )
                )

        return [response.encode() for response in responses]

    def _handle_outbound_response(self, frame: Frame) -> list[bytes]:
        if not self.outbound_busy or self.sender is None:
            raise ProtocolError("received a response but no outbound transfer is active")
        if frame.message_id != self.sender.message_id:
            raise ProtocolError("response belongs to a different outbound message")

        if frame.frame_type == FrameType.COMPLETE:
            retransmit = self.sender.handle_response([frame])
            self._nack_pages.pop(frame.message_id, None)
            return [item.encode() for item in retransmit]

        page_count = frame.total_packets
        if page_count == 0:
            raise ProtocolError("NACK page count cannot be zero")
        if frame.packet_index >= page_count:
            raise ProtocolError("NACK page index is out of range")

        pages = self._nack_pages.setdefault(frame.message_id, {})
        pages[frame.packet_index] = frame

        if len(pages) < page_count:
            return []
        if set(pages) != set(range(page_count)):
            return []

        ordered_pages = [pages[index] for index in range(page_count)]
        self._nack_pages.pop(frame.message_id, None)
        retransmit = self.sender.handle_response(ordered_pages)
        return [item.encode() for item in retransmit]

    def pop_received_messages(self) -> list[ReceivedMessage]:
        messages = list(self.received_messages)
        self.received_messages.clear()
        return messages
