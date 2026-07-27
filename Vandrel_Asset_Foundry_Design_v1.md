# Vandrel Asset Foundry
## Version 1 Architecture and MVP Development Plan

**Status:** Proposed design baseline
**Date:** July 26, 2026
**Primary development directory:** `C:\dev\VandrelAssetFoundry`

## 1. Executive Decision

Vandrel Asset Foundry is a separate Python companion tool for Vandrel. Its purpose is to turn AI-generated and externally sourced 3D candidates into reviewed, technically validated, reproducible asset releases suitable for later import into Vandrel.

The first version is deliberately not a distributed worker system. The three-home-computer model is organizational:

- **Foundry PC:** develops and operates Vandrel Asset Foundry, communicates with Meshy, stores active candidate work, runs Blender cleanup, performs asset review, and publishes approved releases.
- **Vandrel PC:** develops the main Godot game and imports only approved asset releases.
- **Third PC:** remains available for a future mod manager, Blender batch processing, testing, backups, reference generation, or other supporting work.

Git is the coordination mechanism between computers. Active Foundry work is not synchronized as a live shared workspace. Approved, immutable releases are transferred through a dedicated Git LFS asset-library repository.

The central rule is:

> Meshy creates candidate source material. Foundry records its provenance, processes it, validates it, and publishes an approved immutable asset release. Vandrel imports that release explicitly and separately.

## 2. Scope

### 2.1 Foundry owns

- Prompts and reference images used to create an asset candidate.
- Provider requests, task IDs, task status, and recoverable job history.
- Downloaded GLB, FBX, textures, thumbnails, and related source outputs.
- Optional Meshy remesh, retexture, rigging, and animation operations.
- Optional Blender cleanup and decimation.
- Technical inspection and Godot sandbox import validation.
- Wrapper-scene templates and staged wrapper scenes.
- Asset workflow status, review notes, approval, rejection, and release history.
- Immutable released packages with hashes and provenance summaries.

### 2.2 Foundry does not own

- Equipment damage, armor values, racial characteristics, recipes, technology definitions, or other gameplay metadata.
- Runtime mod dependency resolution, load order, patch semantics, or override priority.
- Direct modification of the Vandrel repository during generation and review.
- Automatic acceptance of humanoid or creature skeletons into Vandrel's canonical animation pipeline.
- A general-purpose digital asset management system.

Gameplay metadata and mod coexistence belong to a separate future Vandrel content/mod tool.

## 3. Repository and Computer Model

### 3.1 Recommended repositories

| Repository | Working directory | Purpose | Large binaries |
|---|---|---|---|
| `Vandrel` | `C:\dev\Vandrel` | Main Godot game project | Use the game's established binary policy; Git LFS where appropriate |
| `VandrelAssetFoundry` | `C:\dev\VandrelAssetFoundry` | Python source, schemas, templates, tests, documentation | No generated models in normal history |
| `VandrelAssetLibrary` | `C:\dev\VandrelAssetLibrary` | Approved immutable release packages | Git LFS required for GLB, FBX, textures, Blender files, and other large binaries |
| `VandrelModManager` | `C:\dev\VandrelModManager` | Future content metadata and mod-resolution tool | Deferred |

### 3.2 Why the asset library is separate

The Foundry source repository should remain fast to clone, easy to test, and free of generated binary history. The asset-library repository is a release channel, not an active workspace. It contains only approved immutable packages and can use Git LFS without burdening the Foundry code repository.

### 3.3 Operating flow across computers

```text
Foundry PC
  C:\dev\VandrelAssetFoundry       source code
  C:\dev\VandrelFoundryWorkspace   active untracked candidates
  C:\dev\VandrelAssetLibrary       approved releases, Git LFS
              |
              | git push / pull
              v
Central private Git remote
              |
              v
Vandrel PC
  C:\dev\Vandrel                    main game
  C:\dev\VandrelAssetLibrary        approved releases only
              |
              | explicit import
              v
Vandrel assets/ and game/scenes/
```

The third PC can clone whichever repository matches its assigned work. It should not edit the same branch or active candidate workspace simultaneously without an explicit Git workflow.

