import copy

from app.database.models.funding_rates import FundingRate
from app.database.models.liquidation_heatmaps import LiquidationHeatmap
from app.database.models.open_interest import OpenInterest
from app.engines.derivative_engine import DerivativeEngine
from app.engines.liquidity_engine import LiquidityEngine
from app.engines.smart_money_fusion_engine import SmartMoneyFusionEngine
from app.engines.whale_engine import WhaleEngine
from app.intelligence.master_ai_engine import generate_master_signal
from app.repositories.candle_repository import get_latest_candle
from app.repositories.candle_repository import get_latest_candles
from app.repositories.intelligence_repository import get_ai_inputs
from app.utils.freshness import candle_freshness_timestamp, freshness_status


ACTIONABLE_SIGNALS = {"LONG", "SHORT"}
CRITICAL_INPUTS = {"candle", "feature", "regime", "orderflow", "smc"}


def build_contradiction_report(db, symbol, timeframe="5m", stale_after_seconds=900):
    cache = _session_cache(db, "quantpulse_contradiction_reports")
    cache_key = (symbol, timeframe, int(stale_after_seconds))
    if cache is not None and cache_key in cache:
        return copy.deepcopy(cache[cache_key])

    candle = get_latest_candle(db, symbol, timeframe)

    if candle is None:
        report = {
            "source": "contradiction_engine",
            "symbol": symbol,
            "timeframe": timeframe,
            "signal": "NO_DATA",
            "bias": "NO_DATA",
            "status": "INVALIDATED",
            "trade_allowed": False,
            "confidence": 0,
            "conflict_score": 100,
            "reasons": ["No latest candle found for symbol/timeframe"],
            "conflicts": [
                {
                    "name": "missing_candle",
                    "weight": 100,
                    "severity": "critical",
                    "detail": "No latest candle found for symbol/timeframe",
                }
            ],
            "inputs": {},
            "freshness": {
                "candle": freshness_status(None, stale_after_seconds),
            },
        }
        if cache is not None:
            cache[cache_key] = copy.deepcopy(report)
        return report

    inputs = get_ai_inputs(db, symbol, timeframe)
    feature = inputs["feature"]
    regime = inputs["regime"]
    orderflow = inputs["orderflow"]
    smc = inputs["smc"]
    master_signal = (
        generate_master_signal(feature, regime, orderflow, smc)
        if all([feature, regime, orderflow, smc])
        else {
            "signal": "NO_DATA",
            "bias": "NO_DATA",
            "confidence": 0,
            "score": 0,
            "reasons": ["Missing one or more core inputs"],
        }
    )

    current_price = float(candle.close_price)
    previous_candle = _previous_candle(db, symbol, timeframe)
    previous_price = float(previous_candle.close_price) if previous_candle else None
    price_change_pct = _percent_change(previous_price, current_price)
    funding_rate = _latest_funding_rate(db, symbol)
    open_interest_change_pct = _latest_open_interest_change(db, symbol)

    liquidity = LiquidityEngine().analyze(
        symbol,
        funding_rate or 0.0,
        open_interest_change_pct or 0.0,
        price_change_pct or 0.0,
    )
    derivative = DerivativeEngine().analyze(
        funding_rate=funding_rate,
        open_interest_delta=open_interest_change_pct,
        long_short_ratio=None,
    )
    whale_cache = _session_cache(db, "quantpulse_whale_analysis")
    if whale_cache is not None and symbol in whale_cache:
        whale = whale_cache[symbol]
    else:
        whale = WhaleEngine().analyze(db, symbol)
        if whale_cache is not None:
            whale_cache[symbol] = whale
    smart_money = SmartMoneyFusionEngine().analyze(smc, orderflow)
    heatmap = _latest_heatmap(db, symbol)

    freshness = {
        "candle": freshness_status(
            candle_freshness_timestamp(candle),
            stale_after_seconds,
        ),
        "feature": freshness_status(
            getattr(feature, "CreatedAt", None), stale_after_seconds
        ),
        "regime": freshness_status(
            getattr(regime, "CreatedAt", None), stale_after_seconds
        ),
        "orderflow": freshness_status(
            getattr(orderflow, "CreatedAt", None), stale_after_seconds
        ),
        "smc": freshness_status(
            getattr(smc, "created_at", None), stale_after_seconds
        ),
        "funding": freshness_status(
            getattr(_latest_funding_record(db, symbol), "funding_time", None),
            stale_after_seconds,
        ),
        "open_interest": freshness_status(
            getattr(_latest_open_interest_record(db, symbol), "timestamp", None),
            stale_after_seconds,
        ),
        "heatmap": freshness_status(
            getattr(heatmap, "created_at", None) if heatmap else None,
            stale_after_seconds,
        ),
    }

    report = analyze_contradictions(
        symbol=symbol,
        timeframe=timeframe,
        signal=master_signal,
        feature=feature,
        regime=regime,
        orderflow=orderflow,
        smc=smc,
        candle=candle,
        liquidity=liquidity,
        derivative=derivative,
        whale=whale,
        smart_money=smart_money,
        heatmap=heatmap,
        freshness=freshness,
        current_price=current_price,
        previous_price=previous_price,
        price_change_pct=price_change_pct,
        funding_rate=funding_rate,
        open_interest_change_pct=open_interest_change_pct,
    )
    report["master_signal"] = master_signal
    report["current_price"] = current_price
    report["candle_time"] = candle.candle_time
    report["freshness"]["candle"] = freshness["candle"]
    report["inputs"] = {
        "feature": freshness["feature"],
        "regime": freshness["regime"],
        "orderflow": freshness["orderflow"],
        "smc": freshness["smc"],
        "funding": freshness["funding"],
        "open_interest": freshness["open_interest"],
        "heatmap": freshness["heatmap"],
    }

    if cache is not None:
        cache[cache_key] = copy.deepcopy(report)
    return report


