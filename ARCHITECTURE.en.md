# gcc-evo Five-Layer Architecture

> Complete five-layer framework design, implementation logic, and data flow explanation

---

> Canonical v5.330 commercial boundary: see [LAYER_STRUCTURE.md](LAYER_STRUCTURE.md). Release-facing split is `5 Free + 3 Paid`: free foundation = `UI + L0 + L1 + L2 + L3`, paid core = `L4 + L5 + DA`.

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [L1: Memory Layer](#l1-memory-layer)
3. [L2: Retrieval Layer](#l2-retrieval-layer)
4. [L3: Distillation Layer](#l3-distillation-layer)
5. [L4: Decision Layer](#l4-decision-layer)
6. [L5: Orchestration Layer](#l5-orchestration-layer)
7. [Inter-Layer Collaboration](#inter-layer-collaboration)
8. [Implementation Guide](#implementation-guide)

---

## Architecture Overview

### Why Five Layers?

gcc-evo's five-layer architecture is not arbitrary—it systematically addresses these questions:

1. **L1 Memory Layer** — "How does AI remember information across sessions?"
   - Traditional: Concatenate entire history (Token explosion)
   - gcc-evo: Three-tier hierarchical storage with on-demand retrieval

2. **L2 Retrieval Layer** — "How to quickly find relevant information from thousands of records?"
   - Traditional: Full-text search or random sampling (low accuracy)
   - gcc-evo: Hybrid retrieval combining semantic + temporal + keyword (85%+ hit rate)

3. **L3 Distillation Layer** — "How does AI learn from its own experience?"
   - Traditional: No distillation mechanism (experience lost)
   - gcc-evo: Automatic rule extraction and skill library (continuous learning)

4. **L4 Decision Layer** — "How to prevent AI hallucinations from polluting memory?"
   - Traditional: No verification (error propagation)
   - gcc-evo: Skeptic gate + human-in-the-loop validation

5. **L5 Orchestration Layer** — "How to automate the entire improvement process?"
   - Traditional: Manual scripts (error-prone)
   - gcc-evo: DAG scheduling + 6-step closure loop (zero-touch automation)

### Relationship Diagram

```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃  L5: Orchestration                   ┃
┃  ├─ 6-step closure                   ┃
┃  ├─ DAG scheduling                   ┃
┃  └─ Loop automation                  ┃
┗━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━┛
                 │
┏━━━━━━━━━━━━━━━━┻━━━━━━━━━━━━━━━━━━━┓
┃  L4: Decision Making                 ┃
┃  ├─ LLM reasoning                    ┃
┃  ├─ Skeptic gate                     ┃
┃  └─ Human validation                 ┃
┗━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━┛
                 │
┏━━━━━━━━━━━━━━━━┻━━━━━━━━━━━━━━━━━━━┓
┃  L3: Distillation                    ┃
┃  ├─ Experience → SkillBank           ┃
┃  ├─ Auto versioning                  ┃
┃  └─ Accuracy tracking                ┃
┗━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━┛
                 │
┏━━━━━━━━━━━━━━━━┻━━━━━━━━━━━━━━━━━━━┓
┃  L2: Retrieval                       ┃
┃  ├─ Semantic (50%)                   ┃
┃  ├─ Temporal (30%)                   ┃
┃  └─ Keyword (20%)                    ┃
┗━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━┛
                 │
┏━━━━━━━━━━━━━━━━┻━━━━━━━━━━━━━━━━━━━┓
┃  L1: Memory                          ┃
┃  ├─ Sensory (24h)                    ┃
┃  ├─ Short-term (7d)                  ┃
┃  └─ Long-term (∞)                    ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
```

---

## L1: Memory Layer

### Design Philosophy

**Problem**: How to remember information across sessions when LLM context is limited (Claude: 200K tokens)?

**Solution**: Three-tier hierarchy + automatic lifecycle management

### Three-Tier Design

#### Sensory Layer (24-hour window)

**Purpose**: Store latest raw observations and events

```
Timeline:
  Now:        ← New events recorded (auto-timestamped)
  1h ago:     ← 1 hour old observations
  12h ago:    ← 12 hours old decision records
  23h 59m:    ← About to expire (kept for completeness)
  24h 1m:     ← Auto-cleanup (permanent deletion)
```

**Data types**:
- Raw logs: Trade executions, API calls, error messages
- Events: What the system did
- Observations: What the AI saw

**Storage structure**:
```python
{
  "timestamp": 1709476800,        # Unix timestamp
  "event_type": "trade_executed", # Event category
  "symbol": "TSLA",              # Context
  "price": 145.50,
  "data": {...},                 # Raw data
  "expires_at": 1709563200       # Auto-delete after 24h
}
```

**Access characteristics**:
- ✅ High-frequency writes (per second)
- ✅ Fast queries (indexed access)
- ❌ Not used in RAG retrieval (too fresh, lacks context)
- ✅ Used for latest state snapshot

---

#### Short-term Layer (7-day window)

**Purpose**: Store recent decisions, discussion history, and context

```
Timeline:
  Now:        ← Today's decisions
  1d ago:     ← Yesterday's discussions
  3d ago:     ← 3-day-old improvement attempts
  6d 23h:     ← About to compress (still retrievable)
  7d:         ← Expiration triggers compression to Long-term
```

**Data types**:
- Decision records: "What was proposed" + "Why"
- Discussion context: Q&A pairs
- Insights: AI's analysis results

**Storage structure**:
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

**Access characteristics**:
- ✅ Medium-frequency writes (per minute)
- ✅ Semantic search (embedding index)
- ✅ Temporal weighting (recent data weighted higher)
- ✅ Used for RAG context

---

#### Long-term Layer (Permanent storage)

**Purpose**: Store verified rules and skill library

```
Timeline:
  v1: SK-001 (2026-01-15)  ← Initial (72% accuracy)
  v2: SK-001 (2026-02-10)  ← Improved (81% accuracy)
  v3: SK-001 (2026-03-01)  ← Current (87% accuracy)
  ...permanent storage (version history accessible)
```

**Data types**:
- Verified rules: Passed human or multiple validations
- Experience cards: Reusable knowledge units
- SkillBank: Versioned skill collection

**Storage structure**:
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

**Access characteristics**:
- ✅ Low-frequency writes (validation-based)
- ✅ Exact queries (ID/version lookup)
- ✅ Immutable archive (history permanently preserved)
- ✅ Used for rule library and knowledge retrieval

---

## L2: Retrieval Layer

### Design Philosophy

**Problem**: How to quickly find 5-10 relevant records from thousands?

**Solution**: Hybrid retrieval combining three methods (no single-point dependency)

### Three Retrieval Methods

#### Method 1: Semantic Similarity (50% weight)

**Principle**: Use embedding model to compute semantic distance

```
Query: "How to reduce false signals?"
       ↓ embedding
      [0.45, -0.23, 0.87, ...]  (768-dimensional)

Memories in library:
1. "Ways to reduce false signals"    → similarity 0.89 ✓✓✓ (most relevant)
2. "MACD threshold adjustment"       → similarity 0.76 ✓✓
3. "Trade frequency control"         → similarity 0.42 ✓
4. "Risk management rules"           → similarity 0.35 ✗
```

**Implementation**:
```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer('all-MiniLM-L6-v2')

# Index time
for memory in memories:
    memory['embedding'] = model.encode(memory['text'])
    save_to_index(memory)

# Retrieval time
query_vector = model.encode(query)
results = index.search(query_vector, top_k=10)
```

**Advantages**:
- ✅ Captures semantic relationships ("signal quality" ≈ "accuracy")
- ✅ Robust (handles different phrasings)

**Disadvantages**:
- ❌ Ignores temporal information
- ❌ Expensive computation

---

#### Method 2: Temporal Weighting (KNN, 30% weight)

**Principle**: Recent data is more relevant, decays with time

```
Temporal weight curve:
Now       ← weight 1.0
1 day ago ← weight 0.95
3 days    ← weight 0.80
7 days    ← weight 0.50
14 days   ← weight 0.10 (deprecated)

Calculation:
final_score = base_score × temporal_weight

Example:
  Record A: base 0.75, time_weight 1.0  → final 0.75
  Record B: base 0.80, time_weight 0.3  → final 0.24
```

**Implementation**:
```python
def temporal_weight(timestamp, half_life_hours=24):
    """Exponential decay weight"""
    age_hours = (time.time() - timestamp) / 3600
    return math.exp(-0.693 * age_hours / half_life_hours)

# Apply during retrieval
results = []
for memory in candidates:
    semantic_score = 0.89
    temporal_score = temporal_weight(memory['timestamp'])
    final_score = semantic_score * temporal_score
    results.append((memory, final_score))
```

**Advantages**:
- ✅ Reflects data freshness
- ✅ Fast computation

**Disadvantages**:
- ❌ New but irrelevant data ranks high
- ❌ Ignores content quality

---

#### Method 3: BM25 Keyword Matching (20% weight)

**Principle**: Exact keyword matching (search engine classic)

```
Query: ["MACD", "threshold", "adjust"]

Memories:
1. "MACD threshold adjusted from 0.8 to 0.7"
   Match rate: 3/3 (100%)  → score 1.0 ✓✓✓

2. "MACD indicator explanation"
   Match rate: 1/3 (33%)   → score 0.33 ✓

3. "Profit/risk ratio calculation"
   Match rate: 0/3 (0%)    → score 0.0 ✗
```

**Implementation**:
```python
from rank_bm25 import BM25Okapi

# Index time
corpus = [memory['text'] for memory in memories]
bm25 = BM25Okapi([doc.split() for doc in corpus])

# Retrieval time
query_tokens = query.split()
bm25_scores = bm25.get_scores(query_tokens)
```

**Advantages**:
- ✅ Exact matches work well
- ✅ Fast, low memory
- ✅ Sensitive to domain vocabulary

**Disadvantages**:
- ❌ Ignores semantics ("reduce errors" ≠ "lower failure rate")
- ❌ Requires text processing

---

### Hybrid Retrieval Fusion

```
Step 1: Run three searches
├─ Semantic search   → [0.89, 0.76, 0.42, ...]
├─ Temporal weighting → [1.00, 0.95, 0.80, ...]
└─ BM25 search      → [1.00, 0.50, 0.30, ...]

Step 2: Normalize to [0-1] range
├─ Semantic: max_normalize(...)
├─ Temporal: already [0-1]
└─ BM25: max_normalize(...)

Step 3: Weighted fusion (50% + 30% + 20%)
final_score = semantic*0.5 + temporal*0.3 + bm25*0.2

Step 4: Sort and return top-k
```

**Python implementation**:
```python
class HybridRetriever:
    def __init__(self, weights=(0.5, 0.3, 0.2)):
        self.w_semantic, self.w_temporal, self.w_keyword = weights

    def search(self, query, top_k=5):
        # 1. Three searches
        semantic = self.semantic_search(query)
        temporal = self.temporal_search(query)
        keyword = self.keyword_search(query)

        # 2. Fusion
        all_ids = set(semantic.keys() | temporal.keys() | keyword.keys())
        final_scores = {}

        for mid in all_ids:
            score = (
                semantic.get(mid, 0) * self.w_semantic +
                temporal.get(mid, 0) * self.w_temporal +
                keyword.get(mid, 0) * self.w_keyword
            )
            final_scores[mid] = score

        # 3. Rank and return
        ranked = sorted(final_scores.items(),
                       key=lambda x: x[1],
                       reverse=True)
        return [self.memory[mid] for mid, _ in ranked[:top_k]]
```

---

## L3: Distillation Layer

### Design Philosophy

**Problem**: How to make AI learn from experience instead of starting from scratch each time?

**Solution**: Automatic rule extraction + versioning + accuracy tracking

### Three-Stage Distillation Process

#### Stage 1: Observation → Experience Card

**Input**: Complete context of one interaction

```
Example observation:
{
  "timestamp": 1709476800,
  "context": "TSLA triggered MACD signal at 10:30",
  "observation": "MACD divergence at resistance, but false breakout",
  "action_taken": "Skipped entry, avoided loss",
  "outcome": "Avoided $500 loss",
  "model": "claude-3.5",
  "confidence": 0.85
}
```

**Extraction (via LLM)**:
```
LLM Prompt:
"Extract a reusable rule from:
Observation: {observation}
Outcome: {outcome}

Return JSON with:
- pattern (what was discovered)
- condition (trigger condition)
- action (recommended action)
- confidence (your confidence)"

LLM Response:
{
  "pattern": "MACD divergence at resistance → high false breakout",
  "condition": "When MACD diverges at relative resistance",
  "action": "Wait for confirmation, don't rush entry",
  "confidence": 0.87
}
```

**Output**: Experience card (structured knowledge unit)

---

#### Stage 2: Experience Card → Skill Rule

**Input**: Multiple accumulated experience cards

```
Multiple cards:
1. MACD divergence → false breakout
2. RSI extremes → reversal probability
3. Bollinger band edge → pullback likely
...
```

**Synthesis (via LLM)**:
```
LLM Prompt:
"Synthesize a general rule from these experience cards:
[list all cards]

Return unified rule covering common pattern"

LLM Response:
{
  "skill_id": "SK-001",
  "name": "False_Signal_Detection",
  "rule": "Multiple indicators extreme + price near key level = reversal likely",
  "applicability": "Daily and higher timeframes",
  "success_rate": 0.82,
  "exceptions": ["Strong trends", "Major events"]
}
```

**Output**: Skill rule (reusable high-level knowledge)

---

#### Stage 3: Skill Rule → SkillBank (Version Management)

**Concept**: Skill library with version history

```
SK-001 evolution:

v1 (2026-01-15):
  Rule: "MACD divergence → false breakout"
  Accuracy: 72%
  Samples: 45
  Note: "Basic version, high false positives"

v2 (2026-02-10):
  Rule: "MACD divergence + RSI extreme → false breakout"
  Accuracy: 81%
  Samples: 120
  Change: "Added RSI confirmation, reduced false alarms"

v3 (2026-03-01):  ← Current
  Rule: "MACD divergence + RSI extreme + near support/resistance → false breakout"
  Accuracy: 87%
  Samples: 250
  Change: "Added price level filter, further improvement"
```

**Version management rules**:
```
Before submitting new rule:
✓ Clear description (5 sentences max)
✓ Programmable conditions (not vague)
✓ Data-validated (not intuition)
✓ Sample size >= 30 (statistical significance)
✓ Accuracy >= previous version - 5% (avoid regression)

After approval:
1. Create new version (v_old + 1)
2. Mark old as deprecated
3. Activate in SkillBank
4. Log changelog
```

---

## L4: Decision Layer

### Design Philosophy

**Problem**: How to prevent wrong LLM outputs from polluting memory?

**Solution**: Skeptic gate + human validation + multi-model comparison

### Skeptic Verification Mechanism

#### Confidence Calculation

```
Decision confidence composed of three parts:

confidence = (accuracy_history * 0.4) +
             (current_reasoning * 0.4) +
             (human_anchor * 0.2)

1. accuracy_history (40%):
   - How accurate was this model before?
   - Success rate on similar tasks
   - Source: Historical decision records

2. current_reasoning (40%):
   - How thorough is this reasoning?
   - Sufficient evidence?
   - Considered counterarguments?
   - Source: LLM reasoning process

3. human_anchor (20%):
   - Was there human validation?
   - Level of detail?
   - Source: Human annotations
```

#### Gate Rules

```python
class SkepticGate:
    THRESHOLD = 0.75  # Configurable

    def verify(self, decision):
        confidence = self.calculate_confidence(decision)

        if confidence >= self.THRESHOLD:
            return True, "APPROVED"  # Write to memory
        elif confidence >= 0.6:
            return None, "REQUIRES_REVIEW"  # Request human
        else:
            return False, "REJECTED"  # Decline
```

**Three outcomes**:

| Confidence | Action | Explanation |
|-----------|--------|-------------|
| >= 0.75 | ✅ Auto-approve | Write to Short-term |
| 0.60-0.75 | ⚠️ Human review | Await confirmation |
| < 0.60 | ❌ Reject | Don't write, suggest reasoning |

---

#### Multi-Model Comparison

**Strategy**: Compare outputs from multiple LLMs on important decisions

```python
def multi_model_decision(task, models=['claude', 'gpt', 'gemini']):
    """Compare multiple models independently"""
    decisions = {}
    confidences = {}

    for model_name in models:
        model = get_model(model_name)

        # Independent reasoning
        decision = model.reason(task)
        confidence = model.get_confidence()

        decisions[model_name] = decision
        confidences[model_name] = confidence

    # Analyze consensus
    consensus = check_consensus(decisions)  # Do models agree?
    avg_confidence = sum(confidences.values()) / len(models)

    # High consensus + high confidence = approve
    if consensus and avg_confidence > 0.75:
        return "APPROVED", avg_confidence
    else:
        return "REQUIRES_REVIEW", avg_confidence
```

**Example**:
```
Task: "Should TSLA be bought at $145?"

Claude-3.5:
  Decision: "Wait for pullback, possible further downside"
  Confidence: 0.82
  Reason: "RSI 50-60, not extreme"

GPT-4:
  Decision: "Can start small position"
  Confidence: 0.68
  Reason: "Monthly support nearby"

Gemini:
  Decision: "Don't buy yet, wait for confirmation"
  Confidence: 0.79
  Reason: "MACD not confirmed"

Analysis:
- Consensus: Claude + Gemini agree (66%)
- Avg confidence: 0.76
- Result: Pass Skeptic gate ✅
  (Medium consensus + sufficient confidence)
```

---

## L5: Orchestration Layer

### Design Philosophy

**Problem**: How to automate 6-step improvement without manual operation?

**Solution**: DAG scheduling + 6-step closure loop + automation

### Six-Step Loop Closure

```
Step 1: OBSERVE (collect events)
  ├─ Read recent logs
  ├─ Extract key events
  └─ Identify anomalies
       ↓

Step 2: AUDIT (analyze)
  ├─ Analyze log problems
  ├─ Compute metrics
  └─ Identify opportunities
       ↓

Step 3: EXTRACT (distill rules)
  ├─ Extract rules from problems
  ├─ Generate experience cards
  └─ Synthesize skills
       ↓

Step 4: VERIFY (validate)
  ├─ Skeptic confidence check
  ├─ Request human review (if needed)
  └─ Multi-model comparison (if important)
       ↓

Step 5: DISTILL (write skills)
  ├─ Write validated rules to SkillBank
  ├─ Update version numbers
  └─ Record accuracy baseline
       ↓

Step 6: REPORT (summarize)
  ├─ Generate summary
  ├─ List items requiring review
  └─ Suggest next direction
```

### DAG Task Scheduling

**Concept**: Represent task dependencies as a directed acyclic graph

```
    ┌─────────────┐
    │  OBSERVE    │ (collect logs)
    └──────┬──────┘
           │
    ┌──────▼──────┐
    │   AUDIT     │ (analyze)
    └──────┬──────┘
           │
    ┌──────▼──────┐
    │  EXTRACT    │ (distill)
    └──────┬──────┘
           │
    ┌──────▼──────┐
    │  VERIFY     │ (validate)
    └──┬──────┬───┘
       │      │
  ┌────▼─┐  ┌─▼──────┐
  │PASS  │  │REQUIRES│
  │      │  │REVIEW  │
  └────┬─┘  └─┬──────┘
       │      │ (human input)
       └──┬───┘
          │
    ┌─────▼──────┐
    │  DISTILL   │ (write skills)
    └─────┬──────┘
          │
    ┌─────▼──────┐
    │   REPORT   │ (summarize)
    └────────────┘
```

**Implementation**:
```python
class LoopEngine:
    def __init__(self, task_id):
        self.task_id = task_id
        self.dag = self.build_dag()

    def build_dag(self):
        """Build task dependency graph"""
        return {
            'observe': {'deps': [], 'executor': self.observe},
            'audit': {'deps': ['observe'], 'executor': self.audit},
            'extract': {'deps': ['audit'], 'executor': self.extract},
            'verify': {'deps': ['extract'], 'executor': self.verify},
            'distill': {'deps': ['verify'], 'executor': self.distill},
            'report': {'deps': ['distill'], 'executor': self.report}
        }

    def run_once(self):
        """Execute one complete loop"""
        results = {}
        executed = set()

        while len(executed) < len(self.dag):
            for task_name, config in self.dag.items():
                if task_name in executed:
                    continue

                # Check dependencies satisfied
                if not all(dep in executed for dep in config['deps']):
                    continue

                # Execute task
                try:
                    result = config['executor'](results)
                    results[task_name] = result
                    executed.add(task_name)
                except Exception as e:
                    print(f"Task {task_name} failed: {e}")
                    return results

        return results
```

### Continuous Loop

```bash
# One-time run
gcc-evo loop GCC-0001 --once
# Output: Single loop result

# Continuous run (5-minute cycle)
gcc-evo loop GCC-0001
# Equivalent to:
while True:
    run_once()
    sleep(300)  # 5 minutes
    if should_stop():
        break
```

---

## Inter-Layer Collaboration

### Complete Data Flow

```
New observation event
  │
  ├─→ [L5] LoopEngine.observe()
  │        Read logs, get recent events
  │
  ├─→ [L1] Store in Sensory
  │        memory.sensory.record(event)
  │
  ├─→ [L5] LoopEngine.audit()
  │        Analyze problems
  │
  ├─→ [L2] HybridRetriever.search()
  │        Find related history
  │   └─→ [L1] Read from Short-term + Long-term
  │
  ├─→ [L5] LoopEngine.extract()
  │        Distill rules
  │
  ├─→ [L4] SkepticGate.verify()
  │        Calculate confidence
  │   └─→ (if confidence < 0.75) Request human
  │
  ├─→ [L5] LoopEngine.distill()
  │        (if passed verification)
  │
  ├─→ [L3] Distiller.extract_skill()
  │        Generate experience card
  │
  ├─→ [L3] SkillBank.add_skill()
  │        Store in skill library
  │
  ├─→ [L1] memory.long_term.add_skill()
  │        Write to Long-term
  │
  ├─→ [L1] memory.short_term.store()
  │        Update Short-term (decision record)
  │
  ├─→ [L5] LoopEngine.report()
  │        Generate report
  │
  └─→ Output: Decision + Report

Timeline:
  Observation (seconds)
    ↓ (Sensory → Short-term, minutes)
  Decision (seconds)
    ↓ (Verification, seconds-minutes)
  Distillation (seconds)
    ↓ (Memory update, seconds)
  Next loop (5 minutes later)
```

---

## Implementation Guide

### Minimal Implementation (MVP)

For quick prototyping, minimum required:

```python
# L1: Memory - minimal
class SimpleMemory:
    def __init__(self):
        self.sensory = []
        self.short_term = []
        self.long_term = {}

    def record(self, event):
        self.sensory.append({
            'timestamp': datetime.now().isoformat(),
            'data': event
        })
        self._cleanup_sensory()

    def _cleanup_sensory(self):
        """Remove data older than 24h"""
        cutoff = datetime.now() - timedelta(hours=24)
        self.sensory = [
            e for e in self.sensory
            if datetime.fromisoformat(e['timestamp']) > cutoff
        ]

# L2: Retrieval - minimal
class SimpleRetriever:
    def search(self, query, memory, top_k=5):
        """Simple keyword matching"""
        results = []
        for item in memory.short_term:
            if query.lower() in str(item).lower():
                results.append(item)
        return results[:top_k]

# L4: Decision - minimal
class SimpleSkeptic:
    THRESHOLD = 0.75
    def verify(self, decision, confidence):
        return confidence >= self.THRESHOLD

# L5: Orchestration - minimal
class SimpleLoop:
    def run_once(self):
        events = self.get_events()
        problems = self.analyze(events)
        rule = self.extract_rule(problems)

        if self.skeptic.verify(rule, confidence=0.8):
            self.skillbank.add(rule)

        return self.generate_report()
```

### Progressive Enhancement

```
v1 (MVP):
  - Basic three-tier memory (file-based)
  - Keyword retrieval
  - Simple Skeptic gate
  - Single model

v2 (Enhanced):
  - Add semantic search (embeddings)
  - Add temporal weighting
  - Hybrid retrieval (3-method fusion)
  - Human validation UI

v3 (Complete):
  - SQLite storage backend
  - Multi-model comparison
  - Full version management
  - Performance optimization

v4 (Production):
  - Redis distributed storage
  - Microservices architecture
  - Real-time monitoring
  - Enterprise features
```

---

## Summary

gcc-evo's five-layer architecture solves core problems:

| Problem | Solution | Key Metric |
|---------|----------|-----------|
| Token limit | L1 three-tier | 20x context expansion |
| Retrieval accuracy | L2 hybrid search | > 85% hit rate |
| Knowledge accumulation | L3 distillation + versioning | Skill library growth |
| Hallucination prevention | L4 Skeptic gate | > 95% error blocking |
| Process automation | L5 Loop closure | Zero-touch cycles |

**Next step**: Choose implementation level and start prototyping!

---

**[English](ARCHITECTURE.en.md) | [中文](ARCHITECTURE.md)**
