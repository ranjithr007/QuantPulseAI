from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.signals_api import router
from app.backtesting.replay_decision_chain import build_replay_decision_chain
from app.contracts.specialized import FrozenDecisionEvaluationRequest
from test_replay_golden_parity import GOLDEN_DERIVATIVES, GOLDEN_INPUT


def test_api_and_replay_use_identical_shared_frozen_decision_service():
    request = FrozenDecisionEvaluationRequest(
        symbol="DOGEUSDT",
        timeframe="1h",
        intelligence=GOLDEN_INPUT,
        derivatives=GOLDEN_DERIVATIVES,
    )

    app = FastAPI()
    app.include_router(router)
    response = TestClient(app).post(
        "/signals/evaluate-frozen",
        json=request.model_dump(),
    )
    assert response.status_code == 200
    api_result = response.json()
    replay_result = build_replay_decision_chain(
        "DOGEUSDT",
        "1h",
        GOLDEN_INPUT,
        GOLDEN_DERIVATIVES,
    )

    assert api_result == replay_result
    assert api_result["source"] == "shared_frozen_decision_evaluation"
    assert api_result["parity"] == replay_result["parity"]
