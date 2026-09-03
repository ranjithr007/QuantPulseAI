from datetime import datetime, timezone
from types import SimpleNamespace

from app.repositories import candle_repository
from app.repositories import intelligence_repository


class FakeSession:
    def __init__(self):
        self.info = {}


def test_ai_inputs_are_loaded_once_per_session(monkeypatch):
    calls = []

    def lookup(name):
        def run(self, db, symbol, timeframe):
            calls.append((name, symbol, timeframe))
            return name

        return run

    monkeypatch.setattr(
        intelligence_repository.IntelligenceRepository,
        "get_latest_feature",
        lookup("feature"),
    )
    monkeypatch.setattr(
        intelligence_repository.IntelligenceRepository,
        "get_latest_regime",
        lookup("regime"),
    )
    monkeypatch.setattr(
        intelligence_repository.IntelligenceRepository,
        "get_latest_orderflow",
        lookup("orderflow"),
    )
    monkeypatch.setattr(
        intelligence_repository.IntelligenceRepository,
        "get_latest_smc",
        lookup("smc"),
    )
    db = FakeSession()

    first = intelligence_repository.get_ai_inputs(db, "BTCUSDT", "15m")
    second = intelligence_repository.get_ai_inputs(db, "BTCUSDT", "15m")

    assert first is second
    assert len(calls) == 4


def test_latest_candles_are_loaded_once_per_session():
    candle = SimpleNamespace(
        id=1,
        candle_time=datetime.now(timezone.utc),
    )

    class FakeQuery:
        def __init__(self):
            self.all_calls = 0
            self.limits = []

        def filter(self, *args):
            return self

        def order_by(self, *args):
            return self

        def limit(self, value):
            self.limits.append(value)
            return self

        def all(self):
            self.all_calls += 1
            return [candle]

    class CandleSession(FakeSession):
        def __init__(self):
            super().__init__()
            self.query_result = FakeQuery()

        def query(self, model):
            return self.query_result

    db = CandleSession()

    first = candle_repository.get_latest_candles(db, "BTCUSDT", "15m", limit=80)
    second = candle_repository.get_latest_candles(db, "BTCUSDT", "15m", limit=1)

    assert first == [candle]
    assert second == [candle]
    assert db.query_result.all_calls == 2
    assert db.query_result.limits == [320, 320]


def test_latest_candle_uses_a_small_bounded_candidate_window():
    candle = SimpleNamespace(
        id=1,
        candle_time=datetime.now(timezone.utc),
    )

    class FakeQuery:
        def __init__(self):
            self.limits = []

        def filter(self, *args):
            return self

        def order_by(self, *args):
            return self

        def limit(self, value):
            self.limits.append(value)
            return self

        def all(self):
            return [candle]

    class CandleSession(FakeSession):
        def __init__(self):
            super().__init__()
            self.query_result = FakeQuery()

        def query(self, model):
            return self.query_result

    db = CandleSession()

    assert candle_repository.get_latest_candle(db, "ETHUSDT", "1h") == candle
    assert db.query_result.limits == [32, 32]
