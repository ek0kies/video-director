# video-director

用编码 Agent 把本地素材生成可直接播放的短视频 mp4。

![Video Director 项目封面](assets/video-director-cover.png)

[English](README.md)

把图片或视频素材放到一个目录里，让 Agent 使用这个 skill，即可得到基于时间线的 `final.mp4` 类输出。默认路径是：

```text
素材清单 -> 旁白优先时间线 -> ffmpeg 渲染
```

## 安装提示词

复制给 Claude Code、Codex、Hermes、Openclaw、TRAE SOLO，或任何有 shell 权限的 Agent：

```text
请帮我安装 Video Director：https://github.com/ek0kies/video-director

请先阅读仓库里的 install.md，然后你自己完成环境检查和安装。需要的运行环境是 Python 3.10+、根目录 pyproject.toml 中声明的 Pillow，以及 ffmpeg/ffprobe。

请把仓库克隆到一个稳定的本地目录，使用仓库自带 launcher 自动检测已有 Python 3.10+，不要一开始就安装新的 Python。只把缺失依赖安装到 launcher 选中的那个 Python 解释器里。请把整个仓库注册为当前 Agent 的 skill，而不是只复制 SKILL.md。安装后请运行内置 demo smoke test，确认可以生成 mp4。

不要自动安装 Miniforge、Conda、Anaconda、pyenv 或其他完整 Python 发行版。只有在需要安装系统软件、需要管理员权限、找不到兼容 Python，或无法确定当前 Agent 的 skill 目录时，再问我。最后只告诉我安装位置、skill 注册位置和验证结果。
```

GitHub 仓库地址：https://github.com/ek0kies/video-director

## 更新

安装过以后，直接对 Agent 说：

```text
更新 Video Director。
```

已安装的 Skill 内置更新流程。Agent 应该自己定位已注册的
`video-director` Skill，刷新整个仓库，执行安装和 smoke 检查，最后只汇报安装位置、Skill 注册位置和验证结果。

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
请使用 video-director 读取这些素材，先整理素材清单并提出短视频剪辑方案；等我确认方案和文案后，再渲染一个可直接播放的 mp4。
```

Unix/macOS 使用 `scripts/video-director.sh`，Windows 使用 `scripts\video-director.cmd`；Agent 也可以用
`scripts/run.sh update` 或 `scripts\run.ps1 update` 更新已安装的 Git checkout。配置模板是 skill 内部实现细节；正常使用时，Agent 会根据你的请求生成本地配置，只在所选路径缺少必要信息时再询问。

## License

MIT
