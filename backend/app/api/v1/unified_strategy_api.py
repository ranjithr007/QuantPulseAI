"""Safe configuration validation for the Unified Composite strategy."""

from fastapi import APIRouter

from app.contracts.unified_strategy import UnifiedCompositeProfile


router = APIRouter(prefix="/unified-strategy", tags=["Unified Strategy"])


@router.post("/validate")
def validate_profile(profile: UnifiedCompositeProfile):
    """Validate and normalize a per-coin profile without executing anything."""

    return {
        "status": "VALID",
        "execution": "PAPER_ONLY",
        "orders_created": 0,
        "profile": profile.model_dump(by_alias=True),
    }
