import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
AI_SCORES_API = PROJECT_ROOT / "backend" / "app" / "api" / "v1" / "ai_scores_api.py"


class Phase0AIScoresStaticTests(unittest.TestCase):
    def test_ai_scores_has_computed_fallback_when_table_empty(self):
        source = AI_SCORES_API.read_text(encoding="utf-8")

        self.assertIn("computed_current", source)
        self.assertIn("COMPUTED_NOT_PERSISTED", source)
        self.assertIn("_compute_current_score", source)
        self.assertIn("get_ai_inputs", source)


if __name__ == "__main__":
    unittest.main()
