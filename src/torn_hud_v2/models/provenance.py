"""Field-level source metadata for normalized table state."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Generic, TypeVar

T = TypeVar("T")


class FieldSource(str, Enum):
    DOM = "dom"
    OCR = "ocr"
    INFERRED = "inferred"


@dataclass(frozen=True)
class SourcedValue(Generic[T]):
    raw: str | None
    parsed: T | None
    source: FieldSource = FieldSource.DOM
