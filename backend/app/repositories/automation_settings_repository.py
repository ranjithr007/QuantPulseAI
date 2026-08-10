import json
from datetime import datetime

from app.database.models.automation_settings import AutomationSetting
from app.database.models.automation_settings import AutomationSettingsAudit
from app.governance.evidence_policy import r0_runtime_policy
from app.repositories._db_utils import commit_or_rollback
from app.repositories._db_utils import flush_or_rollback


DEFAULT_AUTOMATION_SETTINGS = {
    "enabled": False,
    "locked": True,
    "emergencyStop": False,
    "allowedSymbols": ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT"],
    "maxRiskPerTrade": 1.0,
    "dailyLossLimit": 4.0,
    "maxOpenTrades": 4,
    "maxLeverage": 5,
    "maxPositionSize": 25000.0,
    "minConfidence": 70.0,
    "direction": "BOTH",
    "executionMode": "PAPER",
    "liveExecutionEnabled": False,
}


def ensure_automation_settings_schema(engine):
    AutomationSetting.__table__.create(engine, checkfirst=True)
    AutomationSettingsAudit.__table__.create(engine, checkfirst=True)


def get_automation_settings(db):
    row = db.query(AutomationSetting).filter(AutomationSetting.id == 1).first()
    if row:
        return row

    defaults = normalize_automation_settings(DEFAULT_AUTOMATION_SETTINGS)
    row = AutomationSetting(id=1)
    _apply_settings(row, defaults)
    row.version = 1
    row.updated_at = datetime.utcnow()
    db.add(row)
    flush_or_rollback(db)
    db.add(
        AutomationSettingsAudit(
            setting_id=row.id,
            action="INITIALIZED",
            actor="system",
            changed_fields=json.dumps(list(defaults.keys())),
            previous_values="{}",
            new_values=json.dumps(defaults, sort_keys=True, default=str),
        )
    )
    commit_or_rollback(db)
    db.refresh(row)
    return row


def update_automation_settings(db, updates, actor="local_ui", action="SETTINGS_UPDATED"):
    row = get_automation_settings(db)
    previous = automation_settings_payload(row)
    normalized = normalize_automation_settings({**previous, **(updates or {})})
    changed = {
        key: {"from": previous.get(key), "to": value}
        for key, value in normalized.items()
        if key in DEFAULT_AUTOMATION_SETTINGS and previous.get(key) != value
    }

    if not changed:
        return previous, False

    _apply_settings(row, normalized)
    row.version = int(row.version or 0) + 1
    row.updated_at = datetime.utcnow()
    current = automation_settings_payload(row)
    db.add(
        AutomationSettingsAudit(
            setting_id=row.id,
            action=action,
            actor=str(actor or "local_ui")[:80],
            changed_fields=json.dumps(changed, sort_keys=True, default=str),
            previous_values=json.dumps(previous, sort_keys=True, default=str),
            new_values=json.dumps(current, sort_keys=True, default=str),
        )
    )
    commit_or_rollback(db)
    db.refresh(row)
    return automation_settings_payload(row), True


def set_emergency_stop(db, active, actor="local_ui"):
    updates = {
        "emergencyStop": bool(active),
        "enabled": False,
        "locked": True,
    }
    action = "EMERGENCY_STOP_ACTIVATED" if active else "EMERGENCY_STOP_CLEARED"
    return update_automation_settings(db, updates, actor=actor, action=action)


def list_automation_audit(db, limit=50):
    rows = (
        db.query(AutomationSettingsAudit)
        .order_by(AutomationSettingsAudit.created_at.desc(), AutomationSettingsAudit.id.desc())
        .limit(max(1, min(int(limit), 200)))
        .all()
    )
    return [
        {
            "id": row.id,
            "settingId": row.setting_id,
            "action": row.action,
            "actor": row.actor,
            "changedFields": _json_value(row.changed_fields, {}),
            "previousValues": _json_value(row.previous_values, {}),
            "newValues": _json_value(row.new_values, {}),
            "createdAt": row.created_at,
        }
        for row in rows
    ]


def automation_settings_payload(row):
    return {
        "enabled": bool(row.enabled),
        "locked": bool(row.locked),
        "emergencyStop": bool(row.emergency_stop),
        "allowedSymbols": _json_value(row.allowed_symbols, []),
        "maxRiskPerTrade": float(row.max_risk_per_trade),
        "dailyLossLimit": float(row.daily_loss_limit),
        "maxOpenTrades": int(row.max_open_trades),
        "maxLeverage": int(row.max_leverage),
        "maxPositionSize": float(row.max_position_size),
        "minConfidence": float(row.min_confidence),
        "direction": row.direction,
        "executionMode": "PAPER",
        "liveExecutionEnabled": False,
        "version": int(row.version or 1),
        "updatedAt": row.updated_at,
        "governance": r0_runtime_policy(),
    }


def normalize_automation_settings(value):
    allowed = value.get("allowedSymbols", DEFAULT_AUTOMATION_SETTINGS["allowedSymbols"])
    if isinstance(allowed, str):
        allowed = allowed.split(",")
    allowed_symbols = list(dict.fromkeys(str(item).strip().upper() for item in allowed if str(item).strip()))
    direction = str(value.get("direction") or "BOTH").upper()
    if direction not in {"LONG", "SHORT", "BOTH"}:
        direction = "BOTH"

    emergency_stop = bool(value.get("emergencyStop", False))
    normalized = {
        "enabled": bool(value.get("enabled", False)),
        "locked": bool(value.get("locked", True)),
        "emergencyStop": emergency_stop,
        "allowedSymbols": allowed_symbols,
        "maxRiskPerTrade": float(value.get("maxRiskPerTrade", 1.0)),
        "dailyLossLimit": float(value.get("dailyLossLimit", 4.0)),
        "maxOpenTrades": int(value.get("maxOpenTrades", 4)),
        "maxLeverage": int(value.get("maxLeverage", 5)),
        "maxPositionSize": float(value.get("maxPositionSize", 25000)),
        "minConfidence": float(value.get("minConfidence", 70)),
        "direction": direction,
        "executionMode": "PAPER",
        "liveExecutionEnabled": False,
    }
    if emergency_stop:
        normalized["enabled"] = False
        normalized["locked"] = True
    return normalized


def _apply_settings(row, value):
    row.enabled = value["enabled"]
    row.locked = value["locked"]
    row.emergency_stop = value["emergencyStop"]
    row.allowed_symbols = json.dumps(value["allowedSymbols"])
    row.max_risk_per_trade = value["maxRiskPerTrade"]
    row.daily_loss_limit = value["dailyLossLimit"]
    row.max_open_trades = value["maxOpenTrades"]
    row.max_leverage = value["maxLeverage"]
    row.max_position_size = value["maxPositionSize"]
    row.min_confidence = value["minConfidence"]
    row.direction = value["direction"]
    row.execution_mode = "PAPER"


def _json_value(value, fallback):
    try:
        return json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError):
        return fallback
