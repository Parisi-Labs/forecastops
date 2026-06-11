from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True, slots=True)
class HorizonBucket:
    name: str
    min: str | None = None
    max: str | None = None


@dataclass(frozen=True, slots=True)
class ForecastOpsConfig:
    project: str = "default"
    store: Path = Path(".forecastops")
    ui_host: str = "127.0.0.1"
    ui_port: int = 4784
    allow_insample: bool = False
    timezone_policy: str = "warn"
    max_slice_cardinality: int = 100
    horizon_buckets: list[HorizonBucket] = field(
        default_factory=lambda: [
            HorizonBucket("0-1h", max="1h"),
            HorizonBucket("1-6h", min="1h", max="6h"),
            HorizonBucket("6-24h", min="6h", max="24h"),
            HorizonBucket("24-48h", min="24h", max="48h"),
            HorizonBucket("48h-7d", min="48h", max="7d"),
            HorizonBucket("7d+", min="7d"),
        ]
    )
    otel_enabled: bool = False
    otel_service_name: str = "forecastops"


DEFAULT_CONFIG_DICT: dict[str, Any] = {
    "project": "default",
    "store": ".forecastops",
    "ui": {"host": "127.0.0.1", "port": 4784},
    "validation": {
        "allow_insample": False,
        "timezone_policy": "warn",
        "max_slice_cardinality": 100,
    },
    "horizon_buckets": [
        {"name": "0-1h", "max": "1h"},
        {"name": "1-6h", "min": "1h", "max": "6h"},
        {"name": "6-24h", "min": "6h", "max": "24h"},
        {"name": "24-48h", "min": "24h", "max": "48h"},
        {"name": "48h-7d", "min": "48h", "max": "7d"},
        {"name": "7d+", "min": "7d"},
    ],
    "otel": {"enabled": False, "service_name": "forecastops"},
}


def load_config(path: str | Path = "forecastops.yaml") -> ForecastOpsConfig:
    config_path = Path(path)
    data = DEFAULT_CONFIG_DICT.copy()
    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as handle:
            user_data = yaml.safe_load(handle) or {}
        data = _deep_merge(data, user_data)
    store = Path(os.environ.get("FOPS_LOCAL_STORE", data.get("store", ".forecastops")))
    ui = data.get("ui", {})
    validation = data.get("validation", {})
    otel = data.get("otel", {})
    return ForecastOpsConfig(
        project=data.get("project", "default"),
        store=store,
        ui_host=ui.get("host", "127.0.0.1"),
        ui_port=int(os.environ.get("FOPS_UI_PORT", ui.get("port", 4784))),
        allow_insample=bool(validation.get("allow_insample", False)),
        timezone_policy=validation.get("timezone_policy", "warn"),
        max_slice_cardinality=int(validation.get("max_slice_cardinality", 100)),
        horizon_buckets=[HorizonBucket(**bucket) for bucket in data.get("horizon_buckets", [])],
        otel_enabled=_env_bool("FOPS_OTEL_ENABLED", bool(otel.get("enabled", False))),
        otel_service_name=otel.get("service_name", "forecastops"),
    )


def write_default_config(path: str | Path = "forecastops.yaml") -> Path:
    config_path = Path(path)
    if not config_path.exists():
        with config_path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(DEFAULT_CONFIG_DICT, handle, sort_keys=False)
    return config_path


def _deep_merge(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _env_bool(key: str, default: bool) -> bool:
    value = os.environ.get(key)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}

