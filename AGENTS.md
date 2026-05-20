# Video Director Agent Rules

This repository is a standalone Agent Skill for turning local media, narration,
and editing intent into a directly playable short mp4. Editable draft export,
cloud-assisted generation, TTS, avatar generation, and other providers are
optional paths selected only when the user asks for them.

## Read Order

When working in this repository, read:

1. `AGENTS.md`
2. `SKILL.md`
3. The source files directly related to the task

## Naming

- Use `Video Director` in user-facing docs, command output, and install text.
- Keep `runtime/` as the internal runtime directory.
- Do not reintroduce nested runtime package names or old compatibility scripts.

## Boundaries

- The default output target is `final_render`, a directly playable mp4.
- `draft` must mean a real editable draft, never a bundle/debug substitute.
- The current draft exporter is one adapter, not the product's primary path.
- `scripts/video_director.py` is the command router. Shell and cmd wrappers only
  select Python and delegate to it.
- Root `pyproject.toml` is the dependency source. Do not add a second dependency
  manifest under `runtime/`.
- Config templates under `runtime/templates/` are internal scaffolding. The
  Agent generates local configs from user intent and runtime context.

## Generated State

- Generated smoke assets, manifests, local configs, run outputs, and adapter
  draft outputs are local artifacts.
- Do not commit `*.local.json`, `output/`, generated media, or runtime caches.

## Verification

For entrypoint, config, dependency, or render-path changes, verify through the
public launcher for the current platform.

Unix/macOS:

```bash
bash scripts/video-director.sh --help
bash scripts/video-director.sh config local --output-mode video --output video-director-smoke.local.json --job-id smoke --narration-text smoke
```

Windows:

```bat
scripts\video-director.cmd --help
scripts\video-director.cmd config local --output-mode video --output video-director-smoke.local.json --job-id smoke --narration-text smoke
```

For render-path changes, also run the public smoke flow from `SKILL.md` and
confirm the final target reports `status=rendered`.
