from gcc_evolution.enterprise.knn_evolution import (
    KNNEvolver,
    REGIME_BEAR,
    REGIME_BULL,
    REGIME_CRISIS,
    REGIME_HIGH_VOL,
    REGIME_SIDE,
    adaptive_knn_search,
    knn_feature_importance,
)


def test_phase1_dynamic_forgetting_accelerates_in_high_volatility():
    engine = KNNEvolver(base_forgetting=0.02)

    low = engine.dynamic_forgetting_factor(
        regime=REGIME_BULL,
        volatility=1.0,
        baseline_volatility=1.0,
    )
    high = engine.dynamic_forgetting_factor(
        regime=REGIME_HIGH_VOL,
        volatility=2.2,
        baseline_volatility=1.0,
    )
    crisis = engine.dynamic_forgetting_factor(
        regime=REGIME_CRISIS,
        volatility=2.8,
        baseline_volatility=1.0,
    )

    assert low < high < crisis


def test_phase1_regime_expands_from_three_to_five_buckets():
    assert KNNEvolver.infer_regime(volatility=1.0, baseline_volatility=1.0, trend=0.3) == REGIME_BULL
    assert KNNEvolver.infer_regime(volatility=1.0, baseline_volatility=1.0, trend=-0.3) == REGIME_BEAR
    assert KNNEvolver.infer_regime(volatility=1.0, baseline_volatility=1.0, trend=0.02) == REGIME_SIDE
    assert KNNEvolver.infer_regime(volatility=1.6, baseline_volatility=1.0, trend=0.0) == REGIME_HIGH_VOL
    assert KNNEvolver.infer_regime(volatility=2.1, baseline_volatility=1.0, trend=-0.1) == REGIME_CRISIS


def test_phase2_tta_normalization_tracks_recent_window():
    engine = KNNEvolver(recent_window=3)
    engine.fit(
        [
            {"features": [1.0, 1.0], "label": "old", "timestamp": 1, "volatility": 1.0, "baseline_volatility": 1.0, "trend": 0.0},
            {"features": [2.0, 2.0], "label": "old", "timestamp": 2, "volatility": 1.0, "baseline_volatility": 1.0, "trend": 0.0},
            {"features": [100.0, 100.0], "label": "new", "timestamp": 3, "volatility": 1.0, "baseline_volatility": 1.0, "trend": 0.0},
            {"features": [101.0, 101.0], "label": "new", "timestamp": 4, "volatility": 1.0, "baseline_volatility": 1.0, "trend": 0.0},
            {"features": [102.0, 102.0], "label": "new", "timestamp": 5, "volatility": 1.0, "baseline_volatility": 1.0, "trend": 0.0},
        ]
    )

    snapshot = engine.snapshot()
    assert snapshot["tta_mean"][0] > 100.0
    assert snapshot["tta_std"][0] > 0.0


def test_phase2_drift_downweights_old_samples_and_cleans_after_repeat_shift():
    engine = KNNEvolver(recent_window=6, cleanup_age=6)
    for ts in range(1, 7):
        engine.add_sample(
            [0.0, 0.0],
            label="old",
            timestamp=ts,
            volatility=1.0,
            baseline_volatility=1.0,
            trend=0.2,
        )
    for ts in range(7, 13):
        engine.add_sample(
            [10.0, 10.0],
            label="new",
            timestamp=ts,
            volatility=2.0,
            baseline_volatility=1.0,
            trend=0.0,
        )

    first = engine.detect_drift()
    second = engine.detect_drift()
    assert first["drift"] is True
    assert second["drift"] is True
    assert second["cleaned"] > 0

    result = engine.predict(
        [10.2, 10.2],
        timestamp=13,
        volatility=2.0,
        baseline_volatility=1.0,
        trend=0.0,
    )
    assert result["label"] == "new"
    assert result["drift"]["epoch"] >= 2


def test_adaptive_knn_search_and_feature_importance_are_usable():
    history = [
        {"features": [0.0, 10.0], "label": "sell", "timestamp": 1, "volatility": 1.0, "baseline_volatility": 1.0, "trend": -0.2},
        {"features": [1.0, 11.0], "label": "sell", "timestamp": 2, "volatility": 1.0, "baseline_volatility": 1.0, "trend": -0.2},
        {"features": [9.0, 1.0], "label": "buy", "timestamp": 3, "volatility": 1.0, "baseline_volatility": 1.0, "trend": 0.2},
        {"features": [10.0, 0.0], "label": "buy", "timestamp": 4, "volatility": 1.0, "baseline_volatility": 1.0, "trend": 0.2},
    ]

    neighbors = adaptive_knn_search(
        history,
        [9.5, 0.5],
        timestamp=5,
        volatility=1.0,
        baseline_volatility=1.0,
        trend=0.2,
        k=2,
    )
    assert neighbors
    assert neighbors[0].label == "buy"

    importance = knn_feature_importance(history)
    assert set(importance.keys()) == {0, 1}
    assert abs(sum(importance.values()) - 1.0) < 1e-6
