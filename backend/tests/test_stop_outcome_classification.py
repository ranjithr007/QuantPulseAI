from test_strategy_learning import _trade
from app.strategies.learning import _trade_metrics
from app.api.v1.strategy_api import _strategy_performance
import pytest


@pytest.mark.parametrize('pnl,expected_loss,expected_protected', [(100, 0, 1), (0, 0, 1), (-10, 1, 0)])
def test_pre_target_stop_uses_net_result(pnl, expected_loss, expected_protected):
    trade = _trade(1, winning=False)
    trade.realized_pnl_inr = pnl
    trade.gross_pnl_percent = 0.1
    trade.pnl_percent = pnl / 1000
    for calculate in (_trade_metrics, _strategy_performance):
        result = calculate([trade])
        assert result['initial_stop_failures'] == expected_loss
        assert result['protected_stop_exits'] == expected_protected
        assert result['target_successes'] == 0


def test_sql_summary_matches_learning_stop_counts():
    from test_strategy_learning import _row, _session
    from app.api.v1.strategy_api import _load_strategy_performance
    from app.database.models.strategy_shadow_trade import StrategyShadowTrade
    db = _session()
    try:
        rows = []
        for index, pnl in enumerate((100, 0, -10), start=1):
            row = _row(index, winning=False)
            row.realized_pnl_inr = pnl
            rows.append(row)
        db.add_all(rows)
        db.commit()
        summary = _load_strategy_performance(db, StrategyShadowTrade, [rows[0].strategy_id])
        result = summary[(rows[0].strategy_id, rows[0].strategy_version)]
        assert result['initial_stop_failures'] == 1
        assert result['protected_stop_exits'] == 2
    finally:
        db.close()
