from datetime import datetime, timedelta
from types import SimpleNamespace as S
import pytest
from app.jobs.paper_trade_monitor_job import _overlap_close_evidence, _after_target1_evidence
from app.paper_trading.paper_trade_monitor import evaluate_paper_trade_exit
from app.paper_trading.exit_time import exit_evidence_time
from test_paper_fast_exits import runtime, add_trade, tick
from app.database.models.paper_trade import PaperTrade
from app.jobs import paper_trade_fast_exit_job as fast_job


def trade(side='LONG'):
    return S(id=1, symbol='BTCUSDT', side=side, entry_price=100., stop_loss=99.25 if side=='LONG' else 100.75,
        initial_stop_loss=99.25, target1=101.5 if side=='LONG' else 98.5,
        target2=102.3 if side=='LONG' else 97.7, target1_hit_at=None,
        confidence=60, risk_reward=2, exit_policy='PAPER_STAGED_EXIT_V2',
        opened_at=datetime(2026,1,1), last_exit_evaluated_at=datetime(2026,1,1,10,2))


def test_overlap_uses_later_close_not_pre_change_wick():
    t=trade()
    c=S(close_time=datetime(2026,1,1,10,5), close_price=98, low_price=97, high_price=103)
    evidence=_overlap_close_evidence(t,c)
    assert evidence.high_price == evidence.low_price == 98
    assert evaluate_paper_trade_exit(t,evidence)['action']=='CLOSE'
    c.close_time=datetime(2026,1,1,10,1)
    assert _overlap_close_evidence(t,c) is None


@pytest.mark.parametrize('side', ['LONG','SHORT'])
def test_historical_both_targets_do_not_reapply_pre_t1_wick(side):
    t=trade(side)
    c=S(candle_time=datetime(2026,1,1,11),close_time=datetime(2026,1,1,11,5),
        high_price=103 if side=='LONG' else 100,low_price=100 if side=='LONG' else 97)
    assert evaluate_paper_trade_exit(t,c)['action']=='PARTIAL_CLOSE'
    t.target1_hit_at=c.close_time
    t.stop_loss=100.75 if side=='LONG' else 99.25
    decision=evaluate_paper_trade_exit(t,_after_target1_evidence(t,c))
    assert decision['fill_profile']['trigger_type']=='TARGET2'
    assert decision['fill_profile']['exit_evidence_at']==c.close_time


def test_recovery_time_is_historical_not_processing_time():
    t=trade()
    observed=datetime(2026,1,2)
    assert exit_evidence_time(t,{'exit_evidence_at':observed})==observed
    with pytest.raises(ValueError):
        exit_evidence_time(t,{'exit_evidence_at':t.opened_at-timedelta(seconds=1)})


def test_quote_expiring_during_lock_is_not_executed(runtime, monkeypatch):
    from datetime import timezone
    factory, feed = runtime
    key = add_trade(factory, PaperTrade)
    now = datetime.now(timezone.utc)
    feed.ingest([tick(98, now)])
    original_take = feed.take
    marks = original_take(['BTCUSDT'])
    monkeypatch.setattr(feed, 'take', lambda symbols: marks)
    original_lock = fast_job.lock_open_trade
    def delayed_lock(db, row):
        current = original_lock(db, row)
        marks['BTCUSDT'][0]['observed_at'] = now - timedelta(seconds=10)
        # The job holds the timestamp value, so move its clock forward instead.
        return current
    class LaterClock:
        calls = 0
        @classmethod
        def now(cls, tz=None):
            cls.calls += 1
            return now + timedelta(seconds=10 if cls.calls >= 2 else 0)
    monkeypatch.setattr(fast_job, 'datetime', LaterClock)
    monkeypatch.setattr(fast_job, 'lock_open_trade', delayed_lock)
    monkeypatch.setattr(fast_job, '_alert', lambda *args: None)
    summary = fast_job.run_paper_trade_fast_exit_job()
    assert summary['closed'] == 0
    assert any('PRICE_EXPIRED_DURING_LOCK' in e for e in summary['errors'])
    with factory() as db:
        assert db.get(PaperTrade, key).status == 'OPEN'
