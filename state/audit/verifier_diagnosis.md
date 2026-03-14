# BeyondEuclidVerifier 实盘诊断报告

**数据范围**: 2026-03-11 ~ 2026-03-13 (gcc_trading_decisions.jsonl)
**总记录数**: 1,299 条

---

## 1. 总体统计

| 指标 | 数值 | 占比 |
|------|------|------|
| 总决策数 | 1,299 | 100% |
| EXECUTE | 732 | 56.4% |
| SKIP | 566 | 43.6% |
| HOLD_ONLY | 1 | 0.1% |

### 动作分布

| 动作 | 次数 | 占比 |
|------|------|------|
| HOLD | 432 | 33.3% |
| UNKNOWN (None) | 381 | 29.3% |
| BUY | 249 | 19.2% |
| SELL | 237 | 18.2% |

### Phase 分布

| Phase | 次数 |
|-------|------|
| execute | 1,099 |
| observe | 199 |
| hold_only | 1 |

---

## 2. 三视角通过率

> 注意：仅 736/1299 条记录包含 verifier_results（非空），563 条为空数组。

| 视角 | ok=True | 总数 | 通过率 |
|------|---------|------|--------|
| **topology** | 534 | 736 | **72.6%** |
| **geometry** | 407 | 736 | **55.3%** |
| **algebra** | 423 | 736 | **57.5%** |

### 关键发现：topology 通过率最高(72.6%)，可能门控过松

---

## 3. 三视角组合分布

| 组合 | 次数 | 占比 | 说明 |
|------|------|------|------|
| **0/3 通过** | 597 | **46.0%** | 含563条空VR记录+34条全fail |
| 1/3 通过 | 216 | 16.6% | |
| 2/3 通过 | 310 | 23.9% | |
| 3/3 通过 | 176 | 13.5% | |

### 2/3 通过的子分布

| 哪两个通过 | 次数 | 占比 |
|------------|------|------|
| algebra + topology | 121 | 9.3% |
| geometry + topology | 118 | 9.1% |
| algebra + geometry | 71 | 5.5% |

### 1/3 通过的子分布

| 哪个通过 | 次数 | 占比 |
|----------|------|------|
| topology | 119 | 9.2% |
| algebra | 55 | 4.2% |
| geometry | 42 | 3.2% |

---

## 4. Consensus 与 Verdict 的关系

**发现：verdict 完全由 consensus 阈值决定，>=2 则 EXECUTE，<2 则 SKIP。**

| consensus | EXECUTE | SKIP | EXECUTE率 |
|-----------|---------|------|-----------|
| 0 | 0 | 244 | **0%** |
| 1 | 0 | 322 | **0%** |
| **2** | **456** | **0** | **100%** |
| **3** | **276** | **0** | **100%** |

**结论：这是一个硬阈值 `consensus >= 2`，没有灰度。2/3 通过即全部放行。**

---

## 5. 空 verifier_results 记录分析

**563 条记录的 verifier_results 为空数组 `[]`**

| verdict | 次数 |
|---------|------|
| SKIP | 316 |
| EXECUTE | **246** |
| HOLD_ONLY | 1 |

**246 条无任何验证就 EXECUTE 了。** 这些记录的特征：
- `final_action` 全部为 None/UNKNOWN (381条) 或 HOLD (182条)
- 意味着 HOLD/无信号 的情况跳过了验证器直接进入下一步

**风险评估**：HOLD 动作无需验证合理，但需确认 EXECUTE+空VR 是否意味着未经过滤的交易信号。

---

## 6. 各视角深度分析

### 6.1 Topology（通过率 72.6% - 最宽松）

**reasoning 分布 TOP 5**：
| 次数 | 原因 |
|------|------|
| 107 | pos=1 neg=1 neutral=7 active=2 cheeger=0.50 |
| 46 | fallback: active=1 (pos=0 neg=1 neutral=10) |
| 30 | pos=1 neg=2 neutral=6 active=3 cheeger=0.33 |
| 24 | pos=1 neg=2 neutral=6 active=3 cheeger=0.33 fiedler=0.0000 |
| 19 | pos=2 neg=1 neutral=6 active=3 cheeger=0.33 |

**问题**：大量 `neutral` 节点（6-10个），`active` 节点极少（1-4个），说明图结构非常稀疏。多数决策的拓扑图没有足够信号节点来形成有意义的判断。

