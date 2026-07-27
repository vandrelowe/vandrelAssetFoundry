import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

from pydantic import ValidationError

from vandrel_foundry.domain.errors import (
    AmbiguousSubmissionError,
    DefinitiveSubmissionError,
    DownloadError,
    ProviderRequestError,
)
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

MAX_JSON_RESPONSE_BYTES = 10 * 1024 * 1024
DOWNLOAD_CHUNK_BYTES = 1024 * 1024


class MeshyHttpTransport:
    """Bounded standard-library HTTP transport for the Meshy Text to 3D API."""

    def __init__(
        self,
        api_base: str,
        timeout_seconds: float,
        opener: Callable[..., Any] = urlopen,
        maximum_download_bytes: int = 4_000_000_000,
    ) -> None:
        self.api_base = api_base.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.maximum_download_bytes = maximum_download_bytes
        self._opener = opener
        split = urlsplit(self.api_base)
        if (
            split.scheme != "https"
            or not split.netloc
            or split.username
            or split.password
            or split.query
            or split.fragment
            or split.path not in {"", "/"}
        ):
            raise ValueError("Meshy API base must be a credential-free HTTPS origin")
        if maximum_download_bytes <= 0:
            raise ValueError("Maximum download bytes must be positive")

    def create_text_preview(
        self,
        request: TextTo3DPreviewRequest,
        api_key: str,
    ) -> CreateTaskResponse:
        return self._create_task(request, api_key, "/openapi/v2/text-to-3d")

    def create_text_refine(
        self,
        request: TextTo3DRefineRequest,
        api_key: str,
    ) -> CreateTaskResponse:
        return self._create_task(request, api_key, "/openapi/v2/text-to-3d")

    def create_image_task(
        self,
        request: ImageTo3DRequest,
        api_key: str,
    ) -> CreateTaskResponse:
        return self._create_task(request, api_key, "/openapi/v1/image-to-3d")

    def create_remesh_task(
        self,
        request: RemeshRequest,
        api_key: str,
    ) -> CreateTaskResponse:
        return self._create_task(request, api_key, "/openapi/v1/remesh")

    def create_retexture_task(
        self,
        request: RetextureRequest,
        api_key: str,
    ) -> CreateTaskResponse:
        return self._create_task(request, api_key, "/openapi/v1/retexture")

    def create_rigging_task(
        self,
        request: RiggingRequest,
        api_key: str,
    ) -> CreateTaskResponse:
        return self._create_task(request, api_key, "/openapi/v1/rigging")

    def _create_task(
        self,
        request: (
            TextTo3DPreviewRequest
            | TextTo3DRefineRequest
            | ImageTo3DRequest
            | RemeshRequest
            | RetextureRequest
            | RiggingRequest
        ),
        api_key: str,
        endpoint: str,
    ) -> CreateTaskResponse:
        body = json.dumps(
            request.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        http_request = Request(
            f"{self.api_base}{endpoint}",
            data=body,
            headers=self._headers(api_key),
            method="POST",
        )
        try:
            payload = self._open_json(http_request)
            return CreateTaskResponse.model_validate(payload)
        except HTTPError as exc:
            message = self._http_error_message(exc)
            if 400 <= exc.code < 500:
                raise DefinitiveSubmissionError(message) from exc
            raise AmbiguousSubmissionError(message) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise AmbiguousSubmissionError(f"Meshy submission transport failed: {exc}") from exc
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            raise AmbiguousSubmissionError(
                f"Meshy submission returned an invalid response: {exc}"
            ) from exc

    def retrieve_text_task(
        self,
        provider_task_id: str,
        api_key: str,
    ) -> TextTo3DTaskResponse:
        payload = self._retrieve_task(
            provider_task_id,
            api_key,
            "/openapi/v2/text-to-3d",
        )
        try:
            return TextTo3DTaskResponse.model_validate(payload)
        except ValidationError as exc:
            raise ProviderRequestError("Meshy returned an invalid task response.") from exc

    def retrieve_image_task(
        self,
        provider_task_id: str,
        api_key: str,
    ) -> ImageTo3DTaskResponse:
        payload = self._retrieve_task(
            provider_task_id,
            api_key,
            "/openapi/v1/image-to-3d",
        )
        try:
            return ImageTo3DTaskResponse.model_validate(payload)
        except ValidationError as exc:
            raise ProviderRequestError("Meshy returned an invalid task response.") from exc

    def retrieve_remesh_task(
        self,
        provider_task_id: str,
        api_key: str,
    ) -> RemeshTaskResponse:
        payload = self._retrieve_task(provider_task_id, api_key, "/openapi/v1/remesh")
        try:
            return RemeshTaskResponse.model_validate(payload)
        except ValidationError as exc:
            raise ProviderRequestError("Meshy returned an invalid task response.") from exc

    def retrieve_retexture_task(
        self,
        provider_task_id: str,
        api_key: str,
    ) -> RetextureTaskResponse:
        payload = self._retrieve_task(provider_task_id, api_key, "/openapi/v1/retexture")
        try:
            return RetextureTaskResponse.model_validate(payload)
        except ValidationError as exc:
            raise ProviderRequestError("Meshy returned an invalid retexture response.") from exc

    def retrieve_rigging_task(
        self,
        provider_task_id: str,
        api_key: str,
    ) -> RiggingTaskResponse:
        payload = self._retrieve_task(provider_task_id, api_key, "/openapi/v1/rigging")
        try:
            return RiggingTaskResponse.model_validate(payload)
        except ValidationError as exc:
            raise ProviderRequestError("Meshy returned an invalid rigging response.") from exc

    def _retrieve_task(
        self,
        provider_task_id: str,
        api_key: str,
        endpoint: str,
    ) -> Any:
        task_id = quote(provider_task_id, safe="")
        request = Request(
            f"{self.api_base}{endpoint}/{task_id}",
            headers=self._headers(api_key),
            method="GET",
        )
        try:
            return self._open_json(request)
        except HTTPError as exc:
            raise ProviderRequestError(self._http_error_message(exc)) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ProviderRequestError(f"Meshy task retrieval failed: {exc}") from exc
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            raise ProviderRequestError(f"Meshy returned an invalid task response: {exc}") from exc

    def download_file(self, url: str, destination: Path) -> int:
        split = urlsplit(url)
        if split.scheme != "https" or not split.netloc or split.username or split.password:
            raise DownloadError(
                "Provider download URL must be an absolute credential-free HTTPS URL"
            )
        request = Request(url, method="GET")
        created_destination = False
        completed = False
        try:
            with self._opener(request, timeout=self.timeout_seconds) as response:
                self._require_https_response(response)
                status = getattr(response, "status", 200)
                if not 200 <= status < 300:
                    raise DownloadError(f"Provider download returned HTTP {status}")
                with destination.open("xb") as stream:
                    created_destination = True
                    total = 0
                    while True:
                        chunk = response.read(DOWNLOAD_CHUNK_BYTES)
                        if not chunk:
                            break
                        stream.write(chunk)
                        total += len(chunk)
                        if total > self.maximum_download_bytes:
                            raise DownloadError(
                                "Provider download exceeded configured maximum size"
                            )
                    stream.flush()
                    os.fsync(stream.fileno())
            if total == 0:
                raise DownloadError("Provider download was empty")
            completed = True
            return total
        except HTTPError as exc:
            raise DownloadError(self._http_error_message(exc)) from exc
        except FileExistsError as exc:
            raise DownloadError(f"Download destination already exists: {destination}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise DownloadError(f"Provider download failed: {exc}") from exc
        finally:
            if created_destination and not completed:
                destination.unlink(missing_ok=True)

    def _open_json(self, request: Request) -> Any:
        with self._opener(request, timeout=self.timeout_seconds) as response:
            self._require_https_response(response)
            raw = response.read(MAX_JSON_RESPONSE_BYTES + 1)
            if len(raw) > MAX_JSON_RESPONSE_BYTES:
                raise ValueError("JSON response exceeded size limit")
            return json.loads(raw.decode("utf-8"))

    @staticmethod
    def _require_https_response(response: Any) -> None:
        geturl = getattr(response, "geturl", None)
        if callable(geturl):
            final_url = str(geturl())
            if urlsplit(final_url).scheme != "https":
                raise ValueError("Provider redirected to a non-HTTPS URL")

    @staticmethod
    def _headers(api_key: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    @staticmethod
    def _http_error_message(exc: HTTPError) -> str:
        message = f"Meshy returned HTTP {exc.code}"
        try:
            payload = json.loads(exc.read(MAX_JSON_RESPONSE_BYTES).decode("utf-8"))
            detail = payload.get("message") if isinstance(payload, dict) else None
            if isinstance(detail, str) and detail.strip():
                message = f"{message}: {detail.strip()}"
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            pass
        return message
