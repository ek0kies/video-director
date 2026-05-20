# Troubleshooting

Read this only after a run fails. Keep the normal path in `SKILL.md`.

## Video render fails

- Inspect `targets/final_render/final_render.render_plan.json`.
- Check the ffmpeg error, source media paths, output permissions, and whether at
  least one material or avatar clip exists.

## Doctor reports Python or Pillow errors

- Use `scripts/video-director.sh` on Unix/macOS and `scripts\video-director.cmd`
  on Windows; do not run the internal runtime module directly.
- Install dependencies from the repo root with `uv sync` or `pip install -e .`.
- If the wrong interpreter is selected, set `VIDEO_DIRECTOR_PYTHON` to a Python
  3.11+ executable.

## Draft export reports missing `pyJianYingDraft`

- If the user requested `draft`, do not silently downgrade to a bundle file.
- Install the optional dependency or stop and explain that real draft generation
  is unavailable in the current environment.

## TOS config errors

- Cloud mode currently expects `production.audio_delivery.provider=tos`.
- Required fields are `endpoint`, `region`, `access_key`, `secret_key`, and `bucket`.

## Partial cloud success

- Reuse the same `job_id`.
- Check `output/video_director/<job_id>/Remote_Run_Manifest.json`.
- Re-run after fixing the blocking config issue instead of changing the job id.

## Summarizer cannot find the run

- Point it to `output/video_director/<job_id>/latest_run.json`.
- If run management was disabled, pass the concrete run directory that contains `Timeline_Model.json`.
