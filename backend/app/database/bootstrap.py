from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import sessionmaker
from app.repositories._db_utils import commit_or_rollback
from app.repositories._db_utils import flush_or_rollback


TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h", "1d")

SYMBOL_PROFILES = {
    "BTCUSDT": {
        "base_asset": "BTC",
        "quote_asset": "USDT",
        "price": 66515.99,
        "biases": {
            "5m": "SHORT",
            "15m": "LONG",
            "1h": "LONG",
            "4h": "LONG",
            "1d": "LONG",
        },
    },
    "ETHUSDT": {
        "base_asset": "ETH",
        "quote_asset": "USDT",
        "price": 1773.30,
        "biases": {
            "5m": "SHORT",
            "15m": "LONG",
            "1h": "LONG",
            "4h": "LONG",
            "1d": "LONG",
        },
    },
    "XRPUSDT": {
        "base_asset": "XRP",
        "quote_asset": "USDT",
        "price": 1.2362,
        "biases": {
            "5m": "SHORT",
            "15m": "LONG",
            "1h": "LONG",
            "4h": "LONG",
            "1d": "LONG",
        },
    },
    "SOLUSDT": {
        "base_asset": "SOL",
        "quote_asset": "USDT",
        "price": 74.54,
        "biases": {
            "5m": "NEUTRAL",
            "15m": "SHORT",
            "1h": "NEUTRAL",
            "4h": "NEUTRAL",
            "1d": "NEUTRAL",
        },
    },
    "BNBUSDT": {
        "base_asset": "BNB",
        "quote_asset": "USDT",
        "price": 613.39,
        "biases": {
            "5m": "SHORT",
            "15m": "SHORT",
            "1h": "SHORT",
            "4h": "SHORT",
            "1d": "SHORT",
        },
    },
    "DOGEUSDT": {
        "base_asset": "DOGE",
        "quote_asset": "USDT",
        "price": 0.1335,
        "biases": {
            "5m": "SHORT",
            "15m": "LONG",
            "1h": "LONG",
            "4h": "LONG",
            "1d": "LONG",
        },
    },
}


