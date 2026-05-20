"""Core data models for the Video Director pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Dict, List, Optional


def to_dict(value: Any) -> Any:
    """Recursively convert dataclasses and containers into JSON-ready values."""
    if is_dataclass(value):
        return {key: to_dict(val) for key, val in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): to_dict(val) for key, val in value.items()}
    if isinstance(value, list):
        return [to_dict(item) for item in value]
    return value


@dataclass
class MaterialAsset:
    """Reusable B-roll or still asset that can be selected by the edit kernel."""

    asset_id: str
    path: str
    media_type: str = "video"
    duration_ms: Optional[int] = None
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AudioClip:
    """Per-beat narration clip produced by TTS or any other voice generator."""

    segment_id: str
    audio_path: str
    start_ms: int
    end_ms: int
    text: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AvatarClip:
    """Per-beat avatar clip produced by a digital-human provider."""

    segment_id: str
    video_path: str
    audio_path: str = ""
    start_ms: int = 0
    end_ms: int = 0
    text: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProductionBundle:
    """Normalized upstream production result before edit planning starts."""

    job_id: str
    script_text: str
    topic_hint: str = ""
    avatar_image_path: str = ""
    full_tts_audio_path: str = ""
    full_tts_duration_ms: Optional[int] = None
    materials: List[MaterialAsset] = field(default_factory=list)
    tts_clips: List[AudioClip] = field(default_factory=list)
    avatar_clips: List[AvatarClip] = field(default_factory=list)
    understanding: Dict[str, Any] = field(default_factory=dict)
    copy_review: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Beat:
    """Narration-first edit unit."""

    beat_id: str
    text: str
    segment_type: str
    start_ms: int
    end_ms: int
    keywords: List[str] = field(default_factory=list)
    selected_asset_id: str = ""
    selected_avatar_id: str = ""


@dataclass
class EditDecision:
    """Why a beat was mapped to a specific source."""

    beat_id: str
    segment_type: str
    source_type: str
    source_ref: str
    start_ms: int
    end_ms: int
    reason: str
    text: str


@dataclass
class SubtitleCue:
    """Subtitle cue generated from a beat."""

    cue_id: str
    text: str
    start_ms: int
    end_ms: int


@dataclass
class TimelineClip:
    """Canonical clip used by every downstream adapter."""

    clip_id: str
    track: str
    source_path: str
    start_ms: int
    end_ms: int
    media_start_ms: int = 0
    media_end_ms: Optional[int] = None
    role: str = ""
    segment_id: str = ""
    text: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TimelineModel:
    """Canonical edit result consumed by multiple output adapters."""

    job_id: str
    duration_ms: int
    resolution: str
    fps: int
    color_space: str
    beats: List[Beat] = field(default_factory=list)
    subtitles: List[SubtitleCue] = field(default_factory=list)
    tracks: Dict[str, List[TimelineClip]] = field(default_factory=dict)
    style_profile: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class KernelOutput:
    """Complete result emitted by the edit kernel."""

    beat_sheet: List[Beat]
    edit_decisions: List[EditDecision]
    timeline: TimelineModel


@dataclass
class AdapterResult:
    """Result returned by a single output adapter."""

    target: str
    status: str
    artifact_path: str
    note: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
