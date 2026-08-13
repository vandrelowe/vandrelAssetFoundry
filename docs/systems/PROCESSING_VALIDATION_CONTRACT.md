# Processing and Validation Contract

**Status:** Active — local processing and sandbox staging permitted

## Scope and authority

This corridor governs processors, technical inspection, generated Godot
validation sandboxes, tool execution, reports, and artifact derivation.
Processed and staged outputs remain Foundry candidates. They do not become
Vandrel runtime wrappers, catalog entries, or approved releases.

The real Vandrel checkout is always read-only and must never be used as a
processing directory, import target, cache, or validation sandbox.

## Immutable artifact protocol

Every processor must:

1. Load an existing manifest through `ManifestRepository`.
2. Require an artifact with a recorded SHA-256 and size.
3. Recalculate both before processing.
4. Write to a new asset-relative path without overwrite.
5. Flush the completed output and recalculate its hash and size.
6. Record a distinct artifact ID, role, stage, derivation, processor name, and
   processor version.
7. Persist the manifest with an expected-revision check.

Local Blender decimation is explicit and accepts a positive triangle target.
It records before/after counts and the target in the immutable processing
report. Foundry parses the produced GLB independently and rejects an output
that exceeds the requested target. Lane policy does not silently trigger
decimation.

Local review previews are derived evidence, not approval. Bounded Blender
renders a hash-verified processed GLB into a new transparent PNG and JSON
report, and retains bounded subprocess output as an immutable log artifact.
Rendering does not alter workflow state, approved hashes, release
state, or the source model.
When a scene contains skinned meshes, preview framing uses those meshes and
excludes unskinned helper geometry from camera bounds; the report records the
included and excluded mesh counts.
Batch preview rendering is sequential and selects only processed, review, or
approved candidates without an existing local preview. It skips all other
states and never replaces a preview.

The versioned static-batch orchestrator is also sequential and local-only. A
plan explicitly names candidate identity, source, lane, and requested
credit-free stages. The orchestrator composes the same creation, intake,
processing, inspection, Godot-sandbox, preview, and audit services used by
their individual CLI commands; it is not a second workflow implementation.
Each stage records UTC start/end time, duration, result/error category,
manifest revisions, artifact count/byte deltas, and manifest-derived next
actions in a new machine-readable ledger. Candidate failures are isolated and
the plan explicitly chooses continue or stop behavior. Reruns explicitly
choose either resume-by-skipping completed immutable stages or fail-on-complete;
they never silently duplicate a completed stage. Completion evidence must bind
to the currently selected source and current processed artifact. Read-only
integrity audit is deliberately repeatable and exempt from fail-on-complete.
When stop-on-failure prevents later candidates from running, their IDs remain
explicit in the ledger's `not_run_candidates` list.
The orchestrator reserves the new ledger destination before executing the
first candidate stage. A missing or unwritable ledger parent, an existing
destination, or failure to reserve the file therefore fails before candidate
state can change. Controlled failure before the final ledger flush removes
only that empty reservation.

Multi-angle batch records measure each generated PNG's nonzero-alpha pixel
fraction and foreground bounding-box fraction. A bounding-box fraction below
0.25 is flagged as excessive empty canvas for review; this observation neither
auto-crops nor replaces immutable evidence.

Multi-angle framing is owned by the existing preview renderer. It derives an
initial perspective-safe camera distance from evaluated world-space mesh
vertices, records the geometry bounds and projected margins, and may make at
most two bounded camera corrections from the current render's nonzero-alpha
bounding box. Corrections recenter and resize the camera only; they do not edit
meshes, materials, or saved source artifacts. Before registration, Foundry
independently measures every final PNG and rejects empty alpha or any
foreground bounding box that touches a frame edge. The immutable report records
initial geometry-fit facts, final camera parameters, alpha occupancy, pixel
margins, correction count, and explicit per-view/all-view no-crop assertions.
Useful occupancy remains a conservative flag; actual no-crop is a hard
registration condition.

