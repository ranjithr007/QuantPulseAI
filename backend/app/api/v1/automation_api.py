from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.database.sqlserver import SessionLocal
from app.repositories.automation_settings_repository import automation_settings_payload
from app.repositories.automation_settings_repository import get_automation_settings
from app.repositories.automation_settings_repository import list_automation_audit
from app.repositories.automation_settings_repository import set_emergency_stop
from app.repositories.automation_settings_repository import update_automation_settings


router = APIRouter(prefix="/automation", tags=["Automation"])


class AutomationSettingsUpdate(BaseModel):
    enabled: bool
    locked: bool
    emergencyStop: bool
    allowedSymbols: list[str]
    maxRiskPerTrade: float = Field(ge=0.1, le=5)
    dailyLossLimit: float = Field(ge=0.5, le=15)
    maxOpenTrades: int = Field(ge=1, le=20)
    maxLeverage: int = Field(ge=1, le=25)
    maxPositionSize: float = Field(ge=100, le=1_000_000)
    minConfidence: float = Field(ge=0, le=100)
    direction: str = Field(pattern="^(LONG|SHORT|BOTH)$")


class EmergencyStopUpdate(BaseModel):
    active: bool


@router.get("/settings")
def read_automation_settings():
    db = SessionLocal()
    try:
        return {
            "source": "automation_settings",
            "settings": automation_settings_payload(get_automation_settings(db)),
        }
    finally:
        db.close()


@router.put("/settings")
def write_automation_settings(
    payload: AutomationSettingsUpdate,
    actor: str = Query(default="local_ui", max_length=80),
):
    db = SessionLocal()
    try:
        settings, changed = update_automation_settings(db, payload.model_dump(), actor=actor)
        return {"source": "automation_settings", "changed": changed, "settings": settings}
    finally:
        db.close()


@router.post("/emergency-stop")
def write_emergency_stop(
    payload: EmergencyStopUpdate,
    actor: str = Query(default="local_ui", max_length=80),
):
    db = SessionLocal()
    try:
        settings, changed = set_emergency_stop(db, payload.active, actor=actor)
        return {"source": "automation_settings", "changed": changed, "settings": settings}
    finally:
        db.close()


@router.get("/audit")
def read_automation_audit(limit: int = Query(default=50, ge=1, le=200)):
    db = SessionLocal()
    try:
        records = list_automation_audit(db, limit=limit)
        return {"source": "automation_settings_audit", "count": len(records), "records": records}
    finally:
        db.close()
