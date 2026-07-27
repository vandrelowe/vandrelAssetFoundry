# Vandrel Asset Foundry Agent Instructions

This file governs AI work in this repository. It is a router, not a substitute
for the authoritative documents below.

## Required reading before changes

Read in this order:

1. `GOVERNANCE.md`
2. `AI_RULES.md`
3. `docs/DOCUMENTATION_RULES.md`
4. `docs/ARCHITECTURE_AUTHORITY.md`
5. The relevant `docs/systems/*_CONTRACT.md`
6. The active task brief or sprint document, if supplied

If documents conflict, follow the authority order in
`docs/DOCUMENTATION_RULES.md`. Archived documents and sibling-repository
documents are reference material only; they do not override this repository.

## Session orientation

Before editing:

- Inspect `git status` and preserve unrelated or user-owned changes.
- Inspect the files and tests that own the behavior being changed.
- Identify the primary Foundry corridor and its contract.
- State the intended files, safety boundaries, and validation plan.
- If `session-recall` is available, it may be used for developer-session
  context. It must never become a runtime dependency or persisted Foundry data.

## Non-negotiable boundaries

- Work only in this repository and explicitly configured temporary test
  workspaces unless the user authorizes another target.
- Treat the Vandrel repository as read-only. Do not write to it, run its game,
  or alter its project/import state from Foundry work.
- Do not write to the asset-library repository except through a future,
  explicitly approved release workflow.
- Do not make provider calls or spend credits unless the user explicitly asks
  for the network action and the relevant provider contract is ratified.
- Never print, log, persist, or commit secrets.
- Never commit active candidate work, downloaded models, caches, `.env`, or a
  real `foundry.toml`.
- Preserve the single-authority boundaries in
  `docs/ARCHITECTURE_AUTHORITY.md`.

## Engineering defaults

- Use typed Python and small modules.
- Keep the CLI thin; application services own workflows, domain models own
  invariants, and storage adapters own filesystem mechanics.
- Prefer explicit errors to silent repair.
- Keep stored paths relative, forward-slash normalized, and traversal-safe.
- Use atomic writes and asset-specific locking for state changes.
- Add focused tests that exercise public behavior, not only source text.
- Run `ruff check .` and `pytest` before claiming completion.
- Keep changes scoped. Do not introduce speculative managers, frameworks, or
  future-phase abstractions.

## Cross-repository compatibility

Foundry may inspect current Vandrel contracts to validate compatibility, but it
must not copy Vandrel gameplay authority into Foundry manifests.

- Foundry owns candidate provenance, processing evidence, technical facts,
  review, approval, and immutable release packaging.
- The asset library owns published immutable release files and catalog entries.
- Vandrel owns import destination, runtime wrappers, `res://game/**` paths,
  content classification, gameplay metadata, collision/navigation behavior,
  equipment semantics, and canonical rig/animation acceptance.
- The future mod manager owns dependencies, overrides, load order, and gameplay
  content authoring.

If a cross-repository contract is missing or contradictory, stop at the
boundary and document the required handshake instead of guessing.
