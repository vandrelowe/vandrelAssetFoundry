# DM-004 Shaman Rejection Triage

**Program:** Asset Foundry  
**Directive:** DM-004  
**Observed:** 2026-07-27  
**Result:** Rejection imported; candidate blocked; one credit-free forensic
experiment proposed but not executed

```yaml
program: Asset Foundry
directive_id: DM-004
repository: C:\Dev\vandrelAssetFoundry
branch: main
head_commit: recorded in director handoff; this document cannot bind its own commit hash
remote_sync: origin/main was already one commit behind local before DM-004; push is not authorized
working_tree: bounded DM-004 source, contract, test, and report changes
status: partial
delivered:
  - exact hash-bound Vandrel rejection imported into Foundry
  - additive consumer-ledger compatibility update
  - defect-stage ownership trace
  - one bounded credit-free forensic repair experiment proposal
changed_files:
  - src/vandrel_foundry/domain/consumer_validation.py
  - src/vandrel_foundry/services/import_consumer_validation.py
  - tests/test_import_consumer_validation.py
  - docs/systems/INTEROPERABILITY_CONTRACT.md
  - docs/reports/DM-004_SHAMAN_REJECTION_TRIAGE_2026-07-27.md
automated_evidence:
  - ruff check --no-cache .: pass
  - ruff format --check --no-cache .: pass
  - pytest: 146 passed, 2 skipped
  - candidate integrity audit: pass, 214 artifacts
visual_evidence:
  - Vandrel continuous movie and exact-hash full-resolution closeups
  - existing immutable Foundry/provider previews compared as historical stage evidence
manual_review:
  result: reject current candidate
  reason: three generic asset blockers; repair experiment not yet run
known_failures:
  - no provider-native Idle output exists for the recorded rigging task
  - exact FBX shows unacceptable face/neck and crown/hair defects in Godot
  - cross-render origin of the two visible model defects is not yet isolated
  - no current exact-hash release exists
  - remote synchronization remains unauthorized
cross_program_requests:
  - Vandrel should retain the current evidence and await a new exact hash set
decisions_needed: []
recommended_next:
  - issue DM-005 for the bounded no-spend cross-render/repair experiment below
```

## Imported rejection

The first import attempt failed closed because Vandrel's current version `1.0`
ledger contains additive exact-provenance binding fields that the older
Foundry reader forbade. The reader now models and retains:

- manifest revision;
- model, walk, and run artifact IDs and hashes;
- provider task key and provider task ID; and
- optional matching library revision.

These fields remain evidence-only. As before, only exact asset ID and current
processed-model hash control the promotion-affecting generic-defect gate. The
interoperability contract reference now identifies Vandrel closeout commit
`16cbf78d`, and a focused test proves that the added fields survive import.

The successful import produced:

| Fact | Value |
|---|---|
| Foundry manifest revision | `85` |
| Workflow | `blocked` |
| Validation result | `failed` |
| Approval | `false`, no bound hashes |
| Report artifact | `vandrel_consumer_validation_report_001` |
| Report path | `reports/vandrel-consumer-validation-001.json` |
| Report SHA-256 | `e116a3f70de98d3e77702609c341323ba2ef59fe3b5c17c27fd6cea977a94bbc` |
| Source ledger SHA-256 | `359f7cf92030e6843e733a7a0440877019b24fed33c3298a30fee11de6aa8a66` |
| Bound model SHA-256 | `e583fa38493609685df0f01f519f9311b772b352b7a34fafc54e119771e05d4f` |
| Consumer status | `blocked` |
| Generic gate | failed |

The post-import candidate audit passes all 214 immutable artifacts, derivation
edges, approval bindings, and event-history checks. The failure is a quality
gate, not an integrity failure.

## Visual evidence inspected

The authoritative consumer evidence is:

