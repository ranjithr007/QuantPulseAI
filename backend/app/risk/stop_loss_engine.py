class StopLossEngine:

    def calculate(self, signal, entry, atr):

        if signal in {"BUY", "LONG"}:

            return entry - (atr * 1.5)

        elif signal in {"SELL", "SHORT"}:

            return entry + (atr * 1.5)

        return None
