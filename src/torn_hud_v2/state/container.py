"""In-memory current table snapshot container."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..models.messages import TableDeltaMessage
from ..models.snapshot import TableSnapshot
from ..normalization.normalize import normalize_message
from .validator import validate_snapshot


@dataclass
class TableStateContainer:
    """Apply userscript deltas and hold the latest validated snapshot."""

    snapshot: TableSnapshot = field(default_factory=TableSnapshot)

    def apply_message(self, message: TableDeltaMessage) -> tuple[TableSnapshot, str | None]:
        if not message.is_table_delta:
            return self.snapshot, None

        normalized = normalize_message(message, previous=self.snapshot)
        validated, block_reason = validate_snapshot(normalized)
        self.snapshot = validated
        return validated, block_reason
