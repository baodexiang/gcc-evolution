# gcc-evo Commercial Open Source Strategy

> How to balance open source with commercial protection

---

## Core Principle

```
Basic Functionality: FREE (Can use)
↓
Core Functionality: PAID (Needs license)

This ensures:
✅ Users can experiment freely
✅ You monetize essential capabilities
✅ Clear boundary between free and paid
```

---

## Three-Tier Model

### Tier 1: Framework Foundation (FREE)
**License**: MIT / Apache 2.0
**Scope**: Interfaces and abstractions only

```
✅ Completely free for any use
✅ No commercial restrictions
✅ Can be forked and modified
✅ Encourages ecosystem around your design

Examples:
- Pipeline DAG interface
- Memory interface (abstract)
- Retriever interface (abstract)
- Decision interface (abstract)
```

### Tier 2: Core Implementation (BUSL 1.1)
**License**: BUSL 1.1 (Business Source License)
**Scope**: Essential production features

```
✅ FREE for:
  - Personal use
  - Learning/research
  - Companies < $1M revenue
  - Open source projects

❌ PAID for:
  - Companies >= $1M revenue
  - SaaS/productized use
  - Embedded commercial products

Examples (BASIC features):
- Three-tier memory (Sensory/Short/Long)
- File-based storage (JSON/SQLite)
- Hybrid retrieval (basic)
- Skeptic gate (basic)
- Loop engine (basic)
```

### Tier 3: Enterprise Features (PAID ONLY)
**License**: Proprietary (not open source)
**Scope**: Advanced capabilities not in free tier

```
🔒 For enterprise customers only
   (No public source code)

Examples (ADVANCED features):
- Distributed memory (Redis/database)
- Sharded storage
- Advanced semantic search
- Multi-user collaboration
- Enterprise integrations (Kafka/gRPC)
- SLA guarantees
- Professional support
```

---

## What Counts as "Basic" vs "Core"

### Basic Features (FREE)
✅ Users can build working systems
✅ Can test all concepts
✅ Can integrate with their own code

```
- Three-tier memory structure
  (basic file storage, auto-cleanup)

- Hybrid retrieval
  (semantic + temporal + keyword)

- Experience distillation
  (LLM-based, using user's API key)

- Skeptic verification
  (confidence threshold gate)

- Loop automation
  (6-step closure)
```

**Why these are free**:
- They're the "value proposition"
- Show the core concept works
- Prove the framework is useful
- Let users experiment and learn

### Core Features (PAID)
❌ Only in enterprise version
❌ Requires commercial license

```
- Distributed/replicated storage
  (Can't just use files)

- Advanced performance optimization
  (Query caching, intelligent indexing)

- Multi-user collaboration
  (Conflict resolution, permissions)

- Enterprise integrations
  (Native Kafka, gRPC, etc.)

- SaaS/cloud deployment
  (Infrastructure you manage)

- Priority support
  (24/7, with SLA)
```

**Why these are paid**:
- Require significant infrastructure
- Add production-grade features
- Enable enterprise deployment
- Justify professional support

---

## Feature Boundary Design

### Example: Memory Storage

**FREE VERSION**:
```python
# Users can use these
class MemoryTier:
    def __init__(self, storage_type='json'):
        # Options: 'json' or 'sqlite'
        # Both are local file-based
        self.storage = FileStorage(storage_type)

# json example: state/memory.jsonl
# sqlite example: memory.db

# Users can:
✅ Store data locally
✅ Manually backup
✅ Run on single machine
✅ Integrate with their system
```

**ENTERPRISE VERSION** (paid only):
```python
# Only enterprise gets this
class EnterpriseMemoryTier:
    def __init__(self, storage_type):
        # Options: 'redis', 'postgresql', 'dynamodb'
        # Can be distributed, replicated, high-availability
        self.storage = ManagedStorage(storage_type)

# Enterprise features:
❌ NOT available in free tier
- Automatic replication
- Distributed sharding
- Real-time sync
- Managed backups
- Multi-region deployment
```

### Example: Retrieval

**FREE VERSION**:
```python
class BasicRetriever:
    """Three-method hybrid retrieval"""
    def search(self, query, top_k=5):
        # ✅ Semantic (embedding)
        # ✅ Temporal (time-weighted)
        # ✅ Keyword (BM25)
        # ✅ Weighted fusion

        # Performance: OK for typical use
        # Speed: <1s for most queries
```

