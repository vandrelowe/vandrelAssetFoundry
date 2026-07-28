# DM-006 Static Batch Predeclaration

Recorded before intake on 2026-07-27.

All successful sources are from Quaternius Fantasy Props MegaKit Standard.
Its bundled `License_Standard.txt` declares CC0 1.0 Universal / Public Domain
Dedication and identifies the models as by Quaternius. No network access or
paid provider action is required.

| Trial ID | Role | Exact source | Expected result |
|---|---|---|---|
| `dm006_quaternius_candle_001` | Simple prop | `Exports/FBX/Candle_1.fbx` | Local intake through review; small geometry and embedded/simple material may produce conversion warnings but should validate |
| `dm006_quaternius_chest_wood_001` | Textured prop | `Exports/glTF/Chest_Wood.gltf` plus its declared local buffer and texture sidecars | Intake should retain required same-package sidecars, convert, validate materials/textures, and reach review |
| `dm006_quaternius_workbench_001` | Larger near-environment object | `Exports/glTF/Workbench.gltf` plus declared local sidecars | Higher geometry/evidence volume than the candle; should remain within static-prop policy and reach review |
| `dm006_malformed_traversal_001` | Deliberately bad synthetic package | Local glTF fixture whose buffer URI traverses outside its package | `add-source` must fail closed, copy no source artifact, preserve the draft manifest, and leave all other candidates auditable |

The trial will stop before manual approval, release planning/application,
Asset Library mutation, or Vandrel import. “Throughput” will mean only these
four observed cases.