## 4. Storage Boundaries

### 4.1 Foundry code repository

```text
VandrelAssetFoundry/
├── pyproject.toml
├── README.md
├── foundry.example.toml
├── lanes.toml
├── .env.example
├── .gitignore
├── docs/
├── schemas/
│   ├── asset-manifest-v1.schema.json
│   └── asset-release-v1.schema.json
├── templates/
│   └── godot/
├── src/
│   └── vandrel_foundry/
│       ├── cli.py
│       ├── config.py
│       ├── domain/
│       ├── storage/
│       ├── providers/
│       ├── processors/
│       ├── validators/
│       ├── godot/
│       └── release/
└── tests/
```

### 4.2 Local active workspace

The active workspace is outside the Git repository and is never treated as portable source control.

```text
VandrelFoundryWorkspace/
├── assets/
│   └── stone_knife_001/
│       ├── manifest.json
│       ├── manifest.previous.json
│       ├── events.jsonl
│       ├── input/
│       ├── provider/
│       ├── source/
│       ├── processed/
│       ├── preview/
│       ├── reports/
│       ├── godot_staging/
│       └── release_staging/
├── temp/
├── cache/
├── locks/
└── backups/
```

An asset workspace path never changes because the asset moves from review to approved. Workflow state is recorded in the manifest, not represented by moving the entire directory between status folders.

### 4.3 Approved asset-library layout

```text
VandrelAssetLibrary/
├── README.md
├── .gitattributes
├── catalog.json
└── releases/
    └── static_prop/
        └── stone_knife_001/
            └── r001/
                ├── asset-release.json
                ├── model.glb
                ├── thumbnail.png
                ├── textures/
                ├── godot/
                │   └── stone_knife_001.tscn
                └── provenance/
                    └── manifest-snapshot.json
```

Releases are immutable. A changed model becomes `r002`; it does not overwrite `r001`.

## 5. Asset Lifecycle

### 5.1 Foundry workflow states

```text
draft
  -> submitted
  -> generating
  -> source_ready
  -> downloaded
  -> processed
  -> staged
  -> review
  -> approved | rejected | blocked
  -> released
```

Provider task state is tracked separately from Foundry workflow state. A Meshy task may be `PENDING`, `IN_PROGRESS`, `SUCCEEDED`, `FAILED`, or `CANCELED` without collapsing the Foundry asset into the same state model.

### 5.2 Required gates

- `create` records a candidate but spends no provider credits.
- `submit` is an explicit paid/network action.
- `downloaded` requires a complete local file and SHA-256 hash.
- `processed` requires a distinct processed artifact record, even if the initial processor is pass-through.
- `staged` means the asset has a deterministic Godot staging layout outside Vandrel.
- `review` requires a validation report.
- `approved` requires explicit manual approval bound to exact artifact hashes.
- `released` requires an immutable package and a validated release descriptor.

Any modification to an approved artifact invalidates approval.

## 6. Asset Lanes

### 6.1 Static props

Examples: primitive tools, knives, clubs, baskets, bones, bedding, small furniture, fire pits, and lean-tos.

MVP support: full generation-to-release pipeline.

Required review areas:

- Silhouette and Vandrel visual style.
- Scale, orientation, pivot, and ground contact.
- Triangle and material budgets.
- Texture completeness.
- Collision recommendation.
- Successful Godot sandbox import.

### 6.2 Near environment assets

Examples: boulders, cliffs, cave entrances, and terrain chunks used near the player.

MVP support: generation, processing, staging, review, and release. Collision remains a reviewed policy rather than silently generated final collision.

### 6.3 Distant horizon assets

Examples: mountain silhouettes, distant cliffs, and low-resolution world-edge pieces.

Policy differences:

- Aggressive geometry budget.
- Simplified materials.
- No collision.
- Silhouette quality is more important than close-detail quality.

### 6.4 Humanoids

Examples: cavemen, cavewomen, hominids, and primitive humanoid species.

