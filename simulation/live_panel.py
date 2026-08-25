from __future__ import annotations

import argparse
import json
import queue
import random
from pathlib import Path

from simulation.channel_scenario_manager import ChannelScenarioStore
from simulation.channel_scenario_manager_v2 import run_channel_builder_v2
from simulation.per_transmission_panel import PerTransmissionPanel

ROOT = Path(__file__).resolve().parents[1]
BUILDER_COMMANDS = {"make", "new", "edit", "builder"}


class LivePanel(PerTransmissionPanel):
    """Streaming Panel plus terminal-only channel scenario management."""

    def __init__(self, cfg: dict, scenario_path: str | Path | None = None):
        super().__init__(cfg, live=True)
        self.scenario_store = ChannelScenarioStore(ROOT)
        self.scenario_path = Path(scenario_path).expanduser().resolve() if scenario_path else None

    def _builder_requested(self, raw: str) -> bool:
        command = raw[1:] if raw.startswith("/") else raw
        head, _, rest = command.partition(" ")
        if head.lower() != "scenario":
            return False
        subcommand = rest.strip().partition(" ")[0].lower()
        return subcommand in BUILDER_COMMANDS

    def stdin_worker(self):
        """Exclusive owner of panel stdin, including the modal builder."""
        while self.running:
            try:
                raw = input("PANEL> ").strip()
            except (EOFError, KeyboardInterrupt):
                return
            if not raw:
                continue
            if self._builder_requested(raw):
                try:
                    new_path = run_channel_builder_v2(
                        self.scenario_store,
                        self.scenario_path,
                        self.cfg,
                    )
                except (EOFError, KeyboardInterrupt):
                    print("\n[PANEL] channel scenario builder cancelled", flush=True)
                    continue
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    self.log(f"channel scenario builder error: {exc}")
                    continue
                if new_path:
                    self.command_queue.put(f"scenario __builder_saved__ {new_path}")
                continue
            self.command_queue.put(raw)

    def process_commands(self):
        while True:
            try:
                raw = self.command_queue.get_nowait()
            except queue.Empty:
                return
            command = raw[1:] if raw.startswith("/") else raw
            head, _, rest = command.partition(" ")
            head = head.lower()
            rest = rest.strip()
            if head == "metadata":
                self.metadata_command(rest.lower())
            elif head == "scenario":
                self.scenario_command(rest)
            elif head == "help":
                self.print_help()
            else:
                self.log("unknown panel command; use /help")

    def print_help(self):
        print(
            "\n=== PANEL COMMANDS ===\n"
            "/scenario                         show selected scenario status\n"
            "/scenario list                    list saved channel scenarios\n"
            "/scenario select <n/name/path>    preload an old channel scenario\n"
            "/scenario preview                 preview selected channel scenario\n"
            "/scenario make                    terminal-only packet-loss scenario builder\n"
            "/metadata current                 show latest full metadata snapshot once\n"
            "/metadata on                      full metadata for every TX/retry sequence\n"
            "/metadata off                     stop automatic full metadata\n"
            "/metadata status                  show metadata mode\n"
            "/help                             show this help\n",
            flush=True,
        )

    def scenario_command(self, argument: str) -> None:
        raw = argument.strip()
        subcommand, _, value = raw.partition(" ")
        subcommand = subcommand.lower()
        value = value.strip()

        if subcommand == "__builder_saved__":
            self.load_channel_scenario(value)
            return
        if not subcommand:
            print(
                f"[PANEL] channel scenario={self.scenario_path or '(startup/in-memory)'} "
                f"transmission_position={self.seq_i}/{len(self.cfg.get('sequences', []))}",
                flush=True,
            )
            print("Use /scenario list | select <n/name> | preview | make", flush=True)
            return
        if subcommand in {"list", "ls"}:
            self.scenario_store.print_list()
            return
        if subcommand in {"preview", "show"}:
            self.scenario_store.preview(self.cfg, self.scenario_path, "SELECTED CHANNEL SCENARIO")
            return
        if subcommand in {"select", "use", "load"}:
            try:
                path = self.scenario_store.resolve(value)
                self.load_channel_scenario(path)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                self.log(f"cannot select channel scenario: {exc}")
            return
        if subcommand in BUILDER_COMMANDS:
            self.log("type /scenario make directly at PANEL> to open the builder")
            return
        self.log("usage: /scenario list | select <number/name/path> | preview | make")

    def load_channel_scenario(self, raw_path: str | Path) -> None:
        if self.active_tx_window is not None or self.active_nack_tx:
            self.log(
                "cannot switch channel scenario while a transmission is active; "
                "wait until the current DATA/NACK transmission finishes"
            )
            return
        path, cfg = self.scenario_store.load(raw_path)
        self.cfg = cfg
        self.scenario_path = path
        self.rng = random.Random(cfg.get("seed"))
        self.seq_i = 0
        self.response_seq.clear()
        self.pending_retry_indexes.clear()
        self.nack_pages.clear()
        self.active_nack_tx.clear()
        self.continuous_probability_loss = None
        self.continuous_control_drops = None
        self.latest_sequence_metadata = None
        self.log(f"preloaded channel scenario: {path}")
        self.scenario_store.preview(cfg, path, "PRELOADED CHANNEL SCENARIO")

    def run(self, host, port):
        print("Live channel scenario commands: /scenario list | select | preview | make", flush=True)
        print("Channel scenarios are consumed per transmission: DATA, END, NACK, COMPLETE.", flush=True)
        return super().run(host, port)


def main() -> None:
    parser = argparse.ArgumentParser(description="Live simulation panel with terminal scenario builder")
    parser.add_argument(
        "--scenario",
        default=str(Path(__file__).parent / "scenarios" / "live_channel.json"),
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    scenario_path = Path(args.scenario).expanduser().resolve()
    with scenario_path.open("r", encoding="utf-8") as handle:
        cfg = json.load(handle)
    ChannelScenarioStore(ROOT).validate(cfg, str(scenario_path))
    print("=== SIMULATION CONTROL / MONITOR PANEL ===")
    print(json.dumps(cfg, indent=2))
    LivePanel(cfg, scenario_path).run(args.host, args.port)


if __name__ == "__main__":
    main()
