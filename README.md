# video-director

Turn local media into a directly playable short mp4 with a coding agent.

![Video Director project cover](https://raw.githubusercontent.com/ek0kies/video-director/main/assets/video-director-cover.png)

[简体中文](README_ZH.md)

Drop source media in a folder, ask an agent to use this skill, and get a
timeline-backed `final.mp4` style output. The default path is:
manifest -> narration-first timeline -> ffmpeg render.

## Setup prompt

Paste into Claude Code, Codex, Hermes, Openclaw, TRAE SOLO, or any agent with
shell access:

```text
Set up https://github.com/ek0kies/video-director for me.
Read install.md first and handle the environment yourself. The required runtime
dependencies are Python 3.10+, Pillow from the root pyproject.toml, and
ffmpeg/ffprobe.
Clone the repo to a stable local path, use the launcher to detect an existing
Python 3.10+ before installing anything, install only missing dependencies into
that interpreter, register the whole repo as a skill for the current agent, then
run the built-in demo smoke test. Do not install Miniforge, Conda, Anaconda,
pyenv, or another Python distribution automatically; ask me first if no
compatible Python exists. Only ask me if you need permission for system package
installation or cannot determine the agent's skill location.
```

GitHub repository: https://github.com/ek0kies/video-director

## Updating

After Video Director is installed, just ask your agent:

```text
Update Video Director.
```

The installed Skill contains the update workflow. The agent should locate the
registered `video-director` Skill, refresh the whole repository, run the install
and smoke checks, and report the install path, registered Skill path, and
verification result.

## What it does

- Inventories local image/video assets into a structured manifest.
- Builds a narration-first beat sheet, edit decision list, and timeline model.
- Renders a vertical mp4 through ffmpeg.
- Burns subtitles by default.
- Keeps cloud generation, TTS, avatar, and adapter-specific draft export optional.

## Manual quick start

```bash
git clone https://github.com/ek0kies/video-director ~/Developer/video-director
cd ~/Developer/video-director
bash scripts/video-director.sh --help
# If doctor later reports missing Python packages, install them into the
# interpreter selected by the launcher.
bash scripts/video-director.sh demo
bash scripts/video-director.sh doctor demo/contest/video-director.contest-demo.local.json
bash scripts/video-director.sh run demo/contest/video-director.contest-demo.local.json --dry-run
bash scripts/video-director.sh run demo/contest/video-director.contest-demo.local.json
```

Windows:

```bat
git clone https://github.com/ek0kies/video-director %USERPROFILE%\Developer\video-director
cd %USERPROFILE%\Developer\video-director
scripts\video-director.cmd demo
scripts\video-director.cmd doctor demo\contest\video-director.contest-demo.local.json
scripts\video-director.cmd run demo\contest\video-director.contest-demo.local.json --dry-run
scripts\video-director.cmd run demo\contest\video-director.contest-demo.local.json
```

## Daily use

After installation, point your agent at a folder containing source media and say:

```text
Use video-director to inventory these materials, propose a short-video strategy,
and render a direct mp4 after I approve the plan.
```

The public command surface is `scripts/video-director.sh` on Unix/macOS and
`scripts\video-director.cmd` on Windows; agents can also use
`scripts/run.sh update` or `scripts\run.ps1 update` to refresh an installed Git
checkout. See `SKILL.md` for the full workflow. Config templates are internal to
the skill. In normal use, the agent generates the local config from your request
and only asks for missing information when a selected path requires it.

## License

MIT
