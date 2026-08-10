import pytest

from app.api.v1 import backtest_api
from app.backtesting.portfolio_replay import build_portfolio_replay


def _trade(
    *,
    entry_time,
    exit_time,
    confidence,
    pnl=100,
    notional=6_000,
    side="LONG",
):
    return {
        "side": side,
        "entry_time": entry_time,
        "exit_time": exit_time,
        "confidence": confidence,
        "pnl": pnl,
        "pnl_percent": pnl / 100,
        "fees": 4,
        "sizing": {"notional": notional},
    }


def test_portfolio_replay_rejects_lower_priority_same_cluster_overlap():
    results = {
        "BTCUSDT": {
            "trades": [
                _trade(
                    entry_time="2026-01-01T01:00:00+00:00",
                    exit_time="2026-01-01T04:00:00+00:00",
                    confidence=80,
                )
            ]
        },
        "ETHUSDT": {
            "trades": [
                _trade(
                    entry_time="2026-01-01T01:00:00+00:00",
                    exit_time="2026-01-01T03:00:00+00:00",
                    confidence=70,
                )
            ]
        },
    }

    report = build_portfolio_replay(
        results,
        initial_capital=10_000,
        max_open_positions=5,
        max_gross_exposure_percent=200,
        max_cluster_exposure_percent=100,
        symbol_clusters={"BTCUSDT": "MAJORS", "ETHUSDT": "MAJORS"},
    )

    assert [trade["symbol"] for trade in report["trades"]] == ["BTCUSDT"]
    assert report["rejection_counts"] == {
        "PORTFOLIO_MAX_CLUSTER_EXPOSURE": 1
    }
    assert report["portfolio_policy"]["same_timestamp_priority"] == (
        "CONFIDENCE_DESC_SYMBOL_ASC_SIDE_ASC"
    )


def test_portfolio_replay_releases_exited_position_before_next_entry():
    results = {
        "BTCUSDT": {
            "trades": [
                _trade(
                    entry_time="2026-01-01T01:00:00+00:00",
                    exit_time="2026-01-01T02:00:00+00:00",
                    confidence=75,
                )
            ]
        },
        "ETHUSDT": {
            "trades": [
                _trade(
                    entry_time="2026-01-01T02:00:00+00:00",
                    exit_time="2026-01-01T03:00:00+00:00",
                    confidence=70,
                )
            ]
        },
    }

    report = build_portfolio_replay(
        results,
        initial_capital=10_000,
        max_open_positions=1,
        max_gross_exposure_percent=100,
        max_cluster_exposure_percent=100,
        symbol_clusters={"BTCUSDT": "MAJORS", "ETHUSDT": "MAJORS"},
    )

    assert report["total_trades"] == 2
    assert report["rejection_counts"] == {}
    assert report["final_capital"] == 10_200


def test_portfolio_replay_does_not_infer_missing_clusters():
    results = {
        "BTCUSDT": {
            "trades": [
                _trade(
                    entry_time="2026-01-01T01:00:00+00:00",
                    exit_time="2026-01-01T04:00:00+00:00",
                    confidence=80,
                    notional=4_000,
                )
            ]
        },
        "ETHUSDT": {
            "trades": [
                _trade(
                    entry_time="2026-01-01T01:00:00+00:00",
                    exit_time="2026-01-01T03:00:00+00:00",
                    confidence=70,
                    notional=4_000,
                )
            ]
        },
    }

    report = build_portfolio_replay(
        results,
        max_cluster_exposure_percent=50,
    )

    assert report["total_trades"] == 2
    assert report["portfolio_policy"]["cluster_source"] == (
        "SYMBOL_ISOLATED_NO_INFERRED_CORRELATION"
    )


def test_portfolio_replay_api_forwards_explicit_cluster_contract(monkeypatch):
    captured = {}

    def execute(symbols, timeframe, signal, **options):
        captured.update(
            {
                "symbols": symbols,
                "timeframe": timeframe,
                "signal": signal,
                **options,
            }
        )
        return {"engine_version": "portfolio_replay_v1", "total_trades": 0}

    monkeypatch.setattr(backtest_api, "execute_portfolio_backtest", execute)
    response = backtest_api.portfolio_replay_report(
        symbols="dogeusdt,btcusdt",
        signal="SHORT",
        timeframe="1h",
        limit=500,
        initial_capital=10_000,
        position_size_percent=25,
        min_confidence=70,
        stop_atr_multiple=1.5,
        target_atr_multiple=3.5,
        cooldown_candles=3,
        fee_bps=4,
        slippage_bps=2,
        risk_percent_per_trade=1,
        target_trade_volatility_percent=None,
        max_leverage=2,
        max_open_positions=3,
        max_gross_exposure_percent=200,
        max_cluster_exposure_percent=80,
        symbol_clusters_json='{"DOGEUSDT":"ALT","BTCUSDT":"MAJOR"}',
        initial_portfolio_json="[]",
        collision_policy="STOP_FIRST",
    )

    assert response["source"] == "portfolio_replay_v1"
    assert captured["symbols"] == ["DOGEUSDT", "BTCUSDT"]
    assert captured["symbol_clusters"] == {
        "DOGEUSDT": "ALT",
        "BTCUSDT": "MAJOR",
    }
    assert captured["max_cluster_exposure_percent"] == 80


@pytest.mark.parametrize("symbols", ["DOGEUSDT", "DOGEUSDT,DOGEUSDT"])
def test_portfolio_replay_api_requires_two_unique_symbols(symbols):
    with pytest.raises(Exception) as error:
        backtest_api._parse_symbols(symbols)

    assert error.value.status_code == 422
