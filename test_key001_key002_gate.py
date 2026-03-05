"""
KEY-001 / KEY-002 Phase B 门控验证测试
commit: 19b39a5
"""

import sys
sys.path.insert(0, ".")

PASS_COUNT = 0
FAIL_COUNT = 0
FAILURES = []


def test(name, condition, expected=True):
    global PASS_COUNT, FAIL_COUNT, FAILURES
    if condition == expected:
        PASS_COUNT += 1
        print(f"[PASS] {name}")
    else:
        FAIL_COUNT += 1
        FAILURES.append(name)
        print(f"[FAIL] {name} (got {condition}, expected {expected})")


print("=" * 65)
print("KEY-001 / KEY-002 Phase B 门控验证")
print("=" * 65)

# ── KEY-001 ──────────────────────────────────────────────────────────────

from modules.vision_adaptive import (
    compute_key001_gate_score,
    evaluate_key001_gate,
    Key001GateInput,
    _KEY001_PHASE2_ENFORCE,
    _STRUCT_TO_PHASE,
    update_key001_false_block_stats,
    suggest_key001_threshold_update,
)

print("\n[KEY-001] enforce 状态")
test("Phase B enforce=True", _KEY001_PHASE2_ENFORCE is True)

print("\n[KEY-001] gate_score 计算")

# 高置信 + 强结构：score = 0.35*0.85 + 0.25*0.85 + 0.20*0.80 - 0.20*0.10 = 0.65
inp_high = Key001GateInput("BTC", "BUY", "MARKUP", signal_conf=0.85, n_state_strength=0.85, trend_consistency=0.80, risk_score=0.10)
score_high = compute_key001_gate_score(inp_high)
test("高置信高结构 → score>0.58(高于soft_thresh)", score_high > 0.58)

# 低置信 + 弱结构 → 低分
inp_low = Key001GateInput("BTC", "BUY", "UNKNOWN", signal_conf=0.20, n_state_strength=0.30, trend_consistency=0.30, risk_score=0.80)
score_low = compute_key001_gate_score(inp_low)
test("低置信弱结构 → score<0.3", score_low < 0.30)

# 风险拉高会压低分数
inp_risk = Key001GateInput("BTC", "BUY", "MARKUP", signal_conf=0.70, n_state_strength=0.70, trend_consistency=0.70, risk_score=0.90)
score_risk = compute_key001_gate_score(inp_risk)
test("高风险压低分数 < 低风险版本", score_risk < score_high)

print("\n[KEY-001] evaluate_key001_gate 决策")

# 超高置信 → PASS（score需>=0.72 for MARKUP default）
# score = 0.35*0.95 + 0.25*0.92 + 0.20*0.90 - 0.20*0.05 = 0.3325+0.23+0.18-0.01 = 0.7325
inp_vhigh = Key001GateInput("BTC", "BUY", "MARKUP", signal_conf=0.95, n_state_strength=0.92, trend_consistency=0.90, risk_score=0.05)
res_pass = evaluate_key001_gate(inp_vhigh)
test("超高置信 → PASS", res_pass.decision == "PASS")

# 低分 → BLOCK
res_block = evaluate_key001_gate(inp_low)
test("低分 → BLOCK", res_block.decision == "BLOCK")

# score=0.65 in [0.58, 0.72) → HOLD
# score = 0.35*0.85 + 0.25*0.85 + 0.20*0.80 - 0.20*0.10 = 0.65
res_mid = evaluate_key001_gate(inp_high)
test("score=0.65 在HOLD带 → HOLD", res_mid.decision == "HOLD")

print("\n[KEY-001] ACCUM 分桶(hard_block=0.80, soft_hold=0.64)")
# ACCUM_BUY: score=0.65 → 0.64<=0.65<0.80 → HOLD
inp_accum = Key001GateInput("BTC", "BUY", "ACCUM", signal_conf=0.85, n_state_strength=0.85, trend_consistency=0.80, risk_score=0.10)
res_accum = evaluate_key001_gate(inp_accum)
test("ACCUM score=0.65 → HOLD(在[0.64,0.80)带内)", res_accum.decision == "HOLD")

print("\n[KEY-001] struct→phase 映射")
test("ACCUMULATION → ACCUM", _STRUCT_TO_PHASE.get("ACCUMULATION") == "ACCUM")
test("DISTRIBUTION → DISTRIB", _STRUCT_TO_PHASE.get("DISTRIBUTION") == "DISTRIB")
test("MARKUP → MARKUP", _STRUCT_TO_PHASE.get("MARKUP") == "MARKUP")
test("MARKDOWN → MARKDOWN", _STRUCT_TO_PHASE.get("MARKDOWN") == "MARKDOWN")

print("\n[KEY-001] suggest_threshold_update 逻辑")
# block_rate >= 0.35 且 samples >= 20 → relax
mock_stats = {
    "BTC_ACCUM_BUY": {"total": 25, "block": 10, "hold": 5, "pass": 10, "block_rate": 0.40},
    "ETH_SIDE_BUY":  {"total": 30, "block": 2,  "hold": 3, "pass": 25, "block_rate": 0.07},
    "SOL_MARKUP_BUY": {"total": 10, "block": 5, "hold": 2, "pass": 3,  "block_rate": 0.50},  # samples<20, skip
}
changes = suggest_key001_threshold_update(mock_stats)
buckets_changed = [c["bucket"] for c in changes]
test("BTC_ACCUM_BUY block_rate=0.40 → relax", "BTC_ACCUM_BUY" in buckets_changed)
test("ETH_SIDE_BUY block_rate=0.07 → tighten", "ETH_SIDE_BUY" in buckets_changed)
test("SOL_MARKUP_BUY samples=10 → 不建议(样本不足)", "SOL_MARKUP_BUY" not in buckets_changed)
btc_change = next((c for c in changes if c["bucket"] == "BTC_ACCUM_BUY"), None)
test("relax: soft_hold_delta=+0.03", btc_change and btc_change["soft_hold_threshold_delta"] == 0.03)

# ── KEY-002 ──────────────────────────────────────────────────────────────

from modules.key002_regime import (
    Key002RegimeFeatures,
    detect_regime,
    load_key002_runtime_params,
    key002_apply_entry_gate,
    key002_adjust_stoploss,
    build_features_from_market_regime,
    _KEY002_PHASE2_ENFORCE,
)

print("\n[KEY-002] enforce 状态")
test("Phase B enforce=True", _KEY002_PHASE2_ENFORCE is True)

print("\n[KEY-002] detect_regime")
# 震荡高波动
feat_sh = Key002RegimeFeatures("BTC", atr_pct=0.035, trend_persistence=0.35, flip_count_24h=4)
test("震荡高波动 → SIDE_HIGH_VOL", detect_regime(feat_sh) == "REGIME_SIDE_HIGH_VOL")

# 趋势低波动
feat_tl = Key002RegimeFeatures("TSLA", atr_pct=0.012, trend_persistence=0.75, flip_count_24h=1)
test("趋势低波动 → TREND_LOW_VOL", detect_regime(feat_tl) == "REGIME_TREND_LOW_VOL")

# 趋势高波动
feat_th = Key002RegimeFeatures("ETH", atr_pct=0.035, trend_persistence=0.70, flip_count_24h=1)
test("趋势高波动 → TREND_HIGH_VOL", detect_regime(feat_th) == "REGIME_TREND_HIGH_VOL")

# 震荡低波动
feat_sl = Key002RegimeFeatures("ZEC", atr_pct=0.010, trend_persistence=0.30, flip_count_24h=5)
test("震荡低波动 → SIDE_LOW_VOL", detect_regime(feat_sl) == "REGIME_SIDE_LOW_VOL")

# 数据过期 → EVENT_RISK
feat_ev = Key002RegimeFeatures("SOL", atr_pct=0.02, trend_persistence=0.60, flip_count_24h=2, data_staleness_sec=1000)
test("数据过期 → EVENT_RISK", detect_regime(feat_ev) == "REGIME_EVENT_RISK")

print("\n[KEY-002] 参数矩阵")
params_sh = load_key002_runtime_params("BTC", "REGIME_SIDE_HIGH_VOL")
test("SIDE_HIGH_VOL cooldown=8", params_sh.side_cooldown_hours == 8)
test("SIDE_HIGH_VOL threshold=0.70", params_sh.entry_threshold == 0.70)
test("SIDE_HIGH_VOL atr_mult=1.28", params_sh.atr_multiplier == 1.28)
test("SIDE_HIGH_VOL max_trades=1", params_sh.max_trades_per_cycle == 1)

params_ev = load_key002_runtime_params("SOL", "REGIME_EVENT_RISK")
test("EVENT_RISK max_trades=0", params_ev.max_trades_per_cycle == 0)

print("\n[KEY-002] entry_gate 决策")
# 震荡高波动 + 低置信 → 拦截
allowed, reason = key002_apply_entry_gate("BTC", 0.50, params_sh)
test("SIDE_HIGH_VOL conf=0.50 → 拦截", allowed is False)
test("拦截原因含entry_threshold", "entry_threshold" in reason)

# 趋势低波动 + 高置信 → 放行
params_tl = load_key002_runtime_params("TSLA", "REGIME_TREND_LOW_VOL")
allowed_tl, _ = key002_apply_entry_gate("TSLA", 0.72, params_tl)
test("TREND_LOW_VOL conf=0.72 → 放行", allowed_tl is True)

# EVENT_RISK 无论置信度多高都冻结
allowed_ev, reason_ev = key002_apply_entry_gate("SOL", 0.99, params_ev)
test("EVENT_RISK conf=0.99 → 全冻结", allowed_ev is False)
test("冻结原因=event_risk_freeze", "event_risk_freeze" in reason_ev)

print("\n[KEY-002] 止损调整")
adj = key002_adjust_stoploss(0.025, params_sh)
test("SIDE_HIGH_VOL stop=0.025×1.28=0.032", abs(adj - 0.032) < 0.0001)

params_tl2 = load_key002_runtime_params("TSLA", "REGIME_TREND_LOW_VOL")
adj_tl = key002_adjust_stoploss(0.025, params_tl2)
test("TREND_LOW_VOL stop=0.025×1.00=0.025", abs(adj_tl - 0.025) < 0.0001)

print("\n[KEY-002] build_features_from_market_regime")
mr = {"current_trend": "UP", "atr_pct": 0.018, "flip_count_24h": 2, "data_staleness_sec": 0}
feat_mr = build_features_from_market_regime("COIN", mr)
test("UP trend → persistence=0.65", feat_mr.trend_persistence == 0.65)
test("atr_pct 正确读取", feat_mr.atr_pct == 0.018)

mr_side = {"current_trend": "SIDE"}
feat_side = build_features_from_market_regime("AMD", mr_side)
test("SIDE trend → persistence=0.35", feat_side.trend_persistence == 0.35)

# ── 结果 ─────────────────────────────────────────────────────────────────

print("\n" + "=" * 65)
print(f"结果: {PASS_COUNT} passed, {FAIL_COUNT} failed")
if FAILURES:
    print(f"FAILED: {FAILURES}")
print("=" * 65)
