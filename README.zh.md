# gcc-evo — AI Self-Evolution Engine v5.295
# gcc-evo — AI 自进化引擎 v5.295

> **Break the 200K token context window limit — let AI truly remember and continuously evolve**
>
> **突破 AI 20 万 Token 窗口限制，让 AI 真正记住过去、持续进化**

[![License](https://img.shields.io/badge/license-BUSL%201.1-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)

[English](README.md) | [中文](README.zh.md)

---

## What is gcc-evo?

**gcc-evo** is an open-source framework that enables LLM agents to:

- **Remember** — Three-tier persistent memory system (sensory/short-term/long-term)
- **Learn** — Automatic experience distillation into reusable skills
- **Improve** — Continuous self-refinement through automated loops
- **Decide** — Skeptic verification gate to prevent hallucinations
- **Collaborate** — Seamless switching between Claude, GPT-4, Gemini, DeepSeek

## 背景

这个项目的起点，不是一个宏大的计划。

我厌倦了天天盯着 K 线图，于是花了三个月写了一套不用人工看盘的自动化交易软件。软件跑起来了，但随之而来的是一堆 bug——改 bug 比看 K 线还麻烦。

为了系统性地追踪和修复这些问题，我顺手写了一个辅助工具：记录每个问题、跟踪修复过程、验证结果。

恰好这段时间，有个客户找我协助解决他们激光切割机的生产问题。上门拜访时，我随口提了这个"AI 辅助改善"的工具。客户非常感兴趣，当场让我试试能不能用在他们的工业场景上。

两周后，**gcc-evo** 的雏形诞生了。

---

## Five-Layer Architecture / 五层框架架构

```
┌──────────────────────────────────────────────────────────────────┐
│                    Application Layer / 应用层                      │
│                   gcc-evo loop / commands                        │
└──────────────────────────┬───────────────────────────────────────┘
                           │
┌──────────────────────────▼────────────────────────────────────────┐
│  L5: Orchestration / 编排层                                        │
│  Loop Closure Engine (6-step automation):                         │
│  Observe → Audit → Extract → Verify → Distill → Report           │
│  Modules: pipeline.py, loop_engine.py                             │
└──────────────────────────┬───────────────────────────────────────┘
                           │
┌──────────────────────────▼────────────────────────────────────────┐
│  L4: Decision Making / 决策层                                      │
│  Skeptic Verification Gate (confidence threshold: 0.75)           │
│  Human-in-the-Loop + Hallucination Prevention                     │
│  Modules: skeptic.py, multi_model.py                              │
└──────────────────────────┬───────────────────────────────────────┘
                           │
┌──────────────────────────▼────────────────────────────────────────┐
│  L3: Distillation / 蒸馏层                                        │
│  Experience Cards → SkillBank Knowledge Library                   │
│  Auto-versioning + Accuracy Tracking                              │
│  Modules: distiller.py, skillbank.py                              │
└──────────────────────────┬───────────────────────────────────────┘
                           │
┌──────────────────────────▼────────────────────────────────────────┐
│  L2: Retrieval / 检索层                                            │
│  Semantic(50%) + Temporal(30%) + Keyword(20%)                     │
│  Modules: retriever.py, rag_pipeline.py                           │
└──────────────────────────┬───────────────────────────────────────┘
                           │
┌──────────────────────────▼────────────────────────────────────────┐
│  L1: Memory / 记忆层                                               │
│  Sensory(24h) → Short-term(7d) → Long-term(permanent)            │
│  Storage: JSON/JSONL / SQLite / Redis                             │
│  Modules: memory_tiers.py, storage.py                             │
└──────────────────────────────────────────────────────────────────┘
```

| Layer | Name | Core Responsibility | Key Modules | Academic Foundation |
|-------|------|---------------------|-------------|-------------------|
| **L1** | Memory / 记忆层 | Persistent storage + 3-tier hierarchy | `memory_tiers.py` | RAG, Memory Networks |
| **L2** | Retrieval / 检索层 | Hybrid search: semantic + temporal + keywords | `retriever.py` | Dense Passage Retrieval, BM25 |
| **L3** | Distillation / 蒸馏层 | Knowledge extraction + skill library + versioning | `distiller.py` | Knowledge Distillation, Experience Replay |
| **L4** | Decision / 决策层 | LLM reasoning + hallucination prevention | `skeptic.py` | Uncertainty Quantification, Constitutional AI |
| **L5** | Orchestration / 编排层 | Loop closure + task scheduling + automation | `pipeline.py` | DAG Scheduling, Reinforcement Learning |

---

## Key Features / 主要特性

- **Cross-model switching / 跨模型切换** — Gemini, GPT-4, Claude, DeepSeek seamless context transfer
- **Hallucination prevention / 防幻觉门控** — Skeptic verification blocks unverified conclusions
- **Auto experience distillation / 自动经验蒸馏** — Each iteration refines reusable rules
- **Loop command / Loop 闭环命令** — `gcc-evo loop` runs the full improvement cycle
- **Dashboard / 可视化看板** — Single HTML file, no installation required
- **Research-backed / 论文驱动** — 30 arXiv papers (score 4.0+) inform core algorithms

---

## Quick Start / 快速开始

```bash
# Install / 安装
pip install -e .

# Initialize / 初始化
gcc-evo init

# View commands / 查看命令
gcc-evo --help

# Run improvement loop / 运行改善闭环
gcc-evo loop GCC-0001 --once

# Open dashboard / 打开看板
gcc-evo dashboard
```

See [QUICKSTART.md](QUICKSTART.md) | [QUICKSTART.en.md](QUICKSTART.en.md)

---

## Use Cases / 适用场景

- **Software improvement / 软件系统改善** — Bug tracking, performance optimization
- **Industrial AI diagnostics / 工业 AI 辅助诊断** — Equipment monitoring, process optimization
- **Any long-term AI task / 跨会话 AI 应用** — Any scenario requiring accumulated experience

**Evolution path / 进化路线**: Product → General Engine → Custom Engine → Improve Product

---

## Command Reference / 命令参考

```bash
# Project Management
gcc-evo init [--project NAME]              # Initialize
gcc-evo version                            # Version info

# Task Management
gcc-evo pipe task <TITLE> -k KEY -m module -p P0|P1|P2
gcc-evo pipe list                          # List tasks
gcc-evo pipe status GCC-0001               # Task status

# Loop Execution
gcc-evo loop GCC-0001 --once               # Single iteration
gcc-evo loop GCC-0001 --provider gemini    # Specify LLM

# Memory Management
gcc-evo memory compact                     # Compress memory
gcc-evo memory export                      # Backup state
```

---

## Numbers / 数字

| Metric / 指标 | Value / 数值 |
|------|------|
| Development time / 开发时间 | ~240 hours |
| Lines of code / 代码行数 | 6,000+ |
| Submodules / 子模块数 | 45 |
| Referenced papers / 引用论文 | 30 (arXiv score 4.0+) |
| Supported models / 支持模型 | Gemini / GPT-4 / Claude / DeepSeek |

---

## Pricing / 定价

| Tier / 版本 | Price / 价格 | Included / 包含 | Best For / 适用 |
|------|------|--------|--------|
| **Community** | 🆓 Forever Free | L1-L5 foundation + Direction Anchor | Personal/Academic/<$1M |
| **Evolve** | $29/month | + KNN Evolution + Walk-Forward Testing | Small teams |
| **Pro** | $79/month | + Signal Evolution + Advanced SkillBank | Institutions |
| **Enterprise** | $500+/month | + Private deployment + Custom | Large funds |

See [PRICING.md](PRICING.md) | [PRICING.en.md](PRICING.en.md)

---

## License / 许可证

- **Base**: [BUSL 1.1](LICENSE)
- **Change Date**: 2028-05-01 → auto-converts to Apache 2.0
- **Community Forever Free**: Individuals, academics, <$1M annual revenue

---

## Contributing / 贡献

See [CONTRIBUTING.md](CONTRIBUTING.md) | [CONTRIBUTING.en.md](CONTRIBUTING.en.md)

Welcome issues and PRs. For core architecture changes, please open an issue first.

---

## Roadmap

```
v5.295 (Current) — Loop + Skeptic + Multi-Model
    ↓
v5.5 (Q2 2026) — Distributed Memory + Real-time Collaboration
    ↓
v6.0 (Q4 2026) — Apache 2.0 + Full Open Source
    ↓
v7.0 (2027) — Plugin Ecosystem + Enterprise Features
```

---

## Citation

```bibtex
@software{gcc_evo_2026,
  author = {baodexiang},
  title = {gcc-evo: AI Self-Evolution Engine},
  year = {2026},
  url = {https://github.com/baodexiang/gcc-evolution},
  version = {5.295}
}
```

---

**Made with ❤️ by [baodexiang](https://github.com/baodexiang)**
