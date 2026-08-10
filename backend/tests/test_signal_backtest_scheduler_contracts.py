from app.contracts.backtest import BacktestResponse
from app.contracts.scheduler import SchedulerJobsResponse, SchedulerStatusResponse
from app.contracts.signals import SignalBatchResponse, SignalResponse


def test_signal_contracts_preserve_nested_payloads():
    signal = SignalResponse(
        symbol="DOGEUSDT",
        timeframe="1h",
        source="computed_current",
        status="OK",
        confidence=65,
        nested={"regime": "SHORT"},
    )
    batch = SignalBatchResponse(
        source="computed_current_batch",
        status="OK",
        data_scope="timeframe",
        timeframe="1h",
        count=1,
        records=[{"symbol": "DOGEUSDT"}],
        records_by_symbol={"DOGEUSDT": {"symbol": "DOGEUSDT"}},
    )
    assert signal.nested["regime"] == "SHORT"
    assert batch.count == 1


def test_backtest_and_scheduler_contracts_accept_failure_shapes():
    backtest = BacktestResponse(
        source="backtest_summary_v2",
        symbol="DOGEUSDT",
        signal="LONG",
        timeframe="1h",
        result={"trades": 0},
    )
    status = SchedulerStatusResponse(available=False, running=False, error="unavailable")
    jobs = SchedulerJobsResponse(available=True, configured_jobs=["deterministic_pipeline"])

    assert backtest.result["trades"] == 0
    assert status.error == "unavailable"
    assert jobs.configured_jobs == ["deterministic_pipeline"]
