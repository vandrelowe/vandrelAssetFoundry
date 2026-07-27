# Outside Asset Inventory

**Source:** `C:\Dev\outsideassets`

**Inspection mode:** Read-only

**Last verified:** 2026-07-27

The Foundry scanner found 963 supported model sources: 869 FBX and 94 glTF.
Its path-based first-pass classification identified 61 Meshy, 651 Mixamo, and
251 Quaternius files, with 262 suggested static-prop candidates and 701
suggested humanoid candidates. The Meshy subset contains 50 humanoid-intent and
11 static-prop candidates. The scan completed with no warnings, produced 963
unique suggested asset IDs, and did not copy or modify source files.

## Format inventory

| Extension | Files |
|---|---:|
| FBX | 869 |
| Godot `.import` metadata | 231 |
| PNG | 166 |
| glTF | 94 |
| glTF binary buffer | 94 |
| OBJ | 94 |
| MTL | 94 |
| JPG | 4 |
| TXT | 2 |

The collection includes Meshy exports, Mixamo animation/rigging assets, and
Quaternius asset kits. The Meshy area contains both standalone/rigged FBX files
and texture export directories with an FBX plus a same-directory PNG.

## Representative zero-credit validation

The first representative package was:

`Meshy\Meshy_AI_Empty_Basket_3K_0616194737_texture_fbx`

Inputs were left unchanged. Blender 5.1.2 loaded the 19.2 MB FBX with its
19.1 MB PNG and exported a texture-embedded GLB. Foundry then copied that GLB
into its workspace and ran the normal local pipeline.

Observed result:

| Measurement | Result |
|---|---:|
| Meshes | 1 |
| Primitives | 1 |
| Triangles | 3,084 |
| Materials | 1 |
| Textures | 1 |
| Images | 1 |
| Static-prop maximum | 5,000 triangles |
| GLB structure | Passed |
| Triangle budget | Passed |
| Godot headless import | Passed |
| Final workflow state | `review` |

Godot completed in approximately 7.7 seconds, created its import cache, and
returned exit code 0 without timing out or exceeding the output limit.

## Findings and next cases

- Existing Meshy FBX packages are useful zero-credit equivalents of provider
  downloads.
- The texture survived FBX-to-GLB conversion and was visible to the GLB
  inspector as one embedded texture/image.
- Blender warned that more than one image-texture shader node contributed to a
  texture sampler. The export remained valid, but material-node ambiguity
  should become a recorded Blender validation check.
- Static props should be exercised before humanoids because the humanoid lane
  remains release-disabled and requires a future canonical skeleton contract.
- Native FBX package intake now copies the FBX and same-directory texture
  sidecars into immutable provenance storage before converting the copy.
- A second Meshy berry-basket package passed native intake, Blender conversion,
  the 5,000-triangle static-prop budget at 2,988 triangles, and Godot import.
- Native glTF intake copies only JSON-declared local buffers/images. A
  Quaternius anvil package copied its GLTF, one BIN, and three referenced
  textures; it passed at 750 triangles and reached review.
- Both Meshy FBX and Quaternius glTF conversion exposed Blender's
  multiple-image-texture-node sampler warning. It is now retained in structured
  conversion evidence instead of only console text.

## Humanoid preservation probe

Two existing Meshy biped FBXs were processed through native package intake to
test the still-release-disabled humanoid lane. Both preserved one skin and 24
joints. The character export contained one animation; the merged-animation
export contained 14 animations. The character GLB also passed a real Godot
headless import.

Both candidates correctly failed the required-material check because their
source FBXs contained no materials. Neither was approved. Blender reported
that some vertices had more than four joint influences and retained the four
highest weights during GLB export; the warning is preserved in each candidate's
conversion evidence. These results validate basic rig and animation
preservation, but do not establish a canonical Vandrel humanoid skeleton
contract.

## Local decimation probe

The native Empty Basket package was reprocessed with an explicit 2,000-triangle
target. Blender reduced it from 3,084 to exactly 2,000 triangles while
preserving one material, one texture, and one embedded image. Foundry
independently measured the output at 2,000 triangles, and Godot imported the
decimated GLB successfully. The candidate remains in review because geometric
and texture counts do not substitute for human visual-quality review.

The Meshy Fresh Wood Campfire was then processed without decimation because
its source conversion already measured 2,544 triangles, close to the
2,500-triangle lane target and below the 5,000 maximum. Its material and
embedded texture survived conversion, Godot import passed, and an audited local
preview was generated. It remains in review.

After delegated visual review, the Fresh Wood Campfire, original Empty Basket,
and Quaternius Anvil were approved with exact processed-model and Godot-wrapper
hash bindings. The Berry Basket remains in review because its contents are
visually ambiguous.

The first humanoid previews exposed an oversized unskinned `Icosphere` helper
mesh and centimeter-scale character geometry. Preview framing now prefers
skinned meshes, uses scale-relative camera clipping and lighting, and records
excluded helper counts. Corrected renders show intact posed silhouettes, but
both candidates remain unapproved because their GLBs contain no materials.
