# video-director

用编码 Agent 把本地素材生成可直接播放的短视频 mp4。

[English](README.md)

把图片或视频素材放到一个目录里，让 Agent 使用这个 skill，即可得到基于时间线的 `final.mp4` 类输出。默认路径是：

```text
素材清单 -> 旁白优先时间线 -> ffmpeg 渲染
```

## 安装提示词

复制给 Claude Code、Codex、Hermes、Openclaw、TRAE SOLO，或任何有 shell 权限的 Agent：

```text
Set up https://github.com/ek0kies/video-director for me.
Read install.md first and handle the environment yourself. The required runtime
dependencies are Python 3.11+, Pillow from the root pyproject.toml, and
ffmpeg/ffprobe.
Clone the repo to a stable local path, use the launcher to detect an existing
Python 3.11+ before installing anything, install only missing dependencies into
that interpreter, register the whole repo as a skill for the current agent, then
run the built-in demo smoke test. Do not install Miniforge, Conda, Anaconda,
pyenv, or another Python distribution automatically; ask me first if no
compatible Python exists. Only ask me if you need permission for system package
installation or cannot determine the agent's skill location.
```

GitHub 仓库地址：https://github.com/ek0kies/video-director

## 能做什么

- 读取本地图片/视频素材，生成结构化素材清单。
- 生成旁白优先的 beat sheet、剪辑决策和时间线模型。
- 通过 ffmpeg 渲染竖屏 mp4。
- 默认烧录字幕。
- 云生成、TTS、数字人、可编辑草稿导出都是可选路径。

## 手动快速开始

```bash
git clone https://github.com/ek0kies/video-director ~/Developer/video-director
cd ~/Developer/video-director
bash scripts/video-director.sh --help
bash scripts/video-director.sh demo
bash scripts/video-director.sh doctor demo/contest/video-director.contest-demo.local.json
bash scripts/video-director.sh run demo/contest/video-director.contest-demo.local.json --dry-run
bash scripts/video-director.sh run demo/contest/video-director.contest-demo.local.json
```

Windows：

```bat
git clone https://github.com/ek0kies/video-director %USERPROFILE%\Developer\video-director
cd %USERPROFILE%\Developer\video-director
scripts\video-director.cmd demo
scripts\video-director.cmd doctor demo\contest\video-director.contest-demo.local.json
scripts\video-director.cmd run demo\contest\video-director.contest-demo.local.json --dry-run
scripts\video-director.cmd run demo\contest\video-director.contest-demo.local.json
```

## 日常使用

安装后，把 Agent 指向素材目录，然后说：

```text
Use video-director to inventory these materials, propose a short-video strategy,
and render a direct mp4 after I approve the plan.
```

Unix/macOS 使用 `scripts/video-director.sh`，Windows 使用 `scripts\video-director.cmd`。配置模板是 skill 内部实现细节；正常使用时，Agent 会根据你的请求生成本地配置，只在所选路径缺少必要信息时再询问。

## License

MIT
