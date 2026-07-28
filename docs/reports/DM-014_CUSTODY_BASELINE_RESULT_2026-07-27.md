---
directive: DM-014
status: accepted
date: 2026-07-27
scope: read-only Outside Assets and Foundry Workspace custody baseline
---

# DM-014 Custody Baseline

## Result

Foundry now provides strict versioned custody-policy, canonical-register, and
operational-report schemas plus:

- `foundry custody-inventory`, which scans without mutating protected roots and
  creates exclusive new evidence files only after two complete root views
  agree; and
- `foundry validate-custody-register`, which rejects noncanonical or internally
  inconsistent content and then rebuilds the current physical-root authority
  for exact byte comparison.

Library/Intake owns custody-required fields and acceptance. Foundry owns the
backward-compatible implementation. Custody eligibility is only a prerequisite;
it is not approval, publication, legal interpretation, Vandrel acceptance,
gameplay registration, or deletion authority.

## Accepted-candidate evidence

- Canonical register:
  `docs/reports/evidence/dm014/custody-register-accepted.json`
- Operational report:
  `docs/reports/evidence/dm014/custody-run-report-accepted.json`
- Register SHA-256:
  `9a5e006eda1dc80b45f6c4b5b99ed68989192fb3007bd702f7d2323011e99e60`
- Report SHA-256:
  `10245ed7877dea4b074c94ef168dfde049d33b6d8fea3e38e209bd9ee8512eee`

The scan reached stability on its first bounded attempt. Before and after
fingerprints are identical:

| Protected root | Fingerprint |
|---|---|
| Outside Assets | `88113abffcbbf864840c04111953cbd03ae954506b671c17db5a622a3e3192d6` |
| Foundry Workspace | `195b8118be0bb11947435d14d18b7ab12b6bb580329d79d788851de1074e0098` |
| Asset Library | `7e8aa63c89023f0cfabd3e37494fa0f8b79b60b2aa31820b3efa338562ac2483` |

The report records `zero_source_mutation_observed: true`. No network, provider,
approval, publication, movement, deletion, deduplication, immutable-release
rewrite, remote configuration, or Vandrel change occurred.

## Inventory findings

| Measure | Result |
|---|---:|
| Outside Assets files represented | 1,648 |
| Explicit exclusions | 0 |
| Deterministic packages | 146 |
| Documented-rights packages | 2 |
| Missing-rights packages | 144 |
| Custody-eligible files | 582 |
| Missing-rights/ineligible files | 1,066 |
| Duplicate SHA-256 groups | 178 |
| Files in duplicate groups | 490 |
| Potential duplicate bytes | 352,792,545 |
| Foundry Workspace files represented | 1,070 |
| Candidate manifests | 17 |
| Managed manifest artifacts | 614 |
| Explicit generated cache/temp | 32 |
| Unregistered workspace files | 407 |

Duplicate observations are non-destructive. They do not authorize file removal
or movement. Rights inference comes only from policy-authoritative evidence.
Names such as Meshy, Mixamo, or Quaternius are merely hints unless policy binds
source identity and license evidence.

Only the Quaternius Fantasy Props and Medieval Village packages currently bind
valid license evidence. Meshy and Mixamo file-bearing packages are inventoried
but promotion-ineligible until authoritative provenance and rights evidence is
added. Six additional named Quaternius directories are empty; they are outside
the file/package register until content exists and have not been assigned a
custody status.

All 17 workspace candidates have unregistered content and therefore carry the
`unregistered_content` retention hold. Active workflow, approval/release
history, rejected evidence, and integrity-failure holds remain separate. No
storage record claims that content is deletable.

## Fail-closed and adversarial proof

The implementation rejects:

- traversal, malformed or ambiguous policy paths, and overlapping exclusions;
- static or encountered symlinks/reparse points;
- final-component and lexical-ancestor reparse redirection;
- file or ancestor identity drift during hashing;
- missing or hash-mismatched license evidence;
- conflicting applicable license scopes;
- forged package/source/rights/eligibility, duplicate, coverage, count, defect,
  workspace-classification, candidate, audit, release, and retention facts;
- noncanonical serialized registers; and
- output paths inside Outside Assets, Foundry Workspace, or Asset Library.

Windows final-component hashing uses `CreateFileW` with
`FILE_FLAG_OPEN_REPARSE_POINT`; POSIX uses `O_NOFOLLOW`. Lexical directory
ancestors are checked before and after hashing and publication. A privileged
hostile process able to swap and perfectly restore an ancestor entirely between
checks is explicitly outside the local tool's threat model and requires an OS
sandbox or handle-relative traversal.

Independent review initially broke the validator with a fabricated candidate,
forged cache class, orphan package, and incomplete retention facts. The final
validator rebuilds current root authority and compares canonical bytes, and all
exact mutations are now rejected. Independent post-hardening focused acceptance
passed 13 tests; the only skip was creating a real Windows symlink without the
required OS privilege. Non-skipped simulated reparse, output-parent reparse,
and concurrent-ancestor-change tests passed.

## Verification

- canonical physical-root validation: passed, Outside 1,648 / Workspace 1,070;
- `foundry audit-all`: passed all 17 candidates;
- full pytest suite: passed with expected environment skips;
- Ruff format/check and `git diff --check`: passed before the final evidence
  run and rerun at handoff;
- accepted-candidate canonical register is byte-identical to the earlier stable
  scans, while the accepted operational report additionally names all three
  physical roots.

Earlier preliminary scan outputs were excluded from the accepted commit and
removed from the local evidence directory after the accepted pair reproduced
the same canonical register. Only the `-accepted` register/report pair is
handoff authority.
