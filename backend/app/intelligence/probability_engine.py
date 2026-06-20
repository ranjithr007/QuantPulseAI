from app.intelligence.confidence_engine import ConfidenceEngine
from app.intelligence.contradiction_engine import build_contradiction_report
from app.intelligence.master_ai_engine import generate_master_signal
from app.intelligence.master_ai_engine import score_master_signal_components
from app.repositories.candle_repository import get_latest_candle
from app.repositories.candle_repository import get_latest_candles
from app.repositories.intelligence_repository import get_ai_inputs
from app.utils.freshness import freshness_status


ACTIONABLE_SIGNALS = {"LONG", "SHORT"}


class ProbabilityEngine:
    def __init__(self):
        self.confidence = ConfidenceEngine()

    def analyze(
        self,
        symbol,
        timeframe,
        signal,
        components,
        contradiction,
        freshness,
        current_price=None,
        previous_price=None,
        price_change_pct=None,
    ):
        signal_score = float(signal.get("score", 0) or 0)
        signal_bias = signal.get("bias") or _bias_from_signal(signal.get("signal"))
        component_scores = {
            name: float(component.get("score", 0) or 0)
            for name, component in components.items()
        }

        positive_support = sum(max(0.0, value) for value in component_scores.values())
        negative_support = sum(max(0.0, -value) for value in component_scores.values())
        freshness_factor = self._freshness_factor(freshness)
        contradiction_score = float(contradiction.get("conflict_score", 0) or 0)
        contradiction_factor = max(0.15, 1 - contradiction_score / 120)

        prior = self._prior(signal_score, contradiction.get("status"))
        likelihood = self._likelihood(
            signal_score,
            positive_support,
            negative_support,
            freshness_factor,
            contradiction_score,
            price_change_pct,
            signal.get("signal"),
        )

        posterior = {
            name: self.confidence.bayesian_update(prior[name], likelihood[name])
            for name in ("LONG", "SHORT", "WAIT")
        }

        posterior["LONG"] *= freshness_factor * contradiction_factor
        posterior["SHORT"] *= freshness_factor * contradiction_factor
        posterior["WAIT"] *= max(0.25, 1 - freshness_factor / 2) * max(
            0.25, 1 - contradiction_score / 200
        )

        probabilities = self.confidence.normalize(posterior)
        decision = max(probabilities, key=probabilities.get)

        actionable = decision in ACTIONABLE_SIGNALS
        if contradiction.get("status") == "INVALIDATED":
            decision = "WAIT"
            actionable = False
        elif probabilities[decision] < 55 and signal_bias in ACTIONABLE_SIGNALS:
            decision = "WAIT"
            actionable = False

        confidence = probabilities.get(decision, 0)
        status = contradiction.get("status", "CLEAR")
        if status == "CLEAR" and freshness_factor < 0.7:
            status = "WATCH"
        if status == "CLEAR" and confidence < 45:
            status = "WATCH"

        reasons = []
        reasons.extend(signal.get("reasons") or [])
        if contradiction_score > 0:
            reasons.append(f"Contradiction score {round(contradiction_score, 2)}")
        if freshness_factor < 1:
            reasons.append(f"Freshness factor {round(freshness_factor, 4)} applied")
        if price_change_pct is not None:
            reasons.append(f"Price change {round(price_change_pct, 2)}%")
        if not reasons:
            reasons.append("Probability profile calculated from current inputs")

        return {
            "source": "probability_engine",
            "symbol": symbol,
            "timeframe": timeframe,
            "signal": signal.get("signal"),
            "bias": signal_bias,
            "decision": decision,
            "actionable": actionable,
            "status": status,
            "confidence": confidence,
            "probabilities": probabilities,
            "prior": prior,
            "likelihood": likelihood,
            "posterior": posterior,
            "freshness_factor": round(freshness_factor, 4),
            "contradiction_factor": round(contradiction_factor, 4),
            "signal_score": signal_score,
            "component_scores": component_scores,
            "support": {
                "positive": round(positive_support, 2),
                "negative": round(negative_support, 2),
            },
            "current_price": current_price,
            "previous_price": previous_price,
            "price_change_pct": price_change_pct,
            "freshness": freshness,
            "contradiction": contradiction,
            "reasons": reasons,
        }

    def _prior(self, signal_score, contradiction_status):
        long_prior = self._clamp(0.5 + signal_score / 200, 0.05, 0.95)
        short_prior = self._clamp(0.5 - signal_score / 200, 0.05, 0.95)
        wait_prior = self._clamp(0.35 + (1 - min(abs(signal_score), 100) / 100) * 0.35, 0.05, 0.8)

        if contradiction_status == "INVALIDATED":
            wait_prior = 0.9
            long_prior = 0.05
            short_prior = 0.05

        return {
            "LONG": round(long_prior, 4),
            "SHORT": round(short_prior, 4),
            "WAIT": round(wait_prior, 4),
        }

    def _likelihood(
        self,
        signal_score,
        positive_support,
        negative_support,
        freshness_factor,
        contradiction_score,
        price_change_pct,
        signal_name,
    ):
        long_likelihood = 0.5 + min(0.45, positive_support / 220)
        short_likelihood = 0.5 + min(0.45, negative_support / 220)
        wait_likelihood = 0.5 + min(0.35, contradiction_score / 200)

        if signal_score > 0:
            long_likelihood += min(0.1, signal_score / 400)
        elif signal_score < 0:
            short_likelihood += min(0.1, abs(signal_score) / 400)

        if price_change_pct is not None:
            if price_change_pct > 0:
                long_likelihood += min(0.05, price_change_pct / 100)
            elif price_change_pct < 0:
                short_likelihood += min(0.05, abs(price_change_pct) / 100)

        if signal_name == "WAIT":
            wait_likelihood += 0.1

        long_likelihood *= freshness_factor
        short_likelihood *= freshness_factor
        wait_likelihood = min(0.95, wait_likelihood + (1 - freshness_factor) * 0.25)

        return {
            "LONG": round(self._clamp(long_likelihood, 0.05, 0.95), 4),
            "SHORT": round(self._clamp(short_likelihood, 0.05, 0.95), 4),
            "WAIT": round(self._clamp(wait_likelihood, 0.05, 0.95), 4),
        }

    def _freshness_factor(self, freshness):
        if not freshness:
            return 0.2

        weights = []
        for key, status in freshness.items():
            if not status:
                continue

            if status.get("is_stale"):
                weights.append(0.2)
                continue

            age_seconds = status.get("data_age_seconds")
            decay = self.confidence.decay(age_seconds, half_life_seconds=900, floor=0.2)
            weights.append(decay)

        if not weights:
            return 0.2

        return sum(weights) / len(weights)

    @staticmethod
    def _clamp(value, minimum, maximum):
        return max(minimum, min(maximum, float(value)))


