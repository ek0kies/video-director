# Decisions

## 2026-05-20: Flatten Runtime Directory

Decision: keep the bundled runtime directly under `runtime/`.

Reason: adding a second package-name directory under `runtime/` made the public
tree look heavier than necessary for a standalone skill.

Consequence: `scripts/video_director.py` imports modules from `runtime/`
directly after adding the repository root to `sys.path`. New code and docs must
not reintroduce a nested runtime package directory or a separate runtime CLI
entrypoint.

## 2026-05-20: One Command Router

Decision: `scripts/video_director.py` owns command routing and mode/output defaults.

Reason: duplicating config default logic between Python and shell wrappers makes behavior drift likely.

Consequence: shell and cmd wrappers stay thin. Compatibility helper scripts and
the old runtime CLI layer were removed from the public surface; normal usage
goes through the router.

## 2026-05-20: Root `pyproject.toml` Is the Dependency Source

Decision: keep dependencies in the repository root and avoid maintaining a second runtime-level dependency manifest.

Reason: users install from the skill root, and the runtime is bundled under the same tree.

Consequence: dependency changes must update the root `pyproject.toml` and related install docs.

## 2026-05-20: Config Templates Are Internal

Decision: store committed templates under `runtime/templates/` with
`*.template.json` names.

Reason: users should not have to open, copy, or hand-edit JSON configs. In
Agent-first usage, the user provides intent, media paths, and only the optional
secrets/paths needed by the selected mode; the Agent generates the local config.

Consequence: generated `*.local.json` files remain local artifacts. Docs should
describe templates as internal scaffolding, not as user-facing setup steps.
