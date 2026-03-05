from __future__ import annotations

from datetime import datetime, timedelta, timezone

from modules import key001_vision_cache as k1


def _snap(
    snapshot_id: str,
    *,
    confidence: float = 0.8,
    bias: k1.Bias = "BUY",
    ts_iso: str | None = None,
) -> k1.VisionSnapshot:
    ts = ts_iso or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return k1.VisionSnapshot(
        snapshot_id=snapshot_id,
        ts_iso=ts,
        symbol="TSLA",
        timeframe="4h",
        price_at_snapshot=100.0,
        pattern="DOUBLE_BOTTOM",
        bias=bias,
        confidence=confidence,
        key_features=["f1", "f2"],
        price_signature=[0.1, 0.3, 0.7, 0.9],
        volume_signature=[0.2, 0.4, 0.6, 0.8],
        structure_points=[(5, "L", 0.2), (15, "H", 0.8)],
    )


def test_signatures_and_similarity_paths():
    closes = [float(x) for x in range(1, 81)]
    volumes = [100.0 + float(x) for x in range(80)]

    price_sig = k1.compute_price_signature(closes, bars=60)
    vol_sig = k1.compute_volume_signature(volumes, bars=60)
    points = k1.compute_structure_points(closes, bars=60, order=3)

    assert len(price_sig) == 60
    assert len(vol_sig) == 60
    assert all(0.0 <= x <= 1.0 for x in price_sig)
    assert all(0.0 <= x <= 1.0 for x in vol_sig)
    assert isinstance(points, list)

    assert k1.l2_similarity([0.1, 0.2, 0.3], [0.1, 0.2, 0.3]) == 1.0
    assert 0.0 <= k1.cosine_similarity([1.0, 0.0], [0.0, 1.0]) <= 0.5


def test_calibration_behavior_low_and_medium_reliability():
    cur = _snap("cur", confidence=0.9)

    low = k1.calibrate_with_twins(cur, [(_snap("h1"), 0.9), (_snap("h2"), 0.8)])
    assert low.reliability == "low"
    assert abs(low.calibrated_confidence - 0.72) < 1e-9

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    twins = []
    for i in range(10):
        s = _snap(f"hist_{i}", confidence=0.7, ts_iso=ts)
        s.actual_outcome = "UP_WEAK"
        s.vision_correct = i < 7
        s.move_pct["3d"] = 0.01 if i < 7 else -0.01
        twins.append((s, 1.0))

    med = k1.calibrate_with_twins(cur, twins)
    assert med.reliability == "medium"
    assert med.historical_winrate is not None and med.historical_winrate > 0.65
    assert med.expected_move_3d is not None and med.expected_move_3d > 0.0
    assert med.calibrated_confidence > 0.8


def test_vision_gate_fail_open_when_enhanced_vision_errors(monkeypatch, tmp_path):
    cache = k1.VisionCache(root_dir=str(tmp_path / "vision_cache"))

    def _boom(*args, **kwargs):
        raise RuntimeError("test failure")

    monkeypatch.setattr(k1, "enhanced_vision", _boom)

    allowed_obs, reason_obs = k1.vision_gate("TSLA", "BUY", None, None, cache, mode="observe")
    allowed_full, reason_full = k1.vision_gate("TSLA", "BUY", None, None, cache, mode="full")

    assert allowed_obs is True and reason_obs == "fail_open_exception"
    assert allowed_full is True and reason_full == "fail_open_exception"


def test_backfill_snapshots_monkeypatched_price_source(tmp_path, monkeypatch):
    cache = k1.VisionCache(root_dir=str(tmp_path / "vision_cache"))
    ts_iso = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    snap = _snap("bf_1", ts_iso=ts_iso, confidence=0.75, bias="BUY")
    cache.save(snap)

    px_map = {"1h": 101.0, "4h": 102.0, "1d": 103.0, "3d": 105.0}

    def _fake_get_price_at(symbol: str, ts: str, horizon: str):
        del symbol, ts
        return px_map[horizon]

    monkeypatch.setattr(k1, "get_price_at", _fake_get_price_at)

    updated = k1.backfill_snapshots(cache)
    assert updated == 1

    rows = cache.query(pattern="DOUBLE_BOTTOM", bias="BUY", timeframe="4h", limit=10)
    assert len(rows) == 1
    out = rows[0]
    assert out.price_after == px_map
    assert out.actual_outcome == "UP_STRONG"
    assert out.vision_correct is True
