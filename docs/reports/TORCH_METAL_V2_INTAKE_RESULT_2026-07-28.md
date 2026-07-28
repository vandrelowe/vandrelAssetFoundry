# Torch Metal v2 Intake Result

> Reference only. If this document conflicts with Foundry governance,
> architecture authority, or the relevant corridor contract, the higher
> authority wins.

status: candidate review and exact custody binding complete; unapproved and
unpublished
candidate: `quaternius_torch_metal_001`

## Candidate outcome

The documented Quaternius Torch_Metal glTF bundle completed the existing
credit-free static corridor headlessly through review. No network, provider,
paid, approval, publication, Library mutation, or Vandrel mutation occurred.

The candidate is revision 9, `review`, unapproved, and unpublished. Technical
inspection and the Godot sandbox import pass. After custody binding, a separate
integrity audit rehashed all 24 recorded artifacts successfully, including the
retained CC0 notice.

## Technical, timing, and storage proof

- Manifest SHA-256:
  `7fea1231255c6053cb1bc8055aaeb81570214a929c834726c902c26420735026`
- Processed GLB:
  `34bd0f9deb256b4620b3d802ad61e8203398e289b9f72f67a494b8feccd3e838`
- Geometry: 970 triangles, one mesh, one primitive
- Materials/textures: one material, three textures/images
- Rig/animation: zero skins, joints, or animations
- Physical footprint: 51 files, 50,867,125 bytes; within the planned
  30-55 MB band
- Candidate execution: 73.649 seconds from `asset.created` through
  `preview.multi_angle_rendered`

The original native batch-ledger write failed after candidate completion
because that process could not create its repository destination. The retained
execution transcript honestly reconstructs the immutable event timestamps. A
later native resume run through the repaired orchestrator skipped all eight
complete immutable stages, repeated the read-only audit, changed no candidate
state, and wrote a schema-valid, path-redacted ledger preserved at
`docs/reports/evidence/torch-metal/native-resume-ledger.json` with SHA-256
`f40b5fa40611a4049f7e2f924c944a09ef569805945d221d33b7faa6bb7ac3bc`.

## Visual proof

All four deterministic 2048x2048 views were inspected. They show a complete,
uncropped wall-torch model with a coherent metal basket, shaft, side support,
and wall mounting bracket. Front and back views establish the basket and
shaft; right and left views expose the bracket depth and attachment.

The supplied source has no flame, emission, light, or particle content. This
is an honest content limitation and consumer-side behavior boundary, not a
failed static-model import.

- Front SHA-256:
  `3cecd7f7d15b36bad427227595ebdf41b2f5013d993b79728d368a73bc2aa572`
- Right SHA-256:
  `04368807caa7753870269cde03645d29e9ee373b1d899149c307f33d1a6aea09`
- All four renderer measurements: `no_crop=true`,
  `useful_occupancy=true`

An independent adversarial reviewer reproduced the exact source union and
license hashes, inspected all four previews, and found no P1/P2 geometry,
material, framing, or authority defect in the candidate itself.

## Custody closure

The accepted ACL baseline `5bd7fd5` made all configured roots mutually
readable without relaxing release write policy. A fresh preflight under
`Nerdutron\CodexSandboxOffline` passed across three roots, 19 candidate roots,
11 release roots, 2,994 files, and 746 directories with zero unreadable targets
or setup issues.

A fresh full inventory and independent validation passed with 1,648 Outside
Assets records and 1,172 workspace records:

- Canonical register SHA-256:
  `88ee0e18780d16342e598b4b9f758f4a1a19dba4dc4d7f678d4f7a26cc10ceba`
- Operational report SHA-256:
  `29def49d1848210af4177a8d2ca3872826f6d95742ca03bb4b1000f84df76592`
- Package:
  `pkg:quaternius:500426d4f80eeeddff6b8423`
- Package rights: documented, promotion-eligible