def bootstrap_sqlite_demo_data(engine):
    """Populate the local SQLite fallback with a compact, coherent dataset."""

    from app.database.models.ai_scores import AIScore
    from app.database.models.master_signals import MasterSignal
    from app.database.models.market_candles import MarketCandle
    from app.database.models.market_features import MarketFeature
    from app.database.models.market_order_flow import MarketOrderFlow
    from app.database.models.market_regimes import MarketRegime
    from app.database.models.data_quality_events import DataQualityEvent
    from app.database.models.point_in_time_snapshots import (
        DecisionSnapshot,
        FeatureSnapshot,
    )
    from app.database.models.trade_thesis import TradeThesis
    from app.database.models.market_smc import MarketSMCSignal
    from app.database.models.paper_trade import PaperTrade
    from app.database.models.risk_decision import RiskDecision
    from app.database.models.symbols import Symbol
    from app.database.models.trade_plan import TradePlan
    from app.database.sqlserver import Base

    Base.metadata.create_all(bind=engine)

    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    with Session() as db:
        if db.query(Symbol).first():
            return

        now = datetime.utcnow().replace(microsecond=0)

        symbol_id = 1
        candle_id = 1
        feature_id = 1
        regime_id = 1
        orderflow_id = 1
        smc_id = 1
        trade_plan_id = 1
        risk_id = 1
        paper_trade_id = 1
        thesis_id = 1
        master_signal_id = 1
        ai_score_id = 1

        for symbol, profile in SYMBOL_PROFILES.items():
            db.add(
                Symbol(
                    id=symbol_id,
                    symbol=symbol,
                    base_asset=profile["base_asset"],
                    quote_asset=profile["quote_asset"],
                    is_active=True,
                )
            )
            symbol_id += 1

            for timeframe in TIMEFRAMES:
                bias = profile["biases"].get(timeframe, profile["biases"].get("5m", "NEUTRAL"))
                current_price = profile["price"]
                candles = _build_candles(symbol, current_price, bias, now, timeframe)
                for candle in candles:
                    candle.id = candle_id
                    candle_id += 1
                    db.add(candle)

                feature = _build_feature_row(symbol, timeframe, current_price, bias, feature_id, now)
                feature_id += 1
                db.add(feature)

                regime = _build_regime_row(symbol, timeframe, current_price, bias, regime_id, now)
                regime_id += 1
                db.add(regime)

                orderflow = _build_orderflow_row(symbol, timeframe, current_price, bias, orderflow_id, now)
                orderflow_id += 1
                db.add(orderflow)

                smc = _build_smc_row(symbol, timeframe, current_price, bias, smc_id, now)
                smc_id += 1
                db.add(smc)

            trade_bias = profile["biases"]["1h"]
            if trade_bias in {"LONG", "SHORT"}:
                entry, stop_loss, target1, target2, target3, risk_reward = _trade_plan_levels(
                    profile["price"],
                    trade_bias,
                )

                trade_plan = TradePlan(
                    id=trade_plan_id,
                    symbol=symbol,
                    side=trade_bias,
                    entry_price=entry,
                    stop_loss=stop_loss,
                    target1=target1,
                    target2=target2,
                    target3=target3,
                    risk_reward=risk_reward,
                    confidence=78.0 if trade_bias == "LONG" else 69.0,
                    thesis_id=thesis_id,
                    status="OPEN",
                    created_at=now - timedelta(minutes=8),
                )
                db.add(trade_plan)
                flush_or_rollback(db)
                trade_plan_id += 1

                thesis = TradeThesis(
                    id=thesis_id,
                    thesis_key=f"{symbol}:{trade_bias}:{trade_plan.id}",
                    symbol=symbol,
                    side=trade_bias,
                    title=f"{symbol} {trade_bias} thesis",
                    lifecycle_state="ACTIVE",
                    source_signal=trade_bias,
                    confidence=78.0 if trade_bias == "LONG" else 69.0,
                    mode="intraday",
                    entry_timeframe="1h",
                    timeframe_stack="5m,15m,1h",
                    regime="TRENDING_BULL" if trade_bias == "LONG" else "TRENDING_BEAR",
                    trade_plan_id=trade_plan.id,
                    assumptions_json='{"source":"bootstrap"}',
                    invalidation_json='{"source":"bootstrap"}',
                    targets_json='{"source":"bootstrap"}',
                    created_at=now - timedelta(minutes=8),
                    updated_at=now - timedelta(minutes=8),
                )
                thesis_id += 1
                db.add(thesis)

                risk = RiskDecision(
                    id=risk_id,
                    symbol=symbol,
                    signal=trade_bias,
                    decision="APPROVE",
                    entry_price=entry,
                    stop_loss=stop_loss,
                    target1=target1,
                    target2=target2,
                    risk_reward=risk_reward,
                    position_size=1.25,
                    risk_percent=1.0,
                    confidence=78.0 if trade_bias == "LONG" else 69.0,
                    thesis_id=trade_plan.thesis_id,
                    created_at=now - timedelta(minutes=7),
                )
                risk_id += 1
                db.add(risk)

                master_signal = MasterSignal(
                    id=master_signal_id,
                    symbol=symbol,
                    signal=trade_bias,
                    confidence=78.0 if trade_bias == "LONG" else 69.0,
                    long_score=65.0 if trade_bias == "LONG" else 15.0,
                    short_score=15.0 if trade_bias == "LONG" else 65.0,
                    orderflow_score=100.0 if trade_bias == "LONG" else 5.0,
                    risk="MEDIUM" if trade_bias == "LONG" else "HIGH",
                    entry_price=entry,
                    target_price=target1,
                    reasons=_master_signal_reasons(trade_bias),
                    created_at=now - timedelta(minutes=6),
                )
                master_signal_id += 1
                db.add(master_signal)

                ai_score = AIScore(
                    id=ai_score_id,
                    symbol=symbol,
                    trend_score=72 if trade_bias == "LONG" else 28,
                    liquidity_score=68 if trade_bias == "LONG" else 32,
                    derivative_score=64 if trade_bias == "LONG" else 36,
                    volatility_score=45,
                    whale_score=66 if trade_bias == "LONG" else 34,
                    sentiment_score=62 if trade_bias == "LONG" else 38,
                    final_score=67 if trade_bias == "LONG" else 33,
                    bias="BULLISH" if trade_bias == "LONG" else "BEARISH",
                    confidence=78 if trade_bias == "LONG" else 69,
                )
                ai_score_id += 1
                db.add(ai_score)

                _seed_paper_trades(
                    db,
                    symbol=symbol,
                    side=trade_bias,
                    trade_plan_id=trade_plan.id,
                    risk_id=risk.id,
                    thesis_id=trade_plan.thesis_id,
                    current_price=profile["price"],
                    now=now,
                    paper_trade_id_start=paper_trade_id,
                )
                paper_trade_id += 2

        commit_or_rollback(db)


