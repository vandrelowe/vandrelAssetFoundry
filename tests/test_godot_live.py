import json
import os
import struct
from pathlib import Path

import pytest

from vandrel_foundry.domain.states import WorkflowState
from vandrel_foundry.services.add_source import add_external_glb
from vandrel_foundry.services.create_asset import create_asset
from vandrel_foundry.services.inspect_assets import initialize_workspace
from vandrel_foundry.services.inspect_glb import inspect_processed_glb
from vandrel_foundry.services.plan_release import plan_release
from vandrel_foundry.services.process_asset import process_passthrough
from vandrel_foundry.services.review_asset import approve_asset
from vandrel_foundry.services.stage_godot import prepare_godot_sandbox
from vandrel_foundry.services.validate_godot import validate_godot_sandbox
from vandrel_foundry.storage.manifests import ManifestRepository


@pytest.mark.live_tool
def test_real_godot_import_is_opt_in(config, lanes, prompt: Path) -> None:
    executable_value = os.environ.get("VANDREL_FOUNDRY_TEST_GODOT")
    if not executable_value:
        pytest.skip("Set VANDREL_FOUNDRY_TEST_GODOT for the opt-in Godot smoke test.")
    executable = Path(executable_value)
    if not executable.is_file():
        pytest.skip(f"Configured Godot executable does not exist: {executable}")
    config.tools.godot_executable = executable

    initialize_workspace(config.foundry.workspace_root)
    create_asset(
        config,
        lanes,
        "godot_smoke_asset",
        "static_prop",
        "Godot Smoke Asset",
        prompt,
    )
    model = prompt.parent / "external-smoke.glb"
    document = json.dumps({"asset": {"version": "2.0"}, "materials": [{}]}).encode("utf-8")
    document += b" " * (-len(document) % 4)
    content = (
        struct.pack("<4sII", b"glTF", 2, 20 + len(document))
        + struct.pack("<II", len(document), 0x4E4F534A)
        + document
    )
    model.write_bytes(content)
    repository = ManifestRepository(config.foundry.workspace_root)

    add_external_glb(config, "godot_smoke_asset", model)
    process_passthrough(config, "godot_smoke_asset")
    inspect_processed_glb(config, lanes, "godot_smoke_asset")
    prepare_godot_sandbox(config, lanes, "godot_smoke_asset")
    result = validate_godot_sandbox(config, "godot_smoke_asset")
    approve_asset(config, "godot_smoke_asset", reviewer="Opt-in smoke test")
    release_plan = plan_release(config, lanes, "godot_smoke_asset")
    saved = repository.load("godot_smoke_asset")
    assert result.return_code == 0
    assert not result.timed_out
    assert not result.output_limited
    assert saved.workflow.state is WorkflowState.APPROVED
    assert release_plan.release_revision == 1
    assert not release_plan.destination.exists()