- Continuous 18.22-second movie:
  `C:\Dev\vandrel\debug_output\character_lab_review_20260727_183257.avi`,
  SHA-256
  `27bc2f3624541e76057b2ee46a6dccf1bad033cae9dbf96d281fce4ba53c2f59`.
- Frontal closeup:
  `closeup_skull_hair_front.png`, SHA-256
  `56e4d8053d1a3ed6f02dc8cfb3a750e83f98bfc7f68591031105a51ed37550aa`.
- Side closeup:
  `closeup_skull_hair_side.png`, SHA-256
  `76a576d55b0ec0053444a16f413ec3a9e6db4392bda5cddd1eacff9ec2fd8d05`.

The full-resolution frontal image makes the horizontal lower-face band and
open crown panels unmistakable. The side image exposes overlapping,
unsupported opaque planes around the crown and silhouette.

The provider beauty thumbnail
`preview/meshy_retexture_beauty_001/thumbnail_001.png` (SHA-256
`ec562743e23e301da8aee9d84c1df6db57a63c59d175e99ddbc1a47f6b790d69`)
already shows the planar/spiked hair construction before rigging, but its
distance and angle cannot prove the precise open-panel defect. Foundry's
existing local previews are similarly too distant to validate the face or
crown. Their earlier apparent acceptability was a deficient evidence gate.

## Defect-stage trace

### 1. Missing Idle: package incompleteness

The succeeded Meshy rigging response exposes exactly these provider-native
basic animations:

- walking with skin, GLB and FBX;
- running with skin, GLB and FBX; and
- their armature-only variants.

There is no Idle URL or unused Idle artifact. Foundry downloaded and prepared
only the available Walk and Run outputs. Its provider-native loader likewise
adds only `Walk` and `Run`.

Vandrel mapped the embedded 0.001-second base/rest clip to `Idle` as a
diagnostic choice so the absence could be observed continuously. That mapping
did not turn the base T-pose into a provider Idle and did not cause the package
incompleteness.

Ownership: **Asset Foundry candidate completeness**, originating in available
provider output. No same-task provider Idle exists. Foundry must not rename
Walk, Run, or the T-pose as Idle.

Disposition: if the model becomes otherwise repairable, a deliberate neutral,
no-motion idle may be authored as a new derived downstream artifact with
explicit provenance and separate visual acceptance. It must not be represented
as a provider-native animation. If no such authored pose is authorized, this
candidate remains rejected.

### 2. Face/neck discontinuity: provider model or import interaction

`processed_fbx_012` is byte-identical to provider source `source_fbx_006`.
Foundry performed no Blender conversion, mesh edit, texture-mask operation, or
material rewrite on this path. The Foundry wrapper only instances the FBX and
loads animation resources. Vandrel likewise imports that exact FBX hash.

Therefore the defect was **not introduced by Foundry processing, wrapper
generation, file copying, or a hash mismatch**. Current evidence does not yet
distinguish:

- discontinuous source geometry/normals/UV/material data inside the FBX; from
- a Godot FBX-import interpretation of otherwise valid source data.

Ownership remains **Asset Foundry** because either outcome is a generic
portable-asset defect that must be resolved before consumer handoff.

### 3. Open/intersecting crown and hair panels: provider geometry or import interaction

The same byte-identity proof rules out a later Foundry mesh edit. The beauty
thumbnail already establishes that the layered planar hair construction
predates rigging. The exact open edges and intersections are proven in Godot,
but a second renderer has not yet isolated whether backface/material import
settings amplify a source-topology defect.

Ownership remains **Asset Foundry**, with the most likely origin being
provider-generated hair/headdress geometry. It is not a Vandrel gameplay,
lighting, camera, or grounding concern.

## Existing immutable-artifact comparison

Asset Library `r001`, `r002`, and `r003` contain older processed GLBs and
wrapper templates only. They:

- have different model hashes from the rejected FBX;
- use the suspended retarget/mapping corridor;
- contain neither current Walk nor Run resources;
- explicitly state `vandrel_runtime_accepted: false`; and
- have no equivalent full-resolution consumer closeup acceptance.

