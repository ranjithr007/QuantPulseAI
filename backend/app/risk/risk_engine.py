from math import isfinite

from app.risk.stop_loss_engine import StopLossEngine
from app.risk.target_engine import TargetEngine
from app.governance.evidence_policy import FULL_SIZE_ENTRY_CONFIDENCE
from app.governance.evidence_policy import MINIMUM_TIER_RISK_PERCENT
from app.governance.evidence_policy import MIN_ENTRY_CONFIDENCE
from app.risk.confidence_sizing import confidence_sizing_profile
from app.risk.position_sizing import PositionSizer


class RiskEngine:
    MIN_CONFIDENCE = MIN_ENTRY_CONFIDENCE
    FULL_SIZE_CONFIDENCE = FULL_SIZE_ENTRY_CONFIDENCE
    MINIMUM_TIER_RISK_PERCENT = MINIMUM_TIER_RISK_PERCENT
    MIN_RISK_REWARD = 2.0

    SIGNAL_TO_SIDE = {
        "BUY": "LONG",
        "LONG": "LONG",
        "STRONG_LONG": "LONG",
        "SELL": "SHORT",
        "SHORT": "SHORT",
        "STRONG_SHORT": "SHORT",
    }

    NON_ACTIONABLE_SIGNALS = {
        "",
        "WAIT",
        "HOLD",
        "NEUTRAL",
        "NO_TRADE",
    }

    def __init__(self):
        self.stop_engine = StopLossEngine()
        self.target_engine = TargetEngine()
        self.sizer = PositionSizer()

    def analyze(
        self,
        symbol,
        signal,
        price,
        atr,
        confidence,
        capital=10000,
        risk_percent=1,
        min_confidence=None,
    ):
        raw_signal = str(signal).strip().upper() if signal is not None else ""

        if raw_signal in self.NON_ACTIONABLE_SIGNALS:
            return self._basic_rejection(
                symbol=symbol,
                signal=raw_signal or None,
                reason="No actionable trade signal",
                confidence=confidence,
            )

        side = self.SIGNAL_TO_SIDE.get(raw_signal)

        if side is None:
            return self._basic_rejection(
                symbol=symbol,
                signal=raw_signal,
                reason=f"Unsupported signal: {raw_signal}",
                confidence=confidence,
            )

        try:
            price = self._to_finite_float("price", price)
            atr = self._to_finite_float("atr", atr)
            confidence = self._to_finite_float("confidence", confidence)
            capital = self._to_finite_float("capital", capital)
            risk_percent = self._to_finite_float("risk_percent", risk_percent)
        except ValueError as exc:
            return self._basic_rejection(
                symbol=symbol,
                signal=side,
                reason=str(exc),
                confidence=confidence,
            )

        if price <= 0:
            return self._basic_rejection(
                symbol, side, "Price must be greater than zero", confidence
            )

        if atr <= 0:
            return self._basic_rejection(
                symbol, side, "ATR must be greater than zero", confidence
            )

        stop_loss = self.stop_engine.calculate(
            side,
            price,
            atr,
        )

        targets = self.target_engine.calculate(
            side,
            price,
            stop_loss,
        )

        result = self.analyze_trade_plan(
            symbol=symbol,
            side=side,
            entry=price,
            stop_loss=stop_loss,
            target1=targets["t1"],
            target2=targets["t2"],
            confidence=confidence,
            risk_percent=risk_percent,
            capital=capital,
            min_confidence=min_confidence,
        )

        if result["decision"] == "APPROVE":
            result["reason"] = "Generated trade plan passed risk checks"

        return result

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
        min_confidence=None,
    ):
        # Required values must be checked before comparisons.
        if entry is None or stop_loss is None or target1 is None:
            return self._reject_trade_plan(
                symbol=symbol,
                side=side,
                entry=entry,
                stop_loss=stop_loss,
                target1=target1,
                target2=target2,
                confidence=confidence,
                risk_percent=risk_percent,
                reason="entry, stop_loss, and target1 are required",
            )

        raw_side = str(side).strip().upper() if side is not None else ""

        canonical_side = self.SIGNAL_TO_SIDE.get(raw_side)

        if canonical_side is None:
            return self._reject_trade_plan(
                symbol=symbol,
                side=raw_side,
                entry=entry,
                stop_loss=stop_loss,
                target1=target1,
                target2=target2,
                confidence=confidence,
                risk_percent=risk_percent,
                reason=f"Unsupported trade side: {raw_side}",
            )

        try:
            entry = self._to_finite_float("entry", entry)
            stop_loss = self._to_finite_float("stop_loss", stop_loss)
            target1 = self._to_finite_float("target1", target1)
            confidence = self._to_finite_float("confidence", confidence)
            risk_percent = self._to_finite_float("risk_percent", risk_percent)
            capital = self._to_finite_float("capital", capital)

            if target2 is not None:
                target2 = self._to_finite_float("target2", target2)

        except ValueError as exc:
            return self._reject_trade_plan(
                symbol=symbol,
                side=canonical_side,
                entry=entry,
                stop_loss=stop_loss,
                target1=target1,
                target2=target2,
                confidence=confidence,
                risk_percent=risk_percent,
                reason=str(exc),
            )

        if min(entry, stop_loss, target1) <= 0:
            return self._reject_trade_plan(
                symbol,
                canonical_side,
                entry,
                stop_loss,
                target1,
                target2,
                confidence,
                risk_percent,
                "Entry, stop loss, and target prices must be positive",
            )

        if target2 is not None and target2 <= 0:
            return self._reject_trade_plan(
                symbol,
                canonical_side,
                entry,
                stop_loss,
                target1,
                target2,
                confidence,
                risk_percent,
                "Target 2 must be positive",
            )

        if not 0 <= confidence <= 100:
            return self._reject_trade_plan(
                symbol,
                canonical_side,
                entry,
                stop_loss,
                target1,
                target2,
                confidence,
                risk_percent,
                "Confidence must be between 0 and 100",
            )

        effective_min_confidence = (
            self.MIN_CONFIDENCE
            if min_confidence is None
            else self._to_finite_float("min_confidence", min_confidence)
        )
        if not 0 <= effective_min_confidence <= 100:
            return self._reject_trade_plan(
                symbol,
                canonical_side,
                entry,
                stop_loss,
                target1,
                target2,
                confidence,
                risk_percent,
                "Minimum confidence must be between 0 and 100",
            )

        if confidence < effective_min_confidence:
            return self._reject_trade_plan(
                symbol,
                canonical_side,
                entry,
                stop_loss,
                target1,
                target2,
                confidence,
                risk_percent,
                "Confidence below risk threshold",
            )

        if capital <= 0:
            return self._reject_trade_plan(
                symbol,
                canonical_side,
                entry,
                stop_loss,
                target1,
                target2,
                confidence,
                risk_percent,
                "Capital must be greater than zero",
            )

        if not 0 < risk_percent <= 100:
            return self._reject_trade_plan(
                symbol,
                canonical_side,
                entry,
                stop_loss,
                target1,
                target2,
                confidence,
                risk_percent,
                "Risk percentage must be greater than 0 and at most 100",
            )

        sizing_profile = confidence_sizing_profile(
            confidence,
            risk_percent,
        )
        effective_risk_percent = sizing_profile["risk_percent"]

        if canonical_side == "LONG":
            if not stop_loss < entry < target1:
                return self._reject_trade_plan(
                    symbol,
                    canonical_side,
                    entry,
                    stop_loss,
                    target1,
                    target2,
                    confidence,
                    risk_percent,
                    "LONG requires stop_loss < entry < target1",
                )

            if target2 is not None and target2 <= target1:
                return self._reject_trade_plan(
                    symbol,
                    canonical_side,
                    entry,
                    stop_loss,
                    target1,
                    target2,
                    confidence,
                    risk_percent,
                    "LONG target2 must be greater than target1",
                )

            risk_distance = entry - stop_loss
            reward_distance = target1 - entry

        else:
            if not stop_loss > entry > target1:
                return self._reject_trade_plan(
                    symbol,
                    canonical_side,
                    entry,
                    stop_loss,
                    target1,
                    target2,
                    confidence,
                    risk_percent,
                    "SHORT requires stop_loss > entry > target1",
                )

            if target2 is not None and target2 >= target1:
                return self._reject_trade_plan(
                    symbol,
                    canonical_side,
                    entry,
                    stop_loss,
                    target1,
                    target2,
                    confidence,
                    risk_percent,
                    "SHORT target2 must be less than target1",
                )

            risk_distance = stop_loss - entry
            reward_distance = entry - target1

        raw_rr = reward_distance / risk_distance

        # Compare before rounding.
        if raw_rr < self.MIN_RISK_REWARD:
            return self._reject_trade_plan(
                symbol=symbol,
                side=canonical_side,
                entry=entry,
                stop_loss=stop_loss,
                target1=target1,
                target2=target2,
                confidence=confidence,
                risk_percent=risk_percent,
                reason="Risk reward below minimum threshold",
                risk_reward=round(raw_rr, 2),
            )

        try:
            position_size = self.sizer.calculate(
                capital=capital,
                risk_percent=effective_risk_percent,
                entry=entry,
                stop=stop_loss,
            )
        except ValueError as exc:
            return self._reject_trade_plan(
                symbol,
                canonical_side,
                entry,
                stop_loss,
                target1,
                target2,
                confidence,
                risk_percent,
                str(exc),
                risk_reward=round(raw_rr, 2),
            )

        result = {
            "symbol": symbol,
            "signal": canonical_side,
            "decision": "APPROVE",
            "reason": "Trade plan passed risk checks",
            "entry": entry,
            "stop_loss": stop_loss,
            "targets": {
                "t1": target1,
                "t2": target2,
            },
            "risk_reward": round(raw_rr, 2),
            "position_size": position_size,
            "risk_percent": effective_risk_percent,
            "requested_risk_percent": sizing_profile["requested_risk_percent"],
            "position_tier": sizing_profile["position_tier"],
            "full_size_confidence": self.FULL_SIZE_CONFIDENCE,
            "risk_amount": capital * effective_risk_percent / 100,
            "confidence": confidence,
        }
        if min_confidence is not None:
            result["minimum_confidence"] = effective_min_confidence
        return result

    @staticmethod
    def _to_finite_float(name, value):
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be a valid number") from exc

        if not isfinite(number):
            raise ValueError(f"{name} must be a finite number")

        return number

    @staticmethod
    def _basic_rejection(
        symbol,
        signal,
        reason,
        confidence,
    ):
        return {
            "symbol": symbol,
            "signal": signal,
            "decision": "REJECT",
            "reason": reason,
            "confidence": confidence,
        }

    @staticmethod
    def _reject_trade_plan(
        symbol,
        side,
        entry,
        stop_loss,
        target1,
        target2,
        confidence,
        risk_percent,
        reason,
        risk_reward=None,
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
            "risk_reward": risk_reward,
            # Rejected plans must not expose executable quantity.
            "position_size": None,
            "risk_percent": risk_percent,
            "confidence": confidence,
        }

    def calculate_risk_reward(
        signal,
        entry,
        stop_loss,
        target,
    ):
        signal = str(signal or "").strip().upper()

        if signal in {"LONG", "BUY"}:
            risk = entry - stop_loss
            reward = target - entry

        elif signal in {"SHORT", "SELL"}:
            risk = stop_loss - entry
            reward = entry - target

        else:
            return None

        if risk <= 0 or reward <= 0:
            return None

        return reward / risk
