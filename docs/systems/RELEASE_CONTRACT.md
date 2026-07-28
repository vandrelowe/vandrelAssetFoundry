# Review, Approval, and Release Contract

**Status:** Active for review, approval, dry-run planning, and explicit publication

## Ratified invariants

- Approval is explicit and manual.
- Approval binds exact artifact roles to SHA-256 hashes.
- Approval requires passing GLB structure, nonempty geometry, lane
  triangle-budget, material, skeleton, and Godot sandbox-import checks.
- Any approved artifact change invalidates approval.
- Release is dry-run by default.
- Release revisions are immutable, monotonically numbered, and limited to the
  canonical `r001` through `r999` layout.
- Publication never overwrites an existing release revision.
- A newly processed and explicitly re-approved candidate may publish the next
  immutable revision after an earlier release.
- Release creation and Git commit/push are separate user-controlled actions.
- A release contains technical facts and provenance, not Vandrel gameplay or
  mod authority.
- A humanoid release is a candidate package, not canonical Vandrel rig,
  animation, deformation, root-motion, or runtime acceptance.
- Humanoid release planning requires either a passing, hash-bound
  humanoid-retarget compatibility check or passing, hash-bound provider-native
  same-task playback evidence for the exact approved processed model.
- Provider-native humanoid evidence must prove that nonempty character
  geometry is actually bound to a resolvable imported skeleton; a static mesh
  placed beside an animated reference rig is not releasable.
- Publication requires the asset library to be an existing Git worktree with
  no unrelated changes.
- Binary model paths must resolve to the Git LFS `filter=lfs` attribute before
  any release files are copied.
- Foundry never initializes, commits, pushes, or repairs the asset-library
  repository as part of publication.

## One-time local library bootstrap

`init-library --confirm-init` is a separate, explicit maintenance action for a
configured library path that does not yet exist. It creates the complete
baseline in a unique sibling staging directory, initializes Git and local Git
LFS hooks, writes the LFS attributes, staging ignore, empty schema-versioned
catalog, and boundary README, creates one baseline commit, verifies a clean
worktree, then atomically renames the staging directory to the configured path.

Bootstrap refuses an existing destination, never adopts or repairs a directory,
never configures a remote, never pushes, and never touches Vandrel. A failed
bootstrap removes only its own uniquely created staging directory before the
destination becomes visible.

## Dry-run release descriptor

`release` performs a read-only plan. It verifies the approved artifact files
against their recorded hashes and sizes, checks that the lane permits release,
selects the next unused `rNNN` directory, and prints schema-versioned
`asset-release.json` content. Historical descriptor v1 remains byte-preserving
and parse-compatible. Planned descriptor v2 is a strict Foundry executable
projection and remains unratified pending separate Asset Library contract
authority. The plan contains:

- stable asset identity, lane, display name, and proposed revision;
- portable release paths, roles, hashes, sizes, and source artifact IDs;
- Godot import-validation result and declared wrapper-template intent;
- an explicit closed set of portable technical facts and collision
  recommendation; arbitrary manifest observations, provider URLs, operational
  report paths, and unknown fields are not projected;
- evaluated custody assertion 1.1 with logical-root-qualified package,
  evidence, and scope paths, the exact three register root fingerprints, and
  the evidence-freshness fingerprint;
- for humanoids, either mapping/donor compatibility facts or provider-native
  same-task playback facts, plus explicit candidate-only/runtime-unaccepted
  markers and a packaged report entry bound by release path, source artifact
  ID, SHA-256, and size;
- exact role, release path, source artifact ID, SHA-256, and size reconciliation
  for every packaged custody-evidence and humanoid-report reference; neither a
  model nor another static release role may substitute for evidence;
- Foundry manifest revision and approval provenance.

The plan does not create a directory, mutate the manifest or catalog, run Git,
or claim a Vandrel runtime destination.

The checked Foundry files
`schemas/release-descriptor-v1.compat.schema.json` and
`schemas/release-descriptor-v2.planned.schema.json` mirror the executable
models and compatibility fixtures. They are implementation guardrails, not
Asset Library ratification or a transfer of schema ownership.

The `humanoid` lane may publish only with the `humanoid_candidate` wrapper
intent and one ratified evidence route. The mapping route requires passing
`humanoid_retarget_compatibility`. The provider-native route requires the
approved FBX model and approved compact walk/run resources to derive from one
Meshy rigging task and pass bounded Godot playback. Its descriptor states
`shared_animation_pool_compatible: false` and
`vandrel_runtime_accepted: false`. Neither route may claim consumer-side
runtime acceptance.