**ENTERPRISE VERSION** (paid):
```python
class AdvancedRetriever:
    """Optimized retrieval for scale"""
    def search(self, query, top_k=5):
        # ✅ Same 3 methods +
        # ❌ Custom fine-tuned embedding model
        # ❌ Hierarchical indexing
        # ❌ Intelligent caching
        # ❌ Vector quantization

        # Performance: Optimized for millions of records
        # Speed: <100ms even with huge datasets
```

---

## Clear Boundary Checklist

When deciding if a feature is "basic" or "core":

```
Is it in Tier 2 (free BUSL)? Ask:

☑️ Can users build something useful without it?
   → YES = probably Tier 2 (free)
   → NO = probably Tier 3 (paid)

☑️ Can it be implemented without enterprise infrastructure?
   → YES = probably Tier 2 (free)
   → NO = probably Tier 3 (paid)

☑️ Is it required for the core value proposition?
   → YES = Tier 2 (free)
   → NO = Tier 3 (paid)

☑️ Does it scale to millions of users/records?
   → YES = might be Tier 3 if requires specialized infra
   → NO = Tier 2 (free)
```

---

## BUSL 1.1 Commercial Terms

### What Requires Payment

**Scenario 1: Company using gcc-evo core**
```
Annual Revenue: $2M
Using: BUSL Tier 2 features
Status: ❌ REQUIRES LICENSE

Cost: Annual license (negotiable)
Example: $2,000-10,000/year based on use
```

**Scenario 2: SaaS product based on gcc-evo**
```
Using: gcc-evo as backend for SaaS
Status: ❌ REQUIRES LICENSE

Why: Can't sell service using BUSL without license
Solution: License or upgrade to Enterprise (custom implementation)
```

**Scenario 3: Embedded in commercial product**
```
Example: Trading robot bundled with gcc-evo
Status: ❌ REQUIRES LICENSE

Why: Distributing BUSL code commercially
Solution: Get commercial license or reimplement using Tier 1 (MIT)
```

### Automatic Transitions

```
Timeline:
2025-2028: BUSL 1.1 (commercial license required)
2028-05-01: Automatically → Apache 2.0 (free forever)

Implication:
- You have 3 years of commercial protection
- After that, everything is fully open
- Forces you to innovate (Layer 3) by then
```

---

## Pricing Strategy

### Free Tier (BUSL)
- **Price**: $0
- **Users**: Personal, learning, small companies (<$1M)
- **Support**: Community (GitHub, forums)
- **SLA**: None
- **How they pay**: They respect your license terms
- **Why it works**: Builds community, gets feedback

### Professional Tier ($99-299/month)
- **Price**: $99-299/month
- **Users**: Small companies, startups (<$10M)
- **Includes**: Enterprise storage options, private model support
- **Support**: Email support (24-48h)
- **SLA**: Standard (95% uptime)
- **Why they upgrade**: Need more than free, less than enterprise

### Enterprise Tier ($1,000+/month)
- **Price**: $1,000+ (custom)
- **Users**: Large companies (>$10M)
- **Includes**: Layer 3 (all advanced features)
- **Support**: Phone, Slack, 24/7
- **SLA**: Premium (99.9% uptime)
- **Add-ons**: Custom development, consulting, training
- **Why they buy**: Mission-critical use, need support/integration

### Conversion Example

```
Year 1:
- 10,000 free users
- Revenue: $0 (intentional)
- Goal: Build mindshare

Year 2:
- 10,000 free users
- 50 professional tier ($200 avg) = $120K
- 5 enterprise ($5K avg) = $25K
- Revenue: $145K

Year 3:
- 50,000 free users
- 200 professional tier = $480K
- 20 enterprise = $100K
- Revenue: $580K

Year 4 (post BUSL transition):
- 100,000 free users
- 500 professional tier = $1.2M
- 50 enterprise = $250K
- Revenue: $1.45M
- (Can now be fully open source)
```

---

## License Compliance

### How to Check (Honor System)