def build_probability_profile(db, symbol, timeframe="5m", stale_after_seconds=900):
    candle = get_latest_candle(db, symbol, timeframe)

    if not candle:
        return {
            "source": "probability_engine",
            "symbol": symbol,
            "timeframe": timeframe,
            "signal": "NO_DATA",
            "bias": "NO_DATA",
            "decision": "WAIT",
            "actionable": False,
            "status": "INVALIDATED",
            "confidence": 0,
            "probabilities": {"LONG": 0, "SHORT": 0, "WAIT": 100},
            "prior": {"LONG": 0, "SHORT": 0, "WAIT": 1},
            "likelihood": {"LONG": 0, "SHORT": 0, "WAIT": 1},
            "posterior": {"LONG": 0, "SHORT": 0, "WAIT": 1},
            "freshness_factor": 0,
            "contradiction_factor": 0,
            "support": {"positive": 0, "negative": 0},
            "freshness": {"candle": freshness_status(None, stale_after_seconds)},
            "contradiction": build_contradiction_report(
                db, symbol, timeframe, stale_after_seconds
            ),
            "reasons": ["No latest candle found for symbol/timeframe"],
        }

    inputs = get_ai_inputs(db, symbol, timeframe)
    signal = generate_master_signal(
        inputs["feature"], inputs["regime"], inputs["orderflow"], inputs["smc"]
    )
    components = score_master_signal_components(
        inputs["feature"], inputs["regime"], inputs["orderflow"], inputs["smc"]
    )

    previous_candle = _previous_candle(db, symbol, timeframe)
    current_price = float(candle.close_price)
    previous_price = float(previous_candle.close_price) if previous_candle else None
    price_change_pct = _percent_change(previous_price, current_price)
    contradiction = build_contradiction_report(db, symbol, timeframe, stale_after_seconds)
    freshness = {
        "candle": freshness_status(candle.candle_time, stale_after_seconds),
        "feature": freshness_status(
            getattr(inputs["feature"], "CreatedAt", None), stale_after_seconds
        ),
        "regime": freshness_status(
            getattr(inputs["regime"], "CreatedAt", None), stale_after_seconds
        ),
        "orderflow": freshness_status(
            getattr(inputs["orderflow"], "CreatedAt", None), stale_after_seconds
        ),
        "smc": freshness_status(
            getattr(inputs["smc"], "created_at", None), stale_after_seconds
        ),
    }

    return ProbabilityEngine().analyze(
        symbol=symbol,
        timeframe=timeframe,
        signal=signal,
        components=components,
        contradiction=contradiction,
        freshness=freshness,
        current_price=current_price,
        previous_price=previous_price,
        price_change_pct=price_change_pct,
    )


def _previous_candle(db, symbol, timeframe):
    candles = get_latest_candles(db, symbol, timeframe, limit=2)

    if len(candles) < 2:
        return None

    return candles[1]


def _percent_change(previous, current):
    if previous in (None, 0) or current is None:
        return None

    return ((float(current) - float(previous)) / abs(float(previous))) * 100


def _bias_from_signal(signal):
    text = str(signal or "").upper()

    if "LONG" in text:
        return "LONG"

    if "SHORT" in text:
        return "SHORT"

    return "WAIT"
