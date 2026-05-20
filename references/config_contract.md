# Config Contract

`prepare_config.py` is intentionally thin. It only covers the high-frequency
fields that an Agent should fill from user intent and runtime context.

Committed templates live under `runtime/templates/` and are internal
scaffolding. Do not ask users to open, copy, or hand-edit them.

## Output semantics

- `--output-mode draft` means a real Jianying draft.
- `--output-mode video` means a directly playable result video.
- `video` maps to `outputs.targets=["final_render"]`.
- Internal bundle/debug artifacts are not a valid substitute for `video`.
- On macOS, `--output-mode draft` with `pyJianYingDraft` enabled is blocked by default. Use `--output-mode video`, run draft export on Windows, or pass `--allow-mac-jianying-draft` only for unsupported local debugging.

## Direct flags

- `--output-mode` -> user-facing output type
- `--job-id` -> `job_id`
- `--narration-text` / `--narration-file` -> `inputs.narration_text`
- `--script-text` / `--script-file` -> backward-compatible input that is normalized into `inputs.narration_text`
- `--director-brief` -> `inputs.director_brief`
- `inputs.narration_text` -> preferred viewer-facing narration and subtitles
- `inputs.director_brief` -> planning guidance that must not be shown as subtitles
- `--topic-hint` -> `inputs.topic_hint`
- `--materials-dir` -> `inputs.materials_dir`
- `--avatar-path` -> `inputs.avatar_path`
- `--avatar-image-path` -> `inputs.avatar_image_path`
- `--full-tts-audio-path` -> `production.full_tts_audio_path`
- `--full-tts-duration-ms` -> `production.full_tts_duration_ms`
- `--drafts-root` -> `outputs.jianying.drafts_root`
- `--output-root` -> `outputs.output_root`
- `--use-pyjianyingdraft` -> `outputs.jianying.use_pyjianyingdraft`
- `--allow-mac-jianying-draft` -> bypass the macOS draft-export guard for local experiments
- repeated `--target` -> `outputs.targets`

In `--output-mode video`, template-provided avatar inputs and avatar clips are
removed by default. Re-enable them only with explicit `--set` overrides and
matching avatar assets.

The direct-video path also clears template `production.full_tts_audio_path` by
default, so a missing sample audio file will not break mp4 rendering. Re-enable
voice audio with `--full-tts-audio-path` or a cloud/TTS configuration.

## Assets manifest

`production.assets_manifest_path` points to a structured material understanding file:

```json
{
  "version": "1.0",
  "assets": [
    {
      "asset_id": "mat-001",
      "path": "input/materials/opening.mp4",
      "media_type": "video",
      "tags": ["开场", "城市", "人群"],
      "description": "城市人群的开场素材",
      "scene_type": "city_broll",
      "mood": "active",
      "best_for": ["opening", "transition"]
    }
  ]
}
```

The runtime consumes the manifest as normalized `MaterialAsset` records. In
Agent usage, the Agent may inspect media and write this manifest directly; the
skill does not require separate visual-model configuration.

## Escalation path

If the required field is not covered by a direct flag, use repeated `--set key=value`.

Examples:

```bash
--set production.retry_policy.max_attempts=5
--set outputs.jianying.subtitles.enabled=true
--set production.api.auth.token='\"replace-with-real-token\"'
```

`VALUE` is parsed as JSON when possible, otherwise it is written as a string.

## Secret handling

- Keep real secrets in a local-only config path such as `/tmp/*.json` or `video-director.*.local.json`.
- Do not overwrite committed templates with live credentials.