```python
# Informational checker - doesn't prevent usage
class LicenseCheck:
    def __init__(self):
        self.shown_once = False

    def check_on_startup(self):
        """Inform users about licensing"""
        if not self.shown_once:
            print("""
╔════════════════════════════════════════════╗
║     gcc-evo License Information             ║
╠════════════════════════════════════════════╣
║  This software is BUSL 1.1 licensed        ║
║  Free for personal/academic/small-biz use  ║
║  Commercial license required for:          ║
║  • Companies with $1M+ annual revenue      ║
║  • SaaS/productized offerings             ║
║  • Embedded in commercial products        ║
║                                            ║
║  Learn more: gcc-evo.dev/licensing         ║
╚════════════════════════════════════════════╝
            """)
            self.shown_once = True
```

### What NOT to Do

❌ Don't require activation codes
❌ Don't block functionality
❌ Don't track usage (violates privacy)
❌ Don't use DRM or obfuscation
❌ Don't check license at runtime (too intrusive)

### Why Trust?

```
Good reasons to use honor system:
✅ Open source projects rely on trust
✅ Users who respect you won't cheat
✅ Users who cheat won't respect you anyway
✅ Law protects you if needed
✅ Most companies prefer to license fairly
   (easier than managing risk of breach)
```

---

## Risk Mitigation

### Risk 1: Fork Attempts

**If someone forks and claims it's theirs:**
- ✅ You own the copyright
- ✅ BUSL license still applies to derived works
- ✅ You can pursue legal action
- ✅ Community will recognize the original

### Risk 2: License Violations

**If a $10M company uses Tier 2 without license:**
- ✅ BUSL 1.1 is binding
- ✅ You have legal grounds to sue
- ✅ Reasonable settlement: 2-3 years of license fees
- ✅ Most companies will license proactively

### Risk 3: Tier 3 Leakage

**If someone leaks enterprise code:**
- ✅ Proprietary software
- ✅ Stronger legal protection
- ✅ Trade secret laws apply
- ✅ Confidentiality agreements

---

## Documentation Requirements

### Files to Create

1. **COMMERCIAL_STRATEGY.md** (this file)
   - Clear explanation of the model

2. **LICENSE_FAQ.md**
   - Common questions and answers
   - "Do I need to buy a license?"
   - "Can I use gcc-evo in my company?"
   - etc.

3. **ADDITIONAL_USE_GRANT.md**
   - Specific exceptions to BUSL
   - Free categories (academic, open source, etc.)
   - How to apply for exemptions

4. **LICENSING.md** (on website)
   - License comparison table
   - Pricing tiers
   - Contact form for inquiries

### File Headers

```python
# In Tier 2 (BUSL) files:
"""
gcc-evo core functionality module.

License: BUSL 1.1 (Business Source License)
- Free for personal, academic, and open source use
- Free for companies with <$1M annual revenue
- Requires license for commercial companies

For more information: gcc-evo.dev/licensing
"""

# In Tier 1 (MIT) files:
"""
gcc-evo framework interface.

License: MIT
Freely usable for any purpose, including commercial.
"""

# In Tier 3 (proprietary) files:
"""
PROPRIETARY - ENTERPRISE CUSTOMERS ONLY

This file is not part of the open source release.
© baodexiang. All rights reserved.
"""
```

---

## Go-to-Market Strategy

### Phase 1: Community (2025)
- Release Tier 1 + Tier 2 as open source
- Build GitHub stars (target: 10K+)
- Establish thought leadership
- Get press coverage
- Free to everyone

### Phase 2: Monetization (2026)
- Launch Professional tier ($99/month)
- Launch Enterprise tier (custom pricing)
- Hire sales/support team
- Get first 50 customers
- Maintain free tier unchanged

### Phase 3: Scale (2027)
- Expand enterprise sales
- Build custom integrations
- Professional services revenue
- Reach $500K ARR
- Maintain community investment

### Phase 4: Transition (2028)
- BUSL auto-converts to Apache 2.0
- Everything becomes fully open source
- Shift revenue to services/hosting/support
- Become sustainable open source project

---

## Key Principles Summary

```
1. OPENNESS
   "Code is open, business model is transparent"

2. FAIRNESS
   "Free for those who can't pay, fair pricing for those who can"

3. CLARITY
   "Clear boundary between free and paid"

4. TRUST
   "Trust users to respect your licensing"

5. TIMING
   "3-year commercial window, then full open source"
```

This strategy:
- ✅ Protects your investment early
- ✅ Builds thriving open source community
- ✅ Creates sustainable business model
- ✅ Maintains integrity and trust
- ✅ Ensures long-term project viability

---

**[English](COMMERCIAL_STRATEGY.en.md) | [中文](COMMERCIAL_STRATEGY.md)**
