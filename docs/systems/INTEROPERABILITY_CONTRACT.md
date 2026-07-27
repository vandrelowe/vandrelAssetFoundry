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

## Compatibility strategy

- Version manifest and release schemas.
- Prefer additive optional fields within a schema version.
- Never change field meaning silently.
- Keep deterministic fixtures representing supported consumer contracts.
- Detect incompatible consumer expectations and report them; do not mutate the
  sibling repository to make a test pass.
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
separate, consumer-validated retarget corridor. Grafted clip names and donor
artifact hashes are technical evidence only; Vandrel retains authority over
runtime clip promotion, semantic animation keys, root-motion handling, and
visual acceptance.
