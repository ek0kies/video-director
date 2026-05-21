# Agent-native Skill package plan

## Requirement summary

Video Director must be consumable by an AI Agent as a self-installing and
self-checking Skill. A human should be able to paste one install prompt to an
Agent with shell access; the Agent should then install the Skill, prepare Python
dependencies, run doctor checks, and call the Skill without pushing manual setup
steps back to the human.

## Scope

| Area | Decision |
| --- | --- |
| Skill payload | Keep the repository root as the Skill directory that is registered as `skills/video-director/`. |
| Runtime | Reuse the existing `runtime/` and `scripts/video_director.py` command router. |
| Installation | Add executable `scripts/install.sh` for Python detection, virtualenv setup, requirements install, and local permission checks. |
| Doctor | Add executable `scripts/doctor.sh` for PASS/FAIL output and AI-executable repair commands. |
| Invocation | Add executable `scripts/run.sh` as the stable Skill runtime entrypoint. |
| Windows support | Add PowerShell-native `scripts/install.ps1`, `scripts/doctor.ps1`, `scripts/run.ps1`, and `tests/smoke.ps1`. |
| Examples | Add an Agent-facing install prompt under `examples/`. |
| Verification | Add a smoke script under `tests/` that exercises install, doctor, demo, dry-run, render, and summarize. |

## Non-goals

| Non-goal | Reason |
| --- | --- |
| Copy runtime into a nested `skills/video-director/` folder | It would create two runtime sources and conflict with the current repository-as-skill architecture. |
| Add cloud/TTS/avatar provider dependencies | These remain optional paths selected only when requested. |
| Auto-install Python distributions | Python installation choices remain a human decision when no compatible Python exists. |
| Replace the existing router | The current router is the stable command boundary. |

## Implementation plan

| Step | File path | Change | Expected result | Verification |
| --- | --- | --- | --- | --- |
| 1 | `requirements.txt` | Declare baseline runtime dependencies for installer use. | `install.sh` can install without parsing project metadata. | `python -m pip install -r requirements.txt` via installer. |
| 2 | `scripts/install.sh` | Add self-install entrypoint with Python detection, venv setup, dependency install, ffmpeg check/attempt, and permission checks. | An Agent can prepare the local Skill environment with one command. | Run `bash scripts/install.sh --no-system-install`. |
| 3 | `scripts/doctor.sh` | Add PASS/FAIL doctor wrapper with OS-specific repair commands. | Failures are actionable by an AI Agent. | Run `bash scripts/doctor.sh runtime/templates/video.template.json`. |
| 4 | `scripts/run.sh` | Add stable entrypoint that prefers the managed venv. | Agent can call Skill commands consistently. | Run `bash scripts/run.sh --help`. |
| 5 | `examples/install-prompt.md` | Add the final prompt a human can send to an AI Agent. | Install contract is portable and explicit. | Manual read-through. |
| 6 | `tests/smoke.sh` | Add end-to-end smoke script. | Install and render path can be verified repeatedly. | Run smoke script where ffmpeg is available. |
| 7 | `SKILL.md` and `install.md` | Reframe docs around Agent-native install and auto-repair. | Docs no longer make humans responsible for routine setup. | Read and command verification. |
| 8 | `scripts/*.ps1`, `tests/smoke.ps1` | Add Windows-native Agent entrypoints. | Windows Agents can install, doctor, run, and smoke without Git Bash. | Parse checks where PowerShell is available; otherwise document unverified Windows runtime. |

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| System package install requires admin approval. | Installer attempts only when allowed and prints minimal OS-specific commands on failure. |
| Existing user changes are present in the working tree. | Touch only Skill packaging files and avoid unrelated dirty files. |
| Windows support differs from shell scripts. | Provide PowerShell-native install/doctor/run/smoke entrypoints and keep the existing `.cmd` launcher as the low-level runtime bridge. |
| Optional draft/cloud dependencies are missing. | Doctor marks them optional unless selected by config. |
