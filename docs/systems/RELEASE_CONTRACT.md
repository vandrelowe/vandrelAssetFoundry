# Review, Approval, and Release Contract

**Status:** Active for review, approval, and dry-run planning; publication blocked

## Ratified invariants

- Approval is explicit and manual.
- Approval binds exact artifact roles to SHA-256 hashes.
- Approval requires passing GLB structure, nonempty geometry, lane
  triangle-budget, material, skeleton, and Godot sandbox-import checks.
- Any approved artifact change invalidates approval.
- Release is dry-run by default.
- Release revisions are immutable and monotonically numbered.
- Publication never overwrites an existing release revision.
- Release creation and Git commit/push are separate user-controlled actions.
- A release contains technical facts and provenance, not Vandrel gameplay or
  mod authority.

## Dry-run release descriptor

`release` performs a read-only plan. It verifies the approved artifact files
against their recorded hashes and sizes, checks that the lane permits release,
selects the next unused `rNNN` directory, and prints schema-versioned
`asset-release.json` content. The plan contains:

- stable asset identity, lane, display name, and proposed revision;
- portable release paths, roles, hashes, sizes, and source artifact IDs;
- Godot import-validation result and declared wrapper-template intent;
- observed technical facts and collision recommendation;
- Foundry manifest revision and approval provenance.

The plan does not create a directory, mutate the manifest or catalog, run Git,
or claim a Vandrel runtime destination. `release --apply` fails closed.

## Required before publication implementation

Publication still requires a ratified staging/rename transaction, catalog
update transaction, clean-tree policy, partial-publication recovery, and
asset-library Git LFS verification.
