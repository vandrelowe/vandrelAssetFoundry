---
directive: DM-013
status: implementation_complete_visual_acceptance_blocked
date: 2026-07-27
scope: local static multi-angle preview framing
---

# DM-013 Static Preview Framing Quality

## Result

The existing `render-multi-angle-preview` authority now fits evaluated
world-space mesh vertices with a perspective-safe initial camera and uses at
most two bounded nonzero-alpha feedback corrections. Foundry independently
measures the saved PNG before registration and fails closed on empty alpha or
foreground touching any frame edge. No mesh, material, source artifact,
workflow state, approval, publication, Asset Library, or Vandrel content was
changed.

The exact DM-006 candle, chest, and workbench each produced a new immutable
2048x2048 `multi-angle-007` set. All 12 views report useful occupancy and
nonzero crop margins. The previous `multi-angle-002` baseline and every
diagnostic attempt remain intact.

Mechanical framing acceptance passes, but directive acceptance is blocked by
independent visual review of the candle. The final chest and workbench views
are recognizable, centered, materially intact, and materially improve useful
occupancy. The candle is larger and uncropped but remains a nearly featureless
white pillar that the reviewer could not reliably recognize. Its immutable
technical inspection records one material and zero textures/images, and the
same failure is visible in the baseline. Two retained candle-only lighting
diagnostics (`multi-angle-008` and `multi-angle-009`) improved tonal separation
only slightly and did not clear the semantic gate. Their experimental lighting
changes were not retained in code.

## Diagnosis and bounded correction

The old camera used a single coarse scene extent. It did not account for
perspective projection per required angle, and sparse/offset alpha silhouettes
could occupy a small portion of the image even when the aggregate bounds were
technically visible.

The corrected path:

1. samples evaluated mesh vertices in world space;
2. solves the minimum perspective distance whose projected geometry remains
   inside an NDC frame limit of 0.88;
3. renders the required front/right/back/left view;
4. measures the nonzero-alpha bounding box;
5. makes at most two target/distance corrections toward a maximum dimension of
   0.82 with a 0.03 centering tolerance; and
6. independently rejects the final file if alpha is empty or touches an edge.

The projected geometry facts describe the initial safe fit. Camera
location/target/distance and alpha facts describe the final render.

## Mechanical ledger

All coordinates and distances are Blender world units. Margin order is
left/right/top/bottom pixels. Occupancy is width x height; alpha is the
nonzero-alpha pixel fraction.

| Candidate | Evaluated geometry bounds (min → max); points |
|---|---|
| Candle | `(-0.047016,-0.050538,0.000735)` → `(0.046865,0.057329,0.132724)`; 154 |
| Chest | `(-0.951058,-1.000000,-1.000000)` → `(0.951058,1.000000,1.060037)`; 3,367 |
| Workbench | `(-1.009548,-0.509445,0.000175)` → `(1.009549,0.514791,0.894820)`; 1,400 |

| Candidate/view | Final camera distance | Corrections | Occupancy | Alpha | Margins | No crop |
|---|---:|---:|---:|---:|---:|---|
| Candle front | 0.249118 | 1 | 0.5474 x 0.8506 | 0.3755 | 456/471/177/129 | yes |
| Candle right | 0.259487 | 1 | 0.5913 x 0.8311 | 0.3848 | 409/428/201/145 | yes |
| Candle back | 0.276960 | 2 | 0.4644 x 0.8184 | 0.3196 | 548/549/198/174 | yes |
| Candle left | 0.246775 | 1 | 0.6304 x 0.8481 | 0.3906 | 383/374/175/136 | yes |
| Chest front | 2.477395 | 2 | 0.8125 x 0.7964 | 0.5183 | 192/192/163/254 | yes |
| Chest right | 2.712808 | 2 | 0.7822 x 0.7759 | 0.3375 | 220/226/212/247 | yes |
| Chest back | 2.962741 | 2 | 0.8135 x 0.5283 | 0.3431 | 191/191/497/469 | yes |
| Chest left | 2.712808 | 2 | 0.7822 x 0.7764 | 0.3376 | 226/220/212/246 | yes |
| Workbench front | 3.837282 | 0 | 0.8809 x 0.4282 | 0.2291 | 122/122/597/574 | yes |
| Workbench right | 2.939404 | 2 | 0.7720 x 0.7310 | 0.3109 | 233/234/289/262 | yes |
| Workbench back | 3.832407 | 0 | 0.8809 x 0.4316 | 0.2294 | 122/122/596/568 | yes |
| Workbench left | 2.939404 | 2 | 0.7720 x 0.7310 | 0.3109 | 234/233/289/262 | yes |

Exact camera locations, targets, angles, initial projected NDC bounds, and
predicted margins are retained in each candidate's immutable
`reports/multi-angle-preview-007.json`. Those reports assert
`initial_geometry_bounds_contained`, per-view `no_crop`,
`all_views_no_crop`, and `all_views_useful_occupancy`.

## Before/after evidence and hashes

The baseline and final views have identical 2048x2048 resolution and transparent
backgrounds.

