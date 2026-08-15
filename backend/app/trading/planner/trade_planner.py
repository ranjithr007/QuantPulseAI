from .entry_engine import EntryEngine
from .stop_engine import StopEngine
from .target_engine import TargetEngine
from .position_engine import PositionEngine
from .invalidation_engine import InvalidationEngine
from app.trading.trade_plan_engine import build_trade_plan


class TradePlanner:

    def __init__(self):

        self.entry = EntryEngine()

        self.stop = StopEngine()

        self.target = TargetEngine()

        self.position = PositionEngine()

        self.invalidation = InvalidationEngine()

    def create_plan(self, signal, price, atr):

        side = "LONG" if "LONG" in signal["decision"] else "SHORT"

        entry = self.entry.calculate(price, side)

        stop = self.stop.calculate(entry, atr, side)

        governed = build_trade_plan(
            side,
            entry,
            atr,
            confidence=signal["confidence"],
            symbol=signal.get("symbol"),
            timeframe=signal.get("timeframe"),
        )
        stop = governed["stop_loss"]
        targets = [
            governed["target1"],
            governed["target2"],
            governed["target3"],
        ]
        invalidation = self.invalidation.calculate(side, entry, stop, atr)

        return {
            "symbol": signal["symbol"],
            "side": side,
            "entry": round(entry, 2),
            "stop_loss": round(stop, 2),
            "targets": targets,
            "invalidation": invalidation,
            "rr": governed["risk_reward"],
            "gross_rr": governed["gross_risk_reward"],
            "cost_model": governed["cost_model"],
            "exit_policy": governed.get("exit_policy"),
            "target1_fraction": governed.get("target1_fraction"),
            "max_hold_hours": governed.get("max_hold_hours"),
            "confidence": signal["confidence"],
        }
