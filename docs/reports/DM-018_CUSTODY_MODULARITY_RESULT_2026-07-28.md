# DM-018 Custody Modularity Result — 2026-07-28

**Status:** implementation result; reference evidence only  
**Decision authority:** Foundry contracts and automated checks, not this report

## Result

The bounded DM-018 unit introduced logical-root-qualified custody paths,
explicit policy/register/root evidence freshness, and typed workspace storage
classification without migrating package IDs, reorganizing folders, approving
assets, or publishing releases.

Current custody registers are
`vandrel_foundry_custody_register/1.1`. Register 1.0 remains parseable for
historical inspection but is rejected as stale for decisions. New candidate
evaluations use `vandrel_foundry_candidate_custody/1.1`; existing assertion 1.0
records remain readable.

## Compatibility proof

- Package IDs still derive from `sha256(source_id + "\n" + package_root)` and
  existing IDs do not change.
- No folder alias or reorganization mapping was introduced.
- Release descriptor v2 retains its existing string path fields. The planner
  performs an explicit compatibility projection from qualified custody paths.
- Candidate assertion 1.0 remains readable and keeps its legacy freshness
  behavior; only new evaluations emit 1.1.
- Register 1.0 parsing is deliberately separated from decision acceptance.

## Security and freshness proof

The portable path type rejects absolute paths, Windows drive paths, UNC paths,
backslashes, traversal, dot paths, and unknown logical roots. Register
validation rejects stale policy SHA-256 values and stale authoritative-root
fingerprints. Candidate freshness rejects malformed root-fingerprint maps and
an evidence-freshness fingerprint that no longer matches its canonical policy,
register, and root inputs.

Workspace files now have explicit classes for current manifests, creation
inputs, manifest recovery history, event audit logs, current artifacts,
historical artifacts, generated cache/staging content, operational reports,
and unregistered content. Current manifest ownership takes precedence over
historical ownership.

## Modularity review

The dependency direction remains:

1. domain custody types and hashing rules;
2. inventory and candidate-evaluation services;
3. review/release planning;
4. explicit publication.

No inventory or candidate-evaluation module imports publication mechanics, and
no new code crosses the approval or publication boundary. Release planning
depends only on the domain portable-path type and projects it through a local
compatibility helper.

The scan service's use of manifest models, repository reads, and the existing
asset audit is appropriate composition for custody classification but remains
a relatively broad service dependency. The following pre-existing coupling is
not solved by this bounded unit:

- release descriptor v2 still represents custody paths as unqualified strings;
- package identity remains derived from a path string;
- approval does not independently rescan all three physical roots;
- authoritative register validation rebuilds the complete inventory;
- unrelated service-layer authority imports identified by the DM-018 baseline
  remain separate follow-up work.

These require separately versioned cross-project decisions. None was hidden
behind an alias or silent migration.

## Verification

Verification completed:

- focused custody/release/schema suite: 55 passed, 1 expected symlink skip;
- full suite: 243 passed, 3 expected platform/symlink skips;
- Ruff: all checks passed;
- `git diff --check`: passed;
- Pydantic-to-JSON-schema parity: passed;
- live readability preflight: passing for all three roots, 19 candidate roots,
  11 release roots, 2,995 files, and 748 directories;
- live register 1.1 build:
  SHA-256 `0a7285b884d92b66b6d2ce1da26bf5f315e3c7d2a3d95fd42b9ea9108db5fb44`;
- independent live validation: valid, reconciling 1,648 Outside Assets files
  and 1,173 Foundry workspace files.

## Boundaries preserved

This unit performed no approval, rejection, publication, provider/network
operation, deletion, folder migration, Asset Library mutation, Vandrel
mutation, push, or package-ID migration.
