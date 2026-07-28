# DM-005 Shaman Cross-Render Result

**Program:** Asset Foundry  
**Directive:** DM-005  
**Result:** Phase A complete; Phase B stopped; candidate route rejected

```yaml
program: Asset Foundry
directive_id: DM-005
repository: C:\Dev\vandrelAssetFoundry
branch: main
head_commit: recorded in director handoff
remote_sync: local branch remains ahead of origin/main; push is not authorized
working_tree: bounded DM-005 code and report changes
status: complete
delivered:
  - exact-FBX Blender topology and matched visual evidence
  - exact-FBX Godot sandbox matched material evidence
  - immutable manifest-tracked Phase A evidence index
  - source-vs-import origin decision
  - explicit no-Phase-B abandonment decision
automated_evidence:
  - exact candidate integrity audit passes after 14 new evidence artifacts
  - Blender reports one 5137-face skinned mesh, 77 boundary edges, 171 nonmanifold edges
visual_evidence:
  - 10 full-resolution Blender material/geometry/backface views
  - 2 full-resolution matched Godot material views
manual_review:
  result: reject
  phase_b: not executed
known_failures:
  - face/neck band reproduces in Godot but not Blender
  - crown holes and layered intersections reproduce in both renderers
  - provider-native Idle remains absent
cross_program_requests:
  - retain Vandrel rejection and do not retest this abandoned hash set
recommended_next:
  - separately design a narrow Godot FBX importer/material investigation
```

## Phase A evidence

The experiment used exact provider model `source_fbx_006`, SHA-256
`e583fa38493609685df0f01f519f9311b772b352b7a34fafc54e119771e05d4f`.
That file is byte-identical to rejected `processed_fbx_012`.

Blender 5.2.0 LTS ran in background factory state with automatic embedded
scripts disabled. Godot 4.6.2 imported the same FBX in a separate temporary
sandbox. The resulting evidence was promoted without overwriting any prior
artifact to:

`reports/cross-render-001/index.json`

Index SHA-256:
`59e35b4760b2b862c90b129e293f652eb6cd07496ba569aac22594d9d271a227`.

The index binds 13 evidence files to `processed_fbx_012`, including:

- Blender material front closeup:
  `16f07dbe0d6ac9b1072d62182d967f5c42b7dd0446183902f44c43fbcb1d3158`.
- Blender material right closeup:
  `5001413dc825a7844ef4883b19b8106aad55d03429f7bb111fa508e14af1254f`.
- Godot material front closeup:
  `3676917a65cadb0e9e63a35fbcfa0d412c8577f0b071e224b9ba9cacb0b3f510`.
- Godot material right closeup:
  `93428c9f44b835f159d4ed43f67708c32f8a4b82bcaad1571216791df52cafbe`.
- Blender topology report:
  `f502f6d6a82127778a0329b401b79ec24e6ea5525c6c1deda63921b504a1d6e5`.

The Blender report records:

- one mesh and one armature modifier;
- 2,528 vertices, 7,683 edges, and 5,137 faces;
- 77 boundary edges;
- 171 nonmanifold edges;
- no loose edges or zero-area faces;
- one UV layer and custom normals;
- 22 vertex groups;
- the expected 24-bone hierarchy; and
- imported armature scale `0.01` on every axis.

Counts are supporting facts only. The decision below comes from the matched
full-resolution images.

## Origin decision

### Face/neck band: Godot render/import path

The Blender material closeup renders a continuous lower face and neck with no
horizontal rectangular band. The matched Godot import renders a hard band
across the lower face at the jaw line. Both consume the same immutable FBX.

This rules out provider geometry as the demonstrated cause of the band and
rules out any later Foundry file transformation. The evidence isolates the
defect to the Godot render/import path, but does not yet distinguish FBX import,
material conversion, normals, skinning, shader behavior, lighting, or exposure.
The Blender and Godot views match subject, orientation, and framing but not
renderer or illumination.

Per the Phase A stop rule, no mesh repair is permitted for this defect. A
future corridor may vary one Godot render/import variable at a time against
these exact views. It must not modify the source mesh or become a Vandrel
runtime workaround.

### Crown and hair: source geometry

Open crown gaps, unsupported opaque planes, and layered intersections are
visible in Blender material, gray geometry, and backface views before Godot is
involved. Godot reproduces and visually amplifies the same construction. The
77 boundary and 171 nonmanifold edges are consistent with that visual result.

This is provider-source geometry, not a wrapper, animation, texture-copy, or
consumer-path defect.

## Phase B stop and abandonment

Phase B was not executed and no derivative model exists.

Although a source defect is proven, the hair is not one isolated accidental
hole or duplicate face. It is a pervasive layered planar construction defining
the character's crown and silhouette. Deciding which planes are hair, feathers,
skull support, intentional gaps, or disposable overlap requires subjective
redesign. Closing 77 boundaries or removing intersecting panels mechanically
would likely change the silhouette and skinning.

That meets DM-005's explicit abandonment conditions:

- repair requires subjective redesign rather than mechanical correction;
- the affected region is broad rather than bounded; and
- a safe operation cannot guarantee unchanged silhouette and deformation.

The candidate is therefore explicitly rejected at manifest revision 87 with
history retained. The rejection note records both the source hair failure and
the separate Godot-specific face band. Approval remains false, no publication
occurred, and historical `r001-r003` releases were not modified.

The provider-native Walk and Run success remains useful corridor evidence, but
it does not rescue this model. The missing provider-native Idle also remains
unresolved; no semantic substitute was authored.

## Validation and next direction

The post-decision integrity audit passes the candidate, all evidence
derivations, approval bindings, and event history. Integrity is intact even
though quality acceptance failed.

Do not spend credits or retest this exact candidate in Vandrel. If character
work resumes, select a new source identity. Independently, Foundry may later
ratify a small importer/material experiment for the face-band class using the
same cross-render harness, without reopening or repairing this rejected model.
