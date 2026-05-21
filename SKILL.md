---
name: video-director
description: Use this skill when an Agent needs to turn local media into a directly playable short mp4, or an optional editable draft through an explicit adapter.
---

# Video Director

This is a standalone Agent skill. It turns local media into a short vertical
video through this default flow:

```text
local media -> assets manifest -> material-aware copy plan -> reviewed narration -> timeline -> final mp4
```

The default path uses the bundled runtime and does not require cloud services, TTS,
avatar generation, or editable-draft adapters.

## Agent-native Package Contract

This repository root is the Skill payload. When installed into an Agent, register
the whole directory as `skills/video-director/`; do not copy only `SKILL.md`.

Required Skill files:

```text
SKILL.md
requirements.txt
scripts/install.sh
scripts/doctor.sh
scripts/run.sh
scripts/update.sh
scripts/install.ps1
scripts/doctor.ps1
scripts/run.ps1
scripts/update.ps1
tests/smoke.sh
tests/smoke.ps1
runtime/
```

Use the standard entrypoints first:

```bash
bash scripts/install.sh
bash scripts/doctor.sh
bash scripts/run.sh --help
bash scripts/run.sh update --help
```

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
powershell -ExecutionPolicy Bypass -File scripts\doctor.ps1
powershell -ExecutionPolicy Bypass -File scripts\run.ps1 --help
powershell -ExecutionPolicy Bypass -File scripts\run.ps1 update -Help
```

- `scripts/install.sh` detects Python 3.10+, creates or reuses `.venv`, installs
  `requirements.txt`, checks local permissions, and checks or attempts to
  install `ffmpeg`/`ffprobe` when the current environment allows it.
- `scripts/install.ps1` provides the same install contract for Windows Agents,
  including `py -3`, `winget`, Chocolatey, and Scoop checks.
- `scripts/doctor.sh` and `scripts/doctor.ps1` print clear `PASS`/`FAIL` lines
  and AI-executable `FIX` commands. Run those fixes yourself when they do not
  require new human permission.
- `scripts/run.sh` and `scripts/run.ps1` are the stable invocation entrypoints.
  They prefer the managed `.venv` and delegate to the existing command router.
- `scripts/update.sh` and `scripts/update.ps1` refresh an installed Git checkout
  and then run install, doctor, and smoke verification. They refuse to overwrite
  dirty local changes.
- Do not ask the human to manually install packages, hand-edit JSON, or run
  step-by-step setup commands unless the printed fix requires admin/system
  permission or no compatible Python can be found.
- This is a general-purpose Skill. Do not special-case one operating system,
  one Agent product, or one model provider in the workflow. Use the platform
  launcher only as an execution detail.

## Artifact Hygiene

- Treat the Skill root as read-only product source during normal use. Do not
  create user job scripts, one-off config JSON, generated media, SRT files,
  manifests, or scratch reports next to `SKILL.md`.
- Put generated working files under the user's workspace, preferably
  `.video-director/` or `output/video_director/`. Use
  `VIDEO_DIRECTOR_WORKSPACE_ROOT` when invoking the Skill from another current
  directory.
- User-facing output is the final mp4 or the requested editable draft. Internal
  artifacts such as manifests, material-aware copy plans, config snapshots, beat
  sheets, EDL, timeline models, render plans, staging media, and review JSON are
  for Agent/debug use.
- Report the final deliverable path first. Mention internal files only when the
  user asks for debugging details or a command fails.
- `summarize` is concise by default. Use `summarize --verbose` only when you
  need internal debug artifact paths.
- Do not emit external `.srt` files in normal mp4 delivery. Subtitles are burned
  into the mp4 by default, and sidecar SRT requires an explicit advanced config
  opt-in with both `emit_sidecar_srt=true` and `allow_sidecar_srt=true`.
- A final mp4 must contain at least one real visual asset. Subtitle-only,
  text-only, or black-screen outputs are failures, not acceptable deliverables.

## User Contract

- Do not ask users to open, copy, or hand-edit JSON templates.
- Ask users for intent, source media location, output preference, narration or
  style requirements, and only the missing credentials/paths required by the
  selected optional path.
- For simple requests such as "cut a 30 second video from this folder", present
  a natural default path before rendering: a clean edit as a direct mp4 with
  source audio retained and no extra voiceover, subtitles, or BGM.
- In the same short confirmation, mention the optional narration path in plain
  language: if the user wants a narrated version, the Agent can draft narration
  copy and subtitles for review before rendering.
- Do not turn the default assumptions into a long form. Ask only for the choices
  that materially change the output: TTS or voiceover, burned subtitles, source
  audio retention, external music, and editable draft export.
- If the user asks for voiceover, dubbing, or TTS, do not stop at checking local
  speech capabilities. Present the available paths: use a user-provided audio
  file, generate and review narration text for manual recording, or use the
  optional cloud TTS path. The bundled cloud template includes Doubao TTS
  (`doubao_tts2_v3_http_chunked`), which requires explicit user selection and
  credentials.
- Do not frame missing narration or copy as the user's fault; describe the
  default as a "clean edit" instead.
- If the user asks to proceed quickly or accepts the assumptions, continue with
  those defaults without asking again.
- Generate local `*.local.json` configs yourself from `runtime/templates/`.
- Treat `runtime/templates/` as internal scaffolding.
- Use `video` as the default output. It must mean a directly playable mp4.
- Use `draft` only when the user explicitly wants an editable handoff.
- If a `draft` currently targets Jianying, treat Jianying as one adapter, not
  the product's primary workflow.
- On macOS, route users to `video` unless they explicitly accept the current
  editable-draft adapter as experimental or run it in a supported environment.

## Entrypoints

Install or refresh the local Skill environment:

```bash
bash scripts/install.sh
```

Check whether the environment is usable:

```bash
bash scripts/doctor.sh
```

Run commands:

```bash
bash scripts/run.sh --help
```

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
powershell -ExecutionPolicy Bypass -File scripts\doctor.ps1
powershell -ExecutionPolicy Bypass -File scripts\run.ps1 --help
```

