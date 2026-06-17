class InvalidationEngine:
    def calculate(self, side, entry, stop_loss, atr):
        if side not in {"LONG", "SHORT"}:
            return {
                "price": None,
                "rules": ["Unsupported side"],
            }

        buffer = atr * 0.25 if atr else abs(entry - stop_loss) * 0.1

        if side == "LONG":
            invalidation_price = stop_loss - buffer
            rules = [
                "Close below stop loss",
                "Break below invalidation price",
                "SMC bias flips SHORT",
            ]
        else:
            invalidation_price = stop_loss + buffer
            rules = [
                "Close above stop loss",
                "Break above invalidation price",
                "SMC bias flips LONG",
            ]

        return {
            "price": round(invalidation_price, 8),
            "rules": rules,
        }
