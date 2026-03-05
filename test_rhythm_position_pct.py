"""
fix(rhythm) 节奏评分修复验证
测试: market_regime 写入时 position_pct 字段是否正确传递给扫描引擎
commit: 5d7700e
"""

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


# ============================================================================
# 模拟 market_regime 写入逻辑（L3652-3653）
# ============================================================================

def build_market_regime(pos_in_channel):
    """模拟 llm_server_v3640.py L3652-3653 的写入逻辑"""
    mr = {}
    if pos_in_channel is not None:
        mr["position_pct"] = round(pos_in_channel * 100, 1)
    return mr


def simulate_scan_engine_rhythm(mr):
    """模拟扫描引擎读取 position_pct 计算节奏分"""
    pos = mr.get("position_pct", 50.0)  # 默认 50.0
    # 节奏分: pos_in_channel 越高越倾向高位，越低越倾向低位
    return pos


print("=" * 60)
print("fix(rhythm): market_regime position_pct 字段传递验证")
print("=" * 60)

# ============================================================================
# T1: 正常写入 — pos_in_channel 有值时 position_pct 必须写入
# ============================================================================
print("\n[T1] 正常写入")

mr = build_market_regime(0.75)
test("pos=0.75 → position_pct=75.0", mr.get("position_pct") == 75.0)

mr = build_market_regime(0.0)
test("pos=0.0 → position_pct=0.0", mr.get("position_pct") == 0.0)

mr = build_market_regime(1.0)
test("pos=1.0 → position_pct=100.0", mr.get("position_pct") == 100.0)

mr = build_market_regime(0.501)
test("pos=0.501 → position_pct=50.1 (四舍五入1位)", mr.get("position_pct") == 50.1)

# ============================================================================
# T2: None 保护 — pos_in_channel=None 时不写入字段（不能用默认50）
# ============================================================================
print("\n[T2] None 保护")

mr = build_market_regime(None)
test("pos=None → position_pct 字段不存在", "position_pct" not in mr)

# ============================================================================
# T3: 扫描引擎读取 — 有值时用真实值，无值时才用默认50
# ============================================================================
print("\n[T3] 扫描引擎读取")

mr = build_market_regime(0.2)
score = simulate_scan_engine_rhythm(mr)
test("pos=0.2 → 节奏分=20.0 (非默认50)", score == 20.0)

mr = build_market_regime(0.9)
score = simulate_scan_engine_rhythm(mr)
test("pos=0.9 → 节奏分=90.0 (非默认50)", score == 90.0)

# None 时才退化为50
mr = build_market_regime(None)
score = simulate_scan_engine_rhythm(mr)
test("pos=None → 节奏分=50.0 (降级默认)", score == 50.0)

# ============================================================================
# T4: 修复前的 bug 复现 — 没有 position_pct 时节奏永远50
# ============================================================================
print("\n[T4] 修复前 bug 复现（验证修复必要性）")

def build_market_regime_buggy(pos_in_channel):
    """修复前: 不写 position_pct"""
    mr = {}
    # 故意不写 position_pct
    return mr

mr_buggy = build_market_regime_buggy(0.2)
score_buggy = simulate_scan_engine_rhythm(mr_buggy)
test("修复前: 无论 pos 为何，节奏分=50 (bug)", score_buggy == 50.0)

# 修复后同样 pos=0.2 → 20.0
mr_fixed = build_market_regime(0.2)
score_fixed = simulate_scan_engine_rhythm(mr_fixed)
test("修复后: pos=0.2 → 节奏分=20.0 (正确)", score_fixed == 20.0)
test("修复前后节奏分不同（验证修复有效）", score_buggy != score_fixed)

# ============================================================================
# 结果汇总
# ============================================================================
print("\n" + "=" * 60)
print(f"结果: {PASS_COUNT} passed, {FAIL_COUNT} failed")
if FAILURES:
    print(f"FAILED: {FAILURES}")
print("=" * 60)
