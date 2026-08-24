from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import simulation.channel_scenario_manager as legacy


class ChannelScenarioStore(legacy.ChannelScenarioStore):
    """Channel scenario store with per-transmission probability persistence."""

    @staticmethod
    def validate(cfg: dict[str, Any], source: str = "scenario") -> dict[str, Any]:
        cfg = legacy.ChannelScenarioStore.validate(cfg, source)
        for index, seq in enumerate(cfg.get("sequences", [])):
            loss = seq.get("data_loss", {"mode": "none"})
            if loss.get("mode") == "random_probability" and "continuous" in loss:
                if not isinstance(loss["continuous"], bool):
                    raise ValueError(
                        f"sequences[{index}].data_loss.continuous must be true or false"
                    )
        return cfg

    @staticmethod
    def describe_loss(seq: dict[str, Any]) -> str:
        text = legacy.ChannelScenarioStore.describe_loss(seq)
        loss = seq.get("data_loss", {"mode": "none"})
        if loss.get("mode") == "random_probability":
            text += " continuous" if loss.get("continuous", False) else " one-transmission"
        return text


def _build_loss(existing: dict[str, Any] | None = None) -> dict[str, Any]:
    existing = copy.deepcopy(existing or {"mode": "none"})
    print("\nDATA loss mode:", flush=True)
    print("1) None", flush=True)
    print("2) Manual packet indexes (this transmission only)", flush=True)
    print("3) Random exact count (this transmission only)", flush=True)
    print("4) Random probability", flush=True)
    mode_map = {
        "none": "1",
        "manual": "2",
        "random_count": "3",
        "random_probability": "4",
    }
    choice = legacy._ask("Choose", mode_map.get(existing.get("mode", "none"), "1"))

    if choice == "2":
        return {
            "mode": "manual",
            "indexes": legacy._ask_manual_indexes(existing.get("indexes", [])),
        }
    if choice == "3":
        return {
            "mode": "random_count",
            "count": legacy._ask_nonnegative_int(
                "How many DATA packets to lose exactly",
                int(existing.get("count", 1)),
            ),
        }
    if choice == "4":
        probability = legacy._ask_probability(float(existing.get("probability", 0.2)))
        continuous = legacy._yes_no(
            "Keep applying this probability to later DATA transmissions",
            bool(existing.get("continuous", False)),
        )
        return {
            "mode": "random_probability",
            "probability": probability,
            "continuous": continuous,
        }
    return {"mode": "none"}


def run_channel_builder(
    store: ChannelScenarioStore,
    current_path: Path | None,
    current_cfg: dict[str, Any] | None,
) -> Path | None:
    """Run the existing terminal builder with the v2 DATA-loss prompt installed."""
    original = legacy._build_loss
    legacy._build_loss = _build_loss
    try:
        return legacy.run_channel_builder(store, current_path, current_cfg)
    finally:
        legacy._build_loss = original
