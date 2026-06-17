import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Phase0StartScriptStaticTests(unittest.TestCase):
    def test_start_script_sets_setuptools_workaround_before_uvicorn(self):
        source = (PROJECT_ROOT / "backend" / "start_backend.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn("SETUPTOOLS_USE_DISTUTILS", source)
        self.assertIn("stdlib", source)
        self.assertIn("uvicorn app.main:app --reload", source)


if __name__ == "__main__":
    unittest.main()
