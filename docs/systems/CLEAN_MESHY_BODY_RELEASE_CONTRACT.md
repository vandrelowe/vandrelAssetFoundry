# Clean Meshy Body Shared-Animation Release Contract

Status: candidate-only production contract. This route creates immutable Asset
Library candidates; it does not declare Vandrel runtime acceptance and never
edits consumer files.

## Authority and custody

An intake request binds one local provider ZIP by path, size, and SHA-256 and
binds a canonical package policy by SHA-256. The policy contains the complete,
ordered ZIP member inventory. Intake rejects missing, extra, reordered,
encrypted, linked, unsafe, oversized, over-compressed, or non-exact members.
The ZIP is the sole custody root. Body FBX and albedo extraction are derived
artifacts. Companion Running and Walking FBXs are archive evidence only and
are forbidden processing and release outputs.

The request also binds the accepted portable BoneMap and the accepted import
sidecar by exact path, size, and hash. The BoneMap is processing policy input.
The sidecar is policy evidence only: it is verified before use but is never
copied, staged, or released. Historical aggregate output hashes and route IDs
are a typed request-bound anti-laundering policy. Generic code contains no
canary identity or content hashes.

## Body-only processing

`blender_clean_meshy_body` imports the selected FBX with animation import
disabled, clears object animation data, actions, and NLA tracks, requires one
armature plus mesh geometry, and constructs a lit Principled material using an
external albedo. It exports deterministic separate glTF, buffer, and albedo
payloads. The report must prove zero animations/actions/NLA and the exact
material policy. Outputs matching forbidden historical hashes fail closed.
Every mutation uses an operation-owned directory and atomic promotion.

## Godot technical and visual evidence

The shared-motion input is never a caller-selected local resource. The request binds
an Asset Library asset ID, immutable revision, and payload SHA-256. Foundry resolves
the canonical catalog entry and descriptor, validates its v2 `animation_library`
primary payload and semantic order, rehashes every declared file through the library
audit, and only then stages the exact payload.

Schema-v2 animation-library descriptors published before the additive
`processor_version` field remain valid dependencies. Its absence means only
"not recorded by that immutable descriptor"; Foundry does not infer a version.
Identity, catalog/descriptor hashes, every packaged file, import policy,
technical-policy agreement, selected semantics, and payload bytes remain mandatory.

Processing acceptance is derived from exported glTF and dependency bytes. The
service parses accessors and proves that animations are absent; the sole external
buffer and albedo dependencies are exact; every primitive has a lit material and skin
attributes; every vertex has finite, normalized, nonzero influences; and geometry
has finite positive dimensions and is grounded. A Blender diagnostic cannot assert
these release facts, and action/NLA claims are not used.

The dedicated Godot wrapper imports the canonical Vandrel RuntimeGuard and crash
evidence authorities from the configured reference repository. It uses their
version-tolerant matchers, child-only environment, finite bounds, run-owned cleanup,
and at least five seconds of post-exit crash observation. Exit zero is rejected when
Application, .NET, WER, dump, dialog, output, cleanup, or final-inventory evidence
fails.

Validation stages only the exact processed glTF dependencies, exact BoneMap,
and one immutable shared AnimationLibrary. It generates a sandbox-local
`.import` policy with `animation/import=false`; no accepted source sidecar is
copied. The dedicated PowerShell corridor requires process-zero before every
phase, a console executable, child-only environment changes, finite internal
and outer bounds, output limits, owned-tree cleanup, application-error window
polling, Application/.NET/WER evidence, five-second post-exit observation, and
a final process inventory. Exit zero never overrides crash evidence.

The technical report binds the body, BoneMap, sidecar-policy source, and shared
library hashes. It requires exactly one `GeneralSkeleton`, all 22 humanoid map
bones in finite rests with reset import poses, skin, per-vertex finite normalized
weights, lit external albedo on every material surface with emission disabled,
shadow casting,
finite positive scale, grounding, no embedded animation surfaces, exact shared
semantic membership, and no horizontal Hips drift in the shared library.
It also rereads the generated Godot sidecar after reimport and requires the
accepted BoneMap, bone renamer, unique `GeneralSkeleton`, complete Rest Fixer
settings, and `animation/import=false`; matching output bone names alone cannot
substitute for this policy proof.

Capture uses the canonical fixed camera. It produces unique rest views
(front, side, back) and one contact sheet per exact shared semantic containing
all phases `0, .125, .25, .375, .5, .625, .75, .875`. Imported cameras,
environments, lights, AnimationTrees, and AnimationPlayers are removed before
the body enters the fixed world. Capture output is
`manual_review_required` with null results; technical success cannot approve
anatomy. A manual import must rehash every unique cell, cover the exact rest
and motion memberships, and retain explicit PASS/FAIL. Any failed cell blocks
approval. Unchanged-input attempts use stable owned attempt identities and do
not overwrite retained evidence. A process-zero rejection before any Godot
phase launches is environment evidence, not a product-validation attempt. The
first exact preflight-only block is retained separately and permits one retry;
a repeated preflight block consumes the attempt and stops unchanged retries.
If every product phase and exact report passes but post-process scratch deletion
fails, a later invocation may promote the already copied durable evidence after
rehashing and revalidating it; it must not relaunch Godot or relabel failed
product evidence.

## Approval and immutable release

Approval is governed only by workflow policy. It binds the current processed
model, buffer, albedo, processing report, technical report, monitored report,
manual visual report, and every referenced visual artifact. The required
checks are `clean_body_technical_probe`, `clean_body_monitored_godot`, and
`clean_body_visual_review`, with exact current hashes and no failed cells.

The release descriptor uses `primary_payload: clean_body` and route
`clean_body_shared_animation`. It contains exactly one model plus its buffer
and albedo, all processor-specific reports and manual evidence, custody files,
and an immutable shared-animation-library asset/revision/hash reference. It
states `candidate_only=true`, `vandrel_runtime_accepted=false`,
`shared_animation_pool_compatible=true`, and
`embedded_animations_disabled=true`. `.import` files, wrappers, embedded
clips, provider companion motions, historical aggregates, and Meshy-native
routes are forbidden. Audit reconciles the same exact packaged bindings;
model and animation-library release behavior remains unchanged.
