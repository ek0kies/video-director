"""Build material-aware copy planning reports for Video Director."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


VIDEO_MEDIA_TYPES = {"video", "movie", "clip"}
DEFAULT_CHARS_PER_SECOND = 8.0
DEFAULT_SEGMENT_MS = 3000


def _resolve_path(raw: str, cwd: Path) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = (cwd / path).resolve()
    return str(path)


def _read_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"json root must be an object: {path}")
    return payload


def _split_sentences(text: str) -> List[str]:
    parts = re.split(r"[。！？!?；;\n]+", str(text or ""))
    return [part.strip() for part in parts if part.strip()]


def _visible_chars(text: str) -> int:
    return len(re.sub(r"\s+", "", str(text or "")))


def _optional_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_asset(item: Dict[str, Any], *, cwd: Path, index: int) -> Dict[str, Any]:
    metadata = item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {}
    tags = item.get("tags", [])
    if not isinstance(tags, list):
        tags = []
    return {
        "asset_id": str(item.get("asset_id") or f"asset-{index:03d}").strip(),
        "path": _resolve_path(str(item.get("path", "")).strip(), cwd),
        "media_type": str(item.get("media_type", "video") or "video").strip().lower(),
        "duration_ms": _optional_int(item.get("duration_ms")),
        "tags": [str(tag).strip() for tag in tags if str(tag).strip()],
        "description": str(item.get("description") or metadata.get("description") or "").strip(),
        "scene_type": str(item.get("scene_type") or metadata.get("scene_type") or "").strip(),
        "mood": str(item.get("mood") or metadata.get("mood") or "").strip(),
        "best_for": item.get("best_for", metadata.get("best_for", [])),
    }


def _assets_from_manifest(path: str, *, cwd: Path) -> List[Dict[str, Any]]:
    if not path:
        return []
    payload = _read_json(Path(_resolve_path(path, cwd)))
    items = payload.get("assets", [])
    if not isinstance(items, list):
        raise ValueError("assets manifest field 'assets' must be a list")
    return [_normalize_asset(item, cwd=cwd, index=index) for index, item in enumerate(items, start=1) if isinstance(item, dict)]


def _assets_from_materials(items: Iterable[Any], *, cwd: Path) -> List[Dict[str, Any]]:
    assets: List[Dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        if isinstance(item, dict):
            assets.append(_normalize_asset(item, cwd=cwd, index=index))
    return assets


def _estimate_requested_duration_ms(config: Dict[str, Any]) -> Dict[str, Any]:
    inputs = config.get("inputs", {}) if isinstance(config.get("inputs"), dict) else {}
    production = config.get("production", {}) if isinstance(config.get("production"), dict) else {}
    editing = config.get("editing", {}) if isinstance(config.get("editing"), dict) else {}
    explicit = _optional_int(production.get("full_tts_duration_ms"))
    if explicit and explicit > 0:
        return {"duration_ms": explicit, "source": "production.full_tts_duration_ms"}
    text = str(inputs.get("narration_text") or inputs.get("script_text") or "").strip()
    chars_per_second = float(editing.get("chars_per_second", DEFAULT_CHARS_PER_SECOND) or DEFAULT_CHARS_PER_SECOND)
    estimated = int(math.ceil(max(_visible_chars(text), 1) / max(chars_per_second, 0.1) * 1000))
    return {"duration_ms": estimated, "source": "text_length_estimate"}


def build_material_copy_plan(config: Dict[str, Any], *, cwd: Path) -> Dict[str, Any]:
    """Return a report that constrains copywriting to known material capacity."""
    inputs = config.get("inputs", {}) if isinstance(config.get("inputs"), dict) else {}
    production = config.get("production", {}) if isinstance(config.get("production"), dict) else {}
    editing = config.get("editing", {}) if isinstance(config.get("editing"), dict) else {}

    assets = _assets_from_manifest(str(production.get("assets_manifest_path", "")).strip(), cwd=cwd)
    if not assets:
        assets = _assets_from_materials(production.get("materials", []), cwd=cwd)

    max_material_reuse = max(int(editing.get("max_material_reuse", 2) or 2), 1)
    video_assets = [asset for asset in assets if asset.get("media_type") in VIDEO_MEDIA_TYPES]
    known_video_assets = [asset for asset in video_assets if asset.get("duration_ms")]
    image_assets = [asset for asset in assets if asset.get("media_type") not in VIDEO_MEDIA_TYPES]
    known_video_duration_ms = sum(max(int(asset["duration_ms"]), 1) for asset in known_video_assets)
    reusable_video_duration_ms = known_video_duration_ms * max_material_reuse
    requested = _estimate_requested_duration_ms(config)
    requested_ms = int(requested["duration_ms"])

    if known_video_assets:
        suggested_max_ms = reusable_video_duration_ms
        status = "fits" if requested_ms <= suggested_max_ms else "needs_shorter_copy_or_more_material"
    elif image_assets:
        suggested_max_ms = max(requested_ms, DEFAULT_SEGMENT_MS * max(len(image_assets), 1))
        status = "image_based"
    else:
        suggested_max_ms = 0
        status = "no_known_visual_capacity"

    suggested_sentence_count = max(1, min(len(assets) * max_material_reuse if assets else 1, math.ceil(suggested_max_ms / DEFAULT_SEGMENT_MS)))
    segment_budget_ms = max(int(suggested_max_ms / suggested_sentence_count), 1) if suggested_sentence_count else 0
    current_copy = str(inputs.get("narration_text") or inputs.get("script_text") or "").strip()

    return {
        "status": status,
        "job_id": str(config.get("job_id") or inputs.get("job_id") or ""),
        "material_summary": {
            "asset_count": len(assets),
            "video_count": len(video_assets),
            "known_video_duration_ms": known_video_duration_ms,
            "max_material_reuse": max_material_reuse,
            "reusable_video_duration_ms": reusable_video_duration_ms,
            "image_count": len(image_assets),
        },
        "requested_duration": requested,
        "recommended_copy_constraints": {
            "max_narration_duration_ms": suggested_max_ms,
            "suggested_sentence_count": suggested_sentence_count,
            "suggested_segment_budget_ms": segment_budget_ms,
            "must_not_pad_with_black": True,
            "must_not_silently_stretch_material": True,
        },
        "current_copy": {
            "sentence_count": len(_split_sentences(current_copy)),
            "visible_chars": _visible_chars(current_copy),
            "needs_revision": status == "needs_shorter_copy_or_more_material",
        },
        "material_cues": [
            {
                "asset_id": asset["asset_id"],
                "media_type": asset["media_type"],
                "duration_ms": asset.get("duration_ms"),
                "tags": asset.get("tags", []),
                "description": asset.get("description", ""),
                "scene_type": asset.get("scene_type", ""),
                "best_for": asset.get("best_for", []),
            }
            for asset in assets
        ],
        "recommended_next_step": (
            "Generate or revise narration so it stays within max_narration_duration_ms and only claims visible material."
            if status != "fits"
            else "Current requested duration fits known material capacity; proceed to copy review or dry-run."
        ),
    }


def write_material_copy_plan(report: Dict[str, Any], output_path: Optional[Path]) -> None:
    if output_path is None:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
