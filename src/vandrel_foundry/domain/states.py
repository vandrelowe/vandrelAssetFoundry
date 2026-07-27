from enum import StrEnum


class WorkflowState(StrEnum):
    DRAFT = "draft"


def next_actions(state: WorkflowState) -> list[str]:
    return ["submit"] if state is WorkflowState.DRAFT else []
