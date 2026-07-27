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

## Workspace layout

The workspace root contains `assets`, `temp`, `cache`, `locks`, and `backups`.
Each asset contains the layout defined by the current creation service. New
directories may be added compatibly; existing portable paths may not be
repurposed without a schema/contract change.

## Phase 1 commands

`init`, `doctor`, `lanes`, `create`, `list`, `show`, and `status` are local-only.
Reporting `submit` as a next action does not authorize or implement submission.

## Failure policy

Corrupt manifests, unknown lanes, missing prompts, unsafe paths, duplicate IDs,
and unsafe configuration fail explicitly. Automatic repair is out of scope.
