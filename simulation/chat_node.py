from __future__ import annotations

import argparse
import json
import queue
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from lore_protocol import Frame, FrameType
from simulation.common import b64d, recv_lines, send_json
from simulation.experiment_trace import print_trace_block
from simulation.interactive_node import InteractiveNode
from tian_payload import decode_received

ROOT = Path(__file__).resolve().parents[1]


class ConsoleFilter:
    """Filter backend output without changing the backend log generation order.

    Every write is still captured in order. In chat-only mode only user-facing
    lines and prompts are displayed. The full captured backend can later be
    replayed with /logs last.
    """

    ALWAYS_PREFIXES = (
        "[CHAT]",
        "[MESSAGE]",
        "[IMAGE]",
        "[PREVIEW]",
        "[ERROR]",
        "[CONNECTION]",
    )

    def __init__(self, owner: "ChatNode", stream):
        self.owner = owner
        self.stream = stream
        self.buffer = ""

    def write(self, data: str) -> int:
        if not data:
            return 0
        self.buffer += data
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            self.owner.capture_console_line(line)
            if self.owner.should_show_console_line(line):
                self.stream.write(line + "\n")
                self.stream.flush()
        return len(data)

    def flush(self) -> None:
        if self.buffer:
            # input() prompts do not end with a newline. Show them immediately.
            fragment = self.buffer
            self.buffer = ""
            self.owner.capture_console_line(fragment)
            if self.owner.should_show_console_line(fragment, fragment=True):
                self.stream.write(fragment)
        self.stream.flush()

    def isatty(self):
        return getattr(self.stream, "isatty", lambda: False)()

    @property
    def encoding(self):
        return getattr(self.stream, "encoding", "utf-8")


