# Security Policy

## Reporting Security Vulnerabilities

**Please do not open public GitHub issues for security vulnerabilities.**

If you discover a security vulnerability in gcc-evo, please report it responsibly to:

ðŸ“§ **security@gcc-evo.dev**

Include:
- Description of vulnerability
- Affected component/version
- Steps to reproduce
- Potential impact
- Suggested fix (optional)

### Response Timeline
- **24 hours** â€” Acknowledgment of receipt
- **72 hours** â€” Initial assessment and timeline
- **30 days** â€” Patch release and disclosure
- **90 days** â€” Public disclosure (if not patched earlier)

---

## Security Best Practices

### 1. Environment Variable Isolation

**DO** âœ…
```bash
# Use environment variables
export ANTHROPIC_API_KEY=sk-ant-...
gcc-evo loop GCC-0001
```

**DON'T** âŒ
```bash
# Hardcode API keys
gcc-evo loop GCC-0001 --api-key sk-ant-...
grep "sk-ant" config.yaml
```

### 2. Memory Persistence Security

**DO** âœ…
```bash
# Encrypt state files for production
chmod 600 state/*.json
chmod 700 state/

# Use environment-specific configs
cp config/prod.yaml config/params.yaml
```

**DON'T** âŒ
```bash
# Commit secrets to git
git add .env
git add state/api_keys.json

# Use world-readable permissions
chmod 777 state/
```

### 3. Input Validation

**DO** âœ…
```python
# Validate all external inputs
def create_task(title, key_id):
    assert isinstance(title, str), "Title must be string"
    assert len(title) < 256, "Title too long"
    assert key_id.startswith("KEY-"), "Invalid key format"
    return store_task(title, key_id)
```

**DON'T** âŒ
```python
# Accept untrusted input directly
task_title = request.args.get('title')  # User input
eval(task_title)  # Dangerous!
```

### 4. API Communication

**DO** âœ…
```bash
# Use HTTPS only
export OPENAI_API_URL=https://api.openai.com/v1

# Verify SSL certificates
pip install certifi
```

**DON'T** âŒ
```bash
# Use HTTP for sensitive data
export OPENAI_API_URL=http://api.openai.com  # Insecure!

# Disable SSL verification
export CURL_CA_BUNDLE=""
```

### 5. Audit Logging

**DO** âœ…
```python
# Log all LLM decisions
log_audit_event(
    task_id="GCC-0001",
    action="decision_made",
    confidence=0.95,
    timestamp=datetime.now(),
    user="admin"
)
```

**DON'T** âŒ
```python
# Silently process decisions
llm_decision = get_decision()
apply_decision(llm_decision)
# No log record
```

---

## Configuration Security

### `.env` File (Local Development)
```bash
# Create with restricted permissions
touch .env
chmod 600 .env

# Contents
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GCC_LOG_LEVEL=INFO
```

### Never commit to Git
```bash
# Add to .gitignore
echo ".env" >> .gitignore
echo "state/api_keys.json" >> .gitignore
echo "logs/*.log" >> .gitignore

# Verify before commit
git diff --cached | grep -i "sk-\|secret\|password"
```

### Production Deployment
```bash
# Use secrets management system
# Option 1: AWS Secrets Manager
aws secretsmanager get-secret-value --secret-id gcc-evo

# Option 2: HashiCorp Vault
vault kv get secret/gcc-evo

# Option 3: GitHub Actions Secrets
echo ${{ secrets.ANTHROPIC_API_KEY }}
```

---

## Memory Security

### Data Classification
```
PUBLIC     â†’ Configuration, schemas
INTERNAL   â†’ Audit logs, metrics
SENSITIVE  â†’ API keys, user data
CRITICAL   â†’ Security credentials, encryption keys
```

### Retention Policy
```
Sensory (24h)   â†’ Raw logs, auto-purged
Short-term (7d) â†’ Discussion history, encrypted
Long-term (âˆž)   â†’ Verified patterns, immutable
```

### Data Encryption
```bash
# For sensitive state
openssl enc -aes-256-cbc -in state/sensitive.json -out state/sensitive.json.enc

# Decryption
openssl enc -d -aes-256-cbc -in state/sensitive.json.enc -out state/sensitive.json
```

---

## Dependency Security

### Regular Audits
```bash
# Check for vulnerabilities
pip install safety
safety check

# Or use pip-audit
pip install pip-audit
pip-audit
```