Local shader experiments are derived review evidence, not material edits.
They render a hash-verified processed GLB through bounded Blender into new
baseline, tint, matte, and polished previews plus a contact sheet and measured
material report. Variants are whole-material changes only; they must not claim
that regions inside one atlas can be independently recolored without reliable
mask or material assignments. Experiments preserve workflow and approval state
and never replace the source model or textures.

Semantic-mask experiments accept a caller-supplied PNG only when every pixel is
one of the strict skin-red, fur/hair-green, cloth-blue, or accessories-white
palette entries and all four classes are present. Foundry copies that candidate
immutably, samples it as Non-Color with nearest filtering in bounded Blender,
and records baseline plus per-channel isolation previews, a contact sheet, a
report, and a process log. Palette and coverage checks prove file mechanics,
not semantic correctness. The report must set
`usable_for_material_authoring` to false until a later explicit acceptance
workflow reviews the isolation evidence for crossing. This experiment performs
no provider call, changes no source texture or model, preserves workflow and
approval state, and cannot promote or release the candidate.

The offline-vision recovery rehearsal manifest is a separate validation-only
contract. Its schema and blocked template inventory exact runtime, model,
fixture, and legacy-reference identities while real wheel hashes and accepted
canonical inference goldens remain absent. The readiness service performs JSON
Schema and fail-closed blocker validation only: it has no installer, network,
model-loading, inference, cache-write, cleanup, approval, or publication path.
Network, write, and execution requests fail before the manifest is read. A
manifest cannot declare readiness while any derived or declared blocker
remains. Adding a future execution path requires a separately ratified
contract revision, hash-locked recovery inputs, and bounded subprocess rules.

Deterministic texture-region recoloring is an explicit local processor. It
accepts a caller-supplied grayscale PNG aligned to the current GLB's sole
base-color texture and a declared RGB color. The mask must select a nonempty,
bounded region and match the texture dimensions. Bounded Blender colorizes
only the selected pixels while preserving source luminance, embeds the changed
texture in a new immutable GLB, and verifies that the animation count is
unchanged. Foundry records an immutable copy of the mask, a report, and a
bounded process log, all bound to the input and output hashes. The operation
resets technical/Godot validation and approval. Mask mechanics do not prove
semantic correctness; the resulting model requires a new local preview and
visual review before approval.

Same-skeleton animation grafting is an explicit local processor. It requires
the target and donor processed GLBs to have exactly the same unique joint names
and joint-parent relationships, plus numerically matching local joint rest
transforms. A rest-transform mismatch requires actual humanoid retargeting and
must fail before an output is created. The graft replaces the target animation
array with the donor library, copying only donor animation samplers, channels,
their accessors, and referenced embedded buffer views; animation targets are
remapped to unique target nodes by exact name. Sparse accessors, external or
multiple buffers, unsupported channel targets, missing node names, and
duplicate donor clip names fail closed.

The graft creates a new immutable processed GLB plus a hash-bound report and
log. It preserves both inputs, resets technical/Godot validation and approval,
and returns the target to processed state. A structurally valid graft still
requires renewed inspection, Godot import, and visual playback review because
local rest equality alone does not prove inverse-bind or deformation quality.

Rest-pose animation retargeting is a separate bounded Blender processor for
humanoid rigs with exact joint names and hierarchy but differing rest
transforms. It samples donor clips at 30 FPS, applies world-space rest
correction to the hips, transfers child-bone local pose bases onto the target
rest skeleton, uniformly scales translation channels by measured skeleton
extent, and bakes new target actions. It preserves the target mesh, materials,
skin, and rest skeleton; donor geometry is never exported.

The processor creates a new immutable GLB plus a report and bounded process log
bound to both input hashes and the output hash. It resets validation and
approval. Representative animation samples must be rendered from the produced
GLB for gross-deformation, limb-orientation, root-displacement, and foot-contact
review before approval. Sampling evidence does not itself grant visual
acceptance or assign Vandrel clip semantics.

