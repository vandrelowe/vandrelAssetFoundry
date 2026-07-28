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

## Bounded subprocess execution

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
