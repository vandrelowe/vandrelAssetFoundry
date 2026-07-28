# Vandrel Asset Foundry: Objective, Boundary, and Status

> Reference only. If this document conflicts with Foundry governance,
> architecture authority, or the relevant corridor contract, the higher
> authority wins.

**Assessment date:** 2026-07-27  
**Source revision assessed:** `eff54eb` plus the documentation corrections in
the commit containing this report  
**Consumer contract assessed:** Vandrel `b8fb0762`  
**Consumer experiment assessed:** Vandrel `dfd188b9`

## Executive assessment

Asset Foundry is a real, useful local asset-governance and release tool. It is
not yet an autonomous character factory.

The strongest parts are provenance, immutable artifacts, integrity checks,
manual hash-bound approval, immutable release publication, and the explicit
boundary between Foundry, the asset library, and Vandrel. The static-asset
corridor is operational. The workspace and library both pass full integrity
audits.

The weakest and highest-risk part is the humanoid corridor. Foundry can ingest,
inspect, texture, rig, package, and test character candidates, but it has not
yet proven a repeatable character path that produces visually acceptable
results in Vandrel. The Blender rest-pose retarget route produced a badly
deformed consumer result and is now suspended from production approval. The
provider-native Meshy route is technically much more promising, but the latest
consumer experiment has not yet received final visual acceptance and is not a
cataloged game asset.

The project has also accumulated documentation drift because implementation
moved faster than the original phased plan. The code is materially ahead of
the original MVP, while a few overview statements still described earlier
boundaries or capabilities. The governance status and README statements fixed
alongside this report were two examples.

## Objective

The project exists to turn an external or AI-generated 3D candidate into a
traceable, technically assessed, manually approved, immutable release package.
In plain language, it should answer:

1. Where did this asset come from, and what paid/provider work created it?
2. Which exact files and hashes are under review?
3. What processing was applied, by which tool version, and what did it produce?
4. Does the asset meet measurable lane requirements and import into a bounded
   Godot sandbox?
5. What did a human approve, exactly?
6. What immutable revision was published for consumers?
7. What did Vandrel discover when it tested that exact revision?

The objective is deliberately narrower than “make game content.” Foundry
creates and releases technically controlled candidates. It does not decide
what an asset means in the game.

## Asset boundary

The boundary is the main architectural product, not administrative overhead.
Each repository owns a different truth:

| System | Owns | Does not own |
|---|---|---|
| Asset Foundry source repository | Workflow code, schemas, contracts, tests | Candidate binaries or game content |
| Foundry workspace | Active candidate manifests, prompts, provider evidence, source and derived artifacts, validation and review evidence | Published distribution authority |
| Asset library | Immutable published revisions and catalog entries | Active processing state, gameplay meaning, or Vandrel paths |
| Vandrel | Runtime destinations, wrappers, catalog/game registration, gameplay semantics, collision/navigation behavior, canonical rig and animation acceptance | Provider provenance or Foundry approval |
| Future mod manager | Dependencies, overrides, load order, gameplay content authoring | Foundry processing truth or Vandrel engine implementation |

The handoff must be exact and hash-bound:

```text
candidate + provenance
        ↓
Foundry processing and technical evidence
        ↓
human approval bound to exact hashes
        ↓
immutable asset-library revision
        ↓
explicit Vandrel import and consumer validation
        ↓
Vandrel-owned runtime acceptance or rejection
```

Vandrel's character acceptance ledger is useful evidence only when
`foundry_binding.asset_id` and `foundry_binding.model_sha256` match the current
Foundry candidate. A character ID, display name, or source path is not a safe
binding. The current Vandrel ledger and grounding audit contain useful
diagnostics, but their existing records are unbound and therefore cannot act
as Foundry promotion gates.

The standing downstream-integration exception is intentionally narrow. It
allows an approved immutable release to be copied into a new asset-scoped
Vandrel location, wrapped, tested in a bounded scene, imported by Godot, and
reported. It does not authorize gameplay registration, unrelated scene edits,
consumer commits or pushes, or a claim that Vandrel accepted the asset.

## What works now

### Core workflow

