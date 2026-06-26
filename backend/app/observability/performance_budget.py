from dataclasses import asdict
from dataclasses import dataclass
from statistics import mean
from time import perf_counter


@dataclass(frozen=True)
class LatencyBudget:
    p50_ms: float = 100.0
    p95_ms: float = 250.0
    p99_ms: float = 500.0


def measure_callable(operation, sample_size=5):
    samples = []
    for _ in range(max(1, int(sample_size))):
        started = perf_counter()
        operation()
        samples.append((perf_counter() - started) * 1000.0)
    return samples


def summarize_latency_samples(samples, budget=None):
    budget = budget or LatencyBudget()
    values = [float(sample) for sample in samples if sample is not None]
    if not values:
        summary = {
            "sample_count": 0,
            "min_ms": 0.0,
            "max_ms": 0.0,
            "mean_ms": 0.0,
            "p50_ms": 0.0,
            "p95_ms": 0.0,
            "p99_ms": 0.0,
            "budget": asdict(budget),
            "budget_passed": True,
        }
        return summary

    p50 = _percentile(values, 50)
    p95 = _percentile(values, 95)
    p99 = _percentile(values, 99)
    summary = {
        "sample_count": len(values),
        "min_ms": round(min(values), 4),
        "max_ms": round(max(values), 4),
        "mean_ms": round(mean(values), 4),
        "p50_ms": round(p50, 4),
        "p95_ms": round(p95, 4),
        "p99_ms": round(p99, 4),
        "budget": asdict(budget),
        "budget_passed": p50 <= budget.p50_ms and p95 <= budget.p95_ms and p99 <= budget.p99_ms,
    }
    return summary


def build_stage_latency_report(stage_operations, sample_size=5, budgets=None):
    budgets = budgets or {}
    stage_reports = {}
    for name, operation in stage_operations.items():
        stage_reports[name] = summarize_latency_samples(
            measure_callable(operation, sample_size=sample_size),
            budget=budgets.get(name),
        )

    return {
        "source": "performance_budget",
        "sample_size": max(1, int(sample_size)),
        "stages": stage_reports,
    }


def _percentile(values, percentile):
    if not values:
        return 0.0

    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])

    rank = (percentile / 100.0) * (len(ordered) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    if lower == upper:
        return float(ordered[lower])

    fraction = rank - lower
    return float(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction)
