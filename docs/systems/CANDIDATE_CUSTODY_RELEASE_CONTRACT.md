# Candidate Custody and Release Contract

status: implemented
ownership: Asset Library owns rights semantics; Asset Foundry owns enforcement
composition: extends `CUSTODY_INVENTORY_CONTRACT.md`

## Version behavior

Candidate manifest schema v2 carries custody. New candidates begin with
`assessment_status=absent`; this is a truthful state, not an implied rights
failure. An explicit custody evaluation is the only operation that upgrades or
populates the assertion.

Manifest and immutable release descriptor v1 remain readable and unchanged.
They display as `historical_v1_unassessed` and are ineligible for new release
planning. Foundry does not retrofit historical releases.

Candidate custody assertion 1.1 is current for new evaluations. Assertion 1.0
remains readable so existing candidates are not migrated merely by loading
them. Register 1.0 is different: it is historical-only and cannot authorize a
new custody decision.

## Candidate assertion

An evaluated assertion records:

- every logical source contribution and its provider/source/package identity;
- the exact complete set of root source artifact IDs, roles, SHA-256 hashes,
  and byte sizes;
- custody policy and register schema versions and byte hashes;
- the exact canonical fingerprints of the `outside_assets`,
  `foundry_workspace`, and `asset_library` logical roots;
- effective rights (`documented`, `missing`, or `disputed`);
- each license evidence binding's ID, original logical path, SHA-256, size,
  scope root, and documented-rights semantics;
- an evidence-freshness SHA-256 over the policy schema/hash, register
  schema/hash, and exact root-fingerprint map;
- a semantic assertion SHA-256 calculated only from candidate-relevant
  contribution, source, rights, and evidence facts.

Assertion 1.1 package roots, original evidence paths, and evidence scope roots
use `{logical_root, path}` objects. The logical-root vocabulary is closed and
the path component uses the portable path rules in the custody inventory
contract. Physical machine paths are never candidate authority.

The contribution union must equal the candidate's current root source artifact
set exactly. Missing, duplicate, or ambiguous package assignments fail.
Compound assets use multiple `source_contributions`; custody is not collapsed
to one provider.

## Approval and freshness

Approval requires evaluated, documented, fresh custody and verifies retained
evidence bytes. The approval snapshot binds the semantic assertion SHA-256 and
exact source inputs. A change to candidate source facts, evidence facts, or
rights facts makes approval stale. Unrelated custody-register changes do not.

For assertion 1.1, malformed root fingerprints or a mismatch between the
stored evidence-freshness SHA-256 and its canonical inputs is an explicit
freshness blocker. Creating the assertion first validates the supplied current
register against the policy and authoritative roots. Approval does not
silently rescan roots; a later root change requires a rebuilt register and
explicit custody reevaluation before that new evidence can be relied upon.

Any processing path that clears technical approval also clears custody approval
bindings.

## Immutable release

Release planning rechecks the approval-bound custody assertion and fails closed
for absent, historical-unassessed, missing, disputed, incomplete, or stale
custody. New release descriptors are schema v2.

Every sanitized license evidence file is copied byte-for-byte into the
release-relative `custody/evidence/` directory. The descriptor records both its
original logical path and immutable release path with hash, size, scope, and
semantics. Evidence paths are generated from safe components and content hashes.

Custody is a distinct axis from technical validation, human approval,
publication state, and Vandrel consumer acceptance. None implies another.

Release descriptor v2 retains its existing string fields for compatibility;
the planner projects qualified candidate paths to their relative POSIX path
components. Moving descriptor identity and custody paths to qualified objects
requires a separately versioned Library contract and is not part of assertion
1.1.

## Boundaries

Custody evaluation does not approve, publish, contact providers, mutate
historical releases, or write to Vandrel. It consumes the Library-owned policy
and deterministic custody register as read-only authority.