The exact five-file source union is 6,899,540 bytes. All hashes and byte sizes
match the fresh register. The Quaternius Standard CC0 evidence is 837 bytes
with SHA-256
`edad12240087a33e08fc031e4e66c2b2b4b2a6d4f086339bde04f741b385fbda`.
The production bind retained those exact bytes, advanced only the candidate
from revision 8 to 9, and reproduced the independently predicted semantic
assertion exactly:
`2563b86f262d0ec65439b938b9fdc053182ed747e2bb25cffed33f39f0f862e5`.

Current release fitness reports integrity passing, custody
`evaluated_documented` and exact/fresh, no custody blockers, human approval
absent, Library release absent, Vandrel evidence absent, and release
eligibility false because approval is required.

## Workflow gap closed

The first run proved that `run-static-batch` checked ledger writability only
after mutating a candidate. The orchestrator now reserves the exclusive ledger
destination before its first stage and removes only its empty reservation on a
controlled failure. A negative test injects a denied ledger open and proves no
candidate directory is created. Production-path tests also inject failure after
ledger serialization and during `fsync`; both prove the incomplete reservation
is removed while the completed candidate mutation remains explicit, auditable,
unapproved, and unpublished. Existing destinations remain fail-closed.

The static-batch schema also has an explicit negative test rejecting
`bind-custody`, `approve`, and `release` stages. Batch intake therefore cannot
grow into a governance or publication shortcut.

## Adversarial modularity review

For the Torch intake path exercised here, the observed dependency flow was:

1. Provider or external intake records immutable source artifacts in the
   candidate manifest. Torch uses the external-package adapter and creates no
   provider task.
2. Custody inventory reads physical roots independently. Candidate custody
   consumes a validated register plus manifest-owned root source hashes and
   records one evaluated assertion and retained evidence.
3. Candidate processing and technical review consume selected source artifacts
   and add derived evidence. Neither grants approval.
4. Manual review consumes technical checks and fresh custody, then may create
   a hash-bound approval. Custody may invalidate a downstream approval when its
   semantic input changes; approval cannot rewrite custody.
5. Release planning consumes approved hashes and fresh custody read-only.
   Publication alone owns the explicit Asset Library write. No earlier layer
   imports or invokes publication.

No Torch-specific identifier or behavior appears in production source.
Quaternius does appear in the existing generic source-family classifier and its
tests, and the tracked Torch evidence now has a schema/hash contract test.
Torch-specific paths, the five-file glTF closure, CC0 binding, absence of
flame/emission, and static-prop intent otherwise remain in the plan, prompt,
evidence, and candidate data. The general batch and custody services operate
on typed plans, artifact roles, hashes, sizes, and package IDs.

This review does not claim that every dependency in the repository is one-way.
It characterizes only the executed intake/custody/review/release boundary; the
known reverse service dependency in `audit_asset.py` remains listed below.

The sprint-created change adds no cross-layer dependency: it changes only
batch-ledger reservation and its processing contract/tests. The new boundary
test makes forbidden governance stages unrepresentable in a batch plan.

Pre-existing debt remains bounded:

- `audit_asset.py` imports `APPROVAL_ROLES` from the review service. A later
  small unit should move that shared policy constant into a domain module so a
  read-only audit does not depend on a state-changing service.
- Production custody binding deliberately revalidates the complete register,
  even after an operator has run the validation CLI. This duplicates expensive
  scanning but preserves fail-closed freshness. Any optimization needs a
  separately designed, hash-bound validation receipt rather than shared mutable
  state.
- Several tests inject custody or approval fields directly through fixtures
  (`bind_documented_test_custody`, release-fitness helpers, and legacy
  processing tests). They are useful unit seams but bypass production services.
  A bounded follow-on should add one temporary-root integration test that uses
  production inventory, bind, approval, and release planning while still
  stopping before publication.

Existing negative coverage already proves missing/disputed custody cannot
approve, unapproved candidates cannot plan release, existing Library
destinations are not overwritten, and local intake does not require a provider.
The new batch boundary and ledger-preflight tests close the two gaps directly
exposed by this intake.
