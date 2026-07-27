import json
import os
import tempfile
from pathlib import Path
from typing import Any

from vandrel_foundry.domain.errors import FoundryError


def write_new_json_evidence(path: Path, value: Any) -> None:
    """Create one evidence snapshot durably without replacing an existing file."""
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, raw_path = tempfile.mkstemp(
            prefix=f".{path.name}-",
            suffix=".tmp",
            dir=path.parent,
        )
        temporary = Path(raw_path)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    except FileExistsError as exc:
        raise FoundryError(f"Provider evidence already exists: {path}") from exc
    except OSError as exc:
        raise FoundryError(f"Could not write provider evidence {path}: {exc}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
