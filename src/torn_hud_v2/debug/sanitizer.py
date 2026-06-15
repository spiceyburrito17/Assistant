"""Shared CSV cell sanitization for v2 debug logging."""

from __future__ import annotations

import re
from typing import Any


def sanitize_csv_cell(value: Any) -> str:
    """Convert any value into a single-line CSV-safe string."""

    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:.4f}".rstrip("0").rstrip(".")
    text = str(value)
    text = text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    return re.sub(r"\s+", " ", text).strip()


def join_csv_values(values: tuple[str, ...] | list[str]) -> str:
    if not values:
        return ""
    return "|".join(sanitize_csv_cell(item) for item in values)