**Production approval suspension (2026-07-27):** output from
`blender_rest_pose_retarget` cannot currently pass Foundry approval. A live
Meshy-character test exposed a unit-sensitive hips-translation bake and a
Godot skin/import failure that representative Blender stills did not catch.
The processor may remain available for bounded forensic experiments, but its
output must not be approved, released, or copied into Vandrel until a later
ratified revision proves continuous Godot deformation and fixed-camera motion.

For Meshy-rigged characters, the preferred current corridor preserves the
provider-native FBX character and its same-task `withSkin` animation FBXs.
Godot imports those files directly and may load their animations into the
matching character's `AnimationPlayer`; this route performs no Blender bake
and must still receive continuous playback and visual validation.

`prepare-native-character` automates that route in an asset-scoped temporary
Godot project. It requires the rigged character, walking, and running FBX
artifacts to share one provider task. New downloads carry distinct walk/run
roles; the one legacy downloader layout is accepted only when exactly two FBX
animation artifacts exist in its documented walk-then-run order, and that
fallback is recorded in evidence.

The bounded validator imports the three provider-native FBXs, extracts compact
looping walk/run `Animation` resources, loads them onto the character's own
`AnimationPlayer`, and checks geometry, triangle count, textured material
presence, humanoid skeleton size, required clip aliases, and finite sampled
bone scales. At least one nonempty, visible `MeshInstance3D` must also have
both a Godot `Skin` and a resolvable `Skeleton3D` binding. Merely placing
static visible geometry beside an animated or hidden reference rig does not
satisfy the humanoid lane. The report records visible skinned and unskinned
mesh counts plus the visible triangle count actually bound to the rig. The
validator then discards duplicate animation meshes, extracted textures, import
caches, and its temporary validation script before promoting the candidate.

The promoted wrapper is validation and release-template evidence. It does not
choose a Vandrel `res://` destination, establish gameplay clip semantics, or
prove compatibility with a different character or shared animation pool.
Consumer integration should set the character FBX's embedded-texture handling
to `Embed as Basis Universal`; this preserves the working material while
avoiding an unpacked duplicate PNG in the consumer source tree.

User-selected local Meshy merged-animation archives may enter the distinct
`meshy-native-canary` corridor when the archive and its sole FBX member are
both retained as separate immutable source roots. Intake rejects traversal,
links, encryption, unsupported compression, excessive expansion, missing or
additional members, and caller/hash disagreement. After the initial source
hash, intake copies the archive once into its operation-owned temporary root,
rehashes that copy, and performs all archive inspection and extraction only
from the verified copy. Promoted archive, member, and report bytes are rehashed
before manifest save and after any ambiguous-save reconciliation. The intake
service records provider lookup as not performed and embedded metadata only as
actually inspected; separate account research remains separate evidence. Local
selection does not manufacture provider provenance or release rights.

`normalize-meshy-native-animations` is a bounded, profile-specific processor
for the observed Meshy 24-joint hierarchy. It is not a general retargeter. It
requires the exact archive/FBX root union, one native armature and skin,
materials, ten unique actions, the named Running and Walking actions, and zero
unweighted vertices. It preserves bone rest matrices, vertices, vertex-group
weights, and the armature modifier relationship; applies one deterministic
positive-90-degree X world normalization; subtracts each clip's starting hips
translation; raises the full clip's lowest sampled geometry point to ground;
and retains every exact action name. It creates one combined GLB and ten
single-action GLBs, then independently verifies material, skin, 24 joints,
animation counts, and exact names before manifest registration. All inputs are
rehashed after the subprocess. The immutable report binds a separate bounded
process log containing tool/version, portable logical arguments, exit state,
UTC start/end and duration, timeout/output limits, and bounded redacted
stdout/stderr.

