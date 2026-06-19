"""CLI entrypoint for torn-hud-v2."""

from __future__ import annotations

import argparse
from pathlib import Path

from .app import HudApplication
from .config import HudConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Torn poker HUD v2 (DOM-first).")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/v2_default.json"),
        help="Path to v2 JSON config.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = HudConfig.load(args.config if args.config.exists() else None)
    app = HudApplication(config)
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
