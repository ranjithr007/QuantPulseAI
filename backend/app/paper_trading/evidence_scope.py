from app.governance.evidence_policy import OFFICIAL_ENTRY_TIMEFRAMES


# Symbols beginning with QA are reserved for synthetic validation records. They
# may remain in a shared database for auditability, but they must never affect
# the production-visible paper ledger, wallet, risk limits, or executor state.
QA_PAPER_SYMBOL_PREFIX = "QA"
QUARANTINED_LEDGER_SCOPES = frozenset({"QA", "TEST", "SYNTHETIC"})


def is_quarantined_paper_symbol(symbol):
    return str(symbol or "").strip().upper().startswith(QA_PAPER_SYMBOL_PREFIX)


def is_quarantined_paper_trade(record):
    scope = str(_value(record, "ledger_scope") or "").strip().upper()
    return (
        scope in QUARANTINED_LEDGER_SCOPES
        or is_quarantined_paper_symbol(_value(record, "symbol"))
    )


def production_paper_trade_records(records, *, require_official_timeframe=False):
    scoped = [
        record
        for record in (records or [])
        if not is_quarantined_paper_trade(record)
    ]
    if not require_official_timeframe:
        return scoped
    return [
        record
        for record in scoped
        if str(_value(record, "entry_timeframe") or "").strip().lower()
        in OFFICIAL_ENTRY_TIMEFRAMES
    ]


def _value(record, name):
    if isinstance(record, dict):
        return record.get(name)
    return getattr(record, name, None)
