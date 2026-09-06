from datetime import datetime, timezone
from app.utils.freshness import normalize_timestamp_to_utc


def exit_evidence_time(trade, fill_profile):
    now = datetime.now(timezone.utc)
    observed = normalize_timestamp_to_utc((fill_profile or {}).get("exit_evidence_at"))
    opened = normalize_timestamp_to_utc(trade.opened_at)
    if observed is None:
        return now.replace(tzinfo=None)
    if observed > now or (opened is not None and observed < opened):
        raise ValueError("Exit evidence timestamp is outside the trade lifetime")
    return observed.replace(tzinfo=None)
