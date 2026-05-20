# Architecture

## Purpose

Video Director is a self-contained Agent Skill for local-first short-video generation. The user-facing workflow is:

```text
local media -> assets manifest -> narration-first timeline -> final mp4
```

The default path does not require cloud generation, TTS, avatar services, or Jianying.

## Boundaries

| Layer | Responsibility | Must not own |
| --- | --- | --- |
| `SKILL.md` | Agent-facing workflow contract | Runtime implementation details |
| `scripts/video_director.py` | Cross-platform command routing and public command surface | Media editing algorithms |
| shell/cmd wrappers | Python interpreter selection and delegation | Mode/output business rules |
| `runtime/config_prepare.py` | Local config materialization | Public command routing |
| `runtime/templates/` | Internal config templates used by the Agent/router | User-facing setup instructions or live credentials |
| `runtime/` | Bundled runtime implementation | Public install flow |
| `runtime/adapters/` | Output adapters such as mp4 render and Jianying draft | Agent install/register flow |
| `references/*.md` | Stable operator contracts | Run-specific generated state |

## Runtime

The runtime package lives directly under `runtime/`. Public docs and command
output should use `Video Director`; command examples should prefer
`scripts/video-director.sh` or `scripts\video-director.cmd`.

Config templates live under `runtime/templates/` and are internal scaffolding.
Agents generate `.local.json` configs from user intent and runtime context; users
should not be asked to copy or edit template JSON.

## Dependency Source

The root `pyproject.toml` is the dependency source for this skill. The launcher
loads the runtime by adding the repository root to `PYTHONPATH`; the runtime is
not installed as a separate package by default.

## Generated State

Generated demo media, local configs, render outputs, draft outputs, and run manifests are local artifacts. They should be recreated by commands instead of committed as source, unless a future decision explicitly promotes a fixture into versioned test data.
