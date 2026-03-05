# gcc-evo — AI 自进化引擎 v5.295

> **突破 AI 20 万 Token 窗口限制，让 AI 真正记住过去、持续进化**

---

## 背景

这个项目的起点，不是一个宏大的计划。

我厌倦了天天盯着 K 线图，于是花了三个月写了一套不用人工看盘的自动化交易软件。软件跑起来了，但随之而来的是一堆 bug——改 bug 比看 K 线还麻烦。

为了系统性地追踪和修复这些问题，我顺手写了一个辅助工具：记录每个问题、跟踪修复过程、验证结果。

恰好这段时间，有个客户找我协助解决他们激光切割机的生产问题。上门拜访时，我随口提了这个"AI 辅助改善"的工具。客户非常感兴趣，当场让我试试能不能用在他们的工业场景上。

两周后，**gcc-evo** 的雏形诞生了。

---

## 它解决什么问题

用过 AI 的人都遇到过这个问题：**AI 没有长期记忆**。你今天和它谈的改善方案，明天它全忘了。每次对话都要重新解释背景，效率极低。

gcc-evo 的核心目标只有一个：

**让 AI 在多轮会话、多个模型之间，真正记住发生了什么，并持续朝着目标进化。**

不是靠堆 prompt，而是靠一套结构化的记忆+检索+蒸馏+验证闭环。

---

## 五层框架架构

### 整体架构图

```
┌──────────────────────────────────────────────────────────────────┐
│                         应用层 (User)                             │
│                   gcc-evo loop / commands                        │
└──────────────────────────┬───────────────────────────────────────┘
                           │
┌──────────────────────────▼────────────────────────────────────────┐
│  Layer 5: 编排层 (Orchestration)                                  │
│  ┌──────────────────────────────────────────────────────────────┐│
│  │  Loop闭环引擎 (6步自动化)：                                    ││
│  │  Observe → Audit → Extract → Verify → Distill → Report      ││
│  │                                                              ││
│  │  Pipeline DAG调度 / Task依赖管理 / 重试逻辑                   ││
│  │  模块: pipeline.py, loop_engine.py                           ││
│  └──────────────────────────────────────────────────────────────┘│
└──────────────────────────┬───────────────────────────────────────┘
                           │ (结构化指令 + 验证结果)
┌──────────────────────────▼────────────────────────────────────────┐
│  Layer 4: 决策层 (Decision Making)                                │
│  ┌──────────────────────────────────────────────────────────────┐│
│  │  Skeptic验证门控：                                            ││
│  │  - 置信度阈值判断 (default: 0.75)                             ││
│  │  - Human-in-the-Loop验证                                    ││
│  │  - 防幻觉机制                                                ││
│  │                                                              ││
│  │  LLM决策推理 + 多模型对比                                     ││
│  │  模块: skeptic.py, multi_model.py                            ││
│  └──────────────────────────────────────────────────────────────┘│
└──────────────────────────┬───────────────────────────────────────┘
                           │ (决策请求 + 验证指令)
┌──────────────────────────▼────────────────────────────────────────┐
│  Layer 3: 蒸馏层 (Knowledge Distillation)                          │
│  ┌──────────────────────────────────────────────────────────────┐│
│  │  经验卡 → SkillBank 知识库：                                   ││
│  │  - 观察转化为可复用规则                                       ││
│  │  - 自动版本化管理                                             ││
│  │  - 准确率追踪                                                ││
│  │  - 失效规则标记                                               ││
│  │                                                              ││
│  │  LLM合成 + 知识压缩 + 技能索引                                 ││
│  │  模块: distiller.py, skillbank.py, experience_card.py        ││
│  └──────────────────────────────────────────────────────────────┘│
└──────────────────────────┬───────────────────────────────────────┘
                           │ (规则查询请求 + 检索参数)
┌──────────────────────────▼────────────────────────────────────────┐
│  Layer 2: 检索层 (Retrieval Augmented Generation)                 │
│  ┌──────────────────────────────────────────────────────────────┐│
│  │  混合检索策略：                                               ││
│  │  ┌─────────────────────────────────────────────────────────┐││
│  │  │ 语义相似度搜索     KNN时间权重     BM25关键词匹配      │││
│  │  │ (embedding)      (recency bias)   (exact match)       │││
│  │  │     50%              30%              20%              │││
│  │  └─────────────────────────────────────────────────────────┘││
│  │                                                              ││
│  │  RAG管道 + 上下文压缩 + 结果排序                              ││
│  │  模块: retriever.py, rag_pipeline.py                         ││
│  └──────────────────────────────────────────────────────────────┘│
└──────────────────────────┬───────────────────────────────────────┘
                           │ (查询 + 查询类型)
┌──────────────────────────▼────────────────────────────────────────┐
│  Layer 1: 记忆层 (Persistent Memory)                              │
│  ┌──────────────────────────────────────────────────────────────┐│
│  │  三级分层记忆体系：                                           ││
│  │                                                              ││
│  │  Sensory (感知层):  24小时 - 最新事件、原始观察              ││
│  │  ├─ 数据：原始日志、实时事件                                 ││
│  │  ├─ 访问：高频、快速                                        ││
│  │  └─ 管理：自动过期                                           ││
│  │                                                              ││
│  │  Short-term (短期层): 7天 - 近期决策、讨论历史              ││
│  │  ├─ 数据：决策记录、上下文、见解                             ││
│  │  ├─ 访问：语义检索 + 时间加权                                ││
│  │  └─ 管理：定期压缩                                           ││
│  │                                                              ││
│  │  Long-term (长期层): 永久 - 验证规则、技能库                ││
│  │  ├─ 数据：精炼规则、经验卡、SkillBank                       ││
│  │  ├─ 访问：精确查询 + 版本控制                                ││
│  │  └─ 管理：不可变存档                                         ││
│  │                                                              ││
│  │  存储引擎: JSON/JSONL / SQLite / Redis (可扩展)             ││
│  │  模块: memory_tiers.py, storage.py                           ││
│  └──────────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────┘
                           ▲
                           │ (读写操作)
                ┌──────────┴──────────┐
                │                     │
          用户输入              执行反馈
```

