> Reference only. If this document conflicts with Foundry governance,
> architecture authority, or the manifest/workspace contract, the higher
> authority wins.

# DM-018 Pending-Save Journal Implementation — 2026-07-28

status: implemented; independent review accepted

## Decision implemented

The director ratified the bounded per-asset pending-save journal proposed by
the preceding durability characterization. `ManifestRepository.save` now
creates the exact canonical event and a durable operational journal before the
previous-copy/manifest-replace/event sequence. The journal records:

- asset ID;
- source and target revisions;
- exact source and target manifest SHA-256 values;
- exact pre-event byte length and SHA-256;
- event type and losslessly base64-encoded canonical event bytes;
- pending or complete operational state.

It contains no manifest payload and cannot write or reconstruct a manifest.
`manifest.json` remains the sole active-candidate authority.

## Recovery corridor

`ManifestRepository.diagnose_pending_save` is read-only and acquires no lock or
writes. `ManifestRepository.reconcile_pending_save` acquires the existing
asset-specific lock. The same locked reconciliation runs as the first step of
every state-changing save.

Pending recovery recognizes only:

1. exact source manifest plus exact pre-event log;
2. exact target manifest plus exact pre-event log;
3. exact target manifest plus a proper prefix of the exact event after the
   exact pre-event prefix;
4. exact target manifest plus the exact complete event.

Those states respectively complete the uncommitted journal, append the exact
event, truncate only the proven partial tail then append, or complete the
journal without duplicate append. Every other combination fails closed.

Journal writes use a flushed and fsynced temporary file followed by atomic
replacement. POSIX replacement fsyncs the parent directory. Windows uses
`MoveFileExW` with both replace-existing and write-through flags. Completion is
a durable state replacement in the same per-asset journal rather than an
unlink, so a crash cannot ambiguously erase the recovery marker. The next save
atomically replaces that completed record.

## Interruption and negative evidence

The focused matrix injects failures:

- before and after journal replacement;
- during previous-manifest copy;
- before and after manifest replacement;
- before event write, after an exact partial event prefix, and after a complete
  write at the fsync boundary;
- before and after exact partial-tail truncation;
- before and after a reconciled append;
- before and after durable journal completion.

Retries assert exact manifest, previous-manifest, event, revision, journal, and
temporary-file outcomes. Negative cases reject mismatched event type, event
asset ID, journal asset ID, event revision, target manifest hash, pre-event
hash, and non-prefix event tails without mutation. Complete events are proven
idempotent and explicit reconciliation is proven to use the existing lock.

## Modularity report

The change remains inside the local manifest/workspace storage corridor:

- `storage/events.py` owns canonical event construction and exact append;
- `storage/atomic.py` owns canonical manifest bytes and fsynced temporary
  bytes;
- `storage/save_journal.py` owns the private strict journal record, durable
  journal replacement, state classification, exact repair, and diagnosis
  result;
- `storage/manifests.py` remains the only manifest writer and supplies lock and
  sequence orchestration.

There is no dependency from journal code into CLI, services, workflow policy,
publication, custody, providers, candidates, schemas, networking, or runtime
integration. The only domain dependency is read-only validation of manifest
identity and revision; the journal never imports workflow semantics. The
public surface added is two repository methods and the immutable diagnosis
result. No alternate save path or second authority was introduced.

Production module sizes after the change are 324 lines for the cohesive
journal adapter, 127 for the repository, and 28 each for event and atomic
helpers. The journal adapter is intentionally one module because its strict
record validation, state classifier, and permitted mutations form one
fail-closed invariant; splitting classification from mutation would expose
unvalidated recovery state across a module boundary. Its write operations
remain factored into small helpers and its repository caller remains thin.

## Validation

Final validation:

- focused manifest/journal/audit suite: 49 passed;
- full suite: 471 collected, 468 passed, 3 expected skips;
- Ruff: passed;
- `git diff --check`: passed.

The first independent review rejected a publicly named low-level reconciliation
mutator and missing post-mutation interruption cases. The mutator was made a
private lock-owned primitive reachable in production only through repository
methods that hold the asset lock. Post-truncate, reconciled partial/complete
append, reconciliation-completion, and Windows failure/cleanup cases were
added. Independent re-review then accepted the lock boundary, recovery matrix,
idempotency proof, fail-closed behavior, scope, and modularity.
