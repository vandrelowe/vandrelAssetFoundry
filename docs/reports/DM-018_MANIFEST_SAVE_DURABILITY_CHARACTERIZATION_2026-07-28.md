> Reference only. If this document conflicts with Foundry governance,
> architecture authority, or the manifest/workspace contract, the higher
> authority wins.

# DM-018 Manifest Save Durability Characterization — 2026-07-28

status: characterization complete; durability contract decision proposed, not implemented

## Scope and boundary

This bounded unit characterizes injected production-path failures in
`ManifestRepository.save`. It changes tests and this report only. It does not
change manifest persistence, event behavior, workflow policy, publication,
custody, providers, CLI behavior, schemas, or any real candidate.

The tested baseline is commit `18b604e1bb608bf14a21dd510e12a1cdc8e13c0f`.

## Exact observed failure states

Each case begins with:

- authoritative `manifest.json` at revision 2;
- `manifest.previous.json` containing revision 1;
- two exact event records, for revisions 1 and 2;
- a requested revision-3 save using `expected_revision=2`.

### Previous-copy failure

Injected `shutil.copy2` failure occurs before manifest replacement.

- `manifest.json` remains byte-identical revision 2;
- `manifest.previous.json` remains byte-identical revision 1;
- `events.jsonl` remains byte-identical with revisions 1 and 2;
- the revision-3 temporary manifest is removed;
- `save` raises `FoundryError` with the injected `OSError` as its cause.

This is a clean pre-commit failure.

### Atomic manifest-replace failure

Injected `os.replace` failure occurs after the recovery copy.

- `manifest.json` remains byte-identical revision 2;
- `manifest.previous.json` advances to a byte-identical copy of revision 2;
- `events.jsonl` remains byte-identical with revisions 1 and 2;
- the revision-3 temporary manifest is removed;
- `save` raises `FoundryError` with the injected `OSError` as its cause.

The authoritative manifest and event history remain consistent. The historical
recovery copy changes, but it truthfully holds the current pre-attempt
manifest. A normal retry with `expected_revision=2` remains possible.

### Event append: pre-write failure

Injected failure occurs when production `append_event` opens the event log,
before event bytes are written.

- `manifest.json` is byte-identical to the canonical requested revision 3;
- `manifest.previous.json` advances to a byte-identical copy of revision 2;
- `events.jsonl` remains byte-identical with only revisions 1 and 2;
- the temporary manifest is removed;
- `save` raises `FoundryError` with the injected `OSError` as its cause;
- a repository reload observes revision 3;
- the read-only asset audit reports observed revisions `[1, 2]` and expected
  revisions `[1, 2, 3]`.

This is a committed-authority/failed-audit split. A caller that interprets the
exception as “nothing committed” is wrong. A blind retry with the original
`expected_revision=2` conflicts because revision 3 is already authoritative.

### Event append: partial-write failure

The production event writer is allowed to write a prefix before raising.
With a fixed canonical event payload, the injected stream writes exactly half
the event record, flushes it, and then raises.

- `manifest.json` is byte-identical to canonical revision 3;
- `manifest.previous.json` is byte-identical revision 2;
- `events.jsonl` is byte-identical to the original two events plus the exact
  first half of the revision-3 event;
- repository reload observes revision 3;
- asset audit reports the event log as unreadable or invalid;
- `save` raises with the exact injected `OSError` as its cause.

This is a more severe version of the split: ordinary append cannot safely add
another event because the invalid tail must first be identified and repaired.

### Event append: complete-write/reported-fsync failure

The injected production stream accepts the complete event write and flush,
then raises when `append_event` requests the descriptor for `fsync`. This
models a complete-write fsync failure whose durability result is uncertain.

- `manifest.json` is byte-identical to canonical revision 3;
- `manifest.previous.json` is byte-identical revision 2;
- `events.jsonl` is byte-identical to the original two events plus the exact
  complete canonical revision-3 event;
- asset audit passes and observes revisions `[1, 2, 3]`;
- `save` still raises with the injected `OSError` as its cause.

The caller cannot infer commit state from the raised result. A blind
`expected_revision=2` retry still conflicts even though both durable
authorities appear complete.

## Decision

The current post-replace event failure should not be ratified as an accepted
recoverable split in its present form.

The manifest contract correctly says the event log is an audit trail rather
than replay authority, so revision 3 remains the candidate authority. However,
there is no bounded, deterministic reconciliation operation that can restore
the missing exact event type. The ordinary audit blocks, the original caller
received failure, and a normal expected-revision retry cannot complete the
operation. Calling this “recoverable” without an executable recovery corridor
would hide an operational dead end.

## Proposed contract: per-asset save transaction journal

Before implementation, the director should ratify a narrow persistence
contract with these properties:

1. Under the existing asset lock, validate the current manifest and expected
   revision.
2. Construct the canonical event record before mutation, including its
   timestamp, and durably create a bounded per-asset pending-save journal
   containing: asset ID, expected revision, target revision, canonical event
   bytes (or their lossless encoded form), pre-append event-log length and
   SHA-256, current manifest SHA-256, and canonical target manifest SHA-256.
   The journal contains no candidate payload beyond hashes and the same event
   record already intended for the audit log.
3. Preserve the previous manifest and atomically replace the current manifest
   exactly as today.
4. Append the exact journaled event idempotently.
5. Durably remove or mark the journal complete only after both manifest and
   event are reconciled.
6. A read-only diagnosis may classify a pending journal but never writes,
   truncates, appends, or clears it.
7. A separately explicit state-changing reconciliation operation, or the
   locked preamble of the next state-changing save, handles a pending journal
   under the same asset lock:
   - old manifest plus an event log exactly matching the journaled pre-append
     length/hash means replacement did not commit and the journal may be
     cleared before a normal retry;
   - exact target manifest plus the exact pre-append event log means append
     the exact journaled event;
   - exact target manifest plus a tail that is an exact proper prefix of the
     journaled event, with the preceding bytes matching the journaled
     length/hash, means truncate only that proven partial tail, flush/fsync,
     and append the exact event;
   - exact target manifest plus the exact complete journaled event means
     finish journal cleanup without appending again;
   - every other manifest/event/hash combination fails closed for manual
     inspection.

The journal is operational recovery state, not a second manifest authority and
not an event replay database. Its target-manifest hash only identifies the
already validated replacement.

## Rejected shortcuts

- Appending the event before manifest replacement merely reverses the split
  and can produce an event for a revision that never became authoritative.
- Treating event failure as success conceals an audit defect and gives the
  caller no recovery evidence.
- Rolling the manifest back after event failure adds another fallible write,
  risks destroying the only durable committed candidate state, and conflicts
  with optimistic-revision semantics.
- Reconstructing an arbitrary event from `manifest.json` alone cannot recover
  the original exact event type.
- Silently weakening the audit to allow missing revisions contradicts the
  manifest/workspace contract.

## Required implementation evidence if approved

- Seeded failures at journal creation, previous copy, manifest replacement,
  event pre-write, partial write, flush/fsync after complete write, partial-tail
  truncation, reconciled append, and journal completion.
- Retry/reconciliation at each interruption point with exact byte and revision
  assertions.
- Idempotent event verification and rejection of wrong event type, asset ID,
  revision, or manifest hash.
- No unlocked reconciliation and no second manifest authority.
- Existing optimistic revision, previous-copy, atomic replacement, and event
  ordering behavior preserved.
- Focused storage tests, full suite, Ruff, and `git diff --check`.

No durability behavior is changed by this characterization unit.
