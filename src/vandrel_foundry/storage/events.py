import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def build_event_bytes(event_type: str, asset_id: str, revision: int) -> bytes:
    """Build the exact event record before any durable save mutation."""
    event: dict[str, Any] = {
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "event": event_type,
        "asset_id": asset_id,
        "revision": revision,
    }
    return (json.dumps(event, separators=(",", ":")) + "\n").encode("utf-8")


def append_event_bytes(path: Path, event_bytes: bytes) -> None:
    value = event_bytes.decode("utf-8")
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())


def append_event(path: Path, event_type: str, asset_id: str, revision: int) -> None:
    append_event_bytes(path, build_event_bytes(event_type, asset_id, revision))
