"""Production bundle loading for Video Director."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

from .models import AudioClip, AvatarClip, MaterialAsset, ProductionBundle


class ProductionConfigError(ValueError):
    """Raised when the production bundle configuration is invalid."""


VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".bmp"}


def _is_remote_path(raw: str) -> bool:
    parsed = urlparse(raw)
    return parsed.scheme in {"http", "https"}


def _resolve_path(raw: str, cwd: Path) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    if _is_remote_path(text):
        return text
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = (cwd / path).resolve()
    return str(path)


def _read_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _normalize_tags(tags: Iterable[Any]) -> List[str]:
    return [str(item).strip() for item in tags if str(item).strip()]


def _tokenize_filename(path: Path) -> List[str]:
    raw = path.stem.replace("-", " ").replace("_", " ")
    parts = [part.strip() for part in raw.split() if part.strip()]
    return parts[:6]


class ProductionBundleBuilder:
    """Build a normalized production bundle from a JSON config file."""

    def __init__(self, cwd: Path):
        self.cwd = cwd

    def build(self, config: Dict[str, Any]) -> ProductionBundle:
        inputs = config.get("inputs", {})
        production = config.get("production", {})

        script_text = str(inputs.get("narration_text") or inputs.get("script_text", "")).strip()
        if not script_text:
            raise ProductionConfigError("inputs.narration_text is required")

        job_id = str(
            config.get("job_id")
            or production.get("job_id")
            or inputs.get("job_id")
            or "video-director-job"
        ).strip()

        understanding = self._load_understanding(production)
        materials = self._load_materials_from_manifest(production)
        if not materials:
            materials = self._load_materials(production.get("materials", []))
        if not materials:
            materials = self._scan_materials_dir(inputs)
        tts_clips = self._load_tts_clips(production.get("tts_clips", []))
        avatar_clips = self._load_avatar_clips(production.get("avatar_clips", []))
        avatar_image_path = str(inputs.get("avatar_image_path") or inputs.get("avatar_path") or "").strip()

        return ProductionBundle(
            job_id=job_id,
            script_text=script_text,
            topic_hint=str(inputs.get("topic_hint", "")).strip(),
            avatar_image_path=_resolve_path(avatar_image_path, self.cwd),
            full_tts_audio_path=_resolve_path(str(production.get("full_tts_audio_path", "")).strip(), self.cwd),
            full_tts_duration_ms=self._optional_int(production.get("full_tts_duration_ms")),
            materials=materials,
            tts_clips=tts_clips,
            avatar_clips=avatar_clips,
            understanding=understanding,
            metadata={
                "source": str(production.get("mode", "config") or "config"),
                "materials_count": len(materials),
                "tts_clip_count": len(tts_clips),
                "avatar_clip_count": len(avatar_clips),
            },
        )

    def _load_understanding(self, production: Dict[str, Any]) -> Dict[str, Any]:
        path = str(production.get("understanding_path", "")).strip()
        if path:
            return _read_json(Path(_resolve_path(path, self.cwd)))
        value = production.get("understanding", {})
        if isinstance(value, dict):
            return value
        return {}

    def _load_materials_from_manifest(self, production: Dict[str, Any]) -> List[MaterialAsset]:
        path = str(production.get("assets_manifest_path", "")).strip()
        if not path:
            return []
        payload = _read_json(Path(_resolve_path(path, self.cwd)))
        items = payload.get("assets", [])
        if not isinstance(items, list):
            raise ProductionConfigError("assets manifest field 'assets' must be a list")
        materials: List[MaterialAsset] = []
        for index, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                raise ProductionConfigError(f"assets[{index}] must be an object")
            asset_id = str(item.get("asset_id") or f"asset-{index:03d}").strip()
            path_value = str(item.get("path", "")).strip()
            if not path_value:
                raise ProductionConfigError(f"assets[{index}].path is required")
            metadata = item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {}
            for key in ("description", "scene_type", "mood", "best_for"):
                if key in item and key not in metadata:
                    metadata[key] = item[key]
            materials.append(
                MaterialAsset(
                    asset_id=asset_id,
                    path=_resolve_path(path_value, self.cwd),
                    media_type=str(item.get("media_type", "video")).strip() or "video",
                    duration_ms=self._optional_int(item.get("duration_ms")),
                    tags=_normalize_tags(item.get("tags", [])),
                    metadata=metadata,
                )
            )
        return materials

    def _load_materials(self, items: Iterable[Any]) -> List[MaterialAsset]:
        materials: List[MaterialAsset] = []
        for index, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                raise ProductionConfigError(f"production.materials[{index}] must be an object")
            asset_id = str(item.get("asset_id") or f"material-{index:02d}").strip()
            path = _resolve_path(str(item.get("path", "")).strip(), self.cwd)
            if not path:
                raise ProductionConfigError(f"production.materials[{index}].path is required")
            materials.append(
                MaterialAsset(
                    asset_id=asset_id,
                    path=path,
                    media_type=str(item.get("media_type", "video")).strip() or "video",
                    duration_ms=self._optional_int(item.get("duration_ms")),
                    tags=_normalize_tags(item.get("tags", [])),
                    metadata=item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {},
                )
            )
        return materials

    def _scan_materials_dir(self, inputs: Dict[str, Any]) -> List[MaterialAsset]:
        materials_dir_raw = str(inputs.get("materials_dir", "")).strip()
        if not materials_dir_raw:
            raise ProductionConfigError("inputs.materials_dir is required when production.materials is empty")
        materials_dir = Path(_resolve_path(materials_dir_raw, self.cwd))
        if not materials_dir.is_dir():
            raise ProductionConfigError(f"inputs.materials_dir not found: {materials_dir}")

        materials: List[MaterialAsset] = []
        media_files = sorted(
            path
            for path in materials_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in (VIDEO_EXTS | IMAGE_EXTS)
        )
        for index, path in enumerate(media_files, start=1):
            media_type = "video" if path.suffix.lower() in VIDEO_EXTS else "image"
            relative_path = str(path.relative_to(materials_dir))
            materials.append(
                MaterialAsset(
                    asset_id=f"material-{index:02d}",
                    path=str(path.resolve()),
                    media_type=media_type,
                    duration_ms=None,
                    tags=_tokenize_filename(path),
                    metadata={
                        "discovered_from": str(materials_dir.resolve()),
                        "relative_path": relative_path,
                    },
                )
            )
        if not materials:
            raise ProductionConfigError(f"no media assets found under: {materials_dir}")
        return materials

    def _load_tts_clips(self, items: Iterable[Any]) -> List[AudioClip]:
        clips: List[AudioClip] = []
        for index, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                raise ProductionConfigError(f"production.tts_clips[{index}] must be an object")
            start_ms = int(item.get("start_ms", 0) or 0)
            end_ms = int(item.get("end_ms", 0) or 0)
            clips.append(
                AudioClip(
                    segment_id=str(item.get("segment_id") or f"seg-{index}").strip(),
                    audio_path=_resolve_path(str(item.get("audio_path", "")).strip(), self.cwd),
                    start_ms=start_ms,
                    end_ms=end_ms,
                    text=str(item.get("text", "")).strip(),
                    metadata=item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {},
                )
            )
        return clips

    def _load_avatar_clips(self, items: Iterable[Any]) -> List[AvatarClip]:
        clips: List[AvatarClip] = []
        for index, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                raise ProductionConfigError(f"production.avatar_clips[{index}] must be an object")
            clips.append(
                AvatarClip(
                    segment_id=str(item.get("segment_id") or f"seg-{index}").strip(),
                    video_path=_resolve_path(str(item.get("video_path", "")).strip(), self.cwd),
                    audio_path=_resolve_path(str(item.get("audio_path", "")).strip(), self.cwd),
                    start_ms=int(item.get("start_ms", 0) or 0),
                    end_ms=int(item.get("end_ms", 0) or 0),
                    text=str(item.get("text", "")).strip(),
                    metadata=item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {},
                )
            )
        return clips

    @staticmethod
    def _optional_int(value: Any) -> Optional[int]:
        if value is None or value == "":
            return None
        return int(value)
