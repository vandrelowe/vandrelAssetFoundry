# Processing and Validation Contract

**Status:** Active — local processing and sandbox staging permitted

## Scope and authority

This corridor governs processors, technical inspection, generated Godot
validation sandboxes, tool execution, reports, and artifact derivation.
Processed and staged outputs remain Foundry candidates. They do not become
Vandrel runtime wrappers, catalog entries, or approved releases.

The real Vandrel checkout is always read-only and must never be used as a
processing directory, import target, cache, or validation sandbox.

## Immutable artifact protocol

Every processor must:

1. Load an existing manifest through `ManifestRepository`.
2. Require an artifact with a recorded SHA-256 and size.
3. Recalculate both before processing.
4. Write to a new asset-relative path without overwrite.
5. Flush the completed output and recalculate its hash and size.
6. Record a distinct artifact ID, role, stage, derivation, processor name, and
   processor version.
7. Persist the manifest with an expected-revision check.

A pass-through processor still creates a physically distinct output. It may
preserve bytes and hashes, but it must not alias the source file through a hard
link.

External model import is a local source-intake operation, not a provider task.
GLB intake validates the container before copying. FBX and glTF package intake
first copies the original model and required sidecars into an immutable package
directory, then converts the copy through bounded Blender. glTF URI resolution
allows only declared, same-directory local buffers/images and rejects traversal
and network references. Intake records raw and converted hashes, tool version,
structured warnings, and bounded logs; it retains no machine-absolute source
path and enters the same downloaded-state corridor as provider output.

## Technical reports

- Reports are JSON objects with an explicit schema version, asset ID, artifact
  ID and hash, measured facts, and named checks.
- Reports use new numbered paths and never overwrite prior evidence.
- A report records observations; it does not silently repair an artifact.
- Lane validation compares measured facts with the checked-in lane policy.
- Unknown or unsupported structures fail closed with a readable error.
- Approval is not implied by a passing technical report.

## Godot sandbox staging

- Staging occurs only below the asset's `godot_staging/` directory.
- A staging directory is deterministic from the selected artifact identity and
  hash and is immutable once complete.
- The sandbox contains its own `project.godot`, copied candidate model, and
  validation-only wrapper scene.
- Generated scenes may use sandbox-local `res://` paths only. They must not
  emit or claim Vandrel runtime destinations.
- Wrapper scenes instance the GLB; the imported GLB scene is not itself treated
  as a final game wrapper.
- Lane collision policy is recorded as a recommendation. Version 1 creates no
  collision or navigation nodes automatically.

## Bounded subprocess execution

A future Godot or Blender subprocess adapter is permitted only when it:

- executes an explicitly configured absolute executable path;
- uses an argument vector without shell evaluation;
- uses the generated workspace sandbox as its working directory;
- has a configured finite timeout and terminates the child on expiry;
- captures bounded standard output and error into a numbered report;
- records executable version, arguments with secrets removed, exit status,
  start/end times, and timeout state;
- never passes provider credentials or inherits them when they are unnecessary;
- treats nonzero exit, timeout, missing reports, or mutated inputs as failure;
- never writes into the real Vandrel checkout or asset library.

Normal tests use fake process runners. Live tool tests are opt-in and may not be
required by CI.

Godot command-line behavior follows the stable engine documentation:
<https://docs.godotengine.org/en/stable/tutorials/editor/command_line_tutorial.html>.
The validator uses `--headless`, `--path`, `--import`, and a sandbox-local log.

Blender command-line behavior follows the official manual:
<https://docs.blender.org/manual/en/latest/advanced/command_line/arguments.html>.
The adapter uses background mode, factory startup, disabled automatic embedded
scripts, an explicit checked-in Python script, and a nonzero Python exception
exit code. A Blender result is accepted only when the subprocess succeeds, the
new GLB parses, and the versioned report exists.

## Failure recovery

- Remove only incomplete files and directories created by the current
  operation when commit is known not to have occurred.
- If manifest replacement may already have succeeded before a later journal
  error, retain the immutable output for reconciliation.
- Never delete or overwrite an earlier source, processed artifact, staging
  directory, or report during retry.
- A retry receives a new artifact/report identity unless it can prove that an
  existing deterministic output is complete and hash-identical.