A Workspace-relative humanoid report string is never a portable release
reference. Planning verifies the manifest-owned report bytes and includes the
report in `files`; the descriptor references only that packaged, hash-bound
entry.

## Publication transaction

`release --apply` is an explicit publication action. Under one library-wide
lock, it:

1. recomputes the release plan and verifies every approved source artifact;
2. verifies the target is a Git worktree and that its status contains no paths
   outside the exact recoverable transaction;
3. verifies every binary release path is governed by Git LFS;
4. copies files into a same-filesystem staging directory, hashes the copies,
   and writes the release descriptor last;
5. atomically renames the complete staging directory to the unused `rNNN`
   destination;
6. atomically replaces `catalog.json` with a schema-versioned entry containing
   the immutable descriptor hash; and
7. records the published revision in the Foundry manifest only after the
   library catalog is durable.

Normal `list` and `status` output surface that recorded `rNNN` revision while
retaining the approval workflow state. Publication does not invent a second
workflow state or replace the immutable library descriptor as release
authority.

Processing after publication preserves the prior release record as history but
invalidates approval and returns the new candidate to the normal validation
corridor. Once that candidate is explicitly approved, publication allocates the
next unused revision and updates the manifest's latest-release pointer.

No existing revision, catalog release entry, or staged destination is
overwritten. The catalog is the library discovery index; the release
descriptor remains authoritative for files inside its revision.

## Recovery and interruption rules

The directory rename is the publication point for immutable files. If a
process stops after that rename but before catalog or Foundry-manifest update,
a later identical `release --apply` recognizes the descriptor and artifact
hashes, completes the missing catalog entry, and then records the Foundry
release. Any mismatch fails closed.

Recovery validates the uncataloged descriptor through the same versioned
executable contract used by planning and library audit. The descriptor must be
canonical, agree with its `rNNN` directory, and match the complete current
release plan byte-for-byte after substituting that recovery revision. Recovery
also reconciles the exact declared file set and rechecks every file hash and
size before catalog replacement. Partial identity tuples, unknown descriptor
fields, role/source substitution, undeclared files, and changed bytes are not
recoverable and must leave the catalog and Foundry manifest unchanged.

Abandoned staging directories are never treated as releases and are not
silently deleted. They must not affect revision allocation. A retry uses a new
unique staging directory. Status checks permit only the exact matching
recoverable release and catalog path; unrelated changes still block recovery.

Catalog replacement cannot be atomic with directory rename across two paths,
so the matching descriptor is the recovery journal. This deliberately avoids
rollback by deletion after immutable files become visible.

## Git boundary

Publication leaves asset-library changes uncommitted for inspection. Git
commit and push are separate explicit operations. Foundry does not write to
Vandrel, emit a `res://` destination, or claim consumer acceptance.

## Read-only library audit

`audit-library` validates the configured library without changing it. It
requires a schema-versioned catalog, verifies every catalog descriptor hash,
checks descriptor identity and revision, rehashes every declared release file,
and reports release directories absent from the catalog. A recoverable
post-rename interruption therefore appears as an orphan until `release
--apply` completes that exact transaction.

The audit does not require a clean Git tree, mutate the Foundry workspace,
repair catalog data, delete staging evidence, commit, push, or inspect Vandrel.

## Read-only release-fitness view

`release-fitness ASSET_ID` composes existing manifest, candidate-audit,
release-planning, library-audit, and imported consumer-evidence authorities for
one candidate. It has human and JSON presentations of the same versioned
result. It does not create a second workflow or release-eligibility authority:
eligibility is the outcome of the existing dry-run release planner plus the
candidate integrity audit.

The view keeps these dimensions separate:

- current candidate identity, selected source, processed artifact, revision,
  and workflow state;
- candidate artifact/event integrity;
- each named technical check, its result, any exact hashes it records, and
  whether its processed-model binding is exact, stale, or absent;
- explicit human approval and approval-bound hashes;
- immutable library history and whether the latest descriptor file set equals
  the current approved set;
- imported Vandrel consumer evidence, which affects the displayed consumer
  result only when it is explicitly hash-bound to the current processed model.

Approval is shown with a separate exact/stale/unbound comparison against the
current artifact set. The newest valid consumer report is shown even when
stale or unbound; an older report that is still exact for the current complete
consumer input set is surfaced separately and never replaces the latest
evidence label.

Historical library revisions never imply current approval or consumer
acceptance. Missing, unbound, stale, rejected, blocked, passing, and unknown
consumer states remain distinct. The command is read-only, single-candidate,
offline, and does not inspect Vandrel directly.
