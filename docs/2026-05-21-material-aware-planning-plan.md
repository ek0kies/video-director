# Material-Aware Planning Plan

## Context

The current runtime is narration-first: it accepts `inputs.narration_text`,
derives beat durations from TTS duration or text length, and then maps materials
onto those beats. This can create timelines where narration is longer than the
available visual material.

## Decision

Add a minimal material-aware planning pass before timeline construction:

| Phase | Files | Expected result | Verification |
| --- | --- | --- | --- |
| Analyze | `runtime/assets_manifest.py` | Local video manifest entries include `duration_ms` when `ffprobe` is available. | Run `analyze` or `demo` and inspect `assets_manifest.json`. |
| Plan | `runtime/kernel.py` | Beat durations are fitted to known selected material durations before clips are emitted. | Unit smoke with short materials and long narration duration. |
| Copy report | `runtime/material_planning.py`, `scripts/video_director.py` | `plan-copy` reports material capacity and copy constraints before narration rewrite. | Run `plan-copy <config>` and inspect `max_narration_duration_ms`. |
| Policy | `runtime/templates/*.json` | Default `material_duration_policy=cap`; users can opt into `error` or `ignore`. | Generate config and inspect `editing.material_duration_policy`. |
| Export | `runtime/adapters/jianying.py` | Exporter does not silently stretch ordinary beats. | Existing stretch-gate smoke. |

## Scope

This is not automatic copywriting. If real audio already exists and exceeds
material capacity, the run should fail with a clear planning error so the Agent
can regenerate or shorten copy. If audio has not been generated yet, the runtime
may cap the planned duration to the known material capacity.

## Verification Checklist

- `python -m py_compile` for changed runtime files
- Launcher config generation
- Demo smoke render
- Manifest duration inspection
- Material copy planning report via `plan-copy`
- Material-cap smoke: long planned narration over short videos is capped before
  rendering
- Fixed-audio smoke: real TTS clips longer than material capacity fail clearly
