import copy

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
        support_total = positive_support + negative_support
        support_edge = positive_support - negative_support
        freshness_factor = self._freshness_factor(freshness)
        contradiction_score = float(contradiction.get("conflict_score", 0) or 0)
        contradiction_factor = max(0.15, 1 - contradiction_score / 120)

        prior = self._prior(
            signal_score,
            contradiction.get("status"),
            support_edge,
            support_total,
        )
        likelihood = self._likelihood(
            signal_score,
            positive_support,
            negative_support,
            support_edge,
            support_total,
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
        long_probability = probabilities.get("LONG", 0)
        short_probability = probabilities.get("SHORT", 0)
        wait_probability = probabilities.get("WAIT", 0)
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
            "long_probability": long_probability,
            "short_probability": short_probability,
            "wait_probability": wait_probability,
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
                "total": round(support_total, 2),
                "edge": round(support_edge, 2),
            },
            "current_price": current_price,
            "previous_price": previous_price,
            "price_change_pct": price_change_pct,
            "freshness": freshness,
            "contradiction": contradiction,
            "reasons": reasons,
        }

    def _prior(self, signal_score, contradiction_status, support_edge=0, support_total=0):
        edge_bias = self._clamp(support_edge / 220, -0.18, 0.18)
        conviction = min(1.0, abs(signal_score) / 100)
        support_conviction = min(1.0, abs(support_edge) / 80)

        long_prior = self._clamp(0.5 + signal_score / 180 + edge_bias, 0.03, 0.97)
        short_prior = self._clamp(0.5 - signal_score / 180 - edge_bias, 0.03, 0.97)
        wait_prior = self._clamp(
            0.2
            + (1 - conviction) * 0.22
            + (1 - support_conviction) * 0.18
            + (0.08 if support_total < 20 else 0.0),
            0.03,
            0.75,
        )

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
        support_edge,
        support_total,
        freshness_factor,
        contradiction_score,
        price_change_pct,
        signal_name,
    ):
        edge_strength = min(0.22, abs(support_edge) / 220)
        long_likelihood = 0.42 + min(0.4, positive_support / 170)
        short_likelihood = 0.42 + min(0.4, negative_support / 170)
        wait_likelihood = 0.34 + min(0.34, contradiction_score / 180)

        if support_edge > 0:
            long_likelihood += edge_strength
        elif support_edge < 0:
            short_likelihood += edge_strength

        if signal_score > 0:
            long_likelihood += min(0.14, signal_score / 280)
        elif signal_score < 0:
            short_likelihood += min(0.14, abs(signal_score) / 280)

        if price_change_pct is not None:
            if price_change_pct > 0:
                long_likelihood += min(0.06, price_change_pct / 80)
            elif price_change_pct < 0:
                short_likelihood += min(0.06, abs(price_change_pct) / 80)

        if signal_name == "WAIT":
            wait_likelihood += 0.1

        if support_total < 20:
            wait_likelihood += 0.08
        if abs(signal_score) < 15 and abs(support_edge) < 10:
            wait_likelihood += 0.06
        if abs(signal_score) >= 35 and abs(support_edge) >= 20:
            wait_likelihood -= 0.08

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
    cache = _session_cache(db, "quantpulse_probability_profiles")
    cache_key = (symbol, timeframe, int(stale_after_seconds))
    if cache is not None and cache_key in cache:
        return copy.deepcopy(cache[cache_key])

    candle = get_latest_candle(db, symbol, timeframe)

    if not candle:
        profile = {
            "source": "probability_engine",
            "symbol": symbol,
            "timeframe": timeframe,
            "signal": "NO_DATA",
            "bias": "NO_DATA",
            "decision": "WAIT",
            "actionable": False,
            "status": "INVALIDATED",
            "confidence": 0,
            "long_probability": 0,
            "short_probability": 0,
            "wait_probability": 100,
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
        if cache is not None:
            cache[cache_key] = copy.deepcopy(profile)
        return profile

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

    profile = ProbabilityEngine().analyze(
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
    if cache is not None:
        cache[cache_key] = copy.deepcopy(profile)
    return profile


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


def _session_cache(db, key):
    info = getattr(db, "info", None)
    if not isinstance(info, dict):
        return None

    return info.setdefault(key, {})
