from fastapi import APIRouter

router = APIRouter(prefix="/fusion-ai-v2", tags=["fusion AI V2"])

@router.get("/fusion/{symbol}")
def fusion(symbol: str):

    result = service.analyze(symbol)

    return result