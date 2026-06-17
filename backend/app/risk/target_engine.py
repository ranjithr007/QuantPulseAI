class TargetEngine:

    def calculate(self, signal, entry, stop):

        risk = abs(entry - stop)

        if signal in {"BUY", "LONG"}:

            return {"t1": entry + risk * 2, "t2": entry + risk * 3}

        if signal in {"SELL", "SHORT"}:

            return {"t1": entry - risk * 2, "t2": entry - risk * 3}

        return None
