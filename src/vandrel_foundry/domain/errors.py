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


class ProviderSubmissionError(FoundryError):
    """Base error raised by a provider transport during task creation."""


class DefinitiveSubmissionError(ProviderSubmissionError):
    """The provider explicitly rejected the request before accepting work."""


class AmbiguousSubmissionError(ProviderSubmissionError):
    """The request may have created paid work, but no durable task ID is known."""


class ProviderRequestError(FoundryError):
    """A non-submission provider request failed safely."""


class DownloadError(FoundryError):
    """A provider artifact could not be downloaded or promoted safely."""
