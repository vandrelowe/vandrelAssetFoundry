> Reference only. If this document conflicts with Foundry governance,
> architecture authority, or a relevant corridor contract, the higher
> authority wins.

# Asset backlog

This is the durable idea backlog for candidate assets. It records creative
intent and suggested generation order; it does not create a candidate, reserve
an asset ID, authorize a provider call, spend credits, approve an output, or
assign Vandrel gameplay meaning.

The source list came from an earlier Asset Foundry planning conversation. Its
creative categories are retained below, but its proposed lane model is not:
entries use the current Foundry lanes and mesh-budget profiles.

## Status vocabulary

- `idea`: available for selection.
- `selected`: chosen for prompt drafting or a bounded experiment.
- `candidate`: represented by an active Foundry manifest; the manifest is then
  authoritative for workflow state.
- `retired`: intentionally removed from consideration, with a reason noted.

Changing a row to `candidate` should include the permanent Foundry asset ID.
Do not use this backlog as a substitute for manifest or provider-task state.

## First live Meshy trial status

**Rounded rock outcrop** was the recommended first text-to-3D trial. It has a
simple, recognizable silhouette; its success can be judged without semantic
guesswork; it exercises the excavation-aware prompt guidance; and it fits the
small `rock_outcrop` budget. Failure would be inexpensive to diagnose compared
with foliage, thin branches, racks, or skeletal remains.

Acceptance focus: one isolated, low, broad rock mass; natural asymmetry;
weathered cracks; a believable buried continuation; no soil disk; and no
table, altar, platform, masonry, stairs, or carved architecture.

The configured workspace now contains the original downloaded candidate
`rounded_rock_outcrop_001` plus the Meshy experiment series
`meshy_rounded_rock_outcrop_001` through `meshy_rounded_rock_outcrop_004`.
The first trial is therefore no longer pending. The manifests, not this
backlog, govern their individual workflow states and evidence.

## Preserved but paused — Pleistocene creatures

The five `prompts/examples/pleistocene_*.txt` creature concepts are preserved
historical creative work only. They are not selected backlog items, active
provider inputs, or authority to create candidates, launch previews, call a
provider, spend credits, approve assets, or publish releases. Resume them only
after an explicit user decision reopens the creature corridor.

## Active focus — reference-first prehistoric scene dressing replacement

Animal-character and creature-animation work is paused. The active direction
is a coherent set of original prehistoric scene-dressing assets that can
replace Quaternius-derived content without copying its visual design.

The first batch favors high-reuse vegetation and readable ground cover. Each
asset is a self-contained cluster rather than a terrain tile, card sheet, or
scene. Variants should differ in silhouette and density so Vandrel can scatter
them without obvious repetition.

This batch is reference-first. Each prompt describes a concept image to be
generated without a Meshy call. The user reviews and selects the image before a
candidate receives it as a reference and makes one explicitly authorized
Image-to-3D submission with native remeshing. Do not use Meshy Text-to-3D as the
concept iteration loop for these entries.

| Order | Asset | Role | Lane / budget | Status | Prompt |
|---:|---|---|---|---|---|
| 1 | Dense dry grass tussock | common ground cover | `static_prop` / `dense_ground_cover` | `candidate` (`meshy_dense_dry_grass_tussock_001`, rejected text-first experiment; `meshy_dense_dry_grass_tussock_002`, reference-first candidate) | `prompts/examples/prehistoric_dense_dry_grass_tussock_001.txt` |
| 2 | Lush broad-blade grass clump | damp ground cover | `static_prop` / `dense_ground_cover` | `candidate` (`meshy_lush_broad_blade_grass_clump_001`; reference-first experiment, detached geometry, not visually accepted) | `prompts/examples/prehistoric_lush_grass_clump_001.txt` |
| 3 | Thick bracken fern patch | forest understory | `static_prop` / `dense_ground_cover` | `selected` | `prompts/examples/prehistoric_bracken_fern_patch_001.txt` |
| 4 | Forest mushroom cluster | focal ground detail | `static_prop` / `small_plant` | `selected` | `prompts/examples/prehistoric_mushroom_cluster_001.txt` |
| 5 | Dense berry bush | food-bearing shrub | `static_prop` / `large_bush` | `selected` | `prompts/examples/prehistoric_dense_berry_bush_001.txt` |
| 6 | Tangled thorn scrub | harsh scrub cover | `static_prop` / `large_bush` | `selected` | `prompts/examples/prehistoric_tangled_thorn_scrub_001.txt` |
| 7 | Harvested ungulate carcass | narrative/food-site prop | `static_prop` / `large_skeletal_remains` | `candidate` | `caveman_ungulate_carcass_001` |
| 8 | Mixed bone-and-skull scatter | narrative ground detail | `static_prop` / `skeleton_scatter` | `selected` | prompt pending |

Foliage acceptance emphasizes thick, readable opaque geometry, several joined
growth points, natural asymmetry, and a compact scatterable footprint. Reject
paper-thin card fans, flat terrain disks, flowerpot arrangements, ornamental
garden shapes, isolated single leaves, and implausibly dense solid blobs.

