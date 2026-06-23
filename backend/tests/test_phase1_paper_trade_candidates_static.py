import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = PROJECT_ROOT / "backend" / "app"
PAPER_TRADE_API = APP_ROOT / "api" / "v1" / "paper_trade_api.py"


class Phase1PaperTradeCandidatesStaticTests(unittest.TestCase):
    def test_paper_trade_candidate_endpoint_is_read_only_gate(self):
        source = PAPER_TRADE_API.read_text(encoding="utf-8")

        self.assertIn('APIRouter(prefix="/paper-trade"', source)
        self.assertIn('@router.get("/candidates")', source)
        self.assertIn("TradePlanRepository", source)
        self.assertIn("RiskRepository", source)
        self.assertIn("get_open_trades(db)", source)
        self.assertIn("latest_for_symbols", source)
        self.assertIn('"source": "paper_trade_candidates"', source)
        self.assertIn('"eligible_count"', source)
        self.assertIn('"blocked_count"', source)

    def test_paper_trade_execute_candidates_is_simulator_only(self):
        source = PAPER_TRADE_API.read_text(encoding="utf-8")

        self.assertIn('@router.post("/execute-candidates")', source)
        self.assertIn("execute_paper_trade_candidates_for_symbol", source)
        self.assertIn('from app.paper_trading.fill_model import build_fill_profile', source)
        self.assertIn("PaperTradeRepository", source)
        self.assertIn("build_paper_trade_candidates", source)
        self.assertIn('fill_profile=candidate.get("fill_profile")', source)
        self.assertIn('payload["fill_profile"] = fill_profile', source)
        self.assertIn("repo.has_open_trade", source)
        self.assertIn("repo.save_candidate", source)
        self.assertIn("skipped_existing_open_paper_trade", source)
        self.assertIn('"source": "paper_trade_execution_simulator"', source)
        self.assertNotIn("binance", source.lower())
        self.assertNotIn("create_order", source)
        self.assertNotIn("place_order", source)

    def test_paper_trade_fill_model_endpoint_exposes_slippage_assumptions(self):
        source = PAPER_TRADE_API.read_text(encoding="utf-8")

        self.assertIn('@router.get("/fill-model")', source)
        self.assertIn("def get_paper_trade_fill_model", source)
        self.assertIn("build_fill_profile(", source)
        self.assertIn('"source": "paper_trade_fill_model"', source)

    def test_paper_trade_status_list_endpoint_exposes_open_and_closed_trades(self):
        source = PAPER_TRADE_API.read_text(encoding="utf-8")

        self.assertIn('@router.get("/trades")', source)
        self.assertIn("def get_paper_trades", source)
        self.assertIn("status: str | None = Query", source)
        self.assertIn("symbol: str | None = Query", source)
        self.assertIn("limit: int = Query", source)
        self.assertIn("repo.list_trades", source)
        self.assertIn('"source": "paper_trades"', source)
        self.assertIn('"status_filter": normalized_status', source)
        self.assertIn('"summary": _summarize_paper_trades(records)', source)
        self.assertIn('"pnl_percent": paper_trade.pnl_percent', source)
        self.assertIn('"closed_at": paper_trade.closed_at', source)

    def test_paper_trade_performance_endpoint_exposes_scorecard(self):
        source = PAPER_TRADE_API.read_text(encoding="utf-8")

        self.assertIn('@router.get("/performance")', source)
        self.assertIn("def get_paper_trade_performance", source)
        self.assertIn("repo.all_trades", source)
        self.assertIn("paper_trade_performance", source)
        self.assertIn('"source": "paper_trade_performance"', source)
        performance_source = (
            APP_ROOT / "paper_trading" / "paper_trade_performance.py"
        ).read_text(encoding="utf-8")
        self.assertIn('"total_trades"', performance_source)
        self.assertIn('"open_trades"', performance_source)
        self.assertIn('"closed_trades"', performance_source)
        self.assertIn('"win_rate"', performance_source)
        self.assertIn('"average_pnl_percent"', performance_source)
        self.assertIn('"total_pnl_percent"', performance_source)

    def test_candidate_requires_matching_fresh_approved_risk(self):
        source = PAPER_TRADE_API.read_text(encoding="utf-8")

        self.assertIn('risk.decision != "APPROVE"', source)
        self.assertIn("Risk decision is stale", source)
        self.assertIn("Risk signal does not match trade side", source)
        self.assertIn("Risk entry does not match trade entry", source)
        self.assertIn("Risk decision is older than trade plan", source)
        self.assertIn("def _same_price", source)

    def test_main_wires_paper_trade_api(self):
        source = (APP_ROOT / "main.py").read_text(encoding="utf-8")

        self.assertIn("paper_trade_api", source)
        self.assertIn("paper_trade_api.router", source)

    def test_risk_repository_exposes_session_aware_latest_lookup(self):
        source = (APP_ROOT / "repositories" / "risk_repository.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("def latest_for_symbol(self, db, symbol)", source)
        self.assertIn("return self.latest_for_symbol(db, symbol)", source)
        self.assertIn("def latest_for_symbols(self, db, symbols)", source)
        self.assertIn("func.max(RiskDecision.created_at)", source)

    def test_paper_trade_repository_blocks_duplicate_open_positions(self):
        source = (APP_ROOT / "repositories" / "paper_trade_repository.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("class PaperTradeRepository", source)
        self.assertIn("PaperTrade.__table__.create", source)
        self.assertIn("checkfirst=True", source)
        self.assertIn("def has_open_trade", source)
        self.assertIn('PaperTrade.status == "OPEN"', source)
        self.assertIn("def save_candidate", source)
        self.assertIn('fill_profile = candidate.get("fill_profile") or {}', source)
        self.assertIn('fill_profile.get("entry_fill_price"', source)
        self.assertIn('fill_profile.get("effective_risk_reward"', source)
        self.assertIn("def list_trades", source)
        self.assertIn("def all_trades", source)
        self.assertIn("query.order_by(PaperTrade.created_at.desc())", source)

    def test_paper_trade_has_an_alembic_migration(self):
        migration = (
            APP_ROOT.parent / "alembic" / "versions" / "b7c9d4f2a6e1_add_paper_trade_tables.py"
        ).read_text(encoding="utf-8")

        self.assertIn("op.create_table(", migration)
        self.assertIn('"paper_trades"', migration)
        self.assertIn('ix_paper_trades_symbol', migration)
        self.assertIn('ix_paper_trades_status', migration)
        self.assertIn('ix_paper_trades_trade_plan_id', migration)
        self.assertIn('down_revision: Union[str, Sequence[str], None] = "ce46732db598"', migration)

    def test_paper_trade_model_tracks_simulated_position_fields(self):
        source = (APP_ROOT / "database" / "models" / "paper_trade.py").read_text(
            encoding="utf-8"
        )
        init_source = (APP_ROOT / "database" / "models" / "__init__.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('__tablename__ = "paper_trades"', source)
        self.assertIn("trade_plan_id", source)
        self.assertIn("risk_decision_id", source)
        self.assertIn("position_size", source)
        self.assertIn('default="OPEN"', source)
        self.assertIn("exit_price", source)
        self.assertIn("pnl_percent", source)
        self.assertIn("closed_at", source)
        self.assertIn("from .paper_trade import PaperTrade", init_source)


if __name__ == "__main__":
    unittest.main()
