from app.risk.stop_loss_engine import StopLossEngine
from app.risk.target_engine import TargetEngine
from app.risk.position_sizing import PositionSizer


class RiskEngine:

    def __init__(self):

        self.stop_engine = StopLossEngine()

        self.target_engine = TargetEngine()

        self.sizer = PositionSizer()

    def analyze(self, symbol, signal, price, atr, confidence):

        if confidence < 70:

            return {"symbol": symbol, "decision": "REJECT", "confidence": confidence}

        stop = self.stop_engine.calculate(signal, price, atr)

        targets = self.target_engine.calculate(signal, price, stop)

        risk = abs(price - stop)

        reward = abs(targets["t1"] - price)

        rr = reward / risk

        qty = self.sizer.calculate(
            capital=10000, risk_percent=1, entry=price, stop=stop
        )

        return {
            "symbol": symbol,
            "signal": signal,
            "decision": "TAKE_TRADE",
            "entry": price,
            "stop_loss": stop,
            "targets": targets,
            "risk_reward": rr,
            "position_size": qty,
            "confidence": confidence,
        }