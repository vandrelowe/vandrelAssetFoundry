from pathlib import Path, PurePosixPath

from pydantic import GetCoreSchemaHandler, GetJsonSchemaHandler
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import core_schema


class RelativeManifestPath(str):
    """A portable, workspace-relative path stored with forward slashes."""

    @classmethod
    def validate(cls, value: str) -> "RelativeManifestPath":
        if not isinstance(value, str) or not value:
            raise ValueError("path must be a non-empty string")
        if "\\" in value:
            raise ValueError("manifest paths must use forward slashes")
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or "." in path.parts:
            raise ValueError("manifest paths must be relative and may not traverse")
        if ":" in path.parts[0]:
            raise ValueError("manifest paths may not contain a drive")
        return cls(str(path))

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: object, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        return core_schema.no_info_after_validator_function(cls.validate, core_schema.str_schema())

    @classmethod
    def __get_pydantic_json_schema__(
        cls, schema: core_schema.CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        result = handler(schema)
        result.update(
            {
                "description": "Forward-slash workspace-relative path without traversal",
                "pattern": r"^(?!/)(?![A-Za-z]:)(?!.*(?:^|/)\.\.(?:/|$))(?!.*\\).+$",
            }
        )
        return result


def contained_path(root: Path, relative: str) -> Path:
    safe = RelativeManifestPath.validate(relative)
    candidate = (root / Path(*PurePosixPath(safe).parts)).resolve()
    resolved_root = root.resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise ValueError("path escapes workspace")
    return candidate
