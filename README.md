# video-director

Turn local media into a directly playable short mp4 with a coding agent.

Drop source media in a folder, ask an agent to use this skill, and get a
timeline-backed `final.mp4` style output. The default path is local-first:
manifest -> narration-first timeline -> ffmpeg render.

## Setup prompt

Paste into Claude Code, Codex, Hermes, Openclaw, TRAE SOLO, or any agent with
shell access:

```text
Set up https://github.com/ek0kies/video-director for me.
Read install.md first and handle the environment yourself. The required runtime
dependencies are Python 3.11+, Pillow from the root pyproject.toml, and
ffmpeg/ffprobe.
Clone the repo to a stable local path, install dependencies using the best
package manager for this machine, register the whole repo as a skill for the
current agent, then run the built-in demo smoke test. Only ask me if you need
permission for system package installation or cannot determine the agent's skill
location.
```

GitHub repository: https://github.com/ek0kies/video-director

## What it does

- Inventories local image/video assets into a structured manifest.
- Builds a narration-first beat sheet, edit decision list, and timeline model.
- Renders a vertical mp4 through ffmpeg.
- Burns subtitles by default.
- Keeps cloud generation, TTS, avatar, and Jianying draft export optional.

## Manual quick start

```bash
git clone https://github.com/ek0kies/video-director ~/Developer/video-director
cd ~/Developer/video-director
uv sync || pip install -e .
# This installs dependencies from the skill root; runtime code stays bundled
# under runtime/ and is loaded by the launcher.
# Register the whole repo with your agent's skill mechanism.
# For example, symlink/copy this repo into the agent's skills directory,
# or import SKILL.md through the agent's config/system prompt.
bash scripts/video-director.sh demo
bash scripts/video-director.sh doctor demo/contest/video-director.contest-demo.local.json
bash scripts/video-director.sh run demo/contest/video-director.contest-demo.local.json --dry-run
bash scripts/video-director.sh run demo/contest/video-director.contest-demo.local.json
```

Windows:

```bat
git clone https://github.com/ek0kies/video-director %USERPROFILE%\Developer\video-director
cd %USERPROFILE%\Developer\video-director
uv sync || pip install -e .
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
`scripts\video-director.cmd` on Windows; see `SKILL.md` for the full workflow.
Config templates are internal to the skill. In normal use, the agent generates
the local config from your request and only asks for missing information when a
selected path requires it.
