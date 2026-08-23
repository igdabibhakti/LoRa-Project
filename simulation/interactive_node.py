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

SCENARIO_PACING_PRESETS = {"normal": 0.0, "slow": 2.0, "very-slow": 5.0}
TX_FRAME_DELAY_PRESETS = {"normal": 0.0, "slow": 0.25, "very-slow": 1.0}
BUILDER_COMMANDS = {"make", "new", "edit", "builder"}


def desc(frame: Frame) -> str:
    if frame.frame_type == FrameType.DATA:
        return f"DATA index={frame.packet_index} total={frame.total_packets}"
    if frame.frame_type == FrameType.END:
        return f"END round={frame.packet_index}"
    if frame.frame_type == FrameType.NACK:
        return f"NACK {decode_missing_indexes(frame.payload)}"
    return "COMPLETE"


def _parse_delay(raw: str, presets: dict[str, float], label: str) -> tuple[str, float]:
    value = raw.strip().lower().replace("_", "-")
    if value in presets:
        return value, presets[value]
    try:
        seconds = float(value)
    except ValueError as exc:
        raise ValueError(
            f"{label} must be normal, slow, very-slow, or a non-negative number of seconds"
        ) from exc
    if seconds < 0:
        raise ValueError(f"{label} seconds cannot be negative")
    return f"custom-{seconds:g}s", seconds


def parse_scenario_pacing(raw: str) -> tuple[str, float]:
    return _parse_delay(raw, SCENARIO_PACING_PRESETS, "scenario pacing")


