# Video Director Copy Review And Subtitle Centering Plan

## 需求理解

用户明确输入的标题、旁白或字幕应直接作为用户意图使用，不需要二审。由 Agent 或模型自动生成的观众可见文案必须先进入二审，避免把时长、路径、剪辑指令误写进字幕，也避免生成与素材或常识冲突的内容。

当前 final mp4 字幕文字视觉上靠近字幕框上边缘，需要按字体真实边界在字幕框内居中。

## 范围

| 文件 | 改动点 | 验证方式 |
| --- | --- | --- |
| `runtime/config_prepare.py` | 增加文案来源和审核状态配置入口 | launcher 生成配置并检查字段 |
| `runtime/production.py` | 运行前拦截未审核的自动生成文案 | launcher run 预期失败 |
| `runtime/models.py` | 在生产 bundle 中保留文案元数据 | dry-run 输出可追溯 |
| `runtime/adapters/rendered_video.py` | 修复字幕框内文字居中计算 | render/smoke 检查 |
| `scripts/video_director.py` | 将文案审核失败输出为干净的用户级错误 | launcher run 预期失败 |
| `SKILL.md` | 更新使用契约，说明自动生成文案必须审核 | 文档检查 |

## 非目标

- 不引入云审核或外部内容安全服务。
- 不修改剪映 draft 字幕适配器。
- 不自动重写用户明确输入的文案。

## 推荐方案

采用显式字段：

- `inputs.narration_source`: `user_provided` 或 `generated`
- `inputs.copy_review.required`: 是否需要二审
- `inputs.copy_review.status`: `pending` 或 `approved`

运行时规则：

- `user_provided` 默认直接通过。
- `generated` 且审核未通过时中止运行。
- `--materials-dir` 应覆盖模板示例素材，让用户给定素材目录进入扫描路径。

这样不会影响用户手写文案的现有路径，同时给 Agent 自动生成文案提供硬边界。