`render-meshy-native-playback` produces neutral-gray lateral animated WebP
evidence for all ten exact actions and binds it to the current normalized GLB
and report hashes. Blender establishes the normalized 30 FPS timebase before
GLB import. Every encoded WebP duration must match the bound normalization clip
duration within 0.002 seconds; this gate applies to every named and unresolved
action. Blender writes frames and its adapter report only under an
operation-owned temporary root. Foundry validates there, creates the final
directory and files without overwrite, and follows exact-target manifest-save
reconciliation: exact committed outputs survive post-replace/event/lock
ambiguity, while only a proven old unreferencing manifest permits rollback.
The final report references registered WebP identities, never deleted temporary
PNG frames, and binds a separate bounded process log. Model and normalization
report inputs are rehashed after the subprocess and again before manifest save.
Playback evidence records root/ground bounds and semantic limitations, but does
not confer visual acceptance, custody, approval, release, or gameplay meaning.

A carrier canary proves only the Meshy-native processing corridor. For a real
Brukk or Takka adoption, the preferred subsequent corridor is exact account/task
resolution followed by intake of the character's provider-native Meshy biped
auto-rig output, retaining its provider-native skeleton, skin, bind matrices,
materials, and textures. It is not local binding of an unrigged export and is
not a Mixamo migration bridge. Provider calls, downloads, and spend remain
separately authorized actions.

User-authorized local Meshy-native character ZIPs use a separate, narrow
four-root intake: the original ZIP, `Character_output.fbx`, its exact
`Animation_Walking_withSkin.fbx`, and the PNG texture. The service copies and
rehashes the ZIP once before inspecting or extracting it, records supplied task
identities only as `user_observed_provider_metadata`, and records license data
as `not_inspected` unless the service itself inspected and hash-bound it.
Direct inspection requires the exact four-root union, one armature, skinned
geometry, nonempty joints, and zero unweighted vertices in both FBXs. It emits
numbered neutral-gray Walking WebP and bounded process evidence from an
operation-owned temporary root, then compares joint names and in-joint
hierarchy with the current fixed 24-joint canary. That comparison establishes
only skeleton compatibility evidence: it neither retargets canary motions nor
asserts that they are safe to adopt. The candidate remains unreleased and
unapproved; no game identity, Mixamo bridge, or Vandrel integration is created.
The service rehashes every manifest-owned root immediately after Blender,
again immediately before promoting final outputs and saving the manifest, and
again after a successful or exact-target-reconciled save alongside every
registered output. A changed source root fails before promotion; ambiguous
save recovery preserves outputs only when the live manifest is proven to be
the exact intended target.

An authorized authenticated API retrieval uses the same intake authority with
a distinct, truthful four-root profile: exact provider `Character_output.fbx`,
`Character_output.glb`, `Animation_Walking_withSkin.fbx`, and
`Animation_Running_withSkin.fbx`. The service never fabricates a provider ZIP.
It extracts the single embedded PNG from the exact GLB, records that PNG as a
derived artifact whose sole parent is the GLB root, retains only a sanitized
zero-credit task receipt and user-observed identity crosswalk, and stores no
signed URL or secret. Intake requires `SUCCEEDED`, progress 100, consumed
credits zero, and an unchanged observed account balance. Inspection binds
Running hierarchy, bind signature, skin, duration, and zero-unweighted facts in
addition to the historical Character/Walking checks. Both profiles remain
unreleased technical candidates and use the same exact-target save recovery.

`assemble-meshy-native-character-motion` extends that same native corridor for
an inspected real character. It copies the accepted current canary model and
normalization report into the character candidate as two immutable source
contributions; together with the exact four character roots they form the
complete six-root union. Blender preserves the real character mesh, 24-joint
hierarchy and inverse-bind relationship, material, and exact texture while
mapping each canary bone's posed global orientation through one constant
source-to-target armature-space correction. It traverses the target hierarchy
and reconstructs each target local pose basis through the already-posed parent
and target local rest basis. The rotational result never receives an
incompatible per-bone target-global-rest postfactor, target rest translations
and bone lengths remain authoritative, and only Hips receives the declared
skeleton-extent translation scale and root/ground reconciliation. Historical
schema 1.1-1.4 outputs use the reviewed deterministic top-four policy: positive
bone influences are ordered by descending weight with a bone-name tie-break,
four are retained and renormalized, and the report records the source maximum,
affected-vertex count, and discarded source-weight total. Those immutable
outputs do not claim exact native skin-weight preservation.

