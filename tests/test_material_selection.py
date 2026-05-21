import unittest
from collections import defaultdict

from runtime.kernel import NarrationFirstEditKernel
from runtime.models import MaterialAsset, ProductionBundle


class MaterialSelectionTest(unittest.TestCase):
    def test_prefers_material_that_can_cover_requested_duration(self) -> None:
        kernel = NarrationFirstEditKernel({"max_material_reuse": 1})
        bundle = ProductionBundle(
            job_id="material-selection-test",
            script_text="test",
            materials=[
                MaterialAsset(asset_id="short", path="short.mp4", duration_ms=5000),
                MaterialAsset(asset_id="long", path="long.mp4", duration_ms=12000),
            ],
        )

        material, _cursor, _reuse_index = kernel._pick_material(
            bundle,
            text="",
            keywords=[],
            material_reuse=defaultdict(int),
            cursor=0,
            requested_duration_ms=9000,
        )

        self.assertEqual(material.asset_id, "long")


if __name__ == "__main__":
    unittest.main()
