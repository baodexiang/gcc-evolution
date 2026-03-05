"""
KEY-005-M05 Adversarial Validation Run 2/2
Focus: Boundary values and parser consistency
"""
import sys
import json
import os
from pathlib import Path

# Add project to path
sys.path.insert(0, '/c/Users/baode/OneDrive/桌面/ai-trading-bot')

from modules.behavior_finance import (
    _clip, _scale, _to_float, _compute_hii, _feature_engineering,
    RawSentiment, _csi_state, _compute_csi, _compute_dqs
)

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

print("=" * 70)
print("KEY-005-M05 ADVERSARIAL VALIDATION RUN 2/2")
print("=" * 70)

# ============================================================================
# BOUNDARY TEST 1: _clip() edge cases
# ============================================================================
print("\n[BOUNDARY] _clip() function")
test("clip: value below range", _clip(-100, 0, 100), 0)
test("clip: value above range", _clip(200, 0, 100), 100)
test("clip: value at low boundary", _clip(0, 0, 100), 0)
test("clip: value at high boundary", _clip(100, 0, 100), 100)
test("clip: value in middle", _clip(50, 0, 100), 50)
test("clip: inverted range (low > high)", _clip(50, 100, 0), 50)

# ============================================================================
# BOUNDARY TEST 2: _scale() edge cases
# ============================================================================
print("\n[BOUNDARY] _scale() function")
test("scale: zero range returns 50", _scale(50, 100, 100), 50.0)
test("scale: value at low boundary", _scale(10, 10, 100), 0.0)
test("scale: value at high boundary", _scale(100, 10, 100), 100.0)
test("scale: inverted scale", _scale(50, 0, 100, invert=True), 50.0)
test("scale: inverted at low", _scale(0, 0, 100, invert=True), 100.0)
test("scale: inverted at high", _scale(100, 0, 100, invert=True), 0.0)

# ============================================================================
# BOUNDARY TEST 3: _to_float() parser consistency
# ============================================================================
print("\n[PARSER] _to_float() consistency")
test("to_float: string number", _to_float("42.5", 0), 42.5)
test("to_float: int", _to_float(42, 0), 42.0)
test("to_float: float", _to_float(42.5, 0), 42.5)
test("to_float: invalid string", _to_float("invalid", 99), 99)
test("to_float: None", _to_float(None, 88), 88)
test("to_float: empty string", _to_float("", 77), 77)
test("to_float: scientific notation", _to_float("1e-3", 0), 0.001)
test("to_float: negative", _to_float("-42.5", 0), -42.5)

# ============================================================================
# BOUNDARY TEST 4: CSI state mapping
# ============================================================================
print("\n[BOUNDARY] _csi_state() mapping")
test("csi_state: <20 = EXTREME_FEAR", _csi_state(19.99), "EXTREME_FEAR")
test("csi_state: =20 = FEAR", _csi_state(20.0), "FEAR")
test("csi_state: <40 = FEAR", _csi_state(39.99), "FEAR")
test("csi_state: =40 = NEUTRAL", _csi_state(40.0), "NEUTRAL")
test("csi_state: <60 = NEUTRAL", _csi_state(59.99), "NEUTRAL")
test("csi_state: =60 = GREED", _csi_state(60.0), "GREED")
test("csi_state: <80 = GREED", _csi_state(79.99), "GREED")
test("csi_state: =80 = EXTREME_GREED", _csi_state(80.0), "EXTREME_GREED")
test("csi_state: >80 = EXTREME_GREED", _csi_state(100.0), "EXTREME_GREED")

# ============================================================================
# BOUNDARY TEST 5: HII state mapping
# ============================================================================
print("\n[BOUNDARY] HII state mapping")
# Create minimal features dict
features = {
    "fear_greed_score": 50.0,
    "lsr_score": 50.0,
}

# Mock herding_inputs.json
os.makedirs("state/behavior_sources", exist_ok=True)
with open("state/behavior_sources/herding_inputs.json", "w") as f:
    json.dump({"symbols": {"TEST": {"social_sentiment": 50.0, "fund_flow_bias": 50.0}}}, f)

hii_result = _compute_hii("TEST", features)
hii = hii_result["hii"]
test("hii: neutral inputs = ~50", abs(hii - 50.0) < 5.0, True)

# Test with extreme values
features_extreme_high = {
    "fear_greed_score": 100.0,
    "lsr_score": 100.0,
}
with open("state/behavior_sources/herding_inputs.json", "w") as f:
    json.dump({"symbols": {"TEST": {"social_sentiment": 100.0, "fund_flow_bias": 100.0}}}, f)
hii_extreme = _compute_hii("TEST", features_extreme_high)
test("hii: extreme high values clipped to 100", hii_extreme["hii"] <= 100.0, True)

features_extreme_low = {
    "fear_greed_score": 0.0,
    "lsr_score": 0.0,
}
with open("state/behavior_sources/herding_inputs.json", "w") as f:
    json.dump({"symbols": {"TEST": {"social_sentiment": 0.0, "fund_flow_bias": 0.0}}}, f)
hii_extreme_low = _compute_hii("TEST", features_extreme_low)
test("hii: extreme low values clipped to 0", hii_extreme_low["hii"] >= 0.0, True)

# ============================================================================
# BOUNDARY TEST 6: DQS gate thresholds
# ============================================================================
print("\n[BOUNDARY] DQS gate thresholds")
dqs_high = _compute_dqs(0.95, 50.0, "BUY")
test("dqs: high confidence no gates", dqs_high["gate"]["half_position"], False)
test("dqs: high confidence no block", dqs_high["gate"]["block_new_entry"], False)

dqs_mid = _compute_dqs(0.70, 50.0, "BUY")
test("dqs: mid confidence may gate", dqs_mid["dqs"] >= 40.0, True)

# Test with extreme CSI to trigger gate (neutral CSI boosts regime alignment)
dqs_low = _compute_dqs(0.30, 15.0, "BUY")  # Extreme fear CSI
test("dqs: low confidence + extreme fear blocks", dqs_low["gate"]["block_new_entry"], True)

# ============================================================================
# BOUNDARY TEST 7: Feature engineering winsorization
# ============================================================================
print("\n[BOUNDARY] Feature engineering winsorization")
raw_extreme = RawSentiment(
    vix=200.0,
    fear_greed=150.0,
    long_short_ratio=5.0,
    funding_rate=0.1,
    missing_count=0
)
features_extreme = _feature_engineering(raw_extreme)
test("winsorize: vix clipped", features_extreme["vix_clean"] <= 80.0, True)
test("winsorize: fear_greed clipped", features_extreme["fear_greed_clean"] <= 100.0, True)
test("winsorize: lsr clipped", features_extreme["lsr_clean"] <= 2.2, True)
test("winsorize: funding clipped", features_extreme["funding_clean"] <= 0.01, True)

# ============================================================================
# BOUNDARY TEST 8: CSI computation consistency
# ============================================================================
print("\n[BOUNDARY] CSI computation consistency")
features_neutral = {
    "vix_score": 50.0,
    "fear_greed_score": 50.0,
    "lsr_score": 50.0,
    "funding_score": 50.0,
}
csi_neutral = _compute_csi(features_neutral)
test("csi: neutral inputs = ~50", abs(csi_neutral["csi"] - 50.0) < 1.0, True)

features_extreme_fear = {
    "vix_score": 0.0,
    "fear_greed_score": 0.0,
    "lsr_score": 0.0,
    "funding_score": 0.0,
}
csi_fear = _compute_csi(features_extreme_fear)
test("csi: extreme fear inputs = ~0", csi_fear["csi"] < 5.0, True)

features_extreme_greed = {
    "vix_score": 100.0,
    "fear_greed_score": 100.0,
    "lsr_score": 100.0,
    "funding_score": 100.0,
}
csi_greed = _compute_csi(features_extreme_greed)
test("csi: extreme greed inputs = ~100", csi_greed["csi"] > 95.0, True)

# ============================================================================
# BOUNDARY TEST 9: Weight sum validation
# ============================================================================
print("\n[CONSISTENCY] Weight sum validation")
csi_weights = _compute_csi(features_neutral)["weights"]
csi_weight_sum = sum(csi_weights.values())
test("csi: weights sum to 1.0", abs(csi_weight_sum - 1.0) < 0.001, True)

hii_weights = _compute_hii("TEST", features_neutral)["weights"]
hii_weight_sum = sum(hii_weights.values())
test("hii: weights sum to 1.0", abs(hii_weight_sum - 1.0) < 0.001, True)

# ============================================================================
# BOUNDARY TEST 10: Rounding consistency
# ============================================================================
print("\n[CONSISTENCY] Rounding consistency")
test("rounding: vix_score 2 decimals", len(str(features_extreme["vix_score"]).split('.')[-1]) <= 2, True)
test("rounding: csi 2 decimals", len(str(csi_neutral["csi"]).split('.')[-1]) <= 2, True)
test("rounding: hii 2 decimals", len(str(hii_result["hii"]).split('.')[-1]) <= 2, True)

# ============================================================================
# SUMMARY
# ============================================================================
print("\n" + "=" * 70)
print(f"RESULTS: {PASS_COUNT} PASS, {FAIL_COUNT} FAIL")
print("=" * 70)

if FAIL_COUNT > 0:
    print("\nFAILED TESTS:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("\n[SUCCESS] ALL TESTS PASSED")
    sys.exit(0)
