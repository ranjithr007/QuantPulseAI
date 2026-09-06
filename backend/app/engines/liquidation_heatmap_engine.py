from datetime import datetime, timedelta, timezone

from app.database.models.liquidations import Liquidation
from app.utils.freshness import normalize_timestamp_to_naive_utc
from app.intelligence.liquidation_evidence import observed_liquidation_evidence


LIQUIDATION_HEATMAP_LOOKBACK_SECONDS = 4 * 60 * 60


class LiquidationHeatmapEngine:

    def analyze(self, db, symbol, current_price, *, as_of_timestamp=None):

        as_of = normalize_timestamp_to_naive_utc(
            as_of_timestamp or datetime.now(timezone.utc)
        )
        cutoff = as_of - timedelta(seconds=LIQUIDATION_HEATMAP_LOOKBACK_SECONDS)

        liquidations = (
            db.query(Liquidation)
            .filter(Liquidation.symbol == symbol)
            .filter(Liquidation.venue == "BINANCE", Liquidation.price > 0, Liquidation.value_usd > 0)
            .filter(Liquidation.event_time >= cutoff)
            .filter(Liquidation.event_time <= as_of)
            .order_by(Liquidation.event_time.desc())
            .limit(500)
            .all()
        )

        above = {}
        below = {}
        step = max(float(current_price) * .001, .000001)
        for liq in liquidations:
            level = round(round(liq.price / step) * step, 6)
            if liq.price > current_price:
                above[level] = above.get(level, 0) + liq.value_usd
            else:
                below[level] = below.get(level, 0) + liq.value_usd

        top_above = max(above, key=above.get) if above else None
        top_below = max(below, key=below.get) if below else None
        above_value = above.get(top_above, 0)
        below_value = below.get(top_below, 0)

        # Clusters describe historical prices, not the side liquidated. Only
        # actual forced-order sides may contribute directional evidence.
        evidence = observed_liquidation_evidence(db, symbol, as_of_timestamp=as_of)
        return {
            "symbol": symbol,
            "current_price": current_price,
            "liquidity_above": top_above,
            "liquidity_below": top_below,
            "above_value": above_value,
            "below_value": below_value,
            "target_price": current_price,
            "bias": evidence["bias"],
            "confidence": evidence["confidence"],
            "source_window_start": cutoff,
            "source_window_end": as_of,
            "source_event_count": evidence["source_event_count"],
            "observed_liquidations": evidence,
        }
