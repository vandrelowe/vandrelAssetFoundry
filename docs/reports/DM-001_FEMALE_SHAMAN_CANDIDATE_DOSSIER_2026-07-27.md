# DM-001 Female-Shaman Candidate Dossier

**Program:** Asset Foundry  
**Directive:** DM-001  
**Observed:** 2026-07-27  
**Candidate authority:** `C:\Dev\VandrelFoundryWorkspace\assets\meshy_female_shaman_character_001\manifest.json` revision 84  
**Status:** Partial only because remote synchronization is not authorized;
identity handoff evidence is complete and consumer visual acceptance remains
intentionally open

```yaml
program: Asset Foundry
directive_id: DM-001
repository: C:\Dev\vandrelAssetFoundry
branch: main
head_commit: 34e732573bb1f3f7ea7d094e17b4f7f2aaf88955 (pre-report evidence base)
remote_sync: local report commit is 1 ahead of origin/main; push authorization denied
working_tree: clean after local report commit
status: partial
delivered:
  - Exact provider-native candidate identity and derivation chain
  - Workspace and immutable-library integrity audits
  - Historical release mapping
  - Release-fitness and evidence-gap assessment
changed_files:
  - docs/reports/DM-001_FEMALE_SHAMAN_CANDIDATE_DOSSIER_2026-07-27.md
automated_evidence:
  - foundry audit-all: pass, 13 candidates
  - foundry audit-library: pass, 54 checks
  - provider-native playback validation: pass for the exact current hashes
visual_evidence:
  - Historical processed GLB preview and 18-frame contact sheet inspected
  - No continuous or fixed-frame visual evidence currently binds the exact provider-native FBX set
manual_review:
  - Current candidate has no active Foundry approval
  - Historical r001-r003 approvals do not transfer to the current candidate
known_failures:
  - Report commit is not remotely synchronized because push authorization was denied
  - No existing library revision matches the current provider-native candidate
  - No Vandrel acceptance entry binds the current model hash
  - Current exact-hash evidence is technical, not sufficient visual deformation proof
cross_program_requests:
  - Vandrel should test the exact model/walk/run hashes in this dossier
decisions_needed: []
recommended_next:
  - Await Vandrel's hash-bound acceptance result before approval or publication
```

## Exact current candidate

The unambiguous current consumer-test candidate is:

| Fact | Exact value |
|---|---|
| Asset ID | `meshy_female_shaman_character_001` |
| Manifest revision | `84` |
| Workflow state | `review` |
| Model artifact | `processed_fbx_012` |
| Model SHA-256 | `e583fa38493609685df0f01f519f9311b772b352b7a34fafc54e119771e05d4f` |
| Walk artifact | `processed_animation_walk_006` |
| Walk SHA-256 | `4c6b1c61e48fcee01dbedbe4bf4e42190b8e86ac68bfd1e8d4a98f7a78a370e8` |
| Run artifact | `processed_animation_run_006` |
| Run SHA-256 | `f60cf7e192446d506a8975fca328480e032c515428cba2dc538f6762904c1f1a` |
| Wrapper artifact | `godot_wrapper_scene_012` |
| Wrapper SHA-256 | `9f7eba43ee57132b1dc96d8ce0343e32775ecb39f498b0571b53e12f09e0f032` |
| Technical report | `provider_native_character_report_006` |
| Report SHA-256 | `06d8153def9d2a8562409128a613426d7917a635c52382a68e7ea66d975d272e` |

The `006` suffix is a Foundry artifact/preparation iteration. It is not an
asset-library release revision and must not be shortened to “R006.”

## Provider and derivation proof

All three consumer files bind to Foundry task key `meshy_rigging_001`, whose
opaque Meshy provider task ID is
`019fa48e-e101-7a01-9610-fedd8043fa5f`. The task succeeded after the beauty
retexture task and reports five consumed credits. This dossier performs no
provider request.

The exact chain is:

```text
meshy_rigging_001
  source_fbx_006
    sha256 e583fa38493609685df0f01f519f9311b772b352b7a34fafc54e119771e05d4f
    -> processed_fbx_012 (byte-identical provider-native model)

  source_animation_fbx_003
    sha256 1fce221c8604cba031d1592e1cc2d58df2c2d74f4978a1ea315520dca58b1f59
    + source_fbx_006
    -> processed_animation_walk_006

  source_animation_fbx_004
    sha256 ef04e1bcb2af1402d0174963d0d57e488ff42358b64ecbc1475aa2c94d418061
    + source_fbx_006
    -> processed_animation_run_006
```

The rigging request's redacted evidence binds its `input_task_id` to the
succeeded beauty-retexture provider task, and its download evidence exposes the
model, walk, and run outputs under the same rigging task. This establishes the
provider-side relationship without relying on filenames.

