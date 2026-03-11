# gcc-evo v5.400

**AI Self-Evolution Engine** — Persistent memory + continuous learning framework for LLM agents.

[![License: BUSL-1.1](https://img.shields.io/badge/License-BUSL--1.1-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9+-green.svg)](https://www.python.org)

## What is gcc-evo?

gcc-evo is a framework that gives LLM agents the ability to **learn from experience and improve over time**. Instead of starting fresh every session, your agent accumulates knowledge, distills patterns, and evolves its decision-making.

### Core Capabilities

- **L0 Governance** — Safe bootstrap with prerequisite gates and quality checks
- **L1 Memory** — Three-tier memory (sensory → short-term → long-term) with configurable storage backends
- **L2 Retrieval** — Hybrid retrieval (semantic + keyword + temporal) with RAG pipeline
- **L3 Distillation** — Extract reusable experience cards from raw interactions
- **L5 Orchestration** — 6-step self-improvement loop (Observe → Analyze → Hypothesize → Test → Improve → Integrate)
- **UI Dashboard** — Real-time WebSocket dashboard with event bus and execution tracing

## Installation

```bash
pip install gcc-evo
gcc-evo version
```

### From Source

```bash
git clone https://github.com/baodexiang/gcc-evolution.git
cd gcc-evolution
pip install -e "."
```

## Quick Start

```bash
# Initialize project
gcc-evo init

# Setup an improvement key
gcc-evo setup KEY-001

# Bootstrap L0 governance gate
gcc-evo l0 scaffold
gcc-evo l0 check
gcc-evo l0 set-prereq data_quality --status pass --evidence "validated"
gcc-evo l0 set-prereq deterministic_rules --status pass --evidence "validated"
gcc-evo l0 set-prereq mathematical_filters --status pass --evidence "validated"

# Create and manage pipeline tasks
gcc-evo pipe task "Improve error handling" -k KEY-001 -m core -p P1
gcc-evo pipe list
gcc-evo pipe status GCC-0001

# Memory operations
gcc-evo memory compact
gcc-evo memory export

# Health check
gcc-evo health

# Run a demo evolution loop
gcc-evo loop DEMO-001 --once --dry-run
```

## Architecture

```
gcc_evolution/
  free/
    ui/        — Dashboard, event bus, execution tracer
    l0/        — Governance, setup wizard, prerequisites
    l1/        — Memory tiers (sensory/short/long-term) + storage
    l2/        — Hybrid retriever + RAG pipeline
    l3/        — Experience distiller + card generator
    l5/        — Self-improvement loop + DAG pipeline
```

### Theory Foundation

gcc-evo's design is grounded in peer-reviewed research. All referenced papers are included in [`gcc/papers/pdf/`](gcc/papers/pdf/):

| Paper | arXiv | Used In |
|-------|-------|---------|
| DeepSeek Engram (Memory Update & Decay) | [2601.07372](https://arxiv.org/abs/2601.07372) | L1 Memory equations |
| POMDP Safety Constraint (Mem-as-Action) | [2601.12538](https://arxiv.org/abs/2601.12538) | Direction Anchor, Memory Policy, Retrieval Gate |
| History Is Not Enough (Drift-Aware) | [2601.10143](https://arxiv.org/abs/2601.10143) | Drift detection, adaptive windows |
| PUCT Multi-Layer Tree Search | [2603.04735](https://arxiv.org/abs/2603.04735) | Decision tree search |
| Autonomous Market Intelligence | [2601.11958](https://arxiv.org/abs/2601.11958) | Nowcasting signals |
| FINSABER | [2505.07078](https://arxiv.org/abs/2505.07078) | Market regime classification |
| Time-Inhomogeneous Volatility Aversion | [2602.12030](https://arxiv.org/abs/2602.12030) | Risk management |
| Three-Perspective Verification | [2407.09468](https://arxiv.org/abs/2407.09468) | Multi-angle validation |

Formula implementations: [`gcc/papers/formulas/`](gcc/papers/formulas/) (P001–P006 with full test coverage)

### Open-Source Interfaces (Apache 2.0)

8 theoretical interfaces (IRS-001~008) are published under Apache 2.0:

- `mem_action.py` — Memory-as-Action protocol
- `retrieval_policy.py` — Agentic RAG gate with counterfactual rewards
- `direction_anchor.py` — Constitutional governance validator
- `holdout.py` — Holdout splitter + skeptic gate
- `fault_tolerance.py` — Phase isolation + heartbeat monitor
- `shapley.py` — Monte Carlo Shapley attribution
- `divergence_monitor.py` — Fleiss' Kappa consistency checking
- `reasoning_trace.py` — Execution trace logging

## Paid Layers (not included)

| Layer | Purpose |
|-------|---------|
| **L4** | Multi-model ensemble + skeptic gate + benchmark acceptance |
| **DA** | Direction Anchor constitutional governance enforcement |

Available at [gcc-evo.dev/licensing](https://gcc-evo.dev/licensing)

## License

[Business Source License 1.1](LICENSE) — Free for personal, academic, and small business use (<$1M revenue). Converts to Apache 2.0 on May 1, 2028.

## Documents

- [Quick Start (EN)](QUICKSTART.en.md) | [中文说明](README.zh.md)
- [Architecture](ARCHITECTURE.en.md) | [Layer Structure](LAYER_STRUCTURE.md)
- [Pricing](PRICING.en.md) | [Framework Boundary](FRAMEWORK_BOUNDARY.en.md)
- [Contributing](CONTRIBUTING.en.md) | [Security](SECURITY.en.md)
