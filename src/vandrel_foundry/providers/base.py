from pathlib import Path
from typing import Protocol

from vandrel_foundry.providers.meshy.models import (
    CreateTaskResponse,
    ImageTo3DRequest,
    ImageTo3DTaskResponse,
    RemeshRequest,
    RemeshTaskResponse,
    RetextureRequest,
    RetextureTaskResponse,
    RiggingRequest,
    RiggingTaskResponse,
    TextTo3DPreviewRequest,
    TextTo3DRefineRequest,
    TextTo3DTaskResponse,
)


class TextPreviewTransport(Protocol):
    """Transport boundary for one paid Text to 3D preview submission."""

    def create_text_preview(
        self,
        request: TextTo3DPreviewRequest,
        api_key: str,
    ) -> CreateTaskResponse: ...

    def create_text_refine(
        self,
        request: TextTo3DRefineRequest,
        api_key: str,
    ) -> CreateTaskResponse: ...

    def create_image_task(
        self,
        request: ImageTo3DRequest,
        api_key: str,
    ) -> CreateTaskResponse: ...

    def create_remesh_task(
        self,
        request: RemeshRequest,
        api_key: str,
    ) -> CreateTaskResponse: ...

    def create_retexture_task(
        self,
        request: RetextureRequest,
        api_key: str,
    ) -> CreateTaskResponse: ...

    def create_rigging_task(
        self,
        request: RiggingRequest,
        api_key: str,
    ) -> CreateTaskResponse: ...

    def retrieve_text_task(
        self,
        provider_task_id: str,
        api_key: str,
    ) -> TextTo3DTaskResponse: ...

    def retrieve_image_task(
        self,
        provider_task_id: str,
        api_key: str,
    ) -> ImageTo3DTaskResponse: ...

    def retrieve_remesh_task(
        self,
        provider_task_id: str,
        api_key: str,
    ) -> RemeshTaskResponse: ...

    def retrieve_retexture_task(
        self,
        provider_task_id: str,
        api_key: str,
    ) -> RetextureTaskResponse: ...

    def retrieve_rigging_task(
        self,
        provider_task_id: str,
        api_key: str,
    ) -> RiggingTaskResponse: ...

    def download_file(self, url: str, destination: Path) -> int: ...