def _build_candles(symbol, current_price, bias, now, timeframe):
    from app.database.models.market_candles import MarketCandle

    slope = {
        "LONG": 0.0015,
        "SHORT": -0.0015,
        "NEUTRAL": 0.0,
    }[bias]
    candles = []
    deltas = (-10, -5, -1)
    for index, minutes in enumerate(deltas):
        factor = 1 + slope * (index - 1)
        close_price = current_price * factor
        open_price = close_price * (0.999 if bias == "LONG" else 1.001 if bias == "SHORT" else 1.0)
        high_price = max(open_price, close_price) * 1.002
        low_price = min(open_price, close_price) * 0.998
        candles.append(
            MarketCandle(
                symbol=symbol,
                timeframe=timeframe,
                open_price=round(open_price, 8),
                high_price=round(high_price, 8),
                low_price=round(low_price, 8),
                close_price=round(close_price, 8),
                volume=round(1000 + abs(index - 1) * 120 + current_price * 0.01, 2),
                candle_time=now - timedelta(minutes=minutes),
            )
        )
    return candles


def _build_feature_row(symbol, timeframe, current_price, bias, row_id, now):
    trend_score = 72 if bias == "LONG" else 28 if bias == "SHORT" else 50
    momentum_score = 68 if bias == "LONG" else 32 if bias == "SHORT" else 50
    volatility_score = 45 if bias in {"LONG", "SHORT"} else 50
    liquidity_score = 66 if bias == "LONG" else 34 if bias == "SHORT" else 50
    final_score = 67 if bias == "LONG" else 33 if bias == "SHORT" else 50
    trend = "BULLISH" if bias == "LONG" else "BEARISH" if bias == "SHORT" else "NEUTRAL"
    signal = "BUY" if bias == "LONG" else "SELL" if bias == "SHORT" else "WAIT"

    from app.database.models.market_features import MarketFeature

    return MarketFeature(
        Id=row_id,
        Symbol=symbol,
        Timeframe=timeframe,
        TrendScore=trend_score,
        MomentumScore=momentum_score,
        ATR=round(current_price * 0.008, 8),
        VolatilityScore=volatility_score,
        LiquidityScore=liquidity_score,
        FinalScore=final_score,
        Trend=trend,
        Signal=signal,
        CreatedAt=now - timedelta(minutes=3),
    )


def _build_regime_row(symbol, timeframe, current_price, bias, row_id, now):
    regime = "TRENDING_BULL" if bias == "LONG" else "TRENDING_BEAR" if bias == "SHORT" else "RANGE"
    strategy = "LONG_RALLY" if bias == "LONG" else "SHORT_RALLY" if bias == "SHORT" else "WAIT"
    reason = (
        "Bullish structure with higher timeframe support"
        if bias == "LONG"
        else "Bearish structure with lower timeframe pressure"
        if bias == "SHORT"
        else "Balanced structure"
    )

    from app.database.models.market_regimes import MarketRegime

    return MarketRegime(
        Id=row_id,
        Symbol=symbol,
        Timeframe=timeframe,
        Regime=regime,
        Confidence=85.0 if bias in {"LONG", "SHORT"} else 60.0,
        RecommendedStrategy=strategy,
        Reason=reason,
        CreatedAt=now - timedelta(minutes=3),
    )


def _build_orderflow_row(symbol, timeframe, current_price, bias, row_id, now):
    from app.database.models.market_order_flow import MarketOrderFlow

    bullish = bias == "LONG"
    bearish = bias == "SHORT"
    flow_signal = "BUYERS_CONTROL" if bullish else "SELLERS_CONTROL" if bearish else "BALANCED"
    absorption = "BUYER_ABSORPTION" if bullish else "SELLER_ABSORPTION" if bearish else "NEUTRAL_ABSORPTION"
    exhaustion = "SELLER_EXHAUSTION" if bullish else "BUYER_EXHAUSTION" if bearish else "NEUTRAL_EXHAUSTION"

    return MarketOrderFlow(
        Id=row_id,
        Symbol=symbol,
        Timeframe=timeframe,
        BuyVolume=round(current_price * (18 if bullish else 8 if bearish else 12), 2),
        SellVolume=round(current_price * (8 if bullish else 18 if bearish else 12), 2),
        Delta=round(current_price * (0.012 if bullish else -0.012 if bearish else 0.0), 4),
        CVD=round(current_price * (0.02 if bullish else -0.02 if bearish else 0.0), 4),
        BuyerStrength=72.0 if bullish else 32.0 if bearish else 50.0,
        SellerStrength=32.0 if bullish else 72.0 if bearish else 50.0,
        Absorption=absorption,
        Exhaustion=exhaustion,
        FlowSignal=flow_signal,
        Confidence=78.0 if bullish else 69.0 if bearish else 50.0,
        CreatedAt=now - timedelta(minutes=2),
    )


