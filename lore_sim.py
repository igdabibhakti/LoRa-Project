#!/usr/bin/env python3
"""Terminal-first launcher and scenario editor for LoRe/Tian simulation."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCENARIO_DIR = ROOT / "simulation" / "scenarios"
DEFAULT_SCENARIO = SCENARIO_DIR / "example.json"


def ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value if value else (default or "")


def ask_int(prompt: str, default: int, minimum: int = 0) -> int:
    while True:
        raw = ask(prompt, str(default))
        try:
            value = int(raw)
            if value < minimum:
                raise ValueError
            return value
        except ValueError:
            print(f"Enter an integer >= {minimum}.")


def ask_float(prompt: str, default: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    while True:
        raw = ask(prompt, str(default))
        try:
            value = float(raw)
            if not minimum <= value <= maximum:
                raise ValueError
            return value
        except ValueError:
            print(f"Enter a value from {minimum} to {maximum}.")


def ask_bool(prompt: str, default: bool = False) -> bool:
    d = "y" if default else "n"
    while True:
        raw = ask(f"{prompt} (y/n)", d).lower()
        if raw in {"y", "yes"}: return True
        if raw in {"n", "no"}: return False
        print("Enter y or n.")


def parse_indexes(raw: str) -> list[int]:
    if not raw.strip(): return []
    result = []
    for part in raw.split(","):
        part = part.strip()
        if not part: continue
        value = int(part)
        if value < 0: raise ValueError("packet indexes cannot be negative")
        result.append(value)
    return sorted(set(result))


def build_sequence(number: int) -> dict:
    print(f"\n--- Configure Sequence {number} ---")
    name = ask("Sequence name", f"sequence-{number}")
    print("DATA loss mode:\n  1) none\n  2) manual packet indexes\n  3) random exact count\n  4) random probability")
    mode_choice = ask("Choose", "1")
    if mode_choice == "2":
        while True:
            try:
                indexes = parse_indexes(ask("Indexes to drop, comma-separated (e.g. 1,2,5)", "")); break
            except ValueError as exc: print(f"Invalid indexes: {exc}")
        data_loss = {"mode": "manual", "indexes": indexes}
    elif mode_choice == "3":
        data_loss = {"mode": "random_count", "count": ask_int("How many DATA packets to randomly drop", 1)}
    elif mode_choice == "4":
        data_loss = {"mode": "random_probability", "probability": ask_float("Loss probability (0.0-1.0)", 0.20)}
    else:
        data_loss = {"mode": "none"}
    seq = {"name": name, "data_loss": data_loss}
    if ask_bool("Drop END in this sequence", False): seq["drop_end"] = True
    if ask_bool("Drop NACK in this sequence", False): seq["drop_nack"] = True
    if ask_bool("Drop COMPLETE in this sequence", False): seq["drop_complete"] = True
    return seq


def create_scenario() -> Path:
    print("\n=== CREATE SIMULATION SCENARIO ===")
    seed_raw = ask("Random seed (blank = new randomness every run)", "")
    seed = int(seed_raw) if seed_raw else None
    cfg = {"seed": seed, "contention_window_ms": ask_int("Contention window ms", 80, 1), "max_backoff_ms": ask_int("Maximum randomized backoff ms", 120, 5), "messages": [], "sequences": []}
    print("\nAdd messages. Add at least one for A or B.")
    nmsg = ask_int("Number of queued messages", 2, 1)
    for i in range(1, nmsg + 1):
        sender = ask(f"Message {i} sender (A/B)", "A" if i % 2 else "B").upper()
        while sender not in {"A", "B"}: sender = ask("Sender must be A or B").upper()
        label = ask("Label", f"message-{i}")
        text = ask("Text payload", sender * 600)
        cfg["messages"].append({"sender": sender, "label": label, "text": text})
    print("\nAdd as many transmission/retransmission sequences as you want.")
    i = 1
    while True:
        cfg["sequences"].append(build_sequence(i)); i += 1
        if not ask_bool("Add another sequence", True): break
    SCENARIO_DIR.mkdir(parents=True, exist_ok=True)
    name = ask("Scenario filename", "terminal_scenario.json")
    if not name.endswith(".json"): name += ".json"
    path = SCENARIO_DIR / Path(name).name
    path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    print(f"\nSaved: {path}")
    return path


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f: cfg = json.load(f)
    if not isinstance(cfg.get("messages"), list) or not isinstance(cfg.get("sequences"), list):
        raise ValueError("scenario must contain messages[] and sequences[]")
    return cfg


def print_scenario(path: Path) -> None:
    cfg = load_json(path)
    print(f"\n=== {path.name} ===")
    print(json.dumps(cfg, indent=2))


def launch(path: Path) -> None:
    load_json(path)
    subprocess.run([sys.executable, str(ROOT / "simulation" / "launch_three_terminals.py"), "--scenario", str(path)], check=True)


def select_existing() -> Path:
    SCENARIO_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(SCENARIO_DIR.glob("*.json"))
    if files:
        print("\nAvailable scenarios:")
        for i, p in enumerate(files, 1): print(f"  {i}) {p.name}")
        raw = ask("Choose number or enter a JSON path", "1")
        if raw.isdigit() and 1 <= int(raw) <= len(files): return files[int(raw)-1]
        return Path(raw).expanduser().resolve()
    return Path(ask("JSON scenario path")).expanduser().resolve()


def main() -> None:
    while True:
        print("\n========================================\n LoRe / Tian Software Terminal Simulator\n========================================")
        print("1) Create scenario interactively + run\n2) Load existing JSON scenario + run\n3) Create scenario interactively only\n4) Review / validate a JSON scenario\n5) Run included example scenario\n6) Exit")
        choice = ask("Choose", "1")
        try:
            if choice == "1":
                path = create_scenario(); print_scenario(path); launch(path); return
            if choice == "2":
                path = select_existing(); print_scenario(path); launch(path); return
            if choice == "3":
                path = create_scenario(); print_scenario(path); return
            if choice == "4": print_scenario(select_existing()); continue
            if choice == "5": print_scenario(DEFAULT_SCENARIO); launch(DEFAULT_SCENARIO); return
            if choice == "6": return
            print("Unknown option.")
        except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
            print(f"ERROR: {exc}")


if __name__ == "__main__": main()
