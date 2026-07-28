---
directive: DM-008
status: complete
date: 2026-07-27
scope: local-only sequential static batch orchestration
---

# DM-008 Fail-Isolated Static Batch Orchestration

## Result

Added `foundry run-static-batch PLAN --ledger LEDGER`. It consumes a strict
schema-version-1 JSON plan and calls the existing Foundry services sequentially.
It does not implement provider, approval, publication, asset-library, gameplay,
or Vandrel actions.

Plans declare a failure policy (`continue` or `stop`) and rerun policy
(`resume` or `fail`). Resume skips a stage only when manifest authority proves
the immutable stage exists for the current selected source/processed artifact.
Fail reports an already-completed stage as a candidate failure. Audit remains
repeatable and read-only. A stopped batch lists every unattempted candidate ID.

## Ledger proof

Every attempted stage records:

- candidate and stage;
- UTC start/end and elapsed seconds;
- completed, skipped, or failed result and typed error category;
- manifest revision before/after;
- artifact-count and artifact-byte deltas;
- manifest-derived operator next actions;
- per-image alpha foreground coverage for newly generated multi-angle views.

Multi-angle entries report both nonzero-alpha pixel fraction and foreground
bounding-box fraction. Bounding-box coverage below 0.25 is flagged as
`excessive_empty_canvas`; the orchestrator does not crop, overwrite, or claim
authority over the renderer's output.

Ledger creation uses exclusive new-file semantics and refuses overwrite.

## Isolation evidence

The temporary-workspace integration uses three sequential candidates:

1. valid local GLB;
2. invalid local GLB;
3. a later valid local GLB.

Both good candidates complete create, intake, pass-through processing,
inspection, and integrity audit. The invalid input fails during intake,
retains a revision-1 draft with zero artifact delta, and does not prevent the
later candidate from completing. Assertions verify exact revision and artifact
deltas and that neither configured Asset Library nor Vandrel paths are created.
All inputs are local fixtures; no provider transport exists in the allowed
stage vocabulary.

Focused tests also cover resume, fail-on-complete, CLI ledger output, and
foreground coverage debt flags.

## Boundary and ergonomics assessment

This reduces repeated operator invocations to one plan plus one ledger path
while retaining per-candidate state authority. It deliberately remains
sequential. A malformed candidate produces a nonzero CLI outcome after the
ledger is safely written, so automation can inspect evidence without mistaking
a partially successful batch for complete success.

No second large real batch was generated. DM-006 candidates and immutable
previews were not mutated.
