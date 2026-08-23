from __future__ import annotations
import argparse, socket, time, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lore_protocol import ContentType, Frame, FrameType, decode_missing_indexes
from tian_software import TianSoftware
from tian_payload import prepare_text, prepare_image, decode_received
from simulation.common import send_json, recv_lines, b64e, b64d

ROOT = Path(__file__).resolve().parents[1]


def desc(f):
    if f.frame_type == FrameType.DATA: return f"DATA index={f.packet_index} total={f.total_packets}"
    if f.frame_type == FrameType.END: return f"END round={f.packet_index}"
    if f.frame_type == FrameType.NACK: return f"NACK {decode_missing_indexes(f.payload)}"
    return "COMPLETE"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", choices=["A", "B"], required=True)
    ap.add_argument("--id", type=int, required=True)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--timeout", type=float, default=1.2)
    a = ap.parse_args()
    t = TianSoftware(a.id)
    s = socket.create_connection((a.host, a.port))
    send_json(s, {"type": "HELLO", "node": a.name, "node_id": a.id})
    print(f"=== TIAN SOFTWARE {a.name} (node_id={a.id}) ===", flush=True)
    buf = b""; last_tx = time.monotonic(); requested = False
    while True:
        s.settimeout(0.1)
        try: msgs, buf, ok = recv_lines(s, buf)
        except socket.timeout: msgs = []; ok = True
        if not ok: break
        for m in msgs:
            typ = m["type"]
            if typ == "ENQUEUE":
                payload_type = m.get("payload_type", "text")
                label = m.get("label", "")
                if payload_type == "image":
                    prepared = prepare_image(m["path"])
                    t.queue_message(prepared.encrypted, ContentType.IMAGE, label)
                    print(f"[QUEUE] IMAGE {prepared.display_name!r} original={prepared.original_size}B processed={prepared.processed_size}B depth={len(t.outgoing)}", flush=True)
                else:
                    prepared = prepare_text(m.get("text", ""))
                    t.queue_message(prepared.encrypted, ContentType.TEXT, label)
                    print(f"[QUEUE] TEXT {m.get('text','')!r} bytes={prepared.original_size} processed={prepared.processed_size}B depth={len(t.outgoing)}", flush=True)
                if not requested and not t.outbound_busy:
                    send_json(s, {"type": "REQUEST_CHANNEL", "node": a.name}); requested = True
            elif typ == "GRANT":
                requested = False
                print(f"[CHANNEL] GRANTED backoff={m.get('backoff_ms')}ms", flush=True)
                for raw in t.begin_next_transfer():
                    print(f"[TX] {desc(Frame.decode(raw))}", flush=True)
                    send_json(s, {"type": "FRAME", "node": a.name, "data": b64e(raw)})
                last_tx = time.monotonic()
            elif typ == "FRAME":
                raw = b64d(m["data"]); f = Frame.decode(raw)
                print(f"[RX] {desc(f)}", flush=True)
                responses = t.handle_encoded_frame(raw)
                for out in responses:
                    print(f"[TX] {desc(Frame.decode(out))}", flush=True)
                    send_json(s, {"type": "FRAME", "node": a.name, "data": b64e(out)})
                if responses: last_tx = time.monotonic()
                for rm in t.pop_received_messages():
                    decoded = decode_received(rm.payload, rm.content_type, output_dir=ROOT / "received", output_stem=f"node_{a.name}_from_{rm.source_node_id}_{rm.message_id:08X}")
                    if decoded["type"] == "text":
                        print(f"[MESSAGE] TEXT from={rm.source_node_id} bytes={decoded['bytes']} text={decoded['text']!r}", flush=True)
                    elif decoded["type"] == "image":
                        print(f"[MESSAGE] IMAGE from={rm.source_node_id} saved={decoded['path']} size={decoded['width']}x{decoded['height']} jpeg={decoded['bytes']}B", flush=True)
                if f.frame_type == FrameType.COMPLETE and not t.outbound_busy:
                    print("[TRANSFER] COMPLETE", flush=True)
                    if t.has_pending and not requested:
                        send_json(s, {"type": "REQUEST_CHANNEL", "node": a.name}); requested = True
            elif typ == "STOP": return
        if t.outbound_busy and time.monotonic() - last_tx >= a.timeout:
            retry = t.retry_after_timeout()
            if retry:
                print("[TIMEOUT] no NACK/COMPLETE -> retry END", flush=True)
                for raw in retry:
                    print(f"[TX] {desc(Frame.decode(raw))}", flush=True)
                    send_json(s, {"type": "FRAME", "node": a.name, "data": b64e(raw)})
                last_tx = time.monotonic()

if __name__ == "__main__": main()
