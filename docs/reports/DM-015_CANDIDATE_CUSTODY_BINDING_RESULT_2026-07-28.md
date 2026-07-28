# DM-015 Candidate Custody Binding Result

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
