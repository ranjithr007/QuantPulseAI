class StructureEngine:

    def detect(self, candles):

        last = candles[-1]
        previous = candles[-2]

        if last.high_price > previous.high_price and last.low_price > previous.low_price:

            return "BULLISH_BOS"

        if last.low_price < previous.low_price and last.high_price < previous.high_price:

            return "BEARISH_BOS"

        if last.high_price > previous.high_price and last.low_price < previous.low_price:

            return "CHOCH"

        return "RANGE"