def analyze_contradictions(
    symbol,
    timeframe,
    signal,
    feature=None,
    regime=None,
    orderflow=None,
    smc=None,
    candle=None,
    liquidity=None,
    derivative=None,
    whale=None,
    smart_money=None,
    heatmap=None,
    freshness=None,
    current_price=None,
    previous_price=None,
    price_change_pct=None,
    funding_rate=None,
    open_interest_change_pct=None,
):
    signal_bias = _direction_from_signal(signal)
    signal_confidence = float(_safe_number((signal or {}).get("confidence"), 0))

    conflicts = []
    reasons = []
    bias_map = {
        "signal": signal_bias,
        "feature": _direction_from_feature(feature),
        "regime": _direction_from_regime(regime),
        "orderflow": _direction_from_orderflow(orderflow),
        "smc": _direction_from_smc(smc),
        "liquidity": _direction_from_liquidity(liquidity),
        "derivative": _direction_from_derivative(derivative),
        "whale": _direction_from_whale(whale),
        "smart_money": _direction_from_smart_money(smart_money),
        "heatmap": _direction_from_heatmap(heatmap),
    }

    core_missing = [
        name
        for name, value in {
            "candle": candle,
            "feature": feature,
            "regime": regime,
            "orderflow": orderflow,
            "smc": smc,
        }.items()
        if value is None
    ]

    stale_inputs = [
        name
        for name, status in (freshness or {}).items()
        if name in CRITICAL_INPUTS and status and status.get("is_stale")
    ]

    conflict_score = 0

    if bias_map["feature"] != "WAIT" and bias_map["regime"] != "WAIT":
        if bias_map["feature"] != bias_map["regime"]:
            _append_conflict(
                conflicts,
                "feature_regime_mismatch",
                25,
                "Feature trend and regime are pointing in different directions",
                bias_map["feature"],
                bias_map["regime"],
            )

    if signal_bias in ACTIONABLE_SIGNALS:
        if bias_map["orderflow"] != "WAIT" and bias_map["orderflow"] != signal_bias:
            _append_conflict(
                conflicts,
                "orderflow_conflict",
                20,
                "Orderflow is opposing the actionable signal",
                signal_bias,
                bias_map["orderflow"],
            )

        if bias_map["smc"] != "WAIT" and bias_map["smc"] != signal_bias:
            _append_conflict(
                conflicts,
                "smc_conflict",
                15,
                "SMC structure is not aligned with the signal",
                signal_bias,
                bias_map["smc"],
            )

        if bias_map["liquidity"] != "WAIT" and bias_map["liquidity"] != signal_bias:
            _append_conflict(
                conflicts,
                "liquidity_conflict",
                20,
                "Liquidity pressure is fighting the signal",
                signal_bias,
                bias_map["liquidity"],
            )

        if bias_map["derivative"] != "WAIT" and bias_map["derivative"] != signal_bias:
            _append_conflict(
                conflicts,
                "derivative_conflict",
                15,
                "Derivative crowding pressure is not aligned with the signal",
                signal_bias,
                bias_map["derivative"],
            )

        if bias_map["whale"] != "WAIT" and bias_map["whale"] != signal_bias:
            _append_conflict(
                conflicts,
                "whale_conflict",
                15,
                "Whale flow is pointing against the signal",
                signal_bias,
                bias_map["whale"],
            )

        if bias_map["smart_money"] != "WAIT" and bias_map["smart_money"] != signal_bias:
            _append_conflict(
                conflicts,
                "smart_money_conflict",
                15,
                "Smart money fusion is opposing the signal",
                signal_bias,
                bias_map["smart_money"],
            )

        if bias_map["heatmap"] != "WAIT" and bias_map["heatmap"] != signal_bias:
            _append_conflict(
                conflicts,
                "heatmap_conflict",
                10,
                "Heatmap liquidity pressure is pointing the other way",
                signal_bias,
                bias_map["heatmap"],
            )

    if not signal_bias in ACTIONABLE_SIGNALS:
        if bias_map["feature"] in ACTIONABLE_SIGNALS and bias_map["regime"] in ACTIONABLE_SIGNALS:
            if bias_map["feature"] != bias_map["regime"]:
                _append_conflict(
                    conflicts,
                    "feature_regime_mismatch",
                    25,
                    "Feature trend and regime are pointing in different directions",
                    bias_map["feature"],
                    bias_map["regime"],
                )

        if bias_map["orderflow"] in ACTIONABLE_SIGNALS and bias_map["smc"] in ACTIONABLE_SIGNALS:
            if bias_map["orderflow"] != bias_map["smc"]:
                _append_conflict(
                    conflicts,
                    "orderflow_smc_mismatch",
                    15,
                    "Orderflow and SMC are not confirming each other",
                    bias_map["orderflow"],
                    bias_map["smc"],
                )

    if stale_inputs:
        for name in stale_inputs:
            _append_conflict(
                conflicts,
                f"{name}_stale",
                20,
                f"{name.replace('_', ' ').title()} input is stale",
                None,
                None,
                severity="critical",
            )

    if core_missing:
        for name in core_missing:
            _append_conflict(
                conflicts,
                f"missing_{name}",
                100,
                f"Missing required {name} input",
                None,
                None,
                severity="critical",
            )

    conflict_score = min(100, sum(item["weight"] for item in conflicts))
    confidence = max(0, 100 - conflict_score)

    if core_missing or stale_inputs:
        status = "INVALIDATED"
    elif conflict_score >= 60:
        status = "CONFLICT"
    elif conflict_score >= 20:
        status = "WATCH"
    else:
        status = "CLEAR"

    trade_allowed = signal_bias in ACTIONABLE_SIGNALS and status in {"CLEAR", "WATCH"}

    if conflicts:
        reasons.extend(item["detail"] for item in conflicts)
    elif signal_bias in ACTIONABLE_SIGNALS:
        reasons.append("No major contradictions detected")
    else:
        reasons.append("No actionable signal to evaluate")

    summary = _summary_for_report(status, conflict_score, signal_bias, trade_allowed)
    risk_level = _risk_level(status, conflict_score)

    return {
        "source": "contradiction_engine",
        "symbol": symbol,
        "timeframe": timeframe,
        "signal": signal_bias,
        "bias": signal_bias,
        "status": status,
        "trade_allowed": trade_allowed,
        "confidence": confidence if status != "INVALIDATED" else 0,
        "conflict_score": conflict_score,
        "summary": summary,
        "risk": risk_level,
        "reasons": reasons,
        "conflicts": conflicts,
        "bias_map": bias_map,
        "current_price": current_price,
        "previous_price": previous_price,
        "price_change_pct": price_change_pct,
        "funding_rate": funding_rate,
        "open_interest_change_pct": open_interest_change_pct,
        "freshness": freshness or {},
    }


