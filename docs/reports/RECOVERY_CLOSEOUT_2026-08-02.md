> Reference only. If this document conflicts with Foundry governance,
> architecture authority, or a corridor contract, the higher authority wins.

# Desktop migration recovery closeout

**Date:** 2026-08-02  
**Scope:** Read-only workspace and sibling-repository recovery, plus bounded
Foundry documentation/schema correction  
**Network/provider spend:** None  
**Publication, commit, push, deletion, or Vandrel write:** None

> **Superseded ACL status (2026-08-02):** Later Phase 4B.2 evidence proved the
> normal offline `audit-all` gate green for all 39 candidates and
> `audit-library` green for all 173 checks. The ACL-blocked results preserved
> below remain the accurate earlier observation, not the current gate status.
> This recovery source checkpoint is still separate from candidate approval,
> Library publication, and Vandrel acceptance.

## Recovered authority and configuration

The existing repository and configured workspace were preserved. `foundry.toml`
loads successfully, Foundry's Vandrel write switch is disabled, the Meshy
credential is named only by environment-variable reference, and the configured
Godot and Blender executables are discoverable. No usable migrated session
handoff was present in `session-recall`; repository contracts, manifests,
reports, Git history, and current uncommitted files are therefore the recovery
record.

The source worktree contains a coherent uncommitted capability bundle spanning
provider custody assertion 1.2, unreleased lane reclassification, asset-class
mesh budgets, excavation-aware prompt guidance, real-world scale calibration,
release-v2 projection, schemas, CLI commands, and focused tests. It is
user-owned work and was not committed or discarded during recovery.

## Live workspace reconciliation

The configured workspace contains 39 manifests:

| Workflow state | Count |
|---|---:|
| Approved | 20 |
| Review | 12 |
| Draft | 3 |
| Downloaded | 2 |
| Rejected | 2 |

The 17 unfinished manifests are:

- Downloaded: `granite_bedrock_outcrop_001`, `rounded_rock_outcrop_001`.
- Draft: `caveman_ungulate_carcass_001`, `dm006_malformed_traversal_001`,
  `meshy_rounded_rock_outcrop_001`.
- Review: `dm006_quaternius_candle_001`,
  `dm006_quaternius_chest_wood_001`, `dm006_quaternius_workbench_001`,
  `meshy_ai_0731151628_texture`, `meshy_berry_basket_001`,
  `meshy_biped_animations_001`, `meshy_biped_character_001`,
  `meshy_rounded_rock_outcrop_002`, `meshy_rounded_rock_outcrop_003`,
  `meshy_rounded_rock_outcrop_004`, `quaternius_axe_bronze_001`, and
  `quaternius_torch_metal_001`.

The creative backlog has been reconciled conservatively. Its rounded-rock row
now records the five live related manifests. Other manifest names were not
mapped onto loosely similar ideas because the manifest remains authoritative
and similarity of appearance or wording is not identity.

## Workspace audit and ACL characterization

`audit-all` discovered every manifest and reported no discovery errors. It
failed 14 candidates solely because recorded files inside particular Godot
staging subdirectories were unreadable to the recovery process:

- `granite_bedrock_outcrop_image_001`
- `meshy_ai_0731151628_texture`
- `meshy_circular_stone_platform_001`
- `meshy_emerald_crown_fern_001`
- `meshy_emerald_fern_002`
- `meshy_emerald_fern_003`
- `meshy_inverted_roots_tree_001`
- `meshy_inverted_roots_tree_002`
- `meshy_low_poly_berry_tree_001`
- `meshy_low_poly_berry_tree_002`
- `meshy_mossy_boulder_dome_001`
- `meshy_rounded_rock_outcrop_002`
- `meshy_rounded_rock_outcrop_003`
- `meshy_rounded_rock_outcrop_004`

The candidate-level audit detail consistently identifies the staged model,
wrapper scene, or validation project beneath `godot_staging` as unreadable with
Windows error 13. Other artifacts in those same candidates continue to match
their recorded hashes and sizes, and all manifest relationship/event checks
complete. The readable parent staging directories show inherited full control
for the owner and inherited modify access for the configured offline sandbox
SID, while selected generated child directories cannot even have their ACL
queried by the current process. This is an ACL/readability failure, not evidence
of content corruption or hash drift. No ACL was changed and no retry attempted
to bypass custody policy.

