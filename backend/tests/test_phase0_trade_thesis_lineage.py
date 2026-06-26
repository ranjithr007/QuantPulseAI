from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models.paper_trade import PaperTrade
from app.database.models.thesis_snapshots import ThesisSnapshot
from app.database.models.trade_plan import TradePlan
from app.database.models.trade_thesis import TradeThesis
from app.repositories.paper_trade_repository import PaperTradeRepository
from app.repositories.trade_plan_repository import TradePlanRepository


def _session():
    engine = create_engine("sqlite:///:memory:")
    TradePlan.__table__.create(bind=engine)
    PaperTrade.__table__.create(bind=engine)
    TradeThesis.__table__.create(bind=engine)
    return sessionmaker(bind=engine)()


def test_trade_plan_save_creates_thesis_and_updates_lifecycle():
    db = _session()

    try:
        trade = TradePlanRepository().save_trade_plan(
            db,
            {
                "symbol": "BTCUSDT",
                "side": "LONG",
                "entry": 100.0,
                "stop_loss": 98.0,
                "targets": [104.0, 106.0, 108.0],
                "rr": 2.0,
                "confidence": 82.0,
                "mode": "intraday",
                "entry_timeframe": "1h",
                "timeframe_stack": ["5m", "15m", "1h"],
                "regime": "TRENDING_BULL",
                "scenario": {"name": "breakout"},
                "contradiction": {"name": "no_pullback"},
            },
        )

        thesis = db.query(TradeThesis).filter(TradeThesis.id == trade.thesis_id).one()
        snapshots = (
            db.query(ThesisSnapshot)
            .filter(ThesisSnapshot.thesis_id == thesis.id)
            .order_by(ThesisSnapshot.effective_timestamp.asc(), ThesisSnapshot.id.asc())
            .all()
        )
        assert thesis.trade_plan_id == trade.id
        assert thesis.symbol == "BTCUSDT"
        assert thesis.lifecycle_state == "ACTIVE"
        assert thesis.scenario_json is not None
        assert len(snapshots) == 1
        assert snapshots[0].lifecycle_state == "ACTIVE"

        TradePlanRepository().close_trade(db, trade, price=108.0, result="WIN")
        db.refresh(thesis)
        updated_snapshots = (
            db.query(ThesisSnapshot)
            .filter(ThesisSnapshot.thesis_id == thesis.id)
            .order_by(ThesisSnapshot.effective_timestamp.asc(), ThesisSnapshot.id.asc())
            .all()
        )

        assert thesis.lifecycle_state == "COMPLETED"
        assert thesis.resolved_at is not None
        assert len(updated_snapshots) == 2
        assert updated_snapshots[-1].lifecycle_state == "COMPLETED"
    finally:
        db.close()


def test_paper_trade_save_candidate_backfills_thesis_link():
    db = _session()

    try:
        thesis = TradeThesis(
            thesis_key="BTCUSDT:LONG:1",
            symbol="BTCUSDT",
            side="LONG",
            title="BTCUSDT LONG thesis",
            lifecycle_state="ACTIVE",
            source_signal="LONG",
            confidence=82.0,
            mode="intraday",
            entry_timeframe="1h",
            timeframe_stack="5m,15m,1h",
            regime="TRENDING_BULL",
            trade_plan_id=1,
            assumptions_json="{}",
            invalidation_json="{}",
            targets_json="{}",
        )
        db.add(thesis)
        db.flush()

        paper_trade = PaperTradeRepository().save_candidate(
            db,
            {
                "symbol": "BTCUSDT",
                "side": "LONG",
                "trade_plan": {
                    "id": 1,
                    "thesis_id": thesis.id,
                    "entry_price": 100.0,
                    "stop_loss": 98.0,
                    "target1": 104.0,
                    "target2": 106.0,
                    "mode": "intraday",
                    "entry_timeframe": "1h",
                    "timeframe_stack": "5m,15m,1h",
                    "regime": "TRENDING_BULL",
                },
                "risk_decision": {
                    "id": 7,
                    "position_size": 1.25,
                    "risk_reward": 2.0,
                    "risk_percent": 1.0,
                    "confidence": 82.0,
                },
                "fill_profile": {"entry_fill_price": 100.5, "fee_bps": 4.0},
            },
        )

        db.refresh(thesis)
        assert paper_trade.thesis_id == thesis.id
        assert thesis.paper_trade_id == paper_trade.id
    finally:
        db.close()
