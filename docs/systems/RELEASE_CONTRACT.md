# Review, Approval, and Release Contract

**Status:** Active for review, approval, dry-run planning, and explicit publication

## Ratified invariants

For `clean_body`, shared-animation compatibility evidence must resolve a cataloged,
audited immutable `animation_library` descriptor and primary payload by asset ID,
revision, descriptor SHA-256, and payload SHA-256. Arbitrary local `.res` files and
caller-authored compatibility claims are not release evidence. Clean-body processing
facts must be recomputed from the packaged glTF, buffer, and albedo bytes; Blender
action/NLA diagnostics and copied `.import` policy files are not release payloads.

- Approval is explicit and manual.
- Approval binds exact artifact roles to SHA-256 hashes.
- The neutral workflow policy owns allowed candidate-state transitions,
  approval artifact/check requirements, exact approval-binding reconciliation,
  and the single complete approval-invalidation operation. Services orchestrate
  persistence and event recording but do not redefine those rules.
- Model-primary approval requires passing GLB structure, nonempty geometry,
  lane triangle-budget, material, skeleton, and Godot sandbox-import checks.
- The `animation_library` lane is the sole model-free exception. Workflow
  policy instead requires the exact processed library, technical track report,
  isolated self-containment report, complete monitored-Godot report, exact
  three-body fixed-camera visual matrix, and every referenced visual artifact.
  All must be current, passing, rehashed, and approval-bound.
- Any approved artifact change invalidates approval.
- Approval invalidation clears the approval flag, timestamp, artifact hashes,
  custody assertion and source bindings, reviewer, and approval notes together.
  Explicit rejection then records its new rejection reason after invalidation.
- Release is dry-run by default.
- Release revisions are immutable, monotonically numbered, and limited to the
  canonical `r001` through `r999` layout.
- Publication never overwrites an existing release revision.
- A newly processed and explicitly re-approved candidate may publish the next
  immutable revision after an earlier release.
- Release creation and Git commit/push are separate user-controlled actions.
- A release contains technical facts and provenance, not Vandrel gameplay or
  mod authority.
- The `creature` lane is release-enabled only for a technically inspected,
  hash-bound compound result with complete continuous playback evidence and
  explicit visual review for the current model. Its packaged playback report
  records clip-family, deformation, scale, and ground-contact evidence without
  assigning species, prey, hunting, carcass, recipe, job, or runtime semantics.
- A humanoid release is a candidate package, not canonical Vandrel rig,
  animation, deformation, root-motion, or runtime acceptance.
- Humanoid release planning requires one ratified, hash-bound route for the
  exact approved processed model: humanoid-retarget compatibility,
  provider-native same-task playback, or Meshy-native H4 motion-assembly
  release evidence, or `clean_body_shared_animation` evidence.
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
- or evaluated provider custody assertion 1.2 with `foundry_workspace`-qualified
  provider package/evidence paths, the provider-provenance fingerprint, and the
  evidence-freshness fingerprint;
- for humanoids, mapping/donor compatibility facts, provider-native same-task
  playback facts, exact Meshy-native H4 assembly facts, or exact
  `clean_body_shared_animation` body/immutable-library facts, plus explicit
  candidate-only/runtime-unaccepted markers and a packaged report entry bound
  by release path, source artifact ID, SHA-256, and size;
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
`vandrel_runtime_accepted: false`. No route may claim consumer-side
runtime acceptance.

The `clean_body_shared_animation` route requires a body-only processed glTF
with no embedded animation output, exact external buffer/albedo dependencies,
and packages those dependencies beside the glTF so its authored relative URIs
remain directly importable,
canonical humanoid BoneMap/Rest Fixer validation, complete monitored Godot
evidence, manual fixed-view and shared-motion review, and an exact audited
immutable shared animation-library descriptor/payload binding. Its descriptor
remains `candidate_only: true` and `vandrel_runtime_accepted: false`.

