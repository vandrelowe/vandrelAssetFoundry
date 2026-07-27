# Outside Asset Inventory

**Source:** `C:\Dev\outsideassets`  
**Inspection mode:** Read-only  
**Last verified:** 2026-07-26

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
- Native package intake should eventually copy the FBX and sidecar textures
  into immutable provenance storage before conversion. Until that lands,
  conversion should remain an explicit preprocessing step and the originals
  must stay untouched.