### Quaternius replacement map

This table expresses creative replacement intent only. It does not reject,
delete, overwrite, unpublish, or alter any current candidate or release.

| Existing Quaternius-derived candidate | Original role | Original prehistoric replacement |
|---|---|---|
| `dm006_quaternius_candle_001` | small light | rendered-fat stone lamp or resin torch stub |
| `dm006_quaternius_chest_wood_001` | storage | hide-lashed branch cache with woven inner basket |
| `dm006_quaternius_workbench_001` | work surface | low hide-working frame with stone tools and sinew |
| `quaternius_anvil_001` | crafting station | broad knapping stone with flint flakes and hammerstone |
| `quaternius_axe_bronze_001` | hand tool | hafted chipped-stone axe with rawhide binding |
| `quaternius_barrel_001` | bulk storage | large hide-covered woven storage basket |
| `quaternius_crate_wooden_001` | portable storage | rough branch-frame carrying basket or cache |
| `quaternius_stool_001` | camp seat | low split-log seat with hide pad |
| `quaternius_torch_metal_001` | carried light | resinous wood torch bound with bark fibre |

Replacement generation order after the vegetation batch is: knapping stone,
stone axe, resin torch, storage basket/cache, split-log seat, hide-working
frame, then the remaining lighting and storage variants. Each replacement
must stand on its own merits; no Quaternius mesh is a generation reference.

## Priority 1 — establish the generation corridor

These provide varied but bounded tests of solid forms, shallow ground dressing,
organic geometry, and a simple assembled prop.

| Priority | Idea | Category | Foundry lane | Mesh budget | Excavation class | Status | Candidate ID |
|---:|---|---|---|---|---|---|---|
| 1 | Rounded rock outcrop | rocks | `static_prop` | `rock_outcrop` | `excavation_aware` | `candidate` | `rounded_rock_outcrop_001`; `meshy_rounded_rock_outcrop_001`–`004` |
| 2 | Mossy broken stump | natural dressing | `static_prop` | `fallen_log_or_stump` | `excavation_aware` | `idea` | — |
| 3 | Stone fire ring | Paleolithic dressing | `static_prop` | `simple_camp_dressing` | `embedded` | `idea` | — |
| 4 | Tar or mud seep | natural dressing | `static_prop` | `ground_patch` | `surface_clutter` | `idea` | — |
| 5 | River-smoothed boulder cluster | rocks | `static_prop` | `boulder_cluster` | `excavation_aware` | `idea` | — |
| 6 | Tangled exposed root mass | natural dressing | `static_prop` | `root_tangle` | `excavation_aware` | `idea` | — |

## Priority 2 — broaden natural dressing

| Priority | Idea | Category | Foundry lane | Mesh budget | Excavation class | Status | Candidate ID |
|---:|---|---|---|---|---|---|---|
| 7 | Flat cracked bedrock slab | rocks | `static_prop` | `rock_outcrop` | `excavation_aware` | `idea` | — |
| 8 | Riverbed rock shelf | rocks | `environment_near` | `boulder_cluster` | `excavation_aware` | `idea` | — |
| 9 | Cliffside outcrop chunk | rocks | `environment_near` | `talus_pile` | `excavation_aware` | `idea` | — |
| 10 | Fallen rotting log | natural dressing | `static_prop` | `fallen_log_or_stump` | `embedded` | `idea` | — |
| 11 | Half-buried bone scatter | natural dressing | `static_prop` | `skeleton_scatter` | `surface_clutter` | `idea` | — |
| 12 | Half-buried giant skull | natural dressing | `static_prop` | `large_skeletal_remains` | `excavation_aware` | `idea` | — |
| 13 | Half-buried giant rib cage | natural dressing | `environment_near` | `large_skeletal_remains` | `excavation_aware` | `idea` | — |
| 14 | Animal den in roots and stones | natural dressing | `environment_near` | `den_or_nest` | `excavation_aware` | `idea` | — |
| 15 | Shelf-fungus log or stump | natural dressing | `static_prop` | `fallen_log_or_stump` | `embedded` | `idea` | — |
| 16 | Kill-site debris scatter | natural dressing | `static_prop` | `skeleton_scatter` | `surface_clutter` | `idea` | — |

## Priority 3 — foliage and ground cover

Foliage is later because thin leaves, dense overlaps, and transparency can make
generation and validation less predictable than solid props.