### 6.2 Geometry（通过率 55.3% - 最严格）

| 指标 | 数值 |
|------|------|
| aligned=True | 407 (55.3%) |
| aligned=False | 329 (44.7%) |

**工作机制**：检查动量方向(momentum_up)是否与动作方向(BUY/SELL)一致。
- BUY + momentum_up=True → aligned=True → ok=True
- BUY + momentum_up=False → aligned=False → ok=False

**评估**：geometry 是三个视角中最有实际判断力的，真正在做方向性检验。

### 6.3 Algebra（通过率 57.5% - 有严重数据问题）

| 类型 | 次数 | 占比 |
|------|------|------|
| **fallback ok=True**（无历史数据） | 103 | **14.0%** |
| 真实评估 | 633 | 86.0% |
| 真实评估中 ok=True | 320 | 50.6% |

**问题**：14% 的记录因为 `no history, fallback ok=True` 直接放行。这些是未经验证的自动通过。真实评估时通过率仅 50.6%，说明 algebra 的 fallback 机制在虚增通过率。

---

## 7. SKIP 拦截来源分析

在所有 566 次 SKIP 中（含空 VR 的 SKIP）：

| 拦截视角 | 次数 | 占 SKIP 比例 |
|----------|------|-------------|
| geometry | 208 | 36.7% |
| algebra | 195 | 34.5% |
| topology | 131 | 23.1% |

**geometry 是最主要的拦截者**，与其最低通过率一致。

---

## 8. 按 Symbol 统计

### 加密货币

| Symbol | 总数 | EXECUTE | SKIP | topo_ok | geo_ok | alg_ok |
|--------|------|---------|------|---------|--------|--------|
| BTCUSDC | 234 | 62% | 38% | 37% | 34% | 45% |
| ETHUSDC | 211 | 64% | 36% | 36% | 30% | 48% |
| SOLUSDC | 209 | 52% | 48% | 36% | 32% | 26% |
| ZECUSDC | 211 | 48% | 52% | 46% | 35% | 20% |

### 股票

| Symbol | 总数 | EXECUTE | SKIP | topo_ok | geo_ok | alg_ok |
|--------|------|---------|------|---------|--------|--------|
| TSLA | 47 | 34% | 64% | 53% | 21% | 11% |
| RKLB | 40 | 28% | 72% | 38% | 22% | 20% |
| CRWV | 40 | 40% | 60% | 45% | 25% | 20% |
| RDDT | 40 | 50% | 50% | 50% | 18% | 28% |
| PLTR | 40 | 52% | 48% | 45% | 32% | 12% |
| COIN | 14 | 43% | 57% | 29% | 14% | 43% |
| HIMS | 38 | 66% | 34% | 53% | 24% | 26% |
| NBIS | 40 | 75% | 25% | 52% | 48% | 40% |
| OPEN | 39 | 72% | 28% | 62% | 44% | 15% |
| ONDS | 40 | 65% | 35% | 35% | 28% | 52% |
| AMD | 40 | 65% | 35% | 30% | 22% | 35% |

### 异常品种

- **RKLB**: SKIP 率 72%，三个视角都很低 — 过度拦截嫌疑
- **TSLA**: SKIP 率 64%，algebra 仅 11% — algebra 对 TSLA 几乎全拒
- **NBIS**: EXECUTE 率 75%，三个视角都相对高 — 可能过于宽松
- **ZECUSDC**: algebra 仅 20%，但 topo 46% — 视角间差异大

---

## 9. 核心问题诊断

### 问题 1: 空 verifier_results 的 EXECUTE (246条)
- HOLD/None 动作绕过了验证器直接 EXECUTE
- 需确认这是设计意图还是代码漏洞

### 问题 2: algebra fallback 虚增通过率
- 14% 的 algebra 判断是 `no history, fallback ok=True`
- 实际有数据时通过率仅 50.6%
- **建议**: fallback 改为 ok=False 或 ok=None（不参与投票）

### 问题 3: topology 图稀疏，判断力不足
- 大量 active=1-2, neutral=7-10 的稀疏图
- cheeger 常数 0.50-0.80 反映高度割裂
- 72.6% 通过率暗示其门控太松

### 问题 4: consensus=2 硬阈值无灰度
- 2/3 通过 = 100% EXECUTE，1/3 = 100% SKIP
- 没有 score 加权或 confidence 调节
- 特别是 topology(松) + algebra(fallback) 两个弱视角同时 ok 就能通过

