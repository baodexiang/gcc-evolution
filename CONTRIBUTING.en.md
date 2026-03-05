# Contributing to gcc-evo

Thank you for your interest in contributing to gcc-evo! This document provides guidelines and instructions for contributing.

---

## Table of Contents
1. [Code of Conduct](#code-of-conduct)
2. [Getting Started](#getting-started)
3. [Development Workflow](#development-workflow)
4. [Coding Standards](#coding-standards)
5. [Testing Requirements](#testing-requirements)
6. [Pull Request Process](#pull-request-process)
7. [Contributor License Agreement](#contributor-license-agreement)

---

## Code of Conduct

### Our Pledge
We are committed to providing a welcoming and inclusive environment for all contributors.

### Expected Behavior
- Be respectful and professional
- Welcome diversity and different perspectives
- Focus on constructive feedback
- Respect confidentiality of others

### Unacceptable Behavior
- Harassment, discrimination, or abusive language
- Sexual harassment or unwanted advances
- Trolling, deliberate disruption
- Publishing private information without consent

### Reporting Violations
Email: conduct@gcc-evo.dev

---

## Getting Started

### 1. Fork and Clone
```bash
# Fork on GitHub
# Then clone your fork
git clone https://github.com/YOUR-USERNAME/gcc-evo.git
cd gcc-evo

# Add upstream remote
git remote add upstream https://github.com/baodexiang/gcc-evo.git
```

### 2. Create Branch
```bash
# Ensure main is up to date
git fetch upstream
git checkout main
git merge upstream/main

# Create feature branch
git checkout -b feature/your-feature-name
# or
git checkout -b fix/your-bug-name
# or
git checkout -b docs/your-doc-name
```

### 3. Set Up Development Environment
```bash
# Install dependencies
cd opensource
pip install -e ".[dev]"

# Install pre-commit hooks
pip install pre-commit
pre-commit install

# Verify setup
gcc-evo version
make test
```

---

## Development Workflow

### 1. Make Changes
```bash
# Edit files
vim gcc_evolution/core.py

# Run linter before committing
make lint

# Auto-format code
make format

# Run tests
make test
```

### 2. Commit Changes
```bash
# Stage changes
git add gcc_evolution/core.py

# Commit with conventional message
git commit -m "feat(core): Add new feature description"
```

**Commit Message Format**:
```
<type>(<scope>): <subject>

<body>

<footer>
```

**Types**: `feat` (feature), `fix` (bug), `docs` (documentation), `test`, `refactor`, `perf` (performance), `ci`, `chore`

**Scope**: Module name (e.g., `memory`, `retrieval`, `distiller`, `skeptic`)

**Example**:
```
feat(memory): Add three-tier memory consolidation

Implement automatic consolidation of sensory memories into
short-term layer after 24 hours. Uses LLM for summarization.

Fixes #123
```

### 3. Push Changes
```bash
git push origin feature/your-feature-name
```

### 4. Create Pull Request
- Go to GitHub
- Click "New Pull Request"
- Fill in title and description
- Link related issues
- Ensure CI checks pass

---

## Coding Standards

### Python Style Guide
Follow [PEP 8](https://www.python.org/dev/peps/pep-0008/) with:
- 4-space indentation
- Line length: 100 characters max
- Lowercase with underscores for variables/functions
- CamelCase for classes

### Example
```python
"""Module docstring."""

from typing import Optional, List
import requests


class MemoryTier:
    """Represents one memory tier."""

    def __init__(self, name: str, ttl: int):
        """Initialize memory tier.

        Args:
            name: Tier name (sensory/short/long)
            ttl: Time to live in seconds
        """
        self.name = name
        self.ttl = ttl
        self.storage: List[dict] = []

    def consolidate(self, threshold: Optional[float] = None) -> dict:
        """Consolidate memories above threshold.

        Args:
            threshold: Confidence threshold (default: 0.75)

        Returns:
            Dictionary with consolidated memories
        """
        threshold = threshold or 0.75
        return {
            'consolidated': len(self.storage),
            'threshold': threshold
        }
```

### Type Hints
All public functions must have type hints:
```python
def retrieve(query: str, top_k: int = 5) -> List[dict]:
    """Retrieve memories by semantic similarity."""
    pass

def distill_skill(experience: dict, **kwargs) -> Optional[dict]:
    """Extract reusable skill from experience."""
    pass
```

### Docstrings
Use Google-style docstrings:
```python
def function_name(param1: str, param2: int) -> bool:
    """Brief one-line description.

    Longer description if needed, explaining purpose,
    behavior, and important details.

    Args:
        param1: Description of param1
        param2: Description of param2 (default: 5)

    Returns:
        Description of return value

    Raises:
        ValueError: When condition X happens
        TypeError: When param type is wrong

    Example:
        >>> result = function_name("test", 10)
        >>> print(result)
        True
    """
    pass
```

### Imports
Organize imports in three groups:
```python
# Standard library
import json
from pathlib import Path
from typing import Optional, List

# Third-party packages
import requests
import yaml

# Local modules
from gcc_evolution.core import MemoryTier
from gcc_evolution.utils import get_logger
```

---

## Testing Requirements

### Write Tests for All Changes
```bash
# Create test file
touch tests/unit/test_my_feature.py
```

### Test Structure
```python
import pytest
from gcc_evolution.core import MyClass


class TestMyClass:
    """Tests for MyClass."""

    @pytest.fixture
    def instance(self):
        """Create test instance."""
        return MyClass(param="test")

    def test_initialization(self, instance):
        """Test proper initialization."""
        assert instance.param == "test"

    def test_method_with_valid_input(self, instance):
        """Test method with valid input."""
        result = instance.method("valid")
        assert result is not None

    def test_method_with_invalid_input(self, instance):
        """Test method rejects invalid input."""
        with pytest.raises(ValueError):
            instance.method(None)

    @pytest.mark.slow
    def test_expensive_operation(self, instance):
        """Test expensive operation (marked as slow)."""
        result = instance.slow_method()
        assert isinstance(result, dict)
```

### Run Tests
```bash
# All tests
make test

# Specific test
pytest tests/unit/test_my_feature.py -v

# With coverage
pytest tests/ --cov=gcc_evolution --cov-report=html

# Only fast tests
pytest tests/ -m "not slow"
```

### Coverage Requirements
- Minimum 80% overall coverage
- 100% coverage for public APIs
- Aim for > 90% for critical modules

---

## Pull Request Process

### Before Submitting PR
1. ✅ Run `make lint` (format and quality checks)
2. ✅ Run `make test` (all tests pass)
3. ✅ Update documentation
4. ✅ Add entry to CHANGELOG.en.md
5. ✅ Verify no new dependencies added unnecessarily
6. ✅ Sign [Contributor License Agreement](#contributor-license-agreement)

### PR Description Template
```markdown
## Description
Brief description of changes.

## Type of Change
- [ ] Bug fix (non-breaking)
- [ ] New feature (non-breaking)
- [ ] Breaking change
- [ ] Documentation update

## Related Issues
Fixes #123
Related to #456

## Changes
- Change 1
- Change 2
- Change 3

## Testing
Describe testing performed:
- [ ] Unit tests added
- [ ] Integration tests added
- [ ] Manual testing

## Checklist
- [ ] Code follows style guide
- [ ] Tests pass locally
- [ ] Documentation updated
- [ ] No new warnings generated
- [ ] CLA signed
```

### Review Process
1. At least 1 maintainer review required
2. All CI checks must pass
3. Coverage must not decrease
4. Breaking changes require discussion
5. Final approval before merge

### Merge
- Squash commits for cleaner history
- Use `Squash and merge` on GitHub
- Delete branch after merge

---

## Contributor License Agreement

### Individual Contributor License Agreement
All individual contributors must sign the [Individual CLA](CONTRIBUTOR_LICENSE_AGREEMENT.en.md).

**To sign:**
1. Read the agreement
2. Sign with GitHub, email, or physical signature
3. Submit to: baodexiang@hotmail.com

### Corporate Contributor License Agreement
Corporate contributions require the [Corporate CLA](ENTERPRISE_CONTRIBUTOR_LICENSE_AGREEMENT.en.md).

**To sign:**
1. Legal representative reviews agreement
2. Sign with company seal
3. Submit to: legal@gcc-evo.dev

---

## Contribution Areas

### High-Priority Areas
- **Performance optimization** — Memory efficiency, retrieval speed
- **Test coverage** — Edge cases, error conditions
- **Documentation** — Guides, examples, tutorials
- **Bug fixes** — Issues labeled `bug`

### Great for Beginners
- Documentation improvements
- Test additions
- Code style fixes
- Error message improvements

Look for issues labeled `good first issue` or `help wanted`.

---

## Community

### Discussion Channels
- 💬 **Discussions** — https://github.com/baodexiang/gcc-evo/discussions
- 🐛 **Issues** — https://github.com/baodexiang/gcc-evo/issues
- 📧 **Email** — baodexiang@hotmail.com

### Getting Help
- Check existing issues/discussions first
- Ask questions in Discussions, not Issues
- For complex topics, start a Discussion before PR
- Maintainers respond within 48 hours

---

## Recognition

### Contributors are recognized in:
1. CONTRIBUTORS.md file
2. GitHub "Contributor" badge
3. Release notes and changelog
4. Monthly contributor report

---

## Questions?

- 📖 **Documentation**: https://github.com/baodexiang/gcc-evo/wiki
- 🐛 **Report Issue**: https://github.com/baodexiang/gcc-evo/issues
- 💬 **Discuss**: https://github.com/baodexiang/gcc-evo/discussions
- 📧 **Email**: baodexiang@hotmail.com

---

**Thank you for contributing to gcc-evo! 🎉**

[English](CONTRIBUTING.en.md) | [中文](CONTRIBUTING.md)
