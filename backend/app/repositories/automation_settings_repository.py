import json
from datetime import datetime

from app.database.models.automation_settings import AutomationSetting
from app.database.models.automation_settings import AutomationSettingsAudit
from app.governance.evidence_policy import MIN_ENTRY_CONFIDENCE
from app.governance.evidence_policy import r0_runtime_policy
from app.paper_trading.inr_sizing import MAXIMUM_TIER_ALLOCATION_PERCENT
from app.paper_trading.inr_sizing import MINIMUM_TIER_ALLOCATION_PERCENT
from app.paper_trading.inr_sizing import PAPER_CAPITAL_INR
from app.paper_trading.inr_sizing import PAPER_MAX_POSITION_INR
from app.repositories._db_utils import commit_or_rollback
from app.repositories._db_utils import flush_or_rollback


PAPER_DAILY_LOSS_LIMIT_CEILING_PERCENT = 4.0
PAPER_MAX_OPEN_TRADES = 4


DEFAULT_AUTOMATION_SETTINGS = {
    "enabled": False,
    "locked": True,
    "emergencyStop": False,
    "allowedSymbols": ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT"],
    "maxRiskPerTrade": 1.0,
    "dailyLossLimit": PAPER_DAILY_LOSS_LIMIT_CEILING_PERCENT,
    "maxOpenTrades": PAPER_MAX_OPEN_TRADES,
    "maxLeverage": 5,
    "maxPositionSize": PAPER_MAX_POSITION_INR,
    "minConfidence": MIN_ENTRY_CONFIDENCE,
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
        confidence_changed = float(row.min_confidence) != MIN_ENTRY_CONFIDENCE
        position_changed = float(row.max_position_size) != PAPER_MAX_POSITION_INR
        previous_daily_loss_limit = float(row.daily_loss_limit)
        governed_daily_loss_limit = min(
            previous_daily_loss_limit,
            PAPER_DAILY_LOSS_LIMIT_CEILING_PERCENT,
        )
        daily_loss_changed = previous_daily_loss_limit != governed_daily_loss_limit
        previous_max_open_trades = int(row.max_open_trades)
        governed_max_open_trades = min(
            previous_max_open_trades,
            PAPER_MAX_OPEN_TRADES,
        )
        open_trade_cap_changed = (
            previous_max_open_trades != governed_max_open_trades
        )
        if (
            confidence_changed
            or position_changed
            or daily_loss_changed
            or open_trade_cap_changed
        ):
            previous_confidence = float(row.min_confidence)
            previous_position_size = float(row.max_position_size)
            row.min_confidence = MIN_ENTRY_CONFIDENCE
            row.max_position_size = PAPER_MAX_POSITION_INR
            row.daily_loss_limit = governed_daily_loss_limit
            row.max_open_trades = governed_max_open_trades
            row.version = int(row.version or 0) + 1
            row.updated_at = datetime.utcnow()
            changed_fields = {}
            previous_values = {}
            new_values = {}
            if confidence_changed:
                changed_fields["minConfidence"] = {
                    "from": previous_confidence,
                    "to": MIN_ENTRY_CONFIDENCE,
                }
                previous_values["minConfidence"] = previous_confidence
                new_values["minConfidence"] = MIN_ENTRY_CONFIDENCE
            if position_changed:
                changed_fields["maxPositionSize"] = {
                    "from": previous_position_size,
                    "to": PAPER_MAX_POSITION_INR,
                }
                previous_values["maxPositionSize"] = previous_position_size
                new_values["maxPositionSize"] = PAPER_MAX_POSITION_INR
            if daily_loss_changed:
                changed_fields["dailyLossLimit"] = {
                    "from": previous_daily_loss_limit,
                    "to": governed_daily_loss_limit,
                }
                previous_values["dailyLossLimit"] = previous_daily_loss_limit
                new_values["dailyLossLimit"] = governed_daily_loss_limit
            if open_trade_cap_changed:
                changed_fields["maxOpenTrades"] = {
                    "from": previous_max_open_trades,
                    "to": governed_max_open_trades,
                }
                previous_values["maxOpenTrades"] = previous_max_open_trades
                new_values["maxOpenTrades"] = governed_max_open_trades
            db.add(
                AutomationSettingsAudit(
                    setting_id=row.id,
                    action="GOVERNED_PAPER_SETTINGS_REPAIRED",
                    actor="system",
                    changed_fields=json.dumps(changed_fields, sort_keys=True),
                    previous_values=json.dumps(previous_values, sort_keys=True),
                    new_values=json.dumps(new_values, sort_keys=True),
                )
            )
            commit_or_rollback(db)
            db.refresh(row)
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
        "dailyLossLimit": min(
            float(row.daily_loss_limit),
            PAPER_DAILY_LOSS_LIMIT_CEILING_PERCENT,
        ),
        "maxOpenTrades": min(
            int(row.max_open_trades),
            PAPER_MAX_OPEN_TRADES,
        ),
        "maxLeverage": int(row.max_leverage),
        "maxPositionSize": float(row.max_position_size),
        "paperCapitalInr": PAPER_CAPITAL_INR,
        "minimumAllocationPercent": MINIMUM_TIER_ALLOCATION_PERCENT,
        "maximumAllocationPercent": MAXIMUM_TIER_ALLOCATION_PERCENT,
        # The execution boundary is a governed invariant, not an operator-tuned
        # setting. This also repairs legacy rows that still contain 60 or 70.
        "minConfidence": MIN_ENTRY_CONFIDENCE,
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
        "dailyLossLimit": max(
            0.5,
            min(
                float(value.get("dailyLossLimit", 4.0)),
                PAPER_DAILY_LOSS_LIMIT_CEILING_PERCENT,
            ),
        ),
        "maxOpenTrades": max(
            1,
            min(
                int(value.get("maxOpenTrades", 4)),
                PAPER_MAX_OPEN_TRADES,
            ),
        ),
        "maxLeverage": int(value.get("maxLeverage", 5)),
        "maxPositionSize": PAPER_MAX_POSITION_INR,
        "minConfidence": MIN_ENTRY_CONFIDENCE,
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
