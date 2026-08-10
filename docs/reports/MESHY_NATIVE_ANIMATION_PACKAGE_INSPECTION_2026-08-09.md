> Reference only. If this report conflicts with Foundry governance or a
> corridor contract, the higher authority wins.

# Meshy-native animation package and Brukk canary decision

**Date:** 2026-08-09
**Provider writes, downloads, or spend:** None
**Library, Vandrel, release, or approval mutation:** None

## Decision

The newest plausible Meshy archive is safe to intake as an unreleased local
technical candidate. It contains one FBX with one material, one skin, the exact
observed Meshy 24-joint hierarchy, zero unweighted vertices, and ten distinct
actions. `Running` and `Walking` are endpoint-closing in-place loops. Four
actions remain UUIDv7 names because the controllable Meshy session currently
shows `Log In`; no semantic name or provider task metadata was invented.

The package is suitable for a Meshy-native motion-corridor canary, but it is
not an actual Brukk model. Its carrier mesh has 7,340 vertices and 5,087 faces.
Brukk's currently exported local `Male Cave Adult Average Low Poly.fbx` is an
unrigged 2,601-vertex mesh with no armature, actions, or vertex groups. The
carrier therefore proves only native processing and motion preservation; it
does not recommend locally binding that unrigged export.

The VP-directed preferred character path is to resolve Brukk's and Takka's
original identities in the signed-in Meshy account and intake their
provider-native biped auto-rig outputs while retaining the Meshy skeleton,
skin/binds, materials, and textures. This package neither performs nor
authorizes those provider actions, and it does not create a Mixamo migration
bridge.

## Exact sources

| Source | Size | SHA-256 | Custody statement |
| --- | ---: | --- | --- |
| `C:/Users/vandr/Downloads/Meshy_AI_biped (2).zip` | 1,191,509 | `ab17ab1e1e57045aa8d5436972253edac0a895b3e53e9f4b8c8b40b2dc80eab4` | User-selected local source; local unreleased technical use only |
| `Meshy_AI_biped/Meshy_AI_biped_Meshy_AI_Meshy_Merged_Animations.fbx` | 2,347,260 | `48b6e3d300bc32c9b67f8747bb9dd9f36418b37f45c4be3989048c9f360720b3` | Exact immutable archive member; provider task and license metadata not embedded |

The ZIP contains one non-directory entry, uses Deflate, has CRC32 `25a80ced`,
and is FBX binary version 7400. The checked-in structured records are:

- `evidence/meshy-native-canary/source-package-inspection-2026-08-09.json`
- `evidence/meshy-native-canary/source-provenance-2026-08-09.json`

## Action decision table

| Exact action | Technical result | Eating fit | Butchery fit | Next action |
| --- | --- | --- | --- | --- |
| Four `target_character|019f…` UUIDv7 actions | Non-loop motions; exact IDs retained | Unknown | Unknown | Resolve only through a later authenticated read-only account lookup |
| `Female_Crouch_Pick_Fruit_Basket_Stand` | 7.10 s collection motion | Low; no eating/chewing evidence | No | Keep as foraging reference |
| `Female_Stand_Pick_Fruit_Basket` | 6.20 s collection motion | Low; no eating/chewing evidence | No | Keep as foraging reference |
| `Female_Walk_Pick_Put_In_Pocket` | 9.53 s traveling collection motion | No | No | Possible gathering motion only |
| `Red_Carpet_Walk` | 5.97 s stylized walk | No | No | Do not map to work activity |
| `Running` | 0.63 s in-place endpoint-closing loop | No | No | Locomotion regression canary |
| `Walking` | 1.03 s in-place endpoint-closing loop | No | No | Locomotion regression canary |

No mapped action currently proves the requested eating/chewing or kneeling
cutting/dressing behavior. Candidate evidence must say so even if an unresolved
UUID later turns out to be relevant.

## Upright canary review

Candidate `meshy_native_brukk_canary_001` now retains the exact two source
roots and an immutable first technical attempt that exposed a reclined export.
The current superseding output is
`meshy_native_canary_model_005`, SHA-256
`fb221d76082ae3e4c65569910d9908fc2f1b4ae323913441c3bab4fd1da72059`.
Its normalization report SHA-256 is
`a88114232cb250c08c3f4e1e3383cc0e90ba5869c87631b0424886212ffcc258`;
its all-ten-action playback report SHA-256 is
`d757551be19e865d7b010b394fd57b32028cb0b2b82c45807565d24d46a0ea49`.
Attempt 004 proved the corrected timing but retained Blender installation paths
inside captured stdout; immutable attempt 005 supersedes it with portable,
redacted process logs. Running, Walking, and the inspected UUID action each
match their bound normalization durations within 0.000334 seconds, below the
0.002-second contract tolerance. The final report contains only registered
WebP evidence identities and no references to deleted temporary PNG frames.

Neutral-gray lateral playback shows an upright, bounded carrier with no gross
skin explosion. The UUID actions remain unmapped, but their visible motion can
be described without assigning provider semantics:

- `019fe8ca-a6c4-7968-822f-92efebbab5a4` is the strongest provisional eating
  candidate: a crouched hand rises toward face height and returns. It does not
  visibly prove chewing or a clean loop.
- `019fe8c8-1952-7ce9-a611-33851c9cf0b2` is a stable low squat with modest
  two-hand work at knee height; it could support a work pose but does not prove
  cutting.
- `019fe8d4-0feb-798a-bcbb-81126f26e17f` keeps both hands low near the ground
  with limited visible stroke; it is a possible dressing posture, not a
  credible demonstrated cutting loop.
- `019fe8d7-ed16-7b82-a594-728d821ee711` bends forward and reaches down before
  returning to a squat. It is useful posture motion, but no tool-contact or
  repeated cutting action is visible.

Accordingly, the package supplies a plausible crouched hand-to-mouth prototype
and several low work postures, but still does not close the requested exact
eating/chewing or kneeling butchery content gap.

## Smallest subsequent provider-native adoption package

A separate, explicitly authorized package should first perform read-only
account resolution and record, for each of Brukk and Takka:

- signed-in account identity or redacted account evidence and exact character
  task/model UUID, original display name/prompt, creation time, and source
  output identity;
- exact auto-rig task UUID, preset (`biped`), state, input character identity,
  output/file identity, format, `withSkin` status, and any provider-native
  animation association;
- observed joint names/order/hierarchy, rest and inverse-bind facts, skin and
  unweighted counts, material/texture identities, and whether the rig matches
  the observed 24-joint Meshy-native profile;
- account-visible entitlement, credit/download cost, license/local-use terms,
  and redacted provider response or page evidence supporting each fact; and
- after separate download authority, exact source/output filenames, sizes,
  SHA-256 hashes, archive membership, and provider task-to-output binding.

The smallest write package after that read-only resolution is one fresh,
unreleased candidate per character containing the exact native character and
auto-rig roots plus their redacted provider evidence, followed by the existing
native structure/playback checks. It must not locally weight the unrigged FBX,
retarget to Mixamo, publish, release, or touch Vandrel.

## Current bounded write package

The new corridor retains the exact ZIP and FBX as separate source roots,
normalizes only the observed Meshy profile, preserves the 24-joint rest/skin
relationship, splits all ten exact actions, and produces neutral-gray continuous
playback. It creates no provider request, Mixamo retarget, general skeleton
framework, gameplay classification, approval, release, Library publication, or
Vandrel file.
