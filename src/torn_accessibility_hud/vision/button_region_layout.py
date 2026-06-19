"""Validate fixed action-bar slot calibration regions."""

from __future__ import annotations

from ..models import ScreenRegion
from ..parsing.action_slots import ACTION_SLOT_NAMES

_MAX_SLOT_WIDTH = 300
_MAX_SLOT_HEIGHT = 80


def region_intersection_area(left: ScreenRegion, right: ScreenRegion) -> int:
    x1 = max(left.left, right.left)
    y1 = max(left.top, right.top)
    x2 = min(left.left + left.width, right.left + right.width)
    y2 = min(left.top + left.height, right.top + right.height)
    if x2 <= x1 or y2 <= y1:
        return 0
    return (x2 - x1) * (y2 - y1)


def region_area(region: ScreenRegion) -> int:
    return max(region.width, 0) * max(region.height, 0)


def overlap_ratio(left: ScreenRegion, right: ScreenRegion) -> float:
    intersection = region_intersection_area(left, right)
    if intersection <= 0:
        return 0.0
    smaller = min(region_area(left), region_area(right))
    if smaller <= 0:
        return 0.0
    return intersection / smaller


def format_region_coords(region: ScreenRegion) -> str:
    return f"{region.left},{region.top},{region.width},{region.height}"


def validate_action_slot_regions(
    regions: dict[str, ScreenRegion],
) -> tuple[dict[str, ScreenRegion], tuple[str, ...]]:
    """Keep only well-sized action slots; warn on overlap or missing slots."""

    warnings: list[str] = []
    filtered = dict(regions)
    slot_regions = {name: filtered[name] for name in ACTION_SLOT_NAMES if name in filtered}

    for name in ACTION_SLOT_NAMES:
        if name not in slot_regions:
            warnings.append(f"missing calibrated region {name}")

    excluded: set[str] = set()
    for name, region in slot_regions.items():
        if region.width > _MAX_SLOT_WIDTH:
            excluded.add(name)
            warnings.append(f"{name} width {region.width}px exceeds {_MAX_SLOT_WIDTH}px; excluding from OCR")
        if region.height > _MAX_SLOT_HEIGHT:
            excluded.add(name)
            warnings.append(f"{name} height {region.height}px exceeds {_MAX_SLOT_HEIGHT}px; excluding from OCR")

    active_names = [name for name in ACTION_SLOT_NAMES if name in slot_regions and name not in excluded]
    for index, left_name in enumerate(active_names):
        left_region = slot_regions[left_name]
        for right_name in active_names[index + 1 :]:
            right_region = slot_regions[right_name]
            ratio = overlap_ratio(left_region, right_region)
            if ratio >= 0.20:
                warnings.append(f"{left_name} overlaps {right_name} ({ratio:.0%}) — recalibrate tighter boxes")

    for name in excluded:
        filtered.pop(name, None)
    return filtered, tuple(warnings)
