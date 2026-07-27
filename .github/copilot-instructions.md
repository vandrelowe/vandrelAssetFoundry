# Vandrel Asset Foundry Copilot Instructions

Treat this file as a router.

Before editing, read:

1. `GOVERNANCE.md`
2. `AI_RULES.md`
3. `docs/DOCUMENTATION_RULES.md`
4. `docs/ARCHITECTURE_AUTHORITY.md`
5. The relevant `docs/systems/*_CONTRACT.md`

Inspect `git status`, preserve unrelated changes, identify the owning layer,
state a bounded plan, and validate with `ruff check .` plus `pytest`.

Hard rules:

- Vandrel and the asset library are read-only unless a future explicit
  contract and user request authorize a scoped write.
- Tests use temporary workspaces only.
- No secrets, implicit provider calls, paid retries, silent overwrite, path
  traversal, or absolute paths in portable data.
- The manifest repository is the only manifest write path.
- Foundry owns provenance and technical releases; Vandrel owns runtime and
  gameplay meaning; the future mod manager owns mod resolution.
- A stub corridor contract blocks implementation in that corridor.
- Do not revive archived documents or create parallel authority.
- Keep the CLI thin, use typed models and services, and avoid speculative
  abstractions.
