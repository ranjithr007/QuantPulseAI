from scripts.analyze_r5_holdout_clusters import _confidence_band
from scripts.analyze_r5_holdout_clusters import _summarize


def test_summarize_calculates_cluster_edge_metrics():
    trades = [
        {"pnl": 20, "pnl_percent": 2},
        {"pnl": -10, "pnl_percent": -1},
        {"pnl": -5, "pnl_percent": -0.5},
    ]

    result = _summarize(trades)

    assert result["trades"] == 3
    assert result["win_rate"] == 33.33
    assert result["profit_factor"] == 1.3333
    assert result["expectancy_percent"] == 0.1667


def test_confidence_bands_have_stable_boundaries():
    assert _confidence_band(59.99) == "LT_60"
    assert _confidence_band(60) == "60_TO_64_99"
    assert _confidence_band(65) == "65_TO_69_99"
    assert _confidence_band(70) == "GE_70"