Windows also has a low-level cmd launcher:

```bat
scripts\video-director.cmd --help
```

## Update Workflow

When the user asks to update Video Director, do not send them back to the
repository to copy a prompt. Treat it as an Agent-native Skill maintenance task.

User request examples:

```text
Update Video Director.
更新 Video Director。
```

Agent steps:

1. Locate the registered `video-director` Skill directory for the current Agent.
2. Resolve whether that path is a symlink, a Git checkout, or a copied folder.
3. If it is a Git checkout or a symlink into one, run the platform update
   entrypoint:

   ```bash
   bash scripts/run.sh update
   ```

   Windows PowerShell:

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\run.ps1 update
   ```

4. If it is a copied non-Git folder, back it up, clone the latest repository to
   a stable local path, and repoint the Agent skill registration to the whole
   repository. Do not register only `SKILL.md`.
5. If local user changes are present, do not overwrite them. Report the dirty
   files and ask whether to back them up, commit them, or stop.
6. After updating, run install, doctor, and the built-in smoke flow. The update
   entrypoint does this automatically for Git checkouts unless `--skip-verify`
   is explicitly passed.
7. Report only whether the update succeeded, the install path, the registered
   Skill path, and the verification result.

The shell entrypoints detect Python 3.10+ and check `python3`, `python`, `py -3`,
then versioned commands. If auto-detection fails, test both `python3` and
`python` explicitly before proposing an installation. When either is compatible,
set `VIDEO_DIRECTOR_PYTHON` to that command and continue.

Do not install Miniforge, Conda, Anaconda, pyenv, or any other Python
distribution automatically. If no compatible Python exists, stop and ask the
user to choose a lightweight installation method.

## Workflow

### 1. Inspect Materials

Prefer Agent visual understanding when available. Write or update a structured
manifest with paths, tags, descriptions, scene types, mood, best-use hints, and
known media durations.

Offline filename-based fallback:

```bash
bash scripts/run.sh analyze \
  --materials-dir /path/to/source-media \
  --output /path/to/workspace/assets_manifest.json
