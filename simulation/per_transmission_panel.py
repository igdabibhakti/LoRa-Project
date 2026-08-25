from __future__ import annotations

from lore_protocol import Frame, FrameType, decode_missing_indexes
from simulation.common import b64d
from simulation.experiment_trace import frame_metadata
from simulation.panel import Panel


class PerTransmissionPanel(Panel):
    """Panel variant where each logical transmission consumes its own scenario.

    A DATA burst consumes one sequence when its first DATA frame arrives. END,
    NACK, and COMPLETE consume their own transmission sequences.

    Manual indexes and random_count remain one-transmission DATA rules. For a
    random_probability rule, selected control flags (END/NACK/COMPLETE) mean
    "include this frame type in the same probability simulation". Every DATA or
    selected control frame gets an independent fresh probability roll.

    When ``continuous=true``, both the DATA probability and the selected control
    frame types remain active as fallback channel behavior for later
    transmissions. A later continuous probability rule replaces that policy.
    """

    CONTROL_FLAG_BY_TYPE = {
        FrameType.END: "drop_end",
        FrameType.NACK: "drop_nack",
        FrameType.COMPLETE: "drop_complete",
    }

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
            key.replace("drop_", "").upper()
            for key, enabled in self.continuous_control_drops.items()
            if enabled
        ]
        control_text = ",".join(enabled_controls) if enabled_controls else "none"
        self.log(
            f"{seq.get('name','')} enables continuous random_probability="
            f"{self.continuous_probability_loss['probability'] * 100:g}% "
            f"applies_to=DATA{(',' + control_text) if control_text != 'none' else ''}"
        )
        return True

    def _effective_data_sequence(self, seq):
        loss = seq.get("data_loss", {"mode": "none"})
        mode = loss.get("mode", "none")

        if self._remember_continuous_policy(seq):
            return seq

        # Explicit one-shot DATA rules override the persistent DATA probability
        # for this transmission only. The continuous rule resumes afterward.
        if mode != "none" or self.continuous_probability_loss is None:
            return seq

        effective = dict(seq)
        effective["data_loss"] = dict(self.continuous_probability_loss)
        effective["name"] = f"{seq.get('name', '')} + continuous-probability".strip()
        return effective

    def _effective_control_sequence(self, seq):
        # A continuous probability rule may itself be consumed by a control
        # transmission, so activate it here too.
        remembered = self._remember_continuous_policy(seq)
        loss = seq.get("data_loss", {"mode": "none"})

        # An explicit random-probability sequence uses its own selected control
        # types and probability for this transmission.
        if loss.get("mode") == "random_probability":
            return seq

        # Otherwise inherit the persistent probability policy, if any.
        if self.continuous_probability_loss is None or self.continuous_control_drops is None:
            return seq

        effective = dict(seq)
        effective["data_loss"] = dict(self.continuous_probability_loss)
        for key, selected in self.continuous_control_drops.items():
            effective[key] = bool(seq.get(key, False)) or selected
        if not remembered:
            effective["name"] = f"{seq.get('name', '')} + continuous-probability".strip()
        return effective

    def _probability_control_drop(self, seq, frame):
        """Return None for deterministic control rules, else a probability roll."""
        flag = self.CONTROL_FLAG_BY_TYPE.get(frame.frame_type)
        if flag is None:
            return None

        loss = seq.get("data_loss", {"mode": "none"})
        if loss.get("mode") != "random_probability":
            return None
        if not bool(seq.get(flag, False)):
            return False

        p = max(0.0, min(1.0, float(loss.get("probability", 0))))
        roll = self.rng.random()
        dropped = roll < p
        self.log(
            f"{seq.get('name','')} random_probability {frame.frame_type.name} "
            f"roll={roll:.4f} threshold={p:.4f} -> {'DROP' if dropped else 'PASS'}"
        )
        return dropped

    def _deliver_control_frame(self, sender, data64, frame, seq_idx, seq):
        probability_drop = self._probability_control_drop(seq, frame)
        if probability_drop is None:
            # Non-probability scenarios keep the original deterministic control
            # drop behavior.
            return self.deliver(sender, data64, seq_idx, seq)

        # Base deliver() treats drop_end/drop_nack/drop_complete as deterministic
        # booleans. Clear them here because random-probability mode has already
        # made the independent roll above.
        sanitized = dict(seq)
        sanitized["drop_end"] = False
        sanitized["drop_nack"] = False
        sanitized["drop_complete"] = False
        return self.deliver(
            sender,
            data64,
            seq_idx,
            sanitized,
            force_drop=probability_drop,
        )

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
        delivered = self._deliver_control_frame(sender, data64, frame, seq_idx, seq)
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
        delivered = self._deliver_control_frame(sender, data64, frame, seq_idx, seq)
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
