"""The one thing CV emits: one event per unit added or removed (spec §8)."""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class Event:
    event_id: str
    cart_id: str
    type: str  # "added" | "removed"
    product_id: str | None
    confidence: float
    method: str  # "local" | "cloud" | "memory" | "none"
    label: str
    cameras: list[int] = field(default_factory=list)
    crops: list[str] = field(default_factory=list)
    ts: str = ""
    resolves_event_id: str | None = None  # removal of an unrecognized item: clears its "Is this…?" card

    @classmethod
    def new(cls, **fields) -> Event:
        return cls(event_id=str(uuid.uuid4()), ts=utc_now_iso(), **fields)

    def to_json(self) -> dict:
        return asdict(self)
