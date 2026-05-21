"""Jianying draft adapter for Video Director."""

from __future__ import annotations

import json
import subprocess
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import urllib.error
import urllib.request
from urllib.parse import urlparse

from ..models import AdapterResult, KernelOutput, ProductionBundle, TimelineClip, to_dict
from .base import OutputAdapter


class JianyingDraftAdapter(OutputAdapter):
    """Export the canonical timeline into a Jianying-oriented bundle or draft."""

    target_name = "jianying_draft"

    def render(
        self,
        *,
        output_dir: Path,
        bundle: ProductionBundle,
        kernel_output: KernelOutput,
        dry_run: bool,
    ) -> AdapterResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        bundle_path = output_dir / "draft_bundle.json"
        timeline_payload = to_dict(kernel_output.timeline)
        asset_manifest: Dict[str, Any] = {}
        if self.config.get("materialize_local_assets", True):
            timeline_payload, asset_manifest = self._materialize_timeline_assets(
                output_dir=output_dir,
                timeline=timeline_payload,
                dry_run=dry_run,
            )
        payload = {
            "meta": {
                "generated_at": int(time.time()),
                "target": self.target_name,
                "job_id": bundle.job_id,
                "dry_run": dry_run,
            },
            "production_bundle": to_dict(bundle),
            "timeline": timeline_payload,
            "edit_decisions": to_dict(kernel_output.edit_decisions),
        }
        bundle_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        if asset_manifest:
            (output_dir / "assets_local_manifest.json").write_text(
                json.dumps(asset_manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        if not self.config.get("use_pyjianyingdraft", False):
            return AdapterResult(
                target=self.target_name,
                status="bundle_only",
                artifact_path=str(bundle_path),
                note="pyJianYingDraft disabled",
            )

        drafts_root = Path(str(self.config.get("drafts_root", output_dir / "drafts"))).expanduser()
        draft_name = str(self.config.get("draft_name", f"{bundle.job_id}-jianying")).strip()
        draft_dir = self._build_pyjy_draft(bundle_path=bundle_path, drafts_root=drafts_root, draft_name=draft_name)
        return AdapterResult(
            target=self.target_name,
            status="draft_built",
            artifact_path=str(draft_dir.resolve()),
            note="pyJianYingDraft draft created",
            details={"bundle_path": str(bundle_path)},
        )

    def _build_pyjy_draft(self, *, bundle_path: Path, drafts_root: Path, draft_name: str) -> Path:
        try:
            import pyJianYingDraft as pyjy
            from pyJianYingDraft import ClipSettings, TextBorder, TextSegment, TextShadow, TextStyle
        except ModuleNotFoundError as exc:
            raise RuntimeError("outputs.jianying.use_pyjianyingdraft=true but pyJianYingDraft is not installed") from exc

        data = json.loads(bundle_path.read_text(encoding="utf-8"))
        timeline = data["timeline"]
        tracks = timeline.get("tracks", {})
        resolution = timeline.get("resolution", "1080x1920")
        width, height = self._parse_resolution(resolution)

        drafts_root.mkdir(parents=True, exist_ok=True)
        draft_name = self._resolve_unique_draft_name(drafts_root, draft_name)
        draft_folder = pyjy.DraftFolder(str(drafts_root))
        script = draft_folder.create_draft(draft_name, width, height)
        embedded_avatar_audio_segments = self._collect_avatar_segments_with_embedded_audio(tracks)

        if self._visual_tracks_can_merge(tracks):
            script.add_track(pyjy.TrackType.video, "video_main", relative_index=1)
            for clip in self._collect_visual_clips(tracks):
                clip_volume = 1.0 if str(clip.get("segment_id", "")) in embedded_avatar_audio_segments else 0.0
                self._add_video_clip(pyjy, ClipSettings, script, clip, "video_main", volume=clip_volume)
            audio_track_index = 2
        else:
            script.add_track(pyjy.TrackType.video, "video_broll", relative_index=1)
            script.add_track(pyjy.TrackType.video, "video_avatar", relative_index=2)
            for clip in tracks.get("material_track", []):
                self._add_video_clip(pyjy, ClipSettings, script, clip, "video_broll", volume=0.0)
            for clip in tracks.get("avatar_track", []):
                clip_volume = 1.0 if str(clip.get("segment_id", "")) in embedded_avatar_audio_segments else 0.0
                self._add_video_clip(pyjy, ClipSettings, script, clip, "video_avatar", volume=clip_volume)
            audio_track_index = 3

        script.add_track(pyjy.TrackType.audio, "voice", relative_index=audio_track_index)
        if self._subtitles_enabled(timeline):
            script.add_track(pyjy.TrackType.text, "subtitle", relative_index=audio_track_index + 1)

        for clip in tracks.get("audio_track", []):
            if str(clip.get("segment_id", "")) in embedded_avatar_audio_segments:
                continue
            self._add_audio_clip(pyjy, script, clip, "voice")
        for cue in timeline.get("subtitles", []):
            self._add_text_clip(
                pyjy,
                TextSegment,
                TextStyle,
                TextBorder,
                TextShadow,
                ClipSettings,
                script,
                cue,
                "subtitle",
            )

        script.save()
        return drafts_root / draft_name

    def _subtitles_enabled(self, timeline: Dict[str, Any]) -> bool:
        subtitles_cfg = self.config.get("subtitles", {}) if isinstance(self.config.get("subtitles"), dict) else {}
        if not bool(subtitles_cfg.get("enabled", True)):
            return False
        subtitles = timeline.get("subtitles", [])
        return isinstance(subtitles, list) and len(subtitles) > 0

    @staticmethod
    def _resolve_unique_draft_name(drafts_root: Path, draft_name: str) -> str:
        candidate = draft_name.strip() or f"video-director-jianying-{int(time.time())}"
        path = drafts_root / candidate
        if not path.exists():
            return candidate
        return f"{candidate}-{time.strftime('%Y%m%d-%H%M%S')}"

    def _materialize_timeline_assets(
        self,
        *,
        output_dir: Path,
        timeline: Dict[str, Any],
        dry_run: bool,
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        localized = json.loads(json.dumps(timeline, ensure_ascii=False))
        assets_root = output_dir / str(self.config.get("local_assets_subdir", "assets_local"))
        assets_root.mkdir(parents=True, exist_ok=True)
        manifest: Dict[str, Any] = {"root": str(assets_root.resolve()), "tracks": {}}
        track_dirs = {
            "material_track": assets_root / "material",
            "avatar_track": assets_root / "avatar",
            "audio_track": assets_root / "audio",
        }
        for path in track_dirs.values():
            path.mkdir(parents=True, exist_ok=True)

        for track_name, clips in localized.get("tracks", {}).items():
            if not isinstance(clips, list):
                continue
            manifest["tracks"][track_name] = []
            for index, clip in enumerate(clips, start=1):
                if not isinstance(clip, dict):
                    continue
                source = str(clip.get("source_path", "")).strip()
                suffix = Path(urlparse(source).path).suffix or (".wav" if track_name == "audio_track" else ".mp4")
                clip_id = str(clip.get("clip_id", "")).strip() or f"{track_name}_{index:02d}"
                if source == "generated://black":
                    width, height = self._parse_resolution(str(localized.get("resolution", "1080x1920")))
                    duration_ms = max(int(clip.get("end_ms", 0) or 0) - int(clip.get("start_ms", 0) or 0), 1)
                    local_path = self._materialize_generated_black_video(
                        target_dir=track_dirs.get(track_name, assets_root),
                        target_name=self._build_materialized_asset_name(clip_id=clip_id, suffix=".mp4"),
                        width=width,
                        height=height,
                        fps=int(localized.get("fps", 30) or 30),
                        duration_ms=duration_ms,
                        dry_run=dry_run,
                    )
                else:
                    local_path = self._materialize_source(
                        source=source,
                        target_dir=track_dirs.get(track_name, assets_root),
                        target_name=self._build_materialized_asset_name(clip_id=clip_id, suffix=suffix),
                        dry_run=dry_run,
                    )
                if local_path:
                    clip["source_path"] = local_path
                manifest["tracks"][track_name].append(
                    {
                        "clip_id": clip.get("clip_id"),
                        "source_path": source,
                        "local_source_path": local_path,
                    }
                )
        return localized, manifest

    def _materialize_generated_black_video(
        self,
        *,
        target_dir: Path,
        target_name: str,
        width: int,
        height: int,
        fps: int,
        duration_ms: int,
        dry_run: bool,
    ) -> str:
        target_dir = target_dir.resolve()
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = (target_dir / target_name).resolve()
        if dry_run:
            return str(target_path)
        ffmpeg_bin = str(self.config.get("ffmpeg_bin", "ffmpeg")).strip() or "ffmpeg"
        duration_seconds = max(duration_ms / 1000.0, 0.001)
        cmd = [
            ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=black:s={width}x{height}:r={max(fps, 1)}:d={duration_seconds:.3f}",
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(target_path),
        ]
        subprocess.run(cmd, check=True)
        return str(target_path)

    @staticmethod
    def _build_materialized_asset_name(*, clip_id: str, suffix: str) -> str:
        safe_clip_id = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in clip_id).strip("_")
        safe_clip_id = safe_clip_id or "asset"
        return f"{safe_clip_id}{suffix or ''}"

    def _materialize_source(self, *, source: str, target_dir: Path, target_name: str, dry_run: bool) -> str:
        source = source.strip()
        if not source:
            return ""
        parsed = urlparse(source)
        is_remote = parsed.scheme in {"http", "https"}
        is_virtual = "://" in source and parsed.scheme not in {"", "http", "https"}
        target_dir = target_dir.resolve()
        target_name = target_name.strip() or (Path(parsed.path).name if is_remote else Path(source).name) or "asset"
        target_path = (target_dir / target_name).resolve()

        if is_remote:
            if not self.config.get("download_remote_assets", True):
                return source
            if dry_run:
                return str(target_path)
            self._download_file(source, target_path)
            return str(target_path)

        if is_virtual:
            if dry_run:
                return str(target_path)
            raise RuntimeError(f"unsupported non-local asset scheme for Jianying: {source}")

        src_path = Path(source).expanduser()
        if not src_path.is_absolute():
            src_path = src_path.resolve()
        if not src_path.exists():
            raise RuntimeError(f"source asset not found: {src_path}")
        if dry_run:
            return str(src_path.resolve())
        if src_path.resolve() != target_path.resolve():
            shutil.copy2(src_path, target_path)
            return str(target_path)
        return str(src_path.resolve())

    def _collect_avatar_segments_with_embedded_audio(self, tracks: Dict[str, Any]) -> set[str]:
        if not bool(self.config.get("prefer_avatar_embedded_audio", True)):
            return set()
        embedded_audio_segments: set[str] = set()
        avatar_clips = tracks.get("avatar_track", [])
        if not isinstance(avatar_clips, list):
            return embedded_audio_segments
        for clip in avatar_clips:
            if not isinstance(clip, dict):
                continue
            segment_id = str(clip.get("segment_id", "")).strip()
            source_path = str(clip.get("source_path", "")).strip()
            if not segment_id or not source_path:
                continue
            if self._media_has_audio_stream(source_path):
                embedded_audio_segments.add(segment_id)
        return embedded_audio_segments

    @staticmethod
    def _media_has_audio_stream(source_path: str) -> bool:
        path = Path(source_path).expanduser()
        if not path.is_file():
            return False
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    "a",
                    "-show_entries",
                    "stream=index",
                    "-of",
                    "json",
                    str(path),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
        except (OSError, subprocess.CalledProcessError):
            return False
        try:
            payload = json.loads(result.stdout or "{}")
        except json.JSONDecodeError:
            return False
        streams = payload.get("streams", [])
        return isinstance(streams, list) and len(streams) > 0

    @staticmethod
    def _collect_visual_clips(tracks: Dict[str, Any]) -> List[Dict[str, Any]]:
        visual_clips: List[Dict[str, Any]] = []
        for track_name in ("material_track", "avatar_track"):
            clips = tracks.get(track_name, [])
            if not isinstance(clips, list):
                continue
            for clip in clips:
                if isinstance(clip, dict):
                    visual_clips.append(clip)
        visual_clips.sort(
            key=lambda clip: (
                int(clip.get("start_ms", 0)),
                int(clip.get("end_ms", 0)),
                str(clip.get("clip_id", "")),
            )
        )
        return visual_clips

    @classmethod
    def _visual_tracks_can_merge(cls, tracks: Dict[str, Any]) -> bool:
        visual_clips = cls._collect_visual_clips(tracks)
        if len(visual_clips) <= 1:
            return True

        current_end_ms = 0
        for clip in visual_clips:
            start_ms = int(clip.get("start_ms", 0))
            end_ms = int(clip.get("end_ms", 0))
            if start_ms < current_end_ms:
                return False
            current_end_ms = max(current_end_ms, end_ms)
        return True

    @staticmethod
    def _download_file(url: str, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                with output_path.open("wb") as handle:
                    while True:
                        chunk = resp.read(1024 * 64)
                        if not chunk:
                            break
                        handle.write(chunk)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"download failed HTTP {exc.code}: {url}, body={body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"download failed: {url}, error={exc}") from exc

    @staticmethod
    def _parse_resolution(raw: str) -> tuple[int, int]:
        if "x" not in raw:
            return 1080, 1920
        width, height = raw.lower().split("x", 1)
        return max(int(width), 1), max(int(height), 1)

    def _add_video_clip(
        self,
        pyjy: Any,
        clip_settings_cls: Any,
        script: Any,
        clip: Dict[str, Any],
        track_name: str,
        *,
        volume: float,
    ) -> None:
        source_path = self._require_local_file(str(clip.get("source_path", "")).strip(), "video clip")
        start_us = self._ms_to_us(int(clip.get("start_ms", 0)))
        seg_us = self._ms_to_us(int(clip.get("end_ms", 0)) - int(clip.get("start_ms", 0)))
        source_start_us = self._ms_to_us(int(clip.get("media_start_ms", 0)))
        source_us = None
        if clip.get("media_end_ms") is not None:
            source_us = self._ms_to_us(int(clip.get("media_end_ms", 0)) - int(clip.get("media_start_ms", 0)))
        metadata = clip.get("metadata", {}) if isinstance(clip.get("metadata"), dict) else {}
        self._pyjy_add_video_segment(
            pyjy,
            clip_settings_cls,
            script,
            track_name=track_name,
            video_path=source_path,
            start_us=start_us,
            seg_us=seg_us,
            volume=volume,
            source_start_us=source_start_us,
            source_us=source_us,
            fade_in_us=self._ms_to_us(int(metadata.get("fade_in_ms", 0) or 0)),
            fade_out_us=self._ms_to_us(int(metadata.get("fade_out_ms", 0) or 0)),
        )

    def _add_audio_clip(self, pyjy: Any, script: Any, clip: Dict[str, Any], track_name: str) -> None:
        source_path = self._require_local_file(str(clip.get("source_path", "")).strip(), "audio clip")
        start_us = self._ms_to_us(int(clip.get("start_ms", 0)))
        seg_us = self._ms_to_us(int(clip.get("end_ms", 0)) - int(clip.get("start_ms", 0)))
        self._pyjy_add_audio_segment(
            pyjy,
            script,
            track_name=track_name,
            audio_path=source_path,
            start_us=start_us,
            seg_us=seg_us,
            volume=1.0,
        )

    def _add_text_clip(
        self,
        pyjy: Any,
        text_segment_cls: Any,
        text_style_cls: Any,
        text_border_cls: Any,
        text_shadow_cls: Any,
        clip_settings_cls: Any,
        script: Any,
        cue: Dict[str, Any],
        track_name: str,
    ) -> None:
        text = str(cue.get("text", "")).strip()
        if not text:
            return
        start_us = self._ms_to_us(int(cue.get("start_ms", 0)))
        seg_us = self._ms_to_us(int(cue.get("end_ms", 0)) - int(cue.get("start_ms", 0)))
        if seg_us <= 0:
            return

        subtitles_cfg = self.config.get("subtitles", {}) if isinstance(self.config.get("subtitles"), dict) else {}
        style = text_style_cls(
            size=float(subtitles_cfg.get("font_size", 6.0)),
            bold=bool(subtitles_cfg.get("bold", True)),
            italic=bool(subtitles_cfg.get("italic", False)),
            underline=bool(subtitles_cfg.get("underline", False)),
            color=self._parse_rgb_color(str(subtitles_cfg.get("font_color", "#FFFFFF")), fallback=(1.0, 1.0, 1.0)),
            alpha=float(subtitles_cfg.get("font_alpha", 1.0)),
            align=int(subtitles_cfg.get("align", 1)),
            vertical=bool(subtitles_cfg.get("vertical", False)),
            letter_spacing=int(subtitles_cfg.get("letter_spacing", 0)),
            line_spacing=int(subtitles_cfg.get("line_spacing", 8)),
            auto_wrapping=bool(subtitles_cfg.get("auto_wrapping", True)),
            max_line_width=float(subtitles_cfg.get("max_line_width", 0.82)),
        )
        clip_settings = clip_settings_cls(
            alpha=1.0,
            transform_x=float(subtitles_cfg.get("transform_x", 0.0)),
            transform_y=float(subtitles_cfg.get("transform_y", -0.78)),
        )
        border = None
        if bool(subtitles_cfg.get("border_enabled", True)):
            border = text_border_cls(
                alpha=float(subtitles_cfg.get("border_alpha", 1.0)),
                color=self._parse_rgb_color(str(subtitles_cfg.get("border_color", "#000000")), fallback=(0.0, 0.0, 0.0)),
                width=float(subtitles_cfg.get("border_width", 42.0)),
            )
        shadow = None
        if bool(subtitles_cfg.get("shadow_enabled", False)):
            shadow = text_shadow_cls(
                alpha=float(subtitles_cfg.get("shadow_alpha", 0.65)),
                color=self._parse_rgb_color(str(subtitles_cfg.get("shadow_color", "#000000")), fallback=(0.0, 0.0, 0.0)),
                distance=float(subtitles_cfg.get("shadow_distance", 14.0)),
                angle=float(subtitles_cfg.get("shadow_angle", 45.0)),
                diffuse=float(subtitles_cfg.get("shadow_diffuse", 18.0)),
            )

        segment = text_segment_cls(
            text,
            pyjy.Timerange(start_us, seg_us),
            style=style,
            clip_settings=clip_settings,
            border=border,
            shadow=shadow,
        )
        script.add_segment(segment, track_name=track_name)

    @staticmethod
    def _require_local_file(raw: str, label: str) -> str:
        if not raw:
            raise RuntimeError(f"{label} path is empty")
        parsed = urlparse(raw)
        if parsed.scheme in {"http", "https"}:
            raise RuntimeError(f"{label} requires a local file, got remote url: {raw}")
        path = Path(raw).expanduser()
        if not path.is_file():
            raise RuntimeError(f"{label} not found: {path}")
        return str(path.resolve())

    @staticmethod
    def _ms_to_us(value: int) -> int:
        return max(int(value), 0) * 1000

    @staticmethod
    def _parse_rgb_color(raw: str, *, fallback: Tuple[float, float, float]) -> Tuple[float, float, float]:
        text = raw.strip().lstrip("#")
        if len(text) != 6:
            return fallback
        try:
            return tuple(int(text[index : index + 2], 16) / 255.0 for index in (0, 2, 4))  # type: ignore[return-value]
        except ValueError:
            return fallback

    @staticmethod
    def _pyjy_add_video_segment(
        pyjy: Any,
        clip_settings_cls: Any,
        script: Any,
        *,
        track_name: str,
        video_path: str,
        start_us: int,
        seg_us: int,
        volume: float,
        source_start_us: int = 0,
        source_us: Optional[int] = None,
        fade_in_us: int = 0,
        fade_out_us: int = 0,
    ) -> None:
        if seg_us <= 0:
            return
        material = pyjy.VideoMaterial(video_path)
        material_duration_us = max(int(material.duration) - 1, 1)
        safe_source_start_us = max(int(source_start_us), 0) % material_duration_us
        preferred_source_us = int(source_us) if source_us is not None else int(seg_us)
        available_us = max(material_duration_us - safe_source_start_us, 1)
        source_us_final = min(max(preferred_source_us, 1), available_us)
        target_us = min(seg_us, source_us_final)
        if target_us <= 0:
            return
        segment = pyjy.VideoSegment(
            material,
            pyjy.Timerange(start_us, target_us),
            source_timerange=pyjy.Timerange(safe_source_start_us, source_us_final),
            volume=volume,
            clip_settings=clip_settings_cls(alpha=1.0),
        )
        if fade_in_us > 0:
            fade_in_us = min(max(fade_in_us, 0), target_us)
            segment.add_keyframe(pyjy.KeyframeProperty.alpha, 0, 0.0)
            segment.add_keyframe(pyjy.KeyframeProperty.alpha, fade_in_us, 1.0)
        if fade_out_us > 0:
            fade_out_us = min(max(fade_out_us, 0), target_us)
            segment.add_keyframe(pyjy.KeyframeProperty.alpha, max(target_us - fade_out_us, 0), 1.0)
            segment.add_keyframe(pyjy.KeyframeProperty.alpha, target_us, 0.0)
        script.add_segment(segment, track_name=track_name)

    @staticmethod
    def _pyjy_add_audio_segment(
        pyjy: Any,
        script: Any,
        *,
        track_name: str,
        audio_path: str,
        start_us: int,
        seg_us: int,
        volume: float,
    ) -> bool:
        if seg_us <= 0:
            return False
        material = pyjy.AudioMaterial(audio_path)
        source_us = min(seg_us, max(int(material.duration) - 1, 1))
        target_us = min(seg_us, source_us)
        if target_us <= 0:
            return False
        script.add_segment(
            pyjy.AudioSegment(
                material,
                pyjy.Timerange(start_us, target_us),
                source_timerange=pyjy.Timerange(0, source_us),
                volume=volume,
            ),
            track_name=track_name,
        )
        return True
