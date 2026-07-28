---
directive: DM-011
status: complete
date: 2026-07-27
scope: read-only single-candidate release-fitness view
---

# DM-011 Read-Only Release-Fitness View

## Result

Added `foundry release-fitness ASSET_ID` with human and `--json` modes.
Both render the same versioned service result. The service composes the
candidate integrity audit, existing dry-run release planner, candidate-scoped
library audit, manifest approval bindings, and imported Vandrel consumer
reports. It performs no write and has no network or Vandrel inspection path.

The view deliberately does not define a new readiness state. Release
eligibility is the existing release planner's result, additionally blocked by
a failed candidate integrity audit. Vandrel acceptance remains a separate
consumer dimension and is not invented as a static-release prerequisite.

Peer review tightened three truth boundaries before acceptance: a selected
source with no derived output now has no `current_processed`; approval includes
an exact/stale/unbound comparison with current artifacts; and the newest
consumer report remains visible even when stale while the latest exact-current
report is presented separately. Exact consumer matching requires candidate ID,
processed artifact ID, processed hash, and any declared walk/run bindings.

## Required real-candidate proof

### Female shaman

Read-only JSON inspection of
`meshy_female_shaman_character_001` reports:

- current manifest revision `87`, workflow `rejected`;
- current processed `processed_fbx_012`,
  `e583fa38493609685df0f01f519f9311b772b352b7a34fafc54e119771e05d4f`;
- candidate integrity passing across 228 artifacts;
- technical validation result `failed`;
- human approval `rejected`, with no current approval-bound hashes;
- immutable history `r001`, `r002`, and `r003`, all integrity-passing, clearly
  labeled `historical_only`;
- latest exact-bound Vandrel report
  `vandrel_consumer_validation_report_001`, consumer status `blocked`,
  displayed acceptance `rejected`;
- release eligibility false because the current candidate is not approved.

The latest descriptor is `r003`,
`0fb1abc430f6d4182ce3c6e5ef9cfcc0bc1e46110c503910fbf20bd6a22fe98f`.
Nothing in the view treats those releases as current acceptance.

### DM-006 chest

Read-only JSON inspection of `dm006_quaternius_chest_wood_001` reports:

- current manifest revision `9`, workflow `review`;
- current processed `processed_glb_001`,
  `cb248bc1f3033bc18da7453bdcd532258d1ce0a44e951b335506fc94189f45b9`;
- candidate integrity and technical validation passing;
- human approval `unapproved`;
- no library release and no consumer evidence;
- release eligibility false because approval has not occurred.

This is explicitly review-only despite successful technical checks.

## Coverage

Focused tests cover:

- technically valid but unapproved;
- approved and unpublished;
- historical release mismatching the current approved set;
- current published set with no consumer result;
- exact-bound consumer rejection;
- stale versus unbound consumer evidence;
- exact-bound passing consumer evidence alongside a current release;
- rejected candidate retaining separate historical releases;
- agreement between human and JSON CLI modes.

No dashboard, batch aggregation, approval, publication, repair, provider call,
workspace mutation, library mutation, or Vandrel mutation was performed.
