# gcc-evo â€” AI Self-Evolution Engine v5.325

See also: [FRAMEWORK_BOUNDARY.md](FRAMEWORK_BOUNDARY.md) | [FRAMEWORK_BOUNDARY.en.md](FRAMEWORK_BOUNDARY.en.md) | [LAYER_STRUCTURE.md](LAYER_STRUCTURE.md)

# gcc-evo â€” AI è‡ªè¿›åŒ–å¼•æ“Ž v5.325

> **Break the 200K token context window limit â€” let AI truly remember and continuously evolve**
>
> **çªç ´ AI 20 ä¸‡ Token çª—å£é™åˆ¶ï¼Œè®© AI çœŸæ­£è®°ä½è¿‡åŽ»ã€æŒç»­è¿›åŒ–**

[![License](https://img.shields.io/badge/license-BUSL%201.1-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)

[English](README.md) | [ä¸­æ–‡](README.zh.md)

---

## What is gcc-evo?

**gcc-evo** is an open-source framework that enables LLM agents to:

- **Remember** â€” Three-tier persistent memory system (sensory/short-term/long-term)
- **Learn** â€” Automatic experience distillation into reusable skills
- **Improve** â€” Continuous self-refinement through automated loops
- **Decide** â€” Skeptic verification gate to prevent hallucinations
- **Collaborate** â€” Seamless switching between Claude, GPT-4, Gemini, DeepSeek

## èƒŒæ™¯

è¿™ä¸ªé¡¹ç›®çš„èµ·ç‚¹ï¼Œä¸æ˜¯ä¸€ä¸ªå®å¤§çš„è®¡åˆ’ã€‚

æˆ‘åŽŒå€¦äº†å¤©å¤©ç›¯ç€ K çº¿å›¾ï¼ŒäºŽæ˜¯èŠ±äº†ä¸‰ä¸ªæœˆå†™äº†ä¸€å¥—ä¸ç”¨äººå·¥çœ‹ç›˜çš„è‡ªåŠ¨åŒ–äº¤æ˜“è½¯ä»¶ã€‚è½¯ä»¶è·‘èµ·æ¥äº†ï¼Œä½†éšä¹‹è€Œæ¥çš„æ˜¯ä¸€å † bugâ€”â€”æ”¹ bug æ¯”çœ‹ K çº¿è¿˜éº»çƒ¦ã€‚

ä¸ºäº†ç³»ç»Ÿæ€§åœ°è¿½è¸ªå’Œä¿®å¤è¿™äº›é—®é¢˜ï¼Œæˆ‘é¡ºæ‰‹å†™äº†ä¸€ä¸ªè¾…åŠ©å·¥å…·ï¼šè®°å½•æ¯ä¸ªé—®é¢˜ã€è·Ÿè¸ªä¿®å¤è¿‡ç¨‹ã€éªŒè¯ç»“æžœã€‚

æ°å¥½è¿™æ®µæ—¶é—´ï¼Œæœ‰ä¸ªå®¢æˆ·æ‰¾æˆ‘ååŠ©è§£å†³ä»–ä»¬æ¿€å…‰åˆ‡å‰²æœºçš„ç”Ÿäº§é—®é¢˜ã€‚ä¸Šé—¨æ‹œè®¿æ—¶ï¼Œæˆ‘éšå£æäº†è¿™ä¸ª"AI è¾…åŠ©æ”¹å–„"çš„å·¥å…·ã€‚å®¢æˆ·éžå¸¸æ„Ÿå…´è¶£ï¼Œå½“åœºè®©æˆ‘è¯•è¯•èƒ½ä¸èƒ½ç”¨åœ¨ä»–ä»¬çš„å·¥ä¸šåœºæ™¯ä¸Šã€‚

ä¸¤å‘¨åŽï¼Œ**gcc-evo** çš„é›å½¢è¯žç”Ÿäº†ã€‚

---

## Five-Layer Architecture / äº”å±‚æ¡†æž¶æž¶æž„

```
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚                    Application Layer / åº”ç”¨å±‚                      â”‚
â”‚                   gcc-evo loop / commands                        â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                           â”‚
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â–¼â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚  L5: Orchestration / ç¼–æŽ’å±‚                                        â”‚
â”‚  Loop Closure Engine (6-step automation):                         â”‚
â”‚  Observe â†’ Audit â†’ Extract â†’ Verify â†’ Distill â†’ Report           â”‚
â”‚  Modules: pipeline.py, loop_engine.py                             â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                           â”‚
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â–¼â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚  L4: Decision Making / å†³ç­–å±‚                                      â”‚
â”‚  Skeptic Verification Gate (confidence threshold: 0.75)           â”‚
â”‚  Human-in-the-Loop + Hallucination Prevention                     â”‚
â”‚  Modules: skeptic.py, multi_model.py                              â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                           â”‚
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â–¼â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚  L3: Distillation / è’¸é¦å±‚                                        â”‚
â”‚  Experience Cards â†’ SkillBank Knowledge Library                   â”‚
â”‚  Auto-versioning + Accuracy Tracking                              â”‚
â”‚  Modules: distiller.py, skillbank.py                              â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                           â”‚
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â–¼â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚  L2: Retrieval / æ£€ç´¢å±‚                                            â”‚
â”‚  Semantic(50%) + Temporal(30%) + Keyword(20%)                     â”‚
â”‚  Modules: retriever.py, rag_pipeline.py                           â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                           â”‚
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â–¼â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚  L1: Memory / è®°å¿†å±‚                                               â”‚
â”‚  Sensory(24h) â†’ Short-term(7d) â†’ Long-term(permanent)            â”‚
â”‚  Storage: JSON/JSONL / SQLite / Redis                             â”‚
â”‚  Modules: memory_tiers.py, storage.py                             â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
```

| Layer | Name | Core Responsibility | Key Modules | Academic Foundation |
|-------|------|---------------------|-------------|-------------------|
| **L1** | Memory / è®°å¿†å±‚ | Persistent storage + 3-tier hierarchy | `memory_tiers.py` | RAG, Memory Networks |
| **L2** | Retrieval / æ£€ç´¢å±‚ | Hybrid search: semantic + temporal + keywords | `retriever.py` | Dense Passage Retrieval, BM25 |
| **L3** | Distillation / è’¸é¦å±‚ | Knowledge extraction + skill library + versioning | `distiller.py` | Knowledge Distillation, Experience Replay |
| **L4** | Decision / 决策进化层 | 付费专属决策与进化引擎 | `paid/l4/` | Skeptic Agent、多模型共识、walk-forward |
| **L5** | Orchestration / 编排层 | 基础免费，高级编排付费 | `free/l5/`, `paid/l5/` | DAG Scheduling, Reinforcement Learning |

---

## Key Features / ä¸»è¦ç‰¹æ€§

- **Cross-model switching / è·¨æ¨¡åž‹åˆ‡æ¢** â€” Gemini, GPT-4, Claude, DeepSeek seamless context transfer
- **Hallucination prevention / é˜²å¹»è§‰é—¨æŽ§** â€” Skeptic verification blocks unverified conclusions
- **Auto experience distillation / è‡ªåŠ¨ç»éªŒè’¸é¦** â€” Each iteration refines reusable rules
- **Loop command / Loop é—­çŽ¯å‘½ä»¤** â€” `gcc-evo loop` runs the full improvement cycle
- **Dashboard / å¯è§†åŒ–çœ‹æ¿** â€” Single HTML file, no installation required
- **Research-backed / è®ºæ–‡é©±åŠ¨** â€” 30 arXiv papers (score 4.0+) inform core algorithms

---

## Quick Start / å¿«é€Ÿå¼€å§‹

```bash
# Install / å®‰è£…
pip install -e .

# Initialize / åˆå§‹åŒ–
gcc-evo init

# View commands / æŸ¥çœ‹å‘½ä»¤
gcc-evo --help

# Run improvement loop / è¿è¡Œæ”¹å–„é—­çŽ¯
gcc-evo loop GCC-0001 --once

# Health check / å¥åº·æ£€æŸ¥
gcc-evo health
```

See [QUICKSTART.md](QUICKSTART.md) | [QUICKSTART.en.md](QUICKSTART.en.md)

---

## Use Cases / é€‚ç”¨åœºæ™¯

- **Software improvement / è½¯ä»¶ç³»ç»Ÿæ”¹å–„** â€” Bug tracking, performance optimization
- **Industrial AI diagnostics / å·¥ä¸š AI è¾…åŠ©è¯Šæ–­** â€” Equipment monitoring, process optimization
- **Any long-term AI task / è·¨ä¼šè¯ AI åº”ç”¨** â€” Any scenario requiring accumulated experience

**Evolution path / è¿›åŒ–è·¯çº¿**: Product â†’ General Engine â†’ Custom Engine â†’ Improve Product

---

## Command Reference / å‘½ä»¤å‚è€ƒ

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

## Numbers / æ•°å­—

| Metric / æŒ‡æ ‡ | Value / æ•°å€¼ |
|------|------|
| Development time / å¼€å‘æ—¶é—´ | ~240 hours |
| Lines of code / ä»£ç è¡Œæ•° | 6,000+ |
| Submodules / å­æ¨¡å—æ•° | 45 |
| Referenced papers / å¼•ç”¨è®ºæ–‡ | 30 (arXiv score 4.0+) |
| Supported models / æ”¯æŒæ¨¡åž‹ | Gemini / GPT-4 / Claude / DeepSeek |

---

## Pricing / 定价

| Tier / 层级 | Price / 价格 | Included / 包含内容 | Best For / 适用对象 |
|------|------|--------|--------|
| **Community** | Free Forever | UI + L0 Phase 1 + 基础 L1/L2/L3/L5 | Personal/Academic/<$1M |
| **Evolve** | $29/month | + L0 Phase 2-4 | 个人开发者/进阶实验 |
| **Pro** | $79/month | + 高级 L1/L2/L3 | 专业团队/顾问/知识产品 |
| **Enterprise** | $500+/month | + L4 + 高级 L5 + DA + 企业扩展 | 企业部署 |

See [PRICING.md](PRICING.md) | [PRICING.en.md](PRICING.en.md) | [LAYER_STRUCTURE.md](LAYER_STRUCTURE.md)

---

## License / è®¸å¯è¯

- **Base**: [BUSL 1.1](LICENSE)
- **Change Date**: 2028-05-01 â†’ auto-converts to Apache 2.0
- **Community Forever Free**: Individuals, academics, <$1M annual revenue

---

## Contributing / è´¡çŒ®

See [CONTRIBUTING.md](CONTRIBUTING.md) | [CONTRIBUTING.en.md](CONTRIBUTING.en.md)

Welcome issues and PRs. For core architecture changes, please open an issue first.

---

## Roadmap

```
v5.325 (Current) â€” Loop + Skeptic + Multi-Model
    â†“
v5.5 (Q2 2026) â€” Distributed Memory + Real-time Collaboration
    â†“
v6.0 (Q4 2026) â€” Apache 2.0 + Full Open Source
    â†“
v7.0 (2027) â€” Plugin Ecosystem + Enterprise Features
```

---

## Citation

```bibtex
@software{gcc_evo_2026,
  author = {baodexiang},
  title = {gcc-evo: AI Self-Evolution Engine},
  year = {2026},
  url = {https://github.com/baodexiang/gcc-evolution},
  version = {5.325}
}
```

---

**Made with â¤ï¸ by [baodexiang](https://github.com/baodexiang)**





