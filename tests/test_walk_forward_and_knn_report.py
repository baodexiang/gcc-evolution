from gcc_evolution.enterprise.knn_evolution import (
    build_accuracy_matrix,
    build_daily_accuracy_report,
    build_heatmap_payload,
)
from gcc_evolution.enterprise.walk_forward import (
    WalkForwardAnalyzer,
    walk_forward_backtest,
)


def _sample_records():
    records = []
    for ts in range(1, 81):
        if ts <= 40:
            feat = [0.0, 0.0]
            label = "sell"
            trend = -0.2
            vol = 1.0
        else:
            feat = [10.0, 10.0]
            label = "buy"
            trend = 0.2
            vol = 1.8
        records.append(
            {
                "features": feat,
                "label": label,
                "timestamp": ts,
                "volatility": vol,
                "baseline_volatility": 1.0,
                "trend": trend,
            }
        )
    return records


def test_walk_forward_backtest_returns_phase_gate_and_delta():
    report = walk_forward_backtest(_sample_records(), window_size=40)

    assert report["mode"] == "walk_forward"
    assert "phase_gate" in report
    assert report["phase_gate"]["metrics"]["total_windows"] >= 1
    assert "delta_accuracy" in report


def test_walk_forward_analyzer_exposes_window_level_results():
    analyzer = WalkForwardAnalyzer(window_size=40)
    report = analyzer.evaluate(_sample_records())

    assert report["windows"]
    first = report["windows"][0]
    assert "old_accuracy" in first
    assert "new_accuracy" in first
    assert "delta_accuracy" in first


def test_knn_accuracy_matrix_and_heatmap_reporting():
    rows = [
        {"plugin": "vision", "symbol": "BTCUSDC", "correct": True},
        {"plugin": "vision", "symbol": "BTCUSDC", "correct": False},
        {"plugin": "filter", "symbol": "BTCUSDC", "correct": True},
        {"plugin": "filter", "symbol": "ETHUSDC", "correct": True},
    ]

    matrix = build_accuracy_matrix(rows)
    assert matrix["vision"]["BTCUSDC"]["accuracy"] == 0.5
    assert matrix["filter"]["ETHUSDC"]["accuracy"] == 1.0

    heatmap = build_heatmap_payload(rows)
    assert heatmap["plugins"] == ["filter", "vision"]
    assert heatmap["symbols"] == ["BTCUSDC", "ETHUSDC"]
    assert len(heatmap["values"]) == 2

    report = build_daily_accuracy_report(rows, top_k=2)
    assert report["summary"]["pairs"] == 3
    assert report["top"]
    assert report["bottom"]
