# CHANGELOG â€” gcc-evo Version History

All notable changes to this project are documented in this file. This project follows [Semantic Versioning](https://semver.org/).

---

## [5.310] — 2026-03-06

### 🔧 Changed

- Release version bumped to **5.310** (`setup.py`, `gcc_evolution/__init__.py`, dashboard label, init template version field).
- Updated user manual deliverables to `v5_310`:
  - `GCC_Beginners_Guide_v5_310.docx`
  - `GCC_新手完全手册_v5_310.docx`
- Regenerated source release archive as `gcc_evolution_v5310.zip` to include latest formula updates.

---

## [5.305] — 2026-03-06

### 🔧 Changed

- Release version bumped to **5.305** (`setup.py`, `gcc_evolution/__init__.py`, init template version field).
- Updated open-source module header version tags from `v5.300`/`v5.301` to `v5.305` for consistency.
- Updated user manual deliverables to `v5_305`:
  - `GCC_Beginners_Guide_v5_305.docx`
  - `GCC_新手完全手册_v5_305.docx`
- Regenerated source release archive as `gcc_evolution_v5305.zip`.

---

## [5.301] — 2026-03-06

### 🔧 Fixed

- **Added gcc-evo commit command**: when committing with GCC-xxxx and optional Sx, the CLI now auto-syncs .GCC/pipeline/tasks.json so dashboard task status updates immediately after commit.
- **Auto handoff trigger**: when a task/step reference is present, the CLI now attempts gcc-evo ho create automatically (warning-only on failure; commit remains successful).
- **Version bump**: upgraded package version from 5.300 to 5.301 (__init__.py, setup.py, dashboard version label, init template version).

---

## [5.300] â€” 2026-03-05

### âœ¨ New Features

- **L0 Setup Layer** â€” `gcc-evo setup` interactive wizard, mandatory L0 gate before every loop
  - `SessionConfig` â€” stores `.GCC/state/session_config.json`, validates 3 required fields
  - `gcc-evo setup KEY-010` â€” interactive wizard for goal/criteria/config
  - `gcc-evo setup --show` â€” display current config
  - `gcc-evo setup --edit` â€” edit individual fields
  - `gcc-evo setup --reset` â€” delete config
- **L6 Observation Layer** â€” complete real-time observation framework
  - `EventBus` â€” thread-safe singleton event bus, <5ms emit, persists to `.GCC/logs/events.jsonl`
  - `LayerEmitter` â€” semantic emit interfaces for all 7 layers (`emit_l0~l6`, `layer_start/done/error`)
  - `RunTracer` â€” tracks full flow snapshots per loop_id
  - `DashboardServer` â€” local HTTP server (port 7842), SSE real-time push, 15s heartbeat
- **Real-time Dashboard** â€” 7-layer status visualization, dark theme, SSE auto-reconnect, run history panel
- **`gcc-evo loop --dry-run`** â€” skip L0 gate check (for testing)

### ðŸŽ¯ Improvements

- `gcc-evo version` â€” now shows L6:Observation layer status
- `gcc-evo loop` â€” adds L0 gate: invalid config rejects startup and prompts `gcc-evo setup`
- `cli.py` â€” new `setup` subcommand routing

### ðŸ”§ Technical Details

- **EventBus `_writer_loop`** â€” cross-batch `unflushed` list accumulation, flushes at threshold, final flush on thread exit
- **ThreadingHTTPServer** â€” `daemon_threads=True`, SSE threads don't block `stop()`; `stop()` calls `shutdown()` + `server_close()` for port reuse
- **RunTracer `_on_event`** â€” auto-infers layer status (started/done/error/skipped) without manual `mark_layer` calls

---

## [5.295] â€” 2026-03-03

### âœ¨ New Features

- **Loop Closure Command** â€” One-click complete improvement cycle (6 automated steps)
  - `gcc-evo loop GCC-0001 --once` â€” Single iteration
  - `gcc-evo loop GCC-0001` â€” Continuous (5-minute auto-repeat)
- **Cross-Model Switching** â€” Seamless switching between Gemini/ChatGPT/Claude/DeepSeek
- **Plugin Signal Quality Closure** â€” Automatic tracking and improvement of plugin signal quality
  - Signal recording + 4H backfill validation + Phase promotion/demotion + Daily quality report
- **Skeptic Verification Gate** â€” Prevents unverified conclusions from entering memory
- **Visual Dashboard** â€” Single HTML file, no installation required

### ðŸ› Bug Fixes

- Environment variable leakage â€” Sensitive variables now display as `[MASKED]` in error messages
- N-structure gate quality threshold â€” Adjusted 0.65 â†’ 0.55, allowing normal pullback edge signals
- x4 large-timeframe direction limit â€” Disabled overly restrictive conditions, improved accuracy
- Fixed label display issue â€” Fixed rules now show as resolved even without pattern matches

### ðŸŽ¯ Improvements

- **Memory Management** â€” Three-tier hierarchy (sensory/short/long) optimizes long-term retention
- **Retrieval Accuracy** â€” RAG + semantic search + KNN historical similarity
- **Experience Distillation** â€” Automatic extraction of reusable rules into SkillBank
- **Audit Logging** â€” Structured JSON logs recording all LLM interactions

### ðŸ“š Documentation

- README.md â€” Complete project background and architecture explanation
- QUICKSTART.md â€” 10-minute getting started guide
- CONTRIBUTING.md â€” Contribution workflow and CLA process
- SECURITY.md â€” Security policies and best practices
- LICENSE â€” BUSL 1.1 + Additional Use Grant
- CONTRIBUTOR_LICENSE_AGREEMENT.md â€” Individual CLA
- ENTERPRISE_CONTRIBUTOR_LICENSE_AGREEMENT.md â€” Corporate CLA

### ðŸ”§ Technical Details

- **Memory Tiers** â€” Sensory (latest events) / Short-term (recent discussion) / Long-term (summarized knowledge)
- **Retriever** â€” Semantic similarity + KNN time-weighted + BM25 keyword matching
- **Distiller** â€” Experience cards â†’ SkillBank with automatic versioning
- **Skeptic** â€” Confidence threshold (default 0.75) + Human anchor verification
- **Pipeline** â€” DAG task scheduling + dependency management + retry logic

---

## [5.290] â€” 2026-03-01

### âœ¨ New Features

- **gcc-evo v5.290** â€” First complete production release of AI Self-Evolution Engine
- **Loop Command Binding** â€” Associate tasks with improvement cycles
- **Open Source Release Package** â€” Complete P0 documentation and toolset
  - Paper Engine â€” Paper analysis and knowledge distillation
  - Vision Analyzer â€” Image recognition and morphology analysis
  - Plugin Registry â€” Plugin system and scoring mechanism

### ðŸŽ¯ Improvements

- Repository structure reorganization â€” Separated `.GCC/`, `opensource/`, `modules/`
- Version numbering standardization â€” Adopted `v X.YZZ` format (v5.290, v5.295)
- Logging output standardization â€” Unified `[v5.xxx]` and `[symbol]` prefixes

### ðŸ“¦ Releases

- gcc_evolution_v5290.zip â€” Open source documentation and license package
- GCC_Beginners_Guide_v5_290.docx â€” English user manual
- GCC_æ–°æ‰‹å®Œå…¨æ‰‹å†Œ_v5_290.docx â€” Chinese user manual

---

## [4.98] â€” 2025-12-15

### âœ¨ New Features

- **Initial gcc-evo** â€” GCC Evolution Engine prototype version
- **Basic Memory System** â€” In-session token management
- **Simple Retrieval** â€” Keyword-based content lookup
- **Experience Card System** â€” Manual creation and management

### ðŸ“ Architecture Design

- Single-layer memory (session-level)
- Keyword matching
- Static skill library
- Manual operation driven

---

## [3.0] â€” 2025-10-01

### âœ¨ New Features

- **First Generation GCC** â€” Bug tracking and improvement record system
  - Issue management
  - Fix logging
  - Validation workflow

### ðŸ“ Prototype

- Text file storage
- Manual organization
- Basic statistics

---

## Version Evolution Roadmap

```
v3.0 (Bug Tracker)
    â†“
v4.0 (Improvement Manager)
    â†“
v4.98 (GCC Prototype)
    â†“
v5.0 (Memory Tiers Introduction)
    â†“
v5.100 (Retrieval Layer)
    â†“
v5.200 (Distillation Engine)
    â†“
v5.290 (Open Source Release)
    â†“
v5.295 (Current) â€” Loop + Skeptic + Multi-Model
    â†“
v6.0 (Planned) â€” Distributed Memory + Real-time Collaboration
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

- **Token Window** â€” Single conversation still limited by LLM context (claude-opus: 200K tokens)
  - Mitigation: Automatic memory compression and retrieval strategies
- **LLM Hallucination** â€” Models may generate false content
  - Mitigation: Skeptic verification gate (confidence < 0.75 blocks)
- **Cold Start** â€” New projects require initialization on first run
  - Mitigation: `gcc-evo init` automatic setup

### Performance

- **First Retrieval** â€” ~2-3 seconds (KNN index construction)
- **Distillation** â€” ~5-10 seconds (LLM invocation)
- **Loop Cycle** â€” 5-15 minutes (depends on task complexity)

---

## Contributors

This project is developed by baodexiang with contributions from:

- Research and paper selection â€” arXiv paper analysis (30+ papers rated 4.0+)
- Plugin system design â€” Plugin Registry and KNN matching
- User feedback and testing â€” Trading system and industrial diagnostics

---

## License

- **v5.295 and earlier** â€” BUSL 1.1 (auto-converts to Apache-2.0 on 2028-05-01)
- **v6.0 and later** â€” Apache 2.0 (from planning stage)

See [LICENSE](LICENSE) file for details.

---

## Feedback and Reporting

- ðŸ› **Bug Reports** â€” GitHub Issues or baodexiang@hotmail.com
- ðŸ’¬ **Feature Requests** â€” GitHub Discussions
- ðŸ” **Security Issues** â€” security@gcc-evo.dev (private)

---

**Last Updated**: 2026-03-03
**Version**: 5.295
**Maintainer**: baodexiang <baodexiang@hotmail.com>

