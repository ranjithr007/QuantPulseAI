import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = PROJECT_ROOT / "backend" / "app"


class Phase1SymbolRepositoryStaticTests(unittest.TestCase):
    def test_active_symbols_are_deduped_before_scheduler_and_watchlist_use(self):
        source = (APP_ROOT / "repositories" / "symbol_repository.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("def _dedupe_symbols", source)
        self.assertIn("normalized = item.symbol.upper()", source)
        self.assertIn("if normalized in seen", source)
        self.assertIn("order_by(Symbol.symbol.asc(), Symbol.id.asc())", source)

    def test_symbols_api_uses_repository_for_consistent_deduping(self):
        source = (APP_ROOT / "api" / "v1" / "symbols_api.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("SymbolRepository().get_active_symbols(db)", source)


if __name__ == "__main__":
    unittest.main()
