import unittest
from datetime import datetime
from types import SimpleNamespace

from app.api.v1.regime_api import _build_transition_history
from app.api.v1.regime_api import _count_transition_values
from app.api.v1.regime_api import _recent_transitions
from app.api.v1.regime_api import _regime_payload
from app.api.v1.regime_api import _count_values


class Phase1BRegimeTransitionsApiTests(unittest.TestCase):
    def test_count_helpers_work_for_regime_summary(self):
        items = [
            {"Regime": "TRENDING_BEAR", "audit": {"transition_decision": "HELD_PREVIOUS"}},
            {"Regime": "TRENDING_BEAR", "audit": {"transition_decision": "SAME"}},
            {"Regime": "RANGE_DISTRIBUTION", "audit": {"transition_decision": "CONFIRMED_TRANSITION"}},
        ]

        self.assertEqual(_count_values(items, "Regime"), {
            "TRENDING_BEAR": 2,
            "RANGE_DISTRIBUTION": 1,
        })
        self.assertEqual(_count_transition_values(items), {
            "HELD_PREVIOUS": 1,
            "SAME": 1,
            "CONFIRMED_TRANSITION": 1,
        })

    def test_transition_history_marks_previous_and_current(self):
        items = [
            {
                "CreatedAt": "2026-06-17T08:00:00",
                "Regime": "TRENDING_BEAR",
                "Confidence": 85,
                "audit": {
                    "candidate_regime": "RANGE_DISTRIBUTION",
                    "selected_regime": "TRENDING_BEAR",
                    "previous_regime": "TRENDING_BEAR",
                    "transition_decision": "HELD_PREVIOUS",
                    "transition_confidence": 0,
                    "dwell_cycles": 2,
                },
            },
            {
                "CreatedAt": "2026-06-17T07:55:00",
                "Regime": "TRENDING_BEAR",
                "Confidence": 85,
                "audit": {
                    "candidate_regime": "TRENDING_BEAR",
                    "selected_regime": "TRENDING_BEAR",
                    "previous_regime": "TRENDING_BEAR",
                    "transition_decision": "SAME",
                    "transition_confidence": 85,
                    "dwell_cycles": 1,
                },
            },
        ]

        transitions = _build_transition_history(items)
        self.assertEqual(len(transitions), 2)
        self.assertTrue(transitions[0]["held_previous"])
        self.assertEqual(transitions[0]["previous_created_at"], "2026-06-17T07:55:00")
        self.assertFalse(transitions[1]["held_previous"])

    def test_regime_payload_adds_audit_from_reason_json(self):
        record = _fake_regime_record(
            created_at=datetime(2026, 6, 17, 8, 0, 0),
            regime="TRENDING_BEAR",
            confidence=85,
            reason='{"transition_decision":"HELD_PREVIOUS"}',
        )

        payload = _regime_payload(record, 900)
        self.assertEqual(payload["audit"]["transition_decision"], "HELD_PREVIOUS")
        self.assertEqual(payload["Regime"], "TRENDING_BEAR")

    def test_recent_transitions_extracts_compact_view(self):
        items = [
            {
                "CreatedAt": "2026-06-17T08:00:00",
                "Regime": "TRENDING_BEAR",
                "Confidence": 85,
                "audit": {
                    "transition_decision": "HELD_PREVIOUS",
                    "selected_regime": "TRENDING_BEAR",
                    "candidate_regime": "RANGE_DISTRIBUTION",
                    "dwell_cycles": 2,
                },
            }
        ]

        compact = _recent_transitions(items)
        self.assertEqual(compact[0]["transition_decision"], "HELD_PREVIOUS")
        self.assertEqual(compact[0]["dwell_cycles"], 2)


def _fake_regime_record(created_at, regime, confidence, reason):
    class Column:
        def __init__(self, name):
            self.name = name

    class Table:
        columns = [
            Column("Id"),
            Column("Symbol"),
            Column("Timeframe"),
            Column("Regime"),
            Column("Confidence"),
            Column("RecommendedStrategy"),
            Column("Reason"),
            Column("CreatedAt"),
        ]

    record = SimpleNamespace(
        Id=1,
        Symbol="BTCUSDT",
        Timeframe="5m",
        Regime=regime,
        Confidence=confidence,
        RecommendedStrategy="SHORT_RALLY",
        Reason=reason,
        CreatedAt=created_at,
        __table__=Table,
    )
    return record


if __name__ == "__main__":
    unittest.main()
