from __future__ import annotations
import argparse, json, queue, random, selectors, socket, threading, time, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lore_protocol import Frame, FrameType, decode_missing_indexes
from simulation.common import send_json, b64d
from simulation.experiment_trace import frame_metadata


class Panel:
    def __init__(self, cfg, live=False):
        self.cfg = cfg
        self.live = live
        self.rng = random.Random(cfg.get("seed"))
        self.nodes = {}; self.buffers = {}; self.sel = selectors.DefaultSelector()
        self.owner = None; self.waiting = []; self.req_times = {}
        self.seq_i = 0; self.response_seq = {}; self.tx_window = []
        self.completed = 0; self.stats = {"delivered": 0, "dropped": 0}
        self.metadata_auto = False
        self.latest_sequence_metadata = None
        self.latest_traces = {"A": {}, "B": {}}
        self.command_queue = queue.Queue()
        self.running = True

    def log(self, text): print(f"[PANEL] {text}", flush=True)

    def sequence(self, index=None):
        seqs = self.cfg.get("sequences", [])
        i = self.seq_i if index is None else index
        return seqs[i] if i < len(seqs) else {"name": f"default-{i+1}", "data_loss": {"mode": "none"}}

    def stdin_worker(self):
        while self.running:
            try:
                raw = input("PANEL> ").strip()
            except (EOFError, KeyboardInterrupt):
                return
            if raw:
                self.command_queue.put(raw)

    def process_commands(self):
        while True:
            try: raw = self.command_queue.get_nowait()
            except queue.Empty: return
            command = raw[1:] if raw.startswith("/") else raw
            head, _, rest = command.partition(" ")
            head = head.lower(); rest = rest.strip().lower()
            if head == "metadata":
                self.metadata_command(rest)
            elif head == "help":
                self.print_help()
            else:
                self.log("unknown panel command; use /help")

    def print_help(self):
        print(
            "\n=== PANEL COMMANDS ===\n"
            "/metadata current   show latest full metadata snapshot once\n"
            "/metadata on        show full metadata automatically for every TX/retry sequence\n"
            "/metadata off       stop automatic full metadata; concise experiment logs remain\n"
            "/metadata status    show metadata mode\n"
            "/help               show this help\n",
            flush=True,
        )

    def metadata_command(self, mode):
        if mode in {"", "status"}:
            self.log(f"metadata auto={'ON' if self.metadata_auto else 'OFF'}; use current/on/off")
            return
        if mode in {"on", "all", "sequence", "sequences"}:
            self.metadata_auto = True
            self.log("metadata AUTO ON: full metadata will be previewed for every TX/retry sequence")
            return
        if mode == "off":
            self.metadata_auto = False
            self.log("metadata AUTO OFF: concise ENCODE / TRANSMIT / DECODE preview remains")
            return
        if mode in {"current", "now", "preview"}:
            self.print_current_metadata()
            return
        self.log("usage: /metadata current | on | off | status")

    def print_trace_metadata(self, node, stage, trace):
        print(f"\n[METADATA] === {node} {stage} ===", flush=True)
        for key, value in trace.items():
            print(f"[METADATA] {key}: {value}", flush=True)

    def print_sequence_metadata(self, meta):
        if not meta:
            print("[METADATA] No transmission sequence has completed yet.", flush=True)
            return
        print("\n[METADATA] ========== TRANSMISSION SEQUENCE =========", flush=True)
        print(f"[METADATA] sequence={meta['sequence_number']} name={meta['sequence_name']}", flush=True)
        print(f"[METADATA] sender={meta['sender']} message_id={meta['message_id']} content={meta['content_type']}", flush=True)
        print(f"[METADATA] configured_loss={meta['data_loss']} chosen_drop_indexes={meta['drop_indexes']}", flush=True)
        print(f"[METADATA] drop_end={meta['drop_end']} drop_nack={meta['drop_nack']} drop_complete={meta['drop_complete']}", flush=True)
        print(f"[METADATA] data_frames_in_window={len(meta['frames'])} encoded_data_bytes={meta['encoded_data_bytes']}", flush=True)
        for index, frame in enumerate(meta["frames"], 1):
            print(
                f"[METADATA] frame[{index}] {frame['frame_type']} msg={frame['message_id']} "
                f"idx={frame['packet_index']}/{frame['total_packets']} frame={frame['frame_bytes']}B "
                f"payload={frame['payload_bytes']}B header={frame['header_bytes']}B crc={frame['crc16']}",
                flush=True,
            )
            print(f"[METADATA] frame[{index}] hex={frame['frame_hex']}", flush=True)

    def print_current_metadata(self):
        print("\n[METADATA] ===== CURRENT / LATEST SNAPSHOT =====", flush=True)
        found = False
        for node in ("A", "B"):
            for stage in ("ENCODE", "TX_WINDOW", "DECODE"):
                trace = self.latest_traces.get(node, {}).get(stage)
                if trace:
                    found = True
                    self.print_trace_metadata(node, stage, trace)
        if self.latest_sequence_metadata:
            found = True
            self.print_sequence_metadata(self.latest_sequence_metadata)
        if not found:
            print("[METADATA] Nothing captured yet. Send a text/image first.", flush=True)

    def concise_trace(self, node, stage, trace):
        if stage == "ENCODE":
            content = trace.get("content_type", "?")
            source = trace.get("raw_bytes", trace.get("original_bytes", "?"))
            encrypted = trace.get("encrypted_bytes", "?")
            detail = trace.get("raw_preview") or trace.get("display_name") or ""
            self.log(f"[ENCODE] {node} {content} source={source}B -> encrypted={encrypted}B {detail!r}")
        elif stage == "DECODE":
            content = trace.get("content_type", "?")
            encrypted = trace.get("encrypted_bytes", "?")
            result = trace.get("text_preview") or trace.get("dimensions") or trace.get("result", "decoded")
            self.log(f"[DECODE] {node} {content} encrypted={encrypted}B -> {result}")
        elif stage == "TX_WINDOW":
            self.log(
                f"[TRANSMIT] {node} msg={trace.get('message_id')} content={trace.get('content_type')} "
                f"DATA={trace.get('data_frames')} indexes={trace.get('data_indexes')} "
                f"window={trace.get('encoded_window_bytes')}B"
            )

    def run(self, host, port):
        listener = socket.socket(); listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((host, port)); listener.listen(); listener.setblocking(False)
        self.sel.register(listener, selectors.EVENT_READ, data="listener")
        mode = "LIVE" if self.live else "SCENARIO"
        self.log(f"{mode} panel listening {host}:{port}; waiting for A and B")
        print("Panel experiment preview: ENCODE -> TRANSMIT -> DECODE is enabled.", flush=True)
        print("Use /metadata current for one full snapshot, or /metadata on for every sequence.", flush=True)
        threading.Thread(target=self.stdin_worker, daemon=True).start()
        while self.running:
            self.process_commands()
            for key, _ in self.sel.select(0.05):
                if key.data == "listener":
                    conn, _ = listener.accept(); conn.setblocking(False)
                    self.sel.register(conn, selectors.EVENT_READ, data=None); self.buffers[conn] = b""
                else: self.read_sock(key.fileobj)
            self.arbitrate()
            if not self.live and len(self.nodes) == 2 and not getattr(self, "loaded", False):
                self.loaded = True; self.load_messages()
            if not self.live and getattr(self, "loaded", False) and self.done():
                self.log(f"DONE completed={self.completed}/{len(self.cfg.get('messages', []))} delivered={self.stats['delivered']} dropped={self.stats['dropped']}")
                for sock in self.nodes.values(): send_json(sock, {"type": "STOP"})
                self.running = False
                return

    def read_sock(self, sock):
        try: data = sock.recv(65536)
        except BlockingIOError: return
        if not data:
            try: self.sel.unregister(sock)
            except Exception: pass
            self.buffers.pop(sock, None)
            for name, connected in list(self.nodes.items()):
                if connected is sock:
                    self.nodes.pop(name, None)
                    if self.owner == name: self.owner = None
                    if name in self.waiting: self.waiting.remove(name)
                    self.req_times.pop(name, None)
                    self.log(f"{name} disconnected")
            try: sock.close()
            except OSError: pass
            return
        buf = self.buffers[sock] + data
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            if line: self.handle(sock, json.loads(line.decode()))
        self.buffers[sock] = buf

    def handle(self, sock, msg):
        typ = msg["type"]
        if typ == "HELLO":
            self.nodes[msg["node"]] = sock
            self.sel.modify(sock, selectors.EVENT_READ, data=msg["node"])
            self.log(f"{msg['node']} connected node_id={msg['node_id']}")
        elif typ == "REQUEST_CHANNEL":
            node = msg["node"]
            if node not in self.waiting:
                self.waiting.append(node); self.req_times[node] = time.monotonic()
            self.log(f"{node} requests channel")
        elif typ == "FRAME":
            self.accept_frame(msg["node"], msg["data"])
        elif typ == "TRACE":
            node = msg.get("node", "?"); stage = msg.get("stage", "TRACE"); trace = msg.get("trace", {})
            if node in self.latest_traces:
                self.latest_traces[node][stage] = trace
            self.concise_trace(node, stage, trace)

    def load_messages(self):
        for i, msg in enumerate(self.cfg.get("messages", [])):
            out = {"type": "ENQUEUE", "payload_type": msg.get("payload_type", "text"), "label": msg.get("label", f"message-{i+1}")}
            if out["payload_type"] == "image": out["path"] = msg["path"]
            else: out["text"] = msg.get("text", "")
            send_json(self.nodes[msg["sender"]], out)
        self.log(f"loaded {len(self.cfg.get('messages', []))} queued messages")

    def arbitrate(self):
        if self.owner or not self.waiting: return
        oldest = min(self.req_times.values())
        if time.monotonic() - oldest < self.cfg.get("contention_window_ms", 80) / 1000: return
        choices = sorted((self.rng.randint(5, self.cfg.get("max_backoff_ms", 120)), node) for node in self.waiting)
        backoff, winner = choices[0]
        self.waiting.remove(winner); self.req_times.pop(winner, None); self.owner = winner
        self.log("contention " + ", ".join(f"{node}:{delay}ms" for delay, node in choices) + f" -> {winner} wins")
        send_json(self.nodes[winner], {"type": "GRANT", "backoff_ms": backoff})

    def choose_data_drops(self, seq, frames):
        indexes = [Frame.decode(b64d(data)).packet_index for _, data in frames]
        loss = seq.get("data_loss", {"mode": "none"}); mode = loss.get("mode", "none")
        if mode == "manual": return set(loss.get("indexes", [])) & set(indexes)
        if mode == "random_count":
            count = max(0, min(int(loss.get("count", 0)), len(indexes)))
            chosen = set(self.rng.sample(indexes, count))
            self.log(f"{seq.get('name')} random_count selected {sorted(chosen)} from window {indexes}")
            return chosen
        if mode == "random_probability":
            p = max(0.0, min(1.0, float(loss.get("probability", 0))))
            chosen = {i for i in indexes if self.rng.random() < p}
            self.log(f"{seq.get('name')} random_probability selected {sorted(chosen)} from window {indexes}")
            return chosen
        return set()

    def deliver(self, sender, data64, seq_idx, seq, force_drop=False):
        frame = Frame.decode(b64d(data64)); other = "B" if sender == "A" else "A"; lost = force_drop
        if other not in self.nodes:
            self.log(f"cannot deliver {sender}->{other}; destination not connected")
            return False
        if frame.frame_type == FrameType.END: lost = lost or bool(seq.get("drop_end", False))
        elif frame.frame_type == FrameType.NACK: lost = lost or bool(seq.get("drop_nack", False))
        elif frame.frame_type == FrameType.COMPLETE: lost = lost or bool(seq.get("drop_complete", False))
        label = frame.frame_type.name + (f"#{frame.packet_index}" if frame.frame_type == FrameType.DATA else "")
        if frame.frame_type == FrameType.NACK: label += str(decode_missing_indexes(frame.payload))
        if lost:
            self.stats["dropped"] += 1; self.log(f"SEQ {seq_idx+1} {seq.get('name','')} DROP {sender}->{other} {label}"); return False
        self.stats["delivered"] += 1; self.log(f"SEQ {seq_idx+1} {seq.get('name','')} PASS {sender}->{other} {label}")
        send_json(self.nodes[other], {"type": "FRAME", "data": data64}); return True

    def accept_frame(self, sender, data64):
        frame = Frame.decode(b64d(data64))
        if frame.frame_type == FrameType.DATA:
            self.tx_window.append((sender, data64)); return
        if frame.frame_type == FrameType.END:
            seq_idx = self.seq_i; seq = self.sequence(seq_idx); self.response_seq[frame.message_id] = seq_idx
            drops = self.choose_data_drops(seq, self.tx_window)
            frame_metas = [frame_metadata(b64d(data)) for _, data in self.tx_window]
            self.latest_sequence_metadata = {
                "sequence_number": seq_idx + 1,
                "sequence_name": seq.get("name", f"sequence-{seq_idx+1}"),
                "sender": sender,
                "message_id": f"0x{frame.message_id:08X}",
                "content_type": frame.content_type.name,
                "data_loss": seq.get("data_loss", {"mode": "none"}),
                "drop_indexes": sorted(drops),
                "drop_end": bool(seq.get("drop_end", False)),
                "drop_nack": bool(seq.get("drop_nack", False)),
                "drop_complete": bool(seq.get("drop_complete", False)),
                "frames": frame_metas,
                "encoded_data_bytes": sum(meta["frame_bytes"] for meta in frame_metas),
            }
            if self.metadata_auto:
                self.print_sequence_metadata(self.latest_sequence_metadata)
            for source, data in self.tx_window:
                df = Frame.decode(b64d(data)); self.deliver(source, data, seq_idx, seq, df.packet_index in drops)
            self.tx_window.clear(); self.deliver(sender, data64, seq_idx, seq); self.seq_i += 1; return
        seq_idx = self.response_seq.get(frame.message_id, max(0, self.seq_i - 1)); seq = self.sequence(seq_idx)
        delivered = self.deliver(sender, data64, seq_idx, seq)
        if frame.frame_type == FrameType.COMPLETE and delivered and sender != self.owner:
            self.completed += 1; self.log(f"channel released by {self.owner} after delivered COMPLETE"); self.owner = None

    def done(self):
        return self.loaded and self.completed >= len(self.cfg.get("messages", [])) and self.owner is None and not self.waiting


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default=str(Path(__file__).parent / "scenarios" / "example.json"))
    ap.add_argument("--live", action="store_true", help="stay open for interactive nodes instead of preloading messages")
    ap.add_argument("--host", default="127.0.0.1"); ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    cfg = json.load(open(args.scenario))
    print("=== SIMULATION CONTROL / MONITOR PANEL ==="); print(json.dumps(cfg, indent=2))
    Panel(cfg, live=args.live).run(args.host, args.port)


if __name__ == "__main__": main()