### 五层详细说明

| 层级 | 名称 | 核心职责 | 关键模块 | 论文根源 |
|------|------|--------|--------|---------|
| **L1** | 记忆层 | 跨会话持久化 + 三级分层 | `memory_tiers.py` | RAG, Memory-Augmented Networks |
| **L2** | 检索层 | 混合检索 + 语义 + 时间 + 关键词 | `retriever.py` | Dense Passage Retrieval, BM25 |
| **L3** | 蒸馏层 | 知识提炼 + 技能库 + 版本管理 | `distiller.py` | Knowledge Distillation, Experience Replay |
| **L4** | 决策层 | LLM推理 + 防幻觉 + Human-in-loop | `skeptic.py` | Uncertainty Quantification, Constitutional AI |
| **L5** | 编排层 | Loop闭环 + 任务调度 + 自动化 | `pipeline.py` | DAG Scheduling, Reinforcement Learning |

### 数据流转示例

```
输入观察 (日志、事件)
    ↓
[L1] 存储到Sensory层
    ↓
[L2] 语义检索相关历史
    ↓
[L3] 加载已验证的SkillBank规则
    ↓
[L4] LLM推理 + Skeptic验证
    ↓
[L3] 提炼新规则 → SkillBank (if confidence >= 0.75)
    ↓
[L1] 更新Short-term和Long-term层
    ↓
输出决策 + 更新报告
```

### 各层调用示例