def _build_smc_row(symbol, timeframe, current_price, bias, row_id, now):
    from app.database.models.market_smc import MarketSMCSignal

    bullish = bias == "LONG"
    bearish = bias == "SHORT"
    return MarketSMCSignal(
        id=row_id,
        symbol=symbol,
        timeframe=timeframe,
        bos_detected=bullish,
        bos_type="BULL" if bullish else "BEAR" if bearish else "NONE",
        choch_detected=bearish,
        choch_type="BEAR" if bearish else "NONE",
        structure="UPTREND" if bullish else "DOWNTREND" if bearish else "RANGE",
        order_block_type="BULLISH" if bullish else "BEARISH" if bearish else "NONE",
        order_block_price=round(current_price * (0.992 if bullish else 1.008 if bearish else 1.0), 8),
        fvg_detected=True,
        fvg_price=round(current_price * (1.004 if bullish else 0.996 if bearish else 1.0), 8),
        liquidity_sweep=False,
        sweep_price=None,
        smc_bias="LONG" if bullish else "SHORT" if bearish else "NEUTRAL",
        confidence=72.0 if bullish else 67.0 if bearish else 50.0,
        created_at=now - timedelta(minutes=1),
    )


def _trade_plan_levels(current_price, side):
    atr = round(current_price * 0.008, 8)
    if side == "LONG":
        entry = round(current_price, 8)
        stop = round(entry - atr, 8)
        target1 = round(entry + atr * 2, 8)
        target2 = round(entry + atr * 3, 8)
        target3 = round(entry + atr * 4, 8)
    else:
        entry = round(current_price, 8)
        stop = round(entry + atr, 8)
        target1 = round(entry - atr * 2, 8)
        target2 = round(entry - atr * 3, 8)
        target3 = round(entry - atr * 4, 8)
    return entry, stop, target1, target2, target3, 2.0


def _master_signal_reasons(side):
    if side == "LONG":
        return "Feature trend bullish,Strong bullish order flow,Positive CVD,Bullish structure"
    return "Feature trend bearish,Strong bearish order flow,Negative CVD,Bearish structure"


def _seed_paper_trades(
    db,
    symbol,
    side,
    trade_plan_id,
    risk_id,
    thesis_id,
    current_price,
    now,
    paper_trade_id_start,
):
    from app.database.models.paper_trade import PaperTrade

    open_trade = PaperTrade(
        id=paper_trade_id_start,
        trade_plan_id=trade_plan_id,
        risk_decision_id=risk_id,
        thesis_id=thesis_id,
        symbol=symbol,
        side=side,
        entry_price=round(current_price, 8),
        stop_loss=round(current_price * (0.992 if side == "LONG" else 1.008), 8),
        target1=round(current_price * (1.016 if side == "LONG" else 0.984), 8),
        target2=round(current_price * (1.024 if side == "LONG" else 0.976), 8),
        position_size=1.25,
        risk_reward=2.0,
        risk_percent=1.0,
        confidence=78.0 if side == "LONG" else 69.0,
        status="OPEN",
        opened_at=now - timedelta(minutes=15),
        created_at=now - timedelta(minutes=15),
    )
    db.add(open_trade)

    closed_trade = PaperTrade(
        id=paper_trade_id_start + 1,
        trade_plan_id=trade_plan_id,
        risk_decision_id=risk_id,
        thesis_id=thesis_id,
        symbol=symbol,
        side=side,
        entry_price=round(current_price * (0.99 if side == "LONG" else 1.01), 8),
        stop_loss=round(current_price * (0.982 if side == "LONG" else 1.018), 8),
        target1=round(current_price * (1.018 if side == "LONG" else 0.982), 8),
        target2=round(current_price * (1.03 if side == "LONG" else 0.97), 8),
        position_size=1.0,
        risk_reward=2.0,
        risk_percent=1.0,
        confidence=74.0 if side == "LONG" else 68.0,
        status="CLOSED",
        exit_price=round(current_price * (1.025 if side == "LONG" else 0.975), 8),
        result="WIN",
        pnl_percent=3.25,
        opened_at=now - timedelta(days=1, minutes=30),
        closed_at=now - timedelta(minutes=20),
        created_at=now - timedelta(days=1, minutes=30),
    )
    db.add(closed_trade)