Schema 1.5 is the bounded provider-skin/material repair profile. It is allowed
to create a fresh attempt from a processed, review, or released-approved
Meshy-native candidate, but never rewrites an earlier attempt or prior release.
A review retry is ordinary reprocessing: success transactionally clears stale
validation, scale, and approval bindings and returns the candidate to
`processed`; prior report and release history remain immutable.
The processor explicitly limits provider influences to eight using the same
deterministic ordering. It exports all retained influences as
`JOINTS_0`/`WEIGHTS_0` and `JOINTS_1`/`WEIGHTS_1`. It may claim no positive
influence identity was dropped only when the FBX has no positive
ninth-or-later influence. Numeric exact preservation is a separate signature
comparison and remains false when required normalization changes weight values.
When the FBX exceeds eight, the report must state the exact affected-vertex
count and discarded weight above eight and keep both no-drop and exact
preservation false. It cannot hide that loss through exporter-side truncation.

The repair material policy binds the exact source image to base color only,
removes full-strength base/emissive reuse when no distinct authored emissive
mask exists, requires zero emission, opaque alpha, metallic factor zero, and
roughness factor 0.8, and preserves the exported normal/tangent geometry
payload. Overbright specular factors and forced `BLEND` fail inspection. The
repair produces six synchronized 768-pixel-per-panel continuous comparisons:
original provider FBX weights with the exact target H4 action, immutable r001,
and the repaired output for Idle, Walking, selected Eat, selected Butcher, one
hammer control, and one bow control. This evidence is diagnostic and cannot set
`vandrel_runtime_accepted`. The neutral-gray comparison proves only pose and
skin continuity; it does not exercise or visually accept the repaired texture
or PBR material appearance. The actual Vandrel lightweight F12 composition
remains the decisive consumer gate. A schema-1.5 report always retains
`vandrel_ready: false` and records the F12/adoption step as its remaining gate,
not as a technical-release `consumer_blocking_reason`. A source with at most
eight positive influences records a passing top-eight source gate and an empty
consumer-blocker list. If the provider source exceeds eight influences, it
records a failed top-eight source gate and the sole explicit consumer blocker
`greater_than_eight_source_influences`.
Index grafting, Mixamo retargeting, and provider-native character migration are
forbidden. Clip timing remains bound to the canary normalization report, and
each clip receives target-mesh XY root baseline and ground reconciliation.

Complete numbered multi-motion packages may be added before the first character
assembly. In that case the one assembly transaction imports the accepted canary
roots and every complete motion-package root union together; it does not create
a redundant ten-action intermediate model. The default `release_review`
evidence profile retains the established release-facing playback selection.
The `representative_batch` profile keeps the complete runtime action inventory
while rendering exactly default Idle, Walking, and one available work action
(`Pull_Radish`, with `Collect_Object` only as the bounded historical-package
fallback). The profile is hash-bound in report schema 1.4. It may enter the
Meshy-native technical release validator only when the current model contains
the exact complete 61-action inventory, all three registered playback artifacts
resolve and rehash, the complete source-root lineage remains exact, and the
independent H4, skin, bind, material, texture, and Godot gates pass. Schema 1.2
and 1.3 reports retain the established release-review policy of at least thirteen
registered playback clips. Neither profile alone confers visual acceptance,
approval, release, publication, or Vandrel runtime acceptance.

The `repair_canary` schema-1.5 profile may enter the same specialized technical
release validator only with the exact 61-action inventory and exact six
registered repair clips. The validator independently decodes the final GLB with
the existing top-eight repaired-skin inspector, matches its full skin, inverse
bind, geometry, material, and embedded-texture facts to both report-bound
reference and final proofs, resolves the passing ordinary Godot report through
project, wrapper, and staged-model ancestry to the exact current model, and
requires the top-eight source gate to pass with no consumer blockers. It keeps
`vandrel_ready` and `vandrel_runtime_accepted` false pending consumer adoption;
it also records provider-native hand behavior only as a pending consumer-review
observation, not accepted visual debt. Those downstream markers cannot launder
an above-eight technical failure or a missing Vandrel F12 visual decision.

