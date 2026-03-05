# 股票价值分析模块 PRD v1.1 补丁规范

版本: v1.1 (Patch)
日期: 2026-02-16
基线文档: `valueanalysis/股票价值分析模块 PRD v1_0.pdf`
目标: 将 v1.0 从“方向正确”提升为“可直接实现、可直接验收”。

---

## 1) 作用范围与边界 (MVP / Non-MVP)

### MVP (本期必须实现)
- 三层评分引擎: Valuation / Momentum / Quality。
- 单股与批量分析 API。
- 与交易系统集成: 标的过滤 + 仓位上限修正 (不替代技术面入场点)。
- 基础缓存与降级机制: API 失败时允许部分评分, 但必须标注缺失。
- 历史分值存档与查询。

### Non-MVP (延期)
- Dashboard 可视化页面。
- 新闻 NLP 摘要与 AI 自然语言解释增强。
- 跨资产统一因子回归优化。

---

## 2) 评分公式统一 (修复 v1.0 公式歧义)

v1.0 同时描述了 `Quality_Modifier` 作为“乘数”与“加项”，存在冲突。v1.1 统一为“乘数修正”。

### 2.1 单层原始得分
- `Valuation_Raw = Σ(indicator_score_i * indicator_weight_i)`
- `Momentum_Raw = Σ(indicator_score_j * indicator_weight_j)`
- 各指标 `indicator_score ∈ {-2, -1, 0, +1, +2}`。
- 各层权重和固定为 `100%`。

### 2.2 层内归一化到 [-10, +10]
- `Layer_Score = clip(10 * Raw / Raw_MaxAbs, -10, +10)`
- `Raw_MaxAbs = Σ(2 * weight_i)` (权重按 0~1 小数参与计算)。

### 2.3 综合分
- `Base_Composite = 0.35 * Valuation_Score + 0.40 * Momentum_Score`
- `Quality_Factor` 定义:
  - `Pass -> 1.0`
  - `Warning -> 0.7`
  - `Fail -> 0.0` (直接屏蔽)
- `Composite_Score = clip(Base_Composite * Quality_Factor, -10, +10)`

### 2.4 质量层一票否决
- `audit_opinion = 否定` -> `Quality_Status = Fail`
- `Altman_Z < 1.8` -> `Quality_Status = Fail`
- 触发 Fail 时: 强制 `is_tradeable = false`。

---

## 3) 标签与仓位修正规范 (可执行口径)

### 3.1 价值标签映射
- `+6 ~ +10`: Strong Undervalued
- `+2 ~ +5`: Undervalued
- `-1 ~ +1`: Neutral
- `-5 ~ -2`: Overvalued
- `-10 ~ -6`: Severe Overvalued

### 3.2 仓位修正曲线 (MVP 固定分段)
- `position_modifier` 先采用分段函数, 回测后再替换为连续曲线:
  - `score >= +6 -> 1.50`
  - `+2 <= score < +6 -> 1.20`
  - `-1 <= score < +2 -> 1.00`
  - `-5 <= score < -1 -> 0.60`
  - `score < -5 -> 0.00`

### 3.3 与现有仓位系统对接
- 实际仓位上限:
  - `effective_max_units = floor(base_max_units * position_modifier)`
  - 最小值保护: `effective_max_units >= 0`
- 对齐现有仓位入口:
  - `llm_server_v3640.py:40164` (`get_max_position_units`)。

---

## 4) API 合同补丁 (异步批量可落地)

### 4.1 单股分析
- `POST /api/value/analyze/{ticker}`
- 同步返回:
  - `ticker, as_of, valuation_score, momentum_score, quality_status, composite_score, position_modifier, is_tradeable, missing_fields, alerts`

### 4.2 批量分析 (异步)
- `POST /api/value/batch`
- 请求:
```json
{
  "tickers": ["AAPL", "MSFT", "NVDA"],
  "mode": "full",
  "priority": "normal",
  "force_refresh": false
}
```
- 立即返回:
```json
{
  "job_id": "val_20260216_0001",
  "status": "queued",
  "accepted": 3,
  "rejected": 0
}
```

### 4.3 任务状态
- `GET /api/value/batch/{job_id}`
- 状态机: `queued -> running -> partial_success|success|failed|timeout`。
- 字段: `progress_pct, finished_count, failed_count, retry_count, started_at, ended_at`。