The Meshy-native assembly route applies only when the current approved model
was produced by `blender_meshy_native_character_motion_assembly`. It requires
`meshy_native_character_release_playback` for that exact model hash, a packaged
`meshy_native_character_release_report`, the complete exact current source-root
assembly lineage, at least the accepted 29-clip baseline, and the report-bound
current continuous playback artifact set. Assembly report schemas 1.2 and 1.3
retain at least thirteen playback artifacts. Schema 1.4 is accepted only for an
exact 61-action model with exactly the registered representative set: `Idle_6`,
`Walking`, and `Pull_Radish`, using `Collect_Object` only when `Pull_Radish` is
absent. Missing, reordered, duplicated, additional, or substituted
representative clips fail closed. Schema 1.5 is accepted only for the exact
61-action repair model with the six registered repair-canary clips (`Idle_6`,
`Walking`, selected Eat, selected Butcher, `Heavy_Hammer_Swing`, and
`Walk_Forward_with_Bow_Aimed`). It independently decodes both numbered
JOINTS/WEIGHTS sets, at most eight normalized influences, zero unweighted
vertices, inverse binds, geometry, material bindings, and the exact embedded
character texture. Its normalized material must be opaque, base-color-only,
nonmetallic, roughness 0.8, and nonemissive. The exact current Godot import
artifact chain must resolve to the current model. The assembly source-influence
gate must pass and `consumer_blocking_reasons` must be empty; an above-eight
provider source therefore fails before release-validation runtime. All policies
retain the same exact-root,
hash, H4, skin, bind, material, texture, current-validation, and
bounded Godot import/playback with each imported duration reconciled to the
source duration within at most one 30 FPS frame of engine import quantization,
independently decoded policy-bound skin
with zero unweighted vertices, preserved bind/material/embedded-texture
signatures, and the H4 transfer deltas. Legacy reports retain the user-accepted
bounded provider-native hand orientation/weighting debt. Schema 1.5 instead
records that hand limitation only as an observation with
`pending_consumer_review` / `pending_vandrel_lightweight_f12`; neither approval
nor release planning may convert it to accepted debt before that consumer
review. All routes prove the H4 transfer introduced no additional hand
corruption. The descriptor retains the complete technical clip inventory in the
packaged report, does not assign gameplay action IDs, and remains
`vandrel_runtime_accepted: false`. That downstream runtime marker does not
substitute for, or weaken, the schema-1.5 technical source-influence gate.

Independent cross-character visual review, including the accepted nine-body-
class close-up hand review, is DevMaster release-decision evidence. It is not a
portable candidate-manifest dependency, is not synthesized as a Foundry
artifact, and is not projected into a release descriptor.

After an immutable release, a user-authorized numbered motion package may
supersede the candidate's prior source union without altering that release.
Processing invalidates approval, exact current-union custody and evidence are
re-established, and publication allocates the next unused release revision.
Neither planning nor publication rewrites an earlier revision or its catalog
entry.

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

An explicitly bounded multi-asset finalization may use `publish_releases` to
perform the same checks for a unique asset-ID set under one clean-tree
preflight and library lock. It promotes each immutable descriptor journal,
rehashes every package, replaces the catalog once with the complete set, and
then records each Foundry release. It does not authorize assets outside the
caller-supplied set or relax unrelated-change detection.

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

Recovery is evaluated before a prospective revision-cap failure becomes final.
When a visible `r999` might be the publication journal, publication may build
the exact current plan explicitly for revision 999 and run the same complete
recovery comparison. This exception can only finish that matching interrupted
transaction; it cannot allocate `r1000`, republish mismatched content, or weaken
the `r001..r999` cap for new releases.

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

Newly initialized Asset Library repositories pin LF only for `catalog.json`,
release descriptors, Godot wrapper scenes, and custody-evidence JSON. This
keeps immutable SHA-256 bindings byte-stable on Windows without globally
normalizing unrelated JSON or text files; binary release formats retain their
existing Git LFS rules.

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

## Scale-calibrated approval and handoff

Manual model-primary asset approval requires an approved scale calibration
bound to the exact current processed-model SHA-256. Approval fails closed when
calibration is absent or stale. The model-free `animation_library` lane has no
geometry or physical scale and is the sole scale-calibration exception; its
workflow-policy evidence gates remain mandatory. This is independent of
technical validation, custody, and visual-quality approval; all applicable
gates remain required.

Release descriptor v2 carries scale calibration when present: evaluated source dimensions, target height in meters, baseline uniform scale, bounded variation multipliers, reference standard, reviewer, timestamp, notes, and the processed-model and preview-report hashes. The record is a portable recommendation. It does not assign a Vandrel runtime path, placement behavior, collision, navigation, or gameplay authority. Historical already-approved candidates without calibration remain parse-compatible, while all approvals performed after this contract revision require calibration.