Before adding actions, Blender exports a temporary policy-bound reference GLB.
After the animated export, the service independently decodes both GLBs. Legacy
profiles require exactly `JOINTS_0` and `WEIGHTS_0` and at most four positive
influences. The schema-1.5 repair profile instead requires both numbered joint
and weight sets and at most eight positive influences. Both profiles require
normalized nonzero weights for every exported vertex, matching skin payload,
matching inverse bind matrices, matching geometry attributes, matching
primitive/material bindings, and the exact embedded source-texture bytes. The
schema-1.5 material decoder additionally rejects identical full-strength
base/emissive use, non-opaque alpha, nonzero emission or metallic, roughness
other than 0.8, and overbright specular color. Godot 4.6 consumer support is
demonstrated only when the exact repaired outputs import with
`ARRAY_FLAG_USE_8_BONE_WEIGHTS` and eight bone/weight array values per vertex;
the presence of glTF attributes alone is insufficient. The service also checks
geometry, joints, action count/names, continuous playback duration, and every
input/output hash.
All six manifest-owned roots are rehashed again immediately before manifest
replacement and with every registered output after success or exact-target
save reconciliation. A retry creates a new numbered model/report/playback
attempt and never rewrites an earlier attempt.

The multi-entry extension of this corridor adds numbered immutable packages.
Each package retains one exact archive root, every exact `withSkin` FBX entry
root, and the exact texture root. Its intake report derives from that complete
package contribution set; it never collapses an archive into a fictitious
merged-FBX lineage. Historical package 001 remains the exact twenty-FBX,
one-texture export. Later packages accept a bounded nonempty set of safe
`withSkin` entries plus exactly one texture and record their archive-hash
source qualifier. Every manifest-owned root is verified before processing,
immediately before manifest replacement, and after success or exact-target
reconciliation. Compatibility is established from the actual 24-joint
hierarchy, rest/container basis, and action payload rather than filename or
carrier label. The exact legacy UUID
`019fee70-fd9d-7b6e-914a-d6dad2a49eeb` remains in package-001 provenance but
is excluded from assembly because it carries the known positive-90-degree
legacy container normalization. No other entry may be silently excluded.

Extended assembly retains the accepted canary actions plus every compatible
entry from every numbered package. Runtime collision handling compares
normalized motion curves and durations across the complete source set, not
carrier bytes or filenames. Exact curve identity deduplicates only the runtime
action while retaining every source contribution in lineage. A material
difference receives a stable archive-hash-qualified internal ID and remains
available beside the existing action. Duplicate runtime names are forbidden.
Reports state source-entry, excluded-entry, duplicate-curve, and final unique
runtime-action counts separately and bind the complete current source union.

Provider UI labels for the four UUID actions live only in a fresh immutable
semantic evidence artifact as `user_observed_provider_metadata`; they do not
enter generic manifest identity or gameplay fields. Both observed variants for
each squat-eat and squat-butcher semantic remain present. The comparison report
may select the best currently visible variant while explicitly retaining motion
debt. The frozen candidate mappings are eating
`019fe8ca-a6c4-7968-822f-92efebbab5a4` and butchering
`019fe8d7-ed16-7b82-a594-728d821ee711`; alternates remain present. `Idle_6`
is the selected default idle. `Dead` is the selected death motion with a
consumer policy of play once and hold its final frame; a motionless final
ten-frame plateau is not a Foundry requirement. `Stand_To_Side_Lying` is a
lie-down/held-pose action, not death. `Female_` in the two fruit-picking source
filenames is provenance text only and imposes no gender restriction. The
extended report may mark the motion set complete while keeping
`vandrel_ready: false` until Vandrel performs its separate consumer validation
and explicitly adopts the package.

