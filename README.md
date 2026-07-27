# Vandrel Asset Foundry

Vandrel Asset Foundry is a standalone, manifest-first Python companion tool for
turning candidate 3D assets into traceable, reviewable releases for Vandrel.
Phase 1 implements local configuration, workspace creation, draft asset manifests,
atomic storage, event history, and inspection commands only.

It is not the Vandrel game, a mod manager, an asset database, or a provider client.
This phase makes no network calls and does not invoke Meshy, Blender, or Godot.

## Windows setup

Requires Python 3.11 or newer.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item foundry.example.toml foundry.toml
```

Edit `foundry.toml` for the machine. Keep `vandrel.write_enabled = false`. The
real file is ignored because machine-specific paths do not belong in source
control. The CLI also accepts `--config <path>` on every Phase 1 command; this is
especially useful for isolated tests.

## Commands

```powershell
foundry init
foundry doctor
foundry lanes
foundry create --id stone_knife_001 --lane static_prop `
  --display-name "Stone Knife" --prompt-file .\prompts\stone_knife.txt
foundry list
foundry show stone_knife_001
foundry status stone_knife_001
```

`init` is safe to repeat and never creates asset records. `create` validates all
inputs before creating an asset workspace, copies the prompt to
`input/prompt.txt`, and creates a draft manifest plus an event log. `status`
reports `submit` as the next draft action, but submission is intentionally absent
in Phase 1.

## Repository and workspace boundaries

- This repository contains Python source, schemas, tests, and documentation.
- The configured Foundry workspace contains active candidate assets and stays
  outside Git.
- `C:\dev\VandrelAssetLibrary` will eventually contain approved immutable
  releases and use Git LFS; Phase 1 does not write there.
- `C:\dev\Vandrel` is reference-only. `doctor` may check for `project.godot`;
  Foundry refuses configurations that enable writes.
- A future mod manager owns gameplay metadata, dependencies, overrides, and load
  order.

Never commit active candidate assets, downloaded models, `.env`, API keys, or a
real `foundry.toml`. This source repository does not initialize Git LFS.

## Development

```powershell
ruff format --check .
ruff check .
pytest
```

The checked-in JSON Schema is generated from the Pydantic manifest model and is
verified by tests.

AI assistants and contributors must begin with [GOVERNANCE.md](GOVERNANCE.md)
and [AI_RULES.md](AI_RULES.md). The governing read order, current ownership map,
and subsystem contracts live under `docs/`. These rules preserve compatibility
with Vandrel while keeping sibling repositories read-only and preventing
Foundry from taking ownership of runtime or gameplay decisions.

## Phase 2 roadmap

After Phase 1 review, the next phase may add Meshy authentication, explicit
submission, polling, raw redacted request/response records, recovery semantics,
and checksummed downloads. Blender processing, Godot staging, approval, release,
and humanoid pipeline work remain later phases.
