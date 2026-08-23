"""Tian Software protocol engine: queue, encode/decode, reliability and serial-ready frame boundary."""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass
from lore_protocol import ContentType, Frame, FrameType, ProtocolError, ReceiveSession, SenderSession, SenderState, make_data_frames

@dataclass(frozen=True)
class QueuedMessage:
    payload: bytes
    content_type: ContentType
    label: str = ""

@dataclass(frozen=True)
class ReceivedMessage:
    source_node_id: int
    message_id: int
    content_type: ContentType
    payload: bytes

class TianSoftware:
    def __init__(self, node_id: int, max_retransmission_rounds: int = 20):
        self.node_id = node_id
        self.max_retransmission_rounds = max_retransmission_rounds
        self.outgoing = deque()
        self.sender: SenderSession | None = None
        self.receive_sessions = {}
        self.received_messages = []
        self._nack_pages = {}

    @property
    def outbound_busy(self):
        return self.sender is not None and self.sender.state == SenderState.WAITING_FOR_RESPONSE

    @property
    def has_pending(self):
        return bool(self.outgoing)

    def queue_message(self, payload: bytes, content_type: ContentType = ContentType.TEXT, label: str = ""):
        self.outgoing.append(QueuedMessage(payload, content_type, label))
        return len(self.outgoing)

    def begin_next_transfer(self) -> list[bytes]:
        if self.outbound_busy:
            raise ProtocolError("outbound transfer already active")
        if not self.outgoing:
            return []
        q = self.outgoing.popleft()
        frames = make_data_frames(q.payload, q.content_type, self.node_id)
        self.sender = SenderSession(frames, self.max_retransmission_rounds)
        return [f.encode() for f in self.sender.initial_window()]

    def retry_after_timeout(self) -> list[bytes]:
        if not self.outbound_busy or self.sender is None:
            return []
        return [f.encode() for f in self.sender.retry_end_window()]

    def handle_encoded_frame(self, encoded: bytes) -> list[bytes]:
        f = Frame.decode(encoded)
        if f.frame_type in (FrameType.DATA, FrameType.END):
            return self._inbound(f)
        return self._response(f)

    def _inbound(self, f: Frame) -> list[bytes]:
        key = (f.source_node_id, f.message_id)
        s = self.receive_sessions.get(key)
        if s is None:
            s = ReceiveSession.from_frame(f)
            self.receive_sessions[key] = s
        elif f.frame_type == FrameType.DATA:
            s.accept(f)
        else:
            s._validate_message(f)
        if f.frame_type != FrameType.END:
            return []
        rs = s.response_frames(self.node_id)
        if s.is_complete and not any(m.source_node_id == s.source_node_id and m.message_id == s.message_id for m in self.received_messages):
            self.received_messages.append(ReceivedMessage(s.source_node_id, s.message_id, s.content_type, s.reconstruct()))
        return [r.encode() for r in rs]

    def _response(self, f: Frame) -> list[bytes]:
        if not self.outbound_busy or self.sender is None or f.message_id != self.sender.message_id:
            return []
        if f.frame_type == FrameType.COMPLETE:
            self.sender.handle_response([f])
            self._nack_pages.pop(f.message_id, None)
            return []
        if f.frame_type != FrameType.NACK:
            return []
        pages = self._nack_pages.setdefault(f.message_id, {})
        pages[f.packet_index] = f
        if len(pages) < f.total_packets:
            return []
        ordered = [pages[i] for i in range(f.total_packets)]
        self._nack_pages.pop(f.message_id, None)
        return [x.encode() for x in self.sender.handle_response(ordered)]

    def pop_received_messages(self):
        out = list(self.received_messages)
        self.received_messages.clear()
        return out
