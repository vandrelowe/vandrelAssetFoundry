# Architecture

Vandrel Asset Foundry separates active asset production from game development
and release distribution.

```text
VandrelAssetFoundry (Python source)
          |
          v
VandrelFoundryWorkspace (active local candidates)
          |
          v  future explicit approval and publication
VandrelAssetLibrary (immutable, Git LFS releases)
          |
          v  explicit game-side import
Vandrel (read-only to Foundry)
```

The Foundry repository contains code and contracts but no generated models. The
workspace is local operational state: one permanent directory per asset, one
authoritative manifest, prior-manifest backup, and an append-only event log.
Workflow state lives in the manifest rather than directory names.

The asset library is a future release channel containing only reviewed immutable
revisions. Vandrel consumes selected releases explicitly; Foundry never mutates
the game checkout. A future mod manager remains separate and owns gameplay
metadata, dependency resolution, load order, and overrides.

Phase 1 uses a thin Typer CLI over application services, Pydantic domain models,
and a filesystem repository. Manifest changes use an asset-specific exclusive
lock, validation, a flushed same-directory temporary file, prior-manifest copy,
atomic replacement, and event append. Locking is isolated so its implementation
can be replaced later. No database, external subprocess, web server, or network
adapter exists in this phase.