The manifest's active `provider_native_character_playback` check binds the
three processed hashes above and records `same_provider_task: true`. The
bounded Godot report passes geometry, triangle budget, materials, skeleton,
Godot import, visible skin/skeleton binding, and provider-native playback.
Observed technical facts include one mesh, one primitive, one material, two
textures, one skin, 24 joints, 5,137 triangles, and 14 imported animations.

## Immutable-library mapping

There is **no matching immutable library revision** for the current
provider-native model/walk/run set.

| Release | Foundry manifest | Model artifact | Model SHA-256 | Walk/run included | Vandrel accepted |
|---|---:|---|---|---|---|
| `r001` | 51 | `processed_glb_004` | `bcb4eb28ebb9863e732c45d817e319ebd3dbeac979fd22fddbdf604a90ddd33f` | No | False |
| `r002` | 61 | `processed_glb_005` | `86aef4122d5d3c66dffa2923e3251da3b9e61084a3c1ce7351edd6fdb00d9371` | No | False |
| `r003` | 71 | `processed_glb_006` | `34175069a7249c599cea7443c187b9b53c21772ac858fe3add3f8ed53e6a640b` | No | False |

All three releases use the earlier retarget-mapping route. They are immutable,
audited historical packages, not evidence that the current provider-native
candidate is approved, published, or accepted. In particular, `r003` is not
the source of the current model hash.

## Release-fitness separation

### Technical integrity

Pass for the exact current hashes. `foundry audit-all` rehashed all 213
recorded artifacts for this candidate and passed; the full workspace audit
passed all 13 candidates. The exact current provider-native validation check is
also passing.

Two recorded conversion warnings remain relevant background:

- More than one shader image node may affect glTF sampler selection.
- More than four joint influences were reduced to the four highest weights
  during the earlier conversion path.

The current model is provider-native FBX, so Vandrel must judge whether either
warning corresponds to a visible consumer defect rather than assuming it does.

### Foundry human visual review

Not approved for the current candidate. The manifest is in `review` with
`approval.approved: false` and no approved hashes.

Historical preview evidence includes static model previews and an 18-frame
animation contact sheet for `processed_glb_006`. Independent inspection shows
the full character and materially distinct skull, hair/feathers, skin, and
cloth. The sampled frames show visibly different poses. However, those images
bind the historical GLB, not `processed_fbx_012`, and still images do not prove
continuous deformation. They are representative appearance evidence only.

The retained approval note says an earlier `processed_glb_006` was approved.
Because approval is currently false, that note is historical context and must
not be read as approval of the provider-native set.

### Publication

Not published. The manifest's `release_revision: 3` is historical latest
publication metadata. No release descriptor contains the current model hash,
and no descriptor contains the current walk/run resources.

### Vandrel acceptance

Not established. Existing `r001-r003` descriptors explicitly state
`vandrel_runtime_accepted: false`, and no current Foundry consumer-evidence
artifact binds model hash
`e583fa38493609685df0f01f519f9311b772b352b7a34fafc54e119771e05d4f`.

Vandrel should therefore treat this as a direct workspace-to-consumer test
candidate under the director's bounded directive, not as an import of `r003`.

## Reproducible audit transcript

Run from `C:\Dev\vandrelAssetFoundry` with the configured workspace ACL:

```powershell
.\.venv\Scripts\foundry.exe audit-all
.\.venv\Scripts\foundry.exe audit-library
.\.venv\Scripts\foundry.exe audit meshy_female_shaman_character_001
.\.venv\Scripts\foundry.exe show meshy_female_shaman_character_001
```

Observed results:

- Workspace audit: passed, 13 candidates.
- Shaman audit: passed, 213 artifacts.
- Asset-library audit: passed, 54 checks.
- Library shaman revisions discovered: exactly `r001`, `r002`, `r003`.
- Foundry source before report: `main` at
  `34e732573bb1f3f7ea7d094e17b4f7f2aaf88955`, clean and synchronized with
  `origin/main` (0 ahead, 0 behind).
- Asset Library: `main` at
  `732356c081b1f85925d27ba420033001d16eb587`, clean, with no configured
  upstream shown by Git.

## Required next handoff

Vandrel should bind its character-lab evidence to the exact asset ID and model
hash above and record continuous, full-body idle/walk/run playback plus
multi-angle and material close-up evidence. Any returned
`vandrel_character_asset_acceptance/1.0` entry must bind that same model hash.

Foundry must not approve or publish a next revision until that evidence is
reviewed and any consumer finding owned by `asset_foundry` is resolved. A
successful Vandrel test still does not itself mutate Foundry approval or
publish a release.

## Independent review

A separate read-only review agent rechecked manifest revision 84, the provider
task evidence, all exact hashes and derivation edges, all three immutable
release descriptors, the 213-artifact candidate audit, and the 54-check library
audit. It passed this dossier for identity handoff. Its residual risks agree
with this report: the historical visual evidence is non-authoritative for the
current provider-native files, and repository metadata above records the
pre-report evidence base rather than the self-referential report commit.
