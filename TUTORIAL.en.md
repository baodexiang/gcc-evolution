# Tutorial — Deep Dive into gcc-evo v5.300

**Comprehensive learning guide for building self-evolving LLM agents**

---

## Table of Contents

1. [Getting Started](#chapter-1-getting-started)
2. [Core Concepts](#chapter-2-core-concepts)
3. [Task & Loop Design](#chapter-3-task--loop-design)
4. [Memory System](#chapter-4-memory-system)
5. [Retrieval Strategies](#chapter-5-retrieval-strategies)
6. [Distillation & Skills](#chapter-6-distillation--skills)
7. [Skeptic Verification](#chapter-7-skeptic-verification)
8. [Multi-Model Setup](#chapter-8-multi-model-setup)
9. [Case Studies](#chapter-9-case-studies)
10. [Advanced Patterns](#chapter-10-advanced-patterns)

---

## Chapter 1: Getting Started

### Installation & Verification

```bash
# Install
pip install gcc-evo

# Verify
gcc-evo version
# Output: gcc-evo v5.300

# Check environment
gcc-evo health
```

### Project Initialization

```bash
# Create project
gcc-evo init --project my-first-project

# Directory structure
ls -la my-first-project/
# .env, .GCC/, state/, config/, logs/
```

### First Configuration

```bash
# Set API key
export ANTHROPIC_API_KEY=sk-ant-...

# Create .env
cat > my-first-project/.env << 'EOF'
ANTHROPIC_API_KEY=sk-ant-...
GCC_LOG_LEVEL=INFO
GCC_SKEPTIC_THRESHOLD=0.75
EOF

# Verify
gcc-evo config show
```

---

## Chapter 2: Core Concepts

### 2.1 Three-Tier Memory System

**Sensory Layer** (24-hour window)
```
Raw observations → Unprocessed conversations → Auto-discarded
Purpose: Immediate context, ephemeral data
Access: Always available, not stored
```

**Short-term Layer** (7-day window)
```
Recent decisions → Contextual details → Automatic compression
Purpose: Discussion history, recent patterns
Access: Semantic search + recency weighting
```

**Long-term Layer** (Persistent)
```
Verified rules → Experience cards → Immutable archive
Purpose: Permanent knowledge base
Access: Distilled patterns, reusable skills
```

### 2.2 Loop Cycle (6 Steps)

```
① OBSERVE        → Collect logs/observations
   ↓
② AUDIT          → Analyze patterns/failures
   ↓
③ EXTRACT        → Identify reusable rules
   ↓
④ VERIFY         → Skeptic gate validation
   ↓
⑤ DISTILL        → Compress into skills
   ↓
⑥ REPORT         → Generate summary & next actions
   ↓
(Repeat...)
```

### 2.3 Confidence Score Calculation

```python
confidence = (
    (rule_accuracy * weight_accuracy)  # 0.4
    + (rule_frequency * weight_frequency)  # 0.3
    + (human_validation * weight_human)  # 0.3
)

# Decision gate:
# confidence >= 0.75 → Accept
# confidence < 0.75  → Reject (skeptic block)
```

---

## Chapter 3: Task & Loop Design

### 3.1 Creating Well-Structured Tasks

```bash
# Anatomy of a good task
gcc-evo pipe task "Reduce false signals in MACD plugin" \
  -k KEY-001 \
  -m signal_processing \
  -p P0 \
  --description "MACD divergences produce 40% false signals on tight ranges"
```

**Task Properties:**
- **KEY**: Improvement area (KEY-001, KEY-002, ...)
- **Module**: Code component affected (signal_processing, retrieval, ...)
- **Priority**: P0 (blocking) | P1 (high) | P2 (normal)
- **Description**: Context + metrics

### 3.2 Loop Binding

```bash
# Bind loop to task
gcc-evo loop GCC-0001 --once

# Continuous improvement
gcc-evo loop GCC-0001 &

# Run specific provider
gcc-evo loop GCC-0001 --provider gemini --once
```

### 3.3 Loop Execution Flow

**Single Iteration Process:**
```
Start Loop
├─ Read config (params.yaml)
├─ Load current state (improvements.json)
├─ Load memories (short/long term)
├─ Run audit analysis
├─ LLM decision (extract patterns)
├─ Skeptic verification
├─ Update memories
├─ Save state
└─ Generate report
```

---

## Chapter 4: Memory System

### 4.1 Sensory Layer Implementation

```python
from gcc_evolution.memory import SensoryLayer
import time

sensory = SensoryLayer(ttl=86400)  # 24 hours

# Add observation
sensory.record({
    'timestamp': time.time(),
    'event_type': 'trade_execution',
    'symbol': 'TSLA',
    'price': 145.50,
    'confidence': 0.92
})

# Auto-purges after TTL
aged_observations = sensory.get_aged()
```

### 4.2 Short-term Layer

```python
from gcc_evolution.memory import ShortTermLayer

short_term = ShortTermLayer(ttl=604800)  # 7 days

# Store decision with context
short_term.store({
    'task_id': 'GCC-0001',
    'decision': 'Reduce MACD threshold from 0.8 to 0.7',
    'confidence': 0.82,
    'timestamp': time.time(),
    'related_observations': [obs1, obs2, obs3]
})

# Retrieve by semantic similarity
similar = short_term.search_semantic(
    query="threshold adjustment",
    top_k=5
)
```

### 4.3 Long-term Layer

```python
from gcc_evolution.memory import LongTermLayer

long_term = LongTermLayer()

# Add verified experience card
long_term.add_experience({
    'skill_id': 'SK-001',
    'skill_name': 'MACD_Threshold_Calibration',
    'pattern': 'When price range tightens, MACD false signals increase',
    'solution': 'Increase threshold from 0.8 to 0.7 during sideways',
    'confidence': 0.91,
    'version': 1,
    'source': 'retrospective'
})

# Retrieve by skill ID
skill = long_term.get_skill('SK-001')
```

---

## Chapter 5: Retrieval Strategies

### 5.1 Semantic Similarity Search

```python
from gcc_evolution.retrieval import SemanticRetriever

retriever = SemanticRetriever(
    model='sentence-transformers/all-MiniLM-L6-v2'
)

# Index memories
retriever.index(all_memories)

# Search
results = retriever.search(
    query="false signal reduction strategy",
    top_k=5
)

# Returns: [(memory, score), ...]
# score: 0.0 (different) to 1.0 (identical)
```

### 5.2 KNN Temporal Weighting

```python
from gcc_evolution.retrieval import KNNRetriever
import time

knn = KNNRetriever(k=5, decay_rate=0.9)

# Add vectors with timestamps
knn.add({
    'vector': embedding,  # 768-dim
    'timestamp': time.time(),
    'memory_id': 'mem-123'
})

# Retrieve with temporal preference
# Recent memories weighted higher
results = knn.search(
    query_vector,
    hours_weight_half_life=24  # Decay halflife
)
```

### 5.3 BM25 Keyword Matching

```python
from gcc_evolution.retrieval import BM25Retriever

bm25 = BM25Retriever(tokenizer='english')

# Index documents
bm25.index(documents)

# Keyword search
results = bm25.search(
    query="false signal MACD threshold",
    top_k=5
)

# Useful for: logs, keywords, exact matches
```

### 5.4 Hybrid Retrieval

```python
from gcc_evolution.retrieval import HybridRetriever

hybrid = HybridRetriever(
    semantic_weight=0.5,
    temporal_weight=0.3,
    keyword_weight=0.2
)

# Combines all three strategies
results = hybrid.search(
    query="signal accuracy improvement",
    top_k=10
)
```

---

## Chapter 6: Distillation & Skills

### 6.1 Experience Card Extraction

```python
from gcc_evolution.distiller import Distiller

distiller = Distiller()

# Extract skill from experience
experience = {
    'observation': 'MACD false signals 40% on tight ranges',
    'action_taken': 'Increased threshold from 0.8 to 0.7',
    'outcome': 'False signals reduced to 15%',
    'confidence': 0.88
}

skill_card = distiller.extract_skill(experience)
# Returns: Experience card with reusable pattern

print(skill_card)
# {
#   'skill_id': 'SK-002',
#   'name': 'MACD_Range_Adaptation',
#   'pattern': 'When volatility low, increase threshold',
#   'condition': 'price_range_percent < 2%',
#   'action': 'set threshold += 0.1',
#   'success_rate': 0.85,
#   'version': 1
# }
```

### 6.2 SkillBank Management

```python
from gcc_evolution.skillbank import SkillBank

skillbank = SkillBank(storage='state/skillbank.jsonl')

# Add new skill
skillbank.add_skill({
    'skill_id': 'SK-003',
    'name': 'Volatility_Based_Risk',
    'description': 'Adjust risk based on ATR volatility',
    'confidence': 0.87,
    'use_count': 145,
    'success_count': 126,
    'version': 3
})

# Retrieve skill
skill = skillbank.get('SK-003')

# Get top skills by accuracy
top_skills = skillbank.top_by_accuracy(k=10)

# Deprecate old version
skillbank.deprecate('SK-001', new_version='SK-002')
```

### 6.3 Versioning & Evolution

```python
# Track skill evolution over time
skill_v1 = {
    'skill_id': 'SK-050',
    'name': 'Entry_Pattern',
    'version': 1,
    'accuracy': 0.72
}

# After improvement
skill_v2 = {
    'skill_id': 'SK-050',
    'name': 'Entry_Pattern',
    'version': 2,
    'accuracy': 0.81,
    'prior_version': 'v1',
    'improvement': '+0.09'
}

# Query evolution
evolution = skillbank.get_evolution('SK-050')
# [v1, v2, v3, ...]
```

---

## Chapter 7: Skeptic Verification

### 7.1 Confidence Gate

```python
from gcc_evolution.skeptic import SkepticGate

skeptic = SkepticGate(threshold=0.75)

# Decision proposal
decision = {
    'action': 'Set MACD threshold to 0.7',
    'confidence': 0.82,
    'evidence': ['observation_1', 'observation_2'],
    'reasoning': 'Reduced false signals on 10 backtests'
}

# Verify decision
approved = skeptic.verify(decision)
# True (confidence 0.82 >= 0.75)

# With low confidence
low_confidence = {
    **decision,
    'confidence': 0.68  # Below threshold
}

approved = skeptic.verify(low_confidence)
# False → Decision blocked
```

### 7.2 Human-in-the-Loop Validation

```python
from gcc_evolution.skeptic import HumanValidator

validator = HumanValidator(approval_timeout=3600)

# Request human review
validation_id = validator.request_review({
    'task_id': 'GCC-0001',
    'decision': 'Reduce threshold',
    'confidence': 0.68,
    'reason': 'Low confidence, needs human verification'
})

# Human reviews (via dashboard)
# Returns: { 'approved': True, 'feedback': '...' }

result = validator.get_result(validation_id)
if result and result['approved']:
    apply_decision(...)
```

### 7.3 Confidence Calibration

```python
# Track actual vs predicted confidence
calibration = {
    'predicted_confidence': 0.80,
    'actual_accuracy': 0.78,  # From backtest
    'deviation': 0.02,
    'sample_size': 150
}

# Adjust threshold based on calibration
if deviation > 0.05:
    # Recalibrate
    new_threshold = predicted_confidence + deviation
```

---

## Chapter 8: Multi-Model Setup

### 8.1 Configuring Multiple Providers

```bash
# Set all API keys
export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...
export GEMINI_API_KEY=...
export DEEPSEEK_API_KEY=...

# Or in .env
cat > .env << 'EOF'
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=...
DEEPSEEK_API_KEY=...
GCC_DEFAULT_PROVIDER=claude  # Default provider
EOF
```

### 8.2 Running Loops with Different Models

```bash
# Use Claude (default)
gcc-evo loop GCC-0001 --once

# Switch to Gemini
gcc-evo loop GCC-0001 --provider gemini --once

# Switch to GPT-4
gcc-evo loop GCC-0001 --provider gpt --once

# Switch to DeepSeek
gcc-evo loop GCC-0001 --provider deepseek --once
```

### 8.3 Model Comparison

```python
from gcc_evolution.providers import ModelFactory

models = {
    'claude': ModelFactory.create('claude'),
    'gpt': ModelFactory.create('openai'),
    'gemini': ModelFactory.create('gemini'),
}

# Compare decisions
decision_request = {
    'task': 'Analyze false signals',
    'context': audit_logs
}

decisions = {}
for name, model in models.items():
    decisions[name] = model.decide(decision_request)

# Compare confidence levels
for name, decision in decisions.items():
    print(f"{name}: {decision['confidence']:.2f}")
```

---

## Chapter 9: Case Studies

### Case Study 1: Trading Signal Improvement

**Problem:** MACD plugin produces 40% false signals on tight-range days

**Solution with gcc-evo:**

```bash
# Step 1: Create task
gcc-evo pipe task "Reduce MACD false signals" \
  -k KEY-001 \
  -m plugins \
  -p P0

# Step 2: Run initial analysis
gcc-evo loop GCC-0001 --once

# Output:
# - Pattern identified: "Threshold too low for tight ranges"
# - Suggestion: Increase from 0.8 to 0.7
# - Confidence: 0.82

# Step 3: Implement and verify
# (Update code based on suggestion)

# Step 4: Run verification loop
gcc-evo loop GCC-0001 --once

# Output:
# - Accuracy improved: 60% → 85%
# - Skill saved: SK-001 "MACD_Range_Adaptation"
# - Next action: Test on other timeframes
```

### Case Study 2: API Reliability Optimization

**Problem:** High variance in API response times, occasional timeouts

**Solution:**

```bash
# Create task
gcc-evo pipe task "Improve API resilience" \
  -k KEY-002 \
  -m api_client \
  -p P1

# Run loop
gcc-evo loop GCC-0002 --once

# Discovered patterns:
# 1. Timeouts cluster during peak hours
# 2. Exponential backoff more effective than linear
# 3. Connection pooling reduces latency

# Generate skill
# SK-002: "Peak_Hour_Retry_Strategy"
# SK-003: "Connection_Pool_Optimization"

# Verify improvement
gcc-evo loop GCC-0002 --once

# Results:
# - 95th percentile latency: 2.1s → 0.8s
# - Timeout rate: 3.2% → 0.1%
# - Cost: unchanged (better efficiency)
```

---

## Chapter 10: Advanced Patterns

### 10.1 Custom Plugins

```python
from gcc_evolution.plugins import Plugin

class CustomAnalyzer(Plugin):
    """Custom analysis plugin."""

    def analyze(self, data: dict) -> dict:
        """Analyze data and return insights."""
        patterns = self.find_patterns(data)
        return {
            'patterns': patterns,
            'confidence': self.calculate_confidence(patterns)
        }

# Register plugin
plugin = CustomAnalyzer()
gcc_evo.register_plugin('custom_analyzer', plugin)

# Use in loop
decision = gcc_evo.loop(task, plugins=['custom_analyzer'])
```

### 10.2 Custom Retrieval Strategy

```python
from gcc_evolution.retrieval import Retriever

class CustomRetriever(Retriever):
    """Custom retrieval with domain-specific logic."""

    def search(self, query: str, **kwargs) -> List[dict]:
        # Domain-specific search logic
        # e.g., only retrieve from specific timeframes
        # or with specific symbol restrictions
        pass

# Use in loop
retriever = CustomRetriever()
memories = retriever.search("signal improvement", symbol='TSLA')
```

### 10.3 Production Deployment

```bash
# Background loop with logging
nohup gcc-evo loop GCC-0001 > logs/loop.log 2>&1 &

# OR systemd service
cat > /etc/systemd/system/gcc-evo.service << 'EOF'
[Unit]
Description=gcc-evo Auto-Improvement Loop
After=network.target

[Service]
Type=simple
User=gcc-evo
WorkingDirectory=/opt/gcc-evo
ExecStart=/usr/local/bin/gcc-evo loop GCC-0001
Restart=always
RestartSec=60
StandardOutput=append:/var/log/gcc-evo/loop.log
StandardError=append:/var/log/gcc-evo/error.log

[Install]
WantedBy=multi-user.target
EOF

systemctl enable gcc-evo
systemctl start gcc-evo
```

---

## Troubleshooting Guide

### Issue: Loop not progressing

```bash
# Check logs
tail -f logs/gcc-evo.log

# Enable debug
GCC_LOG_LEVEL=DEBUG gcc-evo loop GCC-0001 --once

# Check memory status
gcc-evo memory stats

# Verify API connectivity
curl https://api.openai.com/v1/models
```

### Issue: Low confidence decisions

```bash
# Review audit logs
gcc-evo audit --days 7 --task GCC-0001

# Lower threshold temporarily (testing only)
export GCC_SKEPTIC_THRESHOLD=0.65

# Review skeptic gate decisions
grep "SKEPTIC" logs/gcc-evo.log
```

### Issue: Memory bloat

```bash
# Check disk usage
du -sh state/

# Compact memories
gcc-evo memory compact

# Archive old memories
gcc-evo memory export > backup.json
gcc-evo memory reset
```

---

## Best Practices

### ✅ DO

- Test changes in single-iteration mode before continuous loops
- Monitor confidence scores for all decisions
- Regularly review learned skills for accuracy
- Maintain detailed audit logs
- Version your improvements systematically
- Start with high skeptic thresholds, lower gradually
- Backup state regularly

### ❌ DON'T

- Run multiple loops on same task simultaneously
- Lower skeptic threshold below 0.6 without testing
- Ignore low-confidence decisions
- Store API keys in code or git
- Skip verification on production decisions
- Mix old and new memory formats
- Deploy untested loop configurations

---

## Next Steps

1. **Run Quick Start** — [QUICKSTART.en.md](QUICKSTART.en.md)
2. **Read Full Docs** — [README.en.md](README.en.md)
3. **Explore Examples** — GitHub repository
4. **Join Community** — GitHub Discussions
5. **Contribute** — [CONTRIBUTING.en.md](CONTRIBUTING.en.md)

---

**Happy learning! 🚀**

[English](TUTORIAL.en.md) | [中文](TUTORIAL.md)
