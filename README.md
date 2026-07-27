# Vandrel Asset Foundry

Vandrel Asset Foundry is a standalone, manifest-first Python companion tool for
turning candidate 3D assets into traceable, reviewable releases for Vandrel.
Phase 1 provides local configuration, workspace creation, draft manifests,
atomic storage, event history, and inspection. Phase 2 adds a guarded Meshy
Text-to-3D and Image-to-3D lifecycles with redacted evidence, polling,
recovery, and checksummed source downloads.

It is not the Vandrel game, a mod manager, or an asset database. It does not
invoke Blender or Godot and never writes into the Vandrel repository.

## Windows setup

Requires Python 3.11 or newer.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item foundry.example.toml foundry.toml
```

Edit `foundry.toml` for the machine. Keep `vandrel.write_enabled = false`. The
real file is ignored because machine-specific paths do not belong in source
control. The CLI also accepts `--config <path>` on every command; this is
especially useful for isolated tests.

## Commands

```powershell
foundry init
foundry doctor
foundry lanes
foundry create --id stone_knife_001 --lane static_prop `
  --display-name "Stone Knife" --prompt-file .\prompts\stone_knife.txt
foundry list
foundry show stone_knife_001
foundry status stone_knife_001
```

`init` is safe to repeat and never creates asset records. `create` validates all
inputs before creating an asset workspace, copies the prompt to
`input/prompt.txt`, and creates a draft manifest plus an event log. `status`
reports the current workflow and valid next actions.

Phase 2 adds guarded Meshy commands:

```powershell
# This is a paid network action and requires the explicit confirmation flag.
foundry submit stone_knife_001 --confirm-spend

# These make bounded read/download requests for an already recorded task.
foundry poll stone_knife_001
foundry download stone_knife_001

# Choose a downloaded generation, create a distinct pass-through artifact,
# then inspect GLB structure and the lane triangle budget.
foundry select-output stone_knife_001 --task meshy_preview_001
foundry process stone_knife_001
foundry inspect stone_knife_001

# Optional paid provider remesh; defaults to the lane target.
foundry remesh stone_knife_001 --confirm-spend

# After a preview succeeds, submit the paid texture/refine stage.
foundry refine stone_knife_001 --from meshy_preview_001 --confirm-spend

# Image-to-3D copies the input under the asset before the paid submission.
foundry add-reference stone_knife_001 --image .\references\knife.png
foundry submit-image stone_knife_001 --confirm-spend
foundry poll stone_knife_001
foundry download stone_knife_001
```

If a submission times out after it may have reached Meshy, Foundry marks it
ambiguous and refuses to retry automatically. After checking the Meshy
dashboard, reconcile it explicitly:

```powershell
# Bind the discovered provider task and continue polling.
foundry reconcile stone_knife_001 --task meshy_preview_001 `
  --provider-task-id <provider-task-id>

# Or confirm that no provider task was created, allowing a new explicit submit.
foundry reconcile stone_knife_001 --task meshy_preview_001 `
  --confirm-not-created
```

The API key is read from the environment-variable name configured in
`foundry.toml` (normally `MESHY_API_KEY`). It is never written to the manifest,
provider evidence, event log, or terminal output.

## Repository and workspace boundaries

- This repository contains Python source, schemas, tests, and documentation.
- The configured Foundry workspace contains active candidate assets and stays
  outside Git.
- `C:\dev\VandrelAssetLibrary` will eventually contain approved immutable
  releases and use Git LFS; the current implementation does not write there.
- `C:\dev\Vandrel` is reference-only. `doctor` may check for `project.godot`;
  Foundry refuses configurations that enable writes.
- A future mod manager owns gameplay metadata, dependencies, overrides, and load
  order.

Never commit active candidate assets, downloaded models, `.env`, API keys, or a
real `foundry.toml`. This source repository does not initialize Git LFS.

## Development

```powershell
ruff format --check .
ruff check .
pytest
```

The checked-in JSON Schema is generated from the Pydantic manifest model and is
verified by tests.

GitHub Actions runs formatting, lint, and the complete test suite on Python
3.11 and 3.12 for every pull request and push to `main`.

AI assistants and contributors must begin with [GOVERNANCE.md](GOVERNANCE.md)
and [AI_RULES.md](AI_RULES.md). The governing read order, current ownership map,
and subsystem contracts live under `docs/`. These rules preserve compatibility
with Vandrel while keeping sibling repositories read-only and preventing
Foundry from taking ownership of runtime or gameplay decisions.

## Current roadmap

The implemented Phase 2 slice covers Meshy Text-to-3D preview/refine and
Image-to-3D submission, one-shot polling, ambiguous-submission reconciliation,
and GLB plus preview-thumbnail download. The first Phase 3 slice adds explicit
output selection, immutable pass-through processing, GLB 2.0 structural
inspection, and triangle/material reporting against lane policy. Provider
remesh and deeper technical checks remain Phase 3 work. Blender processing,
Godot staging, approval, release, and humanoid promotion remain later phases.
