# Architecture Authority

**Status:** Authoritative current ownership map

## Repository ownership

| Responsibility | Authority |
|---|---|
| Active candidate identity, provenance, workflow, evidence | Foundry candidate manifest |
| Active candidate files | Configured Foundry workspace |
| Provider request/response truth | Raw redacted provider evidence plus provider task record |
| Technical measurements | Versioned Foundry validators and reports |
| Human approval | Hash-bound Foundry approval record |
| Published package contents | Immutable asset-library release revision |
| Runtime import paths and wrapper scenes | Vandrel |
| Gameplay classification and metadata | Vandrel or future mod manager, according to their contracts |
| Mod dependencies, overrides, and load order | Future mod manager |

## Foundry layer ownership

| Responsibility | Current owner |
|---|---|
| Command parsing and terminal presentation | `src/vandrel_foundry/cli.py` |
| Machine configuration and lane loading | `src/vandrel_foundry/config.py` |
| Asset identity rules | `src/vandrel_foundry/domain/ids.py` |
| Manifest shape and validation | `src/vandrel_foundry/domain/manifest.py` |
| Workflow state and next actions | `src/vandrel_foundry/domain/states.py` |
| Portable path validation and containment | `src/vandrel_foundry/storage/paths.py` |
| Asset-specific locking | `src/vandrel_foundry/storage/locks.py` |
| Atomic manifest replacement | `src/vandrel_foundry/storage/manifests.py` |
| Audit event append | `src/vandrel_foundry/storage/events.py` |
| Asset creation workflow | `src/vandrel_foundry/services/create_asset.py` |
| Workspace discovery and initialization | `src/vandrel_foundry/services/inspect_assets.py` |
| Health checks | `src/vandrel_foundry/services/doctor.py` |
| Provider task status vocabulary | `src/vandrel_foundry/domain/provider.py` |
| Recursive provider evidence redaction | `src/vandrel_foundry/providers/redaction.py` |
| Meshy request/response shapes | `src/vandrel_foundry/providers/meshy/models.py` |
| Local Meshy preview request preparation | `src/vandrel_foundry/services/prepare_submission.py` |
| Reference-image validation and intake | `src/vandrel_foundry/services/add_reference.py` |
| Paid text and image submission orchestration | `src/vandrel_foundry/services/submit_preview.py` |
| Provider transport interface | `src/vandrel_foundry/providers/base.py` |
| Provider evidence snapshots | `src/vandrel_foundry/storage/provider_evidence.py` |
| Bounded Meshy HTTP operations | `src/vandrel_foundry/providers/meshy/http.py` |
| Provider task polling | `src/vandrel_foundry/services/poll_task.py` |
| Source GLB download and promotion | `src/vandrel_foundry/services/download_artifact.py` |
| Ambiguous submission reconciliation | `src/vandrel_foundry/services/reconcile_submission.py` |
| Provider output selection | `src/vandrel_foundry/services/select_output.py` |
| Immutable pass-through processing | `src/vandrel_foundry/services/process_asset.py` |
| GLB structure and lane-budget inspection | `src/vandrel_foundry/services/inspect_glb.py` |
| Godot validation-sandbox staging | `src/vandrel_foundry/services/stage_godot.py` |
| Bounded Godot import validation | `src/vandrel_foundry/services/validate_godot.py` |
| Manual approval and rejection | `src/vandrel_foundry/services/review_asset.py` |
| Read-only release planning | `src/vandrel_foundry/services/plan_release.py` |

The Pydantic model is the source for
`schemas/asset-manifest-v1.schema.json`; the checked-in schema is the portable
contract and must match it exactly.

## Single-authority invariants

- No service writes `manifest.json` directly; it uses `ManifestRepository`.
- No CLI command contains provider, processing, or state-transition mechanics.
- No directory name represents mutable workflow state.
- No provider status replaces Foundry workflow state.
- No report replaces the manifest's selected artifact references.
- No approved artifact may change in place.
- No release revision may change after publication.
- No Foundry field grants Vandrel runtime authority.

## Cross-repository handoff

Foundry's future release descriptor is a technical handoff, not an instruction
to mutate Vandrel. It may contain identity, hashes, provenance, formats,
measured geometry/material/rig facts, preview files, and declared lane intent.

Vandrel import remains a separate, explicit consumer operation. Current Vandrel
rules distinguish raw/source assets from reviewed runtime wrappers and require
runtime content to use approved packed paths. Foundry must therefore avoid
emitting authoritative `res://` destinations or editing Vandrel catalogs.

Humanoid and animated assets are candidates until Vandrel validates them
against its current animation and equipment contracts. A generic label such as
Mixamo-compatible is evidence, not acceptance.

## Forbidden ownership moves

- Do not add a database as a second manifest authority.
- Do not put gameplay metadata or mod resolution into Foundry.
- Do not make lane configuration a substitute for Vandrel content contracts.
- Do not let generated wrapper templates become Vandrel runtime authority.
- Do not infer collision or navigation activation from a mesh or lane.
- Do not let provider adapters mutate manifests directly.
- Do not make sibling checkouts required for ordinary Foundry startup or tests.
