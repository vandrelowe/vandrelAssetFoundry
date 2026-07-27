from enum import StrEnum


class WorkflowState(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    GENERATING = "generating"
    SOURCE_READY = "source_ready"
    DOWNLOADED = "downloaded"
    PROCESSED = "processed"
    BLOCKED = "blocked"


def next_actions(state: WorkflowState) -> list[str]:
    if state is WorkflowState.DRAFT:
        return ["submit"]
    if state in {WorkflowState.SUBMITTED, WorkflowState.GENERATING}:
        return ["poll"]
    if state is WorkflowState.SOURCE_READY:
        return ["download"]
    if state is WorkflowState.DOWNLOADED:
        return ["select-output", "process"]
    return []
