# Provider Pipeline Contract

**Status:** Stub — implementation blocked

This corridor will govern authentication, paid submission, idempotency,
ambiguous outcomes, polling, retries, raw redacted evidence, downloads, hashes,
and provider-independent task records.

No provider integration may be implemented until this contract defines:

- explicit user authorization for paid/network actions;
- pre-request durable attempt recording;
- ambiguous submission and reconciliation behavior;
- retry/idempotency policy;
- secret and payload redaction;
- bounded timeouts and polling;
- `.part` download verification and immutable promotion;
- mocked, opt-in live, and failure-path test requirements.