- Typed Python CLI with 47 user-facing commands.
- Five configurable lanes: static prop, near environment, distant environment,
  humanoid, and non-release creature.
- Atomic manifest writes, asset-specific locks, portable/traversal-safe paths,
  immutable numbered evidence, and event history.
- External GLB, FBX, and glTF package intake.
- Meshy request preparation, explicit paid submission, polling, redacted
  evidence, ambiguous-submission reconciliation, download, remesh, retexture,
  and rigging support.
- Bounded Blender processing and preview rendering.
- GLB structural inspection, lane-budget checks, bounded Godot import
  validation, and offline review galleries.
- Manual approval and rejection bound to exact artifact hashes.
- Dry-run release planning and explicit recoverable publication to a clean
  Git/LFS asset library.
- Workspace and asset-library integrity auditing.
- Versioned import of exact, hash-bound Vandrel character acceptance evidence.

### Live state

The configured machine passes `doctor`: configuration, five lane definitions,
disabled normal Vandrel writes, Meshy key setting, writable workspace, Vandrel
marker, Godot executable, and Blender executable are all present.

The workspace contains 13 candidates:

- 8 approved static assets with `r001` releases;
- 1 rejected static asset;
- 1 static/prop candidate in review;
- 3 humanoid candidates in review.

Every candidate passed the full artifact integrity audit. The largest, the
female shaman, currently tracks 213 artifacts, illustrating both the amount of
evidence retained and the cost of experimentation.

The asset library contains nine cataloged asset IDs and eleven immutable
revisions: eight static `r001` releases and female-shaman revisions `r001`
through `r003`. All 54 catalog, descriptor, identity, hash, and size checks
pass. Its local `main` is clean at `732356c` and has no configured upstream,
which is consistent with the instruction not to push the library.

The source repository had 72 Python modules, 31 test modules, and 117 directly
declared test functions at assessment time. The last completed full source
validation before this report was 146 passed and 2 skipped; the report commit
is revalidated separately.

## Character corridor: honest status

### Proven

- Meshy retexture and rigging API operations have been exercised live.
- Foundry can retain beauty textures and semantic-mask experiments separately.
- A semantic mask can drive regional material variation without changing
  geometry or skinning, provided the new texture keeps the same UV layout.
- Godot validation now rejects the false-positive pattern where visible static
  geometry sits beside a hidden animated rig. A humanoid pass requires visible,
  nonempty geometry with an actual Godot `Skin` and resolvable `Skeleton3D`.
- Provider-native Meshy FBX characters and same-rigging-task walking/running
  `withSkin` FBXs can be imported directly into Godot without a Blender bake.
- Foundry can ingest Vandrel's versioned consumer report and enforce exact
  asset/hash binding before treating a generic defect as a promotion gate.

### Not proven

- There is no visually accepted, repeatable, automated character path from
  candidate through Foundry release to a promoted Vandrel game character.
- The provider-native female-shaman experiment in Vandrel is a bounded
  candidate/lab experiment, not a registered or accepted game asset.
- The historical shaman `r003` remains in the immutable library because
  immutable history is not rewritten. It is not evidence that the current
  candidate is acceptable; the active Foundry state is back in review.
- Automated semantic masks do not yet reliably understand difficult visual
  boundaries. The shaman experiment confused the animal skull headdress with
  hair. Mask mechanics work; semantic correctness remains a review problem.
- Shared animation-pool compatibility is not established. Two observed Meshy
  bipeds shared 24 bone names and hierarchy yet differed substantially in rest
  rotation and bone proportions. Matching names are not enough for safe raw
  animation reuse.
- Foundry does not choose Vandrel clip names, root-motion policy, equipment
  semantics, or left/right-hand animation variants.

### Rejected route

The Blender `blender_rest_pose_retarget` experiment generated convincing-enough
still evidence but failed in Godot with unit-sensitive hips translation,
skin/import problems, and severe visible deformation. That revealed a serious
validation gap: still images and structural checks did not prove animated
deformation quality. Production approval for that processor is suspended. It
should remain a forensic tool unless its math and continuous consumer playback
validation are redesigned and proven.

### Preferred next route

