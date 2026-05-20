# Video Director Agent Rules

本仓库是一个 local-first 的 Agent Skill：把本地素材清单、旁白和剪辑策略转换为可直接播放的短视频 mp4，Jianying draft 和云端生成能力只作为显式可选路径。

## 入口文档

每次进入本仓库，先按顺序读取：

1. `AGENTS.md`
2. `docs/ARCHITECTURE.md`
3. `docs/DECISIONS.md`
4. `SKILL.md`
5. 当前任务相关的 `references/*.md` 或源码入口

## 命名规则

- 对用户、README、安装文档、命令输出统一使用 `Video Director`。
- `runtime/` 是当前内部运行时代码目录，不再额外挂包名子目录。
- 不得重新引入旧运行时目录名。

## 工程边界

- 默认不引入云服务、遥测、远端数据上报。
- 默认输出目标是 direct mp4，即 `final_render`。
- `draft` 必须表示真实 Jianying draft，不得用 bundle/debug 产物冒充。
- `scripts/video_director.py` 是命令路由真源；shell/cmd 脚本只做解释器选择和薄封装。
- 根目录 `pyproject.toml` 是依赖真源；不要在 runtime 子目录重复维护依赖版本。

## 本地生成物

- `demo/contest/*` 中由 `scripts/video-director.sh demo` 生成的素材、manifest、local config 和输出均视为本地生成物。
- `video-director.*.local.json`、`output/`、demo 输出、Jianying draft 输出不得作为默认提交内容。

## 验证要求

涉及运行链路、脚本入口、配置契约或依赖声明变更时，至少执行：

```bash
bash scripts/video-director.sh demo
bash scripts/video-director.sh doctor demo/contest/video-director.contest-demo.local.json
bash scripts/video-director.sh run demo/contest/video-director.contest-demo.local.json --dry-run
```

涉及 render path 时追加：

```bash
bash scripts/video-director.sh run demo/contest/video-director.contest-demo.local.json
bash scripts/video-director.sh summarize demo/contest/output/contest-demo/latest_run.json
```
