"""Dedicated OCR for pot and hero action button regions."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ..config import OCRConfig, RegionsConfig
from ..diagnostics import debug_log
from ..models import ButtonOCRResult, OCRLine, PotOCRResult, TableOCRResult
from ..parsing.amounts import parse_pot_amount_from_text
from ..parsing.legal_actions import (
    allowed_labels_for_region,
    expected_label_for_button_region,
    extract_actions_from_region_text,
)
from .ocr_engine import EasyOCREngine, format_raw_ocr_debug_lines, preprocess_card_region


class TableRegionReader:
    """Read pot and per-button regions with optional debug capture."""

    POT_REGION = "pot_region"
    TO_CALL_REGION = "to_call_region"
    BUTTON_REGION_SUFFIX = "_button_region"

    def __init__(self, config: OCRConfig) -> None:
        self.config = config
        self.regions = self._load_regions(config.calibrated_regions_path)
        self.output_dir = Path(config.debug_table_regions_dir)
        self.last_saved_at: dict[str, float] = {}
        self.last_error: str | None = None

    @property
    def regions_configured(self) -> bool:
        return bool(self.regions)

    @property
    def debug_enabled(self) -> bool:
        return self.config.debug_table_regions

    def capture_and_read(
        self,
        capture: Any,
        ocr: EasyOCREngine,
        frame_id: int,
    ) -> TableOCRResult:
        if not self.regions_configured:
            return TableOCRResult()
        pot_result: PotOCRResult | None = None
        button_results: list[ButtonOCRResult] = []
        pot_scanned = False
        action_scanned = False

        pot_region = self.regions.get(self.POT_REGION)
        if pot_region is not None and self._should_process(self.POT_REGION):
            pot_scanned = True
            pot_result = self._read_pot_region(capture, ocr, frame_id, pot_region)

        for region_name in sorted(self.regions):
            if not region_name.endswith(self.BUTTON_REGION_SUFFIX):
                continue
            if not self._should_process(region_name):
                continue
            action_scanned = True
            button_results.append(
                self._read_button_region(capture, ocr, frame_id, region_name, self.regions[region_name])
            )

        return TableOCRResult(
            pot=pot_result,
            buttons=tuple(button_results),
            pot_region_scanned=pot_scanned,
            action_regions_scanned=action_scanned,
        )

    def _read_pot_region(
        self,
        capture: Any,
        ocr: EasyOCREngine,
        frame_id: int,
        region: Any,
    ) -> PotOCRResult | None:
        allowlist = self.config.pot_ocr_allowlist
        prefix = self._debug_prefix("pot_region", frame_id) if self.debug_enabled else None
        try:
            raw = capture.grab_region(region)
            if raw.size == 0:
                return None
            processed = preprocess_card_region(raw, scale=self.config.pot_ocr_scale)
            raw_lines = ocr.read_raw(processed, allowlist=allowlist)
            combined_text = " ".join(line.text for line in raw_lines).strip()
            best_confidence = max((line.confidence for line in raw_lines), default=0.0)
            parsed = parse_pot_amount_from_text(combined_text)
            if prefix is not None:
                debug_lines = (
                    f"=== pot OCR frame {frame_id:06d} region=pot_region ===",
                    f"allowlist={allowlist!r}",
                    f"raw_text={combined_text!r}",
                    f"ocr_confidence={best_confidence:.4f}",
                    f"parsed_amount={parsed!r}",
                    *format_raw_ocr_debug_lines("pot_region.preprocessed", raw_lines, allowlist),
                )
                self._save_debug_images(prefix, raw, processed, debug_lines)
            self.last_saved_at[self.POT_REGION] = time.monotonic()
            return PotOCRResult(
                raw_text=combined_text,
                parsed_amount=parsed,
                ocr_confidence=best_confidence,
                allowlist=allowlist,
            )
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"pot_region OCR failed: {type(exc).__name__}: {exc}"
            if prefix is not None:
                self._write_debug_text(prefix, (f"[error] {self.last_error}",))
            return None

    def _read_button_region(
        self,
        capture: Any,
        ocr: EasyOCREngine,
        frame_id: int,
        region_name: str,
        region: Any,
    ) -> ButtonOCRResult:
        allowlist = self.config.action_ocr_allowlist
        expected = expected_label_for_button_region(region_name)
        prefix = self._debug_prefix(region_name, frame_id) if self.debug_enabled else None
        raw_text = ""
        normalized_label: str | None = None
        detected_labels: tuple[str, ...] = ()
        confidence = 0.0
        ambiguous = False
        try:
            raw = capture.grab_region(region)
            if raw.size == 0:
                return ButtonOCRResult(
                    region_name=region_name,
                    raw_text="",
                    normalized_label=None,
                    confidence=0.0,
                    ambiguous=False,
                    expected_label=expected,
                    detected_labels=(),
                )
            processed = preprocess_card_region(raw, scale=self.config.action_ocr_scale)
            raw_lines = ocr.read_raw(processed, allowlist=allowlist)
            raw_text = " ".join(line.text for line in raw_lines).strip()
            ocr_confidence = max((line.confidence for line in raw_lines), default=0.0)
            extracted = extract_actions_from_region_text(raw_text, ocr_confidence=ocr_confidence)
            detected_labels = tuple(action.label for action in extracted)
            normalized_label = detected_labels[0] if detected_labels else None
            confidence = max((action.confidence for action in extracted), default=0.0)
            ambiguous = any(action.ambiguous for action in extracted)
            if prefix is not None:
                debug_lines = (
                    f"=== action button OCR frame {frame_id:06d} region={region_name} ===",
                    f"expected_label={expected!r}",
                    f"slot_labels={allowed_labels_for_region(region_name)!r}",
                    f"allowlist={allowlist!r}",
                    f"raw_text={raw_text!r}",
                    f"detected_labels={list(detected_labels)!r}",
                    f"normalized_label={normalized_label!r}",
                    f"confidence={confidence:.4f}",
                    f"ambiguous={ambiguous}",
                    *format_raw_ocr_debug_lines(f"{region_name}.preprocessed", raw_lines, allowlist),
                )
                self._save_debug_images(prefix, raw, processed, debug_lines)
            self.last_saved_at[region_name] = time.monotonic()
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"{region_name} OCR failed: {type(exc).__name__}: {exc}"
            if prefix is not None:
                self._write_debug_text(prefix, (f"[error] {self.last_error}",))
        return ButtonOCRResult(
            region_name=region_name,
            raw_text=raw_text,
            normalized_label=normalized_label,
            confidence=confidence,
            ambiguous=ambiguous,
            expected_label=expected,
            detected_labels=detected_labels,
        )

    def _should_process(self, region_name: str) -> bool:
        interval = max(self.config.debug_table_regions_interval_sec, 0.1)
        return time.monotonic() - self.last_saved_at.get(region_name, 0.0) >= interval

    def _debug_prefix(self, region_name: str, frame_id: int) -> Path:
        assert self.debug_enabled
        self.output_dir.mkdir(parents=True, exist_ok=True)
        return self.output_dir / f"frame_{frame_id:06d}_{region_name}"

    def _save_debug_images(
        self,
        prefix: Path,
        raw: np.ndarray[Any, Any],
        processed: np.ndarray[Any, Any],
        debug_lines: tuple[str, ...],
    ) -> None:
        if not self.debug_enabled:
            return
        import cv2

        cv2.imwrite(str(prefix.with_name(f"{prefix.name}_raw.png")), raw)
        cv2.imwrite(str(prefix.with_name(f"{prefix.name}_preprocessed.png")), processed)
        self._write_debug_text(prefix, debug_lines)

    def _write_debug_text(self, prefix: Path, debug_lines: tuple[str, ...]) -> None:
        if not self.debug_enabled:
            return
        with prefix.with_name(f"{prefix.name}_ocr.txt").open("w", encoding="utf-8") as fp:
            for line in debug_lines:
                fp.write(f"{line}\n")

    def _load_regions(self, path: str | None) -> dict[str, Any]:
        regions: dict[str, Any] = {}
        if path:
            regions_path = Path(path)
            if regions_path.exists():
                try:
                    regions = RegionsConfig.load(regions_path).as_dict()
                except (OSError, ValueError) as exc:
                    self.last_error = f"Unable to load calibrated regions: {exc}"
        if self.config.pot_region is not None:
            regions[self.POT_REGION] = self.config.pot_region
        selected = {
            name: regions[name]
            for name in regions
            if name == self.POT_REGION or name.endswith(self.BUTTON_REGION_SUFFIX)
        }
        for name in selected:
            debug_log("configured table region %s: %sx%s", name, selected[name].width, selected[name].height)
        return selected
