import hashlib
import json
import os
from pathlib import Path

from PIL import Image

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import Artifact, Processor, utc_now
from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.services.validate_godot import ProcessRunner, run_bounded_process
from vandrel_foundry.storage.manifests import ManifestRepository
from vandrel_foundry.storage.paths import RelativeManifestPath, contained_path


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def render_multi_angle_preview(
    config: FoundryConfig, asset_id: str, runner: ProcessRunner | None = None
) -> list[Artifact]:
    repository = ManifestRepository(config.foundry.workspace_root)
    manifest = repository.load(asset_id)
    if manifest.workflow.state not in {
        WorkflowState.PROCESSED,
        WorkflowState.REVIEW,
        WorkflowState.APPROVED,
    }:
        raise FoundryError(f"Multi-angle rendering requires processed or later state: {asset_id}")
    executable = config.tools.blender_executable
    if executable is None or not executable.is_absolute() or not executable.is_file():
        raise FoundryError("Configure tools.blender_executable as an existing absolute file.")
    sources = [item for item in manifest.artifacts if item.role == "processed_model"]
    if not sources:
        raise FoundryError(f"No processed GLB exists for preview rendering: {asset_id}")
    source = sources[-1]
    asset_root = config.foundry.workspace_root / "assets" / asset_id
    source_path = contained_path(asset_root, source.path)
    if _hash_file(source_path) != (source.sha256, source.size_bytes):
        raise FoundryError(f"Preview input artifact changed: {source.artifact_id}")
    number = sum(item.role == "multi_angle_preview" for item in manifest.artifacts) // 4 + 1
    directory = RelativeManifestPath(f"preview/multi-angle-{number:03d}")
    output_dir = contained_path(asset_root, directory)
    report_relative = RelativeManifestPath(f"reports/multi-angle-preview-{number:03d}.json")
    log_relative = RelativeManifestPath(f"reports/multi-angle-preview-{number:03d}.log")
    report_path = contained_path(asset_root, report_relative)
    log_path = contained_path(asset_root, log_relative)
    output_dir.mkdir(parents=True, exist_ok=False)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    script = Path(__file__).parents[1] / "blender" / "render_multi_angle_preview.py"
    arguments = [
        str(executable),
        "--background",
        "--factory-startup",
        "--disable-autoexec",
        "--python-exit-code",
        "1",
        "--python",
        str(script),
        "--",
        str(source_path),
        str(output_dir),
        str(report_path),
    ]
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper()
        in {
            "APPDATA",
            "HOME",
            "LOCALAPPDATA",
            "PATH",
            "SYSTEMROOT",
            "TEMP",
            "TMP",
            "USERPROFILE",
            "WINDIR",
        }
    }
    try:
        result = (runner or run_bounded_process)(
            arguments,
            asset_root,
            environment,
            config.tools.blender_timeout_seconds,
            config.tools.maximum_output_bytes,
        )
        if result.return_code != 0 or result.timed_out or result.output_limited:
            raise FoundryError("Bounded Blender multi-angle rendering failed.")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        version = str(report["blender_version"])
        image_paths = [output_dir / name for name in report["views"]]
        if len(image_paths) != 4 or any(
            path.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n" for path in image_paths
        ):
            raise FoundryError("Multi-angle output set is incomplete or invalid.")
        rendered_views = [_rendered_occupancy(path) for path in image_paths]
        camera_views = report.get("camera_views")
        if not isinstance(camera_views, list) or len(camera_views) != 4:
            raise FoundryError("Multi-angle framing report is incomplete.")
        for camera_view, rendered in zip(camera_views, rendered_views, strict=True):
            if not camera_view.get("initial_geometry_bounds_contained") or not rendered["no_crop"]:
                raise FoundryError("Multi-angle framing could not prove complete geometry.")
        report["rendered_views"] = rendered_views
        report["all_views_no_crop"] = True
        report["all_views_useful_occupancy"] = all(
            item["useful_occupancy"] for item in rendered_views
        )
        report_path.write_text(
            json.dumps(report, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        log_path.write_text(
            f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}\n",
            encoding="utf-8",
            newline="\n",
        )
        processor = Processor(name="blender_multi_angle_preview", version=f"1+blender-{version}")
        artifacts = []
        for path in image_paths:
            digest, size = _hash_file(path)
            artifacts.append(
                Artifact(
                    artifact_id=f"multi_angle_preview_{number:03d}_{path.stem}",
                    role="multi_angle_preview",
                    stage="review",
                    format="png",
                    path=RelativeManifestPath(f"{directory}/{path.name}"),
                    sha256=digest,
                    size_bytes=size,
                    derived_from=[source.artifact_id],
                    processor=processor,
                )
            )
        for artifact_id, role, path, relative, derivations in (
            (
                f"multi_angle_preview_report_{number:03d}",
                "multi_angle_preview_report",
                report_path,
                report_relative,
                [source.artifact_id] + [item.artifact_id for item in artifacts],
            ),
            (
                f"multi_angle_preview_log_{number:03d}",
                "multi_angle_preview_log",
                log_path,
                log_relative,
                [source.artifact_id] + [item.artifact_id for item in artifacts],
            ),
        ):
            digest, size = _hash_file(path)
            artifacts.append(
                Artifact(
                    artifact_id=artifact_id,
                    role=role,
                    stage="review",
                    format=path.suffix.lstrip("."),
                    path=relative,
                    sha256=digest,
                    size_bytes=size,
                    derived_from=derivations,
                    processor=processor,
                )
            )
    except BaseException:
        if output_dir.exists():
            for child in output_dir.iterdir():
                child.unlink(missing_ok=True)
            output_dir.rmdir()
        report_path.unlink(missing_ok=True)
        log_path.unlink(missing_ok=True)
        raise
    manifest.artifacts.extend(artifacts)
    manifest.revision += 1
    manifest.asset.updated_at = utc_now()
    repository.save(
        manifest, "preview.multi_angle_rendered", expected_revision=manifest.revision - 1
    )
    return artifacts


def _rendered_occupancy(path: Path) -> dict[str, object]:
    with Image.open(path) as opened:
        alpha = opened.convert("RGBA").getchannel("A")
        width, height = alpha.size
        bounds = alpha.getbbox()
        foreground_pixels = sum(alpha.histogram()[1:])
    if bounds is None or foreground_pixels == 0:
        raise FoundryError(f"Preview has no rendered foreground: {path.name}")
    left, top, right, bottom = bounds
    margins = {
        "left": left,
        "right": width - right,
        "top": top,
        "bottom": height - bottom,
    }
    bbox_width = right - left
    bbox_height = bottom - top
    no_crop = all(value > 0 for value in margins.values())
    return {
        "output": path.name,
        "alpha_bounding_box_pixels": [left, top, right, bottom],
        "alpha_bounding_box_fraction": (bbox_width * bbox_height) / (width * height),
        "width_occupancy_fraction": bbox_width / width,
        "height_occupancy_fraction": bbox_height / height,
        "nonzero_alpha_pixel_fraction": foreground_pixels / (width * height),
        "crop_margin_pixels": margins,
        "no_crop": no_crop,
        "useful_occupancy": max(bbox_width / width, bbox_height / height) >= 0.70,
    }
