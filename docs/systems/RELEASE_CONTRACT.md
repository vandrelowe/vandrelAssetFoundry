# Review, Approval, and Release Contract

**Status:** Partial — design authority; publication not implemented

## Ratified invariants

- Approval is explicit and manual.
- Approval binds exact artifact roles to SHA-256 hashes.
- Any approved artifact change invalidates approval.
- Release is dry-run by default.
- Release revisions are immutable and monotonically numbered.
- Publication never overwrites an existing release revision.
- Release creation and Git commit/push are separate user-controlled actions.
- A release contains technical facts and provenance, not Vandrel gameplay or
  mod authority.

## Required before publication implementation

The contract must define the versioned release descriptor, staging/rename
transaction, catalog update transaction, clean-tree policy, recovery from
partial publication, and asset-library Git LFS expectations.
