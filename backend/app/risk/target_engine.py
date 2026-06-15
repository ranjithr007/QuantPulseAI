class TargetEngine:

    def calculate(self, signal, entry, stop):

        risk = abs(entry - stop)

        if signal == "BUY":

            return {"t1": entry + risk * 2, "t2": entry + risk * 3}

        if signal == "SELL":

            return {"t1": entry - risk * 2, "t2": entry - risk * 3}