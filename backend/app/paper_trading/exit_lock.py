from sqlalchemy import inspect
from app.utils.freshness import normalize_timestamp_to_utc


def lock_open_trade(db, trade):
    """Reload under a row lock before deciding; reconcile and fast exits may race."""
    state = inspect(trade, raiseerr=False)
    if state is None or not state.identity:
        return trade  # Non-persisted objects used by deterministic unit tests.
    model = type(trade)
    return (
        db.query(model)
        .filter(model.id == state.identity[0], model.status == "OPEN")
        .populate_existing()
        .with_for_update(nowait=True)
        .first()
    )


def advance_exit_checkpoint(db, trade, evaluated_at):
    current = lock_open_trade(db, trade)
    if current is None:
        return trade
    previous = normalize_timestamp_to_utc(getattr(current, "last_exit_evaluated_at", None))
    observed = normalize_timestamp_to_utc(evaluated_at)
    if observed is not None and (previous is None or observed > previous):
        current.last_exit_evaluated_at = evaluated_at
    return current
