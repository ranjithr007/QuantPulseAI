class PositionEngine:

    def calculate_rr(self, entry, stop, target):

        reward = abs(target - entry)

        risk = abs(entry - stop)

        return round(reward / risk, 2)