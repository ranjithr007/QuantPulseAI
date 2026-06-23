from dataclasses import dataclass
from importlib import import_module

DEFAULT_JOB_IDS = [
    "market",
    "feature",
    "regime",
    "orderflow",
    "smc",
    "heatmap",
    "whales",
    "whale_ai",
    "intelligence",
    "master_ai",
]


@dataclass(frozen=True)
class SchedulerJobDefinition:
    id: str
    name: str
    module: str
    function: str
    trigger: str
    seconds: int | None = None
    minutes: int | None = None
    max_instances: int = 1
    coalesce: bool = False

    def load(self):
        module = import_module(self.module)
        return getattr(module, self.function)

    def schedule_kwargs(self):
        kwargs = {
            "trigger": self.trigger,
            "id": self.id,
            "max_instances": self.max_instances,
            "replace_existing": True,
        }

        if self.seconds is not None:
            kwargs["seconds"] = self.seconds

        if self.minutes is not None:
            kwargs["minutes"] = self.minutes

        if self.coalesce:
            kwargs["coalesce"] = True

        return kwargs

    def as_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "module": self.module,
            "function": self.function,
            "trigger": self.trigger,
            "seconds": self.seconds,
            "minutes": self.minutes,
            "max_instances": self.max_instances,
            "coalesce": self.coalesce,
        }


JOB_DEFINITIONS = {
    "market": SchedulerJobDefinition(
        id="market",
        name="Market data collector",
        module="app.jobs.market_job",
        function="run_market_job",
        trigger="interval",
        seconds=30,
    ),
    "feature": SchedulerJobDefinition(
        id="feature",
        name="Feature factory",
        module="app.jobs.feature_jobs",
        function="run_feature_job",
        trigger="interval",
        minutes=1,
    ),
    "regime": SchedulerJobDefinition(
        id="regime",
        name="Regime engine",
        module="app.jobs.regime_jobs",
        function="run_regime_job",
        trigger="interval",
        minutes=1,
    ),
    "orderflow": SchedulerJobDefinition(
        id="orderflow",
        name="Orderflow engine",
        module="app.jobs.orderflow_jobs",
        function="run_orderflow_job",
        trigger="interval",
        minutes=1,
    ),
    "smc": SchedulerJobDefinition(
        id="smc",
        name="SMC engine",
        module="app.jobs.smc_job",
        function="run_smc_job",
        trigger="interval",
        minutes=1,
    ),
    "heatmap": SchedulerJobDefinition(
        id="heatmap",
        name="Liquidation heatmap engine",
        module="app.jobs.heatmap_job",
        function="run_heatmap_job",
        trigger="interval",
        seconds=40,
    ),
    "whales": SchedulerJobDefinition(
        id="whales",
        name="Whale collector",
        module="app.jobs.whale_job",
        function="run_whale_job",
        trigger="interval",
        seconds=20,
    ),
    "whale_ai": SchedulerJobDefinition(
        id="whale_ai",
        name="Whale intelligence",
        module="app.jobs.whale_intelligence_job",
        function="run_whale_intelligence_job",
        trigger="interval",
        seconds=50,
    ),
    "intelligence": SchedulerJobDefinition(
        id="intelligence",
        name="AI intelligence",
        module="app.jobs.intelligence_job",
        function="run_intelligence_job",
        trigger="interval",
        seconds=30,
    ),
    "master_ai": SchedulerJobDefinition(
        id="master_ai",
        name="Master AI",
        module="app.jobs.master_ai_job",
        function="run_master_ai_job",
        trigger="interval",
        seconds=60,
    ),
    "quality": SchedulerJobDefinition(
        id="quality",
        name="Signal quality",
        module="app.jobs.signal_quality_job",
        function="run_signal_quality_job",
        trigger="interval",
        seconds=90,
    ),
    "backtest": SchedulerJobDefinition(
        id="backtest",
        name="Backtest",
        module="app.jobs.backtest_job",
        function="run_backtest_job",
        trigger="interval",
        minutes=1,
    ),
    "ml_dataset": SchedulerJobDefinition(
        id="ml_dataset",
        name="ML dataset",
        module="app.jobs.ml_dataset_job",
        function="run_ml_dataset_job",
        trigger="interval",
        minutes=15,
        coalesce=True,
    ),
    "ml_label": SchedulerJobDefinition(
        id="ml_label",
        name="ML labels",
        module="app.jobs.ml_label_job",
        function="run_ml_label_job",
        trigger="interval",
        minutes=5,
    ),
    "fusion": SchedulerJobDefinition(
        id="fusion",
        name="Fusion AI",
        module="app.jobs.fusion_job",
        function="run_fusion_job",
        trigger="interval",
        seconds=60,
    ),
    "trade_plan": SchedulerJobDefinition(
        id="trade_plan",
        name="Trade planner",
        module="app.jobs.trade_plan_job",
        function="run_trade_plan_job",
        trigger="interval",
        seconds=120,
    ),
    "watchlist_persist": SchedulerJobDefinition(
        id="watchlist_persist",
        name="Watchlist READY persistence",
        module="app.jobs.watchlist_persist_job",
        function="run_watchlist_persist_job",
        trigger="interval",
        seconds=120,
    ),
    "paper_trade_monitor": SchedulerJobDefinition(
        id="paper_trade_monitor",
        name="Paper trade monitor",
        module="app.jobs.paper_trade_monitor_job",
        function="run_paper_trade_monitor_job",
        trigger="interval",
        seconds=60,
    ),
    "paper_trade_execute": SchedulerJobDefinition(
        id="paper_trade_execute",
        name="Paper trade executor",
        module="app.jobs.paper_trade_execute_job",
        function="run_paper_trade_execute_job",
        trigger="interval",
        seconds=60,
    ),
    "pipeline_cycle": SchedulerJobDefinition(
        id="pipeline_cycle",
        name="Pipeline cycle",
        module="app.jobs.pipeline_cycle_job",
        function="run_pipeline_cycle_job",
        trigger="interval",
        seconds=120,
    ),
    "memory": SchedulerJobDefinition(
        id="memory",
        name="AI memory",
        module="app.jobs.memory_job",
        function="run_memory_job",
        trigger="interval",
        minutes=5,
    ),
    "risk": SchedulerJobDefinition(
        id="risk",
        name="Risk engine",
        module="app.jobs.risk_job",
        function="run_risk_job",
        trigger="interval",
        minutes=1,
        max_instances=2,
    ),
}


def all_job_definitions():
    return list(JOB_DEFINITIONS.values())


def get_job_definition(job_id):
    return JOB_DEFINITIONS.get(_normalize_job_id(job_id))


def resolve_job_ids(job_ids):
    if not job_ids:
        return DEFAULT_JOB_IDS

    if job_ids == ["all"]:
        return list(JOB_DEFINITIONS.keys())

    return [_normalize_job_id(job_id) for job_id in job_ids]


def _normalize_job_id(job_id):
    return job_id.replace("-", "_")