def parse_tx_frame_delay(raw: str) -> tuple[str, float]:
    return _parse_delay(raw, TX_FRAME_DELAY_PRESETS, "packet delay")


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
            print(
                f"[PACING] {self.delay_name} = +{self.extra_delay:g}s between scripted actions",
                flush=True,
            )
            print(
                "[PACING] normal=+0s, slow=+2s, very-slow=+5s, /pacing 1.5=+1.5s",
                flush=True,
            )
            return
        name, seconds = parse_scenario_pacing(str(raw))
        self.delay_name = name
        self.extra_delay = seconds
        if self.config:
            self.config["pacing"] = seconds if name.startswith("custom-") else name
        print(f"[PACING] set to {name}: +{seconds:g}s between scripted actions", flush=True)

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
        print(
            f"[SCENARIO] action pacing={self.delay_name} (+{self.extra_delay:g}s between actions)",
            flush=True,
        )

    def run(self) -> None:
        if not self.actions:
            print(
                "[SCENARIO] nothing loaded; use /scenario list, /scenario select, or /scenario make",
                flush=True,
            )
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
        print(
            f"[SCENARIO] started at action {self.index + 1}/{len(self.actions)} pacing={self.delay_name}",
            flush=True,
        )

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
            f"pacing={self.delay_name} extra_action_delay=+{self.extra_delay:g}s",
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
        self.tx_delay_name = "normal"
        self.tx_frame_delay = 0.0

    def set_tx_delay(self, raw: str | None = None) -> None:
        if raw is None:
            print(
                f"[TX DELAY] {self.tx_delay_name} = {self.tx_frame_delay:g}s between protocol frames",
                flush=True,
            )
            print(
                "[TX DELAY] normal=0s, slow=0.25s, very-slow=1s, /delay 0.5=0.5s",
                flush=True,
            )
            return
        name, seconds = parse_tx_frame_delay(raw)
        self.tx_delay_name = name
        self.tx_frame_delay = seconds
        print(
            f"[TX DELAY] set to {name}: {seconds:g}s between DATA/END/NACK/COMPLETE frames",
            flush=True,
        )

    def report_encode(self, prepared) -> None:
        trace = dict(prepared.trace)
        self.pending_encode_traces.append(trace)
        print_trace_block("TIAN ENCODING PROCESS", trace)
        send_json(
            self.sock,
            {"type": "TRACE", "node": self.name, "stage": "ENCODE", "trace": trace},
        )

    def enqueue_text(self, text: str) -> None:
        prepared = prepare_text(text)
        self.report_encode(prepared)
        self.tian.queue_message(prepared.encrypted, ContentType.TEXT, "interactive-text")
        print(
            f"[QUEUE] TEXT {text!r} bytes={prepared.original_size} processed={prepared.processed_size}B "
            f"depth={len(self.tian.outgoing)}",
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

    def _builder_requested(self, command: str, argument: str) -> bool:
        if command not in {"/scenario", "/protocol"}:
            return False
        subcommand = argument.strip().partition(" ")[0].lower()
        return subcommand in BUILDER_COMMANDS

    def _run_builder_from_stdin(self) -> None:
        """Run the modal builder in the one and only stdin-reading thread."""
        try:
            new_path = run_terminal_builder(
                self.name,
                self.scenario_store,
                self.scenario.path,
                self.scenario.config if self.scenario.actions else None,
                self.scenario.config.get("pacing", self.scenario.delay_name),
            )
        except (EOFError, KeyboardInterrupt):
            print("\n[SCENARIO] builder cancelled", flush=True)
            return
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"[ERROR] scenario builder: {exc}", flush=True)
            return
        if new_path:
            # The network/main loop owns scenario state changes. The stdin
            # thread only gathers terminal input, then asks the main loop to
            # load the newly saved file.
            self.command_queue.put(("builder_saved", str(new_path)))

    def stdin_worker(self) -> None:
        """Exclusive owner of keyboard input for the entire node process."""
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

            # IMPORTANT: the scenario builder itself uses input(). Running it
            # here prevents the old bug where the main loop and stdin_worker
            # both waited on input() and stole each other's keystrokes.
            if self._builder_requested(command, argument):
                self._run_builder_from_stdin()
                continue

            mapping = {
                "/image": "image",
                "/load": "load",
                "/run": "run",
                "/pause": "pause",
                "/resume": "resume",
                "/stop": "stop",
                "/delay": "delay",
                "/pacing": "pacing",
                "/scenario-delay": "pacing",
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
        if subcommand in BUILDER_COMMANDS:
            # This is only a safety fallback. Normal terminal input intercepts
            # builder commands in stdin_worker so the main loop never calls
            # input() itself.
            print(
                "[SCENARIO] builder must run from the terminal input thread; type /scenario make again",
                flush=True,
            )
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
            elif command == "builder_saved":
                if argument:
                    self.scenario.load(argument)
                    self.scenario.preview()
                    print(
                        "[SCENARIO] New file is preloaded. Type /run when ready.",
                        flush=True,
                    )
            elif command == "run":
                self.scenario.run()
            elif command == "pause":
                self.scenario.pause()
            elif command == "resume":
                self.scenario.resume()
            elif command == "stop":
                self.scenario.stop()
                print("[SCENARIO] stopped", flush=True)
            elif command == "delay":
                self.set_tx_delay(argument)
            elif command == "pacing":
                self.scenario.set_delay(argument)
            elif command == "scenario":
                self.scenario_command(argument)
            elif command == "status":
                print(
                    f"[STATUS] pending={self.tian.has_pending} outbound_busy={self.tian.outbound_busy} "
                    f"queue_depth={len(self.tian.outgoing)} channel_requested={self.requested}",
                    flush=True,
                )
                print(
                    f"[STATUS] tx_delay={self.tx_delay_name} ({self.tx_frame_delay:g}s between frames)",
                    flush=True,
                )
                self.scenario.status()
            elif command == "help":
                print(
                    "Commands:\n"
                    "  normal text                   send text + show encoding/transmission detail\n"
                    "  /image <path>                 send image + show codec/transmission detail\n"
                    "  /delay                        show REAL packet/frame transmission delay\n"
                    "  /delay normal                 0s between DATA/END/NACK/COMPLETE frames\n"
                    "  /delay slow                   0.25s between frames; easy to watch\n"
                    "  /delay very-slow              1s between frames; demo/debug speed\n"
                    "  /delay 0.5                    custom 0.5s between frames\n"
                    "  /pacing normal                +0s between scenario actions\n"
                    "  /pacing slow                  +2s between scenario actions\n"
                    "  /pacing very-slow             +5s between scenario actions\n"
                    "  /scenario list               list saved node scenarios\n"
                    "  /scenario select <n/name>    select + preview + preload an old scenario\n"
                    "  /scenario preview            preview currently loaded scenario\n"
                    "  /scenario make               terminal-only scenario builder/editor\n"
                    "  /protocol ...                alias for /scenario ...\n"
                    "  /load <file.json>             direct-path preload (power-user shortcut)\n"
                    "  /run                          run loaded scenario\n"
                    "  /pause /resume /stop          control scenario playback\n"
                    "  /status                       node + TX delay + scenario status\n"
                    "  /help                         show commands\n"
                    "  /quit                         exit this Tian terminal",
                    flush=True,
                )
            elif command == "quit":
                self.running = False
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"[ERROR] {exc}", flush=True)

    def send_frames_with_detail(self, frames: list[bytes], title: str) -> None:
        if not frames:
            return
        summary = transfer_summary(frames)
        summary["tx_delay_name"] = self.tx_delay_name
        summary["inter_frame_delay_ms"] = round(self.tx_frame_delay * 1000, 3)
        print_transfer_summary(summary, title)
        send_json(
            self.sock,
            {"type": "TRACE", "node": self.name, "stage": "TX_WINDOW", "trace": summary},
        )
        if self.tx_frame_delay > 0 and len(frames) > 1:
            print(
                f"[TX PACING] {self.tx_delay_name}: waiting {self.tx_frame_delay:g}s between "
                f"{len(frames)} protocol frames",
                flush=True,
            )
        for index, raw in enumerate(frames):
            if index > 0 and self.tx_frame_delay > 0:
                time.sleep(self.tx_frame_delay)
            frame = Frame.decode(raw)
            print(
                f"[TX] {desc(frame)} message_id=0x{frame.message_id:08X} "
                f"content={frame.content_type.name} frame_bytes={len(raw)}",
                flush=True,
            )
            send_json(self.sock, {"type": "FRAME", "node": self.name, "data": b64e(raw)})

    def handle_message(self, message: dict) -> None:
        typ = message["type"]
        if typ == "GRANT":
            self.requested = False
            print(f"[CHANNEL] GRANTED backoff={message.get('backoff_ms')}ms", flush=True)
            frames = self.tian.begin_next_transfer()
            self.current_encode_trace = (
                self.pending_encode_traces.pop(0) if self.pending_encode_traces else None
            )
            self.tx_round = 0
            self.send_frames_with_detail(frames, "INITIAL TRANSMISSION")
            self.last_tx = time.monotonic()
            return

        if typ == "FRAME":
            raw = b64d(message["data"])
            frame = Frame.decode(raw)
            self.last_tx = time.monotonic()
            print(
                f"[RX] {desc(frame)} message_id=0x{frame.message_id:08X} "
                f"content={frame.content_type.name} frame_bytes={len(raw)}",
                flush=True,
            )
            responses = self.tian.handle_encoded_frame(raw)
            if responses:
                self.tx_round += 1
                title = (
                    "PROTOCOL RESPONSE"
                    if frame.frame_type != FrameType.NACK
                    else f"SELECTIVE RETRANSMISSION ROUND {self.tx_round}"
                )
                self.send_frames_with_detail(responses, title)
                self.last_tx = time.monotonic()

            for received in self.tian.pop_received_messages():
                decoded = decode_received(
                    received.payload,
                    received.content_type,
                    output_dir=ROOT / "received",
                    output_stem=(
                        f"node_{self.name}_from_{received.source_node_id}_{received.message_id:08X}"
                    ),
                )
                print_trace_block("TIAN DECODING PROCESS", decoded.get("trace", {}))
                send_json(
                    self.sock,
                    {
                        "type": "TRACE",
                        "node": self.name,
                        "stage": "DECODE",
                        "trace": decoded.get("trace", {}),
                    },
                )
                print(
                    f"[EXPRIMT] RECEIVE COMPLETE message_id=0x{received.message_id:08X} "
                    f"source={received.source_node_id} content={received.content_type.name}",
                    flush=True,
                )
                if decoded["type"] == "text":
                    print(
                        f"\n[MESSAGE] TEXT from={received.source_node_id}: {decoded['text']}\n",
                        flush=True,
                    )
                elif decoded["type"] == "image":
                    print(
                        f"\n[MESSAGE] IMAGE from={received.source_node_id} saved={decoded['path']} "
                        f"size={decoded['width']}x{decoded['height']} jpeg={decoded['bytes']}B\n",
                        flush=True,
                    )

            if frame.frame_type == FrameType.COMPLETE and not self.tian.outbound_busy:
                print(
                    f"[TRANSFER] COMPLETE message_id=0x{frame.message_id:08X}; "
                    "reliable transaction finished",
                    flush=True,
                )
                self.current_encode_trace = None
                self.request_channel_if_needed()
            return

        if typ == "STOP":
            self.running = False

    def run(
        self,
        startup_scenario: str | None = None,
        autorun: bool = False,
        startup_tx_delay: str | None = None,
        startup_pacing: str | None = None,
    ) -> None:
        print(f"=== LIVE TIAN SOFTWARE {self.name} (node_id={self.node_id}) ===", flush=True)
        print("Normal text sends live. Type /help for commands.", flush=True)
        print(
            "EXPERIMENT VIEW is enabled: encode, packet/frame, retransmission, and decode details are shown.",
            flush=True,
        )
        print(
            "REAL TX packet delay: /delay normal=0s, slow=0.25s, very-slow=1s between frames.",
            flush=True,
        )
        print(
            "Scenario-message pacing is separate: /pacing normal=0s, slow=+2s, very-slow=+5s.",
            flush=True,
        )
        print(
            "Node scenarios can be CREATED, PREVIEWED, SAVED, and SELECTED entirely in this terminal.",
            flush=True,
        )
        print("Start with /scenario list or /scenario make.", flush=True)

        if startup_scenario:
            try:
                self.scenario.load(startup_scenario)
            except Exception as exc:
                print(f"[ERROR] startup scenario: {exc}", flush=True)
        if startup_pacing is not None:
            try:
                self.scenario.set_delay(startup_pacing)
            except ValueError as exc:
                print(
                    f"[ERROR] startup scenario pacing: {exc}; keeping scenario/default pacing",
                    flush=True,
                )
        if startup_tx_delay is not None:
            try:
                self.set_tx_delay(startup_tx_delay)
            except ValueError as exc:
                print(f"[ERROR] startup TX delay: {exc}; using normal", flush=True)
        if autorun and self.scenario.actions:
            self.scenario.run()

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
                    self.tx_round += 1
                    print("[TIMEOUT] no NACK/COMPLETE -> retry protocol window", flush=True)
                    self.send_frames_with_detail(retry, f"TIMEOUT RETRY ROUND {self.tx_round}")
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
    parser.add_argument(
        "--autorun",
        action="store_true",
        help="start preloaded scenario immediately",
    )
    parser.add_argument(
        "--delay",
        help="REAL inter-frame TX delay: normal, slow, very-slow, or custom seconds",
    )
    parser.add_argument(
        "--pacing",
        help="scenario action pacing override: normal, slow, very-slow, or custom seconds",
    )
    args = parser.parse_args()
    InteractiveNode(args.name, args.id, args.host, args.port, args.timeout).run(
        args.scenario,
        args.autorun,
        args.delay,
        args.pacing,
    )


if __name__ == "__main__":
    main()
