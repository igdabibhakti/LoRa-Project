from __future__ import annotations

from lore_protocol import Frame, FrameType, decode_missing_indexes
from simulation.common import b64d
from simulation.experiment_trace import frame_metadata
from simulation.panel import Panel


class PerTransmissionPanel(Panel):
    """Panel variant where each logical transmission consumes its own scenario.

    A DATA burst consumes one sequence when its first DATA frame arrives. The END
    that closes that burst consumes the next sequence. NACK (including all pages
    of one paged NACK) and COMPLETE each consume their own sequence as well.

    Manual indexes and random_count are always one-transmission rules. A
    random_probability rule may set ``continuous=true``. Once encountered, both
    its DATA probability and its END/NACK/COMPLETE drop flags persist as fallback
    channel behavior for later transmissions. A later continuous-probability
    rule replaces that persistent behavior.
    """

    def __init__(self, cfg, live=False):
        super().__init__(cfg, live=live)
        self.continuous_probability_loss = None
        self.continuous_control_drops = None
        self.active_nack_tx = {}

    def _consume_sequence(self):
        seq_idx = self.seq_i
        seq = self.sequence(seq_idx)
        self.seq_i += 1
        return seq_idx, seq

    def _remember_continuous_policy(self, seq):
        loss = seq.get("data_loss", {"mode": "none"})
        if loss.get("mode", "none") != "random_probability" or not bool(
            loss.get("continuous", False)
        ):
            return False

        self.continuous_probability_loss = {
            "mode": "random_probability",
            "probability": float(loss.get("probability", 0)),
            "continuous": True,
        }
        self.continuous_control_drops = {
            "drop_end": bool(seq.get("drop_end", False)),
            "drop_nack": bool(seq.get("drop_nack", False)),
            "drop_complete": bool(seq.get("drop_complete", False)),
        }
        enabled_controls = [
            name.upper().replace("DROP_", "")
            for name, enabled in self.continuous_control_drops.items()
            if enabled
        ]
        control_text = ",".join(enabled_controls) if enabled_controls else "none"
        self.log(
            f"{seq.get('name','')} enables continuous random_probability="
            f"{self.continuous_probability_loss['probability'] * 100:g}% "
            f"control_drops={control_text}"
        )
        return True

    def _effective_data_sequence(self, seq):
        loss = seq.get("data_loss", {"mode": "none"})
        mode = loss.get("mode", "none")

        if self._remember_continuous_policy(seq):
            return seq

        # Manual and random_count remain explicitly one-transmission-only. Any
        # explicit DATA rule overrides the persistent probability for this DATA
        # transmission only; the persistent probability resumes afterward.
        if mode != "none" or self.continuous_probability_loss is None:
            return seq

        effective = dict(seq)
        effective["data_loss"] = dict(self.continuous_probability_loss)
        effective["name"] = f"{seq.get('name', '')} + continuous-probability".strip()
        return effective

    def _effective_control_sequence(self, seq):
        # A continuous probability sequence can first be consumed by a control
        # transmission, so remember it here too, not only in DATA handling.
        self._remember_continuous_policy(seq)

        if self.continuous_control_drops is None:
            return seq

        effective = dict(seq)
        inherited = []
        for key, persistent in self.continuous_control_drops.items():
            if persistent:
                inherited.append(key.replace("drop_", "").upper())
            # Explicit current drops and persistent drops are both honored.
            effective[key] = bool(seq.get(key, False)) or persistent

        if inherited and not any(seq.get(key, False) for key in self.continuous_control_drops):
            effective["name"] = f"{seq.get('name', '')} + continuous-controls".strip()
        return effective

    def start_data_window(self, sender, frame):
        seq_idx, configured_seq = self._consume_sequence()
        seq = self._effective_data_sequence(configured_seq)

        retry_indexes = self.pending_retry_indexes.pop(frame.message_id, None)
        if retry_indexes is None:
            expected_indexes = list(range(frame.total_packets))
            kind = "initial"
        else:
            expected_indexes = sorted(retry_indexes)
            kind = "retransmission"

        drops = self.choose_data_drops(seq, expected_indexes)
        self.active_tx_window = {
            "sender": sender,
            "message_id": frame.message_id,
            "content_type": frame.content_type.name,
            "seq_idx": seq_idx,
            "seq": seq,
            "configured_seq": configured_seq,
            "kind": kind,
            "expected_indexes": expected_indexes,
            "drop_indexes": drops,
            "frames": [],
        }
        self.log(
            f"SEQ {seq_idx+1} {seq.get('name','')} START {kind} DATA transmission "
            f"{sender} msg=0x{frame.message_id:08X} expected={expected_indexes} "
            f"drops={sorted(drops)}"
        )
        return self.active_tx_window

    def _deliver_control(self, sender, data64, frame):
        seq_idx, configured_seq = self._consume_sequence()
        seq = self._effective_control_sequence(configured_seq)
        delivered = self.deliver(sender, data64, seq_idx, seq)
        return seq_idx, seq, delivered

    def remember_delivered_nack(self, frame, seq_idx):
        # Keep delivered NACK pages across NACK retransmissions even though each
        # retransmission consumes a new scenario sequence.
        key = frame.message_id
        state = self.nack_pages.setdefault(
            key,
            {"page_count": frame.total_packets, "pages": {}},
        )
        if state["page_count"] != frame.total_packets:
            state = {"page_count": frame.total_packets, "pages": {}}
            self.nack_pages[key] = state
        state["pages"][frame.packet_index] = decode_missing_indexes(frame.payload)
        if set(state["pages"]) != set(range(state["page_count"])):
            return

        missing = []
        for page_index in range(state["page_count"]):
            missing.extend(state["pages"][page_index])
        missing = sorted(set(missing))
        if missing:
            self.pending_retry_indexes[frame.message_id] = missing
            self.log(
                f"NACK complete for msg=0x{frame.message_id:08X}; "
                f"next retry DATA window expected={missing}"
            )
        self.nack_pages.pop(key, None)

    def _accept_nack(self, sender, data64, frame):
        key = (sender, frame.message_id)
        state = self.active_nack_tx.get(key)
        if state is None:
            seq_idx, configured_seq = self._consume_sequence()
            seq = self._effective_control_sequence(configured_seq)
            state = {
                "seq_idx": seq_idx,
                "seq": seq,
                "page_count": frame.total_packets,
                "seen": set(),
            }
            self.active_nack_tx[key] = state
            self.log(
                f"SEQ {seq_idx+1} {seq.get('name','')} START NACK transmission "
                f"{sender} msg=0x{frame.message_id:08X} pages={frame.total_packets}"
            )
        elif state["page_count"] != frame.total_packets:
            self.active_nack_tx.pop(key, None)
            return self._accept_nack(sender, data64, frame)

        seq_idx = state["seq_idx"]
        seq = state["seq"]
        delivered = self.deliver(sender, data64, seq_idx, seq)
        state["seen"].add(frame.packet_index)

        if delivered:
            self.remember_delivered_nack(frame, seq_idx)

        if state["seen"] >= set(range(state["page_count"])):
            self.active_nack_tx.pop(key, None)

    def accept_frame(self, sender, data64):
        frame = Frame.decode(b64d(data64))

        if frame.frame_type == FrameType.DATA:
            window = self.current_or_start_window(sender, frame)
            window["frames"].append(frame_metadata(b64d(data64)))
            should_drop = frame.packet_index in window["drop_indexes"]
            self.deliver(
                sender,
                data64,
                window["seq_idx"],
                window["seq"],
                force_drop=should_drop,
            )
            return

        if frame.frame_type == FrameType.END:
            if (
                self.active_tx_window is not None
                and self.active_tx_window["sender"] == sender
                and self.active_tx_window["message_id"] == frame.message_id
            ):
                window = self.active_tx_window
                self.finish_window_metadata(window, frame)
                self.active_tx_window = None

            seq_idx, seq, _ = self._deliver_control(sender, data64, frame)
            self.response_seq[frame.message_id] = seq_idx
            return

        if frame.frame_type == FrameType.NACK:
            self._accept_nack(sender, data64, frame)
            return

        if frame.frame_type == FrameType.COMPLETE:
            seq_idx, seq, delivered = self._deliver_control(sender, data64, frame)
            self.response_seq[frame.message_id] = seq_idx
            if delivered and sender != self.owner:
                self.completed += 1
                self.log(f"channel released by {self.owner} after delivered COMPLETE")
                self.owner = None
            if delivered:
                self.pending_retry_indexes.pop(frame.message_id, None)
                self.active_nack_tx = {
                    key: value
                    for key, value in self.active_nack_tx.items()
                    if key[1] != frame.message_id
                }
                self.nack_pages.pop(frame.message_id, None)
            return

        self._deliver_control(sender, data64, frame)
