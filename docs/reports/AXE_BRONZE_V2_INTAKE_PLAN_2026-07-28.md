# Axe Bronze v2 Custody/Intake Plan

status: read-only preflight complete; clean to execute
candidate: `quaternius_axe_bronze_001`
lane: `static_prop`

## Selection

Axe_Bronze is the lowest-risk option in the Library shortlist. It has immediate
harvest/tool utility, one mesh, one material, no skeleton, 655 vertices, and
826 indexed triangles. Torch_Metal introduces emissive/light-behavior review;
Bag has lower gameplay utility and more ambiguous scale/use expectations.

No current Foundry candidate or immutable Library release contains the
`Axe_Bronze` name or either unique raw model/buffer hash.

## Exact source bundle

All paths are under
`Quaternius/Fantasy Props MegaKit[Standard]/Exports/glTF/`.

| File | Bytes | SHA-256 |
|---|---:|---|
| `Axe_Bronze.gltf` | 2,591 | `338ce6e6947b8849774aac2deb9d2bf3a1cb14dc869effb7be0a91053e67b64f` |
| `Axe_Bronze.bin` | 31,156 | `d608e8dea796ae8a200cd78bb1836d2705944f628abb6ac2e03c76e6637187b2` |
| `T_Trim_Props_Normal.png` | 4,441,458 | `c4b28a8ba8efe3108cd11356ecab67e8bf75a10cebf29c78ee7724552c305a3e` |
| `T_Trim_Props_BaseColor.png` | 2,263,132 | `75225a4ccfd8cc358c871de7a7a3cab7118ef197419a88464e807b81716215c8` |
| `T_Trim_Props_ORM.png` | 3,017,151 | `2d83d8df79aca2c8f630d389b43f09113afee98e746dfd42ddc3ce3302a136a2` |

The exact raw bundle is 9,755,488 bytes. The glTF and BIN are unique in the
accepted custody register. The three textures are package-local shared
duplicates; their reuse does not make the axe itself a duplicate.

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

## Expected artifacts and storage

Expected candidate records include five raw source artifacts, one converted
source GLB, conversion report/log, one immutable processed GLB, technical
inspection, Godot sandbox model/wrapper/import evidence, deterministic local
and four-angle previews with reports, and one retained custody-evidence file.

The raw minimum is 9.76 MB. Converted/processed and Godot staging copies are
expected to bring candidate storage to roughly 35-55 MB; deterministic preview
evidence may add 5-15 MB. The bounded expected total is 40-70 MB. No Library or
Vandrel storage is created.

## Gates

1. Exact glTF dependency closure; reject traversal, missing sidecars, or hash
   drift.
2. Bounded local Blender conversion; inspect GLB structure, geometry,
   triangle budget, material presence, and unexpected skeleton state.
3. Deterministic transparent and four-angle previews; visually confirm axe
   silhouette, head/handle relationship, scale framing, materials, no crop,
   and no severe empty canvas.
4. Self-contained Godot headless import outside Vandrel.
5. Candidate audit passing.
6. Rebuild/validate custody register against current physical roots, then bind
   the exact five raw inputs and copied CC0 notice.
7. Release fitness must finish in `review`, unapproved and unpublished, with
   exact documented custody and absent human approval as the sole release
   blocker.

## Dry-run command sequence

```powershell
foundry run-static-batch docs/reports/evidence/axe-bronze/batch-plan.json `
  --ledger docs/reports/evidence/axe-bronze/batch-ledger.json --config foundry.toml
foundry custody-inventory --outside-root C:\Dev\outsideassets `
  --workspace-root C:\Dev\VandrelFoundryWorkspace --register <temporary-register> `
  --report <temporary-report> --policy config\custody-policy.v1.json --config foundry.toml
foundry bind-candidate-custody quaternius_axe_bronze_001 `
  --outside-root C:\Dev\outsideassets --register <temporary-register> `
  --package-id pkg:quaternius:500426d4f80eeeddff6b8423 `
  --policy config\custody-policy.v1.json --config foundry.toml
foundry release-fitness quaternius_axe_bronze_001 --config foundry.toml
foundry release-fitness quaternius_axe_bronze_001 --json --config foundry.toml
```

No command includes approval, release application, provider/network access,
paid work, deletion, or a Vandrel write.
