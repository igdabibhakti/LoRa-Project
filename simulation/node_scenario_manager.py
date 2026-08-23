from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any


class NodeScenarioStore:
    """Find, validate, preview, and save Tian node-action scenarios."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.scenario_root = self.root / "simulation" / "scenarios"
        self.saved_root = self.scenario_root / "nodes"

    @staticmethod
    def validate(cfg: dict[str, Any], source: str = "scenario") -> dict[str, Any]:
        if not isinstance(cfg, dict):
            raise ValueError(f"{source} must contain a JSON object")
        actions = cfg.get("actions")
        if not isinstance(actions, list):
            raise ValueError(f"{source} must contain actions[]")
        for index, action in enumerate(actions):
            if not isinstance(action, dict):
                raise ValueError(f"actions[{index}] must be an object")
            if action.get("type") not in {"text", "image"}:
                raise ValueError(f"actions[{index}].type must be text or image")
            try:
                delay = float(action.get("delay", 0))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"actions[{index}].delay must be a number") from exc
            if delay < 0:
                raise ValueError(f"actions[{index}].delay cannot be negative")
            if action["type"] == "text" and "text" not in action:
                raise ValueError(f"actions[{index}] text action must contain text")
            if action["type"] == "image" and not str(action.get("path", "")).strip():
                raise ValueError(f"actions[{index}] image action must contain path")
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
        candidates = sorted(self.scenario_root.rglob("*.json"))
        valid: list[Path] = []
        for path in candidates:
            try:
                with path.open("r", encoding="utf-8") as handle:
                    cfg = json.load(handle)
                self.validate(cfg, str(path))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            valid.append(path.resolve())
        return valid

    def print_list(self) -> list[Path]:
        files = self.list_scenarios()
        print("\n=== AVAILABLE NODE SCENARIOS ===", flush=True)
        if not files:
            print("No node scenarios found yet. Use /scenario make to create one.", flush=True)
            return []
        for index, path in enumerate(files, 1):
            try:
                with path.open("r", encoding="utf-8") as handle:
                    cfg = json.load(handle)
                title = str(cfg.get("name") or path.stem)
                actions = len(cfg.get("actions", []))
                pacing = cfg.get("pacing", "normal")
            except Exception:
                title, actions, pacing = path.stem, "?", "?"
            try:
                shown = path.relative_to(self.root)
            except ValueError:
                shown = path
            print(f"{index:>2}) {title} | actions={actions} | pacing={pacing} | {shown}", flush=True)
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
            raise ValueError("multiple scenarios match that name; use /scenario list and select by number")
        raise ValueError(f"node scenario not found: {token}")

    @staticmethod
    def preview(cfg: dict[str, Any], path: Path | None = None, heading: str = "SCENARIO PREVIEW") -> None:
        name = str(cfg.get("name") or (path.stem if path else "Untitled scenario"))
        pacing = cfg.get("pacing", "normal")
        print(f"\n=== {heading} ===", flush=True)
        print(f"Name   : {name}", flush=True)
        print(f"Pacing : {pacing}", flush=True)
        if path:
            print(f"File   : {path}", flush=True)
        actions = cfg.get("actions", [])
        if not actions:
            print("Actions: (none)", flush=True)
            return
        print("Actions:", flush=True)
        for index, action in enumerate(actions, 1):
            delay = float(action.get("delay", 0))
            if action.get("type") == "image":
                detail = f"IMAGE {action.get('path', '')}"
            else:
                detail = f"TEXT {action.get('text', '')!r}"
            print(f"  {index:>2}) wait {delay:g}s -> {detail}", flush=True)

    @staticmethod
    def _safe_filename(raw: str) -> str:
        stem = Path(raw.strip()).stem
        stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-")
        return stem or "node_scenario"

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


def _ask_delay(prompt: str, default: float = 0.0) -> float:
    while True:
        raw = _ask(prompt, f"{default:g}")
        try:
            value = float(raw)
            if value < 0:
                raise ValueError
            return value
        except ValueError:
            print("Enter a delay in seconds >= 0, for example 0, 1, 2.5, or 5.", flush=True)


def _normalize_pacing(raw: str) -> str | float:
    value = raw.strip().lower().replace("_", "-")
    if value in {"normal", "slow", "very-slow"}:
        return value
    try:
        seconds = float(value)
    except ValueError as exc:
        raise ValueError("pacing must be normal, slow, very-slow, or custom seconds such as 1.5") from exc
    if seconds < 0:
        raise ValueError("custom pacing cannot be negative")
    return seconds


def run_terminal_builder(
    node_name: str,
    store: NodeScenarioStore,
    current_path: Path | None,
    current_cfg: dict[str, Any] | None,
    current_pacing: str | float,
) -> Path | None:
    """Interactive terminal-only scenario editor. Returns the new saved file, if any."""

    print(f"\n========================================\n TIAN {node_name} - NODE SCENARIO BUILDER\n========================================", flush=True)
    print("No JSON editing is required here.", flush=True)
    print("Saving ALWAYS creates a new JSON file; an existing scenario is never overwritten.", flush=True)

    if current_cfg is not None:
        store.preview(current_cfg, current_path, "CURRENTLY LOADED SCENARIO")
        print("\nStart this draft from:", flush=True)
        print("1) Copy the currently loaded scenario (recommended for modifying it)", flush=True)
        print("2) Start a blank scenario", flush=True)
        print("3) Cancel", flush=True)
        choice = _ask("Choose", "1")
        if choice == "3":
            return None
        if choice == "2":
            draft = {"name": f"Tian {node_name} scenario", "pacing": current_pacing, "actions": []}
        else:
            draft = copy.deepcopy(current_cfg)
            draft["pacing"] = draft.get("pacing", current_pacing)
    else:
        draft = {"name": f"Tian {node_name} scenario", "pacing": current_pacing, "actions": []}

    while True:
        print("\n--- BUILDER MENU ---", flush=True)
        print("1) Preview draft", flush=True)
        print("2) Add TEXT action", flush=True)
        print("3) Add IMAGE action", flush=True)
        print("4) Edit an action (including its delay)", flush=True)
        print("5) Delete an action", flush=True)
        print("6) Set scenario pacing (normal / slow / very-slow / custom)", flush=True)
        print("7) Rename scenario title", flush=True)
        print("8) SAVE AS NEW JSON + PRELOAD IT", flush=True)
        print("9) Cancel without saving", flush=True)
        choice = _ask("Choose", "1")

        if choice == "1":
            store.preview(draft, heading="DRAFT PREVIEW")
            continue

        if choice == "2":
            delay = _ask_delay("Wait before this text action (seconds)", 0.0)
            text = _ask("Text to send")
            draft["actions"].append({"delay": delay, "type": "text", "text": text})
            print(f"Added TEXT action #{len(draft['actions'])}.", flush=True)
            continue

        if choice == "3":
            delay = _ask_delay("Wait before this image action (seconds)", 0.0)
            while True:
                raw_path = _ask("Image path")
                image_path = Path(raw_path).expanduser()
                if not image_path.is_absolute():
                    image_path = (Path.cwd() / image_path).resolve()
                else:
                    image_path = image_path.resolve()
                if image_path.is_file():
                    break
                print(f"File not found: {image_path}", flush=True)
            draft["actions"].append({"delay": delay, "type": "image", "path": str(image_path)})
            print(f"Added IMAGE action #{len(draft['actions'])}.", flush=True)
            continue

        if choice == "4":
            actions = draft["actions"]
            if not actions:
                print("There are no actions to edit yet.", flush=True)
                continue
            store.preview(draft, heading="CHOOSE ACTION TO EDIT")
            raw_index = _ask("Action number")
            if not raw_index.isdigit() or not 1 <= int(raw_index) <= len(actions):
                print("Invalid action number.", flush=True)
                continue
            action = actions[int(raw_index) - 1]
            old_delay = float(action.get("delay", 0))
            action["delay"] = _ask_delay("Wait before this action (seconds)", old_delay)
            if action["type"] == "text":
                action["text"] = _ask("Text", str(action.get("text", "")))
            else:
                raw_path = _ask("Image path", str(action.get("path", "")))
                image_path = Path(raw_path).expanduser()
                if not image_path.is_absolute():
                    image_path = (Path.cwd() / image_path).resolve()
                else:
                    image_path = image_path.resolve()
                if not image_path.is_file():
                    print(f"Warning: image does not currently exist: {image_path}", flush=True)
                action["path"] = str(image_path)
            print(f"Updated action #{raw_index}.", flush=True)
            continue

        if choice == "5":
            actions = draft["actions"]
            if not actions:
                print("There are no actions to delete.", flush=True)
                continue
            store.preview(draft, heading="CHOOSE ACTION TO DELETE")
            raw_index = _ask("Action number")
            if not raw_index.isdigit() or not 1 <= int(raw_index) <= len(actions):
                print("Invalid action number.", flush=True)
                continue
            removed = actions.pop(int(raw_index) - 1)
            print(f"Deleted action #{raw_index}: {removed.get('type')}", flush=True)
            continue

        if choice == "6":
            print("\nPacing is EXTRA time added between scripted actions:", flush=True)
            print("  normal    = +0s (scenario runs exactly at each action delay)", flush=True)
            print("  slow      = +2s (easy to follow by eye)", flush=True)
            print("  very-slow = +5s (demo/debug speed)", flush=True)
            print("  1.5       = custom +1.5s", flush=True)
            raw = _ask("Pacing", str(draft.get("pacing", "normal")))
            try:
                draft["pacing"] = _normalize_pacing(raw)
                print(f"Scenario pacing set to {draft['pacing']}.", flush=True)
            except ValueError as exc:
                print(f"Invalid pacing: {exc}", flush=True)
            continue

        if choice == "7":
            draft["name"] = _ask("Scenario title", str(draft.get("name", f"Tian {node_name} scenario")))
            continue

        if choice == "8":
            store.preview(draft, heading="FINAL PREVIEW BEFORE SAVE")
            default_file = store._safe_filename(str(draft.get("name", f"tian_{node_name.lower()}_scenario")))
            requested = _ask("New filename (existing files will NOT be overwritten)", default_file)
            path = store.save_new(draft, requested)
            print(f"\n[SAVED] New node scenario: {path}", flush=True)
            print("[PRELOAD] This new scenario will now become the selected scenario for this Tian node.", flush=True)
            return path

        if choice == "9":
            print("Builder cancelled; nothing was saved.", flush=True)
            return None

        print("Choose a number from 1 to 9.", flush=True)
