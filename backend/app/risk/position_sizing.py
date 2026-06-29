from math import isfinite


class PositionSizer:

    def calculate(
        self,
        capital,
        risk_percent,
        entry,
        stop,
        max_notional=None,
    ):
        capital = float(capital)
        risk_percent = float(risk_percent)
        entry = float(entry)
        stop = float(stop)

        values = [capital, risk_percent, entry, stop]

        if not all(isfinite(value) for value in values):
            raise ValueError("Position sizing values must be finite numbers")

        if capital <= 0:
            raise ValueError("Capital must be greater than zero")

        if not 0 < risk_percent <= 100:
            raise ValueError("Risk percentage must be between 0 and 100")

        if entry <= 0 or stop <= 0:
            raise ValueError("Entry and stop must be positive")

        risk_per_unit = abs(entry - stop)

        if risk_per_unit <= 0:
            raise ValueError("Entry and stop cannot be equal")

        risk_amount = capital * risk_percent / 100
        quantity = risk_amount / risk_per_unit

        if max_notional is not None:
            max_notional = float(max_notional)

            if max_notional <= 0:
                raise ValueError("Maximum notional must be positive")

            quantity = min(
                quantity,
                max_notional / entry,
            )

        if not isfinite(quantity) or quantity <= 0:
            raise ValueError("Calculated position size is invalid")

        return quantity