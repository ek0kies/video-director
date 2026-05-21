#!/usr/bin/env python3
"""Materialize a local Video Director config from internal templates."""

from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence


TEMPLATE_BY_MODE = {
    "bundle_only": "runtime/templates/video.template.json",
    "local": "runtime/templates/video.template.json",
    "cloud": "runtime/templates/cloud.template.json",
}
DRAFT_TEMPLATE = "runtime/templates/draft.template.json"

OUTPUT_MODE_DRAFT = "draft"
OUTPUT_MODE_VIDEO = "video"
SUPPORTED_OUTPUT_MODES = (OUTPUT_MODE_DRAFT, OUTPUT_MODE_VIDEO)
NARRATION_SOURCE_USER = "user_provided"
NARRATION_SOURCE_GENERATED = "generated"
SUPPORTED_NARRATION_SOURCES = (NARRATION_SOURCE_USER, NARRATION_SOURCE_GENERATED)
UNSUPPORTED_DRAFT_ADAPTER_MESSAGE = (
    "The current editable-draft adapter is not supported on macOS in this package. "
    "Use --output-mode video for the judge-safe mp4 path, or run draft export in a supported environment. "
    "Set --allow-unsupported-draft-adapter only for local experimental debugging."
)


def skill_root_from_runtime() -> Path:
    return Path(__file__).resolve().parent.parent


def _read_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _set_nested(data: Dict[str, Any], dotted_key: str, value: Any) -> None:
    current: Dict[str, Any] = data
    parts = [part.strip() for part in dotted_key.split(".") if part.strip()]
    if not parts:
        raise ValueError("override key must not be empty")
    for part in parts[:-1]:
        next_value = current.get(part)
        if not isinstance(next_value, dict):
            next_value = {}
            current[part] = next_value
        current = next_value
    current[parts[-1]] = value


def _parse_scalar(raw: str) -> Any:
    text = raw.strip()
    if text == "":
        return ""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _read_script_text(args: argparse.Namespace) -> Optional[str]:
    provided = [
        bool(args.script_text),
        bool(args.script_file),
        bool(args.narration_text),
        bool(args.narration_file),
        bool(args.generated_narration_text),
        bool(args.generated_narration_file),
    ]
    if sum(provided) > 1:
        raise ValueError(
            "--script-text, --script-file, --narration-text, --narration-file, "
            "--generated-narration-text and --generated-narration-file are mutually exclusive"
        )
    if args.generated_narration_text:
        return args.generated_narration_text
    if args.generated_narration_file:
        return Path(args.generated_narration_file).expanduser().read_text(encoding="utf-8")
    if args.narration_text:
        return args.narration_text
    if args.narration_file:
        return Path(args.narration_file).expanduser().read_text(encoding="utf-8")
    if args.script_text:
        return args.script_text
    if args.script_file:
        return Path(args.script_file).expanduser().read_text(encoding="utf-8")
    return None


def _normalize_targets(values: Iterable[str]) -> List[str]:
    deduped: List[str] = []
    for value in values:
        target = str(value).strip()
        if target and target not in deduped:
            deduped.append(target)
    return deduped


def _disable_default_avatar(payload: Dict[str, Any]) -> None:
    """Make direct video generation B-roll first unless the user opts back in."""
    inputs = payload.setdefault("inputs", {})
    production = payload.setdefault("production", {})
    editing = payload.setdefault("editing", {})

    inputs.pop("avatar_path", None)
    inputs.pop("avatar_image_path", None)
    production.pop("avatar_clips", None)
    production["enable_avatar_generation"] = False
    editing["enable_avatar_timeline"] = False
    editing["avatar_opening_segments"] = 0
    editing["avatar_middle_segments"] = 0
    editing["avatar_ending_segments"] = 0


