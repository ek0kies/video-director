import unittest

from runtime.adapters.jianying import JianyingDraftAdapter


class JianyingSubtitlesTest(unittest.TestCase):
    def test_strips_trailing_punctuation_by_default(self) -> None:
        adapter = JianyingDraftAdapter({})

        self.assertEqual(adapter._clean_subtitle_text("花开成景，人聚成春。"), "花开成景，人聚成春")
        self.assertEqual(adapter._clean_subtitle_text("来梨花节，赴春日约会！"), "来梨花节，赴春日约会")

    def test_can_keep_trailing_punctuation_when_configured(self) -> None:
        adapter = JianyingDraftAdapter({"subtitles": {"subtitle_strip_trailing_punctuation": False}})

        self.assertEqual(adapter._clean_subtitle_text("花开成景，人聚成春。"), "花开成景，人聚成春。")


if __name__ == "__main__":
    unittest.main()
