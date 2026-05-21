# Final Tail Migration Plan

## Context

Video Director previously handled abrupt endings in the AiVideoClip
`skills/video-director` runtime by adding a canonical timeline clip named
`final-tail-buffer` with `source_path="generated://black"`. The standalone
Video Director repository did not carry that timeline-level behavior, so final
mp4 renders could end abruptly when audio and video ended at the same boundary.

## Decision

Migrate the AiVideoClip behavior at the canonical timeline layer instead of
keeping the tail as a render-adapter-only concern.

| Phase | Files | Expected result | Verification |
| --- | --- | --- | --- |
| Kernel | `runtime/kernel.py` | Add optional final black tail clip and mark the last real visual with fade metadata. | Inspect `Timeline_Model.json` for `final-tail-buffer`. |
| Config | `runtime/config_prepare.py`, `runtime/templates/video.template.json` | Enable two-frame final tail by default for `--output-mode video`. | Generate local video config and inspect `editing.final_tail_frames`. |
| Render | `runtime/adapters/rendered_video.py` | Render `generated://black`, honor final `fade_out_ms`, and pad full-track audio to timeline duration. | Run public demo and audio smoke render. |
| Draft | `runtime/adapters/jianying.py` | Materialize `generated://black` and pass `fade_out_ms` into pyJianYingDraft video keyframes. | Run draft bundle smoke with final tail enabled. |

## Scope

This migration enables the final tail by default only for direct mp4 output.
The Jianying draft adapter can now consume the same timeline if a draft config
explicitly enables `final_tail_frames` or receives a timeline containing
`generated://black`.

## Verification Checklist

- `python3 -m py_compile` with `PYTHONPYCACHEPREFIX=/private/tmp/video-director-pycache`
- `bash scripts/video-director.sh --help`
- `bash scripts/video-director.sh config local --output-mode video ...`
- `bash scripts/video-director.sh demo`
- `bash scripts/video-director.sh doctor demo/contest/video-director.contest-demo.local.json`
- `bash scripts/video-director.sh run demo/contest/video-director.contest-demo.local.json --dry-run`
- `bash scripts/video-director.sh run demo/contest/video-director.contest-demo.local.json`
- Audio smoke with a full-track WAV and final mp4 duration check
- Draft bundle smoke with `outputs.jianying.use_pyjianyingdraft=false`
- Tail frame extraction with pixel check for black output