| Candidate/view | Baseline `multi-angle-002` SHA-256 | Final `multi-angle-007` SHA-256 |
|---|---|---|
| Candle front | `223862f7e4696398f1d1380562de9f0a59195ec6131d3e07b4fabc10cc91116c` | `52e8014e8b477350a53dec16543ba869d4d489a83a8103bad209eec51a654a1e` |
| Candle right | `4c5e04b4ac741a30378ecb5196bbaf1de4b48bc5c7e244b8833f60507e374bcc` | `42ceb98a0bb4a12cefd49ae93a70167f6fa945248251a58ee184af2dad010d49` |
| Candle back | `bfbdde5d3b099ae4661a4f91d304b10c3eb3ead9802a93ba2d2b7294e81d9bce` | `1446c4b6dad795d6af965f3e19e4517ef3a830d528e30bec8cea11a5222a79d2` |
| Candle left | `42a70d484049ef62aa4415d2b96e9b0196fa518629bfde0c41d1343385a2f0de` | `ae7a98a77faa4dc2e8b95c07dda5cf42d3f19437b7129b743f8e43f0c99050f8` |
| Chest front | `0aa18439576c6e840680952a0052e53c231c284195078e621f9dd2ed70d888fd` | `c794734455072a1e1e41b0df4577f5dd0d8b5e63f1903ac9ff5d8de2161a0e98` |
| Chest right | `6d1e5121338edb21dfae59cf63363c07bbb7866ffe256fcdeeee3ee31d7bf9f3` | `a8164cf6104a0725c73102974d209d56c613fa6c4cbe4e5db25a7ef2fc53437a` |
| Chest back | `ba780362ab7d42e30b1f396f6d55e74674a8248ea99e226e91d2e4070bd06964` | `54490638b94b7c48345c231ef4f8d4c4d367c72f08951a218b342607cdae80fc` |
| Chest left | `0fe5744b5ee532520f5008ef575c131425b287950c222e47fa8de112cf13e54f` | `03cc396f1df33d748c417939999ea978b22197dca2f809ccf7aa061da85d9984` |
| Workbench front | `64b1c1fdedb1e2b3be98342e06766b857a047278c8d2d7d1e51e86533fa34d05` | `6be177f58b8f3e70e382cdaeeb2f28243e821c0291e6c12690190072a8d520ae` |
| Workbench right | `60faa854033eb37dbfa58191a78d1bf268dfe6d11dd06a6735a3edc0a90ca3f2` | `f075bae5a6586dc875fdf98cc4533735f7a6432e9afef9ce53e3d6f10af65afc` |
| Workbench back | `bf2f36aefa828947e4d1431f1e5698cde0393d696442e67f6d0381e3498c331f` | `1a5b097c45999aefc37bb75cf599618c507bf2f2dd4e97601046c35b53e2eb88` |
| Workbench left | `63544b2836275c1bfd57a11290d4e8ed54d560f326ebc5f2fd9de6b5bc618c23` | `70ba605363e50613dedccbc6154aa18dc57f9df86c96382da3cae9e5c004c11b` |

Final report hashes are candle
`149f084917d12f0bbf7b072c6d9af2a98c2097a9d8c4a9b9cb49906934502ea5`,
chest
`10a12d6e38f68273c195fa964c04b66cfef4b37221c176d2c1a309d86be00f73`,
and workbench
`8cb978c29adaee82bc61a6fb8ca380dac2a1a5f7b899542c89dabe8a9a9d7e31`.

## Evidence history

Sets 003 through 006 are retained diagnostic evidence. Set 003 exposed that an
aggregate AABB still framed sparse silhouettes poorly. Sets 004 and 005
validated evaluated-vertex projection but showed that geometry containment
alone did not guarantee useful visible occupancy. Set 006 proved the bounded
alpha correction. Set 007 repeats that visual result with unambiguous report
field names separating initial geometry fit from final camera facts. Nothing
was overwritten or removed. Candle-only sets 008 and 009 tested lower and more
directional studio lighting after the independent failure; neither made the
source reliably recognizable, so the production renderer retained its prior
lighting authority.

## Verification

- Focused framing/static-batch tests: 13 passed.
- Ruff focused check: passed with cache disabled.
- Exact candidate audits: passed for all three current manifests and all
  retained artifacts.
- `foundry audit-all`: passed 17 candidates before the two retained lighting
  diagnostics; final audit passes with candle 67 artifacts, chest 62,
  workbench 62.
- Independent visual review: chest and workbench pass recognizability,
  centering, useful occupancy, material survival, and no apparent crop, with no
  regression. Candle fails recognizability/material presentation in both
  baseline and final evidence despite passing centering/occupancy/no-crop.

The remaining question is source/control suitability rather than framing:
either explicitly accept the textureless white candle as a geometry-only
control, or replace it under a new directive with a recognizable immutable
control. DM-013 must not claim complete visual acceptance without that decision.

No network, paid provider, approval, publication, release, Asset Library
promotion, or Vandrel mutation occurred.
