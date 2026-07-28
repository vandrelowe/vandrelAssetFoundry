# Axe Bronze v2 Intake Result

status: review complete; unapproved and unpublished
candidate: `quaternius_axe_bronze_001`

## Outcome

The documented Quaternius Axe_Bronze glTF bundle completed the existing
credit-free static corridor through review. No network, provider, paid,
approval, publication, Library mutation, or Vandrel mutation occurred.

The first orchestration run exposed a bounded contract bug:
`run-static-batch` expected a nonexistent `ProcessResult.passed` field after a
successful Godot validation. The candidate had safely reached review. The
orchestrator now uses the actual return-code/timeout/output-limit contract, a
regression test covers it, and resume skipped all completed immutable stages
before rendering previews and auditing.

## Technical and storage proof

- Manifest: v2 revision 9,
  `e923533b31b0676919d88911aca7dc515efe7f85d17956fe4dfd4647874218c4`
- Workflow: `review`; validation `passed`; approval false; release false
- Processed GLB:
  `8fc3362bb80077007a69dc4374bc87fa3aee0462442201b9fdfa7d1f20319abe`
- Geometry: 826 triangles, one mesh, one primitive
- Materials/textures: one material, three textures/images
- Rig/animation: zero skins, joints, or animations
- Physical footprint after custody: 51 files, 66,747,237 bytes; within the
  planned 40-70 MB band
- Candidate audit: passing, 24 recorded artifacts

## Custody proof

- Package: `pkg:quaternius:500426d4f80eeeddff6b8423`
- Exact source union: five raw inputs totaling 9,755,488 bytes, with the hashes
  declared in `AXE_BRONZE_V2_INTAKE_PLAN_2026-07-28.md`
- Semantic assertion:
  `479b6e3049245e4fe27add1321a96202b168e5dfdf84cca52ba3daeaa282b2b3`
- Current register:
  `c900369e0181f45a4b616e53caeff9665ba614b4b1a16136fdd6f979a334fea6`
- Evidence binding: `quaternius_fantasy_props_standard`
- Original and retained CC0 notice: 837 bytes,
  `edad12240087a33e08fc031e4e66c2b2b4b2a6d4f086339bde04f741b385fbda`
- Scope: `Quaternius/Fantasy Props MegaKit[Standard]`
- Fitness: evaluated/documented/exact with no custody blockers

## Visual proof

The deterministic front view clearly shows the bronze double-ended axe head,
long handle, coherent attachment, authored surface detail, and complete
uncropped silhouette. The right view is naturally narrow because it is
edge-on; it confirms plausible model thickness rather than missing geometry.
All four renderer records report `no_crop=true` and
`useful_occupancy=true`.

- Front:
  `docs/reports/evidence/axe-bronze/front.png`,
  `6c50503315aadd23e17e3a268c7afdfbb3fc0af4e41de02ba11b1c3e64b11fff`
- Right:
  `docs/reports/evidence/axe-bronze/right.png`,
  `2ec5be6ca9c50347d5473ed999ae5767f58f740227be8fed4ed644bfa1ab167e`

The batch plan and resume ledger are retained beside those images. The ledger
shows one completed candidate, zero failures, immutable-stage skips, and only
the preview/audit stages executed after the orchestration fix.

## Release boundary

Human and JSON evidence at
`docs/reports/evidence/axe-bronze/release-fitness.*` agree:

- integrity and technical validation pass;
- custody is evaluated, documented, and exact;
- approval is absent;
- publication and consumer evidence are absent;
- absent human approval is the sole release blocker.

A non-apply release-planning command stopped on that exact blocker.
