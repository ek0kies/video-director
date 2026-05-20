"""Environment doctor for the bundled Video Director runtime."""

from __future__ import annotations

import importlib
import importlib.metadata
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


REQUIRED_PYTHON = (3, 11)


def _check_python() -> Dict[str, Any]:
    current = {
        "major": sys.version_info.major,
        "minor": sys.version_info.minor,
        "micro": sys.version_info.micro,
    }
    ok = (current["major"], current["minor"]) >= REQUIRED_PYTHON
    return {
        "name": "python",
        "required": True,
        "status": "ok" if ok else "error",
        "expected": f"{REQUIRED_PYTHON[0]}.{REQUIRED_PYTHON[1]}",
        "actual": f"{current['major']}.{current['minor']}.{current['micro']}",
        "note": "Video Director runtime expects Python 3.11 or newer.",
    }


def _check_command(name: str, *, required: bool, note: str) -> Dict[str, Any]:
    path = shutil.which(name)
    status = "ok" if path else ("error" if required else "warning")
    return {
        "name": name,
        "required": required,
        "status": status,
        "path": path or "",
        "note": note,
    }


def _check_package(import_name: str, *, dist_name: Optional[str], required: bool, note: str) -> Dict[str, Any]:
    try:
        module = importlib.import_module(import_name)
        version = importlib.metadata.version(dist_name or import_name)
        status = "ok"
        module_path = str(getattr(module, "__file__", "") or "")
    except Exception as exc:  # noqa: BLE001
        version = ""
        module_path = ""
        status = "error" if required else "skipped"
        note = f"{note} missing={exc!r}" if required else f"{note} optional_missing={exc!r}"
    return {
        "name": import_name,
        "required": required,
        "status": status,
        "version": version,
        "module_path": module_path,
        "note": note,
    }


def _config_enabled(config: Dict[str, Any], path: List[str], default: Any = None) -> Any:
    current: Any = config
    for key in path:
        if not isinstance(current, dict):
            return default
        current = current.get(key, default)
    return current


def run_doctor(*, config: Optional[Dict[str, Any]], cwd: Path) -> Dict[str, Any]:
    cfg = config or {}
    checks: List[Dict[str, Any]] = []
    checks.append(_check_python())
    checks.append(
        _check_command(
            "ffprobe",
            required=False,
            note="Preferred audio-duration probe. Without it Video Director falls back to Python wave parsing.",
        )
    )
    checks.append(
        _check_command(
            "ffmpeg",
            required=bool("final_render" in _config_enabled(cfg, ["outputs", "targets"], [])),
            note="Required for direct mp4 rendering.",
        )
    )
    checks.append(
        _check_package(
            "PIL",
            dist_name="Pillow",
            required=bool(_config_enabled(cfg, ["outputs", "final_render", "burn_subtitles"], True)),
            note="Required when subtitles are burned into rendered mp4 output.",
        )
    )

    use_pyjianyingdraft = bool(_config_enabled(cfg, ["outputs", "jianying", "use_pyjianyingdraft"], False))
    checks.append(
        _check_package(
            "pyJianYingDraft",
            dist_name="pyjianyingdraft",
            required=use_pyjianyingdraft,
            note="Required only when outputs.jianying.use_pyjianyingdraft=true.",
        )
    )

    audio_delivery_enabled = bool(_config_enabled(cfg, ["production", "audio_delivery", "enabled"], False))
    provider = str(_config_enabled(cfg, ["production", "audio_delivery", "provider"], "tos") or "tos").strip().lower()
    if audio_delivery_enabled and provider != "tos":
        checks.append(
            {
                "name": "audio_delivery.provider",
                "required": True,
                "status": "error",
                "actual": provider,
                "note": "Video Director now only supports provider=tos.",
            }
        )
    checks.append(
        _check_package(
            "tos",
            dist_name="tos",
            required=audio_delivery_enabled,
            note="Required only when production.audio_delivery.enabled=true.",
        )
    )

    if audio_delivery_enabled and provider == "tos":
        delivery = _config_enabled(cfg, ["production", "audio_delivery"], {}) or {}
        required_fields = ("endpoint", "region", "access_key", "secret_key", "bucket")
        missing_fields = [field for field in required_fields if not str(delivery.get(field, "")).strip()]
        checks.append(
            {
                "name": "audio_delivery.tos_config",
                "required": True,
                "status": "ok" if not missing_fields else "error",
                "missing_fields": missing_fields,
                "note": "TOS upload needs endpoint/region/access_key/secret_key/bucket.",
            }
        )

    overall_status = "ok"
    if any(check["status"] == "error" for check in checks):
        overall_status = "error"
    elif any(check["status"] == "warning" for check in checks):
        overall_status = "warning"

    return {
        "status": overall_status,
        "cwd": str(cwd),
        "checks": checks,
        "recommended_command": "bash scripts/video-director.sh doctor <config>",
    }
