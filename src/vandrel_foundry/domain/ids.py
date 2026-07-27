import re

from vandrel_foundry.domain.errors import FoundryError

ASSET_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_]{2,63}$")


def validate_asset_id(value: str) -> str:
    if not ASSET_ID_PATTERN.fullmatch(value):
        raise FoundryError(
            "Asset ID must be 3-64 lowercase ASCII letters, digits, or underscores "
            "and must begin with a letter or digit."
        )
    return value
