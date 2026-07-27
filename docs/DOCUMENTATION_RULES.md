# Documentation Authority Rules

**Status:** Authoritative

## Authority order

When documents overlap, obey:

1. `GOVERNANCE.md`
2. `AI_RULES.md`
3. `docs/DOCUMENTATION_RULES.md`
4. `docs/ARCHITECTURE_AUTHORITY.md`
5. Relevant `docs/systems/*_CONTRACT.md`
6. Schemas and pattern/example files
7. Active task or sprint documents
8. Guides and references
9. Archived documents

Sibling-repository documents are external references below local contracts.
They may constrain an interface but cannot assign ownership inside Foundry.

The supplied `Vandrel_Asset_Foundry_Design_v1.*` files are original design
baselines, and `Vandrel_Asset_Foundry_Codex_Start_Prompt.md` is the completed
Phase 1 implementation brief. Preserve them as project history and intent, but
resolve current implementation decisions through the authority order above.

## Document roles

- Root governance documents define process, safety, and project-wide rules.
- `docs/ARCHITECTURE_AUTHORITY.md` maps current owners and boundaries.
- Each subsystem corridor has exactly one contract under `docs/systems/`.
- Schemas and examples define data shapes but do not override behavior.
- Task documents are plans and completion records, not permanent authority.
- Guides explain workflows.
- Archive material is historical only.

## Rules for changes

- Do not create competing authority documents.
- Put ownership changes in the architecture authority map.
- Put subsystem invariants and data flow in the corridor contract.
- Put reusable public data shapes in schemas.
- Migrate durable decisions out of completed task notes.
- Version externally consumed schemas instead of silently redefining them.
- Record the external contract revision or fixture used when changing a
  Vandrel-facing handshake.

## Reference-only banner

Any guide or planning document that overlaps a contract should begin with:

> Reference only. If this document conflicts with Foundry governance,
> architecture authority, or the relevant corridor contract, the higher
> authority wins.
