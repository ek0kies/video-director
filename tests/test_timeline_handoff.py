import unittest

from runtime.models import KernelOutput, TimelineClip, TimelineModel
from runtime.workflow import VideoDirectorWorkflow, WorkflowError


def _timeline(*, visual_end_ms: int = 5000, visual_media_end_ms: int = 5000) -> TimelineModel:
    visual = TimelineClip(
        clip_id="material-1",
        track="material_track",
        source_path="material.mp4",
        start_ms=0,
        end_ms=visual_end_ms,
        media_start_ms=0,
        media_end_ms=visual_media_end_ms,
        role="broll",
        segment_id="seg-1",
    )
    audio = TimelineClip(
        clip_id="audio-1",
        track="audio_track",
        source_path="audio.wav",
        start_ms=0,
        end_ms=visual_end_ms,
        media_start_ms=0,
        media_end_ms=visual_end_ms,
        role="voice",
        segment_id="seg-1",
    )
    return TimelineModel(
        job_id="handoff-test",
        duration_ms=visual_end_ms,
        resolution="1080x1920",
        fps=30,
        color_space="rec709",
        subtitles=[],
        tracks={
            "material_track": [visual],
            "avatar_track": [],
            "audio_track": [audio],
        },
    )


class TimelineHandoffTest(unittest.TestCase):
    def test_rejects_video_clip_when_source_window_is_shorter_than_target(self) -> None:
        kernel_output = KernelOutput(
            beat_sheet=[],
            edit_decisions=[],
            timeline=_timeline(visual_end_ms=8605, visual_media_end_ms=5005),
        )

        with self.assertRaisesRegex(WorkflowError, "refusing to stretch, loop, or pad media"):
            VideoDirectorWorkflow._validate_timeline_handoff(kernel_output)

    def test_accepts_video_clip_when_source_window_matches_target(self) -> None:
        kernel_output = KernelOutput(
            beat_sheet=[],
            edit_decisions=[],
            timeline=_timeline(visual_end_ms=5000, visual_media_end_ms=5000),
        )

        VideoDirectorWorkflow._validate_timeline_handoff(kernel_output)


if __name__ == "__main__":
    unittest.main()
