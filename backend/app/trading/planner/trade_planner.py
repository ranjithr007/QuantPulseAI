from .entry_engine import EntryEngine
from .stop_engine import StopEngine
from .target_engine import TargetEngine
from .position_engine import PositionEngine


class TradePlanner:

    def __init__(self):

        self.entry = EntryEngine()

        self.stop = StopEngine()

        self.target = TargetEngine()

        self.position = PositionEngine()

    def create_plan(self, signal, price, atr):

        side = "LONG" if "LONG" in signal["decision"] else "SHORT"

        entry = self.entry.calculate(price, side)

        stop = self.stop.calculate(entry, atr, side)

        targets = self.target.calculate(entry, stop, side)

        return {
            "symbol": signal["symbol"],
            "side": side,
            "entry": round(entry, 2),
            "stop_loss": round(stop, 2),
            "targets": targets,
            "rr": self.position.calculate_rr(entry, stop, targets[-1]),
            "confidence": signal["confidence"],
        }