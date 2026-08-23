from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any


class ChannelScenarioStore:
    """Find, validate, preview, and save panel/channel loss scenarios."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.scenario_root = self.root / "simulation" / "scenarios"
        self.saved_root = self.scenario_root / "channels"

    @staticmethod
    def validate(cfg: dict[str, Any], source: str = "scenario") -> dict[str, Any]:
        if not isinstance(cfg, dict):
            raise ValueError(f"{source} must contain a JSON object")
        sequences = cfg.get("sequences")
        if not isinstance(sequences, list):
            raise ValueError(f"{source} must contain sequences[]")
        for index, seq in enumerate(sequences):
            if not isinstance(seq, dict):
                raise ValueError(f"sequences[{index}] must be an object")
            loss = seq.get("data_loss", {"mode": "none"})
            if not isinstance(loss, dict):
                raise ValueError(f"sequences[{index}].data_loss must be an object")
            mode = loss.get("mode", "none")
            if mode not in {"none", "manual", "random_count", "random_probability"}:
                raise ValueError(f"sequences[{index}] has unsupported loss mode {mode!r}")
            if mode == "manual":
                indexes = loss.get("indexes", [])
                if not isinstance(indexes, list) or any(
                    not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in indexes
                ):
                    raise ValueError(f"sequences[{index}] manual indexes must be non-negative integers")
            elif mode == "random_count":
                count = loss.get("count", 0)
                if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                    raise ValueError(f"sequences[{index}] random count must be a non-negative integer")
            elif mode == "random_probability":
                try:
                    p = float(loss.get("probability", 0))
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"sequences[{index}] probability must be numeric") from exc
                if not 0 <= p <= 1:
                    raise ValueError(f"sequences[{index}] probability must be between 0 and 1")
        return cfg

    def load(self, raw_path: str | Path) -> tuple[Path, dict[str, Any]]:
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        else:
            path = path.resolve()
        with path.open("r", encoding="utf-8") as handle:
            cfg = json.load(handle)
        return path, self.validate(cfg, str(path))

    def list_scenarios(self) -> list[Path]:
        self.scenario_root.mkdir(parents=True, exist_ok=True)
        valid: list[Path] = []
        for path in sorted(self.scenario_root.rglob("*.json")):
            try:
                with path.open("r", encoding="utf-8") as handle:
                    cfg = json.load(handle)
                self.validate(cfg, str(path))
                # Node scenarios have actions[]; channel scenarios have sequences[].
                if "actions" in cfg:
                    continue
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            valid.append(path.resolve())
        return valid

    def print_list(self) -> list[Path]:
        files = self.list_scenarios()
        print("\n=== AVAILABLE CHANNEL SCENARIOS ===", flush=True)
        if not files:
            print("No channel scenarios found yet. Use /scenario make to create one.", flush=True)
            return []
        for index, path in enumerate(files, 1):
            try:
                with path.open("r", encoding="utf-8") as handle:
                    cfg = json.load(handle)
                title = str(cfg.get("name") or path.stem)
                seq_count = len(cfg.get("sequences", []))
                seed = cfg.get("seed")
            except Exception:
                title, seq_count, seed = path.stem, "?", "?"
            try:
                shown = path.relative_to(self.root)
            except ValueError:
                shown = path
            print(
                f"{index:>2}) {title} | sequences={seq_count} | seed={seed} | {shown}",
                flush=True,
            )
        print("Select with: /scenario select <number>  (or filename/path)", flush=True)
        return files

    def resolve(self, token: str) -> Path:
        token = token.strip()
        if not token:
            raise ValueError("select needs a scenario number, filename, or path")
        files = self.list_scenarios()
        if token.isdigit():
            number = int(token)
            if 1 <= number <= len(files):
                return files[number - 1]
            raise ValueError(f"scenario number must be 1..{len(files)}")
        candidate = Path(token).expanduser()
        if candidate.exists():
            return candidate.resolve()
        project_candidate = (self.root / candidate).resolve()
        if project_candidate.exists():
            return project_candidate
        lowered = token.lower()
        matches: list[Path] = []
        for path in files:
            if path.name.lower() == lowered or path.stem.lower() == lowered:
                matches.append(path)
                continue
            try:
                with path.open("r", encoding="utf-8") as handle:
                    title = str(json.load(handle).get("name", "")).lower()
                if title == lowered:
                    matches.append(path)
            except Exception:
                pass
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError("multiple channel scenarios match; select by number")
        raise ValueError(f"channel scenario not found: {token}")

    @staticmethod
    def describe_loss(seq: dict[str, Any]) -> str:
        loss = seq.get("data_loss", {"mode": "none"})
        mode = loss.get("mode", "none")
        if mode == "manual":
            return f"manual indexes={loss.get('indexes', [])}"
        if mode == "random_count":
            return f"random exact count={loss.get('count', 0)}"
        if mode == "random_probability":
            return f"random probability={float(loss.get('probability', 0)) * 100:g}%"
        return "none"

    @classmethod
    def preview(
        cls,
        cfg: dict[str, Any],
        path: Path | None = None,
        heading: str = "CHANNEL SCENARIO PREVIEW",
    ) -> None:
        name = str(cfg.get("name") or (path.stem if path else "Untitled channel scenario"))
        print(f"\n=== {heading} ===", flush=True)
        print(f"Name              : {name}", flush=True)
        print(f"Seed              : {cfg.get('seed')}", flush=True)
        print(f"Contention window : {cfg.get('contention_window_ms', 80)} ms", flush=True)
        print(f"Max backoff       : {cfg.get('max_backoff_ms', 120)} ms", flush=True)
        if path:
            print(f"File              : {path}", flush=True)
        sequences = cfg.get("sequences", [])
        if not sequences:
            print("Sequences: (none)", flush=True)
            return
        print("Sequences:", flush=True)
        for index, seq in enumerate(sequences, 1):
            controls = []
            if seq.get("drop_end"):
                controls.append("END")
            if seq.get("drop_nack"):
                controls.append("NACK")
            if seq.get("drop_complete"):
                controls.append("COMPLETE")
            control_text = ",".join(controls) if controls else "none"
            print(
                f"  {index:>2}) {seq.get('name', f'sequence-{index}')} | "
                f"DATA loss: {cls.describe_loss(seq)} | control drops: {control_text}",
                flush=True,
            )

    @staticmethod
    def _safe_filename(raw: str) -> str:
        stem = Path(raw.strip()).stem
        stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-")
        return stem or "channel_scenario"

    def save_new(self, cfg: dict[str, Any], requested_name: str) -> Path:
        self.validate(cfg, "draft")
        self.saved_root.mkdir(parents=True, exist_ok=True)
        stem = self._safe_filename(requested_name)
        path = self.saved_root / f"{stem}.json"
        suffix = 2
        while path.exists():
            path = self.saved_root / f"{stem}_{suffix}.json"
            suffix += 1
        path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
        return path.resolve()


def _ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default not in {None, ""} else ""
    value = input(f"{prompt}{suffix}: ").strip()
    if not value and default is not None:
        return default
    return value


def _yes_no(prompt: str, default: bool = False) -> bool:
    marker = "Y/n" if default else "y/N"
    raw = _ask(f"{prompt} ({marker})", "y" if default else "n").lower()
    return raw in {"y", "yes", "1", "true"}


def _ask_nonnegative_int(prompt: str, default: int = 0) -> int:
    while True:
        raw = _ask(prompt, str(default))
        try:
            value = int(raw)
            if value < 0:
                raise ValueError
            return value
        except ValueError:
            print("Enter a non-negative whole number.", flush=True)


def _ask_probability(default: float = 0.2) -> float:
    while True:
        raw = _ask("Loss probability (0..1, or percentage like 20%)", f"{default:g}")
        try:
            if raw.endswith("%"):
                value = float(raw[:-1]) / 100.0
            else:
                value = float(raw)
            if not 0 <= value <= 1:
                raise ValueError
            return value
        except ValueError:
            print("Enter 0..1 or a percentage such as 20%.", flush=True)


def _ask_manual_indexes(default: list[int] | None = None) -> list[int]:
    default = default or []
    while True:
        raw = _ask("Packet indexes separated by commas", ",".join(map(str, default)))
        if not raw.strip():
            return []
        try:
            values = sorted({int(part.strip()) for part in raw.split(",") if part.strip()})
            if any(value < 0 for value in values):
                raise ValueError
            return values
        except ValueError:
            print("Example: 1,2,5,9 (indexes are zero-based).", flush=True)


def _build_loss(existing: dict[str, Any] | None = None) -> dict[str, Any]:
    existing = existing or {"mode": "none"}
    print("\nDATA loss mode:", flush=True)
    print("1) None", flush=True)
    print("2) Manual packet indexes", flush=True)
    print("3) Random exact count", flush=True)
    print("4) Random probability", flush=True)
    mode_map = {"none": "1", "manual": "2", "random_count": "3", "random_probability": "4"}
    choice = _ask("Choose", mode_map.get(existing.get("mode", "none"), "1"))
    if choice == "2":
        return {"mode": "manual", "indexes": _ask_manual_indexes(existing.get("indexes", []))}
    if choice == "3":
        return {
            "mode": "random_count",
            "count": _ask_nonnegative_int("How many DATA packets to lose exactly", int(existing.get("count", 1))),
        }
    if choice == "4":
        return {
            "mode": "random_probability",
            "probability": _ask_probability(float(existing.get("probability", 0.2))),
        }
    return {"mode": "none"}


def _build_sequence(number: int, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    existing = copy.deepcopy(existing or {})
    name = _ask("Sequence name", str(existing.get("name", f"sequence-{number}")))
    loss = _build_loss(existing.get("data_loss"))
    drop_end = _yes_no("Drop END", bool(existing.get("drop_end", False)))
    drop_nack = _yes_no("Drop NACK", bool(existing.get("drop_nack", False)))
    drop_complete = _yes_no("Drop COMPLETE", bool(existing.get("drop_complete", False)))
    return {
        "name": name,
        "data_loss": loss,
        "drop_end": drop_end,
        "drop_nack": drop_nack,
        "drop_complete": drop_complete,
    }


def run_channel_builder(
    store: ChannelScenarioStore,
    current_path: Path | None,
    current_cfg: dict[str, Any] | None,
) -> Path | None:
    print("\n========================================", flush=True)
    print(" PANEL - CHANNEL SCENARIO BUILDER", flush=True)
    print("========================================", flush=True)
    print("No JSON editing is required here.", flush=True)
    print("Saving ALWAYS creates a new JSON file; existing scenarios are never overwritten.", flush=True)

    if current_cfg is not None:
        store.preview(current_cfg, current_path, "CURRENTLY LOADED CHANNEL SCENARIO")
        print("\nStart this draft from:", flush=True)
        print("1) Copy the currently loaded channel scenario", flush=True)
        print("2) Start a blank channel scenario", flush=True)
        print("3) Cancel", flush=True)
        choice = _ask("Choose", "1")
        if choice == "3":
            return None
        if choice == "2":
            draft = {
                "name": "Channel scenario",
                "seed": None,
                "contention_window_ms": 80,
                "max_backoff_ms": 120,
                "messages": [],
                "sequences": [],
            }
        else:
            draft = copy.deepcopy(current_cfg)
            draft["messages"] = []
    else:
        draft = {
            "name": "Channel scenario",
            "seed": None,
            "contention_window_ms": 80,
            "max_backoff_ms": 120,
            "messages": [],
            "sequences": [],
        }

    while True:
        print("\n--- CHANNEL BUILDER MENU ---", flush=True)
        print("1) Preview draft", flush=True)
        print("2) Add transmission sequence", flush=True)
        print("3) Edit a transmission sequence", flush=True)
        print("4) Delete a transmission sequence", flush=True)
        print("5) Set random seed", flush=True)
        print("6) Set contention / backoff settings", flush=True)
        print("7) Rename scenario title", flush=True)
        print("8) SAVE AS NEW JSON + PRELOAD IT", flush=True)
        print("9) Cancel without saving", flush=True)
        choice = _ask("Choose", "1")

        if choice == "1":
            store.preview(draft, heading="CHANNEL DRAFT PREVIEW")
            continue
        if choice == "2":
            seq = _build_sequence(len(draft["sequences"]) + 1)
            draft["sequences"].append(seq)
            print(f"Added sequence #{len(draft['sequences'])}.", flush=True)
            continue
        if choice == "3":
            if not draft["sequences"]:
                print("There are no sequences to edit yet.", flush=True)
                continue
            store.preview(draft, heading="CHOOSE SEQUENCE TO EDIT")
            raw = _ask("Sequence number")
            if not raw.isdigit() or not 1 <= int(raw) <= len(draft["sequences"]):
                print("Invalid sequence number.", flush=True)
                continue
            idx = int(raw) - 1
            draft["sequences"][idx] = _build_sequence(idx + 1, draft["sequences"][idx])
            print(f"Updated sequence #{idx + 1}.", flush=True)
            continue
        if choice == "4":
            if not draft["sequences"]:
                print("There are no sequences to delete.", flush=True)
                continue
            store.preview(draft, heading="CHOOSE SEQUENCE TO DELETE")
            raw = _ask("Sequence number")
            if not raw.isdigit() or not 1 <= int(raw) <= len(draft["sequences"]):
                print("Invalid sequence number.", flush=True)
                continue
            removed = draft["sequences"].pop(int(raw) - 1)
            print(f"Deleted sequence: {removed.get('name')}", flush=True)
            continue
        if choice == "5":
            raw = _ask("Random seed (blank = random each run)", "" if draft.get("seed") is None else str(draft.get("seed")))
            if not raw.strip():
                draft["seed"] = None
            else:
                try:
                    draft["seed"] = int(raw)
                except ValueError:
                    print("Seed must be a whole number or blank.", flush=True)
                    continue
            print(f"Seed set to {draft['seed']}.", flush=True)
            continue
        if choice == "6":
            draft["contention_window_ms"] = _ask_nonnegative_int(
                "Contention window (ms)", int(draft.get("contention_window_ms", 80))
            )
            draft["max_backoff_ms"] = _ask_nonnegative_int(
                "Maximum randomized backoff (ms)", int(draft.get("max_backoff_ms", 120))
            )
            continue
        if choice == "7":
            draft["name"] = _ask("Scenario title", str(draft.get("name", "Channel scenario")))
            continue
        if choice == "8":
            if not draft["sequences"]:
                print("Add at least one transmission sequence before saving.", flush=True)
                continue
            store.preview(draft, heading="FINAL CHANNEL PREVIEW BEFORE SAVE")
            default_file = store._safe_filename(str(draft.get("name", "channel_scenario")))
            requested = _ask("New filename (existing files will NOT be overwritten)", default_file)
            path = store.save_new(draft, requested)
            print(f"\n[SAVED] New channel scenario: {path}", flush=True)
            print("[PRELOAD] The panel will now select this new channel scenario.", flush=True)
            return path
        if choice == "9":
            print("Builder cancelled; nothing was saved.", flush=True)
            return None
        print("Choose a number from 1 to 9.", flush=True)