```

If the Agent will generate or rewrite narration, create a material-aware copy
plan before writing viewer-facing copy. Use that report to constrain duration,
sentence count, and claims to the available material:

```bash
bash scripts/run.sh plan-copy \
  /path/to/workspace/.video-director/configs/video-director.video.local.json \
  --output /path/to/workspace/.video-director/reviews/material_copy_plan.json
```

The user should not have to run `plan-copy` manually. It is an Agent-internal
planning artifact, and `run` also writes `Material_Copy_Plan.json` into each run
directory for traceability.

Before generating config, apply this clarification gate:

- If the request already specifies narration, subtitles, source audio, BGM, TTS,
  output mode, and duration, use those choices directly.
- If the request only specifies source media and duration, present one concise
  assumption line and wait for confirmation before rendering:
  "I will start with a clean edit: a direct mp4 with the original audio, without
  extra voiceover, subtitles, or BGM. If you want a narrated version, I can
  draft narration copy and subtitles for your review first."
- If the user requested generated copy, create the material-aware copy plan,
  draft copy within that plan's duration and material constraints, then create
  the review report before rendering. Do not treat generated subtitles as
  approved copy.
- If the user requested TTS, avatar, cloud delivery, or editable draft export,
  ask only for the credentials, paths, or adapter constraints required by that
  selected path.
- If the user requested voiceover but did not choose a path, ask one concise
  question that names the meaningful choices: provided audio, generated copy for
  review, or optional Doubao TTS.

### 2. Generate Config

Direct mp4 path:

```bash
bash scripts/run.sh config local \
  --output-mode video \
  --output /path/to/workspace/.video-director/configs/video-director.video.local.json \
  --job-id demo-video \
  --narration-text "Viewer-facing narration and subtitles go here." \
  --director-brief "Private editing guidance goes here." \
  --set production.assets_manifest_path=/path/to/workspace/.video-director/assets_manifest.json \
  --set production.full_tts_duration_ms=30000 \
  --set outputs.final_render.output_name='"demo-video.mp4"'
```

When the user explicitly provides final viewer-facing narration, use
`--narration-text`. When the Agent generates viewer-facing narration, do not use
`--narration-text`; first use `plan-copy` to constrain the generated text, then
use `--generated-narration-text`, build a review report, and only add
`--copy-reviewed` after approval:

```bash
bash scripts/run.sh config local \
  --output-mode video \
  --output /path/to/workspace/.video-director/configs/video-director.generated.local.json \
  --job-id generated-video \
  --set production.assets_manifest_path=/path/to/workspace/.video-director/assets_manifest.json
bash scripts/run.sh plan-copy \
  /path/to/workspace/.video-director/configs/video-director.generated.local.json \
  --output /path/to/workspace/.video-director/reviews/material_copy_plan.json
bash scripts/run.sh config local \
  --output-mode video \
  --output /path/to/workspace/.video-director/configs/video-director.generated.local.json \
  --job-id generated-video \
  --generated-narration-text "Generated subtitles for human review." \
  --set production.assets_manifest_path=/path/to/workspace/.video-director/assets_manifest.json \
  --set production.full_tts_duration_ms=30000
bash scripts/run.sh review-copy \
  /path/to/workspace/.video-director/configs/video-director.generated.local.json \
  --output /path/to/workspace/.video-director/reviews/copy_review.pending.json
```

Editable draft path, only when explicitly requested:

```bash
bash scripts/run.sh config local \
  --output-mode draft \
  --output /path/to/workspace/.video-director/configs/video-director.draft.local.json \
  --job-id demo-draft \
  --narration-text "Viewer-facing narration and subtitles go here." \
  --set production.assets_manifest_path=/path/to/workspace/.video-director/assets_manifest.json
