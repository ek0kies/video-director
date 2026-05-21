#!/usr/bin/env python3
"""Cross-platform command router for Video Director."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable, List, Optional, Sequence, Tuple


REQUIRED_PYTHON = (3, 10)
MODES = {"bundle_only", "local", "cloud"}


def _script_root() -> Path:
    return Path(__file__).resolve().parent


def _skill_root() -> Path:
    return _script_root().parent


if str(_skill_root()) not in sys.path:
    sys.path.insert(0, str(_skill_root()))

from runtime.assets_manifest import AssetAnalysisError, build_assets_manifest  # noqa: E402
from runtime.config_prepare import prepare_config  # noqa: E402
from runtime.copy_review import build_copy_review_report, write_copy_review_report  # noqa: E402
from runtime.doctor import run_doctor  # noqa: E402
from runtime.production import ProductionConfigError  # noqa: E402
from runtime.summarize import summarize_run  # noqa: E402
from runtime.workflow import VideoDirectorWorkflow  # noqa: E402


def _ensure_python_version() -> None:
    if sys.version_info >= REQUIRED_PYTHON:
        return
    required = ".".join(str(part) for part in REQUIRED_PYTHON)
    actual = ".".join(str(part) for part in sys.version_info[:3])
    raise SystemExit(f"error: Python {required}+ is required, current interpreter is {actual}")


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _resolve_config_path(raw: str, *, workspace_root: Path) -> Path:
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path
    cwd_path = (Path.cwd() / path).resolve()
    if cwd_path.is_file():
        return cwd_path
    return (workspace_root / path).resolve()


def _extract_flag_value(args: Sequence[str], flag: str) -> Tuple[Optional[str], List[str]]:
    result: List[str] = []
    found: Optional[str] = None
    skip_next = False
    for index, value in enumerate(args):
        if skip_next:
            skip_next = False
            continue
        if value == flag:
            if index + 1 >= len(args):
                raise SystemExit(f"error: {flag} requires a value")
            found = args[index + 1]
            skip_next = True
            continue
        prefix = flag + "="
        if value.startswith(prefix):
            found = value[len(prefix) :]
            continue
        result.append(value)
    return found, result


def _output_mode(args: Iterable[str]) -> str:
    previous = ""
    for arg in args:
        if previous == "--output-mode":
            return arg
        if arg.startswith("--output-mode="):
            return arg.split("=", 1)[1]
        previous = arg
    return "video"


def _default_config_output(mode: str, output_mode: str, workspace_root: Path) -> Path:
    if mode == "bundle_only":
        name = "video-director.bundle.video.local.json" if output_mode == "video" else "video-director.bundle.local.json"
    elif mode == "cloud":
        name = "video-director.cloud.video.local.json" if output_mode == "video" else "video-director.cloud.local.json"
    else:
        name = "video-director.video.local.json" if output_mode == "video" else "video-director.draft.local.json"
    return _workspace_internal_root(workspace_root) / "configs" / name


def _workspace_root() -> Path:
    return Path(os.environ.get("VIDEO_DIRECTOR_WORKSPACE_ROOT", str(Path.cwd()))).expanduser().resolve()


def _workspace_internal_root(workspace_root: Path) -> Path:
    return Path(os.environ.get("VIDEO_DIRECTOR_WORK_DIR", str(workspace_root / ".video-director"))).expanduser().resolve()


def _default_demo_root() -> Path:
    raw = os.environ.get("VIDEO_DIRECTOR_DEMO_ROOT")
    if raw:
        return Path(raw).expanduser().resolve()
    return Path(tempfile.mkdtemp(prefix="video-director-demo-")).resolve() / "contest"


def _cmd_analyze(args: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description="Build an assets manifest from a media directory")
    parser.add_argument("--materials-dir", required=True, help="directory containing image/video assets")
    parser.add_argument("--output", required=True, help="manifest JSON output path")
    parser.add_argument("--limit", type=int, default=0, help="optional max assets to analyze")
    parsed = parser.parse_args(args)
    workspace_root = _workspace_root()
    output_path = Path(parsed.output).expanduser()
    if not output_path.is_absolute():
        output_path = (workspace_root / output_path).resolve()

    try:
        payload = build_assets_manifest(
            materials_dir=Path(parsed.materials_dir).expanduser(),
            cwd=workspace_root,
            output_path=output_path,
            limit=max(int(parsed.limit or 0), 0),
        )
    except (AssetAnalysisError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "skill_root": str(_skill_root()),
                "output": str(output_path),
                "generated_by": "analyze_assets:filename_heuristic",
                "asset_count": len(payload.get("assets", [])),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _cmd_config(args: Sequence[str]) -> int:
    mode = "local"
    remaining = list(args)
    if remaining and remaining[0] in MODES:
        mode = remaining.pop(0)

    workspace_root = _workspace_root()
    output, remaining = _extract_flag_value(remaining, "--output")
    output = output or os.environ.get("VIDEO_DIRECTOR_CONFIG_OUTPUT")
    output_path = Path(output).expanduser() if output else _default_config_output(mode, _output_mode(remaining), workspace_root)
    if not output_path.is_absolute():
        output_path = (workspace_root / output_path).resolve()

    from runtime.config_prepare import parse_args as parse_config_args

    parsed = parse_config_args(["--mode", mode, "--output", str(output_path), *remaining])
    try:
        result = prepare_config(parsed, skill_root=_skill_root())
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _cmd_doctor(args: Sequence[str]) -> int:
    if args and args[0] in {"-h", "--help"}:
        print("usage: video_director.py doctor [config-path]")
        return 0
    workspace_root = _workspace_root()
    config = args[0] if args else str(_skill_root() / "runtime" / "templates" / "video.template.json")
    config_path = _resolve_config_path(config, workspace_root=workspace_root)
    if not config_path.is_file():
        raise SystemExit(f"error: config not found: {config_path}")
    result = run_doctor(config=_read_json(config_path), cwd=workspace_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] != "error" else 1


def _cmd_run(args: Sequence[str]) -> int:
    if args and args[0] in {"-h", "--help"}:
        print("usage: video_director.py run <config-path> [--dry-run]")
        return 0
    parser = argparse.ArgumentParser(description="Run the Video Director pipeline")
    parser.add_argument("config", help="path to the Video Director config")
    parser.add_argument("--dry-run", action="store_true", help="write plans without rendering final artifacts")
    parsed = parser.parse_args(args)

    workspace_root = _workspace_root()
    config_path = _resolve_config_path(parsed.config, workspace_root=workspace_root)
    if not config_path.is_file():
        raise SystemExit(f"error: config not found: {config_path}")
    workflow = VideoDirectorWorkflow(_read_json(config_path), cwd=workspace_root, dry_run=bool(parsed.dry_run))
    try:
        result = workflow.run()
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _cmd_review_copy(args: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description="Build a viewer-facing copy review report")
    parser.add_argument("config", help="path to the Video Director config")
    parser.add_argument("--output", help="optional report JSON output path")
    parsed = parser.parse_args(args)

    workspace_root = _workspace_root()
    config_path = _resolve_config_path(parsed.config, workspace_root=workspace_root)
    if not config_path.is_file():
        raise SystemExit(f"error: config not found: {config_path}")
    output_path = Path(parsed.output).expanduser() if parsed.output else None
    if output_path is not None and not output_path.is_absolute():
        output_path = (workspace_root / output_path).resolve()
    report = build_copy_review_report(_read_json(config_path))
    write_copy_review_report(report, output_path)
    if output_path is not None:
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "output": str(output_path),
                    "flag_count": len(report.get("flags", [])),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


def _cmd_summarize(args: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description="Summarize a Video Director run")
    parser.add_argument("source", help="path to latest_run.json or run directory")
    parser.add_argument("--verbose", action="store_true", help="include internal debug artifacts")
    parsed = parser.parse_args(args)
    print(json.dumps(summarize_run(Path(parsed.source), verbose=bool(parsed.verbose)), ensure_ascii=False, indent=2))
    return 0


def _require_ffmpeg() -> None:
    result = subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    if result.returncode != 0:
        raise SystemExit("error: ffmpeg is required to generate demo media and render mp4 output")


def _run_checked(args: Sequence[str]) -> None:
    subprocess.run(args, check=True)


def _cmd_demo(args: Sequence[str]) -> int:
    if args:
        raise SystemExit("usage: video_director.py demo")
    _require_ffmpeg()
    demo_root = _default_demo_root()
    materials_dir = demo_root / "materials"
    output_root = demo_root / "output"
    manifest_path = demo_root / "assets_manifest.json"
    config_path = demo_root / "video-director.contest-demo.local.json"
    narration_path = demo_root / "narration.txt"

    materials_dir.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(parents=True, exist_ok=True)

    for color, name in (
        ("0x1b5e20", "opening_green.mp4"),
        ("0x1565c0", "workflow_blue.mp4"),
        ("0x6a1b9a", "result_purple.mp4"),
    ):
        _run_checked(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color=c={color}:s=1080x1920:d=3:r=30",
                "-pix_fmt",
                "yuv420p",
                str(materials_dir / name),
            ]
        )

    narration_path.write_text(
        "\n".join(
            [
                "Video Director turns local media into a short vertical mp4.",
                "It first inventories materials, then builds a narration-first timeline.",
                "The final step renders a shareable video with burned-in subtitles.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    build_assets_manifest(materials_dir=materials_dir, cwd=_skill_root(), output_path=manifest_path)
    config_args = [
        "--mode",
        "local",
        "--output-mode",
        "video",
        "--output",
        str(config_path),
        "--job-id",
        "contest-demo",
        "--narration-file",
        str(narration_path),
        "--director-brief",
        "Contest demo: show the local media to mp4 workflow.",
        "--full-tts-duration-ms",
        "9000",
        "--output-root",
        str(output_root),
        "--set",
        f'production.assets_manifest_path="{manifest_path}"',
        "--set",
        'outputs.final_render.output_name="contest-demo.mp4"',
        "--set",
        "editing.min_segment_ms=1000",
        "--set",
        "editing.chars_per_second=16",
    ]
    from runtime.config_prepare import parse_args as parse_config_args

    prepare_config(parse_config_args(config_args), skill_root=_skill_root())

    print("Demo assets ready.")
    print(f"config: {config_path}")
    print(f"manifest: {manifest_path}")
    print(f"materials: {materials_dir}")
    print("\nUnix/macOS:")
    print(f"  bash scripts/doctor.sh {config_path}")
    print(f"  bash scripts/run.sh run {config_path} --dry-run")
    print(f"  bash scripts/run.sh run {config_path}")
    print("\nWindows:")
    print(f"  scripts\\video-director.cmd doctor {config_path}")
    print(f"  scripts\\video-director.cmd run {config_path} --dry-run")
    print(f"  scripts\\video-director.cmd run {config_path}")
    return 0


def _usage() -> str:
    return """usage: video_director.py <command> [args]

commands:
  analyze    Build an assets manifest from media files
  config     Generate a local config
  review-copy  Build a viewer-facing copy review report
  doctor     Check runtime prerequisites
  run        Dry-run or render the pipeline
  summarize  Summarize a run; pass --verbose for internal artifacts
  demo       Generate contest demo assets and config
"""


def main(argv: Sequence[str]) -> int:
    _ensure_python_version()
    if not argv or argv[0] in {"-h", "--help", "help"}:
        print(_usage())
        return 0

    command, args = argv[0], argv[1:]
    if command == "analyze":
        return _cmd_analyze(args)
    if command == "config":
        return _cmd_config(args)
    if command == "review-copy":
        return _cmd_review_copy(args)
    if command == "doctor":
        return _cmd_doctor(args)
    if command == "run":
        return _cmd_run(args)
    if command == "summarize":
        return _cmd_summarize(args)
    if command == "demo":
        return _cmd_demo(args)

    print(_usage(), file=sys.stderr)
    raise SystemExit(f"error: unknown command: {command}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
