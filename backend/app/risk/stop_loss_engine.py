class StopLossEngine:

    def calculate(self, signal, entry, atr):

        if signal == "BUY":

            return entry - (atr * 1.5)

        elif signal == "SELL":

            return entry + (atr * 1.5)

        return None