A pass-through processor still creates a physically distinct output. It may
preserve bytes and hashes, but it must not alias the source file through a hard
link.

External model import is a local source-intake operation, not a provider task.
GLB intake validates the container before copying. FBX and glTF package intake
first copies the original model and required sidecars into an immutable package
directory, then converts the copy through bounded Blender. glTF URI resolution
allows only declared, same-directory local buffers/images and rejects traversal
and network references. Intake records raw and converted hashes, tool version,
structured warnings, and bounded logs; it retains no machine-absolute source
path and enters the same downloaded-state corridor as provider output.

## Technical reports

- Reports are JSON objects with an explicit schema version, asset ID, artifact
  ID and hash, measured facts, and named checks.
- Reports use new numbered paths and never overwrite prior evidence.
- A report records observations; it does not silently repair an artifact.
- Lane validation compares measured facts with the checked-in lane policy.
- Empty geometry cannot pass review; humanoid lanes require at least one skin
  with at least one valid joint reference.
- Unknown or unsupported structures fail closed with a readable error.
- Approval is not implied by a passing technical report.
- Review-state reinspection may refresh the named technical checks for older
  candidates. It preserves independent validator checks such as Godot import
  evidence and never changes workflow state or approval.

## Godot sandbox staging

- Staging occurs only below the asset's `godot_staging/` directory.
- A staging directory is deterministic from the selected artifact identity and
  hash and is immutable once complete.
- The sandbox contains its own `project.godot`, copied candidate model, and
  validation-only wrapper scene.
- Generated scenes may use sandbox-local `res://` paths only. They must not
  emit or claim Vandrel runtime destinations.
- Wrapper scenes instance the GLB; the imported GLB scene is not itself treated
  as a final game wrapper.
- Lane collision policy is recorded as a recommendation. Version 1 creates no
  collision or navigation nodes automatically.

## Candidate-free package preview

- `preview-package` is a local visual-inspection corridor for a ZIP before
  candidate intake. It creates no manifest, workflow event, approval, or release.
- Each preview is an immutable, hash-named sandbox below
  `workspace/temp/package_previews/` unless an explicit output root is supplied.
- ZIP extraction rejects traversal, absolute or ambiguous paths, symbolic links,
  case collisions, excessive entry counts, excessive sizes, and suspicious
  compression ratios. Only supported models and their texture/buffer sidecars
  are extracted.
- The generated standalone Godot project may show models, embedded animations,
  a metre grid, and scale references. Its report is technical inventory and
  visual evidence only; it cannot establish import, rig, scale, or approval facts.
- The command performs only bounded headless import/readiness validation.
  Interactive `--launch` is unavailable while the exclusive Foundry runtime
  gate is held and fails before sandbox creation or process spawn. The corridor
  makes no provider/network call and writes nothing to candidate workspaces,
  the Asset Library, or Vandrel.

## Offline animated-creature package inspection

- `inspect-creature-package` reads a ZIP without extracting into a candidate,
  contacting a provider, or launching Godot. Archive traversal, ambiguous
  paths, symbolic links, collisions, and excessive expansion fail closed.
- Version 1 requires exactly one base/final-rig GLB and exactly one GLB for
  each `idle`, `walk`, and `run` semantic. Each clip must contain one named,
  positive-duration animation and one nonempty skin with unique joint names.
- The report separately compares animated joint names, hierarchy, and finite
  rest transforms; base-rig containment; base shared hierarchy; and base
  shared rest transforms. A coherent clip set does not imply direct transfer
  to the base rig or to another creature.
- Creature-family and rig-family values are Foundry technical suggestions.
  They do not register a canonical Vandrel gameplay or animation taxonomy.
- The `creature` lane requires a skeleton but remains release-disabled until
  its playback, custody, approval, and downstream taxonomy contracts are
  separately ratified.

## Bounded subprocess execution

### Compound creature derivation

