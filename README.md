# Torn Accessibility HUD

Local Python accessibility HUD for reading fast Torn City poker text logs and
translating them into a simple color-coded overlay. The tool only reads pixels
from the local screen and does not click, type, or automate gameplay.

## Architecture

- **Eyes (`vision/`)**: `mss` screen capture, strict stable-frame debouncing,
  and EasyOCR configured with `gpu=True` by default.
- **Memory (`parsing/`, `tracking/`)**: OCR log parsing, anomaly rejection,
  VPIP/PFR opponent ledger, and a 169-class `RangeMatrix`.
- **Brain & Interface (`poker/`, `ui/`)**: Treys Monte Carlo equity simulation
  in a background thread plus a transparent Tkinter overlay.

Tkinter runs only rendering work. OCR, capture, parsing/tracking coordination,
and equity simulation run in daemon threads with latest-only queues so stale
frames are dropped instead of blocking the UI.

## Install

Python 3.10+ is required.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

For GPU OCR, install CUDA-compatible PyTorch for your local GPU before or after
installing this package. EasyOCR is initialized as:

```python
easyocr.Reader(["en"], gpu=True)
```

## Run

Tune `config/default_config.json` so `capture.region` matches the game log area,
then run:

```bash
torn-hud --config config/default_config.json
```

To write a fresh config template:

```bash
torn-hud --write-default-config config/local_config.json
```

## Region calibration

Torn's poker UI exposes different information in different visual forms. The
text log can be read by OCR, but hero cards, board cards, and stack/balance
areas are image regions that future detectors will need to inspect separately.
For that reason the project supports calibrating:

- `log_region` - text log area; this is intended to become `capture.region`
  for the current OCR pipeline.
- `hero_cards_region` - your private card images.
- `board_cards_region` - community card images.
- `stack_region` - chip stack or balance area.

Run the interactive calibration tool from the repository root:

```bash
python tools/calibrate_regions.py
```

By default it captures the leftmost physical monitor, which matches a common
setup where the second monitor sits to the left of the main display, and writes
`config/regions_calibrated.json`. Use `--monitor-index` if you need to force a
specific MSS monitor:

```bash
python tools/calibrate_regions.py --monitor-index 2 --output config/regions_calibrated.json
```

OpenCV will show the screenshot fullscreen on the selected monitor so the OS
window title bar does not offset the displayed image. Add `--windowed` only if
you need a normal debug window. Draw rectangles in this order: log, hero cards,
board cards, stack. Drag a rectangle, press Enter or Space to confirm it, press
`C` to clear the current rectangle, and press `Q` or Esc when you are done. The
tool converts the screenshot-local rectangles into global screen coordinates
using the monitor offset, writes the JSON file, and prints the same JSON to
stdout.

As a first integration step, copy `log_region` from
`config/regions_calibrated.json` into `capture.region` in
`config/default_config.json`. The other regions are loaded by the optional
`RegionsConfig` helper and are reserved for later image-based hero/board/stack
recognition.

The current calibrated boxes are hardcoded in `config/regions_calibrated.json`.
If card OCR misses hero or board cards, rerun `python tools/calibrate_regions.py`
and redraw `hero_cards_region` and `board_cards_region` tightly around the card
faces. While `ocr.debug_card_regions` is enabled, the OCR worker also saves raw
and preprocessed hero/board crops plus OCR text under
`debug_captures/card_regions/`. Use those images to confirm whether a failure is
caused by shifted coordinates or by unreadable card glyphs.

## Tests

The deterministic tests avoid screen capture, EasyOCR, and Treys imports:

```bash
PYTHONPATH=src python -m unittest discover -s tests
```

## Safety behavior

- Low-confidence OCR lines are ignored.
- Duplicate/impossible cards are rejected.
- Unreasonable chip amounts are discarded.
- Animated, too-dark, too-bright, or low-contrast frames are blocked by the
  stable-frame debouncer.
- Equity simulations have a timeout budget and run off the UI thread.
