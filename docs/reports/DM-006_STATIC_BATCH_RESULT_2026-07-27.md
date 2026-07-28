---
directive: DM-006
status: complete
date: 2026-07-27
scope: credit-free static-asset throughput trial
---

# DM-006 Static Batch Throughput Trial

## Decision

The static corridor is operationally usable for this bounded mixed batch.
Three predeclared assets reached `review`; the unsafe control failed closed in
`draft`; the final whole-workspace audit passed 17 candidates. No asset was
approved, published, imported into Vandrel, or sent to a network provider.

This is evidence for these four cases only, not a high-volume throughput claim.

## Selection and provenance

The three successful sources came from Quaternius Fantasy Props MegaKit
Standard in `C:\Dev\outsideassets`. The bundled `License_Standard.txt`
declares CC0 1.0 Universal / Public Domain Dedication and identifies the models
as by Quaternius. The control fixture is project-authored. The exact
pre-intake declaration is
`docs/reports/DM-006_STATIC_BATCH_PREDECLARATION_2026-07-27.md`.

| Candidate | Lane / role | Exact input | Expected / actual |
|---|---|---|---|
| `dm006_quaternius_candle_001` | `static_prop`, simple | `Exports/FBX/Candle_1.fbx` | success / `review` |
| `dm006_quaternius_chest_wood_001` | `static_prop`, textured | `Exports/glTF/Chest_Wood.gltf` and declared sidecars | success / `review` |
| `dm006_quaternius_workbench_001` | `static_prop`, larger object | `Exports/glTF/Workbench.gltf` and declared sidecars | success / `review` |
| `dm006_malformed_traversal_001` | `static_prop`, unsafe control | `tests/fixtures/dm006_traversal.gltf` (`../outside.bin`) | fail closed / `draft`, zero artifacts |

## Hash proof

| Candidate | Raw input SHA-256 | Converted / processed GLB SHA-256 |
|---|---|---|
| Candle | `a59efc5441093250e88af1fd1e2b16ec4486e55d2397788e4c4c85e2a544bfa1` | `b5193f3b03247023b955c39c44b74986f048b5ae3ae6d75b8db1d1c88bdfb446` |
| Chest Wood | `b2022f69b76526fcbbc7f7a8855848beeefa6e8a6f55337d923bce38ed03b2b6` | `cb248bc1f3033bc18da7453bdcd532258d1ce0a44e951b335506fc94189f45b9` |
| Workbench | `518fc5c955def18cfcb781b3b955da0e8edcf4f37830a21561ef32c03ad0397e` | `d1d44cb0d239dd084426a4a143b1ec1d9c1ca8559cf7495905406f9cf964d296` |
| Unsafe fixture | `543f8309a55c35441b86fc8fd424230ce115f61d21d40e94d1bc6d120ea0cff4` | none |

The glTF candidates additionally retain and hash every declared buffer and
texture sidecar in their manifests.

## Timing and interventions

Elapsed seconds are wall-clock observations from individual CLI invocations.
An active intervention is one deliberate stage invocation; subprocess work and
automatic manifest/evidence writes are not counted separately.

| Candidate | create | intake | process | inspect | stage Godot | validate Godot | preview | audit |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Candle | 0.326 | 1.689 | 0.327 | 0.323 | 0.329 | 3.551 | 2.064 | 0.322 |
| Chest Wood | 0.423 | 2.269 | 1.037 | 0.601 | 1.097 | 10.132 | 1.944 | 0.349 |
| Workbench | 0.385 | 2.417 | 0.490 | 0.409 | 0.794 | 10.109 | 2.053 | 0.360 |
| Unsafe control | 0.370 | 0.322 failed as expected | — | — | — | — | — | 0.299 |

Each successful corridor used eight interventions. The control used three.
The 2048px multi-angle evidence required one additional invocation per
successful candidate after its renderer existed: 3.479 s candle, 3.419 s
chest, and 3.467 s workbench. A first framing pass was retained immutably but
superseded because it left excessive empty canvas; this exposed a real
evidence-volume cost rather than being hidden. Gallery generation took 0.374 s
and the final `audit-all` took 1.333 s.

Godot import validation dominated machine time for both textured glTF cases
(about 10.1 s each). Operator ergonomics were otherwise straightforward, but
the corridor remains command-heavy without an orchestration command.

## Technical and visual evidence

- Candle: 212 triangles, 1 material.
- Chest Wood: 2,546 triangles, 2 materials.
- Workbench: 1,368 triangles, 2 materials.
- Each successful candidate has transparent 2048×2048 front, right, back, and
  left PNGs in `preview/multi-angle-002/`, hash-bound to its processed GLB.
- Independent visual inspection confirmed recognizable, textured silhouettes
  from the sampled front/back views. No missing model, untextured fallback, or
  obvious gross geometry corruption was observed.
- The first and corrected multi-angle sets are both retained. This increases
  evidence volume but preserves the immutable-history rule.

| Candidate | Final artifacts | Recorded bytes |
|---|---:|---:|
| Candle | 25 | 11,037,444 |
| Chest Wood | 32 | 70,771,465 |
| Workbench | 32 | 71,186,877 |
| Unsafe control | 0 | 0 |

The textured cases are roughly 71 MB each because source packages, converted
and processed GLBs, Godot staging, previews, and immutable evidence coexist.
That is acceptable for this trial but material for future batch scaling.

## Failure clarity and integrity

The malformed intake exited nonzero with:

`External glTF sidecar is missing or unsafe: ../outside.bin`

It created no source artifact or partial package. The candidate stayed at
revision 1 in `draft`, its candidate audit passed, and the other three
candidates subsequently passed their audits. `foundry audit-all` passed all 17
workspace candidates. The generated offline review snapshot is
`C:\Dev\VandrelFoundryWorkspace\review_reports\review-gallery-011.html`.

## Reproducible command ledger

For each good candidate:

```text
foundry create --id <id> --lane static_prop --display-name <name> --prompt-file <prompt>
foundry add-source <id> --model <exact-input>
foundry process <id>
foundry inspect <id>
foundry prepare-godot <id>
foundry validate-godot <id>
foundry render-preview <id>
foundry render-multi-angle-preview <id>
foundry audit <id>
```

Control and batch close:

```text
foundry create --id dm006_malformed_traversal_001 --lane static_prop ...
foundry add-source dm006_malformed_traversal_001 --model tests/fixtures/dm006_traversal.gltf
foundry status dm006_malformed_traversal_001
foundry audit dm006_malformed_traversal_001
foundry review-gallery
foundry audit-all
```

## Follow-up recommendation

Keep approval and publication stopped. The next bounded improvement should be
a local batch-orchestration command that emits a machine-readable timing
ledger, while preserving per-candidate fail-closed isolation. Evidence
retention policy should also distinguish superseded review renders without
deleting immutable history.
