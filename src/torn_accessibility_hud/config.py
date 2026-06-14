"""Configuration loading for the local accessibility HUD."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, TypeVar

from .models import ScreenRegion

T = TypeVar("T")


@dataclass(frozen=True)
class CaptureConfig:
    monitor_index: int = 1
    # Once tools/calibrate_regions.py has produced config/regions_calibrated.json,
    # copy its log_region here to keep the existing OCR capture pipeline intact.
    region: ScreenRegion = ScreenRegion(left=0, top=0, width=1280, height=720)
    fps_limit: float = 15.0


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
    calibrated_regions_path: str | None = "config/regions_calibrated.json"
    hero_cards_region: ScreenRegion | None = None
    board_cards_region: ScreenRegion | None = None
    pot_region: ScreenRegion | None = None
    debug_card_regions: bool = False
    debug_card_regions_dir: str = "debug_captures/card_regions"
    debug_card_regions_interval_sec: float = 2.0
    debug_table_regions: bool = False
    debug_table_regions_dir: str = "debug_captures/table_regions"
    debug_table_regions_interval_sec: float = 1.0
    hero_cards_interval_sec: float = 0.25
    card_stable_reads_required: int = 3
    card_cache_max_missing_scans: int = 12
    card_ocr_scale: float = 3.0
    card_ocr_allowlist: str = "0123456789AaKkQqJjTtCDHScdhs"
    pot_ocr_scale: float = 4.0
    pot_ocr_allowlist: str = "POT: $0123456789,."
    pot_ocr_interval_sec: float = 0.0
    action_ocr_scale: float = 3.0
    action_ocr_allowlist: str = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz $0123456789,./KkMm"
    action_ocr_interval_sec: float = 0.0


@dataclass(frozen=True)
class ParserConfig:
    max_reasonable_amount: float = 10_000_000.0
    min_line_confidence: float = 0.42
    action_patterns_path: str | None = None


@dataclass(frozen=True)
class EquityConfig:
    simulations: int = 2500
    timeout_ms: int = 900
    max_opponents: int = 8
    random_seed: int | None = None


@dataclass(frozen=True)
class DebugConfig:
    session_csv_enabled: bool = True
    session_csv_path: str = "debug_captures/debug_current_session.csv"


@dataclass(frozen=True)
class OverlayConfig:
    title: str = "Torn Accessibility HUD"
    width: int = 440
    height: int = 360
    x: int = 20
    y: int = 20
    alpha: float = 0.86
    always_on_top: bool = True
    poll_interval_ms: int = 50
    background_hex: str = "#101820"
    text_hex: str = "#F8F8F2"


CALIBRATED_REGION_NAMES = (
    "log_region",
    "hero_cards_region",
    "board_cards_region",
    "stack_region",
    "pot_region",
    "action_slot_left",
    "action_slot_centre",
    "action_slot_right",
)


@dataclass(frozen=True)
class RegionsConfig:
    """Optional calibrated regions for future image-based detectors.

    AppConfig deliberately does not consume this yet. The current OCR path still
    reads CaptureConfig.region, and calibrated log_region is intended to be
    copied there until the app is expanded to route per-detector regions.
    """

    log_region: ScreenRegion | None = None
    hero_cards_region: ScreenRegion | None = None
    board_cards_region: ScreenRegion | None = None
    stack_region: ScreenRegion | None = None
    pot_region: ScreenRegion | None = None
    action_slot_left: ScreenRegion | None = None
    action_slot_centre: ScreenRegion | None = None
    action_slot_right: ScreenRegion | None = None
    extra_regions: tuple[tuple[str, ScreenRegion], ...] = field(default_factory=tuple)

    @classmethod
    def load(cls, path: str | Path) -> "RegionsConfig":
        config_path = Path(path).expanduser()
        with config_path.open("r", encoding="utf-8") as fp:
            raw = json.load(fp)
        if not isinstance(raw, dict):
            raise ValueError("Calibrated regions JSON must contain an object at the top level.")
        known = {
            name: _screen_region_from_raw(name, raw[name])
            for name in CALIBRATED_REGION_NAMES
            if name in raw
        }
        extras = tuple(
            (name, _screen_region_from_raw(name, value))
            for name, value in sorted(raw.items())
            if name not in CALIBRATED_REGION_NAMES
        )
        return cls(
            log_region=known.get("log_region"),
            hero_cards_region=known.get("hero_cards_region"),
            board_cards_region=known.get("board_cards_region"),
            stack_region=known.get("stack_region"),
            pot_region=known.get("pot_region"),
            action_slot_left=known.get("action_slot_left"),
            action_slot_centre=known.get("action_slot_centre"),
            action_slot_right=known.get("action_slot_right"),
            extra_regions=extras,
        )

    def as_dict(self) -> dict[str, ScreenRegion]:
        regions = {
            name: region
            for name, region in (
                ("log_region", self.log_region),
                ("hero_cards_region", self.hero_cards_region),
                ("board_cards_region", self.board_cards_region),
                ("stack_region", self.stack_region),
                ("pot_region", self.pot_region),
                ("action_slot_left", self.action_slot_left),
                ("action_slot_centre", self.action_slot_centre),
                ("action_slot_right", self.action_slot_right),
            )
            if region is not None
        }
        regions.update(dict(self.extra_regions))
        return regions


@dataclass(frozen=True)
class AppConfig:
    capture: CaptureConfig = CaptureConfig()
    debounce: DebounceConfig = DebounceConfig()
    ocr: OCRConfig = OCRConfig()
    parser: ParserConfig = ParserConfig()
    equity: EquityConfig = EquityConfig()
    overlay: OverlayConfig = OverlayConfig()
    debug: DebugConfig = DebugConfig()

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
    "debug": DebugConfig,
}


def _coerce_dataclass(dataclass_type: type[T], raw: dict[str, Any]) -> T:
    kwargs: dict[str, Any] = {}
    for item in fields(dataclass_type):
        if item.name not in raw:
            continue
        value = raw[item.name]
        if item.name == "region":
            kwargs[item.name] = ScreenRegion(**value)
        elif item.name.endswith("_region") and isinstance(value, dict):
            kwargs[item.name] = ScreenRegion(**value)
        elif item.name in _NESTED_TYPES and isinstance(value, dict):
            kwargs[item.name] = _coerce_dataclass(_NESTED_TYPES[item.name], value)
        elif item.name == "languages" and isinstance(value, list):
            kwargs[item.name] = tuple(value)
        else:
            kwargs[item.name] = value
    return dataclass_type(**kwargs)


def _screen_region_from_raw(name: str, raw: Any) -> ScreenRegion:
    if not isinstance(raw, dict):
        raise ValueError(f"{name} must be an object with left/top/width/height values.")
    try:
        region = ScreenRegion(
            left=int(raw["left"]),
            top=int(raw["top"]),
            width=int(raw["width"]),
            height=int(raw["height"]),
        )
    except KeyError as exc:
        raise ValueError(f"{name} is missing required key {exc.args[0]!r}.") from exc
    if region.width <= 0 or region.height <= 0:
        raise ValueError(f"{name} must have positive width and height.")
    return region


def write_default_config(path: str | Path) -> Path:
    """Write a JSON config template for local screen-region tuning."""

    config_path = Path(path).expanduser()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "capture": {
            "monitor_index": 1,
            "region": {"left": 0, "top": 0, "width": 1280, "height": 720},
            "fps_limit": 15.0,
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
            "calibrated_regions_path": "config/regions_calibrated.json",
            "hero_cards_region": None,
            "board_cards_region": None,
            "pot_region": None,
            "debug_card_regions": False,
            "debug_card_regions_dir": "debug_captures/card_regions",
            "debug_card_regions_interval_sec": 2.0,
            "debug_table_regions": False,
            "debug_table_regions_dir": "debug_captures/table_regions",
            "debug_table_regions_interval_sec": 1.0,
            "hero_cards_interval_sec": 0.25,
            "card_stable_reads_required": 3,
            "card_cache_max_missing_scans": 12,
            "card_ocr_scale": 3.0,
            "card_ocr_allowlist": "0123456789AaKkQqJjTtCDHScdhs",
            "pot_ocr_scale": 4.0,
            "pot_ocr_allowlist": "POT: $0123456789,.",
            "pot_ocr_interval_sec": 0.0,
            "action_ocr_scale": 3.0,
            "action_ocr_allowlist": "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz ",
            "action_ocr_interval_sec": 0.0,
        },
        "parser": {
            "max_reasonable_amount": 10000000.0,
            "min_line_confidence": 0.42,
            "action_patterns_path": None,
        },
        "equity": {
            "simulations": 2500,
            "timeout_ms": 900,
            "max_opponents": 8,
            "random_seed": None,
        },
        "debug": {
            "session_csv_enabled": True,
            "session_csv_path": "debug_captures/debug_current_session.csv",
        },
        "overlay": {
            "title": "Torn Accessibility HUD",
            "width": 440,
            "height": 360,
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
