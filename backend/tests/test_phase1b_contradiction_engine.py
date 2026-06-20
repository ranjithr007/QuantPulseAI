import unittest

from app.intelligence.contradiction_engine import analyze_contradictions


class Obj:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def feature(trend="BULLISH", trend_score=75):
    return Obj(Trend=trend, TrendScore=trend_score, CreatedAt=None)


def regime(name="TRENDING_BEAR"):
    return Obj(Regime=name, RecommendedStrategy="SHORT_RALLY", CreatedAt=None)


def orderflow(**kwargs):
    defaults = {
        "cumulative_delta": -120,
        "delta": -25,
        "buy_pressure": 32,
        "sell_pressure": 68,
        "aggressive_side": "SELL",
        "absorption_type": "SELL_ABSORPTION",
        "exhaustion_type": "BUYER_EXHAUSTION",
        "CreatedAt": None,
    }
    defaults.update(kwargs)
    return Obj(**defaults)


def smc(**kwargs):
    defaults = {
        "smc_bias": "BEARISH",
        "bos_type": "BEARISH_BOS",
        "structure": "BEARISH",
        "created_at": None,
    }
    defaults.update(kwargs)
    return Obj(**defaults)


def liquidity(signal="LONG_SQUEEZE_RISK"):
    return Obj(signal=signal)


def derivative(bias="BEARISH_LONG_CROWDING"):
    return Obj(bias=bias)


def whale(bias="DISTRIBUTION"):
    return Obj(bias=bias)


def smart_money(bias="SMART_MONEY_SHORT"):
    return Obj(bias=bias)


def heatmap(bias="HUNT_LONGS"):
    return Obj(bias=bias, created_at=None)


class Phase1BContradictionEngineTests(unittest.TestCase):
    def test_detects_multi_layer_contradiction(self):
        report = analyze_contradictions(
            symbol="BTCUSDT",
            timeframe="5m",
            signal={"signal": "LONG", "confidence": 80, "bias": "LONG"},
            feature=feature(),
            regime=regime(),
            orderflow=orderflow(),
            smc=smc(),
            candle=Obj(close_price=100, candle_time=None),
            liquidity=liquidity(),
            derivative=derivative(),
            whale=whale(),
            smart_money=smart_money(),
            heatmap=heatmap(),
            freshness={
                "candle": {"is_stale": False},
                "feature": {"is_stale": False},
                "regime": {"is_stale": False},
                "orderflow": {"is_stale": False},
                "smc": {"is_stale": False},
            },
            current_price=100,
            previous_price=98,
            price_change_pct=2.04,
            funding_rate=0.08,
            open_interest_change_pct=5.0,
        )

        self.assertEqual(report["status"], "CONFLICT")
        self.assertFalse(report["trade_allowed"])
        self.assertGreaterEqual(report["conflict_score"], 60)
        self.assertIn("feature_regime_mismatch", [item["name"] for item in report["conflicts"]])
        self.assertIn("orderflow_conflict", [item["name"] for item in report["conflicts"]])
        self.assertIn("liquidity_conflict", [item["name"] for item in report["conflicts"]])

    def test_wait_signal_stays_non_actionable_but_reports_context(self):
        report = analyze_contradictions(
            symbol="SOLUSDT",
            timeframe="5m",
            signal={"signal": "WAIT", "confidence": 5, "bias": "WAIT"},
            feature=feature(trend="RANGE", trend_score=52),
            regime=regime(name="RANGE_NEUTRAL"),
            orderflow=orderflow(
                cumulative_delta=15,
                delta=10,
                buy_pressure=58,
                sell_pressure=42,
                aggressive_side="BUY",
                absorption_type="BUY_ABSORPTION",
                exhaustion_type="SELLER_EXHAUSTION",
            ),
            smc=smc(
                smc_bias="NEUTRAL",
                bos_type="NONE",
                structure="RANGE",
            ),
            candle=Obj(close_price=74.5, candle_time=None),
            freshness={
                "candle": {"is_stale": False},
                "feature": {"is_stale": False},
                "regime": {"is_stale": False},
                "orderflow": {"is_stale": False},
                "smc": {"is_stale": False},
            },
            current_price=74.5,
            previous_price=74.2,
            price_change_pct=0.4,
        )

        self.assertEqual(report["status"], "CLEAR")
        self.assertFalse(report["trade_allowed"])
        self.assertIn("No actionable signal to evaluate", report["reasons"])


if __name__ == "__main__":
    unittest.main()
