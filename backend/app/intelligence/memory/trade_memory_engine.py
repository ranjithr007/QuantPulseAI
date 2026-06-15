from app.intelligence.memory.outcome_tracker import OutcomeTracker

from app.repositories.trade_plan_repository import TradePlanRepository


class TradeMemoryEngine:

    def __init__(self):

        self.tracker = OutcomeTracker()

        self.repo = TradePlanRepository()

    def process(self, db, trades, price_provider):

        updated = []

        for trade in trades:

            price = price_provider(trade.symbol)
            if price is None:
                continue

            result = self.tracker.evaluate(trade, price)

            if result != "OPEN":

                closed = self.repo.close_trade(db, trade, price, result)

                updated.append(closed)

        return updated