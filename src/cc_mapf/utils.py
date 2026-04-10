from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


def ensure_dir(path: str | Path) -> Path:
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def load_yaml(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping in YAML file: {path}")
    return data


def dump_yaml(data: Any, path: str | Path) -> None:
    serial = to_serializable(data)
    with Path(path).open("w", encoding="utf-8") as handle:
        yaml.safe_dump(serial, handle, sort_keys=False)


def dump_json(data: Any, path: str | Path) -> None:
    serial = to_serializable(data)
    with Path(path).open("w", encoding="utf-8") as handle:
        json.dump(serial, handle, indent=2, sort_keys=True)


def load_json(path: str | Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def timestamp_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def scale_label(width: int, height: int, agents: int) -> str:
    return f"{width}x{height}_{agents}a"


def mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return float(ordered[mid])
    return float(ordered[mid - 1] + ordered[mid]) / 2.0


def plan_to_serializable(plan: dict[str, list[tuple[int, int]]]) -> dict[str, list[list[int]]]:
    return {agent_id: [[x, y] for x, y in path] for agent_id, path in plan.items()}


def serializable_to_plan(data: dict[str, list[list[int]]]) -> dict[str, list[tuple[int, int]]]:
    return {agent_id: [tuple(cell) for cell in path] for agent_id, path in data.items()}


def to_serializable(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return to_serializable(value.to_dict())
    if is_dataclass(value):
        return to_serializable(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): to_serializable(item) for key, item in value.items()}
    if isinstance(value, set):
        return sorted(to_serializable(item) for item in value)
    if isinstance(value, tuple):
        return [to_serializable(item) for item in value]
    if isinstance(value, list):
        return [to_serializable(item) for item in value]
    return value
