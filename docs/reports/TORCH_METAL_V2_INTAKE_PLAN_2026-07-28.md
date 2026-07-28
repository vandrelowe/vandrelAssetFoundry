# Torch Metal v2 Custody/Intake Plan

> Reference only. If this document conflicts with Foundry governance,
> architecture authority, or the relevant corridor contract, the higher
> authority wins.

status: executed; see `TORCH_METAL_V2_INTAKE_RESULT_2026-07-28.md`
candidate: `quaternius_torch_metal_001`
lane: `static_prop`

## Selection and authority boundary

Torch_Metal is a bounded static-prop trial from the accepted Quaternius
Fantasy Props Standard package. The source has one mesh, one material, 1,040
vertices, 970 indexed triangles, and no skeleton or animation.

The material uses base-color, normal, and metallic/roughness textures. It has
no authored emissive channel. Foundry will assess the supplied static model
only; it will not add a flame, light, particle effect, gameplay behavior,
collision, or runtime classification. Those remain consumer decisions.

No current Foundry candidate or immutable Library release is named
Torch_Metal or contains either unique raw model/buffer hash.

## Exact source bundle

All paths are under
`Quaternius/Fantasy Props MegaKit[Standard]/Exports/glTF/`.

| File | Bytes | SHA-256 |
|---|---:|---|
| `Torch_Metal.gltf` | 2,203 | `f28978f4f351030766996ccb5585f258882b6892f3944bbf06609a761ffb01a5` |
| `Torch_Metal.bin` | 39,100 | `522de8798b4c2e0db9ba640d69a5c6e506b558f22b98e95c0cfc95ba2d7b79e7` |
| `T_Trim_Metal_Normal.png` | 3,625,541 | `ab7315c864c9a9e6d716c940a599928506e1569d3b0c9085f8f1a64ec520d790` |
| `T_Trim_Metal_BaseColor.png` | 1,361,221 | `50422bbda9661effc259caf8b386224cac4b5ca811d2c5b3b8b25ae8efc714db` |
| `T_Trim_Metal_ORM.png` | 1,871,475 | `7407bccfc39ca74ecd68a61217395959bf56ac2063e6c93b384b11f07f5687c5` |

The exact raw union is 6,899,540 bytes. The glTF and BIN are unique in the
accepted custody register. The three textures are intentional package-local
shared duplicates, also used by existing candidates; they do not make the
torch geometry a duplicate.

## Rights binding

- Package: `pkg:quaternius:500426d4f80eeeddff6b8423`
- Binding: `quaternius_fantasy_props_standard`
- Evidence:
  `Quaternius/Fantasy Props MegaKit[Standard]/License_Standard.txt`
- Evidence SHA-256:
  `edad12240087a33e08fc031e4e66c2b2b4b2a6d4f086339bde04f741b385fbda`
- Evidence bytes: 837
- Scope: `Quaternius/Fantasy Props MegaKit[Standard]`
- Effective rights: documented CC0

## Expected artifacts, timing, and storage

Expected records include five raw source artifacts, one converted source GLB,
conversion report/log, one immutable processed GLB, technical inspection,
Godot sandbox model/wrapper/import evidence, deterministic local and
four-angle previews with reports, one retained custody-evidence file, and a
batch timing ledger.

The raw minimum is 6.90 MB. Converted/processed and Godot staging copies plus
preview evidence are expected to produce a 30-55 MB candidate footprint.
Blender conversion and rendering dominate elapsed time; the complete bounded
headless corridor is expected to finish in 2-6 minutes on the configured
machine. No Library or Vandrel storage will be created.

## Gates

1. Exact glTF dependency closure; reject traversal, missing sidecars, or hash
   drift.
2. Bounded local Blender conversion; inspect GLB structure, geometry,
   triangle budget, material presence, and unexpected skeleton state.
3. Deterministic transparent and four-angle previews; visually confirm the
   complete torch silhouette, basket/head and shaft relationship, material
   coherence, no crop, and useful framing.
4. Record that flame/emission/light behavior is absent from the supplied
   static asset and remains outside Foundry authority.
5. Self-contained Godot headless import outside Vandrel.
6. Candidate audit passing.
7. Rebuild/validate custody against current physical roots, then bind the
   exact five raw inputs and copied CC0 notice.
8. Release fitness must finish in `review`, unapproved and unpublished, with
   exact documented custody and absent human approval as the release blocker.

## Bounded command sequence

```powershell
foundry run-static-batch docs/reports/evidence/torch-metal/batch-plan.json `
  --ledger docs/reports/evidence/torch-metal/batch-ledger.json --config foundry.toml
foundry custody-inventory --outside-root C:\Dev\outsideassets `
  --workspace-root C:\Dev\VandrelFoundryWorkspace --register <temporary-register> `
  --report <temporary-report> --policy config\custody-policy.v1.json --config foundry.toml
foundry bind-candidate-custody quaternius_torch_metal_001 `
  --outside-root C:\Dev\outsideassets --register <temporary-register> `
  --package-id pkg:quaternius:500426d4f80eeeddff6b8423 `
  --policy config\custody-policy.v1.json --config foundry.toml
foundry release-fitness quaternius_torch_metal_001 --config foundry.toml
foundry release-fitness quaternius_torch_metal_001 --json --config foundry.toml
```

No command includes approval, release application, provider/network access,
paid work, deletion, or a Vandrel write.