The immutable asset-library audit passes all 173 catalog, schema, identity,
hash, size, and custody checks.

## Validation evidence

- `ruff check .`: passed.
- Full `pytest -q`: passed at 100 percent with three expected skips.
- Focused scale, release, provider-custody, lane-reclassification, and schema
  tests: passed.
- Pydantic/checked-in manifest and release-v2 schema parity: passed through the
  schema tests.
- `audit-library`: passed 173 checks.
- `audit-all`: intentionally remains nonzero for the 14 ACL-blocked candidates
  above, with zero manifest discovery errors.
- `git diff --check`: passed; line-ending conversion warnings remain advisory.

### Lane B correction validation — 2026-08-02

- `.\.venv\Scripts\python.exe -m pytest -q tests/test_scale_calibration.py tests/test_release_descriptor.py tests/test_publish_release.py tests/test_schema.py`:
  passed at 100 percent. This includes checked-schema/Pydantic parity and the
  historical v2 no-bounds compatibility fixture.
- `.\.venv\Scripts\python.exe -m ruff check .`: passed with
  `All checks passed!`.
- `.\.venv\Scripts\python.exe -m pytest -q`: passed at 100 percent with three
  expected skips.
- `.\.venv\Scripts\python.exe -m vandrel_foundry audit-library`: exit 0;
  passed 173 checks, including historical descriptor schema validation.
- `.\.venv\Scripts\python.exe -m vandrel_foundry audit-all`: expected exit 1;
  exactly the same 14 ACL-blocked candidates failed and discovery errors
  remained zero.
- `git diff --check`: passed; only pre-existing advisory line-ending warnings
  were emitted.

No provider/network call, spend, approval, release, publication, Asset Library
write, candidate/workspace/journal write, ACL change, Vandrel write, Git stage,
commit, or push occurred. Lane B stops here for independent re-review.

## Recovered bundle review

The capability boundaries are consistent with Foundry governance:

- Provider custody consumes already retained authenticated task evidence and a
  checked-in rights policy; it makes no provider call.
- Lane reclassification is limited to processed, unreleased candidates and
  invalidates approval and lane-dependent validation.
- Mesh budgets guide provider submission and review without assigning gameplay
  meaning.
- Excavation classes affect prompt language only; Vandrel retains terrain,
  collision, navigation, and gameplay authority.
- Scale calibration binds exact processed-model and preview-report hashes and
  is required for new approval.

One review defect was corrected: release descriptor v2 claimed to carry
evaluated world-space scale bounds but its model and emitter included only
dimensions. `source_bounds_min` and `source_bounds_max` are now closed-schema
release fields, emitted from every new approved calibration, validated for
paired presence and ordering, and covered by the release-plan test. They remain
optional while reading historical immutable v2 releases that predate this
projection. Checked-in schemas were regenerated from their Pydantic authorities.

Independent review then required a bounded scale-evidence hardening correction.
Manifest calibration and release-v2 scale records now reject non-finite numeric
evidence. New manifest calibration requires paired, finite, ordered bounds and
requires every recorded dimension to equal `maximum - minimum` on the same axis
within a documented `1e-6` relative and absolute tolerance. Calibration performs
the same check against the hash-bound Blender report before saving approval
evidence. Release-v2 applies the same invariant whenever bounds are present,
while an explicit historical-v2 test fixture proves that immutable descriptors
containing dimensions but neither bound remain accepted by both the Pydantic
model and checked schema without mutation.

## Vandrel and Dev Master boundary

The Vandrel checkout is heavily dirty with active Dev Master work spanning mod
boundaries, volumetric terrain/navigation, runtime scenes, generated import
state, and content assets. It was inspected read-only. No Foundry consumer
integration should write there until Dev Master or the user supplies a clean,
asset-scoped target and confirms that the intended immutable release is the
one to validate. Foundry still must not register gameplay content or assign
authoritative `res://` destinations.

## Safest continuation

The next bounded action is to resolve the Godot-staging ACL discrepancy through
the existing custody/ACL policy owner, then rerun `audit-all`. That work should
first determine why generated child directories diverged from their readable
parents; it must not recursively rewrite workspace ACLs or recreate staging
data without an explicit, reviewed repair plan. After a green audit, the
current source bundle is ready for an intentional checkpoint decision.
