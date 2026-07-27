import io
import json
from pathlib import Path
from typing import Self
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from vandrel_foundry.domain.errors import (
    AmbiguousSubmissionError,
    DefinitiveSubmissionError,
    DownloadError,
)
from vandrel_foundry.providers.meshy.http import MeshyHttpTransport
from vandrel_foundry.providers.meshy.models import (
    ImageTo3DRequest,
    RemeshRequest,
    RetextureRequest,
    RiggingRequest,
    TextTo3DPreviewRequest,
    TextTo3DRefineRequest,
)


class FakeResponse:
    def __init__(self, content: bytes, status: int = 200) -> None:
        self.content = io.BytesIO(content)
        self.status = status

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self.content.read(size)


def test_create_preview_uses_bounded_authenticated_post() -> None:
    observed: dict[str, object] = {}

    def opener(request: Request, timeout: float):
        observed["request"] = request
        observed["timeout"] = timeout
        return FakeResponse(json.dumps({"result": "opaque-id"}).encode())

    transport = MeshyHttpTransport("https://api.meshy.ai", 12.5, opener)
    response = transport.create_text_preview(
        TextTo3DPreviewRequest(prompt="stone knife"),
        "secret-key",
    )
    request = observed["request"]
    assert isinstance(request, Request)
    assert response.result == "opaque-id"
    assert request.full_url == "https://api.meshy.ai/openapi/v2/text-to-3d"
    assert request.method == "POST"
    assert request.get_header("Authorization") == "Bearer secret-key"
    assert json.loads(request.data or b"{}")["mode"] == "preview"
    assert observed["timeout"] == 12.5


def test_create_refine_uses_same_endpoint_with_preview_task_id() -> None:
    observed: dict[str, Request] = {}

    def opener(request: Request, timeout: float):
        observed["request"] = request
        return FakeResponse(b'{"result":"refine-id"}')

    transport = MeshyHttpTransport("https://api.meshy.ai", 10, opener)
    response = transport.create_text_refine(
        TextTo3DRefineRequest(preview_task_id="preview-id"),
        "secret",
    )
    payload = json.loads(observed["request"].data or b"{}")
    assert response.result == "refine-id"
    assert payload == {
        "mode": "refine",
        "preview_task_id": "preview-id",
        "enable_pbr": True,
        "target_formats": ["glb"],
    }


def test_create_and_retrieve_image_task_use_v1_image_endpoint() -> None:
    observed: list[Request] = []

    def opener(request: Request, timeout: float):
        observed.append(request)
        if request.method == "POST":
            return FakeResponse(b'{"result":"image-id"}')
        return FakeResponse(
            b'{"id":"image-id","status":"SUCCEEDED","progress":100,'
            b'"model_urls":{"glb":"https://assets.meshy.ai/image.glb"}}'
        )

    transport = MeshyHttpTransport("https://api.meshy.ai", 10, opener)
    created = transport.create_image_task(
        ImageTo3DRequest(image_url="data:image/png;base64,eA=="),
        "secret",
    )
    retrieved = transport.retrieve_image_task(created.result, "secret")
    assert observed[0].full_url == "https://api.meshy.ai/openapi/v1/image-to-3d"
    assert json.loads(observed[0].data or b"{}")["image_url"].startswith("data:image/png")
    assert observed[1].full_url == "https://api.meshy.ai/openapi/v1/image-to-3d/image-id"
    assert retrieved.status.value == "SUCCEEDED"


def test_create_remesh_uses_v1_remesh_endpoint() -> None:
    observed: dict[str, Request] = {}

    def opener(request: Request, timeout: float):
        observed["request"] = request
        return FakeResponse(b'{"result":"remesh-id"}')

    transport = MeshyHttpTransport("https://api.meshy.ai", 10, opener)
    created = transport.create_remesh_task(
        RemeshRequest(input_task_id="source-id", target_polycount=2500),
        "secret",
    )
    request = observed["request"]
    assert created.result == "remesh-id"
    assert request.full_url == "https://api.meshy.ai/openapi/v1/remesh"
    assert json.loads(request.data or b"{}")["target_polycount"] == 2500


