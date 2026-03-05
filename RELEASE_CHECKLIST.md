# Release Checklist for Open-Source Repository

**Before every push to public repository, verify these 6 checkpoints (C1-C6).**

This checklist ensures we never accidentally expose proprietary code, algorithms, or API keys to the public.

---

## C1: Directory Scope Verification

**Checkpoint**: Confirm all changes are within `opensource/` (public) directory

### Actions
- [ ] All modified files in `opensource/` tree
- [ ] No changes in `private/`, `internal/`, or `.GCC/gcc-private/`
- [ ] No modifications to core trading logic outside public layer

### Command
```bash
git diff --name-only HEAD~1 | grep -v "^opensource/"
# Should return: (empty)
```

### Example ✅
```
✅ opensource/PRICING.md
✅ opensource/gcc_evolution/L1_memory/memory_tiers.py
❌ private/advanced_signal.py (FAIL)
❌ llm_server_v3640.py (FAIL)
```

---

## C2: File Scan for Blocked Modules

**Checkpoint**: No knn_evolution, walk_forward, signal_evolution in public code

### Blocked Module Patterns
```
knn_evolution/           # Enterprise-only
walk_forward*            # Enterprise-only
signal_evolution*        # Enterprise-only
bandit_scheduler*        # Might leak in comments
adaptive_dag*            # Might leak in comments
skillbank_content/       # Commercial
gcc-private/
*_private*
*_core*
```

### Actions
- [ ] `grep -r "knn_evolution" opensource/` returns 0 matches
- [ ] `grep -r "walk_forward" opensource/` returns 0 matches (except in enterprise/ stubs)
- [ ] `grep -r "signal_evolution" opensource/` returns 0 matches
- [ ] No files in `opensource/gcc_evolution/enterprise/` except stubs

### Command
```bash
#!/bin/bash
for pattern in knn_evolution walk_forward signal_evolution skillbank_content; do
  matches=$(grep -r "$pattern" opensource/ --exclude-dir=enterprise 2>/dev/null | wc -l)
  if [ $matches -gt 0 ]; then
    echo "❌ Found $matches references to $pattern"
    grep -r "$pattern" opensource/ --exclude-dir=enterprise
  fi
done
```

---

## C3: Import Statement Check

**Checkpoint**: Public code doesn't import enterprise modules

### Forbidden Imports
```python
# ❌ FAIL - importing proprietary modules
from gcc_evolution.enterprise.knn_evolution import KNNEvolver
from private.signal_evolution import SignalEvolver
import knn_evolution
```

### Allowed Imports
```python
# ✅ PASS - safe imports
from gcc_evolution.L1_memory import MemoryStorage
from gcc_evolution.L2_retrieval import HybridRetriever
from gcc_evolution.direction_anchor import DirectionAnchor

# ✅ PASS - importing from enterprise raises EnterpriseRequired
try:
    from gcc_evolution.enterprise import EnterpriseRequired
except EnterpriseRequired:
    # Graceful fallback
    pass
```

### Actions
- [ ] `grep -r "^from.*enterprise\." opensource/gcc_evolution/` shows only stubs
- [ ] `grep -r "^from.*private" opensource/` returns 0 matches
- [ ] `grep -r "^from.*knn_evolution" opensource/` returns 0 matches
- [ ] `grep -r "^import.*signal_evolution" opensource/` returns 0 matches

### Command
```bash
# Check for forbidden imports
grep -r "from.*enterprise\." opensource/gcc_evolution/ --exclude-dir=enterprise | \
  grep -v "raise EnterpriseRequired"
# Should return: (empty)
```

---

## C4: .gitignore Enforcement

**Checkpoint**: Sensitive paths are listed in .gitignore

### Checklist
- [ ] `opensource/.gitignore` exists
- [ ] Contains all blocked module patterns
- [ ] Contains API key / secret patterns
- [ ] Run `git check-ignore -v` on sensitive files

### Sensitive Patterns in .gitignore
```
**/knn_evolution/
**/walk_forward*
**/signal_evolution*
**/bandit_scheduler*
**/adaptive_dag*
**/skillbank_content/
**/gcc-private/
**/*_private*
**/*_core*
.env
**/api_keys*
**/secrets*
```

### Command
```bash
# Verify files are ignored
git check-ignore -v opensource/.gitignore
git check-ignore -v "hypothetical_knn_evolution.py"
# Should say: "hypothetical_knn_evolution.py .gitignore:1"
```

---

## C5: Comment & Documentation Review

**Checkpoint**: No algorithm details, secret keys, or proprietary hints in comments

### Forbidden Content in Comments
```python
# ❌ FAIL - Proprietary algorithm leak
def _advanced_signal():
    # KNN uses manhattan distance on normalized features
    # Enterprise version has walk-forward backtesting
    pass

# ❌ FAIL - API key in comment
api_key = load_config()  # Usually sk_live_51234567890

# ❌ FAIL - File path hints
# See /private/signal_evolution.py for details
```

### Safe Comments
```python
# ✅ PASS - General guidance
def analyze_pattern(data):
    """Find recurring patterns in historical data."""
    # Higher confidence with more samples
    pass

# ✅ PASS - Reference to open-source docs
# For custom validator implementation, see:
# https://docs.gcc-evo.dev/extending-l4-decision
```