```python
# Layer 1: 记忆层操作
from gcc_evolution.memory import MemoryTiers

memory = MemoryTiers()
memory.sensory.record({'event': 'trade_executed', 'price': 145.5})
memory.short_term.store({'decision': 'increase_threshold', 'confidence': 0.82})
memory.long_term.add_skill({'skill_id': 'SK-001', 'pattern': '...'})

# Layer 2: 检索层操作
from gcc_evolution.retrieval import HybridRetriever

retriever = HybridRetriever(semantic=0.5, temporal=0.3, keyword=0.2)
results = retriever.search("threshold adjustment strategy", top_k=5)

# Layer 3: 蒸馏层操作
from gcc_evolution.distiller import Distiller

distiller = Distiller()
skill = distiller.extract_skill(experience={'observation': '...', 'outcome': '...'})
skillbank.add_skill(skill)

# Layer 4: 决策层操作
from gcc_evolution.skeptic import SkepticGate

skeptic = SkepticGate(threshold=0.75)
decision = llm.make_decision(context=context)
if skeptic.verify(decision):
    apply_decision(decision)
else:
    request_human_review(decision)

# Layer 5: 编排层操作
from gcc_evolution.pipeline import LoopEngine

loop = LoopEngine(task_id='GCC-0001')
result = loop.run_once(
    observe=lambda: get_logs(),
    audit=lambda logs: analyze(logs),
    extract=lambda: distill_experience(),
    verify=lambda: skeptic_check(),
    distill=lambda: update_skillbank(),
    report=lambda: generate_report()
)
```

---

## 主要特性

- **跨模型切换**：支持 Gemini、ChatGPT、Claude、DeepSeek 之间无缝切换，不丢失上下文
- **防幻觉门控**：Skeptic 验证层，阻止未验证的结论写入记忆
- **自动经验蒸馏**：每轮改善后自动提炼可复用规则，积累进化
- **Loop 闭环命令**：`gcc-evo loop` 一键运行完整改善闭环
- **可视化看板**：单文件 HTML，无需安装，浏览器直接打开
- **论文驱动**：引用 30 篇评分 4.0+ 的 arXiv 论文，核心算法有学术根基

---

## 适用场景

gcc-evo 适合**已经突破传统 AI 单窗口限制**、需要让 AI 做更复杂长期任务的场景：

- 软件系统持续改善（原始场景：交易软件 bug 追踪）
- 工业设备 AI 辅助诊断与优化
- 任何需要跨会话积累经验的 AI 应用

**进化路线**：产品 → 通用引擎 → 定制引擎 → 改善产品 → 改善专用引擎 → 改善通用引擎

---

## 快速开始

```bash
# 安装
pip install -e .

# 初始化项目
gcc-evo init

# 查看所有命令
gcc-evo --help

# 运行改善闭环（绑定具体任务）
gcc-evo loop GCC-0001 --once

# 打开可视化看板
gcc-evo dashboard
```

详见 [QUICKSTART.md](QUICKSTART.md)

---

## 数字

| 指标 | 数值 |
|------|------|
| 开发时间 | ~240 小时 |
| 代码行数 | 6,000+ 行 |
| 子模块数 | 45 个 |
| 引用论文 | 30 篇（arXiv 评分 4.0+） |
| 支持模型 | Gemini / ChatGPT / Claude / DeepSeek |

---

## 定价与许可证

### 四层定价方案

| 版本 | 价格 | 包含功能 | 适用对象 |
|------|------|--------|--------|
| **Community** | 🆓 永久免费 | L1-L5 基础框架 + Direction Anchor | 个人/学术/<$1M 收入 |
| **Evolve** | $29/月 | + KNN 进化 + Walk-Forward 回测 | 小型团队/交易者 |
| **Pro** | $79/月 | + Signal Evolution + 高级 SkillBank | 机构/专业交易室 |
| **Enterprise** | $500+/月 | + 私有部署 + 垂直优化 | 大型基金/定制方案 |

📖 **完整详情**: [PRICING.md](PRICING.md)

### 许可证
- **Base**: [BUSL 1.1](LICENSE)
- **Change Date**: 2028-05-01 → 届时自动转为 Apache-2.0
- **Community 永久免费**: 个人、学术、<$1M 年收入

---

## 贡献

见 [CONTRIBUTING.md](CONTRIBUTING.md)。欢迎 issue 和 PR，核心架构变更请先开 issue 讨论。
