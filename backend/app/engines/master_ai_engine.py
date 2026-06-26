from app.repositories.orderflow_repository import OrderFlowRepository
from app.engines.orderflow_score_engine import OrderFlowScoreEngine
from app.engines.smart_money_fusion_engine import SmartMoneyFusionEngine
from app.repositories.smc_repository import SMCRepository
from app.risk.risk_engine import RiskEngine


class MasterAIEngine:

    def __init__(self):

        self.order_repo = OrderFlowRepository()

        self.order_engine = OrderFlowScoreEngine()
        self.smart_money_engine = SmartMoneyFusionEngine()
        self.smc_repo = SMCRepository()
        self.risk_engine = RiskEngine()

    def analyze(self, db, symbol, liquidity, heatmap, whale, current_price, atr):

        long_score = 0

        short_score = 0

        reasons = []

        smc = self.smc_repo.latest(db, symbol)
        if smc:
            if smc.confidence >= 70:

                long_score += 25

                reasons.append("Bullish SMC structure")
            elif smc.confidence <= 30:

                short_score += 25

                reasons.append("Bearish SMC structure")
        # ==================
        # Liquidity Engine
        # ==================

        if liquidity.long_squeeze_probability > 50:

            short_score += 30

            reasons.append("Long liquidation risk")

        if liquidity.short_squeeze_probability > 50:

            long_score += 30

            reasons.append("Short liquidation opportunity")

        # ==================
        # Heatmap Engine
        # ==================

        if heatmap.bias == "HUNT_LONGS":

            short_score += 30

            reasons.append("Liquidity below price")

        elif heatmap.bias == "HUNT_SHORTS":

            long_score += 30

            reasons.append("Liquidity above price")

        # ==================
        # Whale Engine
        # ==================

        if whale.bias == "DISTRIBUTION":

            short_score += 30

            reasons.append("Whales distributing")

        elif whale.bias == "ACCUMULATION":

            long_score += 30

            reasons.append("Whales accumulating")

        # ============================
        # Order Flow Engine (NEW)
        # ============================
        orderflow = self.order_repo.latest(db, symbol)
        order_score = 50
        if orderflow:
            order_score = self.order_engine.calculate(orderflow)

        if order_score >= 65:

            long_score += 40

            reasons.append("Strong bullish order flow")

        elif order_score <= 35:

            short_score += 40

            reasons.append("Strong bearish order flow")

        if orderflow:

            # CVD confirmation

            if orderflow.cumulative_delta > 0:

                reasons.append("Positive CVD")

            else:

                reasons.append("Negative CVD")

            # Absorption

            if orderflow.absorption_type == "BUY_ABSORPTION":

                long_score += 15

                reasons.append("Buy absorption detected")

            elif orderflow.absorption_type == "SELL_ABSORPTION":

                short_score += 15

                reasons.append("Sell absorption detected")

            # Exhaustion

            if orderflow.exhaustion_type == "BUYER_EXHAUSTION":

                short_score += 15

                reasons.append("Buyer exhaustion")

            elif orderflow.exhaustion_type == "SELLER_EXHAUSTION":

                long_score += 15

                reasons.append("Seller exhaustion")

        smart_money = self.smart_money_engine.analyze(smc, orderflow)
        if smart_money["bias"] == "SMART_MONEY_LONG":
            long_score += smart_money["score"]
            reasons.extend(smart_money["reasons"])

        elif smart_money["bias"] == "SMART_MONEY_SHORT":
            short_score += smart_money["score"]
            reasons.extend(smart_money["reasons"])

        # ==================
        # Final Decision
        # ==================

        confidence = abs(long_score - short_score)

        if long_score > short_score and confidence >= 20:

            signal = "LONG"

        elif short_score > long_score and confidence >= 20:

            signal = "SHORT"

        else:

            signal = "WAIT"

        if confidence >= 80:

            risk = "LOW"

        elif confidence >= 50:

            risk = "MEDIUM"

        else:

            risk = "HIGH"
        trade_risk = self.risk_engine.calculate(
            signal=signal, price=current_price, atr=atr
        )
        return {
            "symbol": symbol,
            "signal": signal,
            "confidence": min(confidence, 100),
            "long_score": long_score,
            "short_score": short_score,
            "orderflow_score": order_score,
            "risk": risk,
            "entry_price": trade_risk.get("entry_price"),
            "stop_loss": trade_risk.get("stop_loss"),
            "target_price": trade_risk.get("target_price"),
            "risk_reward": trade_risk.get("risk_reward"),
            "position_size": trade_risk.get("position_size"),
            "trade_allowed": trade_risk.get("trade_allowed"),
            "reasons": ",".join(reasons),
        }