Foundry may generate, download, rig, stage, and inspect humanoid candidates. Release into a generic candidate library is permitted, but automatic acceptance into Vandrel's canonical character pipeline is not. A later skeleton contract must define required bones, hierarchy, rest pose, scale, axes, animation naming, and root-motion expectations.

### 6.5 Creatures

Creature candidates may be released as static or experimental assets. Animated creature acceptance remains manual and body-family specific.

## 7. Manifest-First Data Model

Each candidate has one authoritative `manifest.json`. Provider payloads and large reports are stored in separate files and referenced from the manifest.

### 7.1 Identity rules

Asset IDs use lowercase ASCII letters, digits, and underscores:

```regex
^[a-z0-9][a-z0-9_]{2,63}$
```

Examples:

- `stone_knife_001`
- `lean_to_hide_002`
- `horizon_granite_ridge_001`
- `caveman_male_heavy_003`

Display names are editable. Asset IDs are permanent.

### 7.2 Manifest top-level sections

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

### 7.3 Provider task records

Provider operations are an append-only list rather than fixed task fields. This supports retries, alternate generations, remesh experiments, retexturing, rigging, multiple animations, and future non-Meshy providers.

```json
{
  "task_key": "meshy_preview_001",
  "provider": "meshy",
  "operation": "text_to_3d_preview",
  "provider_task_id": "provider-id",
  "attempt": 1,
  "status": "SUCCEEDED",
  "progress": 100,
  "request_path": "provider/meshy/requests/meshy_preview_001.json",
  "response_path": "provider/meshy/responses/meshy_preview_001.json",
  "submitted_at": "2026-07-26T16:00:00Z",
  "completed_at": "2026-07-26T16:05:00Z",
  "error": null
}
```

### 7.4 Artifact records

Every downloaded or derived file is immutable and checksummed.

```json
{
  "artifact_id": "processed_glb_001",
  "role": "processed_model",
  "stage": "processed",
  "format": "glb",
  "path": "processed/model.glb",
  "sha256": "56ef78ab...",
  "size_bytes": 1754300,
  "derived_from": ["source_glb_001"],
  "processor": {
    "name": "passthrough",
    "version": "1"
  }
}
```

### 7.5 Approval binding

Approval stores the hashes of the exact artifacts reviewed. Release fails if those hashes no longer match.

```json
{
  "approved": true,
  "approved_at": "2026-07-26T18:00:00Z",
  "approved_artifact_hashes": {
    "processed_model": "56ef78ab...",
    "godot_wrapper_scene": "90cd12ef..."
  },
  "reviewer": "Andre",
  "notes": "Approved for static-prop library."
}
```

## 8. Release Contract

The Foundry-to-library handoff is `asset-release.json`. It intentionally excludes most provider internals.

```json
{
  "schema_version": 1,
  "asset_id": "stone_knife_001",
  "release_revision": 1,
  "display_name": "Stone Knife",
  "lane": "static_prop",
  "released_at": "2026-07-26T18:30:00Z",
  "files": [
    {
      "role": "model",
      "path": "model.glb",
      "sha256": "56ef78ab...",
      "size_bytes": 1754300
    },
    {
      "role": "godot_wrapper_scene",
      "path": "godot/stone_knife_001.tscn",
      "sha256": "90cd12ef..."
    }
  ],
  "godot": {
    "tested_project_version": "4.5",
    "import_validated": true,
    "wrapper_template": "static_prop"
  },
  "technical": {
    "triangles": 2384,
    "materials": 1,
    "has_skeleton": false,
    "animations": [],
    "collision_recommendation": "manual_simple_convex"
  },
  "provenance": {
    "foundry_manifest_revision": 12,
    "manifest_snapshot": "provenance/manifest-snapshot.json"
  }
}
```

The game or future mod tool can consume this release without understanding Meshy task details.

## 9. Configuration

### 9.1 `foundry.toml`

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
default_download_format = "glb"
poll_interval_seconds = 10
request_timeout_seconds = 60

[executables]
godot = "C:/Tools/Godot/Godot_v4.5.1-stable_mono_win64.exe"
blender = "C:/Program Files/Blender Foundation/Blender/blender.exe"

