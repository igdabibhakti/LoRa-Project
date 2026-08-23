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
from simulation.experiment_trace import print_trace_block, print_transfer_summary, transfer_summary
from simulation.node_scenario_manager import NodeScenarioStore, run_terminal_builder
from tian_payload import decode_received, prepare_image, prepare_text
from tian_software import TianSoftware

ROOT = Path(__file__).resolve().parents[1]

DELAY_PRESETS = {
    "normal": 0.0,
    "slow": 2.0,
    "very-slow": 5.0,
}


def desc(frame: Frame) -> str:
    if frame.frame_type == FrameType.DATA:
        return f"DATA index={frame.packet_index} total={frame.total_packets}"
    if frame.frame_type == FrameType.END:
        return f"END round={frame.packet_index}"
    if frame.frame_type == FrameType.NACK:
        return f"NACK {decode_missing_indexes(frame.payload)}"
    return "COMPLETE"


def parse_scenario_delay(raw: str) -> tuple[str, float]:
    value = raw.strip().lower().replace("_", "-")
    if value in DELAY_PRESETS:
        return value, DELAY_PRESETS[value]
    try:
        seconds = float(value)
    except ValueError as exc:
        raise ValueError(
            "delay must be normal, slow, very-slow, or a non-negative number of seconds"
        ) from exc
    if seconds < 0:
        raise ValueError("delay seconds cannot be negative")
    return f"custom-{seconds:g}s", seconds


