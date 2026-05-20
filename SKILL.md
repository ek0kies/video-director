---
name: video-director
description: Use this skill when an Agent needs to turn local media into a directly playable short mp4, or an optional editable draft through an explicit adapter.
---

# Video Director

This is a standalone Agent skill. It turns local media into a short vertical
video through this default flow:

```text
local media -> assets manifest -> narration-first timeline -> final mp4
```

The default path is local-first and does not require cloud services, TTS,
avatar generation, or editable-draft adapters.

## User Contract

- Do not ask users to open, copy, or hand-edit JSON templates.
- Ask users for intent, source media location, output preference, narration or
  style requirements, and only the missing credentials/paths required by the
  selected optional path.
- Generate local `*.local.json` configs yourself from `runtime/templates/`.
- Treat `runtime/templates/` as internal scaffolding.
- Use `video` as the default output. It must mean a directly playable mp4.
- Use `draft` only when the user explicitly wants an editable handoff.
- If a `draft` currently targets Jianying, treat Jianying as one adapter, not
  the product's primary workflow.
- On macOS, route users to `video` unless they explicitly accept the current
  editable-draft adapter as experimental or run it in a supported environment.

## Entrypoints

Unix/macOS:

```bash
bash scripts/video-director.sh --help
```

Windows:

```bat
scripts\video-director.cmd --help
```

Both launchers auto-detect Python 3.11+. If auto-detection fails, ask the user
to set `VIDEO_DIRECTOR_PYTHON` to a compatible interpreter.

## Workflow

### 1. Inspect Materials

Prefer Agent visual understanding when available. Write or update a structured
manifest with paths, tags, descriptions, scene types, mood, and best-use hints.

Offline filename-based fallback:

```bash
bash scripts/video-director.sh analyze \
  --materials-dir /path/to/source-media \
  --output /path/to/workspace/assets_manifest.json
```

### 2. Generate Config

Direct mp4 path:

```bash
bash scripts/video-director.sh config local \
  --output-mode video \
  --output /path/to/workspace/video-director.video.local.json \
  --job-id demo-video \
  --narration-text "Viewer-facing narration and subtitles go here." \
  --director-brief "Private editing guidance goes here." \
  --set production.assets_manifest_path='"/path/to/workspace/assets_manifest.json"' \
  --set production.full_tts_duration_ms=30000 \
  --set outputs.final_render.output_name='"demo-video.mp4"'
```

Editable draft path, only when explicitly requested:

```bash
bash scripts/video-director.sh config local \
  --output-mode draft \
  --output /path/to/workspace/video-director.draft.local.json \
  --job-id demo-draft \
  --narration-text "Viewer-facing narration and subtitles go here." \
  --set production.assets_manifest_path='"/path/to/workspace/assets_manifest.json"'
```

If the current environment is unsupported for the selected draft adapter, stop
and explain the limitation instead of silently producing a bundle/debug file.

Use repeated `--set key=value` for lower-frequency fields. `value` is parsed as
JSON when possible, otherwise stored as a string.

Important config semantics:

- `inputs.narration_text` is viewer-facing narration/subtitle text.
- `inputs.director_brief` is planning guidance and must not appear as subtitles.
- `--output-mode video` maps to `outputs.targets=["final_render"]`.
- `--output-mode draft` maps to the current editable-draft adapter target.
- Internal bundles or debug artifacts are not valid substitutes for `video`.
- Real secrets must go only into temporary or local-only config files, never into
  templates.

### 3. Doctor

```bash
bash scripts/video-director.sh doctor /path/to/workspace/video-director.video.local.json
```

Stop on required errors. `ffmpeg` is required for real mp4 rendering.

### 4. Dry Run And Render

```bash
bash scripts/video-director.sh run /path/to/workspace/video-director.video.local.json --dry-run
bash scripts/video-director.sh run /path/to/workspace/video-director.video.local.json
```

Relative media and output paths resolve against the caller's working directory.
Set `VIDEO_DIRECTOR_WORKSPACE_ROOT=/path/to/workspace` when running from another
directory.

### 5. Summarize

```bash
bash scripts/video-director.sh summarize output/video_director/<job_id>/latest_run.json
```

Report the mp4 path, render status, beat count, and generated target files.

## Smoke Test

Use the built-in generated smoke assets when installing or validating the skill:

```bash
bash scripts/video-director.sh demo
bash scripts/video-director.sh doctor demo/contest/video-director.contest-demo.local.json
bash scripts/video-director.sh run demo/contest/video-director.contest-demo.local.json --dry-run
bash scripts/video-director.sh run demo/contest/video-director.contest-demo.local.json
bash scripts/video-director.sh summarize demo/contest/output/contest-demo/latest_run.json
```

The `demo/` directory is generated local state and should not be committed.

## Failure Handling

- If `doctor` fails on Python, ffmpeg, or Pillow, fix the local runtime first.
- If rendering fails, inspect `final_render.render_plan.json` and the ffmpeg
  error.
- If a sidecar `.srt` appears unexpectedly, check
  `outputs.final_render.emit_sidecar_srt`.
- If subtitles show planning text, move viewer-facing copy to
  `inputs.narration_text` and private guidance to `inputs.director_brief`.
- If material matching is weak, improve the manifest instead of asking the user
  to configure a separate visual model.
- If an editable-draft adapter dependency is missing, do not downgrade to a
  bundle/debug file. Install the optional dependency or explain that draft export
  is unavailable in the current environment.
