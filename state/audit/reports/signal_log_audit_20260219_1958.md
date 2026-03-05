# KEY-001 审计报告

**生成时间**: 2026-02-20 00:58 UTC  
**数据来源**: state\audit\signal_log.jsonl  
**已判定**: 28 条 | **待回填**: 72 条  
**最小样本阈值**: 5

---

## 1. 总体指标

| 指标 | 值 | 样本 |
|------|-----|------|
| pass_accuracy   | 50.0% | 20 笔放行 |
| block_accuracy  | — | 0 笔拦截 |
| false_block_rate| — | false=0 correct=0 |
| false_pass      | 10 笔 | — |
| inconclusive    | 8 笔 | 变动<0.5% |

## 2. 按 N字状态 (n_pattern)

| 状态                   | 总计  | pass_acc   | false_block_rate | 明细 |
|------------------------|-------|------------|------------------|------|
| SIDE                   |    28 |      50.0% |              — |  10cp  10fp   0cb   0fb |

## 3. 按 N字质量分位 (n_quality)

| 质量段                 | 总计  | pass_acc   | false_block_rate | 明细 |
|------------------------|-------|------------|------------------|------|
| Q1(低)                  |    28 |      50.0% |              — |  10cp  10fp   0cb   0fb |

## 4. 按方向 (direction)

| 方向                   | 总计  | pass_acc   | false_block_rate | 明细 |
|------------------------|-------|------------|------------------|------|
| BUY                    |    14 |     100.0% |              — |  10cp   0fp   0cb   0fb |
| SELL                   |    14 |       0.0% |              — |   0cp  10fp   0cb   0fb |

## 5. 按品种 (symbol)

| 品种                   | 总计  | pass_acc   | false_block_rate | 明细 |
|------------------------|-------|------------|------------------|------|
| BTCUSDC                |     8 |          — |              — |   0cp   0fp   0cb   0fb |
| ETHUSDC                |     8 |      50.0% |              — |   4cp   4fp   0cb   0fb |
| SOLUSDC                |     8 |      50.0% |              — |   4cp   4fp   0cb   0fb |

## 6. 改善建议

1. [P1] 总体 pass_accuracy=50.0% < 55% — 建议收紧 PERFECT_N quality门槛(当前Q3/Q4才放行)或减少 break 配额
2. [P2] SIDE: pass_accuracy=50.0% 偏低 — 建议 SIDE 状态下降低配额或要求更高 quality

---

**GCC-EVO Stage**: analyze[OK] -> design[OK] -> implement[OK] -> test[WAIT: 28/30 条] -> integrate -> done

**改善执行条件**: 积累 >=7天 且 >=30条已判定记录后，按建议调整 `.GCC/params/*.yaml`