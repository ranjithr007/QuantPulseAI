class SMCEngine:

    def find_swings(self, candles, lookback=3):

        swing_highs = []

        swing_lows = []

        for i in range(lookback, len(candles) - lookback):

            current = candles[i]

            left = candles[i - lookback : i]

            right = candles[i + 1 : i + lookback + 1]

            if all(current.high_price > x.high_price for x in left + right):

                swing_highs.append(current)

            if all(current.low_price < x.low_price for x in left + right):

                swing_lows.append(current)

        return (swing_highs, swing_lows)

    def analyze(self, candles):

        score = 50

        reasons = []

        last = candles[-1]

        swing_highs, swing_lows = self.find_swings(candles)

        if len(swing_highs) == 0 or len(swing_lows) == 0:

            return {
                "structure": "RANGE",
                "bos": "NONE",
                "choch": "NONE",
                "liquidity_sweep": "NONE",
                "smc_score": 50,
                "reason": ["Not enough structure"],
            }

        previous_high = swing_highs[-1].high_price

        previous_low = swing_lows[-1].low_price

        bos = "NONE"

        choch = "NONE"

        sweep = "NONE"

        structure = "RANGE"

        # ======================
        # REAL BOS
        # ======================

        if last.close_price > previous_high:

            bos = "BULLISH_BOS"

            structure = "BULLISH_STRUCTURE"

            score += 25

            reasons.append("Break of swing high")

        elif last.close_price < previous_low:

            bos = "BEARISH_BOS"

            structure = "BEARISH_STRUCTURE"

            score -= 25

            reasons.append("Break of swing low")

        # ======================
        # CHoCH
        # ======================

        if len(swing_highs) >= 2:

            old_high = swing_highs[-2].high_price

            if previous_high < old_high and bos == "BULLISH_BOS":

                choch = "BULLISH_CHOCH"

                score += 20

                reasons.append("Bullish character change")

        if len(swing_lows) >= 2:

            old_low = swing_lows[-2].low_price

            if previous_low > old_low and bos == "BEARISH_BOS":

                choch = "BEARISH_CHOCH"

                score -= 20

                reasons.append("Bearish character change")

        # ======================
        # Liquidity Sweep
        # ======================

        if last.low_price < previous_low and last.close_price > previous_low:

            sweep = "SELL_SIDE_SWEEP"

            score += 25

            reasons.append("Sell liquidity swept")

        elif last.high_price > previous_high and last.close_price < previous_high:

            sweep = "BUY_SIDE_SWEEP"

            score -= 25

            reasons.append("Buy liquidity swept")

        # ======================
        # Order Block
        # ======================

        order_block_type, order_block_price = self.detect_order_block(candles, bos)

        if order_block_type == "BULLISH_OB":

            score += 15

            reasons.append("Bullish order block found")

        elif order_block_type == "BEARISH_OB":

            score -= 15

        # ======================
        # FVG
        # ======================

        fvg_direction, fvg_size = self.detect_fvg(candles)

        if fvg_direction == "BULLISH_FVG":

            score += 10

        elif fvg_direction == "BEARISH_FVG":

            score -= 10

        return {
            "structure": structure,
            "bos": bos,
            "choch": choch,
            "liquidity_sweep": sweep,
            "order_block_type": order_block_type,
            "order_block_price": order_block_price,
            "fvg_direction": fvg_direction,
            "fvg_size": fvg_size,
            "smc_score": max(0, min(score, 100)),
            "reason": reasons,
        }

    def detect_order_block(self, candles, bos):

        if bos == "NONE":

            return ("NONE", 0)

        recent = candles[-10:]

        # Bullish BOS
        # find last red candle

        if bos == "BULLISH_BOS":

            for candle in reversed(recent):

                if candle.close_price < candle.open_price:

                    return ("BULLISH_OB", candle.low_price)

        # Bearish BOS
        # find last green candle

        if bos == "BEARISH_BOS":

            for candle in reversed(recent):

                if candle.close_price > candle.open_price:

                    return ("BEARISH_OB", candle.high_price)

        return ("NONE", 0)

    def detect_fvg(self, candles):

        if len(candles) < 3:

            return ("NONE", 0)

        c1 = candles[-3]

        c3 = candles[-1]

        # Bullish FVG

        if c1.high_price < c3.low_price:

            gap = c3.low_price - c1.high_price

            return ("BULLISH_FVG", gap)

        # Bearish FVG

        if c1.low_price > c3.high_price:

            gap = c1.low_price - c3.high_price

            return ("BEARISH_FVG", gap)

        return ("NONE", 0)