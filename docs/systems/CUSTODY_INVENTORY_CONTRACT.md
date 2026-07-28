# Custody Inventory Contract

**Status:** Active — read-only inventory and validation

## Authority

Asset Library/Intake owns required custody fields, rights-status semantics, and
acceptance. Foundry owns the backward-compatible scanner, canonical register,
validator, and CLI implementation. The register is a custody prerequisite, not
approval, publication, legal interpretation, Vandrel acceptance, gameplay
registration, or a deletion recommendation.

The scanner may read Outside Assets and the private Foundry workspace. It must
not change either root, the Asset Library, immutable releases, or Vandrel.
Register and run-report destinations must be outside both scanned roots.

## Versioned records

- `vandrel_foundry_custody_policy/1.0` declares logical roots, source/package
  rules, license evidence and scope, explicit exclusions, and cache/temp paths.
- `vandrel_foundry_custody_register/1.0` is canonical. Its bytes depend only on
  normalized paths, file bytes, and canonical policy bytes.
- `vandrel_foundry_custody_run_report/1.0` is operational and may contain UTC
  run time and physical roots.

Canonical content contains no absolute paths, mtimes, run timestamp, or
platform separators. Paths are root-relative POSIX strings and arrays are
ordinally sorted. SHA-256 values are lowercase.

## Outside Assets rules

Every discovered regular file is represented or matched by exactly one
explicit exclusion. Package identity derives from a policy-authoritative source
ID and normalized package root. Mechanical source hints are diagnostic only.

Rights status is package authority and is exactly `documented`, `missing`, or
`disputed`. Each file carries the derived effective status and all applicable
license-binding IDs. Zero valid binding is valid `missing` custody and is
promotion-ineligible. Disputed custody is valid but ineligible. Missing
evidence, hash mismatch, malformed/traversing scope, or conflicting applicable
bindings invalidates the run.

Duplicate set IDs are `sha256:<digest>` only when two or more represented files
share exact bytes. Exclusions participate only when their explicit rule says
so. Duplicate observations never authorize deletion or movement.

Custody promotion eligibility requires a represented, stable file with a
policy-declared source/package identity, documented nonconflicting rights, and
valid evidence bindings. It remains separate from Foundry workflow approval.

## Workspace rules

Every regular file is classified as `candidate_manifest`,
`managed_manifest_artifact`, `generated_cache_or_temp`, or
`unregistered_file`. Cache/temp classification requires an explicit policy
path rule, never a filename extension guess. Candidate summaries compose the
existing candidate audit and record manifest revision/state, artifact-record
count, physical file/byte totals, released revision, storage class counts, and
additive retention holds:

- `active_workflow`;
- `approval_or_release_history`;
- `rejected_evidence`;
- `integrity_failure`;
- `unregistered_content`.

Rejected, released, historical, or unregistered evidence is never inferred to
be deletable.

## Fail-closed behavior

Traversal, reparse points/symlinks, unreadable files, hash drift, malformed
policy, conflicting license scopes, missing evidence targets, and evidence hash
mismatch fail the run. Hashing checks file identity/size before and after read.
Lexical ancestor components are checked for reparse points and identity before
and after every file open and output publication; any observed ancestor change
fails closed. The tool assumes an exclusive, non-hostile local custody
operation. A privileged hostile process capable of swapping and perfectly
restoring a directory ancestor entirely between two checks is outside this
boundary and requires OS sandboxing or handle-relative traversal by the
operator.
The complete roots are rescanned and must produce the same fingerprint before
any output is written. A bounded retry may handle one observed drift; repeated
drift reports blocked and never loops.
