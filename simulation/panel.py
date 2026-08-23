from __future__ import annotations
import argparse, json, random, selectors, socket, time, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lore_protocol import Frame, FrameType, decode_missing_indexes
from simulation.common import send_json, b64d

class Panel:
    def __init__(self, cfg, live=False):
        self.cfg = cfg
        self.live = live
        self.rng = random.Random(cfg.get("seed"))
        self.nodes = {}; self.buffers = {}; self.sel = selectors.DefaultSelector()
        self.owner = None; self.waiting = []; self.req_times = {}
        self.seq_i = 0; self.response_seq = {}; self.tx_window = []
        self.completed = 0; self.stats = {"delivered": 0, "dropped": 0}

    def log(self, text): print(f"[PANEL] {text}", flush=True)

    def sequence(self, index=None):
        seqs = self.cfg.get("sequences", [])
        i = self.seq_i if index is None else index
        return seqs[i] if i < len(seqs) else {"name": f"default-{i+1}", "data_loss": {"mode": "none"}}

    def run(self, host, port):
        listener = socket.socket(); listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((host, port)); listener.listen(); listener.setblocking(False)
        self.sel.register(listener, selectors.EVENT_READ, data="listener")
        mode = "LIVE" if self.live else "SCENARIO"
        self.log(f"{mode} panel listening {host}:{port}; waiting for A and B")
        while True:
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
        elif typ == "FRAME": self.accept_frame(msg["node"], msg["data"])

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
