class FoundryError(Exception):
    """Base error suitable for display to a CLI user."""


class ConfigurationError(FoundryError):
    pass


class AssetExistsError(FoundryError):
    pass


class AssetNotFoundError(FoundryError):
    pass


class UnknownLaneError(FoundryError):
    pass


class LockError(FoundryError):
    pass
