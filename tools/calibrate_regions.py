"""Interactively calibrate Torn HUD screen regions.

Use a small OpenCV ROI selector on a single MSS screenshot:
drag a rectangle, press Enter/Space to confirm it, and press Q or Esc to finish.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REGION_NAMES = (
    "log_region",
    "hero_cards_region",
    "board_cards_region",
    "stack_region",
    "pot_region",
    "fold_button_region",
    "check_button_region",
    "call_button_region",
    "raise_button_region",
)
DEFAULT_OUTPUT_PATH = Path("config/regions_calibrated.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Interactively calibrate Torn HUD screen regions.")
    parser.add_argument(
        "--monitor-index",
        type=int,
        default=None,
        help=(
            "Explicit MSS monitor index to capture. If omitted, the tool captures "
            "the leftmost physical monitor, which is usually the second monitor "
            "when it sits to the left of the main display."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="JSON path to write calibrated global screen regions.",
    )
    parser.add_argument(
        "--windowed",
        action="store_true",
        help="Show the calibration image in a normal window instead of fullscreen.",
    )
    return parser.parse_args()


def choose_monitor(monitors: list[dict[str, int]], monitor_index: int | None) -> dict[str, int]:
    if monitor_index is not None:
        if monitor_index < 0 or monitor_index >= len(monitors):
            available = len(monitors) - 1
            raise ValueError(f"Monitor index {monitor_index} is invalid; available physical monitors: 1..{available}.")
        return monitors[monitor_index]

    physical_monitors = monitors[1:]
    if not physical_monitors:
        raise ValueError("MSS did not report any physical monitors.")
    # MSS monitor 0 is the virtual bounding box for all displays. For a left-side
    # secondary monitor, the physical monitor with the smallest left coordinate
    # is the one we want to calibrate by default.
    return min(physical_monitors, key=lambda monitor: (int(monitor["left"]), int(monitor["top"])))


def grab_monitor_screenshot(monitor_index: int | None) -> tuple[Any, dict[str, int]]:
    import mss
    import numpy as np

    with mss.mss() as screen_capture:
        monitor = choose_monitor(screen_capture.monitors, monitor_index)
        screenshot = np.asarray(screen_capture.grab(monitor), dtype=np.uint8)
    # MSS returns BGRA; OpenCV's selector displays BGR.
    return screenshot[:, :, :3], monitor


@dataclass
class ROISelector:
    screenshot_bgr: Any
    cv2: Any
    window_name: str
    fullscreen: bool = True
    window_origin: tuple[int, int] = (0, 0)
    rois: list[tuple[int, int, int, int]] = field(default_factory=list)
    drag_start: tuple[int, int] | None = None
    drag_current: tuple[int, int] | None = None
    is_dragging: bool = False

    def handle_mouse(self, event: int, x: int, y: int, _flags: int, _param: Any) -> None:
        if event == self.cv2.EVENT_LBUTTONDOWN:
            self.drag_start = (x, y)
            self.drag_current = (x, y)
            self.is_dragging = True
        elif event == self.cv2.EVENT_MOUSEMOVE and self.drag_start is not None:
            self.drag_current = (x, y)
        elif event == self.cv2.EVENT_LBUTTONUP and self.drag_start is not None:
            self.drag_current = (x, y)
            self.is_dragging = False

    def run(self) -> tuple[tuple[int, int, int, int], ...]:
        self._configure_window()
        self.cv2.setMouseCallback(self.window_name, self.handle_mouse)
        try:
            while True:
                self.cv2.imshow(self.window_name, self._render())
                key = self.cv2.waitKey(20) & 0xFF
                if key in (10, 13, 32):
                    self._confirm_pending_roi()
                elif key in (ord("q"), ord("Q"), 27):
                    break
                elif key in (ord("c"), ord("C"), 8, 127):
                    self._clear_pending_roi()
        finally:
            self.cv2.destroyWindow(self.window_name)
        return tuple(self.rois)

    def _configure_window(self) -> None:
        self.cv2.namedWindow(self.window_name, self.cv2.WINDOW_NORMAL)
        # Move the window onto the same monitor we captured before fullscreening.
        # This avoids the OS title bar and keeps the displayed screenshot aligned
        # with the pixel coordinates returned by the mouse callback.
        self.cv2.moveWindow(self.window_name, self.window_origin[0], self.window_origin[1])
        if self.fullscreen:
            self.cv2.setWindowProperty(
                self.window_name,
                self.cv2.WND_PROP_FULLSCREEN,
                self.cv2.WINDOW_FULLSCREEN,
            )

    def _render(self) -> Any:
        image = self.screenshot_bgr.copy()
        for index, roi in enumerate(self.rois):
            self._draw_roi(image, roi, color=(60, 220, 60), label=self._region_name(index))
        pending = self._pending_roi()
        if pending is not None:
            self._draw_roi(image, pending, color=(0, 215, 255), label=f"pending: {self._region_name(len(self.rois))}")
        help_text = "Drag ROI -> Enter/Space confirm | C clear current | Q or Esc finish"
        self.cv2.putText(image, help_text, (20, 32), self.cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        return image

    def _draw_roi(self, image: Any, roi: tuple[int, int, int, int], color: tuple[int, int, int], label: str) -> None:
        x, y, width, height = roi
        self.cv2.rectangle(image, (x, y), (x + width, y + height), color, 2)
        self.cv2.putText(image, label, (x, max(20, y - 8)), self.cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

    def _confirm_pending_roi(self) -> None:
        pending = self._pending_roi()
        if pending is None:
            return
        self.rois.append(pending)
        self._clear_pending_roi()
        next_name = self._region_name(len(self.rois))
        print(f"Confirmed {self._region_name(len(self.rois) - 1)}. Next: {next_name}")

    def _clear_pending_roi(self) -> None:
        self.drag_start = None
        self.drag_current = None
        self.is_dragging = False

    def _pending_roi(self) -> tuple[int, int, int, int] | None:
        if self.drag_start is None or self.drag_current is None:
            return None
        start_x, start_y = self.drag_start
        current_x, current_y = self.drag_current
        x = min(start_x, current_x)
        y = min(start_y, current_y)
        width = abs(current_x - start_x)
        height = abs(current_y - start_y)
        if width <= 0 or height <= 0:
            return None
        return x, y, width, height

    @staticmethod
    def _region_name(index: int) -> str:
        if index < len(REGION_NAMES):
            return REGION_NAMES[index]
        return f"region_{index - len(REGION_NAMES)}"


def select_regions(
    screenshot_bgr: Any,
    window_origin: tuple[int, int],
    fullscreen: bool,
) -> tuple[tuple[int, int, int, int], ...]:
    import cv2

    window_name = "Torn HUD region calibration - Q or Esc finishes"
    print("Draw ROIs in this order:")
    for index, name in enumerate(REGION_NAMES, start=1):
        print(f"  {index}. {name}")
    print("Draw additional ROIs after those if needed; they will be named region_0, region_1, ...")
    mode = "fullscreen" if fullscreen else "windowed"
    print(f"Opening calibration view in {mode} mode.")
    print("Drag an ROI, press Enter or Space to confirm it, press C to clear it, and press Q or Esc when done.")
    return ROISelector(
        screenshot_bgr=screenshot_bgr,
        cv2=cv2,
        window_name=window_name,
        fullscreen=fullscreen,
        window_origin=window_origin,
    ).run()


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
    rois = select_regions(
        screenshot,
        window_origin=(int(monitor["left"]), int(monitor["top"])),
        fullscreen=not args.windowed,
    )
    regions = label_regions(rois, monitor_left=int(monitor["left"]), monitor_top=int(monitor["top"]))
    write_regions(args.output, regions)
    print(json.dumps(regions, indent=2))


if __name__ == "__main__":
    main()
