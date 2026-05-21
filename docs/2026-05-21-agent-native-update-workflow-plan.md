# Agent-native update workflow plan

## Goal

Video Director updates must feel like a built-in Skill action after the first
install. A user should be able to ask the current Agent to "update Video
Director" without returning to the repository, copying a prompt, or running
manual commands.

## Current problem

The README and install guide previously exposed paste-in update instructions for
humans. That works as documentation, but it keeps routine maintenance outside
the installed Skill experience.

## Recommended design

| Area | Change | Result | Verification |
| --- | --- | --- | --- |
| `scripts/update.sh` | Add a Unix/macOS update entrypoint for Git checkouts. | Agents have a stable command for automatic refresh. | `bash scripts/update.sh --help` and parse check. |
| `scripts/update.ps1` | Add a Windows PowerShell update entrypoint. | Windows Agents get the same update contract. | PowerShell parse check when available. |
| `scripts/run.*` | Route `update` to the update entrypoint before normal runtime dispatch. | Public launcher supports `scripts/run.sh update`. | `bash scripts/run.sh update --help`. |
| `SKILL.md` | Treat update requests as Agent-native workflow, not a user prompt. | Installed Skill contains its own update behavior. | Documentation read-through. |
| README files | Replace pasted update instructions with a one-line user request. | Humans do not need to copy update instructions. | Documentation read-through. |
| `install.md` | Keep detailed checklist for Agents, not as a human paste prompt. | Agents still have exact recovery rules. | Documentation read-through. |

## Boundaries

- Do not overwrite dirty local changes. Stop and report changed files.
- Do not silently replace non-Git copied Skill directories from inside a running
  script. The Agent should back up and replace them using its own registration
  mechanism.
- Do not install optional cloud, TTS, avatar, or editable-draft dependencies.
- Do not change render, doctor, config, or adapter behavior.

## Agent update flow

1. Locate the registered `video-director` Skill directory.
2. Resolve whether it is a symlink, Git checkout, or copied folder.
3. If it is a Git checkout, run the update entrypoint.
4. If it is a copied folder, back it up, clone the latest repository to a stable
   path, and repoint the Agent registration to the whole repository.
5. Run install, doctor, and smoke verification.
6. Report only success/failure, install path, registered Skill path, and
   verification result.
