"""File-backed diagnostics for GUI/no-console launches."""

from __future__ import annotations

import logging
from pathlib import Path

DEBUG_DIR = Path("debug_captures")
RUNTIME_LOG_PATH = DEBUG_DIR / "runtime.log"
STARTUP_LOG_PATH = DEBUG_DIR / "startup.log"

_CONFIGURED = False


def configure_runtime_logging() -> None:
    """Configure logging early enough for detached GUI launches.

    Some desktop launchers detach the GUI process from the terminal. File
    logging is therefore the source of truth for startup and worker diagnostics.
    """

    global _CONFIGURED
    if _CONFIGURED:
        return
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(RUNTIME_LOG_PATH),
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s %(message)s",
        force=True,
    )
    _CONFIGURED = True
    logging.debug("runtime logging configured path=%s", RUNTIME_LOG_PATH)
    write_startup_log("startup logging configured")


def ensure_runtime_logging() -> None:
    if not _CONFIGURED:
        configure_runtime_logging()


def debug_log(message: str, *args: object) -> None:
    ensure_runtime_logging()
    logging.debug(message, *args)


def exception_log(message: str, *args: object) -> None:
    ensure_runtime_logging()
    logging.exception(message, *args)


def write_startup_log(message: str) -> None:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    with STARTUP_LOG_PATH.open("a", encoding="utf-8") as fp:
        fp.write(f"{message}\n")
    logging.debug("startup: %s", message)
