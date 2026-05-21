# video-director

用编码 Agent 把本地素材生成可直接播放的短视频 mp4。

![Video Director 项目封面](https://raw.githubusercontent.com/ek0kies/video-director/main/assets/video-director-cover.png)

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

不要自动安装 Miniforge、Conda、Anaconda、pyenv 或其他完整 Python 发行版。不要在 Skill 根目录生成一次性脚本、配置、字幕、manifest 或成品视频；这些中间产物放到我的工作区 `.video-director/` 或运行输出目录里。只有在需要安装系统软件、需要管理员权限、找不到兼容 Python，或无法确定当前 Agent 的 skill 目录时，再问我。最后只告诉我安装位置、skill 注册位置、验证结果和最终 mp4 路径。
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
- 云生成、TTS、数字人、可编辑草稿导出都是可选路径；需要配音时可以选择已有音频、生成文案后人工录制，或显式启用豆包 TTS。
- 默认只把最终 mp4 当作用户交付物；manifest、配置快照、时间线、渲染计划等是内部调试产物。

## 手动快速开始

```bash
git clone https://github.com/ek0kies/video-director ~/Developer/video-director
cd ~/Developer/video-director
bash scripts/video-director.sh --help
bash scripts/video-director.sh demo
# demo 默认使用临时目录；按命令输出继续执行 doctor/run
bash scripts/video-director.sh summarize <latest_run.json>
```

Windows：

```bat
git clone https://github.com/ek0kies/video-director %USERPROFILE%\Developer\video-director
cd %USERPROFILE%\Developer\video-director
scripts\video-director.cmd demo
REM demo 默认使用临时目录；按命令输出继续执行 doctor/run
scripts\video-director.cmd summarize <latest_run.json>
```

## 日常使用

安装后，把 Agent 指向素材目录，然后说：

```text
请使用 video-director 读取这些素材，先整理素材清单并提出短视频剪辑方案；等我确认方案和文案后，再渲染一个可直接播放的 mp4。
```

Unix/macOS 使用 `scripts/video-director.sh`，Windows 使用 `scripts\video-director.cmd`；Agent 也可以用
`scripts/run.sh update` 或 `scripts\run.ps1 update` 更新已安装的 Git checkout。配置模板是 skill 内部实现细节；正常使用时，Agent 会根据你的请求生成本地配置，只在所选路径缺少必要信息时再询问。
生成的配置会包含 `operation_confirmation.summary`，Agent 应先把这些执行参数展示给你并等待确认，再开始运行。这个执行确认和自动生成文案审核是两个独立 gate：Agent 写出的旁白或字幕仍然要单独审核通过后才能渲染。

正常使用时，Skill 根目录应保持像安装包一样干净。一次性配置、素材清单、文案审核报告、SRT、渲染计划和 staging 文件都不是默认用户交付物。

## License

MIT