They are historical evidence, not repair inputs or fallback candidates.
Selecting one would change candidate identity and revive a corridor already
suspended after Godot skin/import failure. None can legitimately substitute
for local repair of the exact provider-native set.

## Proposed DM-005 experiment: exact-FBX cross-render and minimal repair

This is one bounded, credit-free experiment. It must create new derived
artifacts and reports; it must never overwrite the source or current candidate.

### Exact inputs

- Model: `source_fbx_006`, SHA-256
  `e583fa38493609685df0f01f519f9311b772b352b7a34fafc54e119771e05d4f`.
- Walk donor: `source_animation_fbx_003`, SHA-256
  `1fce221c8604cba031d1592e1cc2d58df2c2d74f4978a1ea315520dca58b1f59`.
- Run donor: `source_animation_fbx_004`, SHA-256
  `ef04e1bcb2af1402d0174963d0d57e488ff42358b64ecbc1475aa2c94d418061`.
- Vandrel closeup hashes and camera framing listed above.

### Phase A: isolate origin

Import the exact FBX into bounded Blender factory state with no automatic
embedded-script execution. Record:

- object, material, vertex, face, normal, UV, armature, modifier, and skin
  facts;
- nonmanifold/boundary edges and intersecting/duplicate faces in face, neck,
  crown, and hair regions;
- front and side orthographic closeups at consumer-comparable framing;
- front/backface and material views that separate geometry holes from material
  interpretation.

Import the unchanged FBX into the existing Godot sandbox and capture the same
fixed views. If Blender is clean while Godot is defective, stop: the next work
is a narrow importer/material experiment, not mesh repair.

### Phase B: minimal local derivation, only if Phase A proves source defects

Create one new immutable FBX derivative. Permit only explicitly logged,
region-bounded operations necessary to:

- weld or bridge proven unintended face/neck seams;
- correct proven invalid normals;
- close unintended crown boundary holes; and
- remove only duplicate/intersecting opaque hair faces.

Do not remodel the character, decimate, change silhouette intentionally,
replace textures, alter the skeleton, repaint the semantic mask, or touch the
immutable source.

Prepare new Walk and Run resources against the repaired model using the proven
same-task provider-native route. Authoring a neutral idle is a separately
declared derivative inside the same experiment only if its downstream semantic
intent is explicitly recorded; otherwise report Idle as still missing.

### Required outputs

- New immutable derived model with a new artifact ID and SHA-256.
- Versioned operation report identifying every touched region and operation.
- Before/after topology and material facts.
- Blender and Godot front/side closeups at fixed full resolution.
- Four-angle full-body stills.
- Continuous Godot Walk and Run playback with one visible skeleton-bound mesh.
- If authored, continuous four-second neutral-idle playback and an explicit
  `authored_downstream`, not provider-native, provenance label.
- Post-operation integrity and candidate audits.

### Pass gate

- No visible horizontal face/neck band in either renderer.
- No ordinary-view open crown holes or intersecting opaque hair panels.
- No new silhouette, texture, normal, skin-binding, or material regressions.
- Walk and Run continue to deform the same visible skeleton-bound mesh.
- Skeleton hierarchy and model scale remain unchanged.
- Idle is either an accepted explicitly authored neutral pose or remains
  honestly missing; a T-pose alias cannot pass.

### Failure and abandonment conditions

Abandon this candidate rather than expanding the experiment if:

- the defects require broad remodelling or texture repainting;
- local repair changes the intended silhouette materially;
- skin weights or animation binding regress;
- the face discontinuity cannot be isolated between source and importer;
- crown cleanup requires subjective redesign rather than mechanical repair; or
- a usable Idle cannot be provided without unauthorized semantic invention.

Paid regeneration, provider animation submission, approval, publication,
Vandrel gameplay registration, and shared-animation retargeting remain outside
this experiment.
