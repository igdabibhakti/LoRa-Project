#!/usr/bin/env python3
"""Easy terminal launcher for LoRe/Tian Software simulation.

Quick mode is intentionally short. Example loss sequence line:

    1,2,5 | 2,5 | random:2 | 20% | none+nack

Each pipe-separated item is one TX/retransmission sequence.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCENARIO_DIR = ROOT / "simulation" / "scenarios"
DEFAULT_SCENARIO = SCENARIO_DIR / "example.json"
QUICK_SCENARIO = SCENARIO_DIR / "quick_last.json"


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value if value else default


def ask_int(prompt: str, default: int, minimum: int = 1) -> int:
    while True:
        raw = ask(prompt, str(default))
        try:
            value = int(raw)
            if value < minimum:
                raise ValueError
            return value
        except ValueError:
            print(f"Please enter a whole number >= {minimum}.")


def repeat_to_size(text: str, size: int) -> str:
    if not text:
        text = "TEST"
    encoded = text.encode("utf-8")
    if len(encoded) >= size:
        return encoded[:size].decode("utf-8", errors="ignore")
    parts: list[str] = []
    total = 0
    while total < size:
        parts.append(text)
        parts.append(" ")
        total += len(encoded) + 1
    return "".join(parts).encode("utf-8")[:size].decode("utf-8", errors="ignore")


def parse_manual_indexes(token: str) -> list[int]:
    if not token.strip():
        return []
    indexes: list[int] = []
    for part in token.split(","):
        part = part.strip()
        if not part:
            continue
        value = int(part)
        if value < 0:
            raise ValueError("packet indexes cannot be negative")
        indexes.append(value)
    return sorted(set(indexes))


def parse_sequence_token(token: str, number: int) -> dict:
    pieces = [p.strip().lower() for p in token.split("+") if p.strip()]
    data_part = pieces[0] if pieces else "none"
    flags = set(pieces[1:])

    if data_part in {"", "none", "clean", "0"}:
        data_loss = {"mode": "none"}
    elif data_part.startswith("random:"):
        count = int(data_part.split(":", 1)[1])
        if count < 0:
            raise ValueError("random count cannot be negative")
        data_loss = {"mode": "random_count", "count": count}
    elif data_part.endswith("%"):
        percent = float(data_part[:-1])
        if not 0 <= percent <= 100:
            raise ValueError("percentage must be between 0% and 100%")
        data_loss = {"mode": "random_probability", "probability": percent / 100.0}
    else:
        data_loss = {"mode": "manual", "indexes": parse_manual_indexes(data_part)}

    unknown = flags - {"end", "nack", "complete"}
    if unknown:
        raise ValueError(f"unknown fault flag(s): {', '.join(sorted(unknown))}")

    seq = {"name": f"sequence-{number}", "data_loss": data_loss}
    if "end" in flags:
        seq["drop_end"] = True
    if "nack" in flags:
        seq["drop_nack"] = True
    if "complete" in flags:
        seq["drop_complete"] = True
    return seq


def parse_sequence_line(raw: str) -> list[dict]:
    tokens = [part.strip() for part in raw.split("|")]
    tokens = [token for token in tokens if token]
    if not tokens:
        return [{"name": "sequence-1", "data_loss": {"mode": "none"}}]
    return [parse_sequence_token(token, i) for i, token in enumerate(tokens, 1)]


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        cfg = json.load(handle)
    if not isinstance(cfg.get("messages"), list) or not isinstance(cfg.get("sequences"), list):
        raise ValueError("scenario must contain messages[] and sequences[]")
    return cfg


def launch(path: Path) -> None:
    load_json(path)
    subprocess.run(
        [sys.executable, str(ROOT / "simulation" / "launch_three_terminals.py"), "--scenario", str(path)],
        check=True,
    )


def quick_test() -> Path:
    print("\n=== QUICK TEST ===")
    print("1) A -> B")
    print("2) B -> A")
    print("3) A and B both send (contention test)")
    direction = ask("Choose", "1")
    if direction not in {"1", "2", "3"}:
        direction = "1"

    payload_size = ask_int("Approx payload bytes (180 B = about 1 DATA packet)", 1200, 1)
    messages = []

    if direction in {"1", "3"}:
        text_a = ask("A message", "Hello from A")
        messages.append({"sender": "A", "label": "A-message", "text": repeat_to_size(text_a, payload_size)})
    if direction in {"2", "3"}:
        text_b = ask("B message", "Hello from B")
        messages.append({"sender": "B", "label": "B-message", "text": repeat_to_size(text_b, payload_size)})

    print("\nLoss sequence syntax:")
    print("  manual packets : 1,2,5")
    print("  random count   : random:2")
    print("  probability    : 20%")
    print("  no DATA loss   : none")
    print("  control loss   : add +end, +nack, or +complete")
    print("  next sequence  : separate with |")
    print("Example: 1,2,5 | 2,5 | random:1 | 20% | none+nack")

    while True:
        raw_loss = ask("Loss sequences", "1,2,5 | 2,5 | none")
        try:
            sequences = parse_sequence_line(raw_loss)
            break
        except ValueError as exc:
            print(f"Invalid sequence: {exc}")

    seed_raw = ask("Random seed (Enter = random every run)", "")
    seed = int(seed_raw) if seed_raw else None

    cfg = {
        "seed": seed,
        "contention_window_ms": 80,
        "max_backoff_ms": 120,
        "messages": messages,
        "sequences": sequences,
    }
    SCENARIO_DIR.mkdir(parents=True, exist_ok=True)
    QUICK_SCENARIO.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")

    print("\nReady.")
    print(f"Messages      : {', '.join(m['sender'] for m in messages)}")
    print(f"Payload       : ~{payload_size} bytes each")
    print(f"Sequences     : {len(sequences)}")
    print(f"Saved JSON    : {QUICK_SCENARIO}")
    print("Launching Panel + Tian Software A + Tian Software B...\n")
    return QUICK_SCENARIO


def choose_json() -> Path:
    SCENARIO_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(SCENARIO_DIR.glob("*.json"))
    if files:
        print("\nSaved JSON scenarios:")
        for i, path in enumerate(files, 1):
            print(f"  {i}) {path.name}")
        raw = ask("Choose number or type path", "1")
        if raw.isdigit() and 1 <= int(raw) <= len(files):
            return files[int(raw) - 1]
        return Path(raw).expanduser().resolve()
    return Path(ask("JSON scenario path")).expanduser().resolve()


def show_json(path: Path) -> None:
    cfg = load_json(path)
    print(f"\n--- {path} ---")
    print(json.dumps(cfg, indent=2))


def main() -> None:
    while True:
        print("\n====================================")
        print(" LoRe / Tian Software Simulator")
        print("====================================")
        print("1) QUICK TEST (recommended)")
        print("2) Run saved JSON scenario")
        print("3) View / validate JSON scenario")
        print("4) Run included example")
        print("5) Exit")
        choice = ask("Choose", "1")
        try:
            if choice == "1":
                launch(quick_test())
                return
            if choice == "2":
                path = choose_json()
                show_json(path)
                launch(path)
                return
            if choice == "3":
                show_json(choose_json())
                continue
            if choice == "4":
                show_json(DEFAULT_SCENARIO)
                launch(DEFAULT_SCENARIO)
                return
            if choice == "5":
                return
            print("Unknown option.")
        except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
            print(f"ERROR: {exc}")


if __name__ == "__main__":
    main()
