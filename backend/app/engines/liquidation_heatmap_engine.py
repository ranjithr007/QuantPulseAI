from app.database.models.liquidations import Liquidation


class LiquidationHeatmapEngine:

    def analyze(self, db, symbol, current_price):

        liquidations = (
            db.query(Liquidation)
            .filter(Liquidation.symbol == symbol)
            .order_by(Liquidation.event_time.desc())
            .limit(500)
            .all()
        )

        above = {}
        below = {}
        for liq in liquidations:
            level = round(liq.price / 100) * 100
            if liq.price > current_price:
                above[level] = above.get(level, 0) + liq.value_usd
            else:
                below[level] = below.get(level, 0) + liq.value_usd

        top_above = max(above, key=above.get) if above else None
        top_below = max(below, key=below.get) if below else None
        above_value = above[top_above] if top_above else 0
        below_value = below[top_below] if top_below else 0

        # =============================
        # No liquidation data fallback
        # Estimate liquidation zones
        # =============================

        if top_above is None and top_below is None:

            top_above = round(current_price * 1.02, 5)

            top_below = round(current_price * 0.98, 5)

            above_value = 0
            below_value = 0
            bias = "ESTIMATED"
            target = top_below
            confidence = 30

        else:

            if below_value > above_value:
                bias = "HUNT_LONGS"
                target = top_below

            elif above_value > below_value:
                bias = "HUNT_SHORTS"
                target = top_above

            else:

                bias = "NEUTRAL"
                target = current_price

        total = above_value + below_value

        confidence = max(above_value, below_value) / total * 100 if total > 0 else 0

        return {
            "symbol": symbol,
            "current_price": current_price,
            "liquidity_above": top_above,
            "liquidity_below": top_below,
            "above_value": above_value,
            "below_value": below_value,
            "target_price": target,
            "bias": bias,
            "confidence": round(confidence, 2),
        }