def test_retexture_and_rigging_use_documented_v1_endpoints() -> None:
    observed: list[Request] = []

    def opener(request: Request, timeout: float):
        observed.append(request)
        return FakeResponse(b'{"result":"task-id"}')

    transport = MeshyHttpTransport("https://api.meshy.ai", 10, opener)
    transport.create_retexture_task(
        RetextureRequest(
            model_url="data:application/octet-stream;base64,eA==",
            text_style_prompt="painted traveler",
        ),
        "secret",
    )
    transport.create_rigging_task(
        RiggingRequest(input_task_id="retexture-id", height_meters=1.8),
        "secret",
    )

    retexture = json.loads(observed[0].data or b"{}")
    rigging = json.loads(observed[1].data or b"{}")
    assert observed[0].full_url == "https://api.meshy.ai/openapi/v1/retexture"
    assert retexture["enable_original_uv"] is True
    assert retexture["remove_lighting"] is True
    assert retexture["target_formats"] == ["glb"]
    assert observed[1].full_url == "https://api.meshy.ai/openapi/v1/rigging"
    assert rigging == {"input_task_id": "retexture-id", "height_meters": 1.8}


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (400, DefinitiveSubmissionError),
        (402, DefinitiveSubmissionError),
        (429, DefinitiveSubmissionError),
        (500, AmbiguousSubmissionError),
    ],
)
def test_submission_http_error_classification(status: int, expected: type[Exception]) -> None:
    def opener(request: Request, timeout: float):
        raise HTTPError(
            request.full_url,
            status,
            "error",
            {},
            io.BytesIO(b'{"message":"provider error"}'),
        )

    transport = MeshyHttpTransport("https://api.meshy.ai", 10, opener)
    with pytest.raises(expected, match=f"HTTP {status}"):
        transport.create_text_preview(TextTo3DPreviewRequest(prompt="x"), "secret")


def test_download_rejects_unsafe_url(tmp_path: Path) -> None:
    transport = MeshyHttpTransport("https://api.meshy.ai", 10)
    with pytest.raises(DownloadError, match="HTTPS"):
        transport.download_file("http://assets.meshy.ai/model.glb", tmp_path / "model.part")


@pytest.mark.parametrize(
    "api_base",
    [
        "http://api.meshy.ai",
        "https://user:secret@api.meshy.ai",
        "https://api.meshy.ai/openapi",
        "https://api.meshy.ai?token=secret",
    ],
)
def test_api_base_must_be_clean_https_origin(api_base: str) -> None:
    with pytest.raises(ValueError, match="HTTPS origin"):
        MeshyHttpTransport(api_base, 10)


def test_download_streams_to_new_destination(tmp_path: Path) -> None:
    def opener(request: Request, timeout: float):
        return FakeResponse(b"model-bytes")

    transport = MeshyHttpTransport("https://api.meshy.ai", 10, opener)
    destination = tmp_path / "model.part"
    assert (
        transport.download_file("https://assets.meshy.ai/model.glb?Signature=x", destination) == 11
    )
    assert destination.read_bytes() == b"model-bytes"
    with pytest.raises(DownloadError, match="already exists"):
        transport.download_file("https://assets.meshy.ai/model.glb", destination)
    assert destination.read_bytes() == b"model-bytes"


def test_failed_download_removes_only_transport_created_partial(tmp_path: Path) -> None:
    class FailingResponse(FakeResponse):
        def read(self, size: int = -1) -> bytes:
            if self.content.tell() > 0:
                raise OSError("connection lost")
            return self.content.read(4)

    def opener(request: Request, timeout: float):
        return FailingResponse(b"partial-data")

    transport = MeshyHttpTransport("https://api.meshy.ai", 10, opener)
    destination = tmp_path / "model.part"
    with pytest.raises(DownloadError, match="connection lost"):
        transport.download_file("https://assets.meshy.ai/model.glb", destination)
    assert not destination.exists()


def test_download_size_limit_removes_partial(tmp_path: Path) -> None:
    def opener(request: Request, timeout: float):
        return FakeResponse(b"too-large")

    transport = MeshyHttpTransport(
        "https://api.meshy.ai",
        10,
        opener,
        maximum_download_bytes=4,
    )
    destination = tmp_path / "model.part"
    with pytest.raises(DownloadError, match="maximum size"):
        transport.download_file("https://assets.meshy.ai/model.glb", destination)
    assert not destination.exists()
