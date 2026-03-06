# CHANGELOG — gcc-evo Version History

All notable changes to this project are documented in this file. This project follows [Semantic Versioning](https://semver.org/).

---

## [5.300] — 2026-03-05

### ✨ New Features

- **L0 Setup Layer** — `gcc-evo setup` interactive wizard, mandatory L0 gate before every loop
  - `SessionConfig` — stores `.GCC/state/session_config.json`, validates 3 required fields
  - `gcc-evo setup KEY-010` — interactive wizard for goal/criteria/config
  - `gcc-evo setup --show` — display current config
  - `gcc-evo setup --edit` — edit individual fields
  - `gcc-evo setup --reset` — delete config
- **L6 Observation Layer** — complete real-time observation framework
  - `EventBus` — thread-safe singleton event bus, <5ms emit, persists to `.GCC/logs/events.jsonl`
  - `LayerEmitter` — semantic emit interfaces for all 7 layers (`emit_l0~l6`, `layer_start/done/error`)
  - `RunTracer` — tracks full flow snapshots per loop_id
  - `DashboardServer` — local HTTP server (port 7842), SSE real-time push, 15s heartbeat
- **Real-time Dashboard** — 7-layer status visualization, dark theme, SSE auto-reconnect, run history panel
- **`gcc-evo loop --dry-run`** — skip L0 gate check (for testing)

### 🎯 Improvements

- `gcc-evo version` — now shows L6:Observation layer status
- `gcc-evo loop` — adds L0 gate: invalid config rejects startup and prompts `gcc-evo setup`
- `cli.py` — new `setup` subcommand routing

### 🔧 Technical Details

- **EventBus `_writer_loop`** — cross-batch `unflushed` list accumulation, flushes at threshold, final flush on thread exit
- **ThreadingHTTPServer** — `daemon_threads=True`, SSE threads don't block `stop()`; `stop()` calls `shutdown()` + `server_close()` for port reuse
- **RunTracer `_on_event`** — auto-infers layer status (started/done/error/skipped) without manual `mark_layer` calls

---

## [5.295] — 2026-03-03

### ✨ New Features

- **Loop Closure Command** — One-click complete improvement cycle (6 automated steps)
  - `gcc-evo loop GCC-0001 --once` — Single iteration
  - `gcc-evo loop GCC-0001` — Continuous (5-minute auto-repeat)
- **Cross-Model Switching** — Seamless switching between Gemini/ChatGPT/Claude/DeepSeek
- **Plugin Signal Quality Closure** — Automatic tracking and improvement of plugin signal quality
  - Signal recording + 4H backfill validation + Phase promotion/demotion + Daily quality report
- **Skeptic Verification Gate** — Prevents unverified conclusions from entering memory
- **Visual Dashboard** — Single HTML file, no installation required

### 🐛 Bug Fixes

- Environment variable leakage — Sensitive variables now display as `[MASKED]` in error messages
- N-structure gate quality threshold — Adjusted 0.65 → 0.55, allowing normal pullback edge signals
- x4 large-timeframe direction limit — Disabled overly restrictive conditions, improved accuracy
- Fixed label display issue — Fixed rules now show as resolved even without pattern matches

### 🎯 Improvements

- **Memory Management** — Three-tier hierarchy (sensory/short/long) optimizes long-term retention
- **Retrieval Accuracy** — RAG + semantic search + KNN historical similarity
- **Experience Distillation** — Automatic extraction of reusable rules into SkillBank
- **Audit Logging** — Structured JSON logs recording all LLM interactions

### 📚 Documentation

- README.md — Complete project background and architecture explanation
- QUICKSTART.md — 10-minute getting started guide
- CONTRIBUTING.md — Contribution workflow and CLA process
- SECURITY.md — Security policies and best practices
- LICENSE — BUSL 1.1 + Additional Use Grant
- CONTRIBUTOR_LICENSE_AGREEMENT.md — Individual CLA
- ENTERPRISE_CONTRIBUTOR_LICENSE_AGREEMENT.md — Corporate CLA

### 🔧 Technical Details

- **Memory Tiers** — Sensory (latest events) / Short-term (recent discussion) / Long-term (summarized knowledge)
- **Retriever** — Semantic similarity + KNN time-weighted + BM25 keyword matching
- **Distiller** — Experience cards → SkillBank with automatic versioning
- **Skeptic** — Confidence threshold (default 0.75) + Human anchor verification
- **Pipeline** — DAG task scheduling + dependency management + retry logic

---

## [5.290] — 2026-03-01

### ✨ New Features

- **gcc-evo v5.290** — First complete production release of AI Self-Evolution Engine
- **Loop Command Binding** — Associate tasks with improvement cycles
- **Open Source Release Package** — Complete P0 documentation and toolset
  - Paper Engine — Paper analysis and knowledge distillation
  - Vision Analyzer — Image recognition and morphology analysis
  - Plugin Registry — Plugin system and scoring mechanism

### 🎯 Improvements

- Repository structure reorganization — Separated `.GCC/`, `opensource/`, `modules/`
- Version numbering standardization — Adopted `v X.YZZ` format (v5.290, v5.295)
- Logging output standardization — Unified `[v5.xxx]` and `[symbol]` prefixes

### 📦 Releases

- gcc_evolution_v5290.zip — Open source documentation and license package
- GCC_Beginners_Guide_v5_290.docx — English user manual
- GCC_新手完全手册_v5_290.docx — Chinese user manual

---

## [4.98] — 2025-12-15

### ✨ New Features

- **Initial gcc-evo** — GCC Evolution Engine prototype version
- **Basic Memory System** — In-session token management
- **Simple Retrieval** — Keyword-based content lookup
- **Experience Card System** — Manual creation and management

### 📝 Architecture Design

- Single-layer memory (session-level)
- Keyword matching
- Static skill library
- Manual operation driven

---

## [3.0] — 2025-10-01

### ✨ New Features

- **First Generation GCC** — Bug tracking and improvement record system
  - Issue management
  - Fix logging
  - Validation workflow

### 📝 Prototype

- Text file storage
- Manual organization
- Basic statistics

---

## Version Evolution Roadmap

```
v3.0 (Bug Tracker)
    ↓
v4.0 (Improvement Manager)
    ↓
v4.98 (GCC Prototype)
    ↓
v5.0 (Memory Tiers Introduction)
    ↓
v5.100 (Retrieval Layer)
    ↓
v5.200 (Distillation Engine)
    ↓
v5.290 (Open Source Release)
    ↓
v5.295 (Current) — Loop + Skeptic + Multi-Model
    ↓
v6.0 (Planned) — Distributed Memory + Real-time Collaboration
```

---

## Upgrade Guide

### From v5.290 to v5.295

**No breaking changes**, all APIs remain backward compatible.

```bash
# Update package
pip install --upgrade gcc-evo

# Verify version
gcc-evo version
# Output: gcc-evo v5.295

# Run migration (optional, automatic)
gcc-evo migrate
```

**New feature usage:**
```bash
# Enable Loop closure
gcc-evo loop GCC-0001 --once

# Specify LLM model
gcc-evo loop GCC-0001 --provider gemini --once

# Continuous operation (production)
gcc-evo loop GCC-0001 &
```

---

## Known Issues and Limitations

### v5.295

- **Token Window** — Single conversation still limited by LLM context (claude-opus: 200K tokens)
  - Mitigation: Automatic memory compression and retrieval strategies
- **LLM Hallucination** — Models may generate false content
  - Mitigation: Skeptic verification gate (confidence < 0.75 blocks)
- **Cold Start** — New projects require initialization on first run
  - Mitigation: `gcc-evo init` automatic setup

### Performance

- **First Retrieval** — ~2-3 seconds (KNN index construction)
- **Distillation** — ~5-10 seconds (LLM invocation)
- **Loop Cycle** — 5-15 minutes (depends on task complexity)

---

## Contributors

This project is developed by baodexiang with contributions from:

- Research and paper selection — arXiv paper analysis (30+ papers rated 4.0+)
- Plugin system design — Plugin Registry and KNN matching
- User feedback and testing — Trading system and industrial diagnostics

---

## License

- **v5.295 and earlier** — BUSL 1.1 (auto-converts to Apache-2.0 on 2028-05-01)
- **v6.0 and later** — Apache 2.0 (from planning stage)

See [LICENSE](LICENSE) file for details.

---

## Feedback and Reporting

- 🐛 **Bug Reports** — GitHub Issues or baodexiang@hotmail.com
- 💬 **Feature Requests** — GitHub Discussions
- 🔐 **Security Issues** — security@gcc-evo.dev (private)

---

**Last Updated**: 2026-03-03
**Version**: 5.295
**Maintainer**: baodexiang <baodexiang@hotmail.com>