def _resolve_narration_source(args: argparse.Namespace, script_text: Optional[str]) -> str:
    if args.narration_source:
        return str(args.narration_source)
    if args.generated_narration_text or args.generated_narration_file:
        return NARRATION_SOURCE_GENERATED
    if script_text is not None:
        return NARRATION_SOURCE_USER
    return NARRATION_SOURCE_GENERATED


def _apply_copy_review(inputs: Dict[str, Any], *, source: str, approved: bool) -> None:
    required = source == NARRATION_SOURCE_GENERATED
    inputs["narration_source"] = source
    inputs["copy_review"] = {
        "required": required,
        "status": "approved" if approved or not required else "pending",
        "scope": "viewer_visible_narration",
        "note": (
            "User-provided narration does not require review."
            if not required
            else "Generated viewer-facing copy must be reviewed before rendering."
        ),
    }


def _apply_output_mode(payload: Dict[str, Any], *, runtime_mode: str, output_mode: str) -> None:
    outputs = payload.setdefault("outputs", {})
    jianying = outputs.setdefault("jianying", {})

    if output_mode == OUTPUT_MODE_VIDEO:
        _disable_default_avatar(payload)
        editing = payload.setdefault("editing", {})
        editing.setdefault("final_tail_frames", 2)
        editing.setdefault("final_tail_buffer_ms", 0)
        editing.setdefault("final_fade_out_ms", 450)
        payload.setdefault("production", {})["full_tts_audio_path"] = ""
        jianying["use_pyjianyingdraft"] = False
        outputs["targets"] = ["final_render"]
        outputs["preview_enabled"] = False
        outputs["final_render_enabled"] = False
        return

    jianying.setdefault("use_pyjianyingdraft", False)
    outputs["targets"] = ["jianying_draft"]
    outputs["preview_enabled"] = False
    outputs["final_render_enabled"] = False


def _validate_platform_support(payload: Dict[str, Any], *, output_mode: str, allow_unsupported_draft_adapter: bool) -> None:
    outputs = payload.get("outputs", {})
    jianying = outputs.get("jianying", {}) if isinstance(outputs, dict) else {}
    uses_real_jianying = bool(jianying.get("use_pyjianyingdraft", False))
    if (
        output_mode == OUTPUT_MODE_DRAFT
        and uses_real_jianying
        and platform.system() == "Darwin"
        and not allow_unsupported_draft_adapter
    ):
        raise RuntimeError(UNSUPPORTED_DRAFT_ADAPTER_MESSAGE)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare a local Video Director config")
    parser.add_argument("--mode", choices=sorted(TEMPLATE_BY_MODE.keys()), default="local")
    parser.add_argument(
        "--output-mode",
        choices=SUPPORTED_OUTPUT_MODES,
        default=OUTPUT_MODE_VIDEO,
        help="user-facing output type: editable draft or final video",
    )
    parser.add_argument("--template", help="override the default template path")
    parser.add_argument("--output", required=True, help="path to the generated config json")
    parser.add_argument("--job-id", help="override job_id")
    parser.add_argument("--script-text", help="inline script text")
    parser.add_argument("--script-file", help="text file used as inputs.script_text")
    parser.add_argument("--narration-text", help="viewer-facing narration/subtitle text")
    parser.add_argument("--narration-file", help="text file used as inputs.narration_text")
    parser.add_argument("--generated-narration-text", help="generated viewer-facing narration/subtitle text")
    parser.add_argument("--generated-narration-file", help="generated text file used as inputs.narration_text")
    parser.add_argument(
        "--narration-source",
        choices=SUPPORTED_NARRATION_SOURCES,
        help="source of viewer-facing narration; generated copy requires review",
    )
    parser.add_argument(
        "--copy-reviewed",
        action="store_true",
        help="mark generated viewer-facing narration as reviewed and approved",
    )
    parser.add_argument("--director-brief", help="planning guidance that should not be shown as subtitles")
    parser.add_argument("--topic-hint", help="override inputs.topic_hint")
    parser.add_argument("--materials-dir", help="override inputs.materials_dir")
    parser.add_argument("--avatar-path", help="override inputs.avatar_path")
    parser.add_argument("--avatar-image-path", help="override inputs.avatar_image_path")
    parser.add_argument("--full-tts-audio-path", help="override production.full_tts_audio_path")
    parser.add_argument("--full-tts-duration-ms", type=int, help="override production.full_tts_duration_ms")
    parser.add_argument("--drafts-root", help="override outputs.jianying.drafts_root")
    parser.add_argument("--output-root", help="override outputs.output_root")
    parser.add_argument(
        "--enable-draft-adapter",
        choices=("true", "false"),
        help="enable or disable the current editable-draft adapter",
    )
    parser.add_argument(
        "--allow-unsupported-draft-adapter",
        action="store_true",
        help="allow experimental draft config generation in unsupported environments",
    )
    parser.add_argument(
        "--target",
        action="append",
        default=[],
        help="repeatable override for outputs.targets",
    )
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="repeatable dotted override; VALUE is parsed as JSON when possible",
    )
    return parser.parse_args(argv)


