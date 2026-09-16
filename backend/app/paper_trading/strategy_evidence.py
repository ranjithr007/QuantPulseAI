from collections import defaultdict

from app.database.models.paper_trade import PaperTrade
from app.database.models.strategy_shadow_trade import StrategyShadowTrade
from app.governance.evidence_policy import OFFICIAL_ENTRY_TIMEFRAMES
from app.paper_trading.evidence_scope import production_paper_trade_records
from app.paper_trading.operational_exit_quality import is_operationally_contaminated_exit


OFFICIAL_STRATEGY_EVIDENCE_POLICY = "PRODUCTION_EXPECTANCY_GATE_V2"
OFFICIAL_STRATEGY_MIN_CLOSED_TRADES = 30
OFFICIAL_STRATEGY_MIN_EXPECTANCY_PERCENT = 0.0
OFFICIAL_STRATEGY_MIN_PROFIT_FACTOR = 1.0


def load_official_strategy_evidence(db, strategy_ids=None):
    """Load only the narrow columns required by the execution evidence gate."""

    normalized_ids = [
        str(strategy_id or "").strip().upper()
        for strategy_id in (strategy_ids or [])
        if str(strategy_id or "").strip()
    ]

    def evidence_rows(model):
        query = db.query(
            model.id.label("id"),
            model.trade_plan_id.label("trade_plan_id"),
            model.strategy_id.label("strategy_id"),
            model.strategy_version.label("strategy_version"),
            model.status.label("status"),
            model.pnl_percent.label("pnl_percent"),
            model.symbol.label("symbol"),
            model.entry_timeframe.label("entry_timeframe"),
            model.exit_reason.label("exit_reason"),
            model.max_hold_hours.label("max_hold_hours"),
            model.opened_at.label("opened_at"),
            model.closed_at.label("closed_at"),
            model.exit_evidence_json.label("exit_evidence_json"),
        ).filter(model.status == "CLOSED")
        if normalized_ids:
            query = query.filter(model.strategy_id.in_(normalized_ids))
        # Scope timeframe and QA records in the shared policy helper below.
        # Keeping this predicate indexable also avoids SQL Server scans caused
        # by applying LOWER/UPPER functions to every ledger row.
        return [dict(row._mapping) for row in query.all()]

    return build_official_strategy_evidence(
        evidence_rows(PaperTrade),
        evidence_rows(StrategyShadowTrade),
    )


def build_official_strategy_evidence(trades, research_trades=None):
    """Build promotion evidence for each exact strategy revision.

    Strategy revisions are deliberately isolated. A redesigned revision must
    earn its own production-paper evidence instead of inheriting either the
    losses or the approval of an older revision.
    """

    grouped = defaultdict(list)
    excluded_by_key = defaultdict(list)
    observed_keys = []
    observed_key_set = set()
    seen_trade_plans = set()
    sources = (
        ("OFFICIAL_PAPER", trades),
        ("STRATEGY_PAPER", research_trades),
    )
    for source, source_records in sources:
        records = production_paper_trade_records(
            source_records,
            require_official_timeframe=True,
        )
        for sequence, trade in enumerate(records):
            if str(_value(trade, "status") or "").upper() != "CLOSED":
                continue
            pnl = _finite_float(_value(trade, "pnl_percent"))
            if pnl is None:
                continue
            key = _strategy_key(
                _value(trade, "strategy_id"),
                _value(trade, "strategy_version"),
            )
            trade_plan_id = _value(trade, "trade_plan_id")
            observation_key = (
                key,
                "PLAN",
                str(trade_plan_id),
            ) if trade_plan_id not in (None, "") else (
                key,
                source,
                str(_value(trade, "id") or sequence),
            )
            if observation_key in seen_trade_plans:
                continue
            seen_trade_plans.add(observation_key)
            if key not in observed_key_set:
                observed_key_set.add(key)
                observed_keys.append(key)
            if is_operationally_contaminated_exit(trade):
                excluded_by_key[key].append(source)
                continue
            grouped[key].append((pnl, source))

    return {
        key: _evidence_snapshot(
            key[0],
            key[1],
            grouped.get(key, []),
            excluded_by_key.get(key, []),
        )
        for key in observed_keys
    }


def strategy_evidence_for_plan(evidence_by_key, plan):
    plan = plan or {}
    key = _strategy_key(
        plan.get("strategy_id"),
        plan.get("strategy_version"),
    )
    return (evidence_by_key or {}).get(
        key,
        _evidence_snapshot(key[0], key[1], []),
    )