The `blender_compound_creature_derivation` processor is the sole bounded
multi-contribution creature corridor. It consumes exactly one immutable primary
mesh root declared as `mesh_material_source`, one or more immutable used texture
roots declared as `material_dependency`, and exactly one distinct immutable
root declared as `rig_animation_donor`. This declared set must equal the complete
current root source set. The service verifies every manifest-bound hash and size
before and after the subprocess. Caller-selected output paths are not accepted.

The service allocates new, contained `processed/compound_creature/` and
`reports/compound-creature-*.json` destinations. The adapter writes into an
operation-owned temporary directory; existing final destinations fail closed.
Only verified output and report bytes are promoted by create-only same-volume
hard links; the operation-root cleanup owns the temporary links. A pre-commit
manifest failure removes them; a post-replace or partial-event failure follows
the manifest journal's exact ambiguous-save diagnosis and reconciliation and
never deletes output referenced by a durable target manifest. The manifest
records the derived model with every root artifact ID in `derived_from`; the report binds
all contributions, their declared roles, paths, hashes, sizes, processor and
tool versions, exact portable logical/redacted arguments (artifact IDs, roles,
and relative destinations), transformation facts, output hash and size,
and the complete contribution union. A composite is never recorded as an
external pass-through source.

Successful derivation returns the workflow to `processed`, clears all prior
technical validation checks, scale calibration, and approval bindings. The
processor and every processed descendant are approval-suspended. Custody for
the complete contribution union
and separate creature playback/release gates must be ratified and pass before
approval is possible. This corridor records no species, prey, hunting,
carcass, recipe, job, or other gameplay semantics.

A future Godot or Blender subprocess adapter is permitted only when it:

- executes an explicitly configured absolute executable path;
- uses an argument vector without shell evaluation;
- uses the generated workspace sandbox as its working directory;
- has a configured finite timeout and terminates the child on expiry;
- captures bounded standard output and error into a numbered report;
- records executable version, arguments with secrets removed, exit status,
  start/end times, and timeout state;
- never passes provider credentials or inherits them when they are unnecessary;
- treats nonzero exit, timeout, missing reports, or mutated inputs as failure;
- never writes into the real Vandrel checkout or asset library.

Normal tests use fake process runners. Live tool tests are opt-in and may not be
required by CI.

Godot command-line behavior follows the stable engine documentation:
<https://docs.godotengine.org/en/stable/tutorials/editor/command_line_tutorial.html>.
The validator uses `--headless`, `--path`, `--import`, and a sandbox-local log.

Blender command-line behavior follows the official manual:
<https://docs.blender.org/manual/en/latest/advanced/command_line/arguments.html>.
The adapter uses background mode, factory startup, disabled automatic embedded
scripts, an explicit checked-in Python script, and a nonzero Python exception
exit code. A Blender result is accepted only when the subprocess succeeds, the
new GLB parses, and the versioned report exists.

## Failure recovery

- Remove only incomplete files and directories created by the current
  operation when commit is known not to have occurred.
- If manifest replacement may already have succeeded before a later journal
  error, retain the immutable output for reconciliation.
- Never delete or overwrite an earlier source, processed artifact, staging
  directory, or report during retry.
- A retry receives a new artifact/report identity unless it can prove that an
  existing deterministic output is complete and hash-identical.

## Required scale calibration

Every newly approved candidate requires an explicit real-world scale calibration for the current processed model. The bounded Blender preview records evaluated world-space minimum, maximum, dimensions, and the `z` height axis for the exact processed artifact. `calibrate-scale` binds that immutable preview report and processed-model SHA-256 to a reviewer-declared target height in meters, computes `baseline_uniform_scale = target_height / evaluated_source_height`, and records bounded variation multipliers.

The scale-review preview visibly includes a 1-meter cube and a 1.8-meter human reference; those reference meshes affect camera framing but are excluded from the recorded candidate bounds. Calibration is technical handoff evidence, not gameplay classification. Foundry does not infer whether an asset is a tree, character, rock, construction, collision object, or navigation blocker. A changed processed-model hash makes the calibration stale and blocks approval until a new preview and calibration are recorded.
