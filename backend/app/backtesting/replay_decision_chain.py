"""Replay adapter for the shared frozen-context decision service."""

from app.services.decision_evaluation_service import evaluate_frozen_decision


def build_replay_decision_chain(
    symbol,
    timeframe,
    intelligence,
    derivatives,
    *,
    capital=10_000,
    risk_percent=1,
):
    return evaluate_frozen_decision(
        symbol,
        timeframe,
        intelligence,
        derivatives,
        capital=capital,
        risk_percent=risk_percent,
    )
