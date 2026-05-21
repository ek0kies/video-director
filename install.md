---
name: video-director-install
description: Install video-director into the current agent and verify the local mp4 render path.
---

# video-director install

Use this file only for first-time install or reconnect. For daily editing, read
`SKILL.md`.

## What you're doing

You are setting up a video generation skill for any coding agent with
shell access: Claude Code, Codex, Hermes, Openclaw, TRAE SOLO, or another agent
that can discover a `SKILL.md` file.

Five things must be true:

1. The `video-director` repo is cloned somewhere stable.
2. The whole repo is registered with the current Agent as `skills/video-director/`.
3. `scripts/install.sh` can find Python 3.10+ or `VIDEO_DIRECTOR_PYTHON` points
   to one.
4. `scripts/doctor.sh` reports `STATUS PASS`.
5. The current agent invokes the Skill through `scripts/run.sh`.

The setup is cross-platform. Do not treat Windows, macOS, Linux, Codex, TRAE
SOLO, Antigravity, or any other Agent as the product boundary. The boundary is
the public launcher plus the whole repository registered as a Skill.

## Agent fast path

Run these commands from the Skill root. Do not ask the human to perform them
manually.

```bash
bash scripts/install.sh
bash scripts/doctor.sh
bash tests/smoke.sh
```

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
powershell -ExecutionPolicy Bypass -File scripts\doctor.ps1
powershell -ExecutionPolicy Bypass -File tests\smoke.ps1
```

If `install.sh` or `doctor.sh` prints `FIX` commands, execute the safe local
fixes yourself. Ask the human only when a fix needs admin/system package
permission, no compatible Python exists, or the Agent skill directory cannot be
resolved.

The reusable install prompt for another AI Agent is:

```text
examples/install-prompt.md
```

## Install prompt contract

- Do the setup yourself. Ask the user only for decisions or permissions you
  cannot safely infer, such as installing system packages.
- Prefer a stable clone path. Examples include `~/Developer/video-director` on
  Unix-like systems or `%USERPROFILE%\Developer\video-director` on Windows.
- Choose the platform-appropriate package manager yourself. Do not ask the user
  to provide Python paths unless auto-detection fails.
- Do not install Miniforge, Conda, Anaconda, pyenv, or any other Python
  distribution automatically. If no compatible Python is found, stop and ask
  the user to choose a lightweight installation method.
- Register the whole repo directory, not only `SKILL.md`; scripts and runtime
  must remain siblings of `SKILL.md`.
- Verify with a real smoke command. Do not declare success from file existence
  alone.
- Do not install optional cloud, TTS, avatar, draft-adapter, or animation
  dependencies unless the user asks for those paths.
- Do not ask the user to open or copy template JSON files. The templates under
  `runtime/templates/` are internal; generate local configs from the user's
  request and ask only for missing information required by the selected path.
- Do not create one-off job scripts, config files, manifests, generated mp4
  files, SRT files, or reports in the Skill root. Use the user's workspace
  `.video-director/` directory or the runtime `output/video_director/` tree.
- When reporting success, lead with the final mp4 or requested draft path.
  Internal files are only for Agent/debug use.

## 1. Clone

Example:

```bash
test -d ~/Developer/video-director || git clone https://github.com/ek0kies/video-director ~/Developer/video-director
cd ~/Developer/video-director
```

If the repo already exists and is a Git checkout, run:

```bash
git pull --ff-only
```

## 2. Resolve Python

Required dependencies:

| Dependency | Purpose |
| --- | --- |
| Python 3.10+ | Runs the bundled Video Director runtime |
| Pillow | Subtitle and render support, declared in `pyproject.toml` |
| ffmpeg | Required for final mp4 rendering |
| ffprobe | Used for media/audio probing when available |

Do not assume `python3` is wrong just because another machine reports an older
default. The installer checks `python3`, `python`, `py -3`, then versioned
commands:

```bash
bash scripts/install.sh --skip-system-install
```

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -SkipSystemInstall
```

Low-level Windows cmd fallback:

```bat
scripts\video-director.cmd --help
```

Only ask the user for a Python path if launcher auto-detection fails. Never
install Miniforge, Conda, Anaconda, pyenv, or another Python distribution as a
fallback. Before proposing any Python installation, explicitly test both
`python3` and `python`:

```bash
python3 -c "import sys; print(sys.executable); print(sys.version)"
python -c "import sys; print(sys.executable); print(sys.version)"
```

If either reports Python 3.10 or newer, use that command:

```bash
export VIDEO_DIRECTOR_PYTHON=python3  # or python, whichever is Python 3.10+
bash scripts/install.sh --skip-system-install
```

Windows PowerShell:

```powershell
python3 -c "import sys; print(sys.executable); print(sys.version)"
python -c "import sys; print(sys.executable); print(sys.version)"
py -3 -c "import sys; print(sys.executable); print(sys.version)"
$env:VIDEO_DIRECTOR_PYTHON = "py -3"
powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -SkipSystemInstall
```