| Priority | Idea | Category | Foundry lane | Mesh budget | Excavation class | Status | Candidate ID |
|---:|---|---|---|---|---|---|---|
| 17 | Simple fern clump | ground cover | `static_prop` | `small_plant` | `surface_clutter` | `selected` | active batch: thick bracken fern patch |
| 18 | Primitive cycad-like plant | ground cover | `static_prop` | `small_plant` | `embedded` | `idea` | — |
| 19 | Mossy forest-floor patch | ground cover | `static_prop` | `ground_patch` | `surface_clutter` | `idea` | — |
| 20 | Leaf-litter, sticks, roots, and stones patch | ground cover | `static_prop` | `ground_patch` | `surface_clutter` | `idea` | — |
| 21 | Sparse survival shrub | bushes and shrubs | `static_prop` | `small_plant` | `embedded` | `idea` | — |
| 22 | Tangled thorn bush | bushes and shrubs | `static_prop` | `large_bush` | `embedded` | `selected` | active batch: tangled thorn scrub |
| 23 | Leafy berry bush | bushes and shrubs | `static_prop` | `large_bush` | `embedded` | `selected` | active batch: dense berry bush |
| 24 | Leafy non-berry bush | bushes and shrubs | `static_prop` | `large_bush` | `embedded` | `idea` | — |

## Priority 4 — Paleolithic camp dressing

| Priority | Idea | Category | Foundry lane | Mesh budget | Excavation class | Status | Candidate ID |
|---:|---|---|---|---|---|---|---|
| 25 | Ash and charcoal pile | Paleolithic dressing | `static_prop` | `ground_patch` | `surface_clutter` | `idea` | — |
| 26 | Flat butchering stone | Paleolithic dressing | `static_prop` | `simple_camp_dressing` | `embedded` | `idea` | — |
| 27 | Flint-tipped spear bundle | Paleolithic dressing | `static_prop` | `simple_camp_dressing` | `embedded` | `idea` | — |
| 28 | Rawhide bedroll | Paleolithic dressing | `static_prop` | `simple_camp_dressing` | `surface_clutter` | `idea` | — |
| 29 | Rough stone cairn | Paleolithic dressing | `static_prop` | `simple_camp_dressing` | `embedded` | `idea` | — |
| 30 | Hide drying rack | Paleolithic dressing | `static_prop` | `complex_camp_structure` | `embedded` | `idea` | — |
| 31 | Meat drying rack | Paleolithic dressing | `static_prop` | `complex_camp_structure` | `embedded` | `idea` | — |
| 32 | Bone pile | Paleolithic dressing | `static_prop` | `skeleton_scatter` | `surface_clutter` | `idea` | — |
| 33 | Skull warning marker | Paleolithic dressing | `static_prop` | `warning_totem` | `embedded` | `idea` | — |
| 34 | Bone-and-antler totem | Paleolithic dressing | `static_prop` | `warning_totem` | `embedded` | `idea` | — |

## Priority 5 — large vegetation

These are valuable environment assets but poor first API probes: branch and
foliage topology, ground continuation, scale, collision, and LOD all require
more demanding review.

| Priority | Idea | Category | Foundry lane | Mesh budget | Excavation class | Status | Candidate ID |
|---:|---|---|---|---|---|---|---|
| 35 | Tall tortured canopy-seeking deciduous tree | trees | `environment_near` | lane default | `excavation_aware` | `idea` | — |
| 36 | Dead broken variant of canopy-seeking tree | trees | `environment_near` | lane default | `excavation_aware` | `idea` | — |

The defining tree silhouette is a long narrow trunk, visible gnarled roots,
occasional dead or broken branches, and foliage concentrated at the crown. It
should feel ancient and harsh, as though struggling upward toward the canopy.

## Shared art direction

Favor primitive, prehistoric, brutal, harsh-wilderness forms made from stone,
mud, moss, roots, dead wood, bone, hide, sinew, ash, charcoal, raw branches,
dry grass, leaf litter, flint, and fur.

Avoid cute or toy-like styling, polished fantasy-marketplace presentation,
medieval or modern objects, metal, barrels, crates, houses, tents, neat village
furniture, and symmetrical decorative construction. Prompt files must also
follow `prompts/PROMPT_GUIDANCE.md`, including its excavation wording and the
reference-first composition rules.

## Reconciliation snapshot — 2026-08-02

The configured Foundry workspace contains 39 manifests: 20 approved, 12 in
review, three draft, two downloaded, and two rejected. Seventeen are unfinished
candidate work. Most predate this creative backlog or do not map to a row
without guessing, so they are intentionally not retrofitted into the idea
table. In particular, existing ferns, trees, camp props, Quaternius fixtures,
and humanoid experiments remain manifest-owned work rather than evidence that
similarly worded backlog ideas have been selected.

Before selecting another idea, finish recovery of the current source change
set and decide which existing review candidates should be completed, rejected,
or retained as experiments. A backlog status change never authorizes provider
spend.

## Selection procedure

1. Pick one `idea` and change it to `selected`.
2. Draft its reference-image prompt and generate concept alternatives without a
   Meshy provider call.
3. Obtain explicit user selection of one reference image; revise locally until
   its silhouette and composition are accepted.
4. Create the Foundry candidate manifest, record its permanent asset ID here,
   and retain the selected image with `add-reference`.
5. Invoke paid Meshy Image-to-3D with native remeshing only after explicit spend
   authorization. Text-to-3D requires a separately stated experimental reason.
6. Let the candidate manifest, retained provider evidence, and review records
   govern all subsequent workflow state.
