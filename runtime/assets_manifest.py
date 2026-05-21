"""Offline assets-manifest builder for Agent-provided or local media input."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


class AssetAnalysisError(ValueError):
    """Raised when a media directory cannot be converted into a manifest."""


VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".bmp"}


def _tokens_from_path(path: Path) -> List[str]:
    raw = " ".join(path.with_suffix("").parts[-3:]).replace("-", " ").replace("_", " ")
    return [part.strip() for part in raw.split() if part.strip()][:8]


def _media_files(root: Path) -> Iterable[Path]:
    exts = VIDEO_EXTS | IMAGE_EXTS
    return sorted(path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in exts)


def _probe_video_duration_ms(path: Path) -> Optional[int]:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    raw = (result.stdout or "").strip()
    if not raw:
        return None
    try:
        return max(int(round(float(raw) * 1000)), 1)
    except ValueError:
        return None


def build_assets_manifest(*, materials_dir: Path, cwd: Path, output_path: Path, limit: int = 0) -> Dict[str, Any]:
    """Write a deterministic manifest from local media paths.

    This helper is deliberately heuristic only. In Agent usage, the Agent can
    inspect media with its own model and overwrite descriptions/tags before run.
    """
    root = materials_dir.expanduser()
    if not root.is_absolute():
        root = (cwd / root).resolve()
    if not root.is_dir():
        raise AssetAnalysisError(f"materials directory not found: {root}")

    files = list(_media_files(root))
    if limit > 0:
        files = files[:limit]
    if not files:
        raise AssetAnalysisError(f"no supported image/video files under: {root}")

    assets: List[Dict[str, Any]] = []
    for index, path in enumerate(files, start=1):
        media_type = "video" if path.suffix.lower() in VIDEO_EXTS else "image"
        relative = path.relative_to(root)
        item = {
            "asset_id": f"asset-{index:03d}",
            "path": str(path.resolve()),
            "media_type": media_type,
            "tags": _tokens_from_path(relative),
            "description": "",
            "scene_type": "",
            "mood": "",
            "best_for": [],
            "metadata": {
                "source_root": str(root),
                "relative_path": str(relative),
                "generated_by": "filename_heuristic",
            },
        }
        if media_type == "video":
            duration_ms = _probe_video_duration_ms(path)
            if duration_ms is not None:
                item["duration_ms"] = duration_ms
        assets.append(item)

    payload: Dict[str, Any] = {"version": "1.0", "assets": assets}
    output = output_path.expanduser()
    if not output.is_absolute():
        output = (cwd / output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload
