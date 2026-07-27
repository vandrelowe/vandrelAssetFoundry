from enum import StrEnum


class WorkflowState(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    GENERATING = "generating"
    SOURCE_READY = "source_ready"
    DOWNLOADED = "downloaded"
    PROCESSED = "processed"
    STAGED = "staged"
    REVIEW = "review"
    APPROVED = "approved"
    REJECTED = "rejected"
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
    if state is WorkflowState.PROCESSED:
        return ["inspect", "prepare-godot"]
    if state is WorkflowState.STAGED:
        return ["validate-godot"]
    if state is WorkflowState.REVIEW:
        return ["approve", "reject"]
    return []
