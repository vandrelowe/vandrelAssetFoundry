# Codex Start Prompt: Vandrel Asset Foundry Phase 1

You are working on a new standalone companion tool for the Vandrel Godot project.

## Working directory

Use:

```text
C:\dev\VandrelAssetFoundry
```

Do not work in `D:\dev`. Do not modify `C:\dev\Vandrel`.

## Product definition

The tool is called **Vandrel Asset Foundry**.

It is not the Vandrel game and it is not a mod manager. It will eventually manage prompts, Meshy jobs, downloaded 3D files, processing, technical validation, review, and publication of approved immutable asset releases.

The first coding pass must implement only the local manifest foundation. Do not integrate Meshy, Blender, Godot subprocesses, a GUI, a web server, SQLite, or the Vandrel repository yet.

## Repository boundaries

The eventual setup uses separate repositories:

- `C:\dev\VandrelAssetFoundry` - this Python tool.
- `C:\dev\Vandrel` - the main game; read-only and untouched in this phase.
- `C:\dev\VandrelAssetLibrary` - approved Git LFS asset releases; not used in this phase.
- A future mod manager will handle gameplay metadata, dependencies, overrides, and load order. Do not implement any mod logic here.

Active Foundry asset work will live outside the source repository in a configured workspace such as:

```text
C:\dev\VandrelFoundryWorkspace
```

## Required technology and quality

Build a conventional typed Python package with:

- `pyproject.toml`
- `src/vandrel_foundry/`
- a CLI executable named `foundry`
- Typer for command parsing
- Rich for readable terminal output
- Pydantic models for configuration and manifests
- pytest for automated tests
- standard-library TOML reading where practical

Use clear type annotations and small modules. Avoid framework layers that are not needed for Phase 1.

## Phase 1 commands

Implement these commands:

```powershell
foundry init
foundry doctor
foundry lanes
foundry create --id <asset_id> --lane <lane> --display-name <name> --prompt-file <path>
foundry list
foundry show <asset_id>
foundry status <asset_id>
```

### `foundry init`

- Load configuration.
- Create the workspace root and standard subdirectories safely.
- Be idempotent.
- Never delete or overwrite user files.
- Create no asset records.

### `foundry doctor`

Check and clearly report:

- Configuration file loading.
- Workspace root validity and writability.
- Lane configuration loading.
- Whether `C:\dev\Vandrel` contains `project.godot`, if configured.
- Confirm that Vandrel writes are disabled.
- Whether the Meshy API environment-variable name is configured, but do not require the actual key yet and never display a key value.

Return a nonzero exit code for blocking problems.

### `foundry lanes`

Display configured lane IDs and key policy fields.

Ship default lanes for:

- `static_prop`
- `environment_near`
- `environment_distant`
- `humanoid`
- `creature`

Only configuration and display are required. No lane-specific processing exists yet.

### `foundry create`

- Validate the asset ID against `^[a-z0-9][a-z0-9_]{2,63}$`.
- Reject duplicates.
- Validate that the lane exists.
- Require an existing prompt file.
- Create one permanent workspace at `<workspace_root>/assets/<asset_id>/`.
- Copy the prompt to `input/prompt.txt`; do not merely store an external absolute path.
- Create these directories:

```text
input/references/
provider/
source/
processed/
preview/
reports/
godot_staging/
release_staging/
```

- Write a valid initial `manifest.json` with workflow state `draft`.
- Write an initial `events.jsonl` event.
- Do not create a partial asset directory if validation fails.
- Do not make network calls.

### `foundry list`

Discover assets from workspace directories and manifests. Do not introduce SQLite. Display at least asset ID, display name, lane, workflow state, and updated timestamp.

### `foundry show`

Display the complete manifest in readable JSON or a structured Rich view.

### `foundry status`

Display a concise status view and valid next actions. For Phase 1, a draft asset's next action may be reported as `submit`, but `submit` must not be implemented yet.

## Data model

Create a manifest model with these top-level sections, even if many later fields are empty:

- `schema_version`
- `revision`
- `asset`
- `workflow`
- `input`
- `generation`
- `artifacts`
- `vandrel_technical`
- `quality`
- `validation`
- `approval`
- `release`
- `notes`

Use UTC ISO-8601 timestamps.

At minimum:

```json
{
  "schema_version": 1,
  "revision": 1,
  "asset": {
    "asset_id": "stone_knife_001",
    "display_name": "Stone Knife",
    "lane": "static_prop",
    "created_at": "...Z",
    "updated_at": "...Z"
  },
  "workflow": {
    "state": "draft",
    "blocked_reason": null,
    "last_error": null
  },
  "input": {
    "kind": "text",
    "prompt_file": "input/prompt.txt",
    "reference_images": []
  },
  "generation": {
    "provider": "meshy",
    "selected_task_key": null,
    "tasks": []
  },
  "artifacts": [],
  "vandrel_technical": {},
  "quality": {
    "targets": {},
    "observed": {}
  },
  "validation": {
    "result": "not_run",
    "checks": []
  },
  "approval": {
    "approved": false,
    "approved_at": null,
    "approved_artifact_hashes": {},
    "reviewer": null,
    "notes": ""
  },
  "release": {
    "released": false,
    "release_revision": null,
    "released_at": null
  },
  "notes": ""
}
```

