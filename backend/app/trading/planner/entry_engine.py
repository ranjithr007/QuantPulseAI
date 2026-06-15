class EntryEngine:

    def calculate(self, price, side):

        if side == "LONG":

            return price * 0.998

        if side == "SHORT":

            return price * 1.002

        return None