# Vandrel Asset Foundry Development Governance

**Status:** Authoritative
**Applies to:** Human contributors and AI assistants

## Purpose

Vandrel Asset Foundry is a standalone, typed Python tool that turns external or
AI-generated asset candidates into traceable, technically assessed, manually
approved, immutable release packages. It is not Vandrel, not an asset library,
and not a mod manager.

These rules favor correctness, provenance, recoverability, and compatibility
over speed.

## Mandatory pre-work

Before changing code:

1. Read `GOVERNANCE.md`, `AI_RULES.md`,
   `docs/DOCUMENTATION_RULES.md`, and
   `docs/ARCHITECTURE_AUTHORITY.md`.
2. Identify the primary development corridor.
3. Read its contract under `docs/systems/`.
4. Inspect the current implementation, tests, and `git status`.
5. State a bounded plan, exact intended files, repository boundaries, and the
   validation evidence required.

If the relevant contract is a stub or the requested behavior crosses an
unratified boundary, contract work comes before implementation.

## Authority order

If instructions conflict:

`GOVERNANCE.md` → `AI_RULES.md` →
`docs/DOCUMENTATION_RULES.md` →
`docs/ARCHITECTURE_AUTHORITY.md` → relevant corridor contract →
schemas/patterns → active task or sprint → guides/references → archive.

Sibling-repository documents are external interface references, not local
authority.

## Development corridors

| Corridor | Governing contract | Status |
|---|---|---|
| Local manifests and workspace | `docs/systems/MANIFEST_WORKSPACE_CONTRACT.md` | Active, Phase 1 |
| Configuration and CLI | `docs/systems/MANIFEST_WORKSPACE_CONTRACT.md` | Active, Phase 1 |
| Provider jobs and downloads | `docs/systems/PROVIDER_PIPELINE_CONTRACT.md` | Stub; blocks provider integration |
| Processing and technical inspection | `docs/systems/PROCESSING_VALIDATION_CONTRACT.md` | Stub; blocks processing integration |
| Review, approval, and release | `docs/systems/RELEASE_CONTRACT.md` | Partial; design only, no publication yet |
| Vandrel/library interoperability | `docs/systems/INTEROPERABILITY_CONTRACT.md` | Active boundary; import handshake remains versioned |

Do not implement a stubbed corridor merely because future fields or directories
already exist.

## Core principles

### Single authority

Each fact has one owner:

- The candidate manifest is authoritative for active Foundry work.
- Provider raw responses are evidence, not workflow authority.
- Derived files are immutable artifacts identified by hashes.
- Approval is bound to exact hashes.
- A release descriptor is authoritative inside one published release.
- Vandrel owns runtime/game meaning after explicit import.

When two systems appear to own the same fact, resolve the authority conflict
before adding synchronization logic.

### Production, not disposable glue

Code must be typed, deterministic, testable, and recoverable. Avoid hidden
repair, mutable global state, parallel workflow paths, and speculative
abstractions. Small does not mean temporary: each implemented slice must have a
clear contract and evidence.

### Framework boundaries first

Foundry records technical facts and provenance. It must not infer that a mesh
which looks like a chair is furniture, that a rock blocks navigation, or that a
humanoid rig is accepted by Vandrel. Those decisions belong to the consuming
repository and its current contracts.

### Explicit irreversible or costly actions

Local validation may be automatic. Network submissions, provider retries that
may spend credits, destructive repair, approval, publication, overwrite, Git
commit, and push require explicit intent and must be auditable.

## Repository safety

- `C:\dev\VandrelAssetFoundry`: source code only.
- Configured Foundry workspace: active candidates; never Git source.
- `C:\dev\VandrelAssetLibrary`: future immutable releases; no Phase 1 writes.
- `C:\dev\Vandrel`: read-only reference; no Foundry writes.

Tests use temporary directories and must never touch real workspaces or sibling
repositories.

## Change discipline

- Preserve unrelated dirty files.
- Make the smallest coherent change that meets acceptance criteria.
- Do not rename public fields, move modules, or revise schemas casually.
- Manifest and release schema changes require versioning or a documented
  backward-compatible migration.
- Do not silently accept unknown data at security or authority boundaries.
- Do not create a second governing document for an existing corridor.
- Durable decisions from task notes must migrate into the relevant contract.

## Evidence required

Every change needs evidence at the layer it affects:

- Domain and storage rules: focused unit tests.
- CLI behavior: CLI runner or subprocess smoke tests.
- Filesystem safety: temporary-directory integration tests.
- Schema changes: Pydantic/JSON Schema parity and representative validation.
- Provider code: mocked contract tests before any live opt-in test.
- Processing tools: bounded subprocess tests with recorded versions and outputs.
- Cross-repository compatibility: fixture-based contract tests; never mutate a
  sibling checkout to prove compatibility.

Completion requires `ruff check .`, the full `pytest` suite, and a concise
manual transcript when human-facing behavior changed.
