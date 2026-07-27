# Local Semantic-Mask Recovery Experiment

## Outcome

The female shaman test proves that Foundry can recover a useful four-channel
character mask locally, without a Meshy provider call or credit spend. The
result is not yet clean enough for automatic material-authoring acceptance.

The strongest recovered regions are:

- hair/fur;
- the feather skirt;
- boots and wrist wraps; and
- most exposed skin.

The remaining errors are concentrated around chest ornaments, narrow feather
edges, and a small number of low-poly triangles that cross a semantic boundary.
Those errors are visible in the recorded per-channel isolation previews, so the
candidate remains experimental.

## Recorded evidence

The workspace asset `meshy_female_shaman_character_001` contains three immutable
semantic-mask experiments. Revision 003 is the densest local candidate:

- candidate mask:
  `masks/semantic-mask-experiment-003.png`;
- isolation board:
  `preview/semantic-mask-experiment-003/contact-sheet.png`; and
- report:
  `reports/semantic-mask-experiment-003.json`.

All recorded artifacts and manifest relationships passed `foundry audit`.

## Local method

The experiment used the following offline processing sequence:

1. Blender rendered eight matched beauty views and exact floating-point UV
   coordinate buffers from the hash-verified processed GLB.
2. Grounding DINO Tiny detected character regions from text labels.
3. SAM 2.1 Hiera Small converted the detected boxes into per-view masks.
4. Per-view labels were projected into the original 2048×2048 texture atlas
   through the matching UV buffers.
5. Multi-view votes were resolved to the strict Foundry palette:
   skin red, fur/hair green, cloth blue, and accessories white.
6. Unobserved atlas texels were filled only within the mesh UV coverage.
7. Foundry sampled the resulting mask as Non-Color with nearest filtering and
   rendered baseline plus four channel-isolation previews.

The local model identifiers used for this proof were:

- `IDEA-Research/grounding-dino-tiny`; and
- `facebook/sam2.1-hiera-small`.

Model inference ran on the local NVIDIA GPU. Model packages and caches remained
under ignored `temp/` storage and are not project dependencies or artifacts.

## What the experiment establishes

The original single beauty atlas is not itself the blocker. A second,
UV-aligned semantic mask is enough to let one material graph vary skin, hair,
cloth, and accessories independently.

The Meshy semantic-retexture image did not supply that mask. It was a beauty-like
white/brown texture, and nearest-palette quantization could not recover correct
meaning from it. Multi-view local segmentation is materially better because it
classifies rendered body regions before projecting them back into UV space.

## Acceptance boundary

Strict palette fidelity, class coverage, and successful Blender rendering prove
only that the mask is technically usable as an input. They do not prove that
the regions mean the right thing.

Foundry therefore records semantic-mask experiments with
`usable_for_material_authoring: false`. No experiment may silently replace a
source texture, change approval, or enter a release until a future explicit
acceptance workflow binds review to the exact mask and isolation hashes.

## Recommended next corridor

The next implementation should parameterize the local generator rather than
hard-code this character:

1. add a versioned character semantic profile containing detector phrases,
   class mappings, thresholds, and view layout;
2. configure a user-owned Python executable and model-cache path without adding
   Torch or Transformers to Foundry's runtime dependencies;
3. preflight GPU, model-cache, Blender, and disk-space requirements;
4. run both Blender and local inference through bounded, secret-free process
   environments;
5. record model identifiers, profile version, view overlays, UV coverage,
   confidence, and output hashes;
6. feed the candidate into `foundry experiment-semantic-mask`; and
7. keep acceptance separate from generation.

Before applying the corridor to hundreds of characters, it should pass on
several materially different bodies and outfits. In particular, the profile
needs better handling of torso garments and small accessories than this first
candidate achieved.

## Diversity probe

A follow-up detector-only probe used three existing Meshy exports from
`C:/Dev/outsideassets`:

- `Female Dark Sorcerer Low Poly.fbx`;
- `Feral Apeman Low Poly.fbx`; and
- `Male Athletic Shaman Low Poly.fbx`.

The broader vocabulary successfully located the apeman loincloth and the male
shaman's hair, skirt, bone ornaments, and wrist wraps. It also exposed two
important failure modes:

- the nearly monochrome tattooed sorcerer produced broad false clothing and
  skirt boxes over painted skin; and
- the pale apeman produced good loincloth and head-hair boxes but did not
  reliably identify body fur as a separate region.

Several generic clothing phrases also produced near-full-body boxes. A reusable
runner must reject implausibly broad boxes before SAM segmentation.

This probe rules out one universal phrase list as the default. The versioned
configuration should provide archetype-specific profiles, such as sparse-clothed
human, tattooed/painted human, and furred humanoid, while allowing manifest or
operator hints to extend detector phrases. Foundry should record the exact
profile and hints used so that a mask can be reproduced and audited.