class ScenarioPlayer:
    def __init__(self, node: "InteractiveNode"):
        self.node = node
        self.path: Path | None = None
        self.config: dict = {"name": "", "pacing": "normal", "actions": []}
        self.actions: list[dict] = []
        self.thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.index = 0
        self.delay_name = "normal"
        self.extra_delay = 0.0

    def set_delay(self, raw: str | float | int | None = None) -> None:
        if raw is None:
            print(f"[DELAY] {self.delay_name} = +{self.extra_delay:g}s between scripted actions", flush=True)
            print("[DELAY] normal=+0s, slow=+2s, very-slow=+5s, /delay 1.5=+1.5s", flush=True)
            return
        name, seconds = parse_scenario_delay(str(raw))
        self.delay_name = name
        self.extra_delay = seconds
        if self.config:
            self.config["pacing"] = seconds if name.startswith("custom-") else name
        print(f"[DELAY] set to {name}: +{seconds:g}s between scripted actions", flush=True)
        if seconds == 0:
            print("[DELAY] NORMAL: scenario uses only each action's own delay.", flush=True)
        elif seconds <= 2:
            print("[DELAY] SLOW: easier to watch the sequence and packet logs.", flush=True)
        else:
            print("[DELAY] VERY SLOW: good for demos, teaching, and debugging.", flush=True)

    def load(self, raw_path: str | Path, apply_saved_pacing: bool = True) -> None:
        path, cfg = self.node.scenario_store.load(raw_path)
        self.stop()
        self.path = path
        self.config = cfg
        self.actions = list(cfg.get("actions", []))
        self.index = 0
        if apply_saved_pacing and "pacing" in cfg:
            self.set_delay(cfg["pacing"])
        print(f"[SCENARIO] loaded {len(self.actions)} actions from {path}", flush=True)
        print(f"[SCENARIO] pacing={self.delay_name} (+{self.extra_delay:g}s between actions)", flush=True)

    def run(self) -> None:
        if not self.actions:
            print("[SCENARIO] nothing loaded; use /scenario list, /scenario select, or /scenario make", flush=True)
            return
        if self.thread and self.thread.is_alive():
            print("[SCENARIO] already running", flush=True)
            return
        if self.index >= len(self.actions):
            self.index = 0
        self.stop_event.clear()
        self.pause_event.clear()
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()
        print(f"[SCENARIO] started at action {self.index + 1}/{len(self.actions)} pacing={self.delay_name}", flush=True)

    def _worker(self) -> None:
        while self.index < len(self.actions) and not self.stop_event.is_set():
            action = self.actions[self.index]
            base_delay = float(action.get("delay", 0))
            pacing_delay = self.extra_delay if self.index > 0 else 0.0
            delay = base_delay + pacing_delay
            if delay > 0:
                print(
                    f"[SCENARIO] next action #{self.index + 1} in {delay:g}s "
                    f"(action={base_delay:g}s + pacing={pacing_delay:g}s)",
                    flush=True,
                )
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
            f"[SCENARIO] state={state} file={self.path or '-'} progress={self.index}/{len(self.actions)} "
            f"pacing={self.delay_name} extra_delay=+{self.extra_delay:g}s",
            flush=True,
        )

    def preview(self) -> None:
        if not self.actions:
            print("[SCENARIO] no scenario loaded", flush=True)
            return
        self.node.scenario_store.preview(self.config, self.path, "LOADED SCENARIO PREVIEW")


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
        self.scenario_store = NodeScenarioStore(ROOT)
        self.scenario = ScenarioPlayer(self)
        self.pending_encode_traces: list[dict] = []
        self.current_encode_trace: dict | None = None
        self.tx_round = 0

    def report_encode(self, prepared) -> None:
        trace = dict(prepared.trace)
        self.pending_encode_traces.append(trace)
        print_trace_block("TIAN ENCODING PROCESS", trace)
        send_json(self.sock, {"type": "TRACE", "node": self.name, "stage": "ENCODE", "trace": trace})

    def enqueue_text(self, text: str) -> None:
        prepared = prepare_text(text)
        self.report_encode(prepared)
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
        self.report_encode(prepared)
        self.tian.queue_message(prepared.encrypted, ContentType.IMAGE, prepared.display_name)
        print(
            f"[QUEUE] IMAGE {prepared.display_name!r} original={prepared.original_size}B "
            f"processed={prepared.processed_size}B depth={len(self.tian.outgoing)}",
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
                "/delay": "delay",
                "/scenario": "scenario",
                "/protocol": "scenario",
                "/status": "status",
                "/help": "help",
                "/quit": "quit",
            }
            if command not in mapping:
                print(f"[ERROR] unknown command {command}; type /help", flush=True)
                continue
            self.command_queue.put((mapping[command], argument or None))

    def scenario_command(self, argument: str | None) -> None:
        raw = (argument or "").strip()
        subcommand, _, value = raw.partition(" ")
        subcommand = subcommand.lower()
        value = value.strip()
        if not subcommand:
            self.scenario.status()
            print("Use /scenario list | select <n/name> | preview | make", flush=True)
            return
        if subcommand in {"list", "ls"}:
            self.scenario_store.print_list()
            return
        if subcommand in {"preview", "show"}:
            self.scenario.preview()
            return
        if subcommand in {"select", "use", "load"}:
            path = self.scenario_store.resolve(value)
            self.scenario.load(path)
            self.scenario.preview()
            return
        if subcommand in {"make", "new", "edit", "builder"}:
            new_path = run_terminal_builder(
                self.name,
                self.scenario_store,
                self.scenario.path,
                self.scenario.config if self.scenario.actions else None,
                self.scenario.config.get("pacing", self.scenario.delay_name),
            )
            if new_path:
                self.scenario.load(new_path)
                self.scenario.preview()
                print("[SCENARIO] New file is preloaded. Type /run when ready.", flush=True)
            return
        print("Usage: /scenario list | select <number/name/path> | preview | make", flush=True)

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
                    self.scenario.preview()
                else:
                    print("Usage: /load <node-scenario.json>", flush=True)
            elif command == "run": self.scenario.run()
            elif command == "pause": self.scenario.pause()
            elif command == "resume": self.scenario.resume()
            elif command == "stop":
                self.scenario.stop(); print("[SCENARIO] stopped", flush=True)
            elif command == "delay": self.scenario.set_delay(argument)
            elif command == "scenario": self.scenario_command(argument)
            elif command == "status":
                print(
                    f"[STATUS] pending={self.tian.has_pending} outbound_busy={self.tian.outbound_busy} "
                    f"queue_depth={len(self.tian.outgoing)} channel_requested={self.requested}", flush=True,
                )
                self.scenario.status()
            elif command == "help":
                print(
                    "Commands:\n"
                    "  normal text                   send text + show encoding/transmission detail\n"
                    "  /image <path>                 send image + show codec/transmission detail\n"
                    "  /scenario list               list saved node scenarios\n"
                    "  /scenario select <n/name>    select + preview + preload an old scenario\n"
                    "  /scenario preview            preview currently loaded scenario\n"
                    "  /scenario make               terminal-only scenario builder/editor\n"
                    "  /protocol ...                alias for /scenario ...\n"
                    "  /load <file.json>             direct-path preload (power-user shortcut)\n"
                    "  /run                          run loaded scenario\n"
                    "  /pause /resume /stop          control scenario playback\n"
                    "  /delay normal                 +0s extra between scripted actions\n"
                    "  /delay slow                   +2s extra between scripted actions\n"
                    "  /delay very-slow              +5s extra between scripted actions\n"
                    "  /delay 1.5                    custom +1.5s extra between actions\n"
                    "  /status                       node + scenario status\n"
                    "  /help                         show commands\n"
                    "  /quit                         exit this Tian terminal",
                    flush=True,
                )
            elif command == "quit": self.running = False
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"[ERROR] {exc}", flush=True)

    def send_frames_with_detail(self, frames: list[bytes], title: str) -> None:
        if not frames:
            return
        summary = transfer_summary(frames)
        print_transfer_summary(summary, title)
        send_json(self.sock, {"type": "TRACE", "node": self.name, "stage": "TX_WINDOW", "trace": summary})
        for raw in frames:
            frame = Frame.decode(raw)
            print(
                f"[TX] {desc(frame)} message_id=0x{frame.message_id:08X} content={frame.content_type.name} frame_bytes={len(raw)}",
                flush=True,
            )
            send_json(self.sock, {"type": "FRAME", "node": self.name, "data": b64e(raw)})

    def handle_message(self, message: dict) -> None:
        typ = message["type"]
        if typ == "GRANT":
            self.requested = False
            print(f"[CHANNEL] GRANTED backoff={message.get('backoff_ms')}ms", flush=True)
            frames = self.tian.begin_next_transfer()
            self.current_encode_trace = self.pending_encode_traces.pop(0) if self.pending_encode_traces else None
            self.tx_round = 0
            self.send_frames_with_detail(frames, "INITIAL TRANSMISSION")
            self.last_tx = time.monotonic()
        elif typ == "FRAME":
            raw = b64d(message["data"])
            frame = Frame.decode(raw)
            print(
                f"[RX] {desc(frame)} message_id=0x{frame.message_id:08X} content={frame.content_type.name} frame_bytes={len(raw)}",
                flush=True,
            )
            responses = self.tian.handle_encoded_frame(raw)
            if responses:
                self.tx_round += 1
                title = "PROTOCOL RESPONSE" if frame.frame_type != FrameType.NACK else f"SELECTIVE RETRANSMISSION ROUND {self.tx_round}"
                self.send_frames_with_detail(responses, title)
                self.last_tx = time.monotonic()
            for received in self.tian.pop_received_messages():
                decoded = decode_received(
                    received.payload,
                    received.content_type,
                    output_dir=ROOT / "received",
                    output_stem=f"node_{self.name}_from_{received.source_node_id}_{received.message_id:08X}",
                )
                print_trace_block("TIAN DECODING PROCESS", decoded.get("trace", {}))
                send_json(
                    self.sock,
                    {"type": "TRACE", "node": self.name, "stage": "DECODE", "trace": decoded.get("trace", {})},
                )
                print(
                    f"[EXPERIMENT] RECEIVE COMPLETE message_id=0x{received.message_id:08X} "
                    f"source={received.source_node_id} content={received.content_type.name}",
                    flush=True,
                )
                if decoded["type"] == "text":
                    print(f"\n[MESSAGE] TEXT from={received.source_node_id}: {decoded['text']}\n", flush=True)
                elif decoded["type"] == "image":
                    print(
                        f"\n[MESSAGE] IMAGE from={received.source_node_id} saved={decoded['path']} "
                        f"size={decoded['width']}x{decoded['height']} jpeg={decoded['bytes']}B\n",
                        flush=True,
                    )
            if frame.frame_type == FrameType.COMPLETE and not self.tian.outbound_busy:
                print(
                    f"[TRANSFER] COMPLETE message_id=0x{frame.message_id:08X}; reliable transaction finished",
                    flush=True,
                )
                self.current_encode_trace = None
                self.request_channel_if_needed()
        elif typ == "STOP":
            self.running = False

    def run(self, startup_scenario: str | None = None, autorun: bool = False, startup_delay: str | None = None) -> None:
        print(f"=== LIVE TIAN SOFTWARE {self.name} (node_id={self.node_id}) ===", flush=True)
        print("Normal text sends live. Type /help for commands.", flush=True)
        print("EXPERIMENT VIEW is enabled: encode, packet/frame, retransmission, and decode details are shown.", flush=True)
        print("Node scenarios can be CREATED, PREVIEWED, SAVED, and SELECTED entirely in this terminal.", flush=True)
        print("Start with /scenario list or /scenario make.", flush=True)
        print("Scenario pacing: normal=+0s, slow=+2s, very-slow=+5s.", flush=True)
        if startup_scenario:
            try: self.scenario.load(startup_scenario)
            except Exception as exc: print(f"[ERROR] startup scenario: {exc}", flush=True)
        if startup_delay is not None:
            try: self.scenario.set_delay(startup_delay)
            except ValueError as exc: print(f"[ERROR] startup delay: {exc}; keeping scenario/default pacing", flush=True)
        if autorun and self.scenario.actions:
            self.scenario.run()
        threading.Thread(target=self.stdin_worker, daemon=True).start()
        buffer = b""
        while self.running:
            while True:
                try: command, argument = self.command_queue.get_nowait()
                except queue.Empty: break
                self.handle_command(command, argument)
            self.request_channel_if_needed()
            self.sock.settimeout(0.05)
            try:
                messages, buffer, ok = recv_lines(self.sock, buffer)
            except socket.timeout:
                messages = []; ok = True
            if not ok:
                print("[CONNECTION] panel disconnected", flush=True); break
            for message in messages:
                self.handle_message(message)
            if self.tian.outbound_busy and time.monotonic() - self.last_tx >= self.timeout:
                retry = self.tian.retry_after_timeout()
                if retry:
                    self.tx_round += 1
                    print("[TIMEOUT] no NACK/COMPLETE -> retry protocol window", flush=True)
                    self.send_frames_with_detail(retry, f"TIMEOUT RETRY ROUND {self.tx_round}")
                    self.last_tx = time.monotonic()
        self.scenario.stop()
        try: self.sock.close()
        except OSError: pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Interactive Tian Software process")
    parser.add_argument("--name", choices=["A", "B"], required=True)
    parser.add_argument("--id", type=int, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--timeout", type=float, default=1.2)
    parser.add_argument("--scenario", help="optional node scenario JSON to preload")
    parser.add_argument("--autorun", action="store_true", help="start preloaded scenario immediately")
    parser.add_argument("--delay", help="override scenario pacing: normal, slow, very-slow, or custom seconds")
    args = parser.parse_args()
    InteractiveNode(args.name, args.id, args.host, args.port, args.timeout).run(args.scenario, args.autorun, args.delay)


if __name__ == "__main__":
    main()
