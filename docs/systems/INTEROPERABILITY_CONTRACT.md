# Vandrel Ecosystem Interoperability Contract

**Status:** Active boundary; handshake schemas evolve by version

## Participants

- Foundry creates candidates and approved technical release packages.
- The asset library distributes immutable approved revisions.
- Vandrel explicitly imports selected revisions and owns runtime integration.
- The future mod manager owns gameplay metadata and mod resolution.

## Handoff rules

Foundry release data may include:

- stable asset ID, display name, lane, and release revision;
- file roles, relative paths, hashes, sizes, and formats;
- provenance and Foundry manifest revision;
- measured geometry, materials, textures, skeleton, and animation facts;
- validation results and reviewer approval evidence;
- declared intent such as collision recommendation.

It must not claim or assign:

- Vandrel `res://` destination paths;
- enabled runtime catalog entries;
- gameplay classification, item stats, recipes, slots, or actions;
- active collision, navigation obstacles, or construction blockers;
- mod dependencies, load order, or overrides;
- canonical humanoid/animation acceptance without Vandrel-side validation.

## Vandrel compatibility references

When changing this handshake, inspect the current read-only Vandrel documents:

- `docs/ASSET_ORGANIZATION.md`
- `docs/ARCHITECTURE_AUTHORITY.md`
- the consuming `docs/systems/*_CONTRACT.md`

The current source/runtime split means Foundry should package portable files and
provenance while Vandrel chooses source placement, reviewed runtime wrappers,
catalog registration, and active `res://game/**` paths.

## Authorized consumer integration

The standing downstream-integration exception in `GOVERNANCE.md` authorizes an
AI development session to exercise the consumer side of this handshake for an
approved, release-enabled, immutable library revision. It may copy the exact
release into a new asset-scoped Vandrel runtime path, create or update the
asset's Vandrel-owned wrapper and bounded debug scene, allow Godot to import the
files, and run a finite bomb test.

This is validation of a selected release, not authority transferred to Foundry.
The session must preserve unrelated checkout changes and must not use this
exception to edit gameplay catalogs, runtime registries, `Main.tscn`, ECS or
gameplay behavior, or other assets. Commit, push, deletion, overwrite, and
runtime promotion remain separate explicit actions. The validation result may
report unit conversion, material, skeleton, skin-bind, animation, and visual
playback findings, but only Vandrel can accept the wrapper or promote clips into
its shared animation vocabulary.

Vandrel character-lab conclusions use the versioned
`vandrel_character_asset_acceptance/1.0` consumer contract, currently tracked
at Vandrel commit `b8fb0762`. Foundry may import one asset-keyed entry and its
matching catalog-grounding audit record as immutable evidence. A consumer finding affects
Foundry promotion only when its `foundry_binding.asset_id` and
`foundry_binding.model_sha256` exactly match the current processed model and
the finding is owned by `asset_foundry`. Unbound legacy entries are accepted
only through an explicit diagnostic-only option. Vandrel runtime corrections,
scene paths, animation semantics, and gameplay policy remain consumer-owned
even when their evidence is retained by Foundry.

## Compatibility strategy

- Version manifest and release schemas.
- Prefer additive optional fields within a schema version.
- Never change field meaning silently.
- Keep deterministic fixtures representing supported consumer contracts.
- Detect incompatible consumer expectations and report them. Asset-scoped
  wrapper corrections may be made during an authorized consumer integration
  test, but portable release evidence must retain the original artifact hashes
  and must not conceal a release defect.
- Record which external contract revision a compatibility decision used.

## Humanoid rig compatibility evidence

Foundry may maintain a versioned mapping from a named source rig to Godot's
`SkeletonProfileHumanoid` bone vocabulary. A compatibility report must bind the
mapping version and hash to exact target-character and animation-donor artifact
hashes. It may measure required-bone coverage, mapped hierarchy, animation
targets, identical joint names and parent relationships, and local joint rest
transforms.

The bundled `meshy_humanoid/v1` mapping reflects Meshy's observed 24-joint
source rig. Its spine names run from the hips upward as `Spine02`, `Spine01`,
then `Spine`; the Godot profile mapping must preserve that anatomical order
rather than sorting by suffix.

A report distinguishes a humanoid retarget candidate from a direct raw-transfer
candidate. Compatible mapped hierarchies can qualify for retargeting even when
their rest transforms differ. Direct transfer additionally requires identical
joint names, hierarchy, and numerically matching local joint rest transforms.
Neither result proves inverse-bind equivalence, good deformation, correct root
motion, acceptable motion quality, or Vandrel runtime acceptance. Those
decisions require consumer-side visual playback validation under the current
Vandrel animation contract. Foundry must not emit a Vandrel runtime path,
wrapper, or animation-library registration from this check.

Only when exact joint names, hierarchy, and local rest transforms match may
Foundry create a new candidate GLB by replacing its animation array with the
donor's shared animation library. This is a format-level derivation, not
general retargeting. A rest-transform mismatch must fail closed and route to a
separate, baked retarget corridor with recorded visual samples. Grafted or
retargeted clip names and donor artifact hashes are technical evidence only;
Vandrel retains authority over runtime clip promotion, semantic animation
keys, root-motion handling, and visual acceptance.
