# Animation-Only Library Contract

Status: production contract 1.0, 2026-08-21

## Authority and boundary

This contract owns selective local-FBX intake, Godot-native normalization,
technical track evidence, Foundry three-body visual review, approval, and
immutable publication of an animation-only `AnimationLibrary`. It does not own
character bodies, body-bound motion assemblies, provider generation, Vandrel
consumer import, gameplay registration, or runtime acceptance.

The route is deliberately separate from the historical one-FBX canary carrier,
the complete ten-motion B2 reaction candidate, and the 29/61-motion character
assemblies. It never reads an old wrapper or completed candidate library as an
authoritative source. Only exact local provider FBX bytes named by the current
intake request are source authority.

## Intake and membership

`foundry intake-animation-library <asset-id> --request <json>` accepts schema
`vandrel_foundry_animation_library_intake/1.0`. A request binds:

- the candidate asset ID;
- two or more unique semantic names;
- one absolute or request-relative local FBX path per semantic;
- exact source size and SHA-256;
- `none` or `linear` loop intent;
- exact excluded semantic/hash pairs;
- a typed, canonical-SHA-256-bound package policy containing the exact ordered
  selected and excluded hashes, forbidden aggregate payload hashes, and
  superseded route identities; and
- import policy
  `godot_skeleton_profile_humanoid_meshy_bone_map_rest_fixer_v1`.

The command performs no provider call. It rejects missing or non-FBX inputs,
non-exact bytes, duplicate semantics, duplicate source bytes, selected/excluded
overlap, any selection that differs from its exact package policy, and any
forbidden selected-set or output aggregate hash. Generic service code contains
no content-specific B2 hashes: the hash-bound B2 request is the authority for
its exact eight selected motions and exact two exclusions. Intake copies only
selected source FBXs and records a manifest-resident source-to-semantic
membership ledger.

## Godot normalization and technical probe

`foundry normalize-animation-library <asset-id>` creates a new isolated Godot
project and runs exactly five named phases under one bounded monitored Windows
process job:

1. initial FBX import;
2. import configuration with `SkeletonProfileHumanoid`, the accepted 22-bone
   Meshy `BoneMap`, bone renaming, and Rest Fixer settings;
3. retargeted animation-library import; Godot 4.7.2 may retain one non-bone
   rotation carrier at the exact path `Armature`, so the finalizer removes
   that exact known carrier only when it occurs once and records the recognized
   and removed track in technical evidence; and
4. finalization plus technical probe; and
5. isolated validation after removing source FBXs and the prior import cache.

The supervisor requires process-zero, the console executable, child-only
`DOTNET_ROLL_FORWARD=LatestMajor`, finite per-phase timeouts, output limits,
application-error polling throughout and for five seconds after exit,
Application/.NET/WER inspection, run-owned process-tree cleanup, and a final
Godot inventory. A zero process exit does not override crash evidence.

Finalization deep-duplicates each imported animation before mutation and creates
one `.res` `AnimationLibrary` containing exactly the selected semantics. The
finished-library phase must load without source FBXs, prior import cache, or
external dependencies. Every semantic must have exactly one Hips position
track, exactly 22 unique mapped rotation tracks, no scale tracks, no non-Hips
position tracks, no other tracks after the one exact known-carrier operation,
and finite key values. Any different path, type, or duplicate carrier remains
in the animation and fails the unchanged strict track-shape probe. The technical report
binds each semantic and exact source SHA-256 to the exact complete
output-library SHA-256. Technical PASS does not constitute visual acceptance.

## Three-body fixed-phase visual evidence

`foundry import-animation-visual-matrix <asset-id> --request <json>` accepts
schema `vandrel_foundry_animation_visual_matrix/1.0`. It requires exactly three
distinct body identities and the complete Cartesian product of current selected
semantics and those bodies. The request binds the exact payload SHA-256 of all
three bodies and the exact fixed-camera policy/configuration SHA-256. Every cell
retains its literal `PASS` or `FAIL`, review notes, exact evidence file
hashes/sizes, and observations at phases
`0, 0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875` from a fixed camera.

Evidence must bind the current animation-library and technical-report hashes.
Missing, duplicate, extra, or stale cells are rejected. A technical PASS never
fills in a visual cell, and any visual `FAIL` makes the matrix fail.

## Approval and immutable release

`domain/workflow_policy.py` is the sole approval-requirement and binding
authority. `foundry approve-animation-library` delegates to the normal approval
service, which rehashes the current library, technical, isolation, monitor, and
visual reports plus every visual cell artifact. It requires current
monitored-Godot PASS, current technical and isolation PASS, every exact
three-body visual cell PASS, no failed cells, explicit reviewer confirmation,
and fresh documented custody. Scale calibration and a model are inapplicable
only for this lane, as ratified by `RELEASE_CONTRACT.md`.

The normal `foundry release` command then emits descriptor v2 with
`primary_payload: animation_library`, exactly one library payload, no model,
the technical, isolated-validation, complete monitored-Godot, and visual-matrix
reports, every referenced visual image at a portable release path, custody
evidence, exact selected source membership, exclusions, and output SHA-256.
Publication remains an explicit `--apply` action and does not imply Vandrel
import or registration.

## B2 selective canary CLI

After creating an `animation_library` candidate and binding custody, the exact
production sequence is:

```powershell
foundry intake-animation-library meshy_shared_reactions_b2_selective_001 `
  --request <absolute-path-to-foundry-selective-intake-request.json>
foundry normalize-animation-library meshy_shared_reactions_b2_selective_001
foundry import-animation-visual-matrix meshy_shared_reactions_b2_selective_001 `
  --request <absolute-path-to-three-body-fixed-phase-review.json>
foundry approve-animation-library meshy_shared_reactions_b2_selective_001 `
  --reviewer "Independent reviewer" --all-required-checks `
  --notes "Eight selected reactions; FallAbdominal and StrangledFall excluded."
foundry release meshy_shared_reactions_b2_selective_001
foundry release meshy_shared_reactions_b2_selective_001 --apply
```

The B2 request and its canonical hash-bound package policy must list only
AngryStomp, CrouchBackstep, DyingBackward, FallingDown, HeadPain, KnockDown,
KnockDownAlt, and StandDodge with their exact ordered source hashes.
FallAbdominal and StrangledFall must remain the exact ordered explicit
exclusions. The policy must also name the historical one-FBX carrier, complete
reaction bundle, and body-bound motion routes as superseded and bind their
known forbidden aggregate hashes.
