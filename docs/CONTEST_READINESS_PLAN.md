# Contest Readiness Plan

## Requirement Summary

Video Director should be safe to publish as a SOLO skill submission. A user who
does not know their Python installation path or config schema should still be
able to ask an Agent to generate a local config, run doctor, dry-run the
workflow, and render a directly playable mp4.

Official contest source: https://forum.trae.cn/t/topic/16860

## Contest Constraints

| Constraint | Implementation impact |
| --- | --- |
| Must be based on new TRAE SOLO, not TRAE IDE SOLO mode | Package as a shareable Skill and document SOLO usage, not only local scripts |
| Must publish a post in the official SOLO contest section | Provide public demo output and reproducible commands for the post |
| Work must be original and compliant | Demo uses generated local materials; real submission should use licensed media |
| Public Skill link is required | Keep the package self-contained and suitable for GitHub/TRAE public sharing |
| Community post supports text, images, and links | Put video/code artifacts behind public links when submitting |

## Scope

| Area | Decision |
| --- | --- |
| Primary output | Direct mp4 through `final_render` |
| Python handling | Cross-platform launcher auto-detects Python 3.11+ with explicit override support |
| Jianying draft | Keep optional and documented as non-primary on macOS |
| Demo path | Provide a local, generated, non-copyright demo asset path |
| Config templates | Keep internal under `runtime/templates/`; Agent generates `.local.json` |
| Cloud services | Out of scope for contest baseline |

## Options

| Option | Pros | Cons | Decision |
| --- | --- | --- | --- |
| Hard-code Homebrew Python | Works on this machine | Fails for other users and Linux/Windows layouts | Rejected |
| Cross-platform router plus thin shell/cmd wrappers | Portable, overridable, usable on Windows/macOS/Linux | Slightly more files to maintain | Selected |
| Vendor a Python runtime | Most controlled | Heavy, platform-specific, poor skill packaging | Rejected |

## Implementation Steps

| Step | Files | Expected result | Verification |
| --- | --- | --- | --- |
| Add interpreter selection | `scripts/video-director.sh`, `scripts/video-director.cmd` | Wrappers find Python 3.11+ or print actionable error | Run with default PATH and `VIDEO_DIRECTOR_PYTHON` |
| Add cross-platform router | `scripts/video_director.py`, `scripts/video-director.sh`, `scripts/video-director.cmd` | macOS/Linux/Windows users have one command family | Run demo, doctor, dry-run, render |
| Remove legacy wrappers | old compatibility shell scripts | Public surface stays small and agent-friendly | Search old entrypoints |
| Add demo generator | `scripts/video_director.py demo` | Generates public-safe local video assets | Run demo and inspect generated files |
| Hide template details | `runtime/templates/`, docs | Users do not copy or edit JSON templates | Search old template names and user-facing wording |
| Update docs | `SKILL.md`, references | Users know the contest-safe path | Read command examples and execute |

## Definition of Done

| Check | Required |
| --- | --- |
| Python 3.11+ selection | Yes |
| Doctor on video config | Must pass on current machine |
| Dry-run | Must produce timeline and render plan |
| Real mp4 render | Must produce a playable file from generated demo assets |
| No cloud dependency | Yes |
| No repository secrets | Yes |
