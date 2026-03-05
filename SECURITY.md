# Security Policy for gcc-evo

> **Responsible Disclosure**: Please report security vulnerabilities privately to **security@gcc-evo.dev** rather than opening public GitHub issues.

---

## Security Overview

gcc-evo is designed with **security-first principles** for handling sensitive data:

- **Stateless execution**: No data persistence between runs (except explicit user files)
- **Config isolation**: API keys separated from code via environment variables or `.local` config files
- **No telemetry**: Zero phone-home, zero tracking
- **Transparent logging**: All LLM interactions logged locally for audit
- **Open algorithm**: No obfuscation, security by design not obscurity

---

## Vulnerability Reporting

### Report Timeline

Security issues are classified by severity and handled on accelerated timelines:

| Severity | Timeline | Definition |
|----------|----------|-----------|
| **Critical** | 24 hours notification | Remote code execution, data breach, authentication bypass |
| **High** | 48 hours notification | Privilege escalation, DoS, information disclosure |
| **Medium** | 7 days notification | Partial bypass, low-impact crash, workaround available |
| **Low** | 30 days notification | Logging error, documentation issue, no user impact |

**Timeline explanation**:
- Notification = Acknowledgment sent to reporter
- Patch deadline = Public disclosure + patch release
- Grace period = 90 days for users to apply patch before public CVE

### How to Report

**Email**: security@gcc-evo.dev

**Include**:
```
Subject: [SECURITY] gcc-evo vulnerability report

From: [Your name/organization]
Email: [Your contact]

## Vulnerability Description
[Clear description of the issue]

## Severity Assessment
[Critical|High|Medium|Low] - Why?

## Steps to Reproduce
1. ...
2. ...

## Impact
[Who is affected? What data/systems?]

## Proof of Concept
[Code snippet, screenshot, or exploit if available]

## Suggested Remediation
[Your fix suggestion if applicable]
```

**Expected Response**:
1. **Within 24 hours**: Acknowledgment of receipt
2. **Within 7 days**: Initial assessment and timeline
3. **Within patch deadline**: Security patch and CVE assignment

### Do NOT Report Publicly

❌ **Do not**:
- Open GitHub issues for vulnerabilities
- Post on social media/forums
- Share exploit code publicly
- Demand payment or compensation

✅ **Do**:
- Email security@gcc-evo.dev
- Wait for acknowledgment
- Follow coordinated disclosure timeline
- Accept partial CVE (Low severity) may not be assigned

---

## Configuration Security

gcc-evo **never embeds API keys or credentials** in code. Instead:

### Environment Variables (Recommended)

```bash
# .bashrc / .zshrc / .env
export GCC_CLAUDE_KEY=sk-ant-...
export GCC_GEMINI_KEY=AIza...
export GCC_OPENAI_KEY=sk-proj-...
```

**Advantages**:
- Keys not in version control
- Easy to rotate per deployment
- Separate from application code

### Configuration Files (evolution.yaml)

```yaml
# evolution.yaml (COMMITTED)
llm_providers:
  claude:
    model: claude-opus-4

  # ❌ NEVER put keys here!
  # api_key: sk-ant-xxx  ← WRONG!
```

**To use keys**: Reference environment variables

```yaml
llm_providers:
  claude:
    api_key: ${GCC_CLAUDE_KEY}  # ← Reads from env var
    model: claude-opus-4
```

### Local Configuration (evolution.local.yaml)

For development/testing with keys:

```yaml
# evolution.local.yaml (NOT COMMITTED)
llm_providers:
  claude:
    api_key: sk-ant-dev-key-for-testing
    model: claude-opus-4
```

**Add to .gitignore**:
```bash
# .gitignore
evolution.local.yaml
*.local.yaml
.env.local
.env
config/secrets.json
```

---

## Data Handling & Privacy

### What gcc-evo Processes

gcc-evo **only processes** data explicitly provided by the user:

1. **LLM Prompts** → Sent to selected provider (Gemini/Claude/OpenAI)
2. **Local Files** → Read from user's filesystem only
3. **Conversation History** → Stored in `.GCC/` directory (user's machine)

### What gcc-evo Does NOT Process

- User IP addresses or network metadata
- Hardware identifiers or device fingerprints
- Browsing history or external data
- Third-party API data (except explicitly requested)

### Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│ User's Local Machine (No Telemetry)                         │
│                                                             │
│  User Input                                                 │
│  ↓                                                          │
│  .GCC/gcc_evo.py                                           │
│  ├─→ Read local files                                      │
│  ├─→ Build LLM prompt                                      │
│  ├─→ Send to LLM (via API)                                │
│  └─→ Store response in .GCC/                              │
│                                                             │
│  ↓ Only this crosses network ↓                             │
│                                                             │
│  Credentials: Sent only to official API endpoints          │
│  Data: Never sent to gcc-evo infrastructure               │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### What User Controls

Users have **full control** over:
- Which files gcc-evo reads
- Which LLM provider to use
- Which prompts to send
- Where to store outputs
- How to filter/sanitize before sending

---

## API Key Rotation & Revocation

### Rotate API Keys Regularly

**Every 90 days** (minimum):

```bash
# 1. Generate new API key in provider dashboard
#    Claude: https://console.anthropic.com/account/keys
#    OpenAI: https://platform.openai.com/account/api-keys
#    Gemini: https://aistudio.google.com/app/apikey

# 2. Update environment variable
export GCC_CLAUDE_KEY=sk-ant-new-key

# 3. Revoke old key in provider dashboard
# 4. Test new key
gcc-evo loop GCC-0001 --once --test
```

### Revoke Compromised Keys Immediately

If a key is leaked:

```bash
# 1. Revoke in provider dashboard (immediate)
# 2. Generate new key
# 3. Update environment variable
# 4. Run with new key to ensure working
# 5. Rotate key in all other environments (CI/CD, other machines)
```

---

## Secure Deployment

### Development Environment

```bash
# Use separate keys for development
export GCC_CLAUDE_KEY=sk-ant-dev-xxxxx

# Keys in ~/.bashrc are user-specific, not committed
# ~/.bashrc is NOT version-controlled (add to ~/.gitignore_global)
```

### Production Environment

For cloud deployment (AWS Lambda, Docker, etc.):

```bash
# Use cloud secret management
# AWS Secrets Manager:
aws secretsmanager get-secret-value --secret-id gcc-evo-keys

# Azure Key Vault:
az keyvault secret show --vault-name gcc-evo --name openai-key

# Docker:
docker run \
  --env GCC_CLAUDE_KEY="$SECRET_KEY" \
  gcc-evo:latest

# Never embed in Dockerfile or environment.yml
```

### CI/CD Pipelines

**GitHub Actions** example:

```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4

      - name: Run tests
        env:
          GCC_CLAUDE_KEY: ${{ secrets.GCC_CLAUDE_KEY }}
          GCC_OPENAI_KEY: ${{ secrets.GCC_OPENAI_KEY }}
        run: pytest tests/
```

**Keys are NOT printed in logs** (GitHub automatically masks secrets).

---

## Audit & Monitoring

### Local Audit Log

gcc-evo logs all LLM interactions to `.GCC/logs/`:

```
.GCC/logs/
├── gcc_evo.log         # Execution log
├── llm_calls.json      # JSON audit of all LLM calls (request + response)
├── errors.log          # Exceptions and errors
└── distill.log         # Distillation cycles
```

**Audit Log Format** (llm_calls.json):

```json
[
  {
    "timestamp": "2026-03-03T15:30:45Z",
    "provider": "claude",
    "model": "claude-opus-4",
    "prompt_length": 2048,
    "response_length": 1024,
    "tokens_used": 3072,
    "status": "success",
    "error": null
  }
]
```

**Note**: Prompts and responses **are not logged** by default (sensitive data). Only metadata is logged.

### Enable Full Prompt Logging (Development Only)

```yaml
# evolution.yaml
logging:
  log_prompts: false      # Set to true only for debugging
  log_responses: false    # Set to true only for debugging
```

⚠️ **WARNING**: Full logging includes all conversation data. Use only in development, not production.

### Audit Retention

- **Default**: 90 days (auto-deleted)
- **Custom**: Set in `evolution.yaml`:

```yaml
logging:
  retention_days: 180
```

### Manual Audit

```bash
# View recent LLM calls
tail -100 .GCC/logs/llm_calls.json | jq '.'

# Count API usage per provider
grep '"provider"' .GCC/logs/llm_calls.json | sort | uniq -c

# Search for errors
grep '"error"' .GCC/logs/llm_calls.json | grep -v null
```

---

## Known Security Issues

### Issue #1: Environment Variable Leakage in Error Messages (Fixed v5.290)

**Status**: ✓ Fixed in v5.290

**Description**: Error messages could include unmasked environment variable names.

**Resolution**: All error messages sanitized; variable names shown as `[MASKED]`.

**Affected Versions**: v5.0 - v5.289

**Mitigation**: Update to v5.290+

### Issue #2: LLM Response Validation (Status: Monitoring)

**Status**: ⚠️ Monitoring (mitigations in place)

**Description**: LLM can hallucinate credentials or malicious code in responses.

**Risk**: Low (responses are not auto-executed; user review required)

**Mitigations**:
- All code from LLM flagged with `[LLM-GENERATED]` tag
- User must review before execution
- No auto-apply for critical operations
- Skeptic validation layer prevents unverified changes

**Recommendation**: Always review generated code before deployment.

---

## Security Best Practices

### For Users

1. **Keep keys secret**
   - Never share `GCC_CLAUDE_KEY`, `GCC_OPENAI_KEY`, etc.
   - Never commit to GitHub
   - Use `.gitignore` for config files

2. **Rotate keys regularly**
   - Every 90 days (minimum)
   - Immediately if leaked or suspicious activity

3. **Monitor API usage**
   - Check your provider dashboard for unusual activity
   - Set usage alerts/limits

4. **Validate LLM output**
   - Review generated code before running
   - Don't auto-apply critical changes
   - Use `--dry-run` to preview

5. **Secure deployment**
   - Use secret management (AWS Secrets, Azure Key Vault)
   - Don't embed keys in Docker images
   - Use IAM roles instead of keys when possible

### For Developers

1. **No hardcoded secrets**
   ```python
   # ❌ WRONG
   api_key = "sk-ant-xxx"

   # ✅ CORRECT
   api_key = os.getenv("GCC_CLAUDE_KEY")
   ```

2. **Validate all user input**
   ```python
   # ✅ Always validate file paths, prompts, etc.
   file_path = validate_file_path(user_input)
   ```

3. **Mask sensitive data in logs**
   ```python
   # ✅ Log with masking
   log.info(f"Using key: {api_key[:10]}...")
   ```

4. **Use type hints & validation**
   ```python
   from typing import List
   from pydantic import BaseModel

   class Config(BaseModel):
       api_key: str
       model: str
   ```

5. **Dependency scanning**
   ```bash
   # Check for vulnerable dependencies
   pip install safety
   safety check
   ```

---

## Compliance & Certifications

### Privacy Standards

gcc-evo complies with:

- **GDPR** (General Data Protection Regulation)
  - No personal data collection
  - Users have full data control
  - Right to deletion (delete `.GCC/` directory)

- **CCPA** (California Consumer Privacy Act)
  - Transparent data usage
  - No third-party sharing
  - User opt-out: Stop using gcc-evo

- **ISO 27001** (Information Security Management)
  - Secure configuration management
  - Incident response procedures
  - Regular security audits

### Data Residency

- **Data stays local** on user's machine
- **No cloud storage** of user data
- **User chooses provider**: Claude, OpenAI, Gemini, DeepSeek
- **User retains all rights** to their data

---

## Security Update Process

### Patch Release Cycle

1. **Report received** → Severity assessment
2. **Development** → Fix implemented in dev branch
3. **Testing** → Internal tests + community review
4. **Release** → Security patch released
5. **Disclosure** → Advisory published (coordinated with reporter)
6. **Monitoring** → Track adoption and incidents

### Subscribe to Security Advisories

```bash
# Watch the repository for security releases
# GitHub → Settings → Notifications → Custom notifications → Security alerts

# Or via email
git clone https://github.com/baodexiang/gcc-evo.git
cd gcc-evo
git config user.email "your-email@example.com"
```

---

## Contact

**Security Issues**: security@gcc-evo.dev

**General Questions**: baodexiang@hotmail.com

**GitHub Issues**: https://github.com/baodexiang/gcc-evo/issues (for non-security)

---

## Security Policy Version

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-03-03 | Initial policy for v5.290 |

**Last Updated**: March 3, 2026
