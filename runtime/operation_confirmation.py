"""Execution-parameter confirmation gate for Video Director."""

from __future__ import annotations

from typing import Any, Dict, List


APPROVED_STATUS = "approved"
PENDING_STATUS = "pending"


class OperationConfirmationError(RuntimeError):
    """Raised when a config has not been approved for execution."""


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _targets(outputs: Dict[str, Any]) -> List[str]:
    raw = outputs.get("targets", [])
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    text = str(raw or "").strip()
    return [text] if text else []


def _materials_source(inputs: Dict[str, Any], production: Dict[str, Any]) -> Dict[str, Any]:
    manifest_path = str(production.get("assets_manifest_path") or "").strip()
    materials_dir = str(inputs.get("materials_dir") or "").strip()
    materials = production.get("materials", [])
    if manifest_path:
        return {"type": "assets_manifest", "path": manifest_path}
    if materials_dir:
        return {"type": "materials_dir", "path": materials_dir}
    if isinstance(materials, list) and materials:
        return {"type": "inline_materials", "count": len(materials)}
    return {"type": "unspecified"}


def _output_mode(targets: List[str]) -> str:
    if "jianying_draft" in targets:
        return "draft"
    if "final_render" in targets:
        return "video"
    return "custom"


def _resolution_parts(raw: Any) -> tuple[int, int]:
    text = str(raw or "").strip().lower()
    if "x" not in text:
        return 0, 0
    width, height = text.split("x", 1)
    try:
        return int(width.strip()), int(height.strip())
    except ValueError:
        return 0, 0


def _orientation(width: int, height: int) -> str:
    if width <= 0 or height <= 0:
        return "unspecified"
    if height > width:
        return "portrait"
    if width > height:
        return "landscape"
    return "square"


def _aspect_ratio(width: int, height: int) -> str:
    if width <= 0 or height <= 0:
        return "unspecified"
    smaller = min(width, height)
    larger = max(width, height)
    if smaller == 0:
        return "unspecified"
    if larger * 9 == smaller * 16:
        return "9:16" if height >= width else "16:9"
    if width == height:
        return "1:1"
    return f"{width}:{height}"


def _style_policy(inputs: Dict[str, Any]) -> Dict[str, Any]:
    requested = str(inputs.get("style") or inputs.get("visual_style") or "").strip()
    return {
        "requested_style": requested,
        "default_policy": "material_first_clean_edit",
        "ask_required": bool(requested),
        "note": (
            "Use the requested style as an execution parameter."
            if requested
            else "Do not ask for style by default; use a material-first clean edit unless the user requests strong styling."
        ),
    }


def build_operation_summary(config: Dict[str, Any]) -> Dict[str, Any]:
    """Return the user-confirmable execution parameters for a config."""

    inputs = _as_dict(config.get("inputs"))
    production = _as_dict(config.get("production"))
    outputs = _as_dict(config.get("outputs"))
    editing = _as_dict(config.get("editing"))
    final_render = _as_dict(outputs.get("final_render"))
    jianying = _as_dict(outputs.get("jianying"))
    copy_review = _as_dict(inputs.get("copy_review"))
    targets = _targets(outputs)
    mode = _output_mode(targets)
    width, height = _resolution_parts(editing.get("resolution"))

    return {
        "job_id": str(config.get("job_id") or production.get("job_id") or inputs.get("job_id") or "").strip(),
        "output_mode": mode,
        "targets": targets,
        "output_root": str(outputs.get("output_root") or "output/video_director"),
        "materials_source": _materials_source(inputs, production),
        "duration_ms": production.get("full_tts_duration_ms"),
        "visual": {
            "resolution": str(editing.get("resolution") or "").strip(),
            "orientation": _orientation(width, height),
            "aspect_ratio": _aspect_ratio(width, height),
            "orientation_requires_confirmation": True,
        },
        "style": _style_policy(inputs),
        "narration": {
            "source": str(inputs.get("narration_source") or "user_provided").strip(),
            "has_viewer_facing_text": bool(str(inputs.get("narration_text") or inputs.get("script_text") or "").strip()),
            "copy_review_required": bool(copy_review.get("required", False)),
            "copy_review_status": str(copy_review.get("status") or "").strip(),
        },
        "audio": {
            "full_tts_audio_path": str(production.get("full_tts_audio_path") or "").strip(),
            "source_audio_policy": str(inputs.get("source_audio_policy") or "runtime_default").strip(),
            "bgm_path": str(inputs.get("bgm_path") or production.get("bgm_path") or "").strip(),
        },
        "subtitles": {
            "burned_in": bool(final_render.get("burn_subtitles", False)) if mode == "video" else bool(_as_dict(jianying.get("subtitles")).get("enabled", False)),
            "sidecar_srt": bool(final_render.get("emit_sidecar_srt", False)),
        },
        "draft_adapter": {
            "enabled": "jianying_draft" in targets,
            "adapter": "jianying" if "jianying_draft" in targets else "",
            "drafts_root": str(jianying.get("drafts_root") or "").strip(),
        },
        "cloud": {
            "enabled": str(production.get("mode") or "").strip().lower() == "cloud",
            "tts_enabled": bool(production.get("enable_tts_generation", False)),
            "avatar_enabled": bool(production.get("enable_avatar_generation", False)),
        },
    }


def apply_operation_confirmation(config: Dict[str, Any], *, approved: bool, note: str = "") -> None:
    """Write the operation confirmation state and current parameter summary."""

    config["operation_confirmation"] = {
        "required": True,
        "status": APPROVED_STATUS if approved else PENDING_STATUS,
        "scope": "execution_parameters",
        "note": note
        or (
            "Execution parameters were confirmed by the user."
            if approved
            else "Show these execution parameters to the user and wait for explicit confirmation before running."
        ),
        "summary": build_operation_summary(config),
    }


def ensure_operation_confirmed(config: Dict[str, Any]) -> None:
    """Raise unless the user-facing execution parameters are approved."""

    confirmation = _as_dict(config.get("operation_confirmation"))
    if not confirmation:
        raise OperationConfirmationError(
            "operation confirmation is required before running; regenerate the config after user confirmation with --operation-confirmed"
        )
    required = bool(confirmation.get("required", True))
    status = str(confirmation.get("status") or PENDING_STATUS).strip().lower()
    if required and status != APPROVED_STATUS:
        raise OperationConfirmationError(
            "operation confirmation is pending; show operation_confirmation.summary to the user, then regenerate the config with --operation-confirmed"
        )