```

If the current environment is unsupported for the selected draft adapter, stop
and explain the limitation instead of silently producing a bundle/debug file.

Use repeated `--set key=value` for lower-frequency fields. `value` is parsed as
JSON when possible, otherwise stored as a string.

Important config semantics:

- `inputs.narration_text` is viewer-facing narration/subtitle text.
- `inputs.director_brief` is planning guidance and must not appear as subtitles.
- User-provided `inputs.narration_text` can render directly.
- Generated viewer-facing copy must set `inputs.narration_source="generated"` and
  must be reviewed before rendering. Use `--generated-narration-text` for
  generated copy and add `--copy-reviewed` only after review approval.
- `plan-copy` creates a material-aware copy plan and does not render media.
- `review-copy` creates a local review report and does not render media.
- `editing.material_duration_policy="cap"` lets the runtime fit planned
  narration to known material capacity before real audio exists. If real audio
  already exists and visuals cannot support it, the run fails with a planning
  error instead of padding with black frames or silently stretching clips.
- `--output-mode video` maps to `outputs.targets=["final_render"]`.
- `--output-mode draft` maps to the current editable-draft adapter target.
- Internal bundles or debug artifacts are not valid substitutes for `video`.
- Real secrets must go only into temporary or local-only config files, never into
  templates.

### 3. Doctor

```bash
bash scripts/doctor.sh /path/to/workspace/.video-director/configs/video-director.video.local.json
```

Stop on required errors. `ffmpeg` is required for real mp4 rendering.

### 4. Dry Run And Render

```bash
bash scripts/run.sh run /path/to/workspace/.video-director/configs/video-director.video.local.json --dry-run
bash scripts/run.sh run /path/to/workspace/.video-director/configs/video-director.video.local.json
```

Relative media and output paths resolve against the caller's working directory.
Set `VIDEO_DIRECTOR_WORKSPACE_ROOT=/path/to/workspace` when running from another
directory.

### 5. Summarize

```bash
bash scripts/run.sh summarize output/video_director/<job_id>/latest_run.json
```

Report the mp4 path, render status, and beat count. Do not list internal target
files unless the user asks for debug details.

## Smoke Test

Use the built-in generated smoke assets when installing or validating the skill:

```bash
bash tests/smoke.sh
```

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File tests\smoke.ps1
```

The smoke script writes generated local state to a temporary directory by
default. Set `VIDEO_DIRECTOR_KEEP_SMOKE=1` only when you need to inspect output.

## Failure Handling

- If `scripts/doctor.sh` or `scripts/doctor.ps1` fails on Python, ffmpeg,
  ffprobe, or Pillow, run the printed `FIX` command yourself when it does not
  require new human permission.
- If rendering fails, inspect `final_render.render_plan.json` and the ffmpeg
  error.
- If a sidecar `.srt` appears unexpectedly, treat it as a bug unless both
  `outputs.final_render.emit_sidecar_srt` and
  `outputs.final_render.allow_sidecar_srt` were explicitly enabled.
- If Chinese subtitles render as blocks, set
  `outputs.final_render.subtitle_font_path` or `VIDEO_DIRECTOR_SUBTITLE_FONT`
  to a CJK-capable font and rerender. Do not ship the blocked subtitle output.
- If subtitles show planning text, move viewer-facing copy to
  `inputs.narration_text` and private guidance to `inputs.director_brief`.
- If a render has subtitles but no real picture, inspect source materials and
  rerun through the public launcher. Do not report subtitle-only output as
  success.
- If material matching is weak, improve the manifest instead of asking the user
  to configure a separate visual model.
- If an editable-draft adapter dependency is missing, do not downgrade to a
  bundle/debug file. Install the optional dependency or explain that draft export
  is unavailable in the current environment.