def strategy_evidence_blockers(evidence):
    evidence = evidence or {}
    if evidence.get("official_execution_allowed") is True:
        return []

    strategy_revision = evidence.get("strategy_revision") or "UNKNOWN"
    closed_trades = int(evidence.get("closed_trades") or 0)
    minimum = int(
        evidence.get("minimum_closed_trades")
        or OFFICIAL_STRATEGY_MIN_CLOSED_TRADES
    )
    if evidence.get("status") == "INSUFFICIENT_EVIDENCE":
        return [
            f"{strategy_revision} has {closed_trades}/{minimum} clean measured closed "
            "official trades; official entry remains research-only until the "
            "minimum evidence sample is complete"
        ]

    expectancy = evidence.get("expectancy_percent")
    profit_factor = evidence.get("profit_factor")
    return [
        f"{strategy_revision} failed the production expectancy gate "
        f"(expectancy {expectancy}%, profit factor {profit_factor}); official "
        "entry remains quarantined while research evidence continues"
    ]


def _evidence_snapshot(
    strategy_id, strategy_version, observations, excluded_sources=None
):
    excluded_sources = list(excluded_sources or [])
    returns = [value for value, _source in observations]
    source_counts = {
        source: sum(1 for _value, item_source in observations if item_source == source)
        for source in ("OFFICIAL_PAPER", "STRATEGY_PAPER")
    }
    positive = [value for value in returns if value > 0]
    negative = [value for value in returns if value < 0]
    gross_profit = sum(positive)
    gross_loss = abs(sum(negative))
    profit_factor = round(gross_profit / gross_loss, 4) if gross_loss else None
    closed_trades = len(returns)
    expectancy = sum(returns) / closed_trades if closed_trades else 0.0
    sufficient = closed_trades >= OFFICIAL_STRATEGY_MIN_CLOSED_TRADES
    profitable = (
        expectancy > OFFICIAL_STRATEGY_MIN_EXPECTANCY_PERCENT
        and sum(returns) > 0
        and (
            profit_factor is not None
            and profit_factor >= OFFICIAL_STRATEGY_MIN_PROFIT_FACTOR
            or profit_factor is None
            and gross_profit > 0
        )
    )
    allowed = sufficient and profitable
    if not sufficient:
        status = "INSUFFICIENT_EVIDENCE"
    elif allowed:
        status = "PROMOTABLE"
    else:
        status = "FAILED_EXPECTANCY"

    revision = strategy_id
    if strategy_version:
        revision = f"{strategy_id}@{strategy_version}"
    return {
        "policy": OFFICIAL_STRATEGY_EVIDENCE_POLICY,
        "strategy_id": strategy_id or None,
        "strategy_version": strategy_version or None,
        "strategy_revision": revision or "UNKNOWN",
        "status": status,
        "official_execution_allowed": allowed,
        "closed_trades": closed_trades,
        "total_observed_closed_trades": closed_trades + len(excluded_sources),
        "excluded_operationally_contaminated_trades": len(excluded_sources),
        "evidence_scope": "CLEAN_OPERATIONAL_EVIDENCE_ONLY",
        "official_paper_closed_trades": source_counts["OFFICIAL_PAPER"],
        "strategy_paper_closed_trades": source_counts["STRATEGY_PAPER"],
        "excluded_official_paper_trades": excluded_sources.count("OFFICIAL_PAPER"),
        "excluded_strategy_paper_trades": excluded_sources.count("STRATEGY_PAPER"),
        "evidence_source": (
            "OFFICIAL_AND_STRATEGY_PAPER"
            if all(source_counts.values())
            else "OFFICIAL_PAPER"
            if source_counts["OFFICIAL_PAPER"]
            else "STRATEGY_PAPER"
            if source_counts["STRATEGY_PAPER"]
            else "NONE"
        ),
        "minimum_closed_trades": OFFICIAL_STRATEGY_MIN_CLOSED_TRADES,
        "wins": len(positive),
        "losses": len(negative),
        "breakeven": closed_trades - len(positive) - len(negative),
        "net_pnl_percent": round(sum(returns), 4),
        "expectancy_percent": round(expectancy, 4),
        "minimum_expectancy_percent": OFFICIAL_STRATEGY_MIN_EXPECTANCY_PERCENT,
        "profit_factor": profit_factor,
        "minimum_profit_factor": OFFICIAL_STRATEGY_MIN_PROFIT_FACTOR,
        "entry_timeframes": sorted(OFFICIAL_ENTRY_TIMEFRAMES),
    }


def _strategy_key(strategy_id, strategy_version):
    return (
        str(strategy_id or "").strip().upper(),
        str(strategy_version or "").strip(),
    )


def _value(record, name):
    if isinstance(record, dict):
        return record.get(name)
    return getattr(record, name, None)


def _finite_float(value):
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric != numeric or numeric in (float("inf"), float("-inf")):
        return None
    return numeric