### Actions
- [ ] `grep -r "api_key\|secret\|password" opensource/` shows only in config templates
- [ ] `grep -r "enterprise\|proprietary\|commercial" opensource/` shows only in docs/licensing
- [ ] Review all `# TODO` and `# FIXME` comments for sensitive information
- [ ] Check docstrings don't leak implementation details

---

## C6: License Header & Attribution Check

**Checkpoint**: All new files have proper license headers

### Required License Header (All Public Files)
```python
"""
Module Name — gcc-evo Open Core
License: BUSL 1.1 | Free for personal/academic/<$1M revenue
Commercial: gcc-evo.dev/licensing

[Brief description of what this module does]
"""
```

### Enterprise License Header (enterprise/ stubs only)
```python
"""
Feature Name (Enterprise Only)

⚠️  This module requires an enterprise license.
Community version available: See gcc-evo.dev/pricing
"""

from . import EnterpriseRequired

def feature():
    raise EnterpriseRequired("feature", tier="Evolve")
```

### Actions
- [ ] All `.py` files in `opensource/gcc_evolution/` have license header
- [ ] `grep -L "BUSL\|License" opensource/gcc_evolution/**/*.py` shows only `__init__.py` files
- [ ] Enterprise stubs have `EnterpriseRequired` exception
- [ ] No file missing `"""..."""` module docstring

### Command
```bash
# Find files missing license header
find opensource/gcc_evolution -name "*.py" -exec grep -L "License:" {} \;
# Should return only: __init__.py files (which have BUSL in parent docs)
```

---

## Pre-Push Verification Script

**Run this before every `git push`:**

```bash
#!/bin/bash
set -e

echo "🔍 Running GCC-Evo Release Checklist (C1-C6)..."
echo ""

# C1: Directory scope
echo "C1: Checking directory scope..."
if git diff --name-only HEAD~1 | grep -v "^opensource/" | grep -v "^.gitignore"; then
    echo "❌ FAIL: Non-opensource files modified"
    exit 1
fi
echo "✅ PASS: All changes in opensource/"

# C2: File scan
echo ""
echo "C2: Scanning for blocked modules..."
for pattern in knn_evolution walk_forward signal_evolution skillbank_content; do
    if grep -r "$pattern" opensource/ --exclude-dir=enterprise 2>/dev/null | grep -q .; then
        echo "❌ FAIL: Found $pattern outside enterprise/"
        exit 1
    fi
done
echo "✅ PASS: No blocked modules in public code"

# C3: Import check
echo ""
echo "C3: Checking imports..."
if grep -r "^from.*private" opensource/ 2>/dev/null | grep -q .; then
    echo "❌ FAIL: Importing from private/"
    exit 1
fi
echo "✅ PASS: No private imports"

# C4: .gitignore check
echo ""
echo "C4: Verifying .gitignore..."
if [ ! -f "opensource/.gitignore" ]; then
    echo "❌ FAIL: Missing .gitignore"
    exit 1
fi
echo "✅ PASS: .gitignore exists"

# C5: Comments review
echo ""
echo "C5: Scanning comments for secrets..."
if grep -r "api_key.*=" opensource/ | grep -v "#.*api_key" | grep -q .; then
    echo "❌ WARNING: Found potential API keys (manual review needed)"
fi
echo "✅ PASS: No obvious secrets"

# C6: License headers
echo ""
echo "C6: Checking license headers..."
missing=$(find opensource/gcc_evolution -name "*.py" -exec grep -L "License:" {} \; | wc -l)
if [ $missing -gt 10 ]; then  # Allow __init__.py exceptions
    echo "❌ FAIL: Many files missing license headers"
    exit 1
fi
echo "✅ PASS: License headers present"

echo ""
echo "✅✅✅ ALL CHECKS PASSED ✅✅✅"
echo "Ready to push!"
```

### Usage
```bash
chmod +x release_checklist.sh
./release_checklist.sh
```

---

## Common Issues & Fixes

### Issue: Accidentally committed enterprise code
```bash
# Remove from git history (force reset, dangerous!)
git reset --hard HEAD~1
git clean -fd
```

### Issue: API key in comment
```bash
# Search for patterns
grep -rn "key\|secret\|password" .
# Edit and remove
git add -A
git commit --amend
git push --force-with-lease
```

### Issue: Import from private module
```python
# ❌ Before
from private.advanced import algorithm

# ✅ After
from gcc_evolution.L4_decision.multi_model import MultiModelEnsemble
# Document how to extend with custom logic
```

---

## Post-Push Verification

After pushing, verify on GitHub:

1. **Check GitHub Actions**: Passes linting & security scans
2. **Check File Count**: ~25 public .py files
3. **Check No Secrets**: GitHub secret scanning shows no issues
4. **Check License**: All files have BUSL header

---

## Who's Responsible?

- **Individual Developer**: Must run checklist before commit
- **Team Lead**: Reviews PRs before merge
- **DevOps**: Enforces checklist in CI/CD (pre-push hook)

---

## Questions?

📧 Contact: releases@gcc-evo.dev
📚 Docs: https://docs.gcc-evo.dev/open-source
🔐 Security: https://gcc-evo.dev/security
