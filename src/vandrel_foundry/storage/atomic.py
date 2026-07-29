import json
import os
import tempfile
from pathlib import Path
from typing import Any


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def write_bytes_temp(directory: Path, value: bytes, prefix: str = ".manifest-") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    descriptor, raw_path = tempfile.mkstemp(prefix=prefix, suffix=".tmp", dir=directory)
    path = Path(raw_path)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path


def write_json_temp(directory: Path, value: Any) -> Path:
    return write_bytes_temp(directory, json_bytes(value))