def prepare_config(args: argparse.Namespace, *, skill_root: Optional[Path] = None) -> Dict[str, str]:
    root = skill_root or skill_root_from_runtime()
    default_template = DRAFT_TEMPLATE if args.output_mode == OUTPUT_MODE_DRAFT and args.mode == "local" else TEMPLATE_BY_MODE[args.mode]
    template_path = Path(args.template).expanduser() if args.template else root / default_template
    if not template_path.is_file():
        raise FileNotFoundError(f"template does not exist: {template_path}")

    payload = _read_json(template_path)
    script_text = _read_script_text(args)
    _apply_output_mode(payload, runtime_mode=args.mode, output_mode=args.output_mode)

    if args.job_id:
        payload["job_id"] = args.job_id

    inputs = payload.setdefault("inputs", {})
    production = payload.setdefault("production", {})
    outputs = payload.setdefault("outputs", {})
    jianying = outputs.setdefault("jianying", {})

    if script_text is not None:
        inputs["narration_text"] = script_text
    _apply_copy_review(
        inputs,
        source=_resolve_narration_source(args, script_text),
        approved=bool(args.copy_reviewed),
    )
    if args.director_brief:
        inputs["director_brief"] = args.director_brief
    if args.topic_hint:
        inputs["topic_hint"] = args.topic_hint
    if args.materials_dir:
        inputs["materials_dir"] = args.materials_dir
        production.pop("materials", None)
    if args.avatar_path:
        inputs["avatar_path"] = args.avatar_path
    if args.avatar_image_path:
        inputs["avatar_image_path"] = args.avatar_image_path
    if args.full_tts_audio_path:
        production["full_tts_audio_path"] = args.full_tts_audio_path
    if args.full_tts_duration_ms is not None:
        production["full_tts_duration_ms"] = args.full_tts_duration_ms
    if args.drafts_root:
        jianying["drafts_root"] = args.drafts_root
    if args.output_root:
        outputs["output_root"] = args.output_root
    if args.enable_draft_adapter is not None:
        jianying["use_pyjianyingdraft"] = args.enable_draft_adapter == "true"
    if args.target:
        outputs["targets"] = _normalize_targets(args.target)

    for override in args.set:
        if "=" not in override:
            raise ValueError(f"invalid override (expected KEY=VALUE): {override}")
        key, raw_value = override.split("=", 1)
        _set_nested(payload, key, _parse_scalar(raw_value))

    _validate_platform_support(
        payload,
        output_mode=args.output_mode,
        allow_unsupported_draft_adapter=args.allow_unsupported_draft_adapter,
    )

    output_path = Path(args.output).expanduser()
    _write_json(output_path, payload)
    return {
        "skill_root": str(root),
        "template": str(template_path),
        "output": str(output_path.resolve()),
        "mode": args.mode,
        "output_mode": args.output_mode,
    }


def main() -> int:
    args = parse_args()
    result = prepare_config(args)
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
