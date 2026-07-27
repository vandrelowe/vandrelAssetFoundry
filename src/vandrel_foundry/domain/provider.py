from enum import StrEnum


class ProviderTaskStatus(StrEnum):
    """Foundry-local and provider-reported task states."""

    READY = "READY"
    SUBMITTING = "SUBMITTING"
    SUBMISSION_FAILED = "SUBMISSION_FAILED"
    AMBIGUOUS = "AMBIGUOUS"
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


TERMINAL_PROVIDER_STATUSES = frozenset(
    {
        ProviderTaskStatus.SUBMISSION_FAILED,
        ProviderTaskStatus.AMBIGUOUS,
        ProviderTaskStatus.SUCCEEDED,
        ProviderTaskStatus.FAILED,
        ProviderTaskStatus.CANCELED,
    }
)
