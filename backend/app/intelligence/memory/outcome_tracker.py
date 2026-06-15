
class OutcomeTracker:

    def evaluate(self, trade, current_price):

        if trade.side == "LONG":

            if current_price >= trade.target1:

                return "WIN"

            if current_price <= trade.stop_loss:

                return "LOSS"

        if trade.side == "SHORT":

            if current_price <= trade.target1:

                return "WIN"

            if current_price >= trade.stop_loss:

                return "LOSS"

        return "OPEN"
