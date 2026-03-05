# gcc-evo 五层架构详解

> 完整的五层框架设计、实现逻辑和数据流转说明

---

## 目录

1. [架构概览](#架构概览)
2. [L1：记忆层](#l1记忆层)
3. [L2：检索层](#l2检索层)
4. [L3：蒸馏层](#l3蒸馏层)
5. [L4：决策层](#l4决策层)
6. [L5：编排层](#l5编排层)
7. [层间协作](#层间协作)
8. [实现指南](#实现指南)

---

## 架构概览

### 为什么是五层？

gcc-evo 的五层架构并非凭空设计，而是对以下问题的系统回答：

1. **L1 记忆层** — "AI 怎样跨会话记住信息？"
   - 传统方案：每次拼接完整历史（Token爆炸）
   - gcc-evo 方案：三级分层存储，按需检索

2. **L2 检索层** — "怎样快速找到相关信息？"
   - 传统方案：全文搜索或随机采样（低准确度）
   - gcc-evo 方案：三种方法融合（语义+时间+关键词）

3. **L3 蒸馏层** — "怎样让 AI 学习自身经验？"
   - 传统方案：没有蒸馏机制（经验丢失）
   - gcc-evo 方案：自动提炼规则入库（持续进化）

4. **L4 决策层** — "怎样防止 AI 幻觉写入记忆？"
   - 传统方案：无验证（错误传播）
   - gcc-evo 方案：Skeptic 门控 + 人工验证

5. **L5 编排层** — "怎样自动化整个改善过程？"
   - 传统方案：手工脚本（易出错）
   - gcc-evo 方案：DAG 调度 + Loop 闭环

### 五层的关系图

```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃  L5: 编排层 (Orchestration)            ┃
┃  ├─ 6步闭环：Observe→Audit→Extract→... ┃
┃  ├─ DAG任务调度                        ┃
┃  └─ Loop自动化运行                     ┃
┗━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┛
                 │ (调度任务 + 执行指令)
┏━━━━━━━━━━━━━━━━┻━━━━━━━━━━━━━━━━━━━━━┓
┃  L4: 决策层 (Decision Making)         ┃
┃  ├─ LLM 推理                          ┃
┃  ├─ Skeptic 门控                      ┃
┃  └─ Human-in-the-Loop 验证             ┃
┗━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┛
                 │ (推理请求 + 验证指令)
┏━━━━━━━━━━━━━━━━┻━━━━━━━━━━━━━━━━━━━━━┓
┃  L3: 蒸馏层 (Distillation)            ┃
┃  ├─ 经验卡 → SkillBank                ┃
┃  ├─ 自动版本管理                      ┃
┃  └─ 准确率追踪                        ┃
┗━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┛
                 │ (规则查询 + 蒸馏指令)
┏━━━━━━━━━━━━━━━━┻━━━━━━━━━━━━━━━━━━━━━┓
┃  L2: 检索层 (Retrieval)               ┃
┃  ├─ 语义相似度 (50%)                  ┃
┃  ├─ KNN 时间加权 (30%)                ┃
┃  └─ BM25 关键词 (20%)                 ┃
┗━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┛
                 │ (查询请求)
┏━━━━━━━━━━━━━━━━┻━━━━━━━━━━━━━━━━━━━━━┓
┃  L1: 记忆层 (Memory)                  ┃
┃  ├─ Sensory (24h)                     ┃
┃  ├─ Short-term (7d)                   ┃
┃  └─ Long-term (∞)                     ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
```

---

## L1：记忆层

### 设计理念

**问题**：LLM 的 Token 上下文有限（Claude-3.5: 200K），如何跨会话记住信息？

**核心方案**：三级分层 + 自动生命周期管理

### 三级分层设计

#### Sensory Layer (感知层) — 24小时窗口

**职责**：存储最新的原始观察和事件

```
时间线:
  Now:        ← 新事件写入 (自动标记时间戳)
  1h ago:     ← 1小时前的观察
  12h ago:    ← 12小时前的决策记录
  23h 59m:    ← 即将过期 (保持最新状态)
  24h 1m:     ← 自动清理（永久删除）
```

**数据类型**：
- Raw logs（原始日志）: 交易执行、API调用、错误记录
- Events（事件）: 系统发生了什么
- Observations（观察）: AI看到了什么

**存储结构**：
```python
{
  "timestamp": 1709476800,        # Unix时间戳
  "event_type": "trade_executed", # 事件类型
  "symbol": "TSLA",              # 上下文信息
  "price": 145.50,
  "data": {...},                 # 原始数据
  "expires_at": 1709563200       # 24h后自动删除
}
```

**访问特点**：
- ✅ 高频写入（秒级）
- ✅ 快速查询（索引访问）
- ❌ 不参与 RAG 检索（太新鲜，上下文不足）
- ✅ 用于最近状态快照

---

#### Short-term Layer (短期层) — 7天窗口

**职责**：存储最近的决策、讨论历史和上下文

```
时间线:
  Now:        ← 今天的决策
  1d ago:     ← 昨天的讨论
  3d ago:     ← 3天前的改进尝试
  6d 23h:     ← 即将压缩（仍可检索）
  7d:         ← 过期触发压缩到 Long-term
```

**数据类型**：
- Decision records（决策记录）: "提议了什么" + "理由是什么"
- Discussion context（讨论上下文）: 问答对话
- Insights（见解）: AI的分析结果

**存储结构**：
```python
{
  "task_id": "GCC-0001",
  "decision": "Reduce MACD threshold from 0.8 to 0.7",
  "reasoning": "False signals increased in tight ranges",
  "confidence": 0.82,
  "timestamp": 1709390400,
  "related_observations": ["obs-123", "obs-456"],
  "metadata": {
    "model": "claude-3.5",
    "temperature": 0.7
  }
}
```

**访问特点**：
- ✅ 中频写入（分钟级）
- ✅ 语义搜索（embedding索引）
- ✅ 时间加权（最近数据权重更高）
- ✅ 用于 RAG 上下文

---

#### Long-term Layer (长期层) — 永久存储

**职责**：存储已验证的规则和技能库

```
时间线:
  v1: SK-001 (2026-01-15)  ← 初版规则（准确率 72%）
  v2: SK-001 (2026-02-10)  ← 改进版（准确率 81%）
  v3: SK-001 (2026-03-01)  ← 当前版（准确率 87%）
  ...永久保存（可查询历史版本）
```

**数据类型**：
- Verified rules（已验证规则）：经过人工或多次验证
- Experience cards（经验卡）：可复用的知识单元
- SkillBank（技能库）：版本化的技能集合

**存储结构**：
```python
{
  "skill_id": "SK-001",
  "name": "MACD_Threshold_Adaptation",
  "description": "When price range tight, increase threshold",
  "pattern": "If volatility_percent < 2% then threshold += 0.1",
  "version": 3,
  "history": [
    {"v": 1, "accuracy": 0.72, "created": "2026-01-15"},
    {"v": 2, "accuracy": 0.81, "created": "2026-02-10"},
    {"v": 3, "accuracy": 0.87, "created": "2026-03-01"}
  ],
  "status": "active",  # active | deprecated | experimental
  "use_count": 145,
  "success_count": 126,
  "last_used": 1709476800
}
```

**访问特点**：
- ✅ 低频写入（验证通过时）
- ✅ 精确查询（ID/版本查询）
- ✅ 不可变存档（历史记录永久保存）
- ✅ 用于规则库和知识检索

### 生命周期管理

```
Sensory → Short-term → Long-term
   24h        7d         ∞

转移条件：
- Sensory → Short-term: 人工确认或自动升级（重要度 > 0.7）
- Short-term → Long-term: 通过 Skeptic 验证（confidence >= 0.75）
- Short-term 过期: 7天后自动删除（或压缩摘要）
- Long-term 维护: 版本化管理，支持废弃但不删除
```

### 实现细节

**存储后端选择**：
```python
# 选项1: 文件系统（开发用）
state/
├── sensory.jsonl      # 最新事件流（追加式）
├── short_term.json    # 7天内决策（定期紧缩）
└── long_term/
    ├── skillbank.jsonl
    ├── rules.json
    └── history/

# 选项2: SQLite（单机生产）
memory.db
├── table: sensory_events
├── table: short_term_decisions
├── table: long_term_skills
└── indices: timestamp, task_id, skill_id

# 选项3: Redis（高并发）
redis:
  SENSORY:{timestamp}  → 原始事件
  SHORT_TERM:{task_id} → 决策记录
  LONG_TERM:SK-{id}    → 技能库
```

**过期管理实现**：
```python
class MemoryTier:
    def cleanup_expired(self):
        """每小时执行一次"""
        now = time.time()
        for item in self.sensory:
            if now - item['timestamp'] > 86400:  # 24 hours
                self.sensory.delete(item)

        for item in self.short_term:
            if now - item['timestamp'] > 604800:  # 7 days
                # 生成摘要或转移到 long_term
                summary = self.summarize(item)
                self.long_term.add(summary)
                self.short_term.delete(item)
```

---

## L2：检索层

### 设计理念

**问题**：从几千条记录中快速找到相关的 5-10 条，用什么方法？

**核心方案**：三种方法加权融合（不依赖单一策略）

### 三种检索方法

#### 方法1：语义相似度 (50% 权重)

**原理**：用 embedding 模型计算语义距离

```
查询：  "我想减少假信号"
       ↓ embedding
      [0.45, -0.23, 0.87, ...]  (768维向量)

记忆库中的文本：
1. "减少虚假信号的方法" → 相似度 0.89 ✓✓✓ (最相关)
2. "MACD 阈值调整"     → 相似度 0.76 ✓✓
3. "交易频率控制"      → 相似度 0.42 ✓
4. "风险管理规则"      → 相似度 0.35 ✗
```

**实现方式**：
```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer('all-MiniLM-L6-v2')

# 索引时
for memory in memories:
    memory['embedding'] = model.encode(memory['text'])
    save_to_index(memory)

# 检索时
query_vector = model.encode(query)
results = index.search(query_vector, top_k=10)
# 返回：[(memory_id, similarity_score), ...]
```

**优点**：
- ✅ 捕捉语义关系（"信号质量" ≈ "准确率"）
- ✅ 鲁棒性好（不怕表述不同）

**缺点**：
- ❌ 忽视时间信息（旧规则和新观察等权重）
- ❌ 计算成本高（embedding 模型推理）

---

#### 方法2：时间加权 (KNN, 30% 权重)

**原理**：最近的数据更相关，按时间衰减加权

```
时间权重曲线：
现在     ← 权重 1.0
1天前   ← 权重 0.95
3天前   ← 权重 0.80
7天前   ← 权重 0.50
14天前  ← 权重 0.10  (已失效)

计算：
相似度分数 = 基础相似度 × 时间权重
例如：
  记录A: 基础相似度 0.75, 时间权重 1.0 → 最终 0.75
  记录B: 基础相似度 0.80, 时间权重 0.3 → 最终 0.24
```

**实现方式**：
```python
def temporal_weight(timestamp, half_life_hours=24):
    """
    计算指数衰减权重
    half_life: 权重降至50%的时间
    """
    age_hours = (time.time() - timestamp) / 3600
    return math.exp(-0.693 * age_hours / half_life_hours)

# 检索时应用
results = []
for memory in candidates:
    semantic_score = 0.89  # 从语义搜索得到
    temporal_score = temporal_weight(memory['timestamp'])
    final_score = semantic_score * temporal_score
    results.append((memory, final_score))
```

**优点**：
- ✅ 反映数据新鲜度（避免陈旧结论）
- ✅ 计算简单快速

**缺点**：
- ❌ 新但无关的数据可能排名高
- ❌ 忽视内容精确度

---

#### 方法3：BM25 关键词匹配 (20% 权重)

**原理**：精确匹配关键字的经典算法（搜索引擎用）

```
查询：["MACD", "阈值", "调整"]

记忆文本：
1. "MACD 阈值从 0.8 调整到 0.7"
   匹配关键词数: 3/3 (100%) → 得分 1.0 ✓✓✓

2. "MACD 指标说明"
   匹配关键词数: 1/3 (33%) → 得分 0.33 ✓

3. "收益风险比计算"
   匹配关键词数: 0/3 (0%) → 得分 0.0 ✗
```

**实现方式**：
```python
from rank_bm25 import BM25Okapi

# 索引时
corpus = [memory['text'] for memory in memories]
bm25 = BM25Okapi([doc.split() for doc in corpus])

# 检索时
query_tokens = query.split()
bm25_scores = bm25.get_scores(query_tokens)
# 返回：[score_1, score_2, score_3, ...]
```

**优点**：
- ✅ 精确匹配效果好
- ✅ 计算快速，占用内存少
- ✅ 对特定领域词汇敏感

**缺点**：
- ❌ 忽视语义（"减少虚假" ≠ "降低错误率"）
- ❌ 需要词汇处理（分词、去停用词）

---

### 混合检索的融合

```
Step 1: 执行三种搜索
├─ 语义搜索   → [0.89, 0.76, 0.42, 0.35, ...]
├─ 时间加权   → [1.00, 0.95, 0.80, 0.50, ...]
└─ BM25搜索   → [1.00, 0.50, 0.30, 0.05, ...]

Step 2: 正规化（都转换到 0-1 范围）
├─ 语义:  max_normalize([0.89, 0.76, ...])
├─ 时间:  已经是 0-1
└─ BM25:  max_normalize([1.00, 0.50, ...])

Step 3: 加权融合（50% + 30% + 20%）
最终得分 = 语义*0.5 + 时间*0.3 + BM25*0.2

Step 4: 排序 + 返回 top-k
```

**Python 实现**：
```python
class HybridRetriever:
    def __init__(self, weights=(0.5, 0.3, 0.2)):
        self.w_semantic, self.w_temporal, self.w_keyword = weights

    def search(self, query, top_k=5):
        # 1. 三种搜索
        semantic_results = self.semantic_search(query)
        temporal_results = self.temporal_search(query)
        keyword_results = self.keyword_search(query)

        # 2. 融合分数
        all_ids = set(semantic_results.keys() |
                      temporal_results.keys() |
                      keyword_results.keys())

        final_scores = {}
        for memory_id in all_ids:
            score = (
                semantic_results.get(memory_id, 0) * self.w_semantic +
                temporal_results.get(memory_id, 0) * self.w_temporal +
                keyword_results.get(memory_id, 0) * self.w_keyword
            )
            final_scores[memory_id] = score

        # 3. 排序返回
        ranked = sorted(final_scores.items(),
                       key=lambda x: x[1],
                       reverse=True)
        return [self.memory_store[mid] for mid, _ in ranked[:top_k]]
```

---

## L3：蒸馏层

### 设计理念

**问题**：如何让 AI 从经验中学习，而不是每次都从零开始？

**核心方案**：自动提炼规则 + 版本化管理 + 准确率追踪

### 三个阶段的蒸馏过程

#### 阶段1：观察 → 经验卡

**输入**：一次交互的完整上下文

```
观察示例：
{
  "timestamp": 1709476800,
  "context": "TSLA 在 10:30 触发 MACD 信号",
  "observation": "MACD 背离出现在高位，但随后假突破",
  "action_taken": "没有下单，躲避了损失",
  "outcome": "避免亏损 $500",
  "model": "claude-3.5",
  "confidence": 0.85
}
```

**提炼过程（LLM）**：
```
LLM Prompt:
"从以下观察中提炼一条可复用的规则：
观察: {observation}
结果: {outcome}

返回JSON格式的经验卡，包含：
- pattern (发现的模式)
- condition (触发条件)
- action (推荐动作)
- confidence (你的置信度)"

LLM 回复:
{
  "pattern": "MACD高位背离 → 假突破概率高",
  "condition": "当 MACD 在相对高位出现背离且价格创新高",
  "action": "等待确认，不急于下单",
  "confidence": 0.87
}
```

**输出**：经验卡（结构化知识单元）

---

#### 阶段2：经验卡 → 技能规则

**输入**：累积的多条经验卡

```
多条经验卡：
1. MACD高位背离 → 假突破
2. RSI极端值 → 反向概率高
3. 布林带接近上轨 → 回调可能性大
...
```

**合成过程（LLM）**：
```
LLM Prompt:
"我有以下经验卡关于虚假信号识别：
[列出所有经验卡]

请合成一条通用规则，涵盖这些模式的共同点"

LLM 回复:
{
  "skill_id": "SK-001",
  "name": "False_Signal_Detection",
  "description": "在趋势起始阶段识别假突破",
  "rule": "多个指标同时极端 + 价格接近关键位 = 反转概率高",
  "applicability": "适用于日线及以上级别",
  "success_rate": 0.82,
  "exceptions": ["极强趋势日、重大事件日"]
}
```

**输出**：技能规则（可复用的高级知识）

---

#### 阶段3：技能规则 → SkillBank（版本管理）

**概念**：技能库是有版本历史的规则集合

```
SK-001 演进历程：

v1 (2026-01-15):
  规则: "MACD高位背离 → 假突破"
  准确率: 72%
  样本: 45个
  评论: "基础版本，假阳性较多"

v2 (2026-02-10):
  规则: "MACD背离 + RSI极端 → 假突破"
  准确率: 81%
  样本: 120个
  变化: "加入RSI确认，减少误判"

v3 (2026-03-01):  ← 当前版本
  规则: "MACD背离 + RSI极端 + 接近支撑阻力 → 假突破"
  准确率: 87%
  样本: 250个
  变化: "加入价格位置过滤，进一步提升"
```

**版本管理规则**：
```
新规则提交时的检查清单：
✓ 规则描述清晰（5句话以内）
✓ 触发条件可编程（不是模糊的）
✓ 基于数据验证（不是直觉）
✓ 样本数 >= 30 (统计显著性)
✓ 准确率 >= 上一版本 - 5% (避免倒退)

通过检查后：
1. 创建新版本 (v_old + 1)
2. 标记 old version 为 deprecated
3. 在 SkillBank 中激活新版本
4. 记录变更日志
```

---

## L4：决策层

### 设计理念

**问题**：LLM 可能输出错误的决策，怎样防止错误写入记忆？

**核心方案**：Skeptic 门控 + 人工验证 + 多模型对比

### Skeptic 防幻觉机制

#### 置信度计算

```
决策的置信度由三部分组成：

confidence = (accuracy_history * 0.4) +
             (current_reasoning * 0.4) +
             (human_anchor * 0.2)

1. accuracy_history (40%):
   - 这个模型过去多准？
   - 在类似任务上的成功率
   - 数据来源: 历史决策记录

2. current_reasoning (40%):
   - 这次推理有多充分？
   - 证据充足吗？
   - 是否考虑了反面案例？
   - 数据来源: LLM 自己的推理过程

3. human_anchor (20%):
   - 有没有人工验证？
   - 验证的详细度
   - 数据来源: 人工标注
```

#### 门控规则

```python
class SkepticGate:
    THRESHOLD = 0.75  # 可配置

    def verify(self, decision):
        confidence = self.calculate_confidence(decision)

        if confidence >= self.THRESHOLD:
            return True, "APPROVED"  # 写入记忆
        elif confidence >= 0.6:
            return None, "REQUIRES_REVIEW"  # 请求人工
        else:
            return False, "REJECTED"  # 拒绝
```

**三种决策结果**：

| 置信度 | 处理方式 | 说明 |
|--------|---------|------|
| >= 0.75 | ✅ 自动通过 | 写入 Short-term 层 |
| 0.60-0.75 | ⚠️ 人工审核 | 等待人工确认 |
| < 0.60 | ❌ 拒绝 | 不写入记忆，建议重新推理 |

---

#### 多模型对比

**策略**：在重要决策时，用多个 LLM 对比

```python
def multi_model_decision(task, models=['claude', 'gpt', 'gemini']):
    """
    用多个模型独立推理，对比结果
    """
    decisions = {}
    confidences = {}

    for model_name in models:
        model = get_model(model_name)

        # 独立推理
        decision = model.reason(task)
        confidence = model.get_confidence()

        decisions[model_name] = decision
        confidences[model_name] = confidence

    # 分析一致性
    consensus = check_consensus(decisions)  # 模型是否同意?
    avg_confidence = sum(confidences.values()) / len(models)

    # 一致性高 → 置信度增加
    # 一致性低 → 需要人工审查
    if consensus and avg_confidence > 0.75:
        return "APPROVED", avg_confidence
    else:
        return "REQUIRES_REVIEW", avg_confidence
```

**示例**：
```
任务: "TSLA 在 $145 应该下单吗？"

Claude-3.5 回答:
  决策: "建议等待，可能还有下行空间"
  置信度: 0.82
  理由: "RSI还在50-60区间，不是极端"

GPT-4 回答:
  决策: "可以小额建仓"
  置信度: 0.68
  理由: "从月线看，这是支撑位"

Gemini 回答:
  决策: "等待，不建议现在下单"
  置信度: 0.79
  理由: "MACD未确认，风险不值"

分析:
- 一致性: Claude + Gemini 同意 (66%)
- 平均置信度: 0.76
- 结论: 通过 Skeptic 门控 ✅
  (一致性中等 + 置信度足够)
```

---

## L5：编排层

### 设计理念

**问题**：6步改善流程怎样自动化执行，而不是手工操作？

**核心方案**：DAG 任务调度 + Loop 自动化 + 6步闭环

### 6步 Loop 闭环

```
Step 1: OBSERVE (观察)
  ├─ 收集最近的日志
  ├─ 提取关键事件
  └─ 识别异常信号
         ↓

Step 2: AUDIT (审计)
  ├─ 分析日志中的问题
  ├─ 统计关键指标
  └─ 识别改善机会
         ↓

Step 3: EXTRACT (提炼)
  ├─ 从问题中提炼规则
  ├─ 生成经验卡
  └─ 合成技能
         ↓

Step 4: VERIFY (验证)
  ├─ Skeptic 置信度检查
  ├─ 请求人工审核（if needed）
  └─ 多模型对比（if 重要决策）
         ↓

Step 5: DISTILL (蒸馏)
  ├─ 通过验证的规则写入 SkillBank
  ├─ 更新版本号
  └─ 记录准确率基线
         ↓

Step 6: REPORT (报告)
  ├─ 生成本轮总结
  ├─ 列出待验证项
  └─ 建议下轮改善方向
```

### DAG 任务调度

**概念**：用有向无环图表示任务依赖关系

```
    ┌─────────────┐
    │  OBSERVE    │ (收集日志)
    └──────┬──────┘
           │
    ┌──────▼──────┐
    │   AUDIT     │ (分析问题)
    └──────┬──────┘
           │
    ┌──────▼──────┐
    │  EXTRACT    │ (提炼规则)
    └──────┬──────┘
           │
    ┌──────▼──────┐
    │  VERIFY     │ (验证)
    └──┬──────┬───┘
       │      │
  ┌────▼─┐  ┌─▼──────┐
  │PASS  │  │FAIL    │
  │      │  │REQUIRE │
  │      │  │REVIEW  │
  └────┬─┘  └─┬──────┘
       │      │ (人工输入)
       └──┬───┘
          │
    ┌─────▼──────┐
    │  DISTILL   │ (写入SkillBank)
    └─────┬──────┘
          │
    ┌─────▼──────┐
    │   REPORT   │ (生成报告)
    └────────────┘
```

**实现**：
```python
class LoopEngine:
    def __init__(self, task_id):
        self.task_id = task_id
        self.dag = self.build_dag()

    def build_dag(self):
        """构建任务依赖图"""
        dag = {
            'observe': {
                'deps': [],
                'executor': self.observe
            },
            'audit': {
                'deps': ['observe'],
                'executor': self.audit
            },
            'extract': {
                'deps': ['audit'],
                'executor': self.extract
            },
            'verify': {
                'deps': ['extract'],
                'executor': self.verify
            },
            'distill': {
                'deps': ['verify'],
                'executor': self.distill
            },
            'report': {
                'deps': ['distill'],
                'executor': self.report
            }
        }
        return dag

    def run_once(self):
        """执行一次完整循环"""
        results = {}
        executed = set()

        while len(executed) < len(self.dag):
            for task_name, task_config in self.dag.items():
                if task_name in executed:
                    continue

                # 检查依赖是否都满足
                if not all(dep in executed for dep in task_config['deps']):
                    continue

                # 执行任务
                try:
                    result = task_config['executor'](results)
                    results[task_name] = result
                    executed.add(task_name)
                except Exception as e:
                    print(f"Task {task_name} failed: {e}")
                    return results

        return results
```

### 持续运行的 Loop

```bash
# 一次性运行
gcc-evo loop GCC-0001 --once
# 输出: 单次 Loop 结果

# 持续运行 (5分钟循环)
gcc-evo loop GCC-0001
# 等同于:
while True:
    run_once()
    sleep(300)  # 5 minutes
    if should_stop():
        break
```

---

## 层间协作

### 完整的数据流

```
输入: 新的观察事件
  │
  ├─→ [L5] LoopEngine.observe()
  │        读取日志，获取最近事件
  │
  ├─→ [L1] 存储到 Sensory 层
  │        memory.sensory.record(event)
  │
  ├─→ [L5] LoopEngine.audit()
  │        分析问题
  │
  ├─→ [L2] HybridRetriever.search()
  │        找到相关历史记录
  │   └─→ [L1] 从 Short-term 和 Long-term 读取
  │
  ├─→ [L5] LoopEngine.extract()
  │        提炼规则
  │
  ├─→ [L4] SkepticGate.verify()
  │        计算置信度
  │   └─→ (if confidence < 0.75) 请求人工审核
  │
  ├─→ [L5] LoopEngine.distill()
  │        (if 验证通过)
  │
  ├─→ [L3] Distiller.extract_skill()
  │        从观察生成经验卡
  │
  ├─→ [L3] SkillBank.add_skill()
  │        存储到技能库
  │
  ├─→ [L1] memory.long_term.add_skill()
  │        写入 Long-term 层
  │
  ├─→ [L1] memory.short_term.store()
  │        更新 Short-term (决策记录)
  │
  ├─→ [L5] LoopEngine.report()
  │        生成报告
  │
  └─→ 输出: 决策 + 报告

时间轴:
  观察 (秒级)
    ↓ (Sensory → Short-term, 分钟级)
  决策 (秒级)
    ↓ (验证, 秒-分钟级)
  蒸馏 (秒级)
    ↓ (记忆更新, 秒级)
  下轮循环 (5分钟后)
```

### 跨层的数据结构

```
Event (观察的最小单位)
  ├─ timestamp
  ├─ event_type
  ├─ symbol (上下文)
  └─ data (原始信息)

Decision (决策记录)
  ├─ task_id
  ├─ decision (具体决策)
  ├─ confidence (置信度)
  ├─ reasoning (推理过程)
  └─ verified_by (人工/模型)

Experience Card (经验卡)
  ├─ pattern (发现的模式)
  ├─ condition (触发条件)
  ├─ action (推荐行动)
  └─ confidence (规则自信度)

Skill (技能规则)
  ├─ skill_id
  ├─ name
  ├─ rule (文字表述)
  ├─ version
  ├─ accuracy (历史准确率)
  └─ history (版本演进)
```

---

## 实现指南

### 最小化实现（MVP）

如果要快速原型，最少需要：

```python
# L1: 记忆 - 最小化
import json
from datetime import datetime, timedelta

class SimpleMemory:
    def __init__(self):
        self.sensory = []      # 最近事件
        self.short_term = []   # 决策
        self.long_term = {}    # 规则库

    def record(self, event):
        """记录事件"""
        self.sensory.append({
            'timestamp': datetime.now().isoformat(),
            'data': event
        })
        self._cleanup_sensory()

    def _cleanup_sensory(self):
        """删除24h前的数据"""
        cutoff = datetime.now() - timedelta(hours=24)
        self.sensory = [
            e for e in self.sensory
            if datetime.fromisoformat(e['timestamp']) > cutoff
        ]

# L2: 检索 - 最小化
class SimpleRetriever:
    def search(self, query, memory, top_k=5):
        """简单的关键词匹配"""
        results = []
        for item in memory.short_term:
            if query.lower() in str(item).lower():
                results.append(item)
        return results[:top_k]

# L4: 决策 - 最小化
class SimpleSkeptic:
    THRESHOLD = 0.75

    def verify(self, decision, confidence):
        """简单的门控"""
        if confidence >= self.THRESHOLD:
            return True
        else:
            return False  # 需要人工

# L5: 编排 - 最小化
class SimpleLoop:
    def run_once(self):
        # 1. 观察
        events = self.get_events()

        # 2. 审计
        problems = self.analyze(events)

        # 3. 提炼
        rule = self.extract_rule(problems)

        # 4. 验证
        if self.skeptic.verify(rule, confidence=0.8):
            # 5. 蒸馏
            self.skillbank.add(rule)

        # 6. 报告
        return self.generate_report()
```

### 逐步增强

```
v1 (MVP):
  - 基础三层记忆 (file-based)
  - 关键词检索
  - 简单 Skeptic 门控
  - 单模型推理

v2 (增强):
  - 加入 embedding 语义搜索
  - 加入时间加权
  - 混合检索 (3方融合)
  - 人工验证界面

v3 (完整):
  - SQLite 存储后端
  - 多模型对比
  - 完整版本管理
  - 性能优化 (缓存/索引)

v4 (生产):
  - Redis 分布式存储
  - 微服务架构
  - 实时监控和告警
  - Enterprise 功能
```

---

## 总结

gcc-evo 的五层架构解决的核心问题：

| 问题 | 解决方案 | 关键指标 |
|------|---------|---------|
| Token 窗口限制 | L1 三层分层 | 20倍上下文扩展 |
| 检索准确度 | L2 混合检索 | 命中率 > 85% |
| 知识积累 | L3 蒸馏+版本管理 | 技能库增长 |
| 防止幻觉 | L4 Skeptic门控 | 错误拦截率 > 95% |
| 自动化执行 | L5 Loop闭环 | 0-touch 改善周期 |

**下一步**：选择实现级别，开始原型开发！

---

**[English](ARCHITECTURE.en.md) | [中文](ARCHITECTURE.md)**
