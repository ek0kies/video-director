---
name: video-director-install
description: Install video-director into the current agent and verify the local mp4 render path.
---

# video-director install

Use this file only for first-time install or reconnect. For daily editing, read
`SKILL.md`.

## What you're doing

You are setting up a local-first video generation skill for any coding agent with
shell access: Claude Code, Codex, Hermes, Openclaw, TRAE SOLO, or another agent
that can discover a `SKILL.md` file.

Five things must be true:

1. The `video-director` repo is cloned somewhere stable.
2. Python 3.11+ is available.
3. Python dependencies from `pyproject.toml` are installed from the repo root.
4. `ffmpeg` and `ffprobe` are available on `PATH`.
5. The current agent can discover this repo's `SKILL.md`.

## Install prompt contract

- Do the setup yourself. Ask the user only for decisions or permissions you
  cannot safely infer, such as installing system packages.
- Prefer a stable clone path such as `~/Developer/video-director` or
  `%USERPROFILE%\Developer\video-director`.
- Choose the platform-appropriate package manager yourself. Do not ask the user
  to provide Python paths unless auto-detection fails.
- Register the whole repo directory, not only `SKILL.md`; scripts and runtime
  must remain siblings of `SKILL.md`.
- Verify with a real smoke command. Do not declare success from file existence
  alone.
- Do not install optional cloud, TTS, avatar, Jianying, or animation dependencies
  unless the user asks for those paths.
- Do not ask the user to open or copy template JSON files. The templates under
  `runtime/templates/` are internal; generate local configs from the user's
  request and ask only for missing information required by the selected path.

## 1. Clone

```bash
test -d ~/Developer/video-director || git clone https://github.com/ek0kies/video-director ~/Developer/video-director
cd ~/Developer/video-director
```

If the repo already exists and is a Git checkout, run:

```bash
git pull --ff-only
```

## 2. Install Python dependencies

Required dependencies:

| Dependency | Purpose |
| --- | --- |
| Python 3.11+ | Runs the bundled Video Director runtime |
| Pillow | Subtitle and render support, declared in `pyproject.toml` |
| ffmpeg | Required for final mp4 rendering |
| ffprobe | Used for media/audio probing when available |

Install Python dependencies with the best available tool. Prefer `uv` if
available; fall back to pip:

```bash
uv sync || pip install -e .
```

The root `pyproject.toml` is the dependency source. The runtime code stays
bundled under `runtime/` and is loaded by the launcher; it is not installed as a
separate package by default.

The baseline dependency is Pillow. Optional extras:

```bash
pip install -e ".[jianying]"   # optional real Jianying draft experiments
pip install -e ".[tos]"        # optional cloud audio delivery
```

## 3. Install ffmpeg

`ffmpeg` and `ffprobe` are hard requirements for the default mp4 path.

Choose the correct package manager for the user's OS. Examples:

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

## 4. Register the skill

Register the whole repo with the current agent's skill mechanism. Do not copy
only `SKILL.md`; scripts and runtime must remain siblings of `SKILL.md`.

If the agent has a skills directory, symlink or copy the whole repo there:

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

## 5. Verify

Run a real local smoke test:

```bash
bash scripts/video-director.sh demo
bash scripts/video-director.sh doctor demo/contest/video-director.contest-demo.local.json
bash scripts/video-director.sh run demo/contest/video-director.contest-demo.local.json --dry-run
bash scripts/video-director.sh run demo/contest/video-director.contest-demo.local.json
bash scripts/video-director.sh summarize demo/contest/output/contest-demo/latest_run.json
```

Windows:

```bat
scripts\video-director.cmd demo
scripts\video-director.cmd doctor demo\contest\video-director.contest-demo.local.json
scripts\video-director.cmd run demo\contest\video-director.contest-demo.local.json --dry-run
scripts\video-director.cmd run demo\contest\video-director.contest-demo.local.json
scripts\video-director.cmd summarize demo\contest\output\contest-demo\latest_run.json
```

Success means the final render target reports `status=rendered` and a playable
`contest-demo.mp4` exists under `demo/contest/output/contest-demo/...`.

## Hand off

Tell the user:

- Where the repo is installed.
- Which agent skill directory was registered.
- That a good first request is: "Use video-director to inventory these media
  files, propose a short-video strategy, and render an mp4 after I approve it."
- That the default contest-safe path is local mp4 rendering; cloud/TTS/avatar and
  Jianying draft export are optional follow-ups.

## Keeping current

```bash
cd ~/Developer/video-director
git pull --ff-only
uv sync || pip install -e .
```
