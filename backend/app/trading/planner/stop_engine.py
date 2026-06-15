class StopEngine:

    def calculate(self, entry, atr, side):

        if side == "LONG":

            return entry - atr * 1.5

        else:

            return entry + atr * 1.5