class ChatNode(InteractiveNode):
    def __init__(self, name: str, node_id: int, host: str, port: int, timeout: float):
        super().__init__(name, node_id, host, port, timeout)
        self.logs_visible = True
        self.console_history: list[str] = []
        self.transaction_log_start = 0
        self.last_transaction_logs: list[str] = []
        self.replaying_logs = False
        self.preview_mode = "auto"
        self.receive_dir = ROOT / "received" / f"node_{self.name}"
        self.receive_dir.mkdir(parents=True, exist_ok=True)
        self._real_stdout = sys.stdout
        self._console_filter = ConsoleFilter(self, self._real_stdout)
        sys.stdout = self._console_filter

    # ------------------------------------------------------------------
    # Console filtering / history
    # ------------------------------------------------------------------
    def capture_console_line(self, line: str) -> None:
        if self.replaying_logs:
            return
        self.console_history.append(line)
        # Bound memory while keeping plenty of recent experiment history.
        if len(self.console_history) > 20000:
            trim = 5000
            self.console_history = self.console_history[trim:]
            self.transaction_log_start = max(0, self.transaction_log_start - trim)

    def should_show_console_line(self, line: str, fragment: bool = False) -> bool:
        if self.replaying_logs or self.logs_visible:
            return True
        stripped = line.strip()
        if not stripped:
            return False
        if fragment and (line.endswith("> ") or line in {"A> ", "B> "}):
            return True
        if line.startswith(f"{self.name}> "):
            return True
        return stripped.startswith(ConsoleFilter.ALWAYS_PREFIXES)

    def begin_transaction_log(self) -> None:
        self.transaction_log_start = len(self.console_history)

    def snapshot_transaction_log(self) -> None:
        lines = self.console_history[self.transaction_log_start :]
        if lines:
            self.last_transaction_logs = list(lines)

    def replay_last_logs(self) -> None:
        if not self.last_transaction_logs:
            self._real_stdout.write("[LOGS] No completed chat/transfer log captured yet.\n")
            self._real_stdout.flush()
            return
        self.replaying_logs = True
        try:
            self._real_stdout.write("\n===== LAST CHAT / TRANSFER BACKEND LOG =====\n")
            for line in self.last_transaction_logs:
                self._real_stdout.write(line + "\n")
            self._real_stdout.write("===== END LAST BACKEND LOG =====\n\n")
            self._real_stdout.flush()
        finally:
            self.replaying_logs = False

    # ------------------------------------------------------------------
    # Human-facing chat helpers
    # ------------------------------------------------------------------
    def enqueue_text(self, text: str) -> None:
        self.begin_transaction_log()
        super().enqueue_text(text)
        print(f"[CHAT] You: {text}", flush=True)

    def enqueue_image(self, raw_path: str) -> None:
        path = Path(raw_path).expanduser().resolve()
        if path.is_file():
            self.begin_transaction_log()
        super().enqueue_image(raw_path)
        if path.is_file():
            print(f"[CHAT] You sent image: {path.name}", flush=True)

    def preview_image(self, path: str | Path) -> None:
        path = Path(path)
        if self.preview_mode == "off":
            return

        candidates: list[tuple[str, list[str]]] = []
        if self.preview_mode in {"auto", "chafa"}:
            candidates.append(("chafa", ["chafa", "--size", "80x30", str(path)]))
        if self.preview_mode in {"auto", "viu"}:
            candidates.append(("viu", ["viu", "-w", "80", str(path)]))

        for program, command in candidates:
            if not shutil.which(program):
                continue
            print(f"[PREVIEW] {path.name} via {program}", flush=True)
            try:
                subprocess.run(command, check=False)
            except OSError as exc:
                print(f"[ERROR] image preview failed with {program}: {exc}", flush=True)
            return

        print(
            f"[PREVIEW] No supported image renderer found; file saved at {path}",
            flush=True,
        )
        if self.preview_mode == "auto":
            print("[PREVIEW] Install 'chafa' (recommended) or 'viu' for terminal previews.", flush=True)

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------
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
                "/logs": "logs",
                "/image-preview": "image-preview",
                "/preview": "image-preview",
            }
            if command not in mapping:
                print(f"[ERROR] unknown command {command}; type /help", flush=True)
                continue
            self.command_queue.put((mapping[command], argument or None))

    def handle_command(self, command: str, argument: str | None) -> None:
        if command == "logs":
            mode = (argument or "status").strip().lower()
            if mode in {"on", "full", "show"}:
                self.logs_visible = True
                self._real_stdout.write("[LOGS] Full experiment logs ON.\n")
                self._real_stdout.flush()
            elif mode in {"off", "chat", "quiet"}:
                self.logs_visible = False
                self._real_stdout.write("[LOGS] Chat-only mode ON; backend logs are still being captured.\n")
                self._real_stdout.flush()
            elif mode in {"last", "previous"}:
                self.replay_last_logs()
            elif mode in {"status", ""}:
                state = "FULL" if self.logs_visible else "CHAT-ONLY"
                self._real_stdout.write(f"[LOGS] mode={state}; use /logs on | off | last\n")
                self._real_stdout.flush()
            else:
                self._real_stdout.write("[LOGS] Usage: /logs on | off | last | status\n")
                self._real_stdout.flush()
            return

        if command == "image-preview":
            mode = (argument or "status").strip().lower()
            if mode in {"auto", "chafa", "viu", "off"}:
                self.preview_mode = mode
                self._real_stdout.write(f"[PREVIEW] mode={mode}\n")
                self._real_stdout.flush()
            elif mode == "status":
                self._real_stdout.write(
                    f"[PREVIEW] mode={self.preview_mode}; auto tries chafa then viu\n"
                )
                self._real_stdout.flush()
            else:
                self._real_stdout.write(
                    "[PREVIEW] Usage: /image-preview auto | chafa | viu | off | status\n"
                )
                self._real_stdout.flush()
            return

        if command == "help":
            super().handle_command(command, argument)
            print(
                "  /logs off                     chat/image-only display; backend still captured\n"
                "  /logs on                      restore full experiment log display\n"
                "  /logs last                    replay backend log from latest chat/transfer\n"
                "  /image-preview auto           preview received image using chafa, then viu\n"
                "  /image-preview chafa|viu|off  force renderer or disable preview",
                flush=True,
            )
            return

        super().handle_command(command, argument)

    # ------------------------------------------------------------------
    # Protocol receive path. Reliability behavior is unchanged from the base
    # InteractiveNode; only received-file location and chat presentation differ.
    # ------------------------------------------------------------------
    def handle_message(self, message: dict) -> None:
        typ = message["type"]
        if typ != "FRAME":
            super().handle_message(message)
            return

        raw = b64d(message["data"])
        frame = Frame.decode(raw)
        self.last_tx = time.monotonic()
        print(
            f"[RX] {self._frame_desc(frame)} message_id=0x{frame.message_id:08X} "
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

        received_any = False
        for received in self.tian.pop_received_messages():
            received_any = True
            # For an inbound chat, begin the saved log at the first currently
            # available backend lines if this node was not already transmitting.
            if self.transaction_log_start >= len(self.console_history):
                self.transaction_log_start = max(0, len(self.console_history) - 50)

            decoded = decode_received(
                received.payload,
                received.content_type,
                output_dir=self.receive_dir,
                output_stem=f"from_{received.source_node_id}_{received.message_id:08X}",
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
                print(f"[CHAT] Node {received.source_node_id}: {decoded['text']}", flush=True)
            elif decoded["type"] == "image":
                print(
                    f"[IMAGE] Node {received.source_node_id} sent {decoded.get('filename', Path(decoded['path']).name)}",
                    flush=True,
                )
                print(f"[IMAGE] saved: {decoded['path']}", flush=True)
                self.preview_image(decoded["path"])

        if received_any:
            self.snapshot_transaction_log()

        if frame.frame_type == FrameType.COMPLETE and not self.tian.outbound_busy:
            print(
                f"[TRANSFER] COMPLETE message_id=0x{frame.message_id:08X}; reliable transaction finished",
                flush=True,
            )
            self.current_encode_trace = None
            self.snapshot_transaction_log()
            self.request_channel_if_needed()

    @staticmethod
    def _frame_desc(frame: Frame) -> str:
        # Keep wording/order identical to simulation.interactive_node.desc().
        from simulation.interactive_node import desc

        return desc(frame)

    def run(
        self,
        startup_scenario: str | None = None,
        autorun: bool = False,
        startup_tx_delay: str | None = None,
        startup_pacing: str | None = None,
    ) -> None:
        self._real_stdout.write(
            f"=== LIVE TIAN SOFTWARE {self.name} (node_id={self.node_id}) - SIMULATION HAUL UP ===\n"
        )
        self._real_stdout.write(
            "Use /logs off for chat-only mode, /logs last to inspect the latest backend, "
            "and /image-preview auto for terminal image rendering.\n"
        )
        self._real_stdout.write(f"Received images: {self.receive_dir}\n")
        self._real_stdout.flush()

        if startup_scenario:
            try:
                self.scenario.load(startup_scenario)
            except Exception as exc:
                print(f"[ERROR] startup scenario: {exc}", flush=True)
        if startup_pacing is not None:
            try:
                self.scenario.set_delay(startup_pacing)
            except ValueError as exc:
                print(f"[ERROR] startup scenario pacing: {exc}", flush=True)
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
            except TimeoutError:
                messages = []
                ok = True
            except OSError as exc:
                if "timed out" in str(exc).lower():
                    messages = []
                    ok = True
                else:
                    raise
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
        finally:
            sys.stdout = self._real_stdout


def main() -> None:
    parser = argparse.ArgumentParser(description="Interactive Tian chat/experiment node")
    parser.add_argument("--name", choices=["A", "B"], required=True)
    parser.add_argument("--id", type=int, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--timeout", type=float, default=1.2)
    parser.add_argument("--scenario")
    parser.add_argument("--autorun", action="store_true")
    parser.add_argument("--delay")
    parser.add_argument("--pacing")
    parser.add_argument(
        "--chat-only",
        action="store_true",
        help="start with backend logs hidden (same as /logs off)",
    )
    args = parser.parse_args()

    node = ChatNode(args.name, args.id, args.host, args.port, args.timeout)
    if args.chat_only:
        node.logs_visible = False
    node.run(args.scenario, args.autorun, args.delay, args.pacing)


if __name__ == "__main__":
    main()
