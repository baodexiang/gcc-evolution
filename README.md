# gcc-evo v5.320

**AI Self-Evolution Engine** â€” Persistent memory + continuous learning for LLM agents

[![Tests](https://github.com/baodexiang/gcc-evo/workflows/Tests/badge.svg)](https://github.com/baodexiang/gcc-evo/actions/workflows/test.yml)
[![Release](https://github.com/baodexiang/gcc-evo/workflows/Release/badge.svg)](https://github.com/baodexiang/gcc-evo/actions/workflows/release.yml)
[![CodeQL](https://github.com/baodexiang/gcc-evo/workflows/CodeQL%20Security%20Analysis/badge.svg)](https://github.com/baodexiang/gcc-evo/actions/workflows/codeql.yml)
[![License](https://img.shields.io/badge/license-BUSL%201.1-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
[![PyPI](https://img.shields.io/pypi/v/gcc-evo.svg)](https://pypi.org/project/gcc-evo/)

---

## What is gcc-evo?

**gcc-evo** is an open-source framework that enables LLM agents to:

- **Remember** â€” Three-tier persistent memory system (sensory/short-term/long-term)
- **Learn** â€” Automatic experience distillation into reusable skills
- **Improve** â€” Continuous self-refinement through automated loops
- **Decide** â€” Skeptic verification gate to prevent hallucinations
- **Collaborate** â€” Seamless switching between Claude, GPT-4, Gemini, DeepSeek

### Core Components

- **Memory Tiers** â€” Sensory (24h) â†’ Short-term (7 days) â†’ Long-term (persistent summaries)
- **Retrieval** â€” Semantic similarity + KNN temporal weighting + BM25 keywords
- **Distillation** â€” Experience cards â†’ SkillBank with automatic versioning
- **Skeptic Gate** â€” Confidence threshold (default 0.75) + Human-in-the-loop validation
- **Loop Command** â€” Single `gcc-evo loop GCC-0001` runs 6-step improvement cycle

---

## Key Features

### ðŸŽ¯ Loop Closure (v5.295)
```bash
gcc-evo loop GCC-0001 --once      # Single iteration
gcc-evo loop GCC-0001             # Continuous (5-minute cycles)
gcc-evo loop GCC-0001 --provider gemini  # Switch LLM provider
```

**6 Automated Steps:**
1. **Task Audit** â€” Analyze execution logs + identify gaps
2. **Experience Cards** â€” Extract reusable patterns
3. **SkillBank** â€” Version and store skills
4. **Skeptic Verification** â€” Human validation gate
5. **Distillation** â€” Compress knowledge
6. **Daily Report** â€” Summary + next actions

### ðŸ§  Three-Tier Memory
```
Sensory Layer (24h events)
  â†“ (retrieval when queried)
Short-term Layer (7-day discussion)
  â†“ (consolidation)
Long-term Layer (permanent summaries)
```

### ðŸ”€ Multi-Model Support
```bash
# Switch providers seamlessly
gcc-evo loop GCC-0001 --provider claude|gpt|gemini|deepseek --once
```

### ðŸ›¡ï¸ Skeptic Verification
- Prevents low-confidence decisions from entering memory
- Requires human review for unverified conclusions
- Confidence threshold configurable (default: 0.75)

### ðŸ“Š Dashboard
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
# Output: gcc-evo v5.320
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
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚                         Application Layer                         â”‚
â”‚                   gcc-evo loop / commands                        â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                           â”‚
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â–¼â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚  Layer 5: Orchestration (Automation & Scheduling)                 â”‚
â”‚  â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”â”‚
â”‚  â”‚  Loop Closure Engine (6-step automation):                    â”‚â”‚
â”‚  â”‚  Observe â†’ Audit â†’ Extract â†’ Verify â†’ Distill â†’ Report     â”‚â”‚
â”‚  â”‚                                                              â”‚â”‚
â”‚  â”‚  Pipeline DAG Scheduling / Task Dependencies / Retry Logic   â”‚â”‚
â”‚  â”‚  Modules: pipeline.py, loop_engine.py                        â”‚â”‚
â”‚  â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                           â”‚ (Structured instructions + Verification)
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â–¼â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚  Layer 4: Decision Making (LLM Reasoning & Verification)          â”‚
â”‚  â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”â”‚
â”‚  â”‚  Skeptic Verification Gate:                                 â”‚â”‚
â”‚  â”‚  - Confidence threshold judgment (default: 0.75)            â”‚â”‚
â”‚  â”‚  - Human-in-the-Loop validation                            â”‚â”‚
â”‚  â”‚  - Hallucination prevention mechanism                       â”‚â”‚
â”‚  â”‚                                                              â”‚â”‚
â”‚  â”‚  LLM decision reasoning + Multi-model comparison             â”‚â”‚
â”‚  â”‚  Modules: skeptic.py, multi_model.py                        â”‚â”‚
â”‚  â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                           â”‚ (Decision requests + Verification)
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â–¼â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚  Layer 3: Distillation (Knowledge Extraction & Compression)       â”‚
â”‚  â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”â”‚
â”‚  â”‚  Experience Cards â†’ SkillBank Knowledge Library:            â”‚â”‚
â”‚  â”‚  - Convert observations into reusable rules                 â”‚â”‚
â”‚  â”‚  - Automatic version management                            â”‚â”‚
â”‚  â”‚  - Accuracy tracking across versions                       â”‚â”‚
â”‚  â”‚  - Mark deprecated rules                                   â”‚â”‚
â”‚  â”‚                                                              â”‚â”‚
â”‚  â”‚  LLM synthesis + Knowledge compression + Skill indexing     â”‚â”‚
â”‚  â”‚  Modules: distiller.py, skillbank.py, experience_card.py   â”‚â”‚
â”‚  â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                           â”‚ (Rule queries + Retrieval parameters)
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â–¼â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚  Layer 2: Retrieval (Multi-Strategy RAG)                          â”‚
â”‚  â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”â”‚
â”‚  â”‚  Hybrid Retrieval Strategy:                                 â”‚â”‚
â”‚  â”‚  â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”â”‚â”‚
â”‚  â”‚  â”‚ Semantic Similarity  Temporal Weighting  Keyword Match  â”‚â”‚â”‚
â”‚  â”‚  â”‚   (embedding)       (recency bias)     (exact match)   â”‚â”‚â”‚
â”‚  â”‚  â”‚        50%               30%               20%          â”‚â”‚â”‚
â”‚  â”‚  â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜â”‚â”‚
â”‚  â”‚                                                              â”‚â”‚
â”‚  â”‚  RAG pipeline + Context compression + Results ranking       â”‚â”‚
â”‚  â”‚  Modules: retriever.py, rag_pipeline.py                     â”‚â”‚
â”‚  â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                           â”‚ (Queries + Query type)
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â–¼â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚  Layer 1: Memory (Persistent Storage & Hierarchy)                 â”‚
â”‚  â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”â”‚
â”‚  â”‚  Three-Tier Memory System:                                  â”‚â”‚
â”‚  â”‚                                                              â”‚â”‚
â”‚  â”‚  Sensory (Perception):  24-hour - Latest events             â”‚â”‚
â”‚  â”‚  â”œâ”€ Data: Raw logs, real-time events                        â”‚â”‚
â”‚  â”‚  â”œâ”€ Access: High-frequency, fast                            â”‚â”‚
â”‚  â”‚  â””â”€ Management: Auto-expiration                             â”‚â”‚
â”‚  â”‚                                                              â”‚â”‚
â”‚  â”‚  Short-term (Working Memory): 7-day - Recent decisions      â”‚â”‚
â”‚  â”‚  â”œâ”€ Data: Decision records, context, insights               â”‚â”‚
â”‚  â”‚  â”œâ”€ Access: Semantic search + temporal weighting            â”‚â”‚
â”‚  â”‚  â””â”€ Management: Periodic compression                        â”‚â”‚
â”‚  â”‚                                                              â”‚â”‚
â”‚  â”‚  Long-term (Knowledge Base): Permanent - Verified rules     â”‚â”‚
â”‚  â”‚  â”œâ”€ Data: Refined rules, experience cards, SkillBank        â”‚â”‚
â”‚  â”‚  â”œâ”€ Access: Exact queries + version control                 â”‚â”‚
â”‚  â”‚  â””â”€ Management: Immutable archive                           â”‚â”‚
â”‚  â”‚                                                              â”‚â”‚
â”‚  â”‚  Storage: JSON/JSONL / SQLite / Redis (extensible)         â”‚â”‚
â”‚  â”‚  Modules: memory_tiers.py, storage.py                       â”‚â”‚
â”‚  â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                           â–²
                           â”‚ (Read/Write operations)
                â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”´â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
                â”‚                     â”‚
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
    â†“
[L1] Store in Sensory Layer
    â†“
[L2] Retrieve related history (semantic + temporal)
    â†“
[L3] Load verified SkillBank rules
    â†“
[L4] LLM reasoning + Skeptic verification
    â†“
[L3] Distill new rules â†’ SkillBank (if confidence >= 0.75)
    â†“
[L1] Update Short-term and Long-term Layers
    â†“
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
from gcc_evolution import SkepticValidator

skeptic = SkepticValidator()
decision = {
    "signal": "BUY",
    "action": "BUY_PARTIAL",
    "confidence": 0.82,
    "conditions": ["+trend_up", "+volume_confirm"],
    "reasoning": "Trend and volume align for a partial long entry.",
}
validation = skeptic.validate(decision)
if validation.is_valid:
    apply_decision(decision)
else:
    request_human_review(validation.issues)

# Layer 5: Orchestration operations
from gcc_evolution.L5_orchestration.loop_engine_base import SimpleImprovementLoop

loop = SimpleImprovementLoop()
result = loop.run_iteration()
print(result.iteration_id, result.phase.value)
```

---

## Command Reference

### Project Management
```bash
gcc-evo init [--project NAME]         # Initialize project
gcc-evo version                       # Show version
gcc-evo setup KEY-001                 # Configure L0 session settings
gcc-evo setup --show                  # Show current L0 settings
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
```

### Debugging
```bash
GCC_LOG_LEVEL=DEBUG gcc-evo loop GCC-0001 --once  # Debug one loop run
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

# Load environment then run gcc-evo
export ANTHROPIC_API_KEY=sk-ant-...
gcc-evo init
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

- **v5.295** â€” BUSL 1.1 (Business Source License)
  - Free for non-commercial use
  - Free for companies < $1M annual revenue
  - Commercial license available
  - Auto-converts to Apache 2.0 on 2028-05-01

- **v6.0+** â€” Apache 2.0 (Full open source)

See [LICENSE](LICENSE) for details.

---

## Support & Contributing

### Documentation
- **[QUICKSTART.en.md](QUICKSTART.en.md)** â€” 10-minute setup guide
- **[TUTORIAL.en.md](TUTORIAL.en.md)** â€” In-depth learning guide
- **[CHANGELOG.en.md](CHANGELOG.en.md)** â€” Version history

### Getting Help
- ðŸ› **Bug Reports** â†’ [GitHub Issues](https://github.com/baodexiang/gcc-evo/issues)
- ðŸ’¬ **Discussions** â†’ [GitHub Discussions](https://github.com/baodexiang/gcc-evo/discussions)
- ðŸ” **Security Issues** â†’ security@gcc-evo.dev (private)

### Contributing
- See [CONTRIBUTING.en.md](CONTRIBUTING.en.md)
- Sign [CLA](CONTRIBUTOR_LICENSE_AGREEMENT.md) for PRs
- Follow [SECURITY.en.md](SECURITY.en.md) guidelines

---

## Roadmap

```
v5.320 (Current) â€” Loop + Skeptic + Multi-Model
    â†“
v5.5 (Q2 2026) â€” Distributed Memory + Real-time Collaboration
    â†“
v6.0 (Q4 2026) â€” Apache 2.0 + Full Open Source
    â†“
v7.0 (2027) â€” Plugin Ecosystem + Enterprise Features
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
  version = {5.320}
}
```

---

## Pricing & Licensing

### Four-Tier Pricing Model

| Tier | Price | Included | Best For |
|------|-------|----------|----------|
| **Community** | ðŸ†“ Forever Free | L1-L5 foundation + Direction Anchor | Personal/Academic/<$1M revenue |
| **Evolve** | $29/month | + KNN Evolution + Walk-Forward Testing | Small teams/traders |
| **Pro** | $79/month | + Signal Evolution + Advanced SkillBank | Institutions/trading desks |
| **Enterprise** | $500+/month | + Private deployment + Vertical optimization | Large funds/custom solutions |

ðŸ“– **Full Details**: [PRICING.md](PRICING.md) | [PRICING.en.md](PRICING.en.md)

### License
- **Base**: [BUSL 1.1](LICENSE) with Additional Use Grant
- **Change Date**: 2028-05-01 â†’ auto-converts to Apache 2.0
- **Community Forever Free**: Individuals, academics, <$1M annual revenue
- **See also**: [LICENSE](LICENSE) file for full terms

---

**Made with â¤ï¸ by [baodexiang](https://github.com/baodexiang)**

[English](README.md) | [ä¸­æ–‡](README.zh.md)


