class PositionSizer:

    def calculate(self, capital, risk_percent, entry, stop):

        risk_amount = capital * risk_percent / 100

        risk_per_unit = abs(entry - stop)

        qty = risk_amount / risk_per_unit

        return qty