def _append_conflict(
    conflicts,
    name,
    weight,
    detail,
    expected,
    actual,
    severity="high",
):
    conflicts.append(
        {
            "name": name,
            "weight": weight,
            "severity": severity,
            "detail": detail,
            "expected": expected,
            "actual": actual,
        }
    )


def _direction_from_signal(signal):
    if not signal:
        return "WAIT"

    value = signal.get("signal") if isinstance(signal, dict) else signal
    return _direction_from_text(value)


def _direction_from_feature(feature):
    if feature is None:
        return "WAIT"

    trend = _direction_from_text(getattr(feature, "Trend", None))
    if trend != "WAIT":
        return trend

    score = _safe_number(getattr(feature, "TrendScore", None), 50)
    if score >= 60:
        return "LONG"
    if score <= 40:
        return "SHORT"
    return "WAIT"


def _direction_from_regime(regime):
    if regime is None:
        return "WAIT"

    value = _direction_from_text(getattr(regime, "Regime", None))
    if value != "WAIT":
        return value

    recommended = _direction_from_text(getattr(regime, "RecommendedStrategy", None))
    if recommended != "WAIT":
        return recommended

    return "WAIT"


def _direction_from_orderflow(orderflow):
    if orderflow is None:
        return "WAIT"

    score = 0
    cumulative_delta = _get_value(orderflow, "cumulative_delta", "CVD")
    delta = _get_value(orderflow, "delta", "Delta")
    buy_pressure = _get_value(orderflow, "buy_pressure", "BuyerStrength")
    sell_pressure = _get_value(orderflow, "sell_pressure", "SellerStrength")
    aggressive_side = _get_value(orderflow, "aggressive_side", "FlowSignal")
    absorption_type = _get_value(orderflow, "absorption_type", "Absorption")
    exhaustion_type = _get_value(orderflow, "exhaustion_type", "Exhaustion")

    if _safe_number(cumulative_delta, None) is not None:
        score += 1 if float(cumulative_delta) > 0 else -1
    if _safe_number(delta, None) is not None:
        score += 1 if float(delta) > 0 else -1
    if _safe_number(buy_pressure, None) is not None:
        score += 1 if float(buy_pressure) > 50 else -1
    if _safe_number(sell_pressure, None) is not None:
        score += 1 if float(sell_pressure) < 50 else -1
    if _text_matches(aggressive_side, "BUY"):
        score += 1
    if _text_matches(aggressive_side, "SELL"):
        score -= 1
    if _text_matches(absorption_type, "BUY_ABSORPTION"):
        score += 1
    if _text_matches(absorption_type, "SELL_ABSORPTION"):
        score -= 1
    if _text_matches(exhaustion_type, "SELLER_EXHAUSTION"):
        score += 1
    if _text_matches(exhaustion_type, "BUYER_EXHAUSTION"):
        score -= 1

    if score > 0:
        return "LONG"
    if score < 0:
        return "SHORT"
    return "WAIT"


def _direction_from_smc(smc):
    if smc is None:
        return "WAIT"

    raw_bias = str(getattr(smc, "smc_bias", "") or "").upper()
    if raw_bias == "LONG":
        return "LONG"
    if raw_bias == "SHORT":
        return "SHORT"

    if _text_matches(getattr(smc, "smc_bias", None), "BULL"):
        return "LONG"
    if _text_matches(getattr(smc, "smc_bias", None), "BEAR"):
        return "SHORT"
    if _text_matches(getattr(smc, "bos_type", None), "BULL"):
        return "LONG"
    if _text_matches(getattr(smc, "bos_type", None), "BEAR"):
        return "SHORT"
    if _text_matches(getattr(smc, "structure", None), "BULL"):
        return "LONG"
    if _text_matches(getattr(smc, "structure", None), "BEAR"):
        return "SHORT"

    return "WAIT"


def _direction_from_liquidity(liquidity):
    if not liquidity:
        return "WAIT"

    signal = getattr(liquidity, "signal", None)
    if _text_matches(signal, "SHORT_SQUEEZE"):
        return "LONG"
    if _text_matches(signal, "LONG_SQUEEZE"):
        return "SHORT"
    if _text_matches(signal, "LONG_LIQUIDATION"):
        return "SHORT"
    if _text_matches(signal, "SHORT_LIQUIDATION"):
        return "LONG"
    return "WAIT"


def _direction_from_derivative(derivative):
    if not derivative:
        return "WAIT"

    bias = getattr(derivative, "bias", None)
    if _text_matches(bias, "BULLISH"):
        return "LONG"
    if _text_matches(bias, "BEARISH"):
        return "SHORT"
    if _text_matches(bias, "NEUTRAL"):
        return "WAIT"
    return "WAIT"


def _direction_from_whale(whale):
    if not whale:
        return "WAIT"

    bias = getattr(whale, "bias", None)
    if _text_matches(bias, "ACCUMULATION"):
        return "LONG"
    if _text_matches(bias, "DISTRIBUTION"):
        return "SHORT"
    return "WAIT"


def _direction_from_smart_money(smart_money):
    if not smart_money:
        return "WAIT"

    bias = getattr(smart_money, "bias", None)
    if _text_matches(bias, "SMART_MONEY_LONG"):
        return "LONG"
    if _text_matches(bias, "SMART_MONEY_SHORT"):
        return "SHORT"
    return "WAIT"


def _direction_from_heatmap(heatmap):
    if not heatmap:
        return "WAIT"

    bias = getattr(heatmap, "bias", None)
    if _text_matches(bias, "HUNT_SHORTS"):
        return "LONG"
    if _text_matches(bias, "HUNT_LONGS"):
        return "SHORT"
    return "WAIT"


def _summary_for_report(status, conflict_score, signal_bias, trade_allowed):
    if status == "INVALIDATED":
        return "One or more core inputs are stale or missing"

    if signal_bias not in ACTIONABLE_SIGNALS:
        return "No actionable signal, contradiction check completed"

    if not trade_allowed:
        return "Signal is blocked by strong contradictions"

    if conflict_score == 0:
        return "Actionable signal is clean across core inputs"

    return "Actionable signal is usable with watch conditions"


def _risk_level(status, conflict_score):
    if status == "INVALIDATED":
        return "HIGH"

    if conflict_score >= 60:
        return "HIGH"

    if conflict_score >= 20:
        return "MEDIUM"

    return "LOW"


def _latest_funding_record(db, symbol):
    cache = _session_cache(db, "quantpulse_latest_funding")
    if cache is not None and symbol in cache:
        return cache[symbol]
    record = (
        db.query(FundingRate)
        .filter(FundingRate.symbol == symbol)
        .order_by(FundingRate.funding_time.desc(), FundingRate.id.desc())
        .first()
    )
    if cache is not None:
        cache[symbol] = record
    return record


def _latest_open_interest_record(db, symbol):
    records = _latest_open_interest_records(db, symbol)
    return records[0] if records else None


def _latest_open_interest_records(db, symbol):
    cache = _session_cache(db, "quantpulse_latest_open_interest")
    if cache is not None and symbol in cache:
        return cache[symbol]
    records = (
        db.query(OpenInterest)
        .filter(OpenInterest.symbol == symbol)
        .order_by(OpenInterest.timestamp.desc(), OpenInterest.id.desc())
        .limit(2)
        .all()
    )
    if cache is not None:
        cache[symbol] = records
    return records


def _latest_funding_rate(db, symbol):
    record = _latest_funding_record(db, symbol)
    return float(record.rate) if record and record.rate is not None else None


def _latest_open_interest_change(db, symbol):
    records = _latest_open_interest_records(db, symbol)

    if len(records) < 2:
        return None

    latest = records[0].value
    previous = records[1].value

    if latest is None or previous in (None, 0):
        return None

    return ((float(latest) - float(previous)) / abs(float(previous))) * 100


def _latest_heatmap(db, symbol):
    cache = _session_cache(db, "quantpulse_latest_heatmap")
    if cache is not None and symbol in cache:
        return cache[symbol]
    record = (
        db.query(LiquidationHeatmap)
        .filter(LiquidationHeatmap.symbol == symbol)
        .order_by(LiquidationHeatmap.created_at.desc(), LiquidationHeatmap.id.desc())
        .first()
    )
    if cache is not None:
        cache[symbol] = record
    return record


def _session_cache(db, key):
    info = getattr(db, "info", None)
    if not isinstance(info, dict):
        return None

    return info.setdefault(key, {})


def _previous_candle(db, symbol, timeframe):
    candles = get_latest_candles(db, symbol, timeframe, limit=2)

    if len(candles) < 2:
        return None

    return candles[-2]


def _percent_change(previous, current):
    if previous in (None, 0) or current is None:
        return None

    return ((float(current) - float(previous)) / abs(float(previous))) * 100


def _text_matches(value, needle):
    return needle in str(value or "").upper()


def _direction_from_text(value):
    text = str(value or "").upper()

    if not text or text in {"NONE", "NEUTRAL", "WAIT", "NO_DATA", "UNKNOWN"}:
        return "WAIT"

    if "BULL" in text or "LONG" in text or text in {"ACCUMULATION", "BUY_SIDE_SWEEP"}:
        return "LONG"

    if "BEAR" in text or "SHORT" in text or text in {"DISTRIBUTION", "SELL_SIDE_SWEEP"}:
        return "SHORT"

    return "WAIT"


def _safe_number(value, default=0):
    if value is None:
        return default

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _get_value(obj, *names):
    for name in names:
        value = getattr(obj, name, None)
        if value is not None:
            return value
    return None
