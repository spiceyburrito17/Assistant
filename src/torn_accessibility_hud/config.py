"""Configuration loading for the local accessibility HUD."""

from __future__ import annotations

import json
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, TypeVar

from .models import ScreenRegion

T = TypeVar("T")


@dataclass(frozen=True)
class CaptureConfig:
    monitor_index: int = 1
    region: ScreenRegion = ScreenRegion(left=0, top=0, width=1280, height=720)
    fps_limit: float = 12.0


@dataclass(frozen=True)
class DebounceConfig:
    stable_frames_required: int = 3
    max_mean_delta: float = 3.5
    hash_width: int = 96
    hash_height: int = 54
    min_luma: float = 12.0
    max_luma: float = 245.0
    min_variance: float = 8.0


@dataclass(frozen=True)
class OCRConfig:
    languages: tuple[str, ...] = ("en",)
    gpu: bool = True
    min_confidence: float = 0.48
    paragraph: bool = False
    queue_size: int = 2


@dataclass(frozen=True)
class ParserConfig:
    max_reasonable_amount: float = 10_000_000.0
    min_line_confidence: float = 0.42
    action_patterns_path: str | None = None


@dataclass(frozen=True)
class EquityConfig:
    simulations: int = 2500
    timeout_ms: int = 450
    max_opponents: int = 8
    random_seed: int | None = None


@dataclass(frozen=True)
class OverlayConfig:
    title: str = "Torn Accessibility HUD"
    width: int = 440
    height: int = 260
    x: int = 20
    y: int = 20
    alpha: float = 0.86
    always_on_top: bool = True
    poll_interval_ms: int = 50
    background_hex: str = "#101820"
    text_hex: str = "#F8F8F2"


@dataclass(frozen=True)
class AppConfig:
    capture: CaptureConfig = CaptureConfig()
    debounce: DebounceConfig = DebounceConfig()
    ocr: OCRConfig = OCRConfig()
    parser: ParserConfig = ParserConfig()
    equity: EquityConfig = EquityConfig()
    overlay: OverlayConfig = OverlayConfig()

    @classmethod
    def default(cls) -> "AppConfig":
        return cls()

    @classmethod
    def load(cls, path: str | Path | None) -> "AppConfig":
        if path is None:
            return cls.default()
        config_path = Path(path).expanduser()
        with config_path.open("r", encoding="utf-8") as fp:
            raw = json.load(fp)
        return _coerce_dataclass(cls, raw)


_NESTED_TYPES: dict[str, type[Any]] = {
    "capture": CaptureConfig,
    "debounce": DebounceConfig,
    "ocr": OCRConfig,
    "parser": ParserConfig,
    "equity": EquityConfig,
    "overlay": OverlayConfig,
}


def _coerce_dataclass(dataclass_type: type[T], raw: dict[str, Any]) -> T:
    kwargs: dict[str, Any] = {}
    for item in fields(dataclass_type):
        if item.name not in raw:
            continue
        value = raw[item.name]
        if item.name == "region":
            kwargs[item.name] = ScreenRegion(**value)
        elif item.name in _NESTED_TYPES and isinstance(value, dict):
            kwargs[item.name] = _coerce_dataclass(_NESTED_TYPES[item.name], value)
        elif item.name == "languages" and isinstance(value, list):
            kwargs[item.name] = tuple(value)
        else:
            kwargs[item.name] = value
    return dataclass_type(**kwargs)


def write_default_config(path: str | Path) -> Path:
    """Write a JSON config template for local screen-region tuning."""

    config_path = Path(path).expanduser()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "capture": {
            "monitor_index": 1,
            "region": {"left": 0, "top": 0, "width": 1280, "height": 720},
            "fps_limit": 12.0,
        },
        "debounce": {
            "stable_frames_required": 3,
            "max_mean_delta": 3.5,
            "hash_width": 96,
            "hash_height": 54,
            "min_luma": 12.0,
            "max_luma": 245.0,
            "min_variance": 8.0,
        },
        "ocr": {
            "languages": ["en"],
            "gpu": True,
            "min_confidence": 0.48,
            "paragraph": False,
            "queue_size": 2,
        },
        "parser": {
            "max_reasonable_amount": 10000000.0,
            "min_line_confidence": 0.42,
            "action_patterns_path": None,
        },
        "equity": {
            "simulations": 2500,
            "timeout_ms": 450,
            "max_opponents": 8,
            "random_seed": None,
        },
        "overlay": {
            "title": "Torn Accessibility HUD",
            "width": 440,
            "height": 260,
            "x": 20,
            "y": 20,
            "alpha": 0.86,
            "always_on_top": True,
            "poll_interval_ms": 50,
            "background_hex": "#101820",
            "text_hex": "#F8F8F2",
        },
    }
    with config_path.open("w", encoding="utf-8") as fp:
        json.dump(payload, fp, indent=2)
        fp.write("\n")
    return config_path
