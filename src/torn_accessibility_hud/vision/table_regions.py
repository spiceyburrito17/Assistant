"""Dedicated OCR for pot and fixed action-bar slot regions."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import numpy as np

from ..config import OCRConfig, RegionsConfig
from ..diagnostics import debug_log
from ..models import ActionSlotOCRResult, OCRLine, PotOCRResult, TableOCRResult
from ..parsing.action_slots import ACTION_SLOT_NAMES
from ..parsing.action_ui import is_post_hand_ui
from ..parsing.pot_parser import parse_pot_region_text
from .button_region_layout import format_region_coords, validate_action_slot_regions
from .ocr_engine import EasyOCREngine, format_raw_ocr_debug_lines, preprocess_card_region


class TableRegionReader:
    """Read pot and three fixed action-bar slots with optional debug capture."""

    POT_REGION = "pot_region"
    MAX_SLOT_WIDTH = 300

    def __init__(self, config: OCRConfig) -> None:
        self.config = config
        self.regions, self.region_warnings = self._load_regions(config.calibrated_regions_path)
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
        slot_results: list[ActionSlotOCRResult] = []
        pot_scanned = False
        action_scanned = False

        pot_region = self.regions.get(self.POT_REGION)
        if pot_region is not None:
            pot_scanned = True
            pot_result = self._read_pot_region(capture, ocr, frame_id, pot_region)

        for slot_name in ACTION_SLOT_NAMES:
            region = self.regions.get(slot_name)
            if region is None:
                continue
            if not self._should_process(slot_name):
                continue
            action_scanned = True
            slot_results.append(self._read_action_slot(capture, ocr, frame_id, slot_name, region))

        slot_texts = [slot.ocr_scan_raw for slot in slot_results]
        return TableOCRResult(
            pot=pot_result,
            slots=tuple(slot_results),
            pot_region_scanned=pot_scanned,
            action_regions_scanned=action_scanned,
            post_hand_ui=any(is_post_hand_ui(text) for text in slot_texts if text),
            region_layout_warnings=self.region_warnings,
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
            pot_parse = parse_pot_region_text(combined_text)
            if prefix is not None:
                debug_lines = (
                    f"=== pot OCR frame {frame_id:06d} region=pot_region ===",
                    f"allowlist={allowlist!r}",
                    f"pot_crop_text={combined_text!r}",
                    f"pot_anchor_match={pot_parse.pot_anchor_match!r}",
                    f"pot_anchor_confidence={pot_parse.pot_anchor_confidence!r}",
                    f"pot_digits_start={pot_parse.pot_digits_start!r}",
                    f"pot_candidate={pot_parse.candidate!r}",
                    f"pot_normalized={pot_parse.normalized!r}",
                    f"parse_status={pot_parse.status}",
                    f"ocr_confidence={best_confidence:.4f}",
                    *format_raw_ocr_debug_lines("pot_region.preprocessed", raw_lines, allowlist),
                )
                self._save_debug_images(prefix, raw, processed, debug_lines)
            self.last_saved_at[self.POT_REGION] = time.monotonic()
            return PotOCRResult(
                raw_text=combined_text,
                parsed_amount=pot_parse.normalized,
                ocr_confidence=best_confidence,
                allowlist=allowlist,
                pot_candidate=pot_parse.candidate,
                parse_status=pot_parse.status,
                pot_anchor_index=pot_parse.pot_anchor_index,
                pot_anchor_match=pot_parse.pot_anchor_match,
                pot_anchor_confidence=pot_parse.pot_anchor_confidence,
                pot_digits_start=pot_parse.pot_digits_start,
            )
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"pot_region OCR failed: {type(exc).__name__}: {exc}"
            if prefix is not None:
                self._write_debug_text(prefix, (f"[error] {self.last_error}",))
            return None

    def _read_action_slot(
        self,
        capture: Any,
        ocr: EasyOCREngine,
        frame_id: int,
        slot_name: str,
        region: Any,
    ) -> ActionSlotOCRResult:
        allowlist = self.config.action_ocr_allowlist
        region_coords = format_region_coords(region)
        prefix = self._debug_prefix(slot_name, frame_id) if self.debug_enabled else None
        ocr_scan_raw = ""
        confidence = 0.0
        raw_lines: tuple[OCRLine, ...] = ()
        try:
            raw = capture.grab_region(region)
            if raw.size == 0:
                return ActionSlotOCRResult(
                    slot_name=slot_name,
                    region_coords=region_coords,
                )
            processed = preprocess_card_region(raw, scale=self.config.action_ocr_scale)
            raw_lines = ocr.read_raw(processed, allowlist=allowlist)
            ocr_scan_raw = " ".join(line.text for line in raw_lines).strip()
            confidence = max((line.confidence for line in raw_lines), default=0.0)
            if prefix is not None:
                debug_lines = (
                    f"=== action slot OCR frame {frame_id:06d} slot={slot_name} ===",
                    f"region_coords={region_coords!r}",
                    f"allowlist={allowlist!r}",
                    f"ocr_scan_raw={ocr_scan_raw!r}",
                    f"ocr_confidence={confidence:.4f}",
                    *format_raw_ocr_debug_lines(f"{slot_name}.preprocessed", raw_lines, allowlist),
                )
                self._save_debug_images(prefix, raw, processed, debug_lines)
            self.last_saved_at[slot_name] = time.monotonic()
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"{slot_name} OCR failed: {type(exc).__name__}: {exc}"
            if prefix is not None:
                self._write_debug_text(prefix, (f"[error] {self.last_error}",))
        return ActionSlotOCRResult(
            slot_name=slot_name,
            ocr_scan_raw=ocr_scan_raw,
            region_coords=region_coords,
            ocr_confidence=confidence,
        )

    def _should_process(self, region_name: str) -> bool:
        if region_name == self.POT_REGION:
            interval = max(self.config.pot_ocr_interval_sec, 0.0)
        elif region_name in ACTION_SLOT_NAMES:
            interval = max(self.config.action_ocr_interval_sec, 0.0)
        else:
            interval = max(self.config.debug_table_regions_interval_sec, 0.1)
        if interval <= 0:
            return True
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

    def _load_regions(self, path: str | None) -> tuple[dict[str, Any], tuple[str, ...]]:
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
            if name == self.POT_REGION or name in ACTION_SLOT_NAMES
        }
        filtered, warnings = validate_action_slot_regions(selected)
        for warning in warnings:
            debug_log("[REGIONS] %s", warning)
        for name in filtered:
            region = filtered[name]
            debug_log(
                "configured table region %s: coords=%s size=%sx%s",
                name,
                format_region_coords(region),
                region.width,
                region.height,
            )
        return filtered, warnings
