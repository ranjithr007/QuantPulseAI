class LiquidityEngine:

    def analyze(self, symbol, funding, oi_change, price_change):

        long_squeeze = 0

        short_squeeze = 0

        reasons = []

        # ======================
        # Funding pressure
        # ======================

        if funding > 0:

            long_squeeze += 10

            reasons.append("Long bias funding")

        if funding < 0:

            short_squeeze += 10

            reasons.append("Short bias funding")

        if funding > 0.0001:

            long_squeeze += 20

            reasons.append("High positive funding")

        if funding < -0.0001:

            short_squeeze += 20

            reasons.append("High negative funding")

        # ======================
        # OI Expansion
        # ======================

        if oi_change > 0:

            score = min(oi_change * 500, 30)

            long_squeeze += score

            short_squeeze += score

            reasons.append(f"OI increasing {round(oi_change,3)}%")

        elif oi_change < 0:

            reasons.append("Leverage unwinding")

        # ======================
        # Long trap
        # ======================

        if price_change < 0 and oi_change > 0 and funding > 0:

            long_squeeze += 40

            reasons.append("Potential long trap")

        # ======================
        # Short trap
        # ======================

        if price_change > 0 and oi_change > 0 and funding < 0:

            short_squeeze += 40

            reasons.append("Potential short trap")

        # ======================
        # OI unwinding
        # ======================

        if oi_change < 0:
            reasons.append("Open interest reducing")

        signal = "NEUTRAL"

        if long_squeeze >= 70:

            signal = "LONG_SQUEEZE_RISK"

        elif short_squeeze >= 70:

            signal = "SHORT_SQUEEZE_RISK"

        elif long_squeeze >= 50:

            signal = "LONG_LIQUIDATION_BUILDING"

        elif short_squeeze >= 50:

            signal = "SHORT_LIQUIDATION_BUILDING"
        return {
            "symbol": symbol,
            "signal": signal,
            "long_squeeze_probability": round(long_squeeze, 2),
            "short_squeeze_probability": round(short_squeeze, 2),
            "confidence": round(max(long_squeeze, short_squeeze), 2),
            "reason": reasons,
        }