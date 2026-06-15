class TargetEngine:

    def calculate(self, entry, stop, side):

        risk = abs(entry - stop)

        if side == "LONG":

            return [entry + risk * 1.5, entry + risk * 2.5, entry + risk * 4]

        else:

            return [entry - risk * 1.5, entry - risk * 2.5, entry - risk * 4]