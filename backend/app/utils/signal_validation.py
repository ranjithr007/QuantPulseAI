def validate_trade_plan_direction(signal, entry_price, target_price):
    errors = []

    if signal in {"WAIT", "HOLD", "NO_SIGNAL", None}:
        return {"is_valid": True, "errors": errors}

    if entry_price is None or target_price is None:
        errors.append("entry_price and target_price are required for actionable signals")
        return {"is_valid": False, "errors": errors}

    if signal == "LONG" and target_price <= entry_price:
        errors.append("LONG target_price must be greater than entry_price")

    if signal == "SHORT" and target_price >= entry_price:
        errors.append("SHORT target_price must be less than entry_price")

    return {"is_valid": not errors, "errors": errors}