For characters originating in Meshy, preserve the provider-native Meshy rig,
download same-task skinned animations, and import those FBXs directly into
Godot. Avoid Blender in the production path unless a specific operation cannot
be performed safely without it.

This route should next be proven with one character through:

1. provider-native model and same-task motion intake;
2. continuous turntable and full-body animation playback, including feet and
   root motion in frame;
3. exact visual acceptance or rejection recorded by Vandrel;
4. hash-bound evidence imported back into Foundry;
5. approval and a new immutable release only after that evidence passes; and
6. an asset-scoped Vandrel consumer import of that exact release.

Only after one route passes should it be converted into a batch corridor for
the larger character set.

## Static assets: honest status

Static assets are the mature corridor. Intake, optional local processing,
structural inspection, Godot sandbox validation, manual review, approval,
immutable publication, Git/LFS policy enforcement, and library audit all work.

The limitations are intentional:

- collision is a recommendation, not automatically activated runtime behavior;
- Foundry does not register assets in Vandrel;
- visual quality is manually judged;
- library Git commit and push remain separate from publication; and
- no evidence yet shows high-volume throughput or ergonomics for hundreds of
  candidates.

## Current risks and debt

1. **Visual validation is the main correctness gap.** Structural passes can
   still accompany terrible deformation, framing, material regions, or motion.
2. **Humanoid release history can be misunderstood.** “Latest release r003”
   means an immutable revision exists, not that Vandrel accepts it.
3. **Animation reuse is unresolved.** Provider-native same-task animations are
   safe enough to test; a cross-character shared pool needs real retargeting
   and consumer acceptance, not name matching.
4. **Semantic-mask generation needs a correction loop.** Difficult regions
   require inspectable masks and targeted repair, not a single opaque provider
   result.
5. **The workspace is evidence-heavy.** One experimental character has 213
   artifacts. Retention is valuable, but review UI, evidence grouping, and
   explicit experiment supersession need improvement.
6. **Documentation can lag implementation.** Corridor status should be
   reviewed whenever a feature moves from planned to live or is suspended.
7. **The original MVP framing is obsolete.** It is useful historical context,
   but the current system spans provider, processing, validation, review,
   publication, and a limited consumer handshake.
8. **Human approval remains necessary.** The system should reduce tedious
   review and present decisive evidence, but it should not silently approve
   visual or gameplay quality.

## Recommended priorities

1. Finish the provider-native shaman consumer test with a full-body continuous
   visualizer and record an explicit Vandrel result bound to the exact model
   hash.
2. Feed that exact consumer result back into Foundry and prove that a failure
   blocks approval while a pass enables a new immutable revision.
3. Add a compact “release fitness” view that separates technical integrity,
   human visual approval, Foundry release, and Vandrel runtime acceptance.
4. Build a semantic-mask correction workflow with region overlays and
   localized repaint/reclassification rather than regenerating the whole model.
5. Define and prove the animation strategy: same-task clips for the first
   reliable corridor, then a separate explicit retargeting project for shared
   pools.
6. Batch only the operations proven by the single-character corridor. Do not
   scale an unresolved deformation or texture error across the character set.
7. Exercise the static corridor on a modest batch and measure operator time,
   failures, and evidence volume before claiming production throughput.

## Guidance for the master coordination task

The master task should coordinate contracts and sequencing, not absorb project
ownership.

- Ask Foundry for exact release identity, hashes, technical evidence, and
  Foundry approval.
- Ask the asset library for immutable availability and catalog integrity.
- Ask Vandrel for runtime import, visual playback, gameplay registration, and
  acceptance.
- Require exact bindings when evidence crosses repositories.
- Keep Foundry defects separate from Vandrel-specific correction policy.
- Treat a green technical check, a Foundry approval, a published release, and
  a Vandrel runtime acceptance as four different milestones.

## Bottom line

Asset Foundry has succeeded as an integrity and boundary system and as a
working static-asset release pipeline. It has not yet succeeded as a reliable
character-production pipeline. The correct next move is not more broad
automation; it is proving one provider-native character end to end with
continuous, consumer-side visual evidence, then automating that proven route.
