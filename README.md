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
