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
