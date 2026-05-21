import tempfile
import unittest
from pathlib import Path

from runtime.adapters.jianying import JianyingDraftAdapter
from runtime.models import KernelOutput, ProductionBundle, TimelineModel


class JianyingDryRunTest(unittest.TestCase):
    def test_dry_run_skips_pyjianyingdraft_build(self) -> None:
        adapter = JianyingDraftAdapter({"use_pyjianyingdraft": True, "materialize_local_assets": False})
        bundle = ProductionBundle(job_id="dry-run-test", script_text="test")
        kernel_output = KernelOutput(
            beat_sheet=[],
            edit_decisions=[],
            timeline=TimelineModel(
                job_id="dry-run-test",
                duration_ms=1000,
                resolution="1080x1920",
                fps=30,
                color_space="rec709",
                tracks={"material_track": [], "avatar_track": [], "audio_track": []},
            ),
        )

        with tempfile.TemporaryDirectory() as tmp:
            result = adapter.render(
                output_dir=Path(tmp),
                bundle=bundle,
                kernel_output=kernel_output,
                dry_run=True,
            )

        self.assertEqual(result.status, "dry_run")


if __name__ == "__main__":
    unittest.main()
