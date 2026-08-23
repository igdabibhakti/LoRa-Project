from __future__ import annotations

import argparse
import json
import queue
import socket
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lore_protocol import ContentType, Frame, FrameType, decode_missing_indexes
from simulation.common import b64d, b64e, recv_lines, send_json
from tian_payload import decode_received, prepare_image, prepare_text
from tian_software import TianSoftware

ROOT = Path(__file__).resolve().parents[1]


def desc(frame: Frame) -> str:
    if frame.frame_type == FrameType.DATA:
        return f"DATA index={frame.packet_index} total={frame.total_packets}"
    if frame.frame_type == FrameType.END:
        return f"END round={frame.packet_index}"
    if frame.frame_type == FrameType.NACK:
        return f"NACK {decode_missing_indexes(frame.payload)}"
    return "COMPLETE"


class ScenarioPlayer:
    def __init__(self, node: "InteractiveNode"):
        self.node = node
        self.path: Path | None = None
        self.actions: list[dict] = []
        self.thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.index = 0

    def load(self, raw_path: str) -> None:
        path = Path(raw_path).expanduser().resolve()
        with path.open("r", encoding="utf-8") as handle:
            cfg = json.load(handle)
        actions = cfg.get("actions")
        if not isinstance(actions, list):
            raise ValueError("node scenario must contain actions[]")
        for i, action in enumerate(actions):
            if action.get("type") not in {"text", "image"}:
                raise ValueError(f"actions[{i}].type must be text or image")
            delay = float(action.get("delay", 0))
            if delay < 0:
                raise ValueError(f"actions[{i}].delay cannot be negative")
        self.stop()
        self.path = path
        self.actions = actions
        self.index = 0
        print(f"[SCENARIO] loaded {len(actions)} actions from {path}", flush=True)

    def run(self) -> None:
        if not self.actions:
            print("[SCENARIO] nothing loaded; use /load <file.json>", flush=True)
            return
        if self.thread and self.thread.is_alive():
            print("[SCENARIO] already running", flush=True)
            return
        self.stop_event.clear()
        self.pause_event.clear()
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()
        print(f"[SCENARIO] started at action {self.index + 1}/{len(self.actions)}", flush=True)

    def _worker(self) -> None:
        while self.index < len(self.actions) and not self.stop_event.is_set():
            action = self.actions[self.index]
            delay = float(action.get("delay", 0))
            deadline = time.monotonic() + delay
            while time.monotonic() < deadline and not self.stop_event.is_set():
                while self.pause_event.is_set() and not self.stop_event.is_set():
                    time.sleep(0.05)
                    deadline += 0.05
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
            if self.stop_event.is_set():
                break
            while self.pause_event.is_set() and not self.stop_event.is_set():
                time.sleep(0.05)
            if self.stop_event.is_set():
                break
            try:
                if action["type"] == "text":
                    text = str(action.get("text", ""))
                    print(f"[SCENARIO] TEXT {text!r}", flush=True)
                    self.node.command_queue.put(("text", text))
                else:
                    raw_path = str(action.get("path", ""))
                    if self.path and not Path(raw_path).expanduser().is_absolute():
                        raw_path = str((self.path.parent / raw_path).resolve())
                    print(f"[SCENARIO] IMAGE {raw_path}", flush=True)
                    self.node.command_queue.put(("image", raw_path))
            finally:
                self.index += 1
        if self.index >= len(self.actions):
            print("[SCENARIO] finished", flush=True)

    def pause(self) -> None:
        self.pause_event.set()
        print("[SCENARIO] paused", flush=True)

    def resume(self) -> None:
        self.pause_event.clear()
        print("[SCENARIO] resumed", flush=True)

    def stop(self) -> None:
        if self.thread and self.thread.is_alive():
            self.stop_event.set()
            self.pause_event.clear()
            self.thread.join(timeout=0.3)
        self.thread = None

    def status(self) -> None:
        state = "running" if self.thread and self.thread.is_alive() else "stopped"
        if self.pause_event.is_set():
            state = "paused"
        print(
            f"[SCENARIO] state={state} file={self.path or '-'} progress={self.index}/{len(self.actions)}",
            flush=True,
        )


