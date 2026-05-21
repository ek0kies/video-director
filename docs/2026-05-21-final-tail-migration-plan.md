# Final Visual Tail Plan

## Context

Video Director previously handled abrupt endings by adding a canonical timeline
clip named `final-tail-buffer` with `source_path="generated://black"`. That
prevents hard stops, but it is the wrong default: the better ending keeps the
last valid visual on screen briefly while narration and subtitles finish
naturally.

## Decision

Keep final-tail handling at the canonical timeline layer, but represent it as a
hold on the last real visual clip instead of appending black frames. Generated
black remains an adapter capability for explicit timelines only; it is not the
default ending strategy.

| Phase | Files | Expected result | Verification |
| --- | --- | --- | --- |
| Kernel | `runtime/kernel.py` | Extend the final real visual clip by `final_tail_frames` or `final_tail_buffer_ms`; mark it with `final_tail_strategy=hold_last_visual` and suppress the default final fade-out. | Inspect `Timeline_Model.json`; there should be no generated black tail clip. |
| Config | `runtime/config_prepare.py`, `runtime/templates/video.template.json` | Keep the existing small default tail duration for `--output-mode video`, but its meaning is visual hold, not black tail; default fade-to-black is disabled. | Generate local video config and inspect `editing.final_tail_frames` and `editing.final_fade_out_ms`. |
| Render | `runtime/adapters/rendered_video.py` | Render the extended final visual, let subtitles/audio end before the visual tail, and skip the default fade-to-black on that final hold. | Run public demo and verify the final clip does not contain a black tail. |
| Draft | `runtime/adapters/jianying.py` | Only stretch source media when the timeline explicitly marks `allow_source_stretch`; ordinary beat gaps are not hidden in the exporter. | Run adapter unit smoke for both default truncation and explicit tail hold. |

## Scope

This plan only fixes ending behavior. It does not implement material-first copy
planning, global material sufficiency checks, or automatic narration rewriting.
Those belong in a separate planning pass before timeline generation.

## Verification Checklist

- `python3 -m py_compile` with `PYTHONPYCACHEPREFIX=/private/tmp/video-director-pycache`
- `bash scripts/video-director.sh --help`
- `bash scripts/video-director.sh config local --output-mode video ...`
- `bash scripts/video-director.sh demo`
- `bash scripts/video-director.sh doctor demo/contest/video-director.contest-demo.local.json`
- `bash scripts/video-director.sh run demo/contest/video-director.contest-demo.local.json --dry-run`
- `bash scripts/video-director.sh run demo/contest/video-director.contest-demo.local.json`
- Audio smoke with a full-track WAV and final mp4 duration check
- Draft adapter smoke with `allow_source_stretch=false`
- Draft adapter smoke with `allow_source_stretch=true`
- Timeline inspection: no `final-tail-buffer` clip and no default
  `generated://black` source
