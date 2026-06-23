from dataclasses import dataclass


@dataclass(frozen=True)
class SwingHighPoint:
    index: int
    high_price: float


@dataclass(frozen=True)
class SwingLowPoint:
    index: int
    low_price: float
class SMCEngine:

    def find_swings(self, candles, swing_length=2):

        swing_highs = []
        swing_lows = []

        if not candles:
            return swing_highs, swing_lows

        minimum_candles = (swing_length * 2) + 1

        if len(candles) < minimum_candles:
            return swing_highs, swing_lows

        # Excludes the latest swing_length candles because they
        # do not yet have enough candles on their right side.
        for index in range(
            swing_length,
            len(candles) - swing_length,
        ):

            current = candles[index]

            left_candles = candles[
                index - swing_length:index
            ]

            right_candles = candles[
                index + 1:index + swing_length + 1
            ]

            surrounding_candles = left_candles + right_candles

            is_swing_high = all(
                float(current.high_price) > float(candle.high_price)
                for candle in surrounding_candles
            )

            is_swing_low = all(
                float(current.low_price) < float(candle.low_price)
                for candle in surrounding_candles
            )

            if is_swing_high:
                swing_highs.append(
                    SwingHighPoint(
                        index=index,
                        high_price=float(current.high_price),
                    )
                )

            if is_swing_low:
                swing_lows.append(
                    SwingLowPoint(
                        index=index,
                        low_price=float(current.low_price),
                    )
                )

        return swing_highs, swing_lows

    def analyze(self, candles):

        # =========================
        # Configurable parameters
        # =========================

        SWING_CONFIRMATION_BARS = 2

        # 0.0005 means 0.05%.
        # Set to 0 if you want any close beyond the level to count.
        BOS_BUFFER_PCT = 0.0005

        # Price can be this far from an order-block level and still count as tested.
        # 0.002 means 0.20%.
        ORDER_BLOCK_TOLERANCE_PCT = 0.002

        BOS_WEIGHT = 25
        CHOCH_WEIGHT = 20
        SWEEP_WEIGHT = 15
        ORDER_BLOCK_WEIGHT = 10
        FVG_WEIGHT = 5

        MAX_DIRECTIONAL_WEIGHT = (
            BOS_WEIGHT
            + SWEEP_WEIGHT
            + ORDER_BLOCK_WEIGHT
            + FVG_WEIGHT
        )

        default_result = {
            "structure": "RANGE",
            "bos": "NONE",
            "choch": "NONE",
            "liquidity_sweep": "NONE",
            "order_block_type": "NONE",
            "order_block_price": None,
            "fvg_direction": "NONE",
            "fvg_size": 0,
            "smc_score": 50,
            "reason": [],
        }

        if not candles or len(candles) < 5:
            default_result["reason"] = ["Not enough candles"]
            return default_result

        last = candles[-1]
        current_index = len(candles) - 1

        reasons = []

        bullish_points = 0
        bearish_points = 0

        swing_highs, swing_lows = self.find_swings(candles)

        # =========================
        # Confirmed swing filtering
        # =========================

        def get_swing_index(swing):
            """
            Supports different possible field names.

            Prefer returning an 'index' property from find_swings().
            """
            return getattr(
                swing,
                "index",
                getattr(
                    swing,
                    "candle_index",
                    getattr(swing, "bar_index", None),
                ),
            )

        def is_confirmed(swing):
            swing_index = get_swing_index(swing)

            # If no index is available, this assumes find_swings()
            # already returns only confirmed swings.
            if swing_index is None:
                return True

            return swing_index <= (
                current_index - SWING_CONFIRMATION_BARS
            )

        confirmed_highs = [
            swing for swing in swing_highs
            if is_confirmed(swing)
        ]

        confirmed_lows = [
            swing for swing in swing_lows
            if is_confirmed(swing)
        ]

        if not confirmed_highs or not confirmed_lows:
            default_result["reason"] = [
                "Not enough confirmed market structure"
            ]
            return default_result

        previous_high = float(confirmed_highs[-1].high_price)
        previous_low = float(confirmed_lows[-1].low_price)

        # =========================
        # Determine prior structure
        # =========================

        prior_structure = "RANGE"

        if len(confirmed_highs) >= 2 and len(confirmed_lows) >= 2:

            older_high = float(confirmed_highs[-2].high_price)
            recent_high = float(confirmed_highs[-1].high_price)

            older_low = float(confirmed_lows[-2].low_price)
            recent_low = float(confirmed_lows[-1].low_price)

            higher_high = recent_high > older_high
            higher_low = recent_low > older_low

            lower_high = recent_high < older_high
            lower_low = recent_low < older_low

            if higher_high and higher_low:
                prior_structure = "BULLISH_STRUCTURE"

            elif lower_high and lower_low:
                prior_structure = "BEARISH_STRUCTURE"

        structure = prior_structure
        bos = "NONE"
        choch = "NONE"
        sweep = "NONE"

        close_price = float(last.close_price)
        high_price = float(last.high_price)
        low_price = float(last.low_price)

        bullish_break_level = previous_high * (1 + BOS_BUFFER_PCT)
        bearish_break_level = previous_low * (1 - BOS_BUFFER_PCT)

        bullish_break = close_price > bullish_break_level
        bearish_break = close_price < bearish_break_level

        # =========================
        # BOS or CHoCH
        # =========================

        if bullish_break:

            structure = "BULLISH_STRUCTURE"

            if prior_structure == "BEARISH_STRUCTURE":

                choch = "BULLISH_CHOCH"
                bullish_points += CHOCH_WEIGHT

                reasons.append(
                    "Bullish CHoCH: price closed above the confirmed "
                    "swing high against the previous bearish structure"
                )

            else:

                bos = "BULLISH_BOS"
                bullish_points += BOS_WEIGHT

                reasons.append(
                    "Bullish BOS: price closed above the confirmed swing high"
                )

        elif bearish_break:

            structure = "BEARISH_STRUCTURE"

            if prior_structure == "BULLISH_STRUCTURE":

                choch = "BEARISH_CHOCH"
                bearish_points += CHOCH_WEIGHT

                reasons.append(
                    "Bearish CHoCH: price closed below the confirmed "
                    "swing low against the previous bullish structure"
                )

            else:

                bos = "BEARISH_BOS"
                bearish_points += BOS_WEIGHT

                reasons.append(
                    "Bearish BOS: price closed below the confirmed swing low"
                )

        # =========================
        # Liquidity sweep
        # =========================

        sell_side_sweep = (
            low_price < previous_low
            and close_price > previous_low
        )

        buy_side_sweep = (
            high_price > previous_high
            and close_price < previous_high
        )

        if sell_side_sweep and buy_side_sweep:

            # Large outside candle swept both sides.
            # Avoid assigning directional points.
            reasons.append(
                "Both buy-side and sell-side liquidity were swept"
            )

        elif sell_side_sweep:

            sweep = "SELL_SIDE_SWEEP"
            bullish_points += SWEEP_WEIGHT

            if bullish_break:
                reasons.append(
                    "Sell-side liquidity swept before bullish expansion"
                )
            else:
                reasons.append("Sell-side liquidity swept")

        elif buy_side_sweep:

            sweep = "BUY_SIDE_SWEEP"
            bearish_points += SWEEP_WEIGHT

            if bearish_break:
                reasons.append(
                    "Buy-side liquidity swept before bearish expansion"
                )
            else:
                reasons.append("Buy-side liquidity swept")

        # =========================
        # Order block
        # =========================

        # detect_order_block may expect BOS naming.
        # Convert CHoCH into its corresponding break direction.
        break_for_order_block = bos

        if choch == "BULLISH_CHOCH":
            break_for_order_block = "BULLISH_BOS"

        elif choch == "BEARISH_CHOCH":
            break_for_order_block = "BEARISH_BOS"

        order_block_type, order_block_price = self.detect_order_block(
            candles,
            break_for_order_block,
        )

        order_block_type = order_block_type or "NONE"

        order_block_touched = False

        if order_block_price is not None:

            order_block_price = float(order_block_price)

            tolerance = close_price * ORDER_BLOCK_TOLERANCE_PCT

            order_block_touched = (
                low_price - tolerance
                <= order_block_price
                <= high_price + tolerance
            )

        if order_block_type == "BULLISH_OB":

            if order_block_touched:

                bullish_points += ORDER_BLOCK_WEIGHT
                reasons.append(
                    "Price is testing a bullish order block"
                )

            else:
                reasons.append(
                    "Bullish order block detected but not currently tested"
                )

        elif order_block_type == "BEARISH_OB":

            if order_block_touched:

                bearish_points += ORDER_BLOCK_WEIGHT
                reasons.append(
                    "Price is testing a bearish order block"
                )

            else:
                reasons.append(
                    "Bearish order block detected but not currently tested"
                )

        # =========================
        # Fair Value Gap
        # =========================

        fvg_direction, fvg_size = self.detect_fvg(candles)

        fvg_direction = fvg_direction or "NONE"
        fvg_size = float(fvg_size or 0)

        bullish_signal_active = (
            bullish_break
            or sweep == "SELL_SIDE_SWEEP"
        )

        bearish_signal_active = (
            bearish_break
            or sweep == "BUY_SIDE_SWEEP"
        )

        if (
            fvg_direction == "BULLISH_FVG"
            and bullish_signal_active
        ):

            bullish_points += FVG_WEIGHT
            reasons.append(
                "Bullish FVG supports the bullish structure signal"
            )

        elif (
            fvg_direction == "BEARISH_FVG"
            and bearish_signal_active
        ):

            bearish_points += FVG_WEIGHT
            reasons.append(
                "Bearish FVG supports the bearish structure signal"
            )

        elif fvg_direction != "NONE":

            reasons.append(
                f"{fvg_direction} detected but not aligned with the current signal"
            )

        # =========================
        # Normalized score
        # =========================

        directional_difference = bullish_points - bearish_points

        normalized_difference = (
            directional_difference
            / MAX_DIRECTIONAL_WEIGHT
        ) * 50

        score = 50 + normalized_difference
        score = round(max(0, min(score, 100)), 2)

        if not reasons:
            reasons.append(
                "No significant SMC event detected"
            )
       
        return {
            "structure": structure,
            "bos": bos,
            "choch": choch,
            "liquidity_sweep": sweep,
            "order_block_type": order_block_type,
            "order_block_price": order_block_price,
            "fvg_direction": fvg_direction,
            "fvg_size": fvg_size,
            "smc_score": score,
            "reason": reasons,
        }
    # def analyze(self, candles):

    #     score = 50

    #     reasons = []

    #     last = candles[-1]

    #     swing_highs, swing_lows = self.find_swings(candles)

    #     if len(swing_highs) == 0 or len(swing_lows) == 0:

    #         return {
    #             "structure": "RANGE",
    #             "bos": "NONE",
    #             "choch": "NONE",
    #             "liquidity_sweep": "NONE",
    #             "smc_score": 50,
    #             "reason": ["Not enough structure"],
    #         }

    #     previous_high = swing_highs[-1].high_price

    #     previous_low = swing_lows[-1].low_price

    #     bos = "NONE"

    #     choch = "NONE"

    #     sweep = "NONE"

    #     structure = "RANGE"

    #     # ======================
    #     # REAL BOS
    #     # ======================

    #     if last.close_price > previous_high:

    #         bos = "BULLISH_BOS"

    #         structure = "BULLISH_STRUCTURE"

    #         score += 25

    #         reasons.append("Break of swing high")

    #     elif last.close_price < previous_low:

    #         bos = "BEARISH_BOS"

    #         structure = "BEARISH_STRUCTURE"

    #         score -= 25

    #         reasons.append("Break of swing low")

    #     # ======================
    #     # CHoCH
    #     # ======================

    #     if len(swing_highs) >= 2:

    #         old_high = swing_highs[-2].high_price

    #         if previous_high < old_high and bos == "BULLISH_BOS":

    #             choch = "BULLISH_CHOCH"

    #             score += 20

    #             reasons.append("Bullish character change")

    #     if len(swing_lows) >= 2:

    #         old_low = swing_lows[-2].low_price

    #         if previous_low > old_low and bos == "BEARISH_BOS":

    #             choch = "BEARISH_CHOCH"

    #             score -= 20

    #             reasons.append("Bearish character change")

    #     # ======================
    #     # Liquidity Sweep
    #     # ======================

    #     if last.low_price < previous_low and last.close_price > previous_low:

    #         sweep = "SELL_SIDE_SWEEP"

    #         score += 25

    #         reasons.append("Sell liquidity swept")

    #     elif last.high_price > previous_high and last.close_price < previous_high:

    #         sweep = "BUY_SIDE_SWEEP"

    #         score -= 25

    #         reasons.append("Buy liquidity swept")

    #     # ======================
    #     # Order Block
    #     # ======================

    #     order_block_type, order_block_price = self.detect_order_block(candles, bos)

    #     if order_block_type == "BULLISH_OB":

    #         score += 15

    #         reasons.append("Bullish order block found")

    #     elif order_block_type == "BEARISH_OB":

    #         score -= 15

    #     # ======================
    #     # FVG
    #     # ======================

    #     fvg_direction, fvg_size = self.detect_fvg(candles)

    #     if fvg_direction == "BULLISH_FVG":

    #         score += 10

    #     elif fvg_direction == "BEARISH_FVG":

    #         score -= 10

    #     return {
    #         "structure": structure,
    #         "bos": bos,
    #         "choch": choch,
    #         "liquidity_sweep": sweep,
    #         "order_block_type": order_block_type,
    #         "order_block_price": order_block_price,
    #         "fvg_direction": fvg_direction,
    #         "fvg_size": fvg_size,
    #         "smc_score": max(0, min(score, 100)),
    #         "reason": reasons,
    #     }

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