[release]
default_dry_run = true
allow_overwrite = false
require_clean_asset_library_git_tree = true
```

The Vandrel path is reference-only. Foundry version 1 must refuse to write to it.

### 9.2 `lanes.toml`

Lane policy belongs in configuration rather than scattered conditionals.

```toml
[lanes.static_prop]
wrapper_template = "static_prop"
target_triangles = 2500
maximum_triangles = 5000
collision_policy = "manual_simple_convex"
requires_materials = true
requires_skeleton = false
release_enabled = true

[lanes.environment_distant]
wrapper_template = "environment_distant"
target_triangles = 2000
maximum_triangles = 5000
collision_policy = "none"
requires_materials = true
requires_skeleton = false
release_enabled = true

[lanes.humanoid]
wrapper_template = "humanoid_candidate"
requires_materials = true
requires_skeleton = true
requires_canonical_skeleton_validation = true
release_enabled = false
```

## 10. CLI Contract

### 10.1 Setup and inspection

```powershell
foundry init
foundry doctor
foundry lanes
foundry list
foundry show stone_knife_001
foundry status stone_knife_001
```

### 10.2 Asset creation

```powershell
foundry create `
  --id stone_knife_001 `
  --lane static_prop `
  --display-name "Stone Knife" `
  --prompt-file prompts/props/stone_knife.txt
```

`create` creates local state only and never submits a provider request.

### 10.3 Provider operations

```powershell
foundry submit stone_knife_001
foundry poll stone_knife_001
foundry poll --all
foundry refine stone_knife_001 --from meshy_preview_001
foundry download stone_knife_001 --task meshy_refine_001
foundry select-output stone_knife_001 --task meshy_refine_001
```

### 10.4 Processing and Godot staging

```powershell
foundry process stone_knife_001
foundry remesh stone_knife_001 --target-triangles 2500
foundry prepare-godot stone_knife_001
foundry validate stone_knife_001
```

### 10.5 Review and release

```powershell
foundry review stone_knife_001
foundry approve stone_knife_001 --all-required-checks
foundry reject stone_knife_001 --reason "Silhouette is too modern."
foundry release stone_knife_001
foundry release stone_knife_001 --apply
```

The first `release` is a dry run. `--apply` writes only to the configured asset-library repository and never pushes automatically.

### 10.6 Recovery

```powershell
foundry retry stone_knife_001 --task meshy_preview_001
foundry reconcile stone_knife_001
foundry repair-manifest stone_knife_001
```

## 11. Python Architecture

```text
CLI
 |
 v
Application services
 |
 +-- Domain and workflow rules
 +-- Manifest repository
 +-- Provider adapters
 +-- Processing adapters
 +-- Validators
 +-- Godot staging generator
 +-- Release publisher
