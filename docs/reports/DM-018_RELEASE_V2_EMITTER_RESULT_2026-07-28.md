# DM-018 Release-v2 Emitter Result — 2026-07-28

> Reference only. Asset Library contract authority remains external to this
> implementation report.

status: implementation and verification complete; v2 unratified and
unpublished

## Result

The Foundry release planner now emits a strict planned-v2 descriptor instead
of an open raw dictionary:

- technical fields are an explicit whitelist with closed schema vocabulary;
- custody package, evidence, and scope paths retain `{logical_root, path}`;
- register bindings carry the exact three root fingerprints;
- the candidate evidence-freshness SHA-256 is retained and recomputed by the
  descriptor validator;
- humanoid compatibility reports are verified manifest artifacts, included in
  the release file set, and referenced by packaged path, source artifact ID,
  SHA-256, and size;
- custody evidence references now carry their candidate evidence artifact ID,
  and both custody evidence and humanoid reports reconcile the exact expected
  role, release path, source artifact ID, SHA-256, and size;
- interrupted publication recovery validates the complete descriptor through
  the same executable v2 contract, requires canonical byte equality to the
  current complete plan, and rechecks the exact release file set, hashes, and
  sizes before any catalog mutation;
- planner, descriptor models, publication layout helpers, and Library audit
  reject revisions outside `1..999`.

Candidate assertion 1.0 and custody register 1.0 remain parseable historical
records but now return explicit legacy-stale decision blockers. They cannot
authorize approval or release.

## Version and compatibility boundary

Historical release descriptor v1 is modeled permissively so existing extension
fields and stored bytes are not rewritten. A pinned v1 fixture proves its exact
SHA-256 remains unchanged. Both v1 and v2 enforce the already canonical
three-digit release revision range.

Planned release descriptor v2 is strict and rejects unknown fields. The
Foundry-checked compatibility/planning schemas exactly match their Pydantic
models. These schemas do not ratify v2 for the Asset Library; they provide
executable producer-side evidence for the future Library-owned contract
decision.

## Security and failure coverage

Runtime and checked-JSON-schema tests reject:

- absolute, drive-qualified, UNC, backslash, dot, and traversing custody paths;
- flattened custody paths with no logical root;
- malformed, incomplete, or extra root-fingerprint maps;
- stale evidence-freshness fingerprints;
- arbitrary technical fields carrying workspace paths;
- Workspace-only humanoid report strings;
- report references not reconciled to packaged file hashes;
- model-as-humanoid-report, model-as-license-evidence, custody source-ID
  mismatch, and static-role-confusion substitutions in both the domain
  validator and live Library-audit service;
- unknown-field, otherwise-valid complete-descriptor, and evidence-source
  tampering in an uncataloged recovery journal, with catalog and Foundry
  manifest remaining unchanged;
- changed or undeclared recovered release files before catalog mutation;
- `r000` and `r1000` descriptor/planner/audit layouts.

The Torch resume-ledger redaction contract now recursively checks all string
fields for backslash and forward-slash drive paths, UNC and POSIX absolute
paths, configured root identifiers, URLs, email-shaped identifiers, and
provider-task identifiers. The ledger remains validated through the closed
production `BatchLedger` schema.

## Modularity review

Dependency direction for this unit is:

1. `domain/release_descriptor.py` owns versioned shape, portable-path,
   freshness, packaged-evidence reconciliation, and revision formatting;
2. `plan_release.py` verifies candidate-owned artifacts and constructs the
   strict v2 projection;
3. `audit_library.py` consumes the versioned validator read-only;
4. `publish_release.py` consumes the already validated plan, reuses the
   versioned descriptor validator for interruption recovery, and owns only
   publication-journal/file-set reconciliation plus transaction mechanics.

No domain module imports planner, audit, publication, configuration, or
Library mechanics. The planner does not invoke publication. No new reverse
dependency or second release authority was introduced.

Sprint-created coupling is limited to the planner importing the descriptor
domain and audit/publication importing the shared revision formatter. Existing
publication transaction, Git/LFS/ACL mechanics, catalog v1 dictionaries, and
the pre-existing `audit_asset.py` approval-role inversion remain separate
follow-up concerns.

## Evidence semantics

An assertion-1.1 evidence fingerprint matching its stored fields proves stored
snapshot consistency. It does not by itself rescan physical roots. Live-root
freshness requires current register revalidation against Outside Assets,
Foundry Workspace, and Asset Library. The two statements remain distinct in
status and documentation.

## Boundaries

This unit performed no asset approval, release publication, Asset Library
mutation, provider/network operation, asset deletion, Git push, folder
migration, or v2 ratification. Bounded generated live-audit files were written
only under ignored `temp/` and removed after validation.

## Verification

- Focused descriptor/planner/publication/audit suite: 50 passed.
- Full suite: 290 passed, 3 expected platform/symlink skips (293 collected).
- Ruff and `git diff --check`: passed.
- Checked manifest and release schemas exactly match their executable models.
- Live read-only Asset Library audit: 65 checks passed across all 11 immutable
  historical releases.
- Live read-only workspace audit: 19 of 19 candidates passed.
- Fresh live custody inventory 1.1:
  SHA-256 `0a7285b884d92b66b6d2ce1da26bf5f315e3c7d2a3d95fd42b9ea9108db5fb44`;
  validation passed with 1,648 Outside files and 1,173 Workspace files.
- Live read-only Torch fitness: integrity passing, custody freshness `stale`,
  explicit blocker `custody_assertion_legacy_stale`, unapproved, unpublished,
  and release-ineligible.
