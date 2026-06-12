"""Interactively calibrate Torn HUD screen regions.

Use OpenCV's ROI selector on a single MSS screenshot:
drag a rectangle, press Enter/Space to confirm it, and press Esc when finished.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REGION_NAMES = (
    "log_region",
    "hero_cards_region",
    "board_cards_region",
    "stack_region",
)
DEFAULT_OUTPUT_PATH = Path("config/regions_calibrated.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Interactively calibrate Torn HUD screen regions.")
    parser.add_argument(
        "--monitor-index",
        type=int,
        default=1,
        help="MSS monitor index to capture. Use 1 for the first physical monitor.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="JSON path to write calibrated global screen regions.",
    )
    return parser.parse_args()


def grab_monitor_screenshot(monitor_index: int) -> tuple[Any, dict[str, int]]:
    import mss
    import numpy as np

    with mss.mss() as screen_capture:
        if monitor_index < 0 or monitor_index >= len(screen_capture.monitors):
            available = len(screen_capture.monitors) - 1
            raise ValueError(f"Monitor index {monitor_index} is invalid; available physical monitors: 1..{available}.")
        monitor = screen_capture.monitors[monitor_index]
        screenshot = np.asarray(screen_capture.grab(monitor), dtype=np.uint8)
    # MSS returns BGRA; OpenCV's selector displays BGR.
    return screenshot[:, :, :3], monitor


def select_regions(screenshot_bgr: Any) -> tuple[tuple[int, int, int, int], ...]:
    import cv2

    window_name = "Torn HUD region calibration - Enter confirms each ROI, Esc finishes"
    print("Draw ROIs in this order:")
    for index, name in enumerate(REGION_NAMES, start=1):
        print(f"  {index}. {name}")
    print("Draw additional ROIs after those if needed; they will be named region_0, region_1, ...")
    print("Press Enter or Space after each rectangle, then Esc when done.")
    rois = cv2.selectROIs(window_name, screenshot_bgr, showCrosshair=True, fromCenter=False)
    cv2.destroyWindow(window_name)
    return tuple((int(x), int(y), int(width), int(height)) for x, y, width, height in rois)


def label_regions(
    rois: tuple[tuple[int, int, int, int], ...],
    monitor_left: int,
    monitor_top: int,
) -> dict[str, dict[str, int]]:
    labeled: dict[str, dict[str, int]] = {}
    extra_index = 0
    for index, (x, y, width, height) in enumerate(rois):
        if width <= 0 or height <= 0:
            continue
        if index < len(REGION_NAMES):
            name = REGION_NAMES[index]
        else:
            name = f"region_{extra_index}"
            extra_index += 1
        # OpenCV returns ROI coordinates relative to the screenshot image. MSS
        # monitor entries include left/top offsets for multi-monitor desktops,
        # so adding those offsets converts local pixels into global coordinates
        # that ScreenRegion and later image-based detectors can capture exactly.
        labeled[name] = {
            "left": monitor_left + x,
            "top": monitor_top + y,
            "width": width,
            "height": height,
        }
    return labeled


def write_regions(path: Path, regions: dict[str, dict[str, int]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fp:
        json.dump(regions, fp, indent=2)
        fp.write("\n")


def main() -> None:
    args = parse_args()
    screenshot, monitor = grab_monitor_screenshot(args.monitor_index)
    # Interactive selection avoids hand-typed coordinates, which are brittle on
    # scaled displays and easy to transpose. Drawing directly over the current
    # Torn layout produces detector-ready regions for logs, hero-card images,
    # board-card images, and stack/balance recognition.
    rois = select_regions(screenshot)
    regions = label_regions(rois, monitor_left=int(monitor["left"]), monitor_top=int(monitor["top"]))
    write_regions(args.output, regions)
    print(json.dumps(regions, indent=2))


if __name__ == "__main__":
    main()
