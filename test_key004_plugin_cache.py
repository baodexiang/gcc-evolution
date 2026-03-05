from __future__ import annotations

from modules.key004_plugin_cache import (
    CacheFallbackManager,
    CacheQueryEngine,
    CacheStorageBackend,
    DeltaEvalRequest,
    FeatureVector,
    KEY004DeltaEvaluator,
    compute_kline_signature,
    compute_mfe_mae,
)


def _fv(ts: int, sig: dict[str, float], strength: float = 0.5) -> FeatureVector:
    return FeatureVector(
        symbol="TSLA",
        timeframe="4h",
        plugin_name="double_pattern",
        timestamp=ts,
        features_dict={"strength": strength, "state": "ok"},
        ohlcv={"open": 100.0, "high": 105.0, "low": 99.0, "close": 103.0, "volume": 1000.0},
        kline_signature=sig,
        version="v1.0",
        regime_label="trend",
    )


def test_cache_backend_write_query_roundtrip(tmp_path):
    backend = CacheStorageBackend(db_path=str(tmp_path / "k004.db"))
    sig = {
        "open_close_ratio": 0.03,
        "high_low_ratio": 0.06,
        "body_ratio": 0.5,
        "volume_ma_ratio": 1.0,
        "atr_ratio": 0.02,
    }
    fv = _fv(1700000000, sig, strength=0.77)

    assert backend.write_feature_vector(fv) is True
    out = backend.query_feature_vector("TSLA", "4h", "double_pattern", 1700000000)
    assert out is not None
    assert out.features_dict["strength"] == 0.77
    assert out.kline_signature["body_ratio"] == 0.5


def test_query_similar_returns_descending_order(tmp_path):
    backend = CacheStorageBackend(db_path=str(tmp_path / "k004.db"))
    engine = CacheQueryEngine(backend)

    bars = [
        {"open": 100.0, "high": 104.0, "low": 99.0, "close": 102.0, "volume": 1000.0}
        for _ in range(30)
    ]
    current = {"open": 100.0, "high": 108.0, "low": 98.0, "close": 106.0, "volume": 1300.0}
    cur_sig = compute_kline_signature(current, bars).to_dict()

    close_sig = dict(cur_sig)
    medium_sig = dict(cur_sig)
    medium_sig["body_ratio"] = max(0.0, cur_sig["body_ratio"] * 0.7)
    far_sig = {
        "open_close_ratio": -abs(cur_sig["open_close_ratio"]),
        "high_low_ratio": max(cur_sig["high_low_ratio"] * 0.2, 0.0001),
        "body_ratio": 0.05,
        "volume_ma_ratio": 0.1,
        "atr_ratio": cur_sig["atr_ratio"] * 4.0,
    }

    assert backend.write_feature_vector(_fv(1, close_sig, 0.9))
    assert backend.write_feature_vector(_fv(2, medium_sig, 0.6))
    assert backend.write_feature_vector(_fv(3, far_sig, 0.2))

    out = engine.query_similar("TSLA", "4h", "double_pattern", current_ohlcv=current, historical_data=bars, k=3)
    assert len(out) == 3
    assert out[0][0].timestamp == 1
    assert out[0][1] >= out[1][1] >= out[2][1]


def test_compute_mfe_mae_buy_and_sell_paths():
    bars = [
        {"high": 105.0, "low": 99.0},
        {"high": 103.0, "low": 97.0},
        {"high": 106.0, "low": 98.0},
    ]

    buy = compute_mfe_mae(100.0, "BUY", bars, lookback_bars=3)
    assert round(buy.mfe_pct, 2) == 6.0
    assert round(buy.mae_pct, 2) == 3.0

    sell = compute_mfe_mae(100.0, "SELL", bars, lookback_bars=3)
    assert round(sell.mfe_pct, 2) == 3.0
    assert round(sell.mae_pct, 2) == 6.0


def test_delta_evaluator_approval_and_rejection_paths():
    evaluator = KEY004DeltaEvaluator(
        approval_threshold_icir=0.10,
        approval_threshold_win_rate=0.0,
        min_sample_n=50,
        min_regime_stability=0.7,
    )

    approved = evaluator.run_delta_eval(
        DeltaEvalRequest(
            feature_name="feat_a",
            baseline_version="v1",
            candidate_version="v2",
            baseline_metrics={"icir": 0.20, "win_rate": 0.50, "sample_n": 60},
            candidate_metrics={"icir": 0.40, "win_rate": 0.55, "sample_n": 80},
            regime_split={"trend": {"icir": 0.38}, "range": {"icir": 0.35}},
        )
    )
    assert approved.status == "approved"

    rejected = evaluator.run_delta_eval(
        DeltaEvalRequest(
            feature_name="feat_a",
            baseline_version="v1",
            candidate_version="v3",
            baseline_metrics={"icir": 0.30, "win_rate": 0.55, "sample_n": 60},
            candidate_metrics={"icir": 0.31, "win_rate": 0.52, "sample_n": 20},
            regime_split={"trend": {"icir": 0.30}},
        )
    )
    assert rejected.status == "rejected"
    assert "regime_coverage_missing_trend_or_range" in rejected.rejection_reason


def test_fallback_manager_fail_open_semantics(tmp_path, monkeypatch):
    backend = CacheStorageBackend(db_path=str(tmp_path / "k004.db"))
    engine = CacheQueryEngine(backend)

    def _realtime_ok(symbol, timeframe, plugin_name, ohlcv_data):
        del symbol, timeframe, plugin_name, ohlcv_data
        return {"strength": 0.88}

    mgr = CacheFallbackManager(engine, backend, _realtime_ok)
    monkeypatch.setattr(mgr, "_async_cache_write", lambda *args, **kwargs: None)

    out = mgr.get_feature_with_fallback("TSLA", "4h", "double_pattern", 999, [{"open": 1}], timeout_ms=100)
    assert out == {"strength": 0.88}
    stats = mgr.get_fallback_stats()
    assert stats["total_fallbacks"] >= 1
    assert stats["reasons"].get("cache_miss", 0) >= 1

    def _realtime_err(symbol, timeframe, plugin_name, ohlcv_data):
        del symbol, timeframe, plugin_name, ohlcv_data
        raise RuntimeError("boom")

    mgr2 = CacheFallbackManager(engine, backend, _realtime_err)
    monkeypatch.setattr(mgr2, "_async_cache_write", lambda *args, **kwargs: None)
    out2 = mgr2.get_feature_with_fallback("TSLA", "4h", "double_pattern", 1000, [{"open": 1}], timeout_ms=100)
    assert out2 == {}
