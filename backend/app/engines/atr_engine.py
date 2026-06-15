class ATREngine:

    def calculate(self, candles, period=14):

        if len(candles) < period + 1:

            return 0

        trs = []

        for i in range(1, len(candles)):

            high = candles[i].high_price

            low = candles[i].low_price

            previous_close = candles[i - 1].close_price

            tr = max(high - low, abs(high - previous_close), abs(low - previous_close))

            trs.append(tr)

        atr = sum(trs[-period:]) / period

        return atr