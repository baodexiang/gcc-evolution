# gcc-evo v5.300

**AI Self-Evolution Engine** — Persistent memory + continuous learning for LLM agents

[![Tests](https://github.com/baodexiang/gcc-evo/workflows/Tests/badge.svg)](https://github.com/baodexiang/gcc-evo/actions/workflows/test.yml)
[![Release](https://github.com/baodexiang/gcc-evo/workflows/Release/badge.svg)](https://github.com/baodexiang/gcc-evo/actions/workflows/release.yml)
[![CodeQL](https://github.com/baodexiang/gcc-evo/workflows/CodeQL%20Security%20Analysis/badge.svg)](https://github.com/baodexiang/gcc-evo/actions/workflows/codeql.yml)
[![License](https://img.shields.io/badge/license-BUSL%201.1-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
[![PyPI](https://img.shields.io/pypi/v/gcc-evo.svg)](https://pypi.org/project/gcc-evo/)

---

## What is gcc-evo?

**gcc-evo** is an open-source framework that enables LLM agents to:

- **Remember** — Three-tier persistent memory system (sensory/short-term/long-term)
- **Learn** — Automatic experience distillation into reusable skills
- **Improve** — Continuous self-refinement through automated loops
- **Decide** — Skeptic verification gate to prevent hallucinations
- **Collaborate** — Seamless switching between Claude, GPT-4, Gemini, DeepSeek

### Core Components

- **Memory Tiers** — Sensory (24h) → Short-term (7 days) → Long-term (persistent summaries)
- **Retrieval** — Semantic similarity + KNN temporal weighting + BM25 keywords
- **Distillation** — Experience cards → SkillBank with automatic versioning
- **Skeptic Gate** — Confidence threshold (default 0.75) + Human-in-the-loop validation
- **Loop Command** — Single `gcc-evo loop GCC-0001` runs 6-step improvement cycle

---

## Key Features

### 🎯 Loop Closure (v5.295)
```bash
gcc-evo loop GCC-0001 --once      # Single iteration
gcc-evo loop GCC-0001             # Continuous (5-minute cycles)
gcc-evo loop GCC-0001 --provider gemini  # Switch LLM provider
```

**6 Automated Steps:**
1. **Task Audit** — Analyze execution logs + identify gaps
2. **Experience Cards** — Extract reusable patterns
3. **SkillBank** — Version and store skills
4. **Skeptic Verification** — Human validation gate
5. **Distillation** — Compress knowledge
6. **Daily Report** — Summary + next actions

### 🧠 Three-Tier Memory
```
Sensory Layer (24h events)
  ↓ (retrieval when queried)
Short-term Layer (7-day discussion)
  ↓ (consolidation)
Long-term Layer (permanent summaries)
```

### 🔀 Multi-Model Support
```bash
# Switch providers seamlessly
gcc-evo loop GCC-0001 --provider claude|gpt|gemini|deepseek --once
```

### 🛡️ Skeptic Verification
- Prevents low-confidence decisions from entering memory
- Requires human review for unverified conclusions
- Confidence threshold configurable (default: 0.75)

### 📊 Dashboard
```bash
# Single-file HTML dashboard (no installation needed)
open .GCC/dashboard.html
```

---

## Installation

### Via PyPI (Recommended)
```bash
pip install gcc-evo
gcc-evo version
# Output: gcc-evo v5.300
```

### From Source
```bash
git clone https://github.com/baodexiang/gcc-evo.git
cd gcc-evo/opensource
pip install -e ".[dev]"
gcc-evo --help
```

### With Optional Features
```bash
# Documentation generation
pip install -e ".[docs]"

# Local LLM support (Ollama)
pip install -e ".[local-llm]"

# All features
pip install -e ".[dev,docs,local-llm]"
```

---

## Quick Start (10 minutes)

### 1. Initialize Project
```bash
gcc-evo init --project my-agent
cd my-agent
```

### 2. Create First Task
```bash
gcc-evo pipe task "Improve error handling" -k KEY-001 -m auth -p P0
```

### 3. Run Loop
```bash
gcc-evo loop GCC-0001 --once
```

### 4. Review Results
```bash
# View dashboard
open .GCC/dashboard.html

# View logs
cat state/audit/*.jsonl | tail -50

# Check skills learned
cat state/skillbank.jsonl | jq '.skill_name' | sort | uniq
```

### 5. Continue Iteration
```bash
gcc-evo loop GCC-0002 --provider gemini --once
```

---

## Five-Layer Architecture Design

### System Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│                         Application Layer                         │
│                   gcc-evo loop / commands                        │
└──────────────────────────┬───────────────────────────────────────┘
                           │
┌──────────────────────────▼────────────────────────────────────────┐
│  Layer 5: Orchestration (Automation & Scheduling)                 │
│  ┌──────────────────────────────────────────────────────────────┐│
│  │  Loop Closure Engine (6-step automation):                    ││
│  │  Observe → Audit → Extract → Verify → Distill → Report     ││
│  │                                                              ││
│  │  Pipeline DAG Scheduling / Task Dependencies / Retry Logic   ││
│  │  Modules: pipeline.py, loop_engine.py                        ││
│  └──────────────────────────────────────────────────────────────┘│
└──────────────────────────┬───────────────────────────────────────┘
                           │ (Structured instructions + Verification)
┌──────────────────────────▼────────────────────────────────────────┐
│  Layer 4: Decision Making (LLM Reasoning & Verification)          │
│  ┌──────────────────────────────────────────────────────────────┐│
│  │  Skeptic Verification Gate:                                 ││
│  │  - Confidence threshold judgment (default: 0.75)            ││
│  │  - Human-in-the-Loop validation                            ││
│  │  - Hallucination prevention mechanism                       ││
│  │                                                              ││
│  │  LLM decision reasoning + Multi-model comparison             ││
│  │  Modules: skeptic.py, multi_model.py                        ││
│  └──────────────────────────────────────────────────────────────┘│
└──────────────────────────┬───────────────────────────────────────┘
                           │ (Decision requests + Verification)
┌──────────────────────────▼────────────────────────────────────────┐
│  Layer 3: Distillation (Knowledge Extraction & Compression)       │
│  ┌──────────────────────────────────────────────────────────────┐│
│  │  Experience Cards → SkillBank Knowledge Library:            ││
│  │  - Convert observations into reusable rules                 ││
│  │  - Automatic version management                            ││
│  │  - Accuracy tracking across versions                       ││
│  │  - Mark deprecated rules                                   ││
│  │                                                              ││
│  │  LLM synthesis + Knowledge compression + Skill indexing     ││
│  │  Modules: distiller.py, skillbank.py, experience_card.py   ││
│  └──────────────────────────────────────────────────────────────┘│
└──────────────────────────┬───────────────────────────────────────┘
                           │ (Rule queries + Retrieval parameters)
┌──────────────────────────▼────────────────────────────────────────┐
│  Layer 2: Retrieval (Multi-Strategy RAG)                          │
│  ┌──────────────────────────────────────────────────────────────┐│
│  │  Hybrid Retrieval Strategy:                                 ││
│  │  ┌─────────────────────────────────────────────────────────┐││
│  │  │ Semantic Similarity  Temporal Weighting  Keyword Match  │││
│  │  │   (embedding)       (recency bias)     (exact match)   │││
│  │  │        50%               30%               20%          │││
│  │  └─────────────────────────────────────────────────────────┘││
│  │                                                              ││
│  │  RAG pipeline + Context compression + Results ranking       ││
│  │  Modules: retriever.py, rag_pipeline.py                     ││
│  └──────────────────────────────────────────────────────────────┘│
└──────────────────────────┬───────────────────────────────────────┘
                           │ (Queries + Query type)
┌──────────────────────────▼────────────────────────────────────────┐
│  Layer 1: Memory (Persistent Storage & Hierarchy)                 │
│  ┌──────────────────────────────────────────────────────────────┐│
│  │  Three-Tier Memory System:                                  ││
│  │                                                              ││
│  │  Sensory (Perception):  24-hour - Latest events             ││
│  │  ├─ Data: Raw logs, real-time events                        ││
│  │  ├─ Access: High-frequency, fast                            ││
│  │  └─ Management: Auto-expiration                             ││
│  │                                                              ││
│  │  Short-term (Working Memory): 7-day - Recent decisions      ││
│  │  ├─ Data: Decision records, context, insights               ││
│  │  ├─ Access: Semantic search + temporal weighting            ││
│  │  └─ Management: Periodic compression                        ││
│  │                                                              ││
│  │  Long-term (Knowledge Base): Permanent - Verified rules     ││
│  │  ├─ Data: Refined rules, experience cards, SkillBank        ││
│  │  ├─ Access: Exact queries + version control                 ││
│  │  └─ Management: Immutable archive                           ││
│  │                                                              ││
│  │  Storage: JSON/JSONL / SQLite / Redis (extensible)         ││
│  │  Modules: memory_tiers.py, storage.py                       ││
│  └──────────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────┘
                           ▲
                           │ (Read/Write operations)
                ┌──────────┴──────────┐
                │                     │
          User Input            Execution Feedback
```

### Five-Layer Details

| Layer | Name | Core Responsibility | Key Modules | Academic Foundation |
|-------|------|---------------------|-------------|-------------------|
| **L1** | Memory | Persistent storage + 3-tier hierarchy | `memory_tiers.py` | RAG, Memory Networks |
| **L2** | Retrieval | Hybrid search + semantic + temporal + keywords | `retriever.py` | Dense Passage Retrieval, BM25 |
| **L3** | Distillation | Knowledge extraction + skill library + versioning | `distiller.py` | Knowledge Distillation, Experience Replay |
| **L4** | Decision | LLM reasoning + hallucination prevention + Human-in-loop | `skeptic.py` | Uncertainty Quantification, Constitutional AI |
| **L5** | Orchestration | Loop closure + task scheduling + automation | `pipeline.py` | DAG Scheduling, Reinforcement Learning |

### Data Flow Example

```
Input Observation (logs, events)
    ↓
[L1] Store in Sensory Layer
    ↓
[L2] Retrieve related history (semantic + temporal)
    ↓
[L3] Load verified SkillBank rules
    ↓
[L4] LLM reasoning + Skeptic verification
    ↓
[L3] Distill new rules → SkillBank (if confidence >= 0.75)
    ↓
[L1] Update Short-term and Long-term Layers
    ↓
Output Decision + Generate Report
```

### Layer Integration Example

```python
# Layer 1: Memory operations
from gcc_evolution.memory import MemoryTiers

memory = MemoryTiers()
memory.sensory.record({'event': 'trade_executed', 'price': 145.5})
memory.short_term.store({'decision': 'increase_threshold', 'confidence': 0.82})
memory.long_term.add_skill({'skill_id': 'SK-001', 'pattern': '...'})

# Layer 2: Retrieval operations
from gcc_evolution.retrieval import HybridRetriever

retriever = HybridRetriever(semantic=0.5, temporal=0.3, keyword=0.2)
results = retriever.search("threshold adjustment strategy", top_k=5)

# Layer 3: Distillation operations
from gcc_evolution.distiller import Distiller

distiller = Distiller()
skill = distiller.extract_skill(experience={'observation': '...', 'outcome': '...'})
skillbank.add_skill(skill)

# Layer 4: Decision making operations
from gcc_evolution.skeptic import SkepticGate

skeptic = SkepticGate(threshold=0.75)
decision = llm.make_decision(context=context)
if skeptic.verify(decision):
    apply_decision(decision)
else:
    request_human_review(decision)

# Layer 5: Orchestration operations
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

## Command Reference

### Project Management
```bash
gcc-evo init [--project NAME]         # Initialize project
gcc-evo version                       # Show version
gcc-evo config set API_KEY <key>      # Set environment
```

### Task Management
```bash
gcc-evo pipe task <TITLE> -k KEY-001 -m module -p P0|P1|P2
gcc-evo pipe list                     # Show all tasks
gcc-evo pipe status GCC-0001          # Task status
```

### Loop Execution
```bash
gcc-evo loop GCC-0001 --once          # Single iteration
gcc-evo loop GCC-0001                 # Continuous (5min cycles)
gcc-evo loop GCC-0001 --provider gemini  # Specify LLM
```

### Memory Management
```bash
gcc-evo memory compact                # Compress memory
gcc-evo memory export                 # Backup state
gcc-evo memory migrate                # Upgrade schema
```

### Debugging
```bash
gcc-evo audit --symbol TSLA --days 7  # Audit logs
gcc-evo debug --trace                 # Enable trace logging
gcc-evo health                        # System health check
```

---

## Use Cases

### 1. Trading System Self-Improvement
```bash
# Monitor trading signals
gcc-evo loop GCC-0001 --once

# Identifies:
# - Low-accuracy signal types
# - Parameter optimization opportunities
# - Risk patterns to avoid

# Output: Refined trading rules in SkillBank
```

### 2. API Client Optimization
```bash
# Track API errors
gcc-evo loop GCC-0002 --once

# Learns:
# - Common failure patterns
# - Retry strategies
# - Rate-limit handling

# Result: Improved resilience
```

### 3. Data Pipeline Monitoring
```bash
# Monitor data quality
gcc-evo loop GCC-0003 --once

# Detects:
# - Anomalies
# - Source reliability
# - Transformation issues

# Action: Auto-correcting pipeline
```

---

## Configuration

### Environment Variables
```bash
# LLM Providers
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=...
DEEPSEEK_API_KEY=...

# Optional
GCC_LOG_LEVEL=INFO|DEBUG
GCC_MEMORY_TTL=7  # days
GCC_SKEPTIC_THRESHOLD=0.75
GCC_LOOP_INTERVAL=300  # seconds
```

### Config File (`.env`)
```bash
# Create file in project root
touch .env
echo "ANTHROPIC_API_KEY=sk-ant-..." >> .env

# Load
gcc-evo init --config .env
```

---

## Development

### Install Development Environment
```bash
git clone https://github.com/baodexiang/gcc-evo.git
cd gcc-evo/opensource
make install-dev
```

### Run Tests
```bash
make test              # Full test suite with coverage
make test-unit        # Unit tests only
make test-int         # Integration tests
```

### Code Quality
```bash
make lint             # flake8, mypy, pylint
make format           # auto-format with black, isort
make security         # bandit, safety
```

### Build Documentation
```bash
make docs             # Build Sphinx docs
make docs-serve       # Serve on localhost:8000
```

### Create Distribution
```bash
make build            # Create wheel + sdist
make clean            # Remove artifacts
```

---

## Licensing

- **v5.295** — BUSL 1.1 (Business Source License)
  - Free for non-commercial use
  - Free for companies < $1M annual revenue
  - Commercial license available
  - Auto-converts to Apache 2.0 on 2028-05-01

- **v6.0+** — Apache 2.0 (Full open source)

See [LICENSE](LICENSE) for details.

---

## Support & Contributing

### Documentation
- **[QUICKSTART.en.md](opensource/QUICKSTART.en.md)** — 10-minute setup guide
- **[TUTORIAL.en.md](opensource/TUTORIAL.en.md)** — In-depth learning guide
- **[CHANGELOG.en.md](opensource/CHANGELOG.en.md)** — Version history

### Getting Help
- 🐛 **Bug Reports** → [GitHub Issues](https://github.com/baodexiang/gcc-evo/issues)
- 💬 **Discussions** → [GitHub Discussions](https://github.com/baodexiang/gcc-evo/discussions)
- 🔐 **Security Issues** → security@gcc-evo.dev (private)

### Contributing
- See [CONTRIBUTING.en.md](opensource/CONTRIBUTING.en.md)
- Sign [CLA](CONTRIBUTOR_LICENSE_AGREEMENT.md) for PRs
- Follow [SECURITY.en.md](opensource/SECURITY.en.md) guidelines

---

## Roadmap

```
v5.300 (Current) — Loop + Skeptic + Multi-Model
    ↓
v5.5 (Q2 2026) — Distributed Memory + Real-time Collaboration
    ↓
v6.0 (Q4 2026) — Apache 2.0 + Full Open Source
    ↓
v7.0 (2027) — Plugin Ecosystem + Enterprise Features
```

---

## Citation

If you use gcc-evo in research or production, please cite:

```bibtex
@software{gcc_evo_2026,
  author = {baodexiang},
  title = {gcc-evo: AI Self-Evolution Engine},
  year = {2026},
  url = {https://github.com/baodexiang/gcc-evo},
  version = {5.300}
}
```

---

## Pricing & Licensing

### Four-Tier Pricing Model

| Tier | Price | Included | Best For |
|------|-------|----------|----------|
| **Community** | 🆓 Forever Free | L1-L5 foundation + Direction Anchor | Personal/Academic/<$1M revenue |
| **Evolve** | $29/month | + KNN Evolution + Walk-Forward Testing | Small teams/traders |
| **Pro** | $79/month | + Signal Evolution + Advanced SkillBank | Institutions/trading desks |
| **Enterprise** | $500+/month | + Private deployment + Vertical optimization | Large funds/custom solutions |

📖 **Full Details**: [PRICING.md](PRICING.md) | [PRICING.en.md](PRICING.en.md)

### License
- **Base**: [BUSL 1.1](LICENSE) with Additional Use Grant
- **Change Date**: 2028-05-01 → auto-converts to Apache 2.0
- **Community Forever Free**: Individuals, academics, <$1M annual revenue
- **See also**: [LICENSE](LICENSE) file for full terms

---

**Made with ❤️ by [baodexiang](https://github.com/baodexiang)**

[English](README.en.md) | [中文](README.md)
