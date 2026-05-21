"""Narration-first edit kernel for Video Director."""

from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .models import Beat, EditDecision, KernelOutput, MaterialAsset, ProductionBundle, SubtitleCue, TimelineClip, TimelineModel


class KernelConfigError(ValueError):
    """Raised when edit-kernel configuration is invalid."""


class NarrationFirstEditKernel:
    """Build a canonical edit plan from script, assets, and production outputs."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.resolution = str(config.get("resolution", "1080x1920"))
        self.fps = int(config.get("fps", 30))
        self.color_space = str(config.get("color_space", "rec709"))
        self.min_segment_ms = int(config.get("min_segment_ms", 2500))
        self.chars_per_second = float(config.get("chars_per_second", 4.0))
        self.enable_avatar_timeline = bool(config.get("enable_avatar_timeline", True))
        self.preserve_avatar_beats_without_clips = bool(config.get("preserve_avatar_beats_without_clips", False))
        self.avatar_opening_segments = int(config.get("avatar_opening_segments", 1))
        self.avatar_middle_segments = int(config.get("avatar_middle_segments", 1))
        self.avatar_ending_segments = int(config.get("avatar_ending_segments", 1))
        self.avatar_min_segments_for_middle = int(config.get("avatar_min_segments_for_middle", 6))
        self.max_material_reuse = int(config.get("max_material_reuse", 2))
        self.material_duration_policy = str(config.get("material_duration_policy", "cap")).strip().lower() or "cap"
        self.subtitle_mode = str(config.get("subtitle_mode", "sentence")).strip().lower() or "sentence"
        self.subtitle_phrase_max_chars = max(int(config.get("subtitle_phrase_max_chars", 18)), 4)
        self.subtitle_phrase_pause_weight = max(float(config.get("subtitle_phrase_pause_weight", 2.0)), 0.0)
        self.subtitle_min_cue_ms = max(int(config.get("subtitle_min_cue_ms", 450)), 1)
        self.final_tail_frames = max(int(config.get("final_tail_frames", 0) or 0), 0)
        configured_tail_ms = max(int(config.get("final_tail_buffer_ms", 0) or 0), 0)
        frame_tail_ms = math.ceil(self.final_tail_frames * 1000 / max(self.fps, 1)) if self.final_tail_frames > 0 else 0
        self.final_tail_buffer_ms = frame_tail_ms or configured_tail_ms
        self.final_fade_out_ms = max(int(config.get("final_fade_out_ms", 450) or 0), 0)

    def build(self, bundle: ProductionBundle) -> KernelOutput:
        sentences = self._split_sentences(bundle.script_text)
        if not sentences:
            raise KernelConfigError("script_text cannot be split into valid narration beats")

        durations = self._resolve_beat_durations(sentences, bundle)
        avatar_indexes = self._pick_avatar_indexes(len(sentences)) if self.enable_avatar_timeline else set()
        narrative_keywords = self._extract_narrative_keywords(bundle.understanding)
        durations = self._fit_durations_to_visual_materials(
            sentences=sentences,
            durations=durations,
            bundle=bundle,
            avatar_indexes=avatar_indexes,
            narrative_keywords=narrative_keywords,
        )
        avatar_by_segment, avatar_by_order = self._index_avatar_clips(bundle) if self.enable_avatar_timeline else ({}, [])
        audio_by_segment, audio_by_order = self._index_audio_clips(bundle)

        beats: List[Beat] = []
        edit_decisions: List[EditDecision] = []
        subtitles: List[SubtitleCue] = []
        material_track: List[TimelineClip] = []
        avatar_track: List[TimelineClip] = []
        audio_track: List[TimelineClip] = []
        material_reuse: Dict[str, int] = defaultdict(int)
        single_full_audio = bool(bundle.full_tts_audio_path and not bundle.tts_clips)

        current_start = 0
        avatar_cursor = 0
        audio_cursor = 0
        material_cursor = 0

        for index, text in enumerate(sentences, start=1):
            start_ms = current_start
            end_ms = start_ms + durations[index - 1]
            current_start = end_ms
            beat_id = f"seg-{index}"
            keywords = self._extract_keywords(text, narrative_keywords)
            segment_type = "AVATAR" if index in avatar_indexes else "B_ROLL"

            beat = Beat(
                beat_id=beat_id,
                text=text,
                segment_type=segment_type,
                start_ms=start_ms,
                end_ms=end_ms,
                keywords=keywords,
            )

            subtitles.extend(
                self._build_subtitle_cues(
                    beat_index=index,
                    text=text,
                    start_ms=start_ms,
                    end_ms=end_ms,
                )
            )

            if segment_type == "AVATAR":
                avatar_clip, avatar_cursor = self._pick_avatar_clip(
                    beat_id=beat_id,
                    avatar_by_segment=avatar_by_segment,
                    avatar_by_order=avatar_by_order,
                    cursor=avatar_cursor,
                )
                if avatar_clip is not None:
                    beat.selected_avatar_id = avatar_clip.segment_id
                    avatar_track.append(
                        TimelineClip(
                            clip_id=f"avatar-{index}",
                            track="avatar_track",
                            source_path=avatar_clip.video_path,
                            start_ms=start_ms,
                            end_ms=end_ms,
                            media_start_ms=0,
                            media_end_ms=max(end_ms - start_ms, 1),
                            role="avatar",
                            segment_id=beat_id,
                            text=text,
                            metadata=avatar_clip.metadata,
                        )
                    )
                    edit_decisions.append(
                        EditDecision(
                            beat_id=beat_id,
                            segment_type=segment_type,
                            source_type="avatar_video",
                            source_ref=avatar_clip.video_path,
                            start_ms=start_ms,
                            end_ms=end_ms,
                            reason="avatar anchor beat selected by narration-first layout",
                            text=text,
                        )
                    )

            if segment_type == "AVATAR" and not beat.selected_avatar_id and not self.preserve_avatar_beats_without_clips:
                beat.segment_type = "B_ROLL"
                segment_type = "B_ROLL"

            if segment_type == "B_ROLL":
                material, material_cursor, reuse_index = self._pick_material(bundle, text, keywords, material_reuse, material_cursor)
                media_start_ms, media_end_ms, media_metadata = self._material_media_window(
                    material=material,
                    duration_ms=end_ms - start_ms,
                    reuse_index=reuse_index,
                )
                beat.selected_asset_id = material.asset_id
                material_track.append(
                    TimelineClip(
                        clip_id=f"material-{index}",
                        track="material_track",
                        source_path=material.path,
                        start_ms=start_ms,
                        end_ms=end_ms,
                        media_start_ms=media_start_ms,
                        media_end_ms=media_end_ms,
                        role="broll",
                        segment_id=beat_id,
                        text=text,
                        metadata={"asset_id": material.asset_id, "tags": material.tags, **material.metadata, **media_metadata},
                    )
                )
                edit_decisions.append(
                    EditDecision(
                        beat_id=beat_id,
                        segment_type=segment_type,
                        source_type="material",
                        source_ref=material.path,
                        start_ms=start_ms,
                        end_ms=end_ms,
                        reason=self._build_material_reason(material, keywords, material_reuse[material.asset_id]),
                        text=text,
                    )
                )

            if not single_full_audio:
                audio_clip, audio_cursor = self._pick_audio_clip(
                    beat_id=beat_id,
                    full_audio_path=bundle.full_tts_audio_path,
                    audio_by_segment=audio_by_segment,
                    audio_by_order=audio_by_order,
                    cursor=audio_cursor,
                )
                if audio_clip is not None:
                    audio_track.append(
                        TimelineClip(
                            clip_id=f"audio-{index}",
                            track="audio_track",
                            source_path=audio_clip["path"],
                            start_ms=start_ms,
                            end_ms=end_ms,
                            media_start_ms=int(audio_clip.get("media_start_ms", 0) or 0),
                            media_end_ms=int(audio_clip.get("media_end_ms", end_ms - start_ms) or (end_ms - start_ms)),
                            role="voice",
                            segment_id=beat_id,
                            text=text,
                            metadata=audio_clip.get("metadata", {}),
                        )
                    )

            beats.append(beat)

        duration_ms = current_start
        if single_full_audio:
            audio_track.append(
                TimelineClip(
                    clip_id="audio-full",
                    track="audio_track",
                    source_path=bundle.full_tts_audio_path,
                    start_ms=0,
                    end_ms=duration_ms,
                    media_start_ms=0,
                    media_end_ms=duration_ms,
                    role="voice",
                    segment_id="full-track",
                    text=bundle.script_text,
                    metadata={"source": "full_tts_audio_path"},
                )
            )
        duration_ms = self._extend_final_visual_tail(material_track, avatar_track, duration_ms)
        timeline = TimelineModel(
            job_id=bundle.job_id,
            duration_ms=duration_ms,
            resolution=self.resolution,
            fps=self.fps,
            color_space=self.color_space,
            beats=beats,
            subtitles=subtitles,
            tracks={
                "material_track": material_track,
                "avatar_track": avatar_track,
                "audio_track": audio_track,
            },
            style_profile={
                "strategy": "narration_first",
                "enable_avatar_timeline": self.enable_avatar_timeline,
                "avatar_opening_segments": self.avatar_opening_segments,
                "avatar_middle_segments": self.avatar_middle_segments,
                "avatar_ending_segments": self.avatar_ending_segments,
                "max_material_reuse": self.max_material_reuse,
            },
            metadata={
                "materials_count": len(bundle.materials),
                "tts_clip_count": len(bundle.tts_clips),
                "avatar_clip_count": len(bundle.avatar_clips),
                "final_tail_frames": self.final_tail_frames,
                "final_tail_buffer_ms": self.final_tail_buffer_ms,
                "final_fade_out_ms": self.final_fade_out_ms,
            },
        )
        return KernelOutput(beat_sheet=beats, edit_decisions=edit_decisions, timeline=timeline)

    def _extend_final_visual_tail(
        self,
        material_track: Sequence[TimelineClip],
        avatar_track: Sequence[TimelineClip],
        timeline_end_ms: int,
    ) -> int:
        if self.final_tail_buffer_ms <= 0 or timeline_end_ms <= 0:
            self._mark_final_visual_fade(material_track, avatar_track, timeline_end_ms)
            return timeline_end_ms
        candidates = [
            clip
            for clip in list(material_track) + list(avatar_track)
            if clip.source_path
            and clip.source_path != "generated://black"
            and clip.end_ms == timeline_end_ms
            and clip.end_ms > clip.start_ms
        ]
        if not candidates:
            self._mark_final_visual_fade(material_track, avatar_track, timeline_end_ms)
            return timeline_end_ms

        final_clip = candidates[-1]
        visual_end_ms = timeline_end_ms + self.final_tail_buffer_ms
        final_clip.end_ms = visual_end_ms
        final_clip.metadata = dict(final_clip.metadata or {})
        final_clip.metadata["final_tail_strategy"] = "hold_last_visual"
        final_clip.metadata["final_tail_buffer_ms"] = self.final_tail_buffer_ms
        final_clip.metadata["allow_source_stretch"] = True
        final_clip.metadata["suppress_default_fade_out"] = True
        final_clip.metadata["tail_reason"] = "hold final visual after narration instead of adding black frames"
        self._mark_final_visual_fade(material_track, avatar_track, visual_end_ms)
        return visual_end_ms

    def _mark_final_visual_fade(
        self,
        material_track: Sequence[TimelineClip],
        avatar_track: Sequence[TimelineClip],
        timeline_end_ms: int,
    ) -> None:
        if self.final_fade_out_ms <= 0:
            return
        candidates = [
            clip
            for clip in list(material_track) + list(avatar_track)
            if clip.source_path and clip.end_ms == timeline_end_ms and clip.end_ms > clip.start_ms
        ]
        if not candidates:
            return
        final_clip = candidates[-1]
        fade_ms = min(self.final_fade_out_ms, final_clip.end_ms - final_clip.start_ms)
        if fade_ms <= 0:
            return
        final_clip.metadata = dict(final_clip.metadata or {})
        final_clip.metadata["fade_out_ms"] = fade_ms
        final_clip.metadata["fade_reason"] = "fade final visual at natural ending"

    @staticmethod
    def _split_sentences(script_text: str) -> List[str]:
        raw_parts = re.split(r"[。！？!?；;\n]+", script_text)
        return [part.strip() for part in raw_parts if part.strip()]

    def _resolve_beat_durations(self, sentences: Sequence[str], bundle: ProductionBundle) -> List[int]:
        if bundle.tts_clips and len(bundle.tts_clips) == len(sentences):
            durations = [max(int(clip.end_ms - clip.start_ms), 1) for clip in bundle.tts_clips]
            return self._normalize_total_duration(durations, sum(durations))

        if bundle.full_tts_duration_ms and bundle.full_tts_duration_ms > 0:
            return self._allocate_by_weight(sentences, bundle.full_tts_duration_ms, min_segment_ms=1)

        estimated_total = int(
            math.ceil(max(len(re.sub(r"\s+", "", bundle.script_text)), 1) / max(self.chars_per_second, 0.1) * 1000)
        )
        estimated_total = max(estimated_total, len(sentences) * self.min_segment_ms)
        return self._allocate_by_weight(sentences, estimated_total)

    def _fit_durations_to_visual_materials(
        self,
        *,
        sentences: Sequence[str],
        durations: Sequence[int],
        bundle: ProductionBundle,
        avatar_indexes: set[int],
        narrative_keywords: Sequence[str],
    ) -> List[int]:
        if self.material_duration_policy == "ignore" or not bundle.materials:
            return list(durations)

        material_reuse: Dict[str, int] = defaultdict(int)
        material_cursor = 0
        caps: List[Optional[int]] = []
        for index, text in enumerate(sentences, start=1):
            if index in avatar_indexes:
                caps.append(None)
                continue
            keywords = self._extract_keywords(text, narrative_keywords)
            material, material_cursor, _reuse_index = self._pick_material(
                bundle,
                text,
                keywords,
                material_reuse,
                material_cursor,
            )
            caps.append(self._material_duration_cap(material))

        known_caps = [cap for cap in caps if cap is not None]
        if not known_caps:
            return list(durations)

        fitted = self._fit_durations_to_caps(durations, caps)
        if fitted == list(durations):
            return fitted

        fixed_audio = bool(bundle.tts_clips) or bool(bundle.full_tts_audio_path)
        if fixed_audio or self.material_duration_policy == "error":
            raise KernelConfigError(
                "visual materials cannot support the narration duration; "
                f"requested_ms={sum(durations)}, material_supported_ms={sum(fitted)}, "
                "shorten/regenerate narration or provide more usable material"
            )
        if self.material_duration_policy != "cap":
            raise KernelConfigError(
                "editing.material_duration_policy must be one of: cap, error, ignore"
            )
        return fitted

    @staticmethod
    def _material_duration_cap(material: MaterialAsset) -> Optional[int]:
        if str(material.media_type).strip().lower() in {"image", "photo", "still"}:
            return None
        if material.duration_ms is None:
            return None
        return max(int(material.duration_ms), 1)

    @classmethod
    def _fit_durations_to_caps(cls, durations: Sequence[int], caps: Sequence[Optional[int]]) -> List[int]:
        fitted = [max(int(duration), 1) for duration in durations]
        if len(fitted) != len(caps):
            return fitted

        overflow = 0
        for index, cap in enumerate(caps):
            if cap is None:
                continue
            safe_cap = max(int(cap), 1)
            if fitted[index] > safe_cap:
                overflow += fitted[index] - safe_cap
                fitted[index] = safe_cap

        if overflow <= 0:
            return fitted

        for index, cap in enumerate(caps):
            if overflow <= 0:
                break
            if cap is None:
                fitted[index] += overflow
                overflow = 0
                break
            spare = max(int(cap) - fitted[index], 0)
            if spare <= 0:
                continue
            added = min(spare, overflow)
            fitted[index] += added
            overflow -= added

        return [max(int(duration), 1) for duration in fitted]

    def _build_subtitle_cues(self, *, beat_index: int, text: str, start_ms: int, end_ms: int) -> List[SubtitleCue]:
        if self.subtitle_mode != "phrase_proportional":
            return [
                SubtitleCue(
                    cue_id=f"sub-{beat_index}",
                    text=text,
                    start_ms=start_ms,
                    end_ms=end_ms,
                )
            ]

        phrases = self._split_subtitle_phrases(text)
        if len(phrases) <= 1:
            return [
                SubtitleCue(
                    cue_id=f"sub-{beat_index}",
                    text=text,
                    start_ms=start_ms,
                    end_ms=end_ms,
                )
            ]

        total_ms = max(end_ms - start_ms, 1)
        weights = [self._subtitle_phrase_weight(phrase) for phrase in phrases]
        durations = self._allocate_by_numeric_weights(weights, total_ms, min_segment_ms=self.subtitle_min_cue_ms)
        cues: List[SubtitleCue] = []
        current_start = start_ms
        for phrase_index, (phrase, duration_ms) in enumerate(zip(phrases, durations), start=1):
            cue_end = current_start + duration_ms
            cues.append(
                SubtitleCue(
                    cue_id=f"sub-{beat_index}-{phrase_index}",
                    text=phrase,
                    start_ms=current_start,
                    end_ms=cue_end,
                )
            )
            current_start = cue_end
        if cues:
            cues[-1].end_ms = end_ms
        return cues

    def _split_subtitle_phrases(self, text: str) -> List[str]:
        normalized_text = str(text or "").strip()
        if not normalized_text:
            return []

        tokens = [token for token in re.split(r"([，、；：,;:])", normalized_text) if token]
        phrases: List[str] = []
        buffer = ""
        for token in tokens:
            if re.fullmatch(r"[，、；：,;:]", token):
                buffer += token
                phrases.extend(self._split_long_subtitle_phrase(buffer))
                buffer = ""
            else:
                buffer += token.strip()
        if buffer.strip():
            phrases.extend(self._split_long_subtitle_phrase(buffer))
        return [phrase for phrase in phrases if phrase]

    def _split_long_subtitle_phrase(self, phrase: str) -> List[str]:
        compact = str(phrase or "").strip()
        if not compact:
            return []
        visible_len = len(re.sub(r"\s+", "", compact))
        if visible_len <= self.subtitle_phrase_max_chars:
            return [compact]

        chunks: List[str] = []
        cursor = 0
        while cursor < len(compact):
            chunk = compact[cursor : cursor + self.subtitle_phrase_max_chars].strip()
            if chunk:
                chunks.append(chunk)
            cursor += self.subtitle_phrase_max_chars
        min_tail_chars = min(4, max(self.subtitle_phrase_max_chars // 3, 2))
        if len(chunks) >= 2 and self._subtitle_visible_len(chunks[-1]) < min_tail_chars:
            merged_tail = f"{chunks[-2]}{chunks[-1]}"
            merged_visible_len = self._subtitle_visible_len(merged_tail)
            if merged_visible_len <= self.subtitle_phrase_max_chars:
                chunks[-2:] = [merged_tail]
            else:
                split_at = max(merged_visible_len - self.subtitle_phrase_max_chars, min_tail_chars)
                split_at = min(split_at, merged_visible_len - min_tail_chars)
                chunks[-2:] = [merged_tail[:split_at].strip(), merged_tail[split_at:].strip()]
        return chunks

    def _subtitle_phrase_weight(self, phrase: str) -> float:
        normalized = re.sub(r"\s+", "", str(phrase or ""))
        pause_count = len(re.findall(r"[，、；：,;:]", normalized))
        visible_chars = len(re.sub(r"[，、；：,;:]", "", normalized))
        return max(visible_chars + pause_count * self.subtitle_phrase_pause_weight, 1.0)

    @staticmethod
    def _subtitle_visible_len(text: str) -> int:
        return len(re.sub(r"\s+", "", str(text or "")))

    def _allocate_by_numeric_weights(
        self,
        weights: Sequence[float],
        total_ms: int,
        *,
        min_segment_ms: int,
    ) -> List[int]:
        if not weights:
            return []
        effective_min_segment_ms = max(int(min_segment_ms), 1)
        if total_ms < effective_min_segment_ms * len(weights):
            effective_min_segment_ms = max(total_ms // len(weights), 1)
        safe_weights = [max(float(weight), 1.0) for weight in weights]
        total_weight = sum(safe_weights)
        durations = [max(effective_min_segment_ms, int(total_ms * weight / total_weight)) for weight in safe_weights]
        return self._normalize_exact_total(durations, total_ms, min_segment_ms=effective_min_segment_ms)

    def _allocate_by_weight(self, sentences: Sequence[str], total_ms: int, *, min_segment_ms: Optional[int] = None) -> List[int]:
        effective_min_segment_ms = self.min_segment_ms if min_segment_ms is None else max(int(min_segment_ms), 1)
        weights = [max(len(re.sub(r"\s+", "", sentence)), 1) for sentence in sentences]
        total_weight = sum(weights)
        durations = [max(effective_min_segment_ms, int(total_ms * weight / total_weight)) for weight in weights]
        return self._normalize_total_duration(durations, max(total_ms, len(sentences) * effective_min_segment_ms))

    @staticmethod
    def _normalize_total_duration(durations: List[int], target_total: int) -> List[int]:
        normalized = list(durations)
        current_total = sum(normalized)
        delta = target_total - current_total
        if not normalized:
            return normalized
        normalized[-1] = max(normalized[-1] + delta, 1)
        return normalized

    @staticmethod
    def _normalize_exact_total(durations: List[int], target_total: int, *, min_segment_ms: int) -> List[int]:
        if not durations:
            return []
        normalized = [max(int(duration), min_segment_ms) for duration in durations]
        delta = target_total - sum(normalized)
        if delta > 0:
            normalized[-1] += delta
            return normalized
        if delta == 0:
            return normalized

        remaining = -delta
        for index in range(len(normalized) - 1, -1, -1):
            reducible = max(normalized[index] - min_segment_ms, 0)
            if reducible <= 0:
                continue
            reduction = min(reducible, remaining)
            normalized[index] -= reduction
            remaining -= reduction
            if remaining == 0:
                break

        if remaining > 0:
            normalized[-1] = max(target_total - sum(normalized[:-1]), min_segment_ms)
        normalized[-1] += target_total - sum(normalized)
        return normalized

    def _pick_avatar_indexes(self, count: int) -> set[int]:
        indexes: set[int] = set()
        for offset in range(min(self.avatar_opening_segments, count)):
            indexes.add(offset + 1)

        if count >= self.avatar_min_segments_for_middle and self.avatar_middle_segments > 0:
            for slot in range(self.avatar_middle_segments):
                position = int(round((slot + 1) * (count + 1) / (self.avatar_middle_segments + 1)))
                indexes.add(max(min(position, count), 1))

        for offset in range(min(self.avatar_ending_segments, count)):
            indexes.add(count - offset)
        return indexes

    @staticmethod
    def _index_avatar_clips(bundle: ProductionBundle) -> Tuple[Dict[str, Any], List[Any]]:
        by_segment = {clip.segment_id: clip for clip in bundle.avatar_clips if clip.video_path}
        ordered = [clip for clip in bundle.avatar_clips if clip.video_path]
        return by_segment, ordered

    @staticmethod
    def _index_audio_clips(bundle: ProductionBundle) -> Tuple[Dict[str, Any], List[Any]]:
        by_segment = {clip.segment_id: clip for clip in bundle.tts_clips if clip.audio_path}
        ordered = [clip for clip in bundle.tts_clips if clip.audio_path]
        return by_segment, ordered

    def _pick_avatar_clip(
        self,
        *,
        beat_id: str,
        avatar_by_segment: Dict[str, Any],
        avatar_by_order: List[Any],
        cursor: int,
    ) -> Tuple[Optional[Any], int]:
        if beat_id in avatar_by_segment:
            clip = avatar_by_segment[beat_id]
            next_cursor = cursor
            for index, candidate in enumerate(avatar_by_order):
                if candidate.segment_id == clip.segment_id and index >= cursor:
                    next_cursor = index + 1
                    break
            return clip, next_cursor
        if cursor < len(avatar_by_order):
            return avatar_by_order[cursor], cursor + 1
        return None, cursor

    def _pick_audio_clip(
        self,
        *,
        beat_id: str,
        full_audio_path: str,
        audio_by_segment: Dict[str, Any],
        audio_by_order: List[Any],
        cursor: int,
    ) -> Tuple[Optional[Dict[str, Any]], int]:
        if beat_id in audio_by_segment:
            clip = audio_by_segment[beat_id]
            next_cursor = cursor
            for index, candidate in enumerate(audio_by_order):
                if candidate.segment_id == clip.segment_id and index >= cursor:
                    next_cursor = index + 1
                    break
            return {
                "path": clip.audio_path,
                "media_start_ms": 0,
                "media_end_ms": max(clip.end_ms - clip.start_ms, 1),
                "metadata": clip.metadata,
            }, next_cursor
        if cursor < len(audio_by_order):
            clip = audio_by_order[cursor]
            return {
                "path": clip.audio_path,
                "media_start_ms": 0,
                "media_end_ms": max(clip.end_ms - clip.start_ms, 1),
                "metadata": clip.metadata,
            }, cursor + 1
        if full_audio_path:
            return {"path": full_audio_path, "media_start_ms": 0, "media_end_ms": None, "metadata": {}}, cursor
        return None, cursor

    def _pick_material(
        self,
        bundle: ProductionBundle,
        text: str,
        keywords: Sequence[str],
        material_reuse: Dict[str, int],
        cursor: int,
    ):
        best_score: Optional[Tuple[int, int, int]] = None
        best_material = bundle.materials[0]
        for index, material in enumerate(bundle.materials):
            score = self._score_material(material.tags, text, keywords)
            reuse_penalty = material_reuse[material.asset_id]
            score_tuple = (score - reuse_penalty * 2, -reuse_penalty, -abs(index - cursor))
            if material_reuse[material.asset_id] >= self.max_material_reuse and score <= 0:
                continue
            if best_score is None or score_tuple > best_score:
                best_score = score_tuple
                best_material = material
        reuse_index = material_reuse[best_material.asset_id]
        material_reuse[best_material.asset_id] += 1
        next_cursor = (bundle.materials.index(best_material) + 1) % max(len(bundle.materials), 1)
        return best_material, next_cursor, reuse_index

    def _material_media_window(
        self,
        *,
        material: MaterialAsset,
        duration_ms: int,
        reuse_index: int,
    ) -> Tuple[int, Optional[int], Dict[str, Any]]:
        cap = self._material_duration_cap(material)
        metadata: Dict[str, Any] = {"reuse_index": max(int(reuse_index), 0)}
        if cap is None:
            return 0, material.duration_ms, metadata

        requested_ms = max(int(duration_ms), 1)
        if requested_ms >= cap:
            if requested_ms > cap:
                metadata["visual_shortfall_ms"] = requested_ms - cap
            return 0, cap, metadata

        max_start_ms = max(cap - requested_ms, 0)
        if max_start_ms <= 0:
            return 0, requested_ms, metadata
        if self.max_material_reuse <= 1:
            start_ms = 0
        else:
            slot = max(int(reuse_index), 0) % self.max_material_reuse
            start_ms = int(round(max_start_ms * slot / max(self.max_material_reuse - 1, 1)))
        metadata["media_window_reason"] = "reuse_offset"
        return start_ms, min(start_ms + requested_ms, cap), metadata

    @staticmethod
    def _score_material(tags: Sequence[str], text: str, keywords: Sequence[str]) -> int:
        score = 0
        lowered_text = text.lower()
        lowered_keywords = [keyword.lower() for keyword in keywords]
        for tag in tags:
            lowered_tag = tag.lower()
            if lowered_tag in lowered_text:
                score += 4
            if any(lowered_tag in keyword or keyword in lowered_tag for keyword in lowered_keywords):
                score += 3
        return score

    @staticmethod
    def _build_material_reason(material, keywords: Sequence[str], reuse_count: int) -> str:
        if keywords:
            return f"matched material tags against beat keywords={list(keywords)} reuse={reuse_count}"
        return f"fallback material rotation reuse={reuse_count}"

    @staticmethod
    def _extract_narrative_keywords(understanding: Dict[str, Any]) -> List[str]:
        keywords: List[str] = []
        if not isinstance(understanding, dict):
            return keywords
        for group in understanding.get("narrative_groups", []) or []:
            if not isinstance(group, dict):
                continue
            for item in group.get("ocr_keywords", []) or []:
                text = str(item).strip()
                if text and text not in keywords:
                    keywords.append(text)
        return keywords

    @staticmethod
    def _extract_keywords(text: str, narrative_keywords: Sequence[str]) -> List[str]:
        candidates = [keyword for keyword in narrative_keywords if keyword and keyword in text]
        if candidates:
            return candidates[:4]
        raw_tokens = re.findall(r"[A-Za-z0-9]{3,}|[\u4e00-\u9fff]{2,}", text)
        deduped: List[str] = []
        for token in raw_tokens:
            if token not in deduped:
                deduped.append(token)
        return deduped[:4]
