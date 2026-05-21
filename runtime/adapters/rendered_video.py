"""FFmpeg-backed rendered video adapters for preview/final outputs."""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

from ..models import AdapterResult, KernelOutput, ProductionBundle, TimelineClip, TimelineModel
from .base import OutputAdapter


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".bmp"}
TRAILING_SUBTITLE_PUNCTUATION = "，,。.!！?？;；:：、"


class RenderAdapterError(RuntimeError):
    """Raised when the rendered video adapter cannot complete."""


# Keep sidecar subtitles opt-in: common players auto-load a matching .srt
# beside the mp4, which duplicates the already burned-in captions.
DEFAULTS_BY_TARGET: Dict[str, Dict[str, Any]] = {
    "preview_render": {
        "output_name": "preview.mp4",
        "video_codec": "libx264",
        "audio_codec": "aac",
        "audio_bitrate": "160k",
        "preset": "veryfast",
        "crf": 28,
        "pixel_format": "yuv420p",
        "background_mode": "blurred_fill",
        "background_color": "black",
        "background_blur_sigma": 32,
        "background_dim_brightness": -0.10,
        "background_saturation": 0.88,
        "emit_sidecar_srt": False,
        "allow_sidecar_srt": False,
        "burn_subtitles": True,
        "transition_mode": "fade",
        "transition_duration_ms": 220,
        "subtitle_bottom_margin": 140,
        "subtitle_box_padding_x": 42,
        "subtitle_box_padding_y": 22,
        "subtitle_box_radius": 24,
        "subtitle_box_color": (0, 0, 0, 150),
        "subtitle_text_color": (255, 255, 255, 255),
        "subtitle_stroke_color": (0, 0, 0, 210),
        "subtitle_stroke_width": 2,
        "subtitle_font_size": 48,
        "subtitle_strip_trailing_punctuation": True,
    },
    "final_render": {
        "output_name": "final.mp4",
        "video_codec": "libx264",
        "audio_codec": "aac",
        "audio_bitrate": "192k",
        "preset": "medium",
        "crf": 20,
        "pixel_format": "yuv420p",
        "background_mode": "blurred_fill",
        "background_color": "black",
        "background_blur_sigma": 32,
        "background_dim_brightness": -0.10,
        "background_saturation": 0.88,
        "emit_sidecar_srt": False,
        "allow_sidecar_srt": False,
        "burn_subtitles": True,
        "transition_mode": "fade",
        "transition_duration_ms": 260,
        "subtitle_bottom_margin": 140,
        "subtitle_box_padding_x": 42,
        "subtitle_box_padding_y": 22,
        "subtitle_box_radius": 24,
        "subtitle_box_color": (0, 0, 0, 150),
        "subtitle_text_color": (255, 255, 255, 255),
        "subtitle_stroke_color": (0, 0, 0, 210),
        "subtitle_stroke_width": 2,
        "subtitle_font_size": 48,
        "subtitle_strip_trailing_punctuation": True,
    },
}


class RenderedVideoAdapter(OutputAdapter):
    """Render the canonical timeline into a directly playable video file."""

    def __init__(self, target_name: str, config: Dict[str, Any]):
        super().__init__(config)
        self.target_name = target_name
        target_defaults = DEFAULTS_BY_TARGET.get(target_name, DEFAULTS_BY_TARGET["final_render"])
        self.effective_config = {**target_defaults, **config}
        self.ffmpeg_bin = str(self.effective_config.get("ffmpeg_bin", "ffmpeg")).strip() or "ffmpeg"

    def render(
        self,
        *,
        output_dir: Path,
        bundle: ProductionBundle,
        kernel_output: KernelOutput,
        dry_run: bool,
    ) -> AdapterResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_ffmpeg_available()

        timeline = kernel_output.timeline
        render_plan = self._build_render_plan(timeline)
        plan_path = output_dir / f"{self.target_name}.render_plan.json"
        plan_path.write_text(json.dumps(render_plan, ensure_ascii=False, indent=2), encoding="utf-8")

        output_name = str(self.effective_config.get("output_name", f"{self.target_name}.mp4")).strip() or f"{self.target_name}.mp4"
        output_path = output_dir / output_name
        subtitles_path = output_dir / f"{output_path.stem}.srt"

        if self._sidecar_srt_enabled():
            self._write_srt(subtitles_path, timeline.subtitles)

        if dry_run:
            return AdapterResult(
                target=self.target_name,
                status="dry_run",
                artifact_path=str(plan_path),
                note="render plan only",
                details={
                    "planned_output_path": str(output_path),
                    "subtitles_path": str(subtitles_path) if subtitles_path.exists() else "",
                },
            )

        staging_root = output_dir / "staging"
        video_segments_dir = staging_root / "video_segments"
        audio_segments_dir = staging_root / "audio_segments"
        concat_dir = staging_root / "concat"
        subtitle_overlay_dir = staging_root / "subtitle_overlays"
        for path in (video_segments_dir, audio_segments_dir, concat_dir, subtitle_overlay_dir):
            path.mkdir(parents=True, exist_ok=True)

        video_segments = self._render_video_segments(
            clips=self._collect_video_clips(timeline),
            timeline=timeline,
            output_dir=video_segments_dir,
            subtitle_overlay_dir=subtitle_overlay_dir,
        )
        silent_video_path = concat_dir / "video.mp4"
        self._concat_video_segments(video_segments, silent_video_path)

        audio_output_path = self._render_audio_track(
            clips=sorted(timeline.tracks.get("audio_track", []), key=lambda clip: (clip.start_ms, clip.clip_id)),
            timeline=timeline,
            output_dir=audio_segments_dir,
            concat_dir=concat_dir,
        )
        self._mux_video_and_audio(
            video_path=silent_video_path,
            audio_path=audio_output_path,
            output_path=output_path,
        )
        self._validate_rendered_output(output_path)

        return AdapterResult(
            target=self.target_name,
            status="rendered",
            artifact_path=str(output_path),
            note="ffmpeg video rendered",
            details={
                "render_plan_path": str(plan_path),
                "silent_video_path": str(silent_video_path),
                "audio_path": str(audio_output_path) if audio_output_path else "",
                "subtitles_path": str(subtitles_path) if subtitles_path.exists() else "",
            },
        )

    def _ensure_ffmpeg_available(self) -> None:
        if shutil.which(self.ffmpeg_bin):
            return
        raise RenderAdapterError(f"ffmpeg binary not found: {self.ffmpeg_bin}")

    def _build_render_plan(self, timeline: TimelineModel) -> Dict[str, Any]:
        video_clips = self._collect_video_clips(timeline)
        audio_clips = sorted(timeline.tracks.get("audio_track", []), key=lambda clip: (clip.start_ms, clip.clip_id))
        return {
            "target": self.target_name,
            "resolution": timeline.resolution,
            "fps": timeline.fps,
            "duration_ms": timeline.duration_ms,
            "video_codec": self.effective_config.get("video_codec"),
            "audio_codec": self.effective_config.get("audio_codec"),
            "preset": self.effective_config.get("preset"),
            "crf": self.effective_config.get("crf"),
            "burn_subtitles": self._burn_subtitles_enabled(),
            "transition_mode": self._transition_mode(),
            "transition_duration_ms": int(self.effective_config.get("transition_duration_ms", 0) or 0),
            "video_clips": [self._clip_plan_item(clip) for clip in video_clips],
            "audio_clips": [self._clip_plan_item(clip) for clip in audio_clips],
            "subtitle_count": len(timeline.subtitles),
        }

    @staticmethod
    def _clip_plan_item(clip: TimelineClip) -> Dict[str, Any]:
        return {
            "clip_id": clip.clip_id,
            "track": clip.track,
            "role": clip.role,
            "source_path": clip.source_path,
            "start_ms": clip.start_ms,
            "end_ms": clip.end_ms,
            "media_start_ms": clip.media_start_ms,
            "media_end_ms": clip.media_end_ms,
            "segment_id": clip.segment_id,
        }

    @staticmethod
    def _collect_video_clips(timeline: TimelineModel) -> List[TimelineClip]:
        clips = list(timeline.tracks.get("material_track", [])) + list(timeline.tracks.get("avatar_track", []))
        ordered = sorted(clips, key=lambda clip: (clip.start_ms, clip.clip_id))
        if not ordered:
            raise RenderAdapterError("timeline has no video clips to render")
        return ordered

    def _render_video_segments(
        self,
        *,
        clips: Sequence[TimelineClip],
        timeline: TimelineModel,
        output_dir: Path,
        subtitle_overlay_dir: Path,
    ) -> List[Path]:
        width, height = self._parse_resolution(timeline.resolution)
        rendered: List[Path] = []
        for index, clip in enumerate(clips, start=1):
            segment_path = output_dir / f"{index:03d}_{clip.role or 'video'}.mp4"
            subtitle_overlay_path = None
            if self._burn_subtitles_enabled() and clip.text.strip():
                subtitle_overlay_path = subtitle_overlay_dir / f"{index:03d}_{clip.role or 'video'}.png"
                subtitle_text = self._subtitle_text_for_clip(timeline, clip)
                self._render_subtitle_overlay(
                    text=subtitle_text,
                    width=width,
                    height=height,
                    output_path=subtitle_overlay_path,
                )
            self._render_video_segment(
                clip=clip,
                output_path=segment_path,
                width=width,
                height=height,
                fps=timeline.fps,
                subtitle_overlay_path=subtitle_overlay_path,
            )
            rendered.append(segment_path)
        return rendered

    def _render_video_segment(
        self,
        *,
        clip: TimelineClip,
        output_path: Path,
        width: int,
        height: int,
        fps: int,
        subtitle_overlay_path: Optional[Path],
    ) -> None:
        source_is_generated_black = self._is_generated_black_source(clip.source_path)
        source = "" if source_is_generated_black else self._validate_media_source(clip.source_path, label=f"{clip.track}:{clip.clip_id}")
        duration_ms = max(int(clip.end_ms - clip.start_ms), 1)
        duration_seconds = self._frame_aligned_seconds_text(duration_ms, fps)
        media_start_seconds = self._seconds_text(max(int(clip.media_start_ms), 0))
        pixel_format = str(self.effective_config.get("pixel_format", "yuv420p"))
        cmd = [self.ffmpeg_bin, "-y"]
        if source_is_generated_black:
            cmd += [
                "-f",
                "lavfi",
                "-t",
                duration_seconds,
                "-i",
                f"color=c=black:s={width}x{height}:r={max(fps, 1)}",
            ]
        else:
            if media_start_seconds != "0.000":
                cmd += ["-ss", media_start_seconds]
            if self._is_image_source(source):
                cmd += [
                    "-loop",
                    "1",
                    "-framerate",
                    str(max(fps, 1)),
                    "-t",
                    duration_seconds,
                    "-i",
                    source,
                ]
            else:
                cmd += ["-i", source]
        if subtitle_overlay_path is not None:
            cmd += [
                "-loop",
                "1",
                "-framerate",
                str(max(fps, 1)),
                "-t",
                duration_seconds,
                "-i",
                str(subtitle_overlay_path),
            ]
        filter_chain = self._video_filter_chain(
            width=width,
            height=height,
            fps=fps,
            pixel_format=pixel_format,
            duration_seconds=duration_seconds,
            fade_out_ms=self._clip_fade_out_ms(clip),
        )
        codec = str(self.effective_config.get("video_codec", "libx264"))
        preset = str(self.effective_config.get("preset", "medium"))
        crf = str(self.effective_config.get("crf", 20))

        if subtitle_overlay_path is not None:
            filter_complex = (
                f"[0:v]{filter_chain}[base];"
                "[1:v]format=rgba[subtitle];"
                "[base][subtitle]overlay=0:0:shortest=1,format="
                f"{pixel_format}[outv]"
            )
            cmd += [
                "-an",
                "-filter_complex",
                filter_complex,
                "-map",
                "[outv]",
                "-t",
                duration_seconds,
                "-c:v",
                codec,
                "-preset",
                preset,
                "-crf",
                crf,
                "-pix_fmt",
                pixel_format,
                str(output_path),
            ]
        else:
            cmd += [
                "-an",
                "-vf",
                filter_chain,
                "-t",
                duration_seconds,
                "-c:v",
                codec,
                "-preset",
                preset,
                "-crf",
                crf,
                "-pix_fmt",
                pixel_format,
                str(output_path),
            ]
        self._run_ffmpeg(cmd, label=f"render video segment {clip.clip_id}")

    def _video_filter_chain(
        self,
        *,
        width: int,
        height: int,
        fps: int,
        pixel_format: str,
        duration_seconds: str,
        fade_out_ms: int,
    ) -> str:
        background_color = str(self.effective_config.get("background_color", "black")).strip() or "black"
        background_mode = str(self.effective_config.get("background_mode", "blurred_fill")).strip().lower()
        if background_mode == "blurred_fill":
            blur_sigma = float(self.effective_config.get("background_blur_sigma", 32) or 32)
            dim = float(self.effective_config.get("background_dim_brightness", -0.10) or 0)
            saturation = float(self.effective_config.get("background_saturation", 0.88) or 1)
            filters = [
                (
                    f"split=2[fgsrc][bgsrc];"
                    f"[bgsrc]scale={width}:{height}:force_original_aspect_ratio=increase,"
                    f"crop={width}:{height},gblur=sigma={blur_sigma:.3f},"
                    f"eq=brightness={dim:.3f}:saturation={saturation:.3f}[bg];"
                    f"[fgsrc]scale={width}:{height}:force_original_aspect_ratio=decrease[fg];"
                    f"[bg][fg]overlay=(W-w)/2:(H-h)/2"
                ),
                f"fps={max(fps, 1)}",
                "setsar=1",
                f"tpad=stop_mode=clone:stop_duration={duration_seconds}",
            ]
        else:
            filters = [
                f"scale={width}:{height}:force_original_aspect_ratio=decrease",
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color={background_color}",
                f"fps={max(fps, 1)}",
                "setsar=1",
                f"tpad=stop_mode=clone:stop_duration={duration_seconds}",
            ]
        transition_mode = self._transition_mode()
        if transition_mode == "fade":
            fade_in_duration = self._transition_duration_seconds(duration_seconds)
            fade_out_duration = self._transition_duration_seconds(
                duration_seconds,
                configured_duration_ms=fade_out_ms if fade_out_ms > 0 else None,
            )
            if fade_in_duration > 0:
                filters.append(f"fade=t=in:st=0:d={fade_in_duration:.3f}")
            if fade_out_duration > 0:
                fade_out_start = max(float(duration_seconds) - fade_out_duration, 0.0)
                filters.append(f"fade=t=out:st={fade_out_start:.3f}:d={fade_out_duration:.3f}")
        filters.append(f"format={pixel_format}")
        return ",".join(filters)

    @staticmethod
    def _subtitle_text_for_clip(timeline: TimelineModel, clip: TimelineClip) -> str:
        matching = [
            cue
            for cue in timeline.subtitles
            if cue.start_ms < clip.end_ms and cue.end_ms > clip.start_ms and cue.text.strip()
        ]
        if not matching:
            return clip.text
        text = matching[0].text.strip()
        return text or clip.text

    def _transition_duration_seconds(self, duration_seconds: str, *, configured_duration_ms: Optional[int] = None) -> float:
        transition_duration_ms = (
            max(int(configured_duration_ms or 0), 0)
            if configured_duration_ms is not None
            else max(int(self.effective_config.get("transition_duration_ms", 0) or 0), 0)
        )
        if transition_duration_ms <= 0:
            return 0.0
        clip_duration = max(float(duration_seconds), 0.001)
        return min(transition_duration_ms / 1000.0, clip_duration / 2.0)

    def _burn_subtitles_enabled(self) -> bool:
        return bool(self.effective_config.get("burn_subtitles", False))

    def _sidecar_srt_enabled(self) -> bool:
        return bool(self.effective_config.get("allow_sidecar_srt", False)) and bool(
            self.effective_config.get("emit_sidecar_srt", False)
        )

    def _transition_mode(self) -> str:
        return str(self.effective_config.get("transition_mode", "fade")).strip().lower()

    @staticmethod
    def _clip_fade_out_ms(clip: TimelineClip) -> int:
        metadata = clip.metadata if isinstance(clip.metadata, dict) else {}
        return max(int(metadata.get("fade_out_ms", 0) or 0), 0)

    def _render_audio_track(
        self,
        *,
        clips: Sequence[TimelineClip],
        timeline: TimelineModel,
        output_dir: Path,
        concat_dir: Path,
    ) -> Optional[Path]:
        if not clips:
            return None
        if len(clips) == 1 and clips[0].start_ms <= 0 and (clips[0].end_ms >= timeline.duration_ms or clips[0].segment_id == "full-track"):
            return self._render_single_audio_source(
                clips[0],
                output_dir / "full_audio.wav",
                target_duration_ms=timeline.duration_ms,
            )

        cursor_ms = 0
        audio_parts: List[Path] = []
        for index, clip in enumerate(clips, start=1):
            if clip.start_ms > cursor_ms:
                silence_path = output_dir / f"{index:03d}_gap.wav"
                self._render_silence_segment(duration_ms=clip.start_ms - cursor_ms, output_path=silence_path)
                audio_parts.append(silence_path)
            segment_path = output_dir / f"{index:03d}_voice.wav"
            self._render_audio_segment(clip=clip, output_path=segment_path)
            audio_parts.append(segment_path)
            cursor_ms = max(cursor_ms, clip.end_ms)
        if cursor_ms < timeline.duration_ms:
            silence_path = output_dir / f"{len(audio_parts) + 1:03d}_tail.wav"
            self._render_silence_segment(duration_ms=timeline.duration_ms - cursor_ms, output_path=silence_path)
            audio_parts.append(silence_path)
        if not audio_parts:
            return None

        concat_list = concat_dir / "audio.concat.txt"
        self._write_concat_list(concat_list, audio_parts)
        output_path = concat_dir / "narration.wav"
        cmd = [
            self.ffmpeg_bin,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-c",
            "copy",
            str(output_path),
        ]
        self._run_ffmpeg(cmd, label="concat audio track")
        return output_path

    def _render_single_audio_source(self, clip: TimelineClip, output_path: Path, *, target_duration_ms: int) -> Path:
        source = self._validate_media_source(clip.source_path, label=f"audio:{clip.clip_id}")
        duration_ms = max(int(target_duration_ms), int(clip.end_ms - clip.start_ms), 1)
        media_start_seconds = self._seconds_text(max(int(clip.media_start_ms), 0))
        duration_seconds = self._seconds_text(duration_ms)
        cmd = [self.ffmpeg_bin, "-y"]
        if media_start_seconds != "0.000":
            cmd += ["-ss", media_start_seconds]
        cmd += [
            "-i",
            source,
            "-vn",
            "-af",
            f"apad=pad_dur={duration_seconds},atrim=duration={duration_seconds},aresample=48000",
            "-ac",
            "2",
            "-c:a",
            "pcm_s16le",
            str(output_path),
        ]
        self._run_ffmpeg(cmd, label=f"render audio source {clip.clip_id}")
        return output_path

    def _render_audio_segment(self, *, clip: TimelineClip, output_path: Path) -> None:
        source = self._validate_media_source(clip.source_path, label=f"audio:{clip.clip_id}")
        duration_ms = max(int(clip.end_ms - clip.start_ms), 1)
        media_start_seconds = self._seconds_text(max(int(clip.media_start_ms), 0))
        duration_seconds = self._seconds_text(duration_ms)
        cmd = [self.ffmpeg_bin, "-y"]
        if media_start_seconds != "0.000":
            cmd += ["-ss", media_start_seconds]
        cmd += [
            "-i",
            source,
            "-vn",
            "-af",
            f"apad=pad_dur={duration_seconds},atrim=duration={duration_seconds},aresample=48000",
            "-ac",
            "2",
            "-c:a",
            "pcm_s16le",
            str(output_path),
        ]
        self._run_ffmpeg(cmd, label=f"render audio segment {clip.clip_id}")

    def _render_silence_segment(self, *, duration_ms: int, output_path: Path) -> None:
        duration_seconds = self._seconds_text(max(duration_ms, 1))
        cmd = [
            self.ffmpeg_bin,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=stereo",
            "-t",
            duration_seconds,
            "-c:a",
            "pcm_s16le",
            str(output_path),
        ]
        self._run_ffmpeg(cmd, label="render silence")

    def _concat_video_segments(self, segments: Sequence[Path], output_path: Path) -> None:
        concat_list = output_path.parent / "video.concat.txt"
        self._write_concat_list(concat_list, segments)
        cmd = [
            self.ffmpeg_bin,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-c",
            "copy",
            str(output_path),
        ]
        self._run_ffmpeg(cmd, label="concat video segments")

    def _mux_video_and_audio(
        self,
        *,
        video_path: Path,
        audio_path: Optional[Path],
        output_path: Path,
    ) -> None:
        cmd = [self.ffmpeg_bin, "-y", "-i", str(video_path)]
        if audio_path is None:
            cmd += [
                "-c:v",
                "copy",
                "-movflags",
                "+faststart",
                str(output_path),
            ]
            self._run_ffmpeg(cmd, label=f"mux silent {self.target_name}")
            return

        cmd += [
            "-i",
            str(audio_path),
            "-c:v",
            "copy",
            "-c:a",
            str(self.effective_config.get("audio_codec", "aac")),
            "-b:a",
            str(self.effective_config.get("audio_bitrate", "192k")),
            "-shortest",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        self._run_ffmpeg(cmd, label=f"mux {self.target_name}")

    def _render_subtitle_overlay(self, *, text: str, width: int, height: int, output_path: Path) -> None:
        Image, ImageDraw, _ = self._load_pillow_modules()
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        subtitle_text = self._clean_subtitle_text(text)
        lines, font = self._build_subtitle_lines(text=subtitle_text, width=width)
        if not lines:
            image.save(output_path)
            return

        font_size = int(getattr(font, "size", self.effective_config.get("subtitle_font_size", 58)))
        spacing = int(font_size * 0.32)
        text_boxes = [draw.textbbox((0, 0), line, font=font, stroke_width=self._subtitle_stroke_width()) for line in lines]
        text_width = max(box[2] - box[0] for box in text_boxes)
        text_height = sum(box[3] - box[1] for box in text_boxes) + spacing * max(len(lines) - 1, 0)

        padding_x = int(self.effective_config.get("subtitle_box_padding_x", 42))
        padding_y = int(self.effective_config.get("subtitle_box_padding_y", 22))
        radius = int(self.effective_config.get("subtitle_box_radius", 24))
        bottom_margin = int(self.effective_config.get("subtitle_bottom_margin", 140))

        box_left = max((width - text_width) // 2 - padding_x, 0)
        box_top = max(height - bottom_margin - text_height - padding_y * 2, 0)
        box_right = min(box_left + text_width + padding_x * 2, width)
        box_bottom = min(box_top + text_height + padding_y * 2, height)
        draw.rounded_rectangle(
            [(box_left, box_top), (box_right, box_bottom)],
            radius=radius,
            fill=self._rgba_tuple(self.effective_config.get("subtitle_box_color"), fallback=(0, 0, 0, 150)),
        )

        block_top = box_top + (box_bottom - box_top - text_height) / 2
        current_y = block_top
        text_color = self._rgba_tuple(self.effective_config.get("subtitle_text_color"), fallback=(255, 255, 255, 255))
        stroke_color = self._rgba_tuple(self.effective_config.get("subtitle_stroke_color"), fallback=(0, 0, 0, 210))
        stroke_width = self._subtitle_stroke_width()
        for line, box in zip(lines, text_boxes):
            box_left, box_top_offset, _, _ = box
            line_width = box[2] - box[0]
            line_height = box[3] - box[1]
            x = (width - line_width) / 2 - box_left
            y = current_y - box_top_offset
            draw.text(
                (x, y),
                line,
                font=font,
                fill=text_color,
                stroke_width=stroke_width,
                stroke_fill=stroke_color,
            )
            current_y += line_height + spacing

        output_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(output_path)

    def _build_subtitle_lines(self, *, text: str, width: int) -> Tuple[List[str], Any]:
        normalized = self._clean_subtitle_text(" ".join(str(text).split()))
        if not normalized:
            return [], self._load_subtitle_font(int(self.effective_config.get("subtitle_font_size", 58)))

        base_size = int(self.effective_config.get("subtitle_font_size", 58))
        font = self._load_subtitle_font(base_size, require_cjk=self._contains_cjk(normalized))
        target_width = int(width * 0.78)
        lines = self._wrap_subtitle_text(normalized, font=font, max_width=target_width)
        while len(lines) > 3 and base_size > 30:
            base_size -= 4
            font = self._load_subtitle_font(base_size, require_cjk=self._contains_cjk(normalized))
            lines = self._wrap_subtitle_text(normalized, font=font, max_width=target_width)
        return lines, font

    def _wrap_subtitle_text(self, text: str, *, font: Any, max_width: int) -> List[str]:
        Image, ImageDraw, _ = self._load_pillow_modules()
        draw = ImageDraw.Draw(Image.new("RGBA", (16, 16), (0, 0, 0, 0)))
        tokens = self._split_subtitle_tokens(text)
        if not tokens:
            return []

        lines: List[str] = []
        current = tokens[0]
        for token in tokens[1:]:
            candidate = current + token
            bbox = draw.textbbox((0, 0), candidate, font=font, stroke_width=self._subtitle_stroke_width())
            if bbox[2] - bbox[0] <= max_width:
                current = candidate
                continue
            lines.append(current.strip())
            current = token.lstrip()
        if current.strip():
            lines.append(current.strip())
        return lines[:3]

    @staticmethod
    def _split_subtitle_tokens(text: str) -> List[str]:
        tokens: List[str] = []
        buffer = ""
        for char in text:
            if char.isspace():
                if buffer:
                    tokens.append(buffer + " ")
                    buffer = ""
                continue
            if ord(char) < 128 and char.isalnum():
                buffer += char
                continue
            if buffer:
                tokens.append(buffer)
                buffer = ""
            tokens.append(char)
        if buffer:
            tokens.append(buffer)
        return tokens

    def _load_subtitle_font(self, size: int, *, require_cjk: bool = False) -> Any:
        _, _, ImageFont = self._load_pillow_modules()
        configured = str(self.effective_config.get("subtitle_font_path", "")).strip()
        env_configured = str(os.environ.get("VIDEO_DIRECTOR_SUBTITLE_FONT", "")).strip()
        candidates = [
            configured,
            env_configured,
            "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/msyhbd.ttc",
            "C:/Windows/Fonts/simhei.ttf",
            "C:/Windows/Fonts/simsun.ttc",
            "C:/Windows/Fonts/Deng.ttf",
            "C:/Windows/Fonts/Dengb.ttf",
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/Hiragino Sans GB.ttc",
            "/System/Library/Fonts/STHeiti Light.ttc",
            "/Library/Fonts/Arial Unicode.ttf",
            "/Library/Fonts/SourceHanSansSC-Regular.otf",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/arphic/ukai.ttc",
        ]
        for candidate in candidates:
            if not candidate:
                continue
            path = Path(candidate).expanduser()
            if path.is_file():
                return ImageFont.truetype(str(path), size=size)
        if require_cjk:
            raise RenderAdapterError(
                "Chinese subtitle burn-in needs a CJK-capable font; set "
                "outputs.final_render.subtitle_font_path or VIDEO_DIRECTOR_SUBTITLE_FONT"
            )
        return ImageFont.load_default()

    @staticmethod
    def _load_pillow_modules() -> Tuple[Any, Any, Any]:
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError as exc:
            raise RenderAdapterError(
                "subtitle burn-in requires Pillow in the current Python environment"
            ) from exc
        return Image, ImageDraw, ImageFont

    def _subtitle_stroke_width(self) -> int:
        return max(int(self.effective_config.get("subtitle_stroke_width", 2) or 0), 0)

    @staticmethod
    def _rgba_tuple(value: Any, *, fallback: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
        if isinstance(value, (list, tuple)) and len(value) == 4:
            return tuple(max(min(int(item), 255), 0) for item in value)  # type: ignore[return-value]
        return fallback

    def _write_srt(self, output_path: Path, subtitles: Iterable[Any]) -> None:
        entries: List[str] = []
        for index, cue in enumerate(subtitles, start=1):
            text = self._clean_subtitle_text(getattr(cue, "text", ""))
            if not text:
                continue
            start_ms = int(getattr(cue, "start_ms", 0) or 0)
            end_ms = int(getattr(cue, "end_ms", 0) or 0)
            if end_ms <= start_ms:
                continue
            entries.append(
                f"{index}\n{self._format_srt_time(start_ms)} --> {self._format_srt_time(end_ms)}\n{text}\n"
            )
        if entries:
            output_path.write_text("\n".join(entries), encoding="utf-8")

    def _clean_subtitle_text(self, text: Any) -> str:
        normalized = re.sub(r"\s+", " ", str(text or "")).strip()
        if bool(self.effective_config.get("subtitle_strip_trailing_punctuation", True)):
            normalized = normalized.rstrip(TRAILING_SUBTITLE_PUNCTUATION).strip()
        return normalized

    @staticmethod
    def _contains_cjk(text: str) -> bool:
        return any("\u4e00" <= char <= "\u9fff" for char in str(text or ""))

    def _validate_rendered_output(self, output_path: Path) -> None:
        if not output_path.is_file() or output_path.stat().st_size <= 0:
            raise RenderAdapterError(f"rendered video was not created: {output_path}")
        ffprobe_bin = str(self.effective_config.get("ffprobe_bin", "ffprobe")).strip() or "ffprobe"
        if not shutil.which(ffprobe_bin):
            return
        result = subprocess.run(
            [
                ffprobe_bin,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "csv=p=0",
                str(output_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or "video" not in result.stdout:
            raise RenderAdapterError(f"rendered output has no video stream: {output_path}")

    @staticmethod
    def _format_srt_time(value_ms: int) -> str:
        total_ms = max(int(value_ms), 0)
        hours, rem = divmod(total_ms, 3600_000)
        minutes, rem = divmod(rem, 60_000)
        seconds, millis = divmod(rem, 1000)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"

    @staticmethod
    def _parse_resolution(raw: str) -> Tuple[int, int]:
        if "x" not in raw:
            return 1080, 1920
        width, height = raw.lower().split("x", 1)
        return max(int(width), 1), max(int(height), 1)

    @staticmethod
    def _seconds_text(value_ms: int) -> str:
        return f"{max(int(value_ms), 1) / 1000:.3f}"

    @staticmethod
    def _frame_aligned_seconds_text(value_ms: int, fps: int) -> str:
        safe_fps = max(int(fps), 1)
        frames = max(math.ceil(max(int(value_ms), 1) * safe_fps / 1000), 1)
        return f"{frames / safe_fps:.3f}"

    @staticmethod
    def _write_concat_list(path: Path, items: Sequence[Path]) -> None:
        lines = []
        for item in items:
            escaped = str(item.resolve()).replace("'", "'\\''")
            lines.append(f"file '{escaped}'")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _validate_media_source(self, source: str, *, label: str) -> str:
        raw = str(source or "").strip()
        if not raw:
            raise RenderAdapterError(f"{label} source path is empty")
        parsed = urlparse(raw)
        if parsed.scheme in {"http", "https"}:
            return raw
        if "://" in raw and parsed.scheme not in {"", "http", "https"}:
            raise RenderAdapterError(f"{label} source scheme is not supported by rendered video adapter: {raw}")
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = path.resolve()
        if not path.exists():
            raise RenderAdapterError(f"{label} source not found: {path}")
        return str(path)

    @staticmethod
    def _is_image_source(source: str) -> bool:
        return Path(urlparse(source).path).suffix.lower() in IMAGE_EXTS

    @staticmethod
    def _is_generated_black_source(source: str) -> bool:
        return str(source or "").strip() == "generated://black"

    @staticmethod
    def _run_ffmpeg(cmd: Sequence[str], *, label: str) -> None:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode == 0:
            return
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        detail = stderr or stdout or "unknown ffmpeg failure"
        raise RenderAdapterError(f"{label} failed: {detail}")
