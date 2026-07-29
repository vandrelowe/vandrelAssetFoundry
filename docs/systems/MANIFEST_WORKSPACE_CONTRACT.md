# Manifest and Workspace Contract

**Status:** Active — Phase 1 authority

## Scope

This contract governs configuration, asset identity, workspace layout,
manifests, event logs, discovery, and local inspection commands.

## Invariants

- One permanent directory exists per asset ID.
- Asset IDs are immutable and match `^[a-z0-9][a-z0-9_]{2,63}$`.
- The manifest is the authoritative active-candidate record.
- Stored portable paths are relative, use `/`, and cannot traverse.
- Prompts are copied into the asset workspace and never referenced only by an
  external absolute path.
- Failed validation creates no partial asset directory.
- Existing asset directories are never deleted or overwritten.
- State-changing writes use the repository's lock/validate/temp/flush/backup/
  replace/event sequence.
- `manifest.previous.json` is recovery history, not a second authority.
- `events.jsonl` is an audit trail, not a replay database.
- Each asset may contain one `manifest.pending-save.json` operational recovery
  journal. It records only source/target manifest hashes and revisions, the
  exact pre-event length/hash, and the already-intended canonical event. It is
  never manifest authority and cannot reconstruct or replace candidate state.

## Workspace layout

The workspace root contains `assets`, `temp`, `cache`, `locks`, and `backups`.
Each asset contains the layout defined by the current creation service. New
directories may be added compatibly; existing portable paths may not be
repurposed without a schema/contract change.

## Phase 1 commands

`init`, `doctor`, `lanes`, `create`, `list`, `show`, `status`, `scan-sources`,
and `audit` are local-only. The audit command is read-only: it rehashes every
recorded artifact and verifies unique IDs/paths, derivation references, and
approval bindings. It also checks that the bounded JSONL event history has one
well-formed, asset-matching event for every manifest revision in order.
Reporting `submit` as a next action does not authorize or implement submission.

`review-gallery` creates a new numbered, offline HTML snapshot under the
configured workspace `review_reports` directory. It embeds the latest recorded
local preview and presents manifest-owned technical facts. It never mutates a
candidate, grants approval, or loads network content.

## Failure policy

Corrupt manifests, unknown lanes, missing prompts, unsafe paths, duplicate IDs,
and unsafe configuration fail explicitly.

A manifest save durably creates or replaces its pending-save journal under the
asset lock before preserving/replacing the manifest or appending the event.
The canonical event bytes are fixed before that first mutation. Journal writes
flush the file and make the atomic directory-entry replacement durable using a
parent-directory sync on POSIX and write-through replacement on Windows. A
completed save durably marks the same journal complete.

Read-only load, audit, and pending-save diagnosis never mutate recovery state.
Only an explicit repository reconciliation or the locked preamble of another
state-changing save may reconcile a pending journal. Reconciliation permits
exactly these states:

- exact source manifest plus the exact journaled pre-event log marks the
  uncommitted attempt complete without changing manifest or events;
- exact target manifest plus the exact pre-event log appends the exact event;
- exact target manifest plus an exact proper prefix of that event truncates
  only the proven partial tail, flushes it, then appends the exact event;
- exact target manifest plus the exact complete event performs only idempotent
  journal completion.

Every other manifest, event-prefix, tail, identity, revision, type, or hash
combination fails closed for manual inspection. Reconciliation always uses the
same asset lock as save; there is no unlocked or load-time repair.