### 4.4 幂等与重试
- 批量接口支持 `idempotency_key`。
- 单 ticker 失败可重试, 最大 `retry=2`。
- 超时策略:
  - 单 ticker > 30s -> timeout
  - 批任务 > 10min -> timeout

---

## 5) 数据与配额预算补丁

### 5.1 配额预算 (按 FMP 免费版 250/day)
- 默认预算拆分:
  - `70%` 用于持仓池和观察池
  - `20%` 用于新增候选
  - `10%` 用于重试与异常
- 超预算降级顺序:
  1. 禁止非持仓候选全量分析
  2. 仅更新估值层关键指标
  3. 延迟到下个窗口

### 5.2 缓存口径
- 财报类: `TTL=7d` (财报更新慢)
- 估值行情类: `TTL=24h`
- 分析师预期/新闻: `TTL=6h`
- 缓存命中必须返回 `data_freshness` 字段。

### 5.3 缺失数据规则
- 若缺失比例 `missing_ratio > 40%`: `analysis_status=degraded`。
- 若 Quality 关键字段缺失且无法判定一票否决项: `quality_status=Warning` 并增加 `DATA_QUALITY_WARN` 警报。

---

## 6) 调度触发规范 (事件+定时去重)

### 6.1 触发优先级
- P0: 财报发布后 24h 内全量分析
- P1: 持仓池每周末重算
- P2: 单日涨跌超过 5% 的快速重算

### 6.2 去重键
- `dedup_key = ticker + trigger_type + as_of_date`
- 同一去重键 6h 内只执行一次 (可配置)。

### 6.3 结果持久化
- 每次分析都写入历史:
  - `ticker, as_of, layer_scores, composite_score, quality_status, missing_ratio, trigger_type`

---

## 7) 与现有代码的挂点建议 (基于当前仓库)

以下挂点基于仓库现有结构证据:
- `llm_server_v3640.py:40164` 已有仓位上限入口 (`get_max_position_units`)。
- `llm_server_v3640.py:40604` 有统一参数读取模式 (`get_timeframe_params`) 可复用为 value 参数读取范式。
- `llm_server_v3640.py:7026` 已有 symbol 级 YAML 参数读取范式 (`load_symbol_params`)。

### 7.1 建议新增模块
- 目录建议保持 PRD 方案:
  - `value_analysis/engine.py`
  - `value_analysis/valuation.py`
  - `value_analysis/momentum.py`
  - `value_analysis/quality.py`
  - `value_analysis/composite.py`
  - `value_analysis/data_fetcher.py`
  - `value_analysis/config.py`

### 7.2 配置建议
- 参考现有 `.GCC/params/{SYMBOL}.yaml` 模式, 新增:
  - `.GCC/value_params/{SYMBOL}.yaml`
- 字段建议:
  - `valuation_weights`
  - `momentum_weights`
  - `quality_thresholds`
  - `position_curve`

---

## 8) 验收标准补丁 (可测试、可自动化)

### 8.1 功能验收
- 单股接口返回结构完整率 `100%` (允许字段值为 `null`, 但 key 不缺失)。
- 批量 50 ticker: 成功率 `>= 95%`, 且无进程崩溃。
- Quality Fail 股票必须 `is_tradeable=false`。

### 8.2 计算一致性验收
- 抽样 20 ticker 人工复核:
  - 层分误差 `<= 1e-6`
  - 综合分误差 `<= 1e-6`

### 8.3 回测验收口径固定
- 样本区间: 最近 5 年美股日频。
- 调仓频率: 周频。
- 因变量: 未来 6 个月收益。
- 指标: 截面 IC 均值 `>= 0.05`。
- 必须输出: 分行业 IC、按市值分层 IC、滚动 12M IC 稳定性。

---

## 9) 未决项 (必须在开发前拍板)

- 数据源主备: FMP / Yahoo / AlphaVantage 的优先级与冲突仲裁规则。
- 美股与加密货币是否同一期上线; 若分期, 建议美股先行。
- `position_modifier` 是否允许覆盖现有风控硬限制 (建议: 不允许覆盖硬限制)。
- 异步批量任务使用现有队列还是新建 worker。

---

## 10) 默认决策建议 (若无额外指令)

- 先交付美股 MVP, 暂不启用加密货币替代估值。
- 先实现 API + 引擎 + 持久化, Dashboard 延后。
- 先用分段 `position_modifier`, 回测稳定后再改连续曲线。
- 先以 `Warning=0.7` 执行 2 周观察, 再考虑调整到 0.8/0.6。

---

END
