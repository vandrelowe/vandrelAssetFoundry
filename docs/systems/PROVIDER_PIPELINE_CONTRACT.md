# Provider Pipeline Contract

**Status:** Active — Phase 2 foundation
**Live provider submission:** Guarded command implemented; live paid verification pending

## Scope

This corridor governs provider authentication, paid submission, task identity,
polling, ambiguous outcomes, retries, raw evidence, redaction, downloads, and
provider-independent task records.

The first provider is Meshy. Provider-specific endpoints and payloads remain in
the Meshy adapter; workflow and safety rules remain provider-neutral.

## Current Meshy contract

The current official Text to 3D API uses:

- bearer-token authentication from an API key;
- `POST /openapi/v2/text-to-3d` with `mode: "preview"` for geometry;
- the same endpoint with `mode: "refine"` and a succeeded
  `preview_task_id` for texturing;
- `GET /openapi/v2/text-to-3d/:id` for task retrieval;
- `POST /openapi/v1/image-to-3d` with an HTTPS URL or in-memory image data URI;
- `GET /openapi/v1/image-to-3d/:id` for image task retrieval;
- `POST /openapi/v1/remesh` with a succeeded generation task ID, explicit
  topology, and target polygon count;
- `GET /openapi/v1/remesh/:id` for remesh task retrieval;
- asynchronous task states including `PENDING`, `IN_PROGRESS`, `SUCCEEDED`,
  `FAILED`, and `CANCELED`;
- signed, time-limited model download URLs returned by succeeded tasks.

Provider task IDs are opaque strings. Foundry must not validate or derive
meaning from their current UUID-like format.

Official references:

- <https://docs.meshy.ai/en/api/authentication>
- <https://docs.meshy.ai/en/api/text-to-3d>
- <https://docs.meshy.ai/en/api/image-to-3d>
- <https://docs.meshy.ai/en/api/remesh>
- <https://docs.meshy.ai/en/api/errors>
- <https://docs.meshy.ai/en/api/rate-limits>

## Explicit authorization

Commands are classified as:

- **Local-only:** request construction, validation, redacted snapshot creation,
  listing, and status inspection. These may run without a key.
- **Read-only network:** task retrieval and signed-URL refresh. These require a
  configured key and explicit command invocation, but do not intentionally
  spend generation credits.
- **Paid network:** preview, refine, remesh, retexture, rigging, animation, and
  retry submission. Every paid operation requires an explicit user command.

No background process, startup hook, `doctor`, `list`, `show`, or `status`
operation may submit or retry provider work.

## Durable submission protocol

Immediately before a paid request:

1. Validate the asset, workflow state, operation, provider configuration, and
   required input.
2. Build a canonical request body and SHA-256 request fingerprint.
3. Write a redacted request snapshot under
   `provider/<provider>/requests/<task_key>.json`.
4. Append a task attempt with local state `SUBMITTING`, no provider task ID,
   and the request fingerprint through the manifest repository.
5. Send exactly one bounded request.
6. If a valid provider task ID is returned, store it and map the task to the
   returned provider state.
7. If the server explicitly rejects the request before accepting work, record
   `SUBMISSION_FAILED` with the sanitized error.
8. If the outcome is uncertain—timeout, disconnect, malformed success
   response, or interruption after send—record `AMBIGUOUS` and block automatic
   retry.

`READY` may represent a locally prepared request that has not been sent. It
does not spend credits and is not a provider state.

## Retry and reconciliation

- Never silently resubmit `SUBMITTING` or `AMBIGUOUS` work.
- A retry is a new append-only attempt with a new task key and incremented
  attempt number.
- If the provider exposes no idempotency key or task lookup by client
  fingerprint, Foundry must tell the user that ambiguous reconciliation may
  require checking the provider dashboard.
- `429` handling honors bounded backoff and never turns a rejected submission
  into an unbounded loop.
- Polling is bounded by configured interval, request timeout, and command
  lifetime. It stops at all terminal states.

## Secret and evidence policy

- Read the key only from the configured environment-variable name.
- Build the `Authorization: Bearer ...` header only in memory.
- Never store or print authorization headers, keys, cookies, tokens, or signed
  URL query parameters.
- Redact sensitive mapping keys recursively and strip query strings from URLs
  in stored provider evidence.
- Store request and response evidence as portable relative paths.
- Persist sanitized provider errors; do not persist raw HTTP library objects.

Prompts and reference images are user asset inputs, not authentication
secrets. They may be stored in the private active workspace as provenance.
Image bytes are sent from memory as a data URI and replaced by
`[REDACTED_DATA_URI]` in provider evidence, avoiding public image hosting and
duplicate base64 blobs on disk.

## Download protocol

1. Require a succeeded provider task and an expected artifact role/format.
2. Refresh the task if its signed URL is absent or expired.
3. Download to workspace `temp` with a unique `.part` suffix.
4. Enforce bounded timeouts and reject empty responses.
5. Calculate SHA-256 and size before promotion.
6. Move to a new immutable path; never overwrite an existing artifact.
7. Update the manifest only after the final file exists.
8. Remove only the operation's own incomplete `.part` file on a known failure.

## Error mapping

- `400`: rejected input; no automatic retry.
- `401`/`403`: authentication or authorization failure; never display the key.
- `402`: insufficient credits; no automatic retry.
- `404`: unknown task/resource; preserve local history.
- `429`: bounded backoff for reads; paid resubmission still requires explicit
  intent.
- `5xx`, timeout, or disconnect: safe retry for retrieval; ambiguous for a
  submission that may have reached the provider.

Provider task failures preserve provider error type/code/message after
redaction. They do not erase prior attempts.

## Tests and live-use gate

- Normal tests use fake transports and fixtures only.
- No test may require `MESHY_API_KEY`.
- Assert that redaction catches nested authorization data and signed URLs.
- Assert that ambiguous submission cannot auto-retry.
- Assert request fingerprints are deterministic.
- Assert download failures leave no promoted artifact or manifest reference.
- Live tests are separately marked, opt-in, and never run in CI by default.
- A live paid submission command remains blocked until its transport,
  pre-request durability, ambiguity handling, and explicit confirmation path
  have focused tests.
