# DM-016 Candidate Custody Binding Result

status: implemented and locally verified
date: 2026-07-28

## Result

Asset Foundry now composes the DM-014 deterministic custody inventory into
candidate manifests, approval freshness, release planning, immutable release
descriptors, library audit, and release-fitness display.

The implementation adds `foundry bind-candidate-custody`, manifest schema v2,
compound `source_contributions`, exact root-source bindings, retained license
evidence, candidate-semantic approval snapshots, and v2 release evidence
custody. Approval and release planning fail closed when custody is absent,
missing, disputed, incomplete, or stale.

Historical manifest/release v1 remains readable and is displayed truthfully as
`historical_v1_unassessed`; no historical descriptor was rewritten.

## Proof

- Full automated suite: passing, with three expected environment skips.
- Ruff: all checks passing.
- Focused tests cover exact evidence retention, missing-rights approval denial,
  unrelated-register freshness stability, v2 evidence publication, release
  path safety, and legacy v1 release-fitness display.
- No real approval, publication, network action, historical mutation, or
  Vandrel write was performed.

## Ownership

Asset Library remains the authority for rights semantics, custody policy, and
the evidence request ledger. Asset Foundry enforces those decisions and carries
the bound evidence into candidates and future immutable releases.

## Real DM-006 chest exercise

The v2 path was exercised once on
`dm006_quaternius_chest_wood_001`, without approval or publication.

- Before: manifest v1 revision 14, SHA-256
  `d70daf646a27c05c1749d0fe62f5f3c574a603dae6a44df6ca1185d556c48869`;
  workflow `review`, validation `passed`, approval false, release false.
- After: manifest v2 revision 15, SHA-256
  `af018154b436b17f10bac22300ebb10d0f7c1d26338811921e458012517d890c`;
  workflow, validation, approval, and release facts are unchanged. The exact
  prior manifest is preserved as `manifest.previous.json` with the before hash.
- Candidate assertion:
  `d9671e74e8373148b8757f09f7e1e9203e05c6a28dbde0dcb6c66c52dea2a17e`.
- Package:
  `pkg:quaternius:500426d4f80eeeddff6b8423`,
  `Quaternius/Fantasy Props MegaKit[Standard]`.
- Exact source union: the raw `Chest_Wood.gltf` hash
  `b2022f69b76526fcbbc7f7a8855848beeefa6e8a6f55337d923bce38ed03b2b6`,
  its BIN, and all six declared texture sidecars. No root source was omitted.
- CC0 notice: original and retained 837-byte copies both hash to
  `edad12240087a33e08fc031e4e66c2b2b4b2a6d4f086339bde04f741b385fbda`;
  scope is `Quaternius/Fantasy Props MegaKit[Standard]`.
- The bound custody-register hash is the already accepted DM-014 canonical
  register:
  `9a5e006eda1dc80b45f6c4b5b99ed68989192fb3007bd702f7d2323011e99e60`.

Human and JSON release-fitness evidence are retained at
`docs/reports/evidence/dm016/chest-release-fitness.txt` and
`docs/reports/evidence/dm016/chest-release-fitness.json`. Both show passing
integrity and technical validation, exact documented custody, no publication,
and exactly one release blocker: absent human approval. A non-apply `foundry
release` attempt stopped on that same blocker.

The accepted front visual is retained at
`docs/reports/evidence/dm016/chest-front-visual-proof.png`, SHA-256
`c794734455072a1e1e41b0df4577f5dd0d8b5e63f1903ac9ff5d8de2161a0e98`.
It remains the same recognizable open wood-and-metal chest accepted in DM-013;
the source, processed GLB, and all multi-angle preview hashes are unchanged by
the custody bind.

Adversarial tests cover missing and disputed rights, exact compound source
unions with multiple evidence files, stale semantic/source/approval snapshots,
physical evidence-byte tampering, unrelated-register freshness stability, and
explicit immutable v1 historical-unassessed display.
