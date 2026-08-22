import unittest

from app.risk.risk_engine import RiskEngine
from app.trading.trade_plan_engine import build_trade_plan
from app.trading.trade_plan_engine import price_precision


class Phase0RiskTradePlanTests(unittest.TestCase):
    def test_wait_trade_plan_includes_atr(self):
        trade = build_trade_plan("WAIT", 100.0)

        self.assertEqual(trade["risk_reward"], 0)
        self.assertIn("atr", trade)
        self.assertEqual(trade["atr"], 1.0)

    def test_risk_engine_rejects_wait_without_error(self):
        risk = RiskEngine().analyze("BTCUSDT", "WAIT", 100.0, 1.0, 80)

        self.assertEqual(risk["decision"], "REJECT")
        self.assertEqual(risk["reason"], "No actionable trade signal")

    def test_risk_engine_accepts_long_short_names(self):
        long_risk = RiskEngine().analyze("BTCUSDT", "LONG", 100.0, 1.0, 80)
        short_risk = RiskEngine().analyze("BTCUSDT", "SHORT", 100.0, 1.0, 80)

        self.assertEqual(long_risk["decision"], "APPROVE")
        self.assertEqual(short_risk["decision"], "APPROVE")

    def test_risk_engine_approves_valid_persisted_trade_plan(self):
        risk = RiskEngine().analyze_trade_plan(
            symbol="BTCUSDT",
            side="LONG",
            entry=100.0,
            stop_loss=99.0,
            target1=102.0,
            target2=103.0,
            confidence=80,
        )

        self.assertEqual(risk["decision"], "APPROVE")
        self.assertEqual(risk["risk_reward"], 2.0)
        self.assertGreater(risk["position_size"], 0)
        self.assertEqual(risk["risk_percent"], 1)
        self.assertEqual(risk["position_tier"], "MAXIMUM")
        self.assertEqual(risk["requested_risk_percent"], 1)
        self.assertEqual(risk["risk_amount"], 100)
        self.assertNotIn("minimum_confidence", risk)

    def test_research_override_does_not_change_default_risk_confidence(self):
        default = RiskEngine().analyze_trade_plan(
            symbol="BTCUSDT",
            side="LONG",
            entry=100.0,
            stop_loss=99.0,
            target1=102.0,
            confidence=39,
        )
        research = RiskEngine().analyze_trade_plan(
            symbol="BTCUSDT",
            side="LONG",
            entry=100.0,
            stop_loss=99.0,
            target1=102.0,
            confidence=39,
            min_confidence=35,
        )

        self.assertEqual(default["decision"], "REJECT")
        self.assertEqual(default["reason"], "Confidence below risk threshold")
        self.assertEqual(research["decision"], "APPROVE")
        self.assertEqual(research["minimum_confidence"], 35)
        self.assertEqual(research["position_tier"], "MINIMUM")
        self.assertEqual(RiskEngine.MIN_CONFIDENCE, 40)

    def test_signal_confidence_boundary_allows_40_and_rejects_below(self):
        at_boundary = RiskEngine().analyze_trade_plan(
            symbol="BTCUSDT",
            side="LONG",
            entry=100.0,
            stop_loss=99.0,
            target1=102.0,
            confidence=40,
        )
        below_boundary = RiskEngine().analyze_trade_plan(
            symbol="BTCUSDT",
            side="LONG",
            entry=100.0,
            stop_loss=99.0,
            target1=102.0,
            confidence=39.99,
        )

        self.assertEqual(at_boundary["decision"], "APPROVE")
        self.assertEqual(below_boundary["decision"], "REJECT")
        self.assertEqual(
            below_boundary["reason"],
            "Confidence below risk threshold",
        )

    def test_minimum_confidence_tier_uses_half_percent_risk_for_long(self):
        risk = RiskEngine().analyze_trade_plan(
            symbol="BTCUSDT",
            side="LONG",
            entry=100.0,
            stop_loss=99.0,
            target1=102.0,
            confidence=59.99,
            risk_percent=1.0,
            capital=10000,
        )

        self.assertEqual(risk["decision"], "APPROVE")
        self.assertEqual(risk["position_tier"], "MINIMUM")
        self.assertEqual(risk["risk_percent"], 0.5)
        self.assertEqual(risk["requested_risk_percent"], 1.0)
        self.assertEqual(risk["risk_amount"], 50.0)
        self.assertEqual(risk["position_size"], 50.0)

    def test_minimum_confidence_tier_uses_half_percent_risk_for_short(self):
        risk = RiskEngine().analyze_trade_plan(
            symbol="BTCUSDT",
            side="SHORT",
            entry=100.0,
            stop_loss=101.0,
            target1=98.0,
            confidence=40.0,
            risk_percent=1.0,
            capital=10000,
        )

        self.assertEqual(risk["decision"], "APPROVE")
        self.assertEqual(risk["position_tier"], "MINIMUM")
        self.assertEqual(risk["risk_percent"], 0.5)
        self.assertEqual(risk["risk_amount"], 50.0)

    def test_full_confidence_tier_starts_at_60(self):
        risk = RiskEngine().analyze_trade_plan(
            symbol="BTCUSDT",
            side="LONG",
            entry=100.0,
            stop_loss=99.0,
            target1=102.0,
            confidence=60.0,
            risk_percent=1.0,
            capital=10000,
        )

        self.assertEqual(risk["decision"], "APPROVE")
        self.assertEqual(risk["position_tier"], "MAXIMUM")
        self.assertEqual(risk["risk_percent"], 1.0)
        self.assertEqual(risk["risk_amount"], 100.0)

    def test_futures_cost_gate_rejects_apparent_two_to_one_plan(self):
        risk = RiskEngine().analyze_trade_plan(
            symbol="BTCUSDT",
            side="LONG",
            entry=100.0,
            stop_loss=99.0,
            target1=102.0,
            confidence=50,
            fee_bps=4,
        )

        self.assertEqual(risk["decision"], "REJECT")
        self.assertEqual(
            risk["reason"],
            "Net risk reward below minimum threshold after futures costs",
        )
        self.assertLess(risk["risk_reward"], 2.0)

    def test_cost_adjusted_long_and_short_plans_preserve_net_two_to_one(self):
        for side in ("LONG", "SHORT"):
            plan = build_trade_plan(side, 100.0, 1.0, confidence=50)
            risk = RiskEngine().analyze_trade_plan(
                symbol="BTCUSDT",
                side=side,
                entry=plan["entry"],
                stop_loss=plan["stop_loss"],
                target1=plan["target1"],
                target2=plan["target2"],
                confidence=50,
                fee_bps=7.5,
            )

            self.assertEqual(risk["decision"], "APPROVE")
            self.assertGreaterEqual(risk["risk_reward"], 2.0)
            self.assertEqual(risk["cost_model"], "paper_futures_net_rr_v1")
            self.assertGreater(plan["gross_risk_reward"], 2.0)
            self.assertGreaterEqual(plan["target2_net_risk_reward"], 3.0)

    def test_governed_futures_plan_uses_five_percent_stop_and_point_fifteen_percent_fees(self):
        long_plan = build_trade_plan("LONG", 100.0, 1.0, confidence=50)
        short_plan = build_trade_plan("SHORT", 100.0, 1.0, confidence=50)

        self.assertEqual(long_plan["stop_loss"], 95.0)
        self.assertEqual(short_plan["stop_loss"], 105.0)
        self.assertEqual(long_plan["stop_loss_percent"], 5.0)
        self.assertEqual(long_plan["estimated_costs"]["fee_bps_per_side"], 7.5)
        self.assertEqual(
            long_plan["estimated_costs"]["estimated_round_trip_fee_percent"],
            0.15,
        )
        self.assertGreater(long_plan["target1"], 110.0)
        self.assertLess(short_plan["target1"], 90.0)
        self.assertGreaterEqual(long_plan["risk_reward"], 2.0)
        self.assertGreaterEqual(short_plan["risk_reward"], 2.0)

    def test_official_paper_plan_uses_staged_exit_policy(self):
        plan = build_trade_plan(
            "SHORT",
            63048.90,
            192.71,
            confidence=47.27,
            symbol="BTCUSDT",
            timeframe="1h",
        )

        self.assertEqual(plan["exit_policy"], "PAPER_STAGED_EXIT_V2")
        self.assertEqual(plan["stop_loss"], 63521.77)
        self.assertEqual(plan["target1"], 62103.17)
        self.assertEqual(plan["target2"], 61598.78)
        self.assertEqual(plan["target1_fraction"], 0.75)
        self.assertEqual(plan["max_hold_hours"], 48)
        self.assertLess(plan["target1_net_risk_reward"], 2.0)
        self.assertGreaterEqual(plan["target2_net_risk_reward"], 2.0)

    def test_staged_plan_uses_final_target_for_two_risk_approval(self):
        plan = build_trade_plan(
            "SHORT",
            63048.90,
            192.71,
            confidence=47.27,
            symbol="BTCUSDT",
            timeframe="1h",
        )
        risk = RiskEngine().analyze_trade_plan(
            symbol="BTCUSDT",
            side="SHORT",
            entry=plan["entry"],
            stop_loss=plan["stop_loss"],
            target1=plan["target1"],
            target2=plan["target2"],
            confidence=47.27,
            fee_bps=7.5,
            minimum_reward_target=plan["target2"],
        )

        self.assertEqual(risk["decision"], "APPROVE")
        self.assertEqual(risk["minimum_reward_target"], plan["target2"])
        self.assertGreaterEqual(risk["risk_reward"], 2.0)

    def test_staged_exit_policy_covers_every_coin_and_official_timeframe(self):
        cases = (
            ("XRPUSDT", "1h"),
            ("ETHUSDT", "2h"),
            ("SOLUSDT", "4h"),
            ("BNBUSDT", "1d"),
        )

        for symbol, timeframe in cases:
            with self.subTest(symbol=symbol, timeframe=timeframe):
                plan = build_trade_plan(
                    "LONG",
                    100.0,
                    1.0,
                    confidence=50,
                    symbol=symbol,
                    timeframe=timeframe,
                )

                self.assertEqual(plan["exit_policy"], "PAPER_STAGED_EXIT_V2")
                self.assertEqual(plan["stop_loss"], 99.25)
                self.assertEqual(plan["target1"], 101.5)
                self.assertEqual(plan["target2"], 102.3)
                self.assertEqual(plan["target1_fraction"], 0.75)
                self.assertEqual(plan["max_hold_hours"], 48)

    def test_non_entry_timeframe_keeps_default_exit_policy(self):
        plan = build_trade_plan(
            "LONG",
            100.0,
            1.0,
            confidence=50,
            symbol="BTCUSDT",
            timeframe="15m",
        )

        self.assertNotIn("exit_policy", plan)
        self.assertEqual(plan["stop_loss_percent"], 5.0)

    def test_minimum_tier_never_exceeds_configured_risk_cap(self):
        risk = RiskEngine().analyze_trade_plan(
            symbol="BTCUSDT",
            side="LONG",
            entry=100.0,
            stop_loss=99.0,
            target1=102.0,
            confidence=50.0,
            risk_percent=0.3,
            capital=10000,
        )

        self.assertEqual(risk["position_tier"], "MINIMUM")
        self.assertEqual(risk["risk_percent"], 0.3)
        self.assertEqual(risk["risk_amount"], 30.0)

    def test_risk_engine_rejects_invalid_persisted_trade_plan_direction(self):
        risk = RiskEngine().analyze_trade_plan(
            symbol="BTCUSDT",
            side="LONG",
            entry=100.0,
            stop_loss=99.0,
            target1=98.0,
            confidence=20,
        )

        self.assertEqual(risk["decision"], "REJECT")
        self.assertIn("Confidence below risk threshold", risk["reason"])

    def test_trade_plan_uses_more_precision_for_low_price_symbols(self):
        trade = build_trade_plan("LONG", 1.21456, 0.00321)

        self.assertEqual(trade["price_precision"], 5)
        self.assertEqual(trade["entry"], 1.21456)
        self.assertEqual(trade["stop_loss"], 1.15383)
        self.assertEqual(trade["target1"], 1.35158)
        self.assertGreaterEqual(trade["risk_reward"], 2.0)
        self.assertEqual(trade["cost_model"], "paper_futures_net_rr_v1")

    def test_trade_plan_keeps_two_decimals_for_large_price_symbols(self):
        trade = build_trade_plan("LONG", 65688.0, 63.2278)

        self.assertEqual(trade["price_precision"], 2)
        self.assertEqual(trade["entry"], 65688.0)
        self.assertEqual(trade["stop_loss"], 62403.6)
        self.assertEqual(trade["target1"], 73098.51)
        self.assertGreaterEqual(trade["risk_reward"], 2.0)

    def test_price_precision_bands(self):
        self.assertEqual(price_precision(0.5), 6)
        self.assertEqual(price_precision(1.2), 5)
        self.assertEqual(price_precision(74.54), 4)
        self.assertEqual(price_precision(613.39), 2)


if __name__ == "__main__":
    unittest.main()