### 问题 5: geometry 是唯一有效视角
- geometry 做真正的方向性检验（动量 vs 动作）
- 但在 2/3 投票制下可以被另两个视角覆盖

---

## 10. SKIP 样本（前5条完整记录）

### SKIP #1 — ETHUSDC BUY 被拦截
```
ts: 2026-03-11T04:00:31Z, consensus=1
topology: ok=false, score=0.2, "pos=1 neg=1 minority=4/5 cheeger=0.80"
geometry: ok=false, score=0.45, "curvature=-0.000459 momentum_up=False action=BUY aligned=False"
algebra:  ok=true,  score=0.5, "no history, fallback ok=True"
```
> 分析: geometry 正确拦截（BUY 但动量向下），algebra fallback 放行无意义

### SKIP #2 — SOLUSDC BUY 被拦截
```
ts: 2026-03-11T04:00:33Z, consensus=1
topology: ok=false, score=0.2, "pos=1 neg=1 minority=4/5 cheeger=0.80"
geometry: ok=false, score=0.42, "curvature=-0.000782 momentum_up=False action=BUY aligned=False"
algebra:  ok=true,  score=0.5, "no history, fallback ok=True"
```

### SKIP #3 — BTCUSDC BUY 被拦截
```
ts: 2026-03-11T04:00:36Z, consensus=1
topology: ok=false, score=0.2
geometry: ok=false, score=0.49, "momentum_up=False action=BUY aligned=False"
algebra:  ok=true,  score=0.5, "no history, fallback ok=True"
```

### SKIP #4 — ZECUSDC BUY 被拦截
```
ts: 2026-03-11T04:00:38Z, consensus=1
topology: ok=false, score=0.2
geometry: ok=false, score=0.35, "curvature=-0.001808 momentum_up=False action=BUY aligned=False"
algebra:  ok=true,  score=0.5, "no history, fallback ok=True"
```

### SKIP #5 — ETHUSDC HOLD (空VR)
```
ts: 2026-03-11T12:00:43Z, consensus=0
verifier_results: [] (空)
final_action: HOLD
```

**SKIP 共性模式**: topology+geometry 双拒，只有 algebra fallback 通过 → consensus=1 → SKIP

---

## 11. EXECUTE 样本（前5条完整记录）

### EXECUTE #1 — BTCUSDC BUY
```
ts: 2026-03-11T01:10:35Z, consensus=2
topology: ok=false, score=0.2, "pos=1 neg=0 minority=4/5 cheeger=0.80"
geometry: ok=true,  score=0.5, "curvature=0 momentum_up=True action=BUY aligned=True"
algebra:  ok=true,  score=0.5, "no history, fallback ok=True"
```
> 分析: topology 拒绝，但 geometry+algebra(fallback) 通过 → consensus=2 → EXECUTE
> **隐患**: algebra 是 fallback 自动通过，实质上只有 geometry 一个真实判断

### EXECUTE #2 — BTCUSDC BUY (execute phase)
```
ts: 2026-03-11T01:10:35Z, consensus=2
topology: ok=false, score=0.2
geometry: ok=true,  score=0.5, "momentum_up=True action=BUY aligned=True"
algebra:  ok=true,  score=1.0, "weighted_wr=1.000 n=5 action=BUY"
```
> 分析: algebra 有真实数据(wr=1.0, n=5)，geometry 对齐 → 2/3 合理

### EXECUTE #3-5 — 同 BTCUSDC BUY，模式相同

---

## 12. 总结与建议

### 最可能的问题视角

| 排序 | 视角 | 问题 | 严重程度 |
|------|------|------|----------|
| **1** | **algebra** | 14% fallback 自动通过，与 geometry 组合可绕过 topology | **高** |
| **2** | **topology** | 图太稀疏(active 1-4)，判断力不足 | 中 |
| **3** | 整体架构 | consensus=2 硬阈值，两个弱视角可覆盖一个强视角 | 中 |
| **4** | geometry | 实际最有效，但可被覆盖 | 低(本身没问题) |

### 风险场景
```
geometry=False (动量不支持) + topology=True (稀疏图) + algebra=True (fallback)
→ consensus=2 → EXECUTE → 逆动量交易
```
这是当前架构最危险的放行路径。
