import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def append_event(path: Path, event_type: str, asset_id: str, revision: int) -> None:
    event: dict[str, Any] = {
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "event": event_type,
        "asset_id": asset_id,
        "revision": revision,
    }
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(event, separators=(",", ":")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
