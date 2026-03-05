# TUTORIAL — gcc-evo 深度使用指南

> 本教程假设你已阅读 QUICKSTART.md。我们将深入讨论核心概念、高级用法和最佳实践。

---

## 目录

1. [核心概念](#核心概念)
2. [KEY 和 GCC 任务设计](#key-和-gcc-任务设计)
3. [Loop 闭环详解](#loop-闭环详解)
4. [内存系统](#内存系统)
5. [检索和蒸馏](#检索和蒸馏)
6. [跨模型协作](#跨模型协作)
7. [实战案例](#实战案例)
8. [性能优化](#性能优化)
9. [故障诊断](#故障诊断)

---

## 核心概念

### gcc-evo 的三个角色

gcc-evo 用三个核心实体来组织工作：

| 实体 | 定义 | 范围 | 示例 |
|------|------|------|------|
| **KEY** | 改善方向 | 战略目标，跨多轮迭代 | KEY-001: 提高交易信号准确率 |
| **GCC** | 任务分解 | KEY 下的单个任务 | GCC-0155: 开源文档完成 |
| **Steps** | 执行步骤 | GCC 下的细化操作 | S1: 创建 LICENSE.md |

### 三层工作模型

```
战略层 (Strategy)
  ↓ 拆解
任务层 (Task)
  ↓ 细化
执行层 (Steps)
```

**示例：提高交易信号准确率**

```
KEY-001: 提高交易信号准确率
├── GCC-0100: Phase 1 - 历史数据验证
│   ├── S1: 收集过去 3 个月交易日志
│   ├── S2: 计算信号准确率 baseline
│   └── S3: 识别高误判时段
├── GCC-0101: Phase 2 - 问题诊断
│   ├── S1: 分析假突破模式
│   ├── S2: 对比多个 LLM 的信号质量
│   └── S3: 提出改进假设
└── GCC-0102: Phase 3 - 改进实施
    ├── S1: 实现新的信号过滤规则
    ├── S2: 回测验证改进效果
    └── S3: 上线和监控
```

---

## KEY 和 GCC 任务设计

### 设计高质量 KEY

**好 KEY 的特征**：
- ✅ 可测量 — 有明确的成功指标
- ✅ 跨越多个 GCC — 需要 3+ 个相关任务
- ✅ 长期 — 改善持续数周或数月
- ✅ 独立性 — 与其他 KEY 的依赖清晰

**反例：不好的 KEY**
```
KEY-000: 改善系统  ❌ 太宽泛，无法测量

KEY-001: 提高交易信号准确率  ✅ 具体、可测量、长期
KEY-002: 降低虚假信号频率   ✅ 具体目标
```

### 创建 KEY

```bash
# 编辑 state/improvements.json
{
  "keys": [
    {
      "id": "KEY-001",
      "title": "提高交易信号准确率",
      "status": "IN_PROGRESS",
      "baseline": 0.65,           # 初始准确率
      "target": 0.75,             # 目标准确率
      "owner": "signal-team",
      "start_date": "2026-01-15",
      "description": "通过历史验证和 LLM 协作，提升 L1/L2 信号准确率"
    }
  ]
}

# 或使用命令行
gcc-evo pipe add --key KEY-001 "创建 KEY 条目"
```

### 设计高质量 GCC 任务

**GCC 任务的生命周期**：

```
BACKLOG → IN_PROGRESS → TESTING → DONE
          (分配给人或智能体)
```

**任务模板**：

```json
{
  "id": "GCC-0155",
  "title": "v5.290 开源发布包 — 完整 P0 文档",
  "key": "KEY-008",
  "priority": "P1",
  "status": "DONE",
  "owner": "claude-code",
  "description": "创建开源发布所需的全套 P0 文档：README/QUICKSTART/LICENSE/SECURITY/CONTRIBUTING/CLAs",
  "steps": [
    {
      "id": "S1",
      "title": "创建 README.md",
      "status": "done"
    },
    {
      "id": "S2",
      "title": "创建 LICENSE (BUSL 1.1)",
      "status": "done"
    }
  ]
}
```

**创建 GCC 任务**：

```bash
gcc-evo pipe task "改善信号准确率 Phase 1" \
  -k KEY-001 \
  -m signal-analysis \
  -p P1 \
  -d "通过历史数据验证发现信号问题"

# 输出: GCC-0155 created
```

---

## Loop 闭环详解

### Loop 是什么？

Loop 是 gcc-evo 的**自动化改善引擎**。它将手动的"发现问题→分析→改进→验证"过程自动化。

### Loop 的 6 步

```
┌──────────────────────────────────┐
│ 1. TASKS — 读取当前任务进度      │
│    (GCC-0155: 80% 完成)          │
└──────────────────────────────────┘
              ↓
┌──────────────────────────────────┐
│ 2. AUDIT — 分析日志，发现问题    │
│    (5 个问题: 环境变量泄露...)    │
└──────────────────────────────────┘
              ↓
┌──────────────────────────────────┐
│ 3. CARDS — 生成经验卡            │
│    (新增 3 张知识卡)              │
└──────────────────────────────────┘
              ↓
┌──────────────────────────────────┐
│ 4. RULES — 提取可复用规则         │
│    (发现 5 条规则模式)            │
└──────────────────────────────────┘
              ↓
┌──────────────────────────────────┐
│ 5. DISTILL — 蒸馏到 SkillBank    │
│    (SkillBank +2 技能)            │
└──────────────────────────────────┘
              ↓
┌──────────────────────────────────┐
│ 6. REPORT — 显示改善摘要          │
│    (预计改善: +3% 准确率)         │
└──────────────────────────────────┘
```

### 运行 Loop

**单次闭环**（测试用）：
```bash
gcc-evo loop GCC-0155 --once
```

**持续闭环**（生产用，每 5 分钟运行一次）：
```bash
gcc-evo loop GCC-0155
# 或后台运行
nohup gcc-evo loop GCC-0155 > loop.log 2>&1 &
```

**监控 Loop**：
```bash
# 查看日志
tail -f .GCC/logs/loop.log

# 查看进度
gcc-evo show GCC-0155

# 查看诊断
gcc-evo diag GCC-0155
```

### Loop 的内部机制

#### 2. AUDIT 阶段

Audit 分析日志找问题：

```python
# 伪代码：Audit 逻辑
problems = []

# 检查 API 错误
for line in log_analyzer.get_errors():
    problems.append(ErrorProblem(line))

# 检查性能下降
for metric in monitor.get_metrics():
    if metric.degradation > 10%:
        problems.append(PerformanceProblem(metric))

# 检查 LLM 不一致
for decision in llm_decisions:
    if decision.confidence < 0.5:
        problems.append(ConfidenceProblem(decision))

return problems[:10]  # 最多 10 个问题
```

#### 4. RULES 阶段

Rules 从问题中提取规则：

```python
# 伪代码：Rule Extraction
rules = []

for problem in problems:
    # 问题 → 规则转换
    rule = {
        "pattern": problem.pattern,
        "condition": problem.condition,
        "action": problem.recommended_fix,
        "confidence": problem.confidence,
        "source": problem.source_code_location
    }
    rules.append(rule)

# 去重和排序
return deduplicate_and_rank(rules)
```

#### 5. DISTILL 阶段

Distill 将规则蒸馏成可复用技能：

```python
# 伪代码：Distillation
skills = []

for rule in rules:
    if rule.confidence >= 0.75:  # 高置信度
        skill = {
            "name": f"Skill-{hash(rule)}",
            "type": "rule_based",
            "condition": rule.condition,
            "action": rule.action,
            "success_rate": estimate_from_history(rule),
            "use_count": 0
        }
        skillbank.add(skill)
        skills.append(skill)

return skills
```

---

## 内存系统

gcc-evo 的内存分为三层，每层有不同的用途：

### 三层内存架构

```
Sensory Tier (感知层)
├─ 最近 10 条消息
├─ 保留期: 24 小时
├─ 用途: 即时参考
└─ 典型: "刚才提到的 KEY-001 准确率是多少？"

Short-term Tier (短期层)
├─ 最近 100 条决策
├─ 保留期: 7 天
├─ 用途: 周期内上下文
└─ 典型: "这周的信号改善模式是什么？"

Long-term Tier (长期层)
├─ 关键决策和总结
├─ 保留期: 无限
├─ 用途: 跨周期知识
└─ 典型: "过去 3 个月的信号准确率趋势"
```

### 内存查询

```bash
# 查看感知层
gcc-evo memory show --tier sensory

# 查看短期层，最近 7 天
gcc-evo memory show --tier short-term --days 7

# 查看长期层，搜索关键词
gcc-evo memory search "信号准确率" --tier long-term

# 内存统计
gcc-evo memory stats
# 输出:
# Sensory: 8/10 (80%)
# Short-term: 47/100 (47%)
# Long-term: 1043 items
```

### 内存管理

```bash
# 压缩内存 (自动将旧的短期转移到长期)
gcc-evo memory compact

# 重新索引 (重建搜索索引)
gcc-evo memory reindex

# 清理过期数据 (删除超过保留期的数据)
gcc-evo memory cleanup --days 30
```

---

## 检索和蒸馏

### 语义检索

gcc-evo 的检索使用三个策略的组合：

```
用户查询: "怎样提高 L2 信号准确率？"

│
├─→ 策略 1: 关键词匹配 (BM25)
│   └─ 返回: 包含 "L2" + "准确率" 的条目
│
├─→ 策略 2: 语义相似度 (Embedding)
│   └─ 返回: 语义相近但词不同的条目
│
└─→ 策略 3: KNN 历史相似 (K-Nearest Neighbors)
    └─ 返回: 相似的历史问题和解决方案

结果融合 → 排序 → 返回 Top-10
```

**使用检索**：

```bash
# 搜索相似的任务
gcc-evo search "提高信号准确率"

# 搜索特定 KEY 的经验
gcc-evo search "KEY-001" --type cards

# 搜索规则
gcc-evo search "环境变量" --type rules
```

### 经验蒸馏

蒸馏将零散的经验转化为结构化知识：

```
原始经验 (日志、对话、代码)
    ↓
提取关键信息 (LLM 分析)
    ↓
生成经验卡 (知识格式化)
    ↓
创建规则 (通用化)
    ↓
蒸馏成技能 (SkillBank)
    ↓
自动应用 (Loop 中自动触发)
```

**手动蒸馏**：

```bash
# 从日志蒸馏
gcc-evo distill --source logs --days 7

# 使用特定 LLM
gcc-evo distill --model gemini

# 查看蒸馏结果
gcc-evo skillbank list

# 查看技能详情
gcc-evo skillbank show SK-0042
```

---

## 跨模型协作

gcc-evo 支持在 Loop 中使用多个 LLM 模型：

### 模型能力对比

| 模型 | 优势 | 劣势 | 推荐用途 |
|------|------|------|----------|
| **Claude** | 长上下文 (200K) | 稍慢 | 决策、长文本分析 |
| **GPT-4** | 快速、准确 | 上下文短 (128K) | 编程、速度敏感 |
| **Gemini** | 便宜、快 | 质量稍低 | 初步分析 |
| **DeepSeek** | 极便宜 | 质量不稳定 | 大量重复任务 |

### Skeptic 验证门控

Loop 中的 Skeptic 模块防止低质量决策：

```python
decision = llm_decide(prompt)

# Skeptic 检查
if decision.confidence < 0.75:
    # 低置信，要求重新分析
    decision = llm_decide(prompt, model='gpt-4')  # 尝试更强模型

if decision.confidence < 0.50:
    # 仍然低，标记为待审核
    decision.status = 'REQUIRES_HUMAN_REVIEW'
    send_alert(decision)
```

### 多模型 Loop

```bash
# 主决策用 Claude，验证用 Gemini + GPT-4
gcc-evo loop GCC-0155 \
  --primary claude \
  --verifier gemini,gpt-4 \
  --skeptic-threshold 0.75
```

---

## 实战案例

### 案例 1：交易信号准确率改善

**目标**：将 L1 信号准确率从 65% 提升到 75%

**过程**：

**Day 1-2: 建立基线**
```bash
# 1. 创建 KEY
gcc-evo pipe add --key KEY-001 "创建 KEY-001"

# 2. 创建任务
gcc-evo pipe task "分析历史信号质量" -k KEY-001 -p P1

# 3. 初始化 Loop
gcc-evo loop GCC-0100 --once
```

**Day 3-5: 诊断问题**
```bash
# 1. 运行 Audit，发现问题
gcc-evo loop GCC-0100

# 2. 查看问题列表
gcc-evo diag GCC-0100

# 3. 分析根因
gcc-evo search "假突破" --type problems
```

**Day 6-10: 改进实施**
```bash
# 1. 创建改进任务
gcc-evo pipe task "实现新信号过滤规则" -k KEY-001 -p P1

# 2. 代码修改 (手动)
# ... 修改 llm_server.py 中的信号逻辑 ...

# 3. 验证改进
gcc-evo loop GCC-0101 --once

# 4. 蒸馏成规则
gcc-evo distill --source logs --days 3
```

**Day 11-15: 监控验证**
```bash
# 持续运行 Loop
gcc-evo loop GCC-0101 &

# 每天检查进度
gcc-evo diag GCC-0101

# 查看准确率趋势
gcc-evo show KEY-001
```

---

### 案例 2：构建新的 AI 功能

**目标**：添加新的 Vision 分析模块

**步骤**：

```bash
# 1. 创建 KEY (长期方向)
# KEY-009: 增强视觉信号识别

# 2. 分解为 Phase
# GCC-0200: Phase 1 - 研究和设计
# GCC-0201: Phase 2 - 核心实现
# GCC-0202: Phase 3 - 集成和验证

# 3. Phase 1 执行
gcc-evo loop GCC-0200 --once

# 4. Loop 自动：
#    - 分析论文和参考实现
#    - 生成设计建议
#    - 提取关键模式
#    - 蒸馏最佳实践

# 5. Phase 2 执行
gcc-evo loop GCC-0201

# 6. 验证和上线
gcc-evo loop GCC-0202
```

---

## 性能优化

### 加速 Loop

**问题**：Loop 运行太慢？

**优化方案**：

```bash
# 1. 并行运行多个任务
gcc-evo loop GCC-0155 &
gcc-evo loop GCC-0156 &
gcc-evo loop GCC-0157 &

# 2. 使用快速模型
gcc-evo loop GCC-0155 --model gemini --once

# 3. 减少日志分析范围
gcc-evo loop GCC-0155 --audit-days 1

# 4. 禁用不需要的阶段
gcc-evo loop GCC-0155 --skip distill --skip cards
```

### 内存优化

```bash
# 定期压缩
gcc-evo memory compact --schedule daily

# 减少保留期
gcc-evo memory config --short-term-days 3 --long-term-days 90

# 清理过期数据
gcc-evo memory cleanup --older-than 30days
```

### 成本优化

```bash
# 查看成本统计
gcc-evo stats --cost

# 使用便宜模型
gcc-evo loop GCC-0155 --model deepseek

# 批量处理以减少 API 调用
gcc-evo distill --batch-size 50
```

---

## 故障诊断

### 常见问题

**Q1: Loop 卡住了**

```bash
# 1. 查看日志
tail -f .GCC/logs/loop.log

# 2. 检查状态
gcc-evo show GCC-0155

# 3. 强制中止
pkill -f "gcc-evo loop"

# 4. 重置状态
gcc-evo state reset --confirm

# 5. 重新启动
gcc-evo loop GCC-0155 --once
```

**Q2: 内存不足**

```bash
# 1. 检查内存大小
gcc-evo memory stats

# 2. 压缩内存
gcc-evo memory compact

# 3. 清理过期数据
gcc-evo memory cleanup

# 4. 检查是否有内存泄漏
gcc-evo diag --memory
```

**Q3: LLM 准确率低**

```bash
# 1. 检查置信度
gcc-evo show GCC-0155 | grep confidence

# 2. 切换到更强的模型
gcc-evo loop GCC-0155 --model gpt-4 --once

# 3. 提高 Skeptic 阈值 (要求更多验证)
gcc-evo config set skeptic.threshold 0.85

# 4. 查看最近的错误决策
gcc-evo search "REQUIRES_HUMAN_REVIEW"
```

### 调试模式

```bash
# 启用调试日志
gcc-evo loop GCC-0155 --debug --once

# 输出详细的 LLM 对话
gcc-evo loop GCC-0155 --verbose-llm --once

# 干运行 (不执行修改)
gcc-evo loop GCC-0155 --dry-run --once
```

---

## 最佳实践

### ✅ 做这些

1. **定期运行 Loop** — 每天至少一次，让系统持续学习
2. **审查生成的规则** — 确保 Skeptic 门控的有效性
3. **维护清晰的 KEY** — 每个 KEY 对应一个独立的改善方向
4. **记录决策理由** — 在任务描述中说明"为什么"
5. **备份经验卡** — 定期导出 SkillBank

### ❌ 避免这些

1. **过度细化** — 不要为每一行代码创建一个 Step
2. **混淆 KEY** — 不要把多个无关的目标放在一个 KEY 里
3. **忽视 Skeptic 告警** — 置信度低的决策需要人工审查
4. **堆积垃圾数据** — 定期清理不相关的内容
5. **依赖单一模型** — 使用多模型验证提高可靠性

---

## 总结

gcc-evo 的核心力量在于：

1. **跨会话记忆** — AI 真正"记住"过去的决策
2. **自动改善循环** — Loop 将手动过程自动化
3. **知识蒸馏** — 将经验转化为可复用规则
4. **多模型协作** — 综合不同模型的优势
5. **可解释性** — 每一步决策都可追溯

通过这些能力，gcc-evo 将 AI 从"一次性工具"转变为"持续学习的伙伴"。

---

**下一步**：
- 阅读 [CONTRIBUTING.md](CONTRIBUTING.md) 了解如何贡献
- 查看 [ARCHITECTURE.md](ARCHITECTURE.md) 深入理解设计
- 浏览 SkillBank 学习已有的技能 — `gcc-evo skillbank list`

---

**版本**: 5.295
**最后更新**: 2026-03-03
**维护者**: baodexiang <baodexiang@hotmail.com>