If neither command is compatible, stop and ask the user how they want Python
3.10+ installed. Prefer a lightweight OS/package-manager Python over a full
Python distribution. Do not download installer bundles on your own.

If one command alias fails but another works, continue with the working command.
For example, `python3` may be missing on Windows while `python` or `py -3` is a
valid Python 3.10+ interpreter.

## 3. Install Python packages when needed

The runtime is loaded from the repo by the launcher. Use the managed isolated
environment created by `scripts/install.sh` instead of installing baseline
dependencies globally.

```bash
bash scripts/install.sh --skip-system-install
```

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -SkipSystemInstall
```

`requirements.txt` is the baseline dependency manifest used by the installer.
`pyproject.toml` remains the project metadata source. Do not add another
dependency manifest under `runtime/`.

If dependency download is slow or times out, retry inside the managed
environment instead of installing globally. Agents may increase pip timeout and
use a user-appropriate mirror when allowed by the environment:

```bash
python -m pip install --timeout 120 --retries 5 -r requirements.txt
```

PowerShell:

```powershell
$env:PIP_DEFAULT_TIMEOUT = "120"
$env:PIP_RETRIES = "5"
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Optional extras are not installed by default:

```bash
"${VIDEO_DIRECTOR_VENV:-.venv}/bin/python" -m pip install -e ".[jianying]"   # optional Jianying draft adapter
"${VIDEO_DIRECTOR_VENV:-.venv}/bin/python" -m pip install -e ".[tos]"        # optional cloud audio delivery
```

## 4. Install ffmpeg

`ffmpeg` and `ffprobe` are hard requirements for the default mp4 path.

`scripts/install.sh` attempts installation when a supported package manager and
permission are available. If not, `scripts/doctor.sh` prints the minimal command
for the OS. The command set is:

```bash
# macOS
command -v ffmpeg >/dev/null || brew install ffmpeg

# Debian / Ubuntu
sudo apt-get update && sudo apt-get install -y ffmpeg

# Arch
sudo pacman -S ffmpeg

# Windows
winget install Gyan.FFmpeg
```

If package installation requires sudo/admin approval, show the exact command and
wait. Do not guess or invent passwords.

## 5. Register the skill

Register the whole repo with the current agent's skill mechanism. Do not copy
only `SKILL.md`; scripts and runtime must remain siblings of `SKILL.md`.

If the agent has a skills directory, symlink or copy the whole repo there. The
following paths are examples:

```bash
# Claude Code
mkdir -p ~/.claude/skills
ln -sfn ~/Developer/video-director ~/.claude/skills/video-director

# Codex
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
ln -sfn ~/Developer/video-director "${CODEX_HOME:-$HOME/.codex}/skills/video-director"
```

For Hermes, Openclaw, TRAE SOLO, or another agent, use the skills directory or
skill-import mechanism documented by that agent. If the agent cannot determine
the location, ask the user one concise question for the skills directory or
whether to import `SKILL.md` through the agent's system prompt/config.

## 6. Verify

Run a real local smoke test:

```bash
bash tests/smoke.sh
```

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File tests\smoke.ps1
```

Success means the smoke script reports `STATUS PASS`, the final render target
reports `status=rendered`, and a playable `contest-demo.mp4` exists in the smoke
output directory.

## Hand off

Tell the user:

- Where the repo is installed.
- Which agent skill directory was registered.
- That a good first request is: "Use video-director to inventory these media
  files, propose a short-video strategy, and render an mp4 after I approve it."
- That the default contest-safe path is local mp4 rendering; cloud/TTS/avatar
  and adapter-specific draft export are optional follow-ups.
- That routine generated files live under the workspace/internal output tree,
  not in the Skill source directory.

## Updating an existing install

Users should not have to copy maintenance instructions or run update commands themselves.
If a user asks to update Video Director, treat it as an agent-first task. The
expected user request is simply:

```text
Update Video Director.
```

Agent update checklist:

1. Locate the registered `video-director` skill directory for the current agent.
2. Resolve whether that path is a symlink, a Git checkout, or a copied folder.
3. If it is a symlink to a Git checkout or a Git checkout, run the platform
   update entrypoint:

   ```bash
   bash scripts/run.sh update
   ```

   Windows:

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\run.ps1 update
   ```

4. If it is a copied non-Git folder, back it up, clone the latest repo to a
   stable local path, and repoint the agent skill registration to the whole
   repo.
5. Use the launcher-selected Python for dependency checks and install only
   missing baseline dependencies into that interpreter.
6. Run the real smoke test from the Verify section before reporting success.

If local user changes are present, do not overwrite them. Report the dirty
files and ask whether to back them up, commit them, or stop.

## Keeping current by Agent

```bash
cd ~/Developer/video-director
bash scripts/run.sh update
```

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run.ps1 update
```
