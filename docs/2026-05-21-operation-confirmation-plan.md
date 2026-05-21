# Operation confirmation gate plan

## Requirement

Video Director must keep two separate gates:

| Gate | Purpose | Blocking point |
| --- | --- | --- |
| Operation confirmation | Show the user the exact execution parameters after the request and before work starts. | Before `run` dry-run or render. |
| Copy review | Review Agent-generated viewer-facing narration or subtitles. | During production bundle build, before timeline/render. |

## Design

Add a top-level `operation_confirmation` object to generated configs. Config
generation writes the operation summary, including output mode, targets,
materials source, narration source, duration, subtitle settings, and output
paths. The status is `pending` by default and `approved` only when the Agent has
already received explicit user confirmation.

`run` validates this object before starting the workflow. Missing or pending
operation confirmation blocks both dry-run and render. After user approval, the
Agent can either regenerate config with `--operation-confirmed` or update the
existing config through `confirm-operation <config>`. This keeps the execution
confirmation independent from the existing generated-copy review gate.

## Implementation plan

| File | Change | Verification |
| --- | --- | --- |
| `runtime/operation_confirmation.py` | Build summary, apply status, and enforce approval. | Pending config fails before workflow starts. |
| `runtime/config_prepare.py` | Add `--operation-confirmed` and `--operation-note`; write confirmation state into config and command result. | Config JSON contains operation summary. |
| `runtime/workflow.py` | Enforce operation approval at workflow entry. | `run` returns a clean error for pending config. |
| `scripts/video_director.py` | Add `confirm-operation` and ensure demo config is pre-confirmed. | Public smoke still completes. |
| `SKILL.md` and README files | Document the two separate gates and the confirmation flag. | Documentation read-through and launcher help/config checks. |