class InteractiveNode:
    def __init__(self, name: str, node_id: int, host: str, port: int, timeout: float):
        self.name = name
        self.node_id = node_id
        self.timeout = timeout
        self.tian = TianSoftware(node_id)
        self.sock = socket.create_connection((host, port))
        send_json(self.sock, {"type": "HELLO", "node": name, "node_id": node_id})
        self.command_queue: queue.Queue[tuple[str, str | None]] = queue.Queue()
        self.requested = False
        self.last_tx = time.monotonic()
        self.running = True
        self.scenario = ScenarioPlayer(self)

    def enqueue_text(self, text: str) -> None:
        prepared = prepare_text(text)
        self.tian.queue_message(prepared.encrypted, ContentType.TEXT, "interactive-text")
        print(
            f"[QUEUE] TEXT {text!r} bytes={prepared.original_size} processed={prepared.processed_size}B depth={len(self.tian.outgoing)}",
            flush=True,
        )
        self.request_channel_if_needed()

    def enqueue_image(self, raw_path: str) -> None:
        path = Path(raw_path).expanduser().resolve()
        if not path.is_file():
            print(f"[ERROR] image not found: {path}", flush=True)
            return
        try:
            prepared = prepare_image(path)
        except Exception as exc:
            print(f"[ERROR] cannot prepare image: {exc}", flush=True)
            return
        self.tian.queue_message(prepared.encrypted, ContentType.IMAGE, prepared.display_name)
        print(
            f"[QUEUE] IMAGE {prepared.display_name!r} original={prepared.original_size}B processed={prepared.processed_size}B depth={len(self.tian.outgoing)}",
            flush=True,
        )
        self.request_channel_if_needed()

    def request_channel_if_needed(self) -> None:
        if self.tian.has_pending and not self.tian.outbound_busy and not self.requested:
            send_json(self.sock, {"type": "REQUEST_CHANNEL", "node": self.name})
            self.requested = True
            print("[CHANNEL] requested", flush=True)

    def stdin_worker(self) -> None:
        while self.running:
            try:
                line = input(f"{self.name}> ")
            except (EOFError, KeyboardInterrupt):
                self.command_queue.put(("quit", None))
                return
            line = line.strip()
            if not line:
                continue
            if not line.startswith("/"):
                self.command_queue.put(("text", line))
                continue
            command, _, argument = line.partition(" ")
            command = command.lower()
            argument = argument.strip()
            mapping = {
                "/image": "image",
                "/load": "load",
                "/run": "run",
                "/pause": "pause",
                "/resume": "resume",
                "/stop": "stop",
                "/scenario": "scenario",
                "/status": "status",
                "/help": "help",
                "/quit": "quit",
            }
            if command not in mapping:
                print(f"[ERROR] unknown command {command}; type /help", flush=True)
                continue
            self.command_queue.put((mapping[command], argument or None))

    def handle_command(self, command: str, argument: str | None) -> None:
        try:
            if command == "text":
                self.enqueue_text(argument or "")
            elif command == "image":
                if argument:
                    self.enqueue_image(argument)
                else:
                    print("Usage: /image <path>", flush=True)
            elif command == "load":
                if argument:
                    self.scenario.load(argument)
                else:
                    print("Usage: /load <node-scenario.json>", flush=True)
            elif command == "run":
                self.scenario.run()
            elif command == "pause":
                self.scenario.pause()
            elif command == "resume":
                self.scenario.resume()
            elif command == "stop":
                self.scenario.stop()
                print("[SCENARIO] stopped", flush=True)
            elif command == "scenario":
                self.scenario.status()
            elif command == "status":
                print(
                    f"[STATUS] pending={self.tian.has_pending} outbound_busy={self.tian.outbound_busy} queue_depth={len(self.tian.outgoing)} channel_requested={self.requested}",
                    flush=True,
                )
                self.scenario.status()
            elif command == "help":
                print(
                    "Commands:\n"
                    "  normal text          send a text message\n"
                    "  /image <path>        send an image\n"
                    "  /load <file.json>    load this node's scenario\n"
                    "  /run                 run loaded scenario\n"
                    "  /pause               pause scenario\n"
                    "  /resume              resume scenario\n"
                    "  /stop                stop scenario\n"
                    "  /scenario            show scenario progress\n"
                    "  /status              show node status\n"
                    "  /help                show commands\n"
                    "  /quit                exit live simulation",
                    flush=True,
                )
            elif command == "quit":
                self.running = False
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"[ERROR] {exc}", flush=True)

    def handle_message(self, message: dict) -> None:
        typ = message["type"]
        if typ == "GRANT":
            self.requested = False
            print(f"[CHANNEL] GRANTED backoff={message.get('backoff_ms')}ms", flush=True)
            frames = self.tian.begin_next_transfer()
            for raw in frames:
                print(f"[TX] {desc(Frame.decode(raw))}", flush=True)
                send_json(self.sock, {"type": "FRAME", "node": self.name, "data": b64e(raw)})
            self.last_tx = time.monotonic()
        elif typ == "FRAME":
            raw = b64d(message["data"])
            frame = Frame.decode(raw)
            print(f"[RX] {desc(frame)}", flush=True)
            responses = self.tian.handle_encoded_frame(raw)
            for outgoing in responses:
                print(f"[TX] {desc(Frame.decode(outgoing))}", flush=True)
                send_json(self.sock, {"type": "FRAME", "node": self.name, "data": b64e(outgoing)})
            if responses:
                self.last_tx = time.monotonic()
            for received in self.tian.pop_received_messages():
                decoded = decode_received(
                    received.payload,
                    received.content_type,
                    output_dir=ROOT / "received",
                    output_stem=f"node_{self.name}_from_{received.source_node_id}_{received.message_id:08X}",
                )
                if decoded["type"] == "text":
                    print(
                        f"\n[MESSAGE] TEXT from={received.source_node_id}: {decoded['text']}\n",
                        flush=True,
                    )
                elif decoded["type"] == "image":
                    print(
                        f"\n[MESSAGE] IMAGE from={received.source_node_id} saved={decoded['path']} size={decoded['width']}x{decoded['height']} jpeg={decoded['bytes']}B\n",
                        flush=True,
                    )
            if frame.frame_type == FrameType.COMPLETE and not self.tian.outbound_busy:
                print("[TRANSFER] COMPLETE", flush=True)
                self.request_channel_if_needed()
        elif typ == "STOP":
            self.running = False

    def run(self, startup_scenario: str | None = None, autorun: bool = False) -> None:
        print(f"=== LIVE TIAN SOFTWARE {self.name} (node_id={self.node_id}) ===", flush=True)
        print("Type /help for commands. Normal text sends immediately when the channel is available.", flush=True)
        if startup_scenario:
            try:
                self.scenario.load(startup_scenario)
                if autorun:
                    self.scenario.run()
            except Exception as exc:
                print(f"[ERROR] startup scenario: {exc}", flush=True)
        threading.Thread(target=self.stdin_worker, daemon=True).start()
        buffer = b""
        while self.running:
            while True:
                try:
                    command, argument = self.command_queue.get_nowait()
                except queue.Empty:
                    break
                self.handle_command(command, argument)
            self.request_channel_if_needed()
            self.sock.settimeout(0.05)
            try:
                messages, buffer, ok = recv_lines(self.sock, buffer)
            except socket.timeout:
                messages = []
                ok = True
            if not ok:
                print("[CONNECTION] panel disconnected", flush=True)
                break
            for message in messages:
                self.handle_message(message)
            if self.tian.outbound_busy and time.monotonic() - self.last_tx >= self.timeout:
                retry = self.tian.retry_after_timeout()
                if retry:
                    print("[TIMEOUT] no NACK/COMPLETE -> retry END", flush=True)
                    for raw in retry:
                        print(f"[TX] {desc(Frame.decode(raw))}", flush=True)
                        send_json(self.sock, {"type": "FRAME", "node": self.name, "data": b64e(raw)})
                    self.last_tx = time.monotonic()
        self.scenario.stop()
        try:
            self.sock.close()
        except OSError:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Interactive Tian Software process")
    parser.add_argument("--name", choices=["A", "B"], required=True)
    parser.add_argument("--id", type=int, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--timeout", type=float, default=1.2)
    parser.add_argument("--scenario", help="optional node scenario JSON to preload")
    parser.add_argument("--autorun", action="store_true", help="start preloaded scenario immediately")
    args = parser.parse_args()
    InteractiveNode(args.name, args.id, args.host, args.port, args.timeout).run(args.scenario, args.autorun)


if __name__ == "__main__":
    main()
