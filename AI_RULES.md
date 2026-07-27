# AI Rules — Vandrel Asset Foundry

## Purpose

These rules make AI work predictable, non-destructive, auditable, and
compatible with the wider Vandrel toolchain.

## Operating behavior

- Default to implementing a requested, bounded change.
- If the user asks for analysis or review only, do not mutate files.
- Inspect before editing and report genuine conflicts instead of overwriting.
- Work in small coherent steps and keep the user informed during tool work.
- Do not claim success without executing proportionate validation.

## Hard safety rules

1. Treat `C:\dev\Vandrel` as read-only except for the approved-release,
   asset-scoped downstream integration and finite test authorized by
   `GOVERNANCE.md`.
2. Never write to a real Foundry workspace during tests.
3. Never delete or replace an existing asset workspace.
4. Never overwrite prompts, artifacts, manifests, or releases silently.
5. Never store absolute machine paths in portable manifests or releases.
6. Never allow `..`, drive-qualified, or backslash paths in portable fields.
7. Never reveal API keys in logs, exceptions, snapshots, test output, or events.
8. Never make an implicit network call or paid provider retry.
9. Never publish, commit, or push automatically unless explicitly requested.
10. Never treat appearance as gameplay classification or runtime approval.

## Architecture rules

- The CLI parses input, presents results, and maps errors to exit codes.
- Services orchestrate use cases.
- Domain models validate identity, state, and portable data.
- Storage modules own locks, containment, atomic replacement, events, and
  discovery.
- Provider, processor, validator, and publisher implementations must remain
  adapters behind explicit service boundaries.
- Do not mutate manifest dictionaries ad hoc. Validate complete replacement
  models through the manifest repository.
- State changes acquire the asset lock, validate, write and flush a temporary
  file, preserve the previous manifest, atomically replace the current
  manifest, append an event, and release the lock.
- Workflow state and provider task state remain separate.

## Data and compatibility rules

- Asset IDs are permanent and follow the documented lowercase identifier rule.
- UTC timestamps use ISO 8601 with an explicit UTC offset or `Z`.
- Portable paths are relative to their package/workspace root.
- Artifacts are immutable and content-addressed with SHA-256 once recorded.
- Approval is invalidated when approved artifact hashes change.
- Released revisions are immutable; changed output becomes a new revision.
- Unknown future enum/state values must fail loudly unless a versioned
  compatibility policy explicitly allows them.
- JSON Schema and Pydantic models must remain synchronized.

## Vandrel interface rules

Before changing any Vandrel-facing export or validation rule, inspect the
current external authorities:

- `C:\dev\Vandrel\docs\ASSET_ORGANIZATION.md`
- `C:\dev\Vandrel\docs\ARCHITECTURE_AUTHORITY.md`
- The relevant active corridor contract, especially animation, equipment
  visuals, construction, furniture/world items, terrain, or navigation.

Use these only to define or test the handshake. Do not make them runtime
dependencies or copy their gameplay catalogs into Foundry. Writes to the
checkout are limited to the standing downstream-integration exception in
`GOVERNANCE.md`.

Foundry releases may state measured facts and declared intent. They must not
claim that Vandrel imported an asset, accepted a skeleton, enabled runtime
content, or granted collision/navigation/gameplay authority without
consumer-side evidence.

## Provider and subprocess rules

- Configuration loading must not require a secret value during local-only work.
- Authentication headers and provider payload snapshots must be redacted.
- Record a local submission attempt before a paid request.
- Treat ambiguous submission outcomes as blocked; do not silently resubmit.
- Downloads go to a `.part` file, are checked and hashed, then moved to a new
  immutable path before manifest update.
- Future Blender and Godot subprocesses must be bounded, invoked through one
  adapter, and capture versions, arguments, and exit status. Godot may operate
  in Vandrel only for the standing approved-release downstream integration
  test; ordinary Foundry processing remains outside Vandrel.
- No unbounded polling or subprocess execution.

## Logging and errors

- Rich console output is for users; persisted events are structured audit data.
- Never use debug output as the only evidence for behavior.
- Errors must name the failed operation and safe target without secret values.
- Do not catch broad exceptions merely to continue with corrupt or partial
  state.
- Partial or ambiguous work must be reported as partial or blocked, not done.

## Testing rules

- Use temporary paths supplied by pytest.
- Assert no partial directory after validation failure.
- Exercise duplicate/race, traversal, interrupted write, and schema failure
  paths when their code changes.
- Mock external providers by default.
- Live-provider tests must be separately marked, opt-in, and never run in the
  normal suite.
- Cross-repository tests use checked-in fixtures or read-only discovery with an
  explicit skip when the sibling checkout is absent.

## Documentation rules

- Update the corridor contract when behavior or authority changes.
- Update the architecture authority map when ownership moves.
- Update examples and schemas when public data changes.
- Mark guides as reference-only when they overlap governing contracts.
- Do not use archived Vandrel documents as current authority.