All paths stored inside manifests must be relative, use forward slashes, and reject `..` traversal.

## Atomic manifest storage

Implement a dedicated manifest repository/storage service. State-changing writes must:

1. Acquire an asset-specific lock.
2. Validate the replacement manifest.
3. Write to a temporary file in the asset directory.
4. Flush and close it.
5. Preserve the existing manifest as `manifest.previous.json` when one exists.
6. Atomically replace `manifest.json`.
7. Append an event to `events.jsonl`.
8. Release the lock.

Use a simple Windows-compatible lock strategy. Keep the locking implementation isolated behind an interface so it can be replaced later.

## Configuration files

Create and document:

- `foundry.example.toml`
- `lanes.toml`
- `.env.example`

Do not commit a real `foundry.toml` or `.env`.

The example configuration should use:

```toml
schema_version = 1

[foundry]
workspace_root = "C:/dev/VandrelFoundryWorkspace"
asset_library_root = "C:/dev/VandrelAssetLibrary"
default_provider = "meshy"

[vandrel]
reference_repo_root = "C:/dev/Vandrel"
required_marker = "project.godot"
write_enabled = false

[providers.meshy]
api_base = "https://api.meshy.ai"
api_key_environment_variable = "MESHY_API_KEY"

[release]
default_dry_run = true
allow_overwrite = false
```

The application must fail configuration validation if `vandrel.write_enabled` is true in Phase 1.

## JSON Schema

Generate `schemas/asset-manifest-v1.schema.json` from or in sync with the Pydantic model. Add a test that validates a newly created manifest against the schema.

## Package structure

Use this as a guide, adjusting only when there is a concrete reason:

```text
src/vandrel_foundry/
├── __init__.py
├── __main__.py
├── cli.py
├── config.py
├── domain/
│   ├── ids.py
│   ├── lanes.py
│   ├── manifest.py
│   ├── states.py
│   └── errors.py
├── storage/
│   ├── atomic.py
│   ├── events.py
│   ├── locks.py
│   ├── manifests.py
│   └── paths.py
└── services/
    ├── create_asset.py
    ├── doctor.py
    └── inspect_assets.py
```

Keep provider, processor, validator, Godot, and release packages as documented placeholders only if useful. Do not add empty abstractions merely to mirror the future architecture.

## Tests

Add focused tests for:

- Valid and invalid asset IDs.
- Duplicate asset rejection.
- Unknown lane rejection.
- Missing prompt rejection.
- No partial directory after failed creation.
- Correct initial workspace layout.
- Prompt copied into the workspace.
- Manifest schema validity.
- Relative path enforcement and traversal rejection.
- Atomic manifest replacement and previous-manifest preservation.
- Event-log creation.
- Idempotent `init`.
- `doctor` refusing `vandrel.write_enabled = true`.
- CLI smoke tests for every implemented command.

Use temporary directories in tests. Tests must not touch `C:\dev\Vandrel` or the real Foundry workspace.

## Documentation

Create a useful `README.md` containing:

- Product purpose and non-goals.
- Windows setup instructions.
- Virtual environment or package-manager setup.
- Configuration setup from the example.
- Every Phase 1 command with examples.
- Repository and workspace boundaries.
- A warning that active candidate assets and secrets must not be committed.
- Phase 2 roadmap summary.

Also add `docs/architecture.md` summarizing the separation among Foundry, the approved asset library, Vandrel, and the future mod manager.

## Git hygiene

Create a strong `.gitignore` covering:

- `.venv`
- Python caches
- `.env`
- real `foundry.toml`
- build artifacts
- active workspace directories
- model downloads
- `.part` files
- Blender backups

Do not initialize Git LFS in this source repository. Git LFS belongs in the separate asset-library repository later.

## Safety constraints

- Never modify, format, or inspect unrelated repositories.
- Never write to `C:\dev\Vandrel`.
- Never make network calls in Phase 1.
- Never print secrets.
- Never delete an existing asset workspace.
- Never silently overwrite manifests or prompts.
- Prefer explicit errors over automatic repair.
- Keep all file operations deterministic and testable.

## Work method

1. Inspect the current contents of `C:\dev\VandrelAssetFoundry` before changing anything.
2. If files already exist, preserve compatible work and report conflicts rather than overwriting blindly.
3. Implement in small coherent steps.
4. Run formatting, static checks if configured, and the full test suite.
5. Exercise the CLI manually against a temporary test workspace.
6. Review `git diff` for accidental binaries, secrets, absolute machine paths, or Vandrel changes.
7. Do not push automatically.

## Definition of done

Stop after Phase 1. Report:

- Files created or changed.
- Architecture choices made.
- Commands implemented.
- Test results.
- A short manual verification transcript.
- Any unresolved issue that blocks Phase 2.
- The recommended next commit message.

Do not begin Meshy integration until Phase 1 is reviewed and accepted.