### Keep Dependencies Updated
```bash
# Use Dependabot (GitHub)
# Automatically creates PRs for updates
# See .github/dependabot.yml

# Or manually
pip list --outdated
pip install --upgrade package-name
```

### Lock Versions
```bash
# Generate requirements.txt with exact versions
pip freeze > requirements.txt

# Use in production
pip install -r requirements.txt
```

---

## Code Security

### Static Analysis
```bash
# Bandit for security issues
pip install bandit
bandit -r gcc_evolution/

# Flake8 for code quality
flake8 gcc_evolution/

# MyPy for type safety
mypy gcc_evolution/ --strict
```

### Testing
```bash
# Run security tests
make security

# Or manually
pytest tests/ -v --cov=gcc_evolution

# Check coverage
coverage report --fail-under=80
```

### Code Review
```bash
# Pre-commit hooks prevent bad commits
pip install pre-commit
pre-commit install
pre-commit run --all-files

# CI/CD validation
# See .github/workflows/
```

---

## Network Security

### API Communication
```python
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Secure session with retries
session = requests.Session()
retry = Retry(
    total=3,
    backoff_factor=0.3,
    status_forcelist=(500, 502, 504)
)
adapter = HTTPAdapter(max_retries=retry)
session.mount('https://', adapter)

# Request with timeout
response = session.get(
    'https://api.example.com/v1/data',
    timeout=10,  # Prevent hanging
    verify=True  # Verify SSL certificate
)
```

### Rate Limiting
```python
from ratelimit import limits, sleep_and_retry

@sleep_and_retry
@limits(calls=100, period=60)  # 100 calls per minute
def api_call(endpoint):
    return requests.get(endpoint)
```

---

## Access Control

### File Permissions
```bash
# Source code (readable)
chmod 644 *.py
chmod 755 gcc_evolution/

# Configuration (restricted)
chmod 600 config/*.yaml
chmod 700 config/

# State files (restricted)
chmod 600 state/*.json
chmod 700 state/

# Logs (readable by owner)
chmod 600 logs/*.log
chmod 700 logs/
```

### User Access
```bash
# Create dedicated user for service
useradd -r -s /bin/false gcc-evo

# Restrict permissions
chown -R gcc-evo:gcc-evo /opt/gcc-evo
chmod -R u=rwX,g=,o= /opt/gcc-evo
```

---

## Vulnerability Disclosure

### Severity Levels
- **CRITICAL** (9.0-10.0) â€” Authentication bypass, data breach risk
- **HIGH** (7.0-8.9) â€” Unauthorized access, information disclosure
- **MEDIUM** (4.0-6.9) â€” Reduced functionality, moderate impact
- **LOW** (0.1-3.9) â€” Minor issues, cosmetic problems

### Disclosure Timeline
1. **Day 1** â€” Vulnerability reported to security@gcc-evo.dev
2. **Day 2** â€” We confirm receipt and assess severity
3. **Days 3-30** â€” Development and testing of fix
4. **Day 31+** â€” Public disclosure and patch release

We appreciate responsible disclosure and will:
- Credit reporters in security advisory
- Provide 90-day advance notice before public disclosure
- Prioritize critical issues for emergency patches

---

## Security Checklist

### Before Production Deployment
- [ ] Environment variables configured securely
- [ ] API keys stored in secrets manager
- [ ] SSL/TLS enabled for all communication
- [ ] File permissions restricted (600/700)
- [ ] Audit logging enabled
- [ ] Dependencies audited for vulnerabilities
- [ ] HTTPS enforced (no HTTP)
- [ ] Database encrypted
- [ ] Backups encrypted
- [ ] Access logs enabled

### Regular Maintenance
- [ ] Weekly dependency security updates
- [ ] Monthly penetration testing
- [ ] Quarterly security audit
- [ ] Annual third-party assessment
- [ ] Incident response plan tested
- [ ] Vulnerability disclosure policy reviewed

---

## Support

For security questions or concerns:
- ðŸ“§ **Email**: security@gcc-evo.dev
- ðŸ”— **GitHub Security Advisory**: https://github.com/baodexiang/gcc-evo/security/advisories
- ðŸ“‹ **Responsible Disclosure**: https://github.com/baodexiang/gcc-evo/security/policy

---

**Last Updated**: 2026-03-05
**Version**: 5.400