```

### 11.1 CLI layer

Use a thin command layer. It parses arguments, displays results, and returns appropriate exit codes. It contains no HTTP logic and no direct manifest mutation rules.

### 11.2 Domain layer

Owns:

- Asset IDs and lane identifiers.
- Manifest models.
- Workflow transitions.
- Approval invalidation.
- Allowed next actions.
- Domain exceptions.

### 11.3 Storage layer

Owns:

- Atomic JSON writes.
- Asset-level locks.
- Relative-path normalization.
- Hash calculation.
- Event-log append operations.
- Workspace discovery.

### 11.4 Provider adapters

Begin with a generic interface and a Meshy implementation. Provider-specific endpoint details must not appear in the domain layer.

### 11.5 Processing adapters

Initial processors:

- `passthrough`
- Reserved `meshy_remesh`
- Reserved `blender`

Blender is not required to prove the first complete local manifest workflow.

### 11.6 Validators

Initial validators:

- Manifest schema.
- Required files.
- Hash consistency.
- Path containment.
- Lane-policy completeness.
- Release readiness.

Later validators add GLB structure, triangle counts, materials, textures, skeletons, animations, and Godot command-line import.

## 12. Safe File Operations

### 12.1 Manifest writes

1. Acquire an asset-specific lock.
2. Load and validate the current manifest.
3. Write the replacement to a temporary file in the same directory.
4. Flush and close it.
5. Copy the previous manifest to `manifest.previous.json`.
6. Atomically replace `manifest.json`.
7. Append a transition event to `events.jsonl`.
8. Release the lock.

### 12.2 Downloads

1. Download into `temp` with a `.part` suffix.
2. Verify nonzero size and expected content type where possible.
3. Calculate SHA-256.
4. Move to a new immutable source path.
5. Update the manifest only after the move succeeds.

Never download over a known-good file.

### 12.3 Release publishing

1. Require approved hashes.
2. Build a release plan.
3. Require a clean asset-library Git working tree.
4. Reject path traversal and absolute package paths.
5. Write to a temporary release directory.
6. Validate all hashes and the release descriptor.
7. Atomically rename into the final `rNNN` directory.
8. Update `catalog.json` atomically.
9. Leave Git commit and push under explicit user control.

## 13. Git Strategy

### 13.1 Foundry source repository

Track:

- Python source.
- Tests.
- Schemas.
- Wrapper templates.
- Documentation.
- Example configuration.
- Reusable prompt templates.

Ignore:

- `.env`
- API keys.
- Active workspace.
- Downloaded provider files.
- `.part` files.
- Blender scratch files.
- Python caches and virtual environments.

### 13.2 Asset-library repository

Use Git LFS for generated binary types. An initial `.gitattributes` may include:

```gitattributes
*.glb filter=lfs diff=lfs merge=lfs -text
*.fbx filter=lfs diff=lfs merge=lfs -text
*.blend filter=lfs diff=lfs merge=lfs -text
*.png filter=lfs diff=lfs merge=lfs -text
*.tga filter=lfs diff=lfs merge=lfs -text
*.exr filter=lfs diff=lfs merge=lfs -text
*.psd filter=lfs diff=lfs merge=lfs -text
```

Do not automatically commit or push from Foundry in the MVP. A release command may prepare files and print the exact Git status and suggested commit message.

### 13.3 Game repository

The Vandrel PC explicitly imports a selected asset release. The import should:

- Verify the release descriptor and hashes.
- Copy into deterministic Vandrel paths.
- Generate or adjust the game-ready wrapper as required.
- Never modify shared gameplay JSON automatically in Foundry.
- Leave a normal Git diff for review and commit in the Vandrel repository.

## 14. Meshy Integration Constraints

The Meshy adapter should treat provider behavior as external and versionable. Current official documentation describes text-to-3D as a preview task followed by a refine task, and image-to-3D as a separate operation. Authentication uses an API key. Provider requests and raw responses should be retained with authorization data redacted.

Submission safety is important because a network failure can occur after the provider creates a paid task but before Foundry records its task ID. Foundry should record a local `SUBMITTING` attempt before the request and mark ambiguous outcomes as `blocked` rather than silently resubmitting.

## 15. Godot Integration Constraints

Godot validation should occur in a generated sandbox project outside the real Vandrel checkout. The validator can invoke Godot's command-line import mode and capture exit status and logs. Foundry should generate wrapper scenes that instance the imported GLB rather than treating the imported source scene as the final game scene.

Version 1 should recommend collision policy and require manual confirmation; it should not claim to generate universally acceptable final collision.

## 16. MVP Development Plan

### Phase 1 - Local manifest foundation

Deliver:

- Python package and CLI.
- Configuration loading.
- Lane configuration.
- Asset creation.
- Manifest model and JSON Schema.
- Atomic manifest writes.
- Event log.
- `init`, `doctor`, `create`, `list`, `show`, and `status` commands.
- Tests for IDs, paths, transitions, and atomic writes.

No Meshy calls, Blender calls, Godot calls, or asset-library writes.

### Phase 2 - Meshy generation and download

Deliver:

- Authentication and redaction.
- Text-to-3D preview submission.
- Image-to-3D submission.
- Polling.
- Refinement.
- Raw request and response snapshots.
- Retry and ambiguous-submission handling.
- GLB and thumbnail downloads with hashes.

### Phase 3 - Processing and technical inspection

Deliver:

- Pass-through processor.
- Optional provider remesh.
- Basic GLB inspection.
- Triangle and material reporting.
- Lane-policy validation.

### Phase 4 - Godot staging and sandbox validation

Deliver:

- Wrapper templates.
- Deterministic staging paths.
- Temporary Godot project generation.
- Command-line import.
- Validation logs and reports.

### Phase 5 - Review and asset-library release

Deliver:

- Manual review checklist.
- Hash-bound approval.
- Rejection reasons.
- Release dry run.
- Immutable `rNNN` package creation.
- Asset-library catalog update.
- Git working-tree checks.

### Phase 6 - Blender processing

Deliver only after the basic static-prop pipeline works:

- Deterministic Blender Python scripts.
- Transform application.
- Origin and axis handling.
- Decimation.
- Normal cleanup.
- GLB export.
- Processor version and settings recorded in provenance.

### Phase 7 - Humanoid candidate sandbox

Begin only after Vandrel defines a canonical skeleton and animation contract.

## 17. Phase 1 Acceptance Criteria

Phase 1 is complete when all of the following are true:

1. `foundry init` creates the configured workspace safely and idempotently.
2. `foundry doctor` reports configuration and path problems without revealing secrets.
3. `foundry create` copies a prompt into a new permanent asset workspace and creates a valid manifest.
4. Invalid or duplicate asset IDs are rejected without partial directories.
5. Manifest updates are atomic and preserve `manifest.previous.json`.
6. Every state-changing operation appends an event to `events.jsonl`.
7. All stored manifest paths are relative and cannot escape the asset workspace.
8. `foundry list`, `show`, and `status` work without a database.
9. Automated tests pass on Windows.
10. The implementation does not read or write `C:\dev\Vandrel` except for a non-mutating marker check in `doctor`.
11. No generated model, API key, active workspace, or secret is committed to Git.
12. README instructions allow the project to be cloned and run on another computer.

## 18. Explicit Non-Goals for the First Coding Pass

- No GUI or local web server.
- No distributed job queue.
- No automatic Git commit or push.
- No writes to the Vandrel repository.
- No Meshy API calls.
- No Blender automation.
- No Godot subprocess invocation.
- No SQLite database.
- No mod manifest or load-order logic.
- No gameplay metadata authoring.
- No automatic collision generation.
- No humanoid promotion.

## 19. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Generated binaries make Git history huge | Keep active work outside Git; publish only approved releases through Git LFS |
| Foundry accidentally pollutes Vandrel | Hard code a version-1 write prohibition and test it |
| Provider retries spend duplicate credits | Append-only attempts, `SUBMITTING` state, reconciliation, no silent retry |
| Approval becomes stale after processing changes | Bind approval to exact artifact hashes |
| Manifest corruption after interruption | Lock, temporary write, atomic replace, prior-manifest backup, event log |
| Different paths on different computers | Store relative manifest paths; isolate machine-specific paths in config |
| Foundry and future mod tool overlap | Release descriptor contains technical facts only; gameplay metadata remains external |
| Humanoid assets dictate character architecture | Require Vandrel's canonical skeleton contract before acceptance |

## 20. Immediate Next Step

The first implementation session should create only the Phase 1 local manifest foundation in `C:\dev\VandrelAssetFoundry`. It should establish architecture, tests, and safety constraints before any external API integration.

The accompanying Codex prompt is designed for that first session.

## Appendix A - Suggested `.gitignore`

```gitignore
.venv/
__pycache__/
.pytest_cache/
.ruff_cache/
.mypy_cache/
*.py[cod]
.env
foundry.toml
build/
dist/
*.egg-info/

# Never commit active asset work
workspace/
downloads/
processed/
review/
temp/
cache/
*.part
*.blend1
```

## Appendix B - External References

1. Meshy Text to 3D API documentation: preview followed by refine for the documented text-to-3D workflow.
2. Meshy Authentication documentation: API-key authentication requirements.
3. Godot command-line documentation: command-line import support for sandbox validation.
4. GitHub Git LFS documentation: Git LFS installation and use for large files.
