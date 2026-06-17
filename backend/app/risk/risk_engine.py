from app.risk.stop_loss_engine import StopLossEngine
from app.risk.target_engine import TargetEngine
from app.risk.position_sizing import PositionSizer
from app.utils.signal_validation import validate_trade_plan_direction


class RiskEngine:

    def __init__(self):

        self.stop_engine = StopLossEngine()

        self.target_engine = TargetEngine()

        self.sizer = PositionSizer()

    def analyze(self, symbol, signal, price, atr, confidence):

        if signal in {"WAIT", "HOLD", None}:

            return {
                "symbol": symbol,
                "signal": signal,
                "decision": "REJECT",
                "reason": "No actionable trade signal",
                "confidence": confidence,
            }

        if confidence < 70:

            return {
                "symbol": symbol,
                "signal": signal,
                "decision": "REJECT",
                "reason": "Confidence below risk threshold",
                "confidence": confidence,
            }

        stop = self.stop_engine.calculate(signal, price, atr)

        if stop is None:

            return {
                "symbol": symbol,
                "signal": signal,
                "decision": "REJECT",
                "reason": f"Unsupported signal: {signal}",
                "confidence": confidence,
            }

        targets = self.target_engine.calculate(signal, price, stop)

        if not targets:

            return {
                "symbol": symbol,
                "signal": signal,
                "decision": "REJECT",
                "reason": f"Could not calculate targets for signal: {signal}",
                "confidence": confidence,
            }

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

    def analyze_trade_plan(
        self,
        symbol,
        side,
        entry,
        stop_loss,
        target1,
        target2=None,
        confidence=0,
        risk_percent=1,
        capital=10000,
    ):
        validation = validate_trade_plan_direction(side, entry, target1)

        if not validation["is_valid"]:
            return self._reject_trade_plan(
                symbol,
                side,
                entry,
                stop_loss,
                target1,
                target2,
                confidence,
                risk_percent,
                "; ".join(validation["errors"]),
            )

        if entry is None or stop_loss is None or target1 is None:
            return self._reject_trade_plan(
                symbol,
                side,
                entry,
                stop_loss,
                target1,
                target2,
                confidence,
                risk_percent,
                "entry, stop_loss, and target1 are required",
            )

        if side == "LONG" and stop_loss >= entry:
            return self._reject_trade_plan(
                symbol,
                side,
                entry,
                stop_loss,
                target1,
                target2,
                confidence,
                risk_percent,
                "LONG stop_loss must be less than entry",
            )

        if side == "SHORT" and stop_loss <= entry:
            return self._reject_trade_plan(
                symbol,
                side,
                entry,
                stop_loss,
                target1,
                target2,
                confidence,
                risk_percent,
                "SHORT stop_loss must be greater than entry",
            )

        risk = abs(entry - stop_loss)

        if risk <= 0:
            return self._reject_trade_plan(
                symbol,
                side,
                entry,
                stop_loss,
                target1,
                target2,
                confidence,
                risk_percent,
                "Risk distance must be greater than zero",
            )

        reward = abs(target1 - entry)
        rr = round(reward / risk, 2)
        position_size = self.sizer.calculate(
            capital=capital,
            risk_percent=risk_percent,
            entry=entry,
            stop=stop_loss,
        )

        if rr < 2:
            return {
                "symbol": symbol,
                "signal": side,
                "decision": "REJECT",
                "reason": "Risk reward below minimum threshold",
                "entry": entry,
                "stop_loss": stop_loss,
                "targets": {
                    "t1": target1,
                    "t2": target2,
                },
                "risk_reward": rr,
                "position_size": position_size,
                "risk_percent": risk_percent,
                "confidence": confidence,
            }

        return {
            "symbol": symbol,
            "signal": side,
            "decision": "APPROVE",
            "reason": "Persisted trade plan passed risk checks",
            "entry": entry,
            "stop_loss": stop_loss,
            "targets": {
                "t1": target1,
                "t2": target2,
            },
            "risk_reward": rr,
            "position_size": position_size,
            "risk_percent": risk_percent,
            "confidence": confidence,
        }

    def _reject_trade_plan(
        self,
        symbol,
        side,
        entry,
        stop_loss,
        target1,
        target2,
        confidence,
        risk_percent,
        reason,
    ):
        return {
            "symbol": symbol,
            "signal": side,
            "decision": "REJECT",
            "reason": reason,
            "entry": entry,
            "stop_loss": stop_loss,
            "targets": {
                "t1": target1,
                "t2": target2,
            },
            "risk_reward": None,
            "position_size": None,
            "risk_percent": risk_percent,
            "confidence": confidence,
        }
