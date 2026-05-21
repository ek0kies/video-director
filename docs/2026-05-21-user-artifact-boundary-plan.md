# User artifact boundary plan

## Requirement summary

Video Director is a general-purpose Agent Skill, not a Windows-only installer or
one-agent workflow. Normal use must keep the Skill root clean and expose only
the user-relevant deliverable by default. Internal files remain available for
debugging but should not be presented as primary output.

## Scope

| Area | Decision |
| --- | --- |
| Product boundary | Keep the public launcher and whole-repo Skill contract platform-neutral. |
| Skill root | Treat it as product source during normal jobs; do not write one-off job files there. |
| Working files | Route generated configs and Agent scratch files to `.video-director/` or `output/video_director/`. |
| User deliverable | Lead with final mp4 or requested editable draft. |
| Debug artifacts | Keep manifests, config snapshots, timelines, render plans, and staging media internal by default. |
| Voiceover | Present provided audio, generated copy for manual recording, and optional Doubao TTS as explicit choices. |
| Subtitles | Burn subtitles into mp4 by default; sidecar SRT requires explicit advanced opt-in and must never be generated casually. |
| Render validity | Reject subtitle-only or black-screen outputs; a final mp4 must contain at least one real visual asset. |

## Implementation plan

| Step | File path | Change | Expected result | Verification |
| --- | --- | --- | --- | --- |
| 1 | `SKILL.md`, `install.md` | Add platform-neutral Agent rules and artifact hygiene contract. | Other Agents stop creating job scripts/configs/media in the Skill root. | Read-through and command help checks. |
| 2 | `README.md`, `README_ZH.md` | Update setup prompt and quick start to describe clean Skill root and concise deliverables. | User-facing docs set the right expectation before installation. | Read-through. |
| 3 | `scripts/video_director.py` | Default generated config paths to `.video-director/configs/` and demo output to a temp root unless explicitly overridden. | Running demo or config without an output path does not pollute the Skill root. | Launcher config/demo smoke checks. |
| 4 | `runtime/workflow.py`, `runtime/summarize.py` | Return concise deliverable-first output; move internals under `internal` or `--verbose`. | Agents report final mp4 first and avoid dumping irrelevant artifacts. | Run summarize and smoke checks. |
| 5 | `.gitignore` | Ignore `.video-director/`. | Local scratch state cannot be accidentally committed. | `git status --short`. |
| 6 | `runtime/adapters/rendered_video.py` | Add CJK font fallback, strip subtitle trailing punctuation, require explicit SRT opt-in, and verify rendered mp4 has a video stream. | Chinese subtitles render as text, captions do not end with stray punctuation, and sidecar SRT stays off by default. | Public smoke plus targeted subtitle/font checks. |
| 7 | `runtime/workflow.py` | Validate that the timeline contains a real visual asset before rendering. | Subtitle-only or text-only output fails instead of being reported as success. | Public smoke and targeted invalid timeline check. |

## Risks

| Risk | Mitigation |
| --- | --- |
| Existing scripts expect verbose summarize output. | Keep `--verbose` for internal artifact inspection. |
| Agents still hand-roll scripts despite docs. | Make `SKILL.md` explicit that the root is product source and launchers are the public API. |
| Users need debug details after failure. | Keep internal files on disk and expose them through verbose summary or error triage. |
