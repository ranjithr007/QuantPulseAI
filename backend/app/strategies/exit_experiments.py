"""Frozen, paper-only exit experiments over an unchanged baseline decision."""

import copy


BASELINE_ENTRY_PROFILE = "BASELINE_ENTRY_V1"
DELAYED_TRAIL_PROFILE = "DELAYED_TRAIL_1R_V1"
TRAILING_ACTIVATION_R = 1.0


def build_exit_experiment_payload(base_payload, definition):
    """Clone baseline geometry and eligibility, opting into delayed trailing.

    Strategy identity is attached by the caller's governed decision pipeline.
    Only execution metadata is changed here: the baseline trigger, scores,
    entry evidence, plan prices, hard stop, targets and exit policy are retained.
    No plan or entry eligibility is invented when the baseline has none.
    """
    payload = copy.deepcopy(base_payload)
    experiment = {
        "entry_quality_profile": BASELINE_ENTRY_PROFILE,
        "exit_management_profile": DELAYED_TRAIL_PROFILE,
        "experiment_version": definition["version"],
        "paper_only": True,
    }
    payload["trailing_activation_r"] = TRAILING_ACTIVATION_R
    payload["execution_evidence"] = {
        **(payload.get("execution_evidence") or {}),
        **experiment,
    }
    plan = payload.get("trade_plan")
    if plan is not None:
        plan["trailing_activation_r"] = TRAILING_ACTIVATION_R
        plan["execution_evidence"] = {
            **(plan.get("execution_evidence") or {}),
            **experiment,
        }
    return payload
