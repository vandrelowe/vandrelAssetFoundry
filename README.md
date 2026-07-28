# Vandrel Asset Foundry

Vandrel Asset Foundry is a standalone, manifest-first Python companion tool for
turning candidate 3D assets into traceable, reviewable releases for Vandrel.
Phase 1 provides local configuration, workspace creation, draft manifests,
atomic storage, event history, and inspection. Phase 2 adds a guarded Meshy
Text-to-3D and Image-to-3D lifecycles with redacted evidence, polling,
recovery, and checksummed source downloads.

It is not the Vandrel game, a mod manager, or an asset database. It can invoke
explicitly configured Godot and Blender executables only through bounded local
workflows. Normal Foundry commands never write into the Vandrel repository.
The governance contract separately permits a narrowly bounded, asset-scoped
consumer-validation step for an approved immutable release; that step does not
grant Foundry gameplay or runtime authority.

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

After setup, the directly runnable Windows entry point is
`.\.venv\Scripts\foundry.exe`. Activating the virtual environment makes the
shorter `foundry` command available in that terminal.

## Commands

```powershell
foundry init
# One-time, explicit creation of a new configured local Git/LFS library:
foundry init-library --confirm-init
foundry doctor
foundry lanes
foundry create --id stone_knife_001 --lane static_prop `
  --display-name "Stone Knife" --prompt-file .\prompts\stone_knife.txt
foundry list
foundry show stone_knife_001
foundry status stone_knife_001
foundry audit stone_knife_001
foundry audit-all
foundry audit-library
foundry review-gallery

# Run an explicit versioned, sequential local-only static batch plan.
foundry run-static-batch .\batch-plan.json --ledger .\batch-ledger.json
foundry scan-sources C:\Dev\outsideassets
foundry scan-sources C:\Dev\outsideassets --json
foundry scan-sources C:\Dev\outsideassets --family meshy --lane static_prop

# Skip Meshy entirely with GLB, FBX-plus-textures, or glTF packages.
foundry add-source stone_knife_001 --model .\models\stone_knife.glb
foundry add-source basket_001 --model .\meshy\basket.fbx
foundry add-source anvil_001 --model .\kit\Anvil.gltf
```

`init` is safe to repeat and never creates asset records. `create` validates all
inputs before creating an asset workspace, copies the prompt to
`input/prompt.txt`, and creates a draft manifest plus an event log. `status`
reports the current workflow and valid next actions.
`scan-sources` performs a read-only recursive inventory of supported model
packages and suggests static-prop or humanoid intake lanes; it does not copy,
convert, submit, or create asset records.
`audit` is also read-only. It rehashes every manifest artifact and checks
artifact IDs, paths, derivation references, and approval bindings.

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
foundry process-blender stone_knife_001
# Explicit, local-only decimation; the output must meet this target.
foundry process-blender stone_knife_001 --target-triangles 2500
foundry inspect stone_knife_001
foundry render-preview stone_knife_001
foundry render-missing-previews
foundry prepare-godot stone_knife_001
foundry validate-godot stone_knife_001
# Extract and validate Meshy's same-rigging-task FBX walk/run clips without Blender.
foundry prepare-native-character character_001
# Offline material-response evidence for a processed character or prop.
foundry experiment-shaders stone_knife_001
# Record a strict four-color mask and render offline per-region isolation evidence.
# This remains experimental and cannot automatically approve the mask.
foundry experiment-semantic-mask character_001 --mask C:\path\to\semantic-mask.png
# Compare a processed character and animation donor against the bundled
# Meshy-to-Godot humanoid profile.
foundry validate-humanoid-rig character_001 --animation-donor animation_library_001
# Raw copying is intentionally narrower than retargeting and fails unless
# joint names, hierarchy, and local rest transforms match.
foundry graft-animations character_001 --animation-donor animation_library_001
foundry approve stone_knife_001 --reviewer "Reviewer Name" --all-required-checks
# Read-only plan:
foundry release stone_knife_001
# Explicitly publish into a preconfigured clean Git/LFS asset library:
foundry release stone_knife_001 --apply

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

`add-source` accepts a GLB directly or converts FBX/glTF packages through the
bounded Blender adapter. Package intake copies the original model and only its
required/same-package texture or buffer sidecars into immutable provenance
storage before conversion. It records hashes, Blender version, structured
warnings, and bounded logs, then moves the asset to the downloaded state. The
remaining processing, Godot validation, review, and release-plan commands work
without a Meshy key or credits.

## Repository and workspace boundaries

- This repository contains Python source, schemas, tests, and documentation.
- The configured Foundry workspace contains active candidate assets and stays
  outside Git.
- The configured asset-library Git repository contains approved immutable
  releases. `release --apply` writes only after clean-tree and Git LFS checks;
  it never commits or pushes those changes.
- `C:\dev\Vandrel` is reference-only to normal Foundry commands. `doctor` may
  check for `project.godot`; Foundry refuses configurations that enable writes.
  The standing governance exception permits only bounded consumer validation
  of an approved immutable release, with Vandrel retaining ownership.
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
remesh is available behind an explicit paid-action guard. The first Phase 4
slice creates a self-contained Godot validation sandbox and runs bounded,
headless import validation without touching Vandrel. The subprocess uses the
configured absolute executable, removes Meshy credentials from its environment,
limits runtime and output, and records hash-bound logs and reports. Manual
hash-bound approval, read-only release planning, recoverable explicit
asset-library publication, and deterministic Blender transform cleanup/export
are implemented. Publication uses an immutable staging/rename transaction,
atomic catalog replacement, clean-worktree checks, and Git LFS verification;
asset-library commit/push and Vandrel import remain separate. Explicit
target-bound local decimation is implemented; automated target selection and
consumer runtime animation acceptance remain later work. Humanoid candidate
publication is enabled only for exact approved model/wrapper hashes with passing,
hash-bound `meshy_humanoid/v1` compatibility evidence. Its release descriptor
explicitly records that Vandrel runtime acceptance remains false.

The local character corridor includes bounded Blender rest-pose retargeting for
exact-name/hierarchy Meshy rigs, 30 FPS action baking, representative animation
sample sheets, and renewed GLB/Godot validation. Production approval of that
processor is suspended: a live character test exposed a unit-sensitive hips
translation bake and a Godot skin/import failure that Blender stills did not
catch. It remains available only for bounded forensic experiments. The current
preferred character route preserves Meshy's provider-native FBX rig and uses
same-task `withSkin` animations imported directly by Godot. Foundry still does
not assign gameplay clip semantics or claim consumer-side animation acceptance.

The optional Blender processor uses the absolute executable configured at
`tools.blender_executable`. The current machine uses the Steam installation at
`C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe`; it has
been verified with Blender 5.2.0 LTS in background mode. Foundry launches it with
factory settings, automatic embedded-script execution disabled, a bounded
runtime/output budget, and a checked-in processing script. It applies rotation
and scale, exports a new GLB, validates that output, and records Blender's
version and a processing report.

The opt-in real Blender smoke test is credit-free:

```powershell
$env:VANDREL_FOUNDRY_TEST_BLENDER = `
  "C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe"
pytest tests/test_blender_live.py
```

Set `tools.godot_executable` in `foundry.toml` before using
`validate-godot`. The opt-in real-tool smoke test can be run without Meshy:

```powershell
$env:VANDREL_FOUNDRY_TEST_GODOT = "C:\Dev\Godot\Godot.exe"
pytest tests/test_godot_live.py
```
