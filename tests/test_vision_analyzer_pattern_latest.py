import json
import sys
import types

import vision_analyzer as va


def test_analyze_patterns_merges_pattern_latest_and_uses_local_bars(tmp_path, monkeypatch):
    # Isolate files
    pattern_file = tmp_path / "pattern_latest.json"
    unified_log = tmp_path / "vision_analysis.log"
    pattern_file.write_text(
        json.dumps({"ETHUSDC": {"pattern": "OLD", "timestamp": "t0"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(va, "PATTERN_LATEST_FILE", str(pattern_file), raising=True)
    monkeypatch.setattr(va, "UNIFIED_LOG", str(unified_log), raising=True)

    # Avoid cooldown and external checks
    monkeypatch.setattr(va, "PATTERN_COOLDOWN_MINUTES", 0, raising=True)
    monkeypatch.setattr(va, "is_us_market_open", lambda: True, raising=True)
    monkeypatch.setattr(va, "_record_pattern_success", lambda symbol: None, raising=True)
    monkeypatch.setattr(va, "_record_pattern_failure", lambda symbol: None, raising=True)
    va._pattern_last_analysis["BTCUSDC"] = 0

    monkeypatch.setattr(va, "read_symbol_timeframe", lambda symbol, default=240: 240, raising=True)
    monkeypatch.setattr(
        va,
        "get_timeframe_params",
        lambda tf, is_crypto=False: {"current_label": "4H"},
        raising=True,
    )

    # Bars: -2 bullish for buy, -1 bearish for sell
    bars = []
    for i in range(20):
        if i == 18:
            bars.append({"open": 100.0, "high": 103.0, "low": 99.0, "close": 102.0, "volume": 10})
        elif i == 19:
            bars.append({"open": 104.0, "high": 105.0, "low": 100.0, "close": 101.0, "volume": 11})
        else:
            bars.append({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 8})
    monkeypatch.setattr(va, "fetch_pattern_bars", lambda symbol, cfg: bars, raising=True)
    monkeypatch.setattr(va, "generate_clean_chart", lambda bars, title, timeframe=None: "base64", raising=True)

    raw_result = {
        "baseline_buy": {"found": True, "bars_ago": 1},
        "baseline_sell": {"found": True, "bars_ago": 0},
    }
    monkeypatch.setattr(va, "call_chatgpt_vision", lambda *args, **kwargs: raw_result, raising=True)
    monkeypatch.setattr(
        va,
        "_parse_radar_to_pattern",
        lambda _result: {
            "pattern": "CHANNEL",
            "stage": "MATURE",
            "confidence": 0.82,
            "volume_confirmed": True,
            "reason": "unit test",
            "overall_structure": "TREND",
            "position": "MID",
            "brooks_pattern": "WEDGE",
            "direction": "UP",
            "stoploss": 99.5,
        },
        raising=True,
    )

    # Stub baseline module imported inside analyze_patterns()
    saved_baseline = {}

    def _load_state():
        return {}

    def _save_state(state):
        saved_baseline.clear()
        saved_baseline.update(state)

    monkeypatch.setitem(
        sys.modules,
        "baseline_vision_task",
        types.SimpleNamespace(_load_state=_load_state, _save_state=_save_state),
    )

    result = va.analyze_patterns("BTCUSDC", {"type": "crypto", "l1_timeframe": 240})
    assert result is not None
    assert result["symbol"] == "BTCUSDC"

    # pattern_latest should preserve existing symbols and update current one
    merged = json.loads(pattern_file.read_text(encoding="utf-8"))
    assert "ETHUSDC" in merged
    assert merged["ETHUSDC"]["pattern"] == "OLD"
    assert merged["BTCUSDC"]["pattern"] == "CHANNEL"
    assert merged["BTCUSDC"]["direction"] == "UP"

    # baseline price extraction should use local bars + bars_ago
    btc_baseline = saved_baseline["BTCUSDC"]
    assert btc_baseline["buy_found"] is True
    assert btc_baseline["sell_found"] is True
    assert btc_baseline["buy_price"] == 102.0   # bars[-2].close
    assert btc_baseline["sell_price"] == 101.0  # bars[-1].close
