# Quick Start â€” gcc-evo v5.305

**Get up and running in 10 minutes**

---

## Table of Contents
1. [Installation](#installation)
2. [Initialize Project](#initialize-project)
3. [Your First Loop](#your-first-loop)
4. [View Dashboard](#view-dashboard)
5. [Common Commands](#common-commands)
6. [Next Steps](#next-steps)

---

## Installation

### Option 1: PyPI (Recommended)
```bash
pip install gcc-evo
```

### Option 2: From Source
```bash
git clone https://github.com/baodexiang/gcc-evo.git
cd gcc-evo/opensource
pip install -e ".[dev]"
```

### Verify Installation
```bash
gcc-evo version
# Output: gcc-evo v5.305
```

---

## Initialize Project

### Create New Project
```bash
gcc-evo init --project my-trading-bot
cd my-trading-bot
```

### Directory Structure
```
my-trading-bot/
â”œâ”€â”€ .env                    # Environment variables
â”œâ”€â”€ .GCC/
â”‚   â”œâ”€â”€ gcc_evo.py         # Core engine
â”‚   â”œâ”€â”€ dashboard.html     # Visual dashboard
â”‚   â””â”€â”€ ...
â”œâ”€â”€ state/
â”‚   â”œâ”€â”€ improvements.json  # Task definitions
â”‚   â”œâ”€â”€ skillbank.jsonl    # Learned skills
â”‚   â””â”€â”€ ...
â””â”€â”€ config/
    â””â”€â”€ params.yaml        # Configuration
```

---

## Set Environment Variables

### Create `.env` file
```bash
cat > .env << 'EOF'
# LLM Provider (choose one)
ANTHROPIC_API_KEY=sk-ant-...
# or
OPENAI_API_KEY=sk-...
# or
GEMINI_API_KEY=...

# Optional
GCC_LOG_LEVEL=INFO
GCC_MEMORY_TTL=7
GCC_SKEPTIC_THRESHOLD=0.75
EOF
```

### Load Environment
```bash
source .env  # macOS/Linux
# or
set -a && source .env && set +a
```

---

## Your First Loop

### Step 0: L0 Setup (Required â€” new in v5.305)

Every loop requires a valid L0 session config. Run the interactive wizard first:

```bash
gcc-evo setup KEY-001
# Wizard prompts:
#   KEY number:        KEY-001
#   Evolution goal:    Improve error handling to reduce failure rate
#   Success criteria:  1. Error rate < 5%
#                      2. Recovery time < 30s
#   Human confirm:     Y/n
#   Max iterations:    0 (unlimited)
```

View or edit anytime:
```bash
gcc-evo setup --show    # view current config
gcc-evo setup --edit    # edit a field
```

### Step 1: Create a Task
```bash
gcc-evo pipe task "Improve error handling" \
  -k KEY-001 \
  -m core \
  -p P0

# Output: Created GCC-0001
```

### Step 2: Run Single Loop
```bash
gcc-evo loop GCC-0001 --once
```

**What happens:**
0. âœ… **L0 Gate** â€” Validates session config (goal, criteria, key)
1. âœ… **Task Audit** â€” Analyzes logs + finds issues
2. âœ… **Experience Cards** â€” Extracts patterns
3. âœ… **SkillBank** â€” Stores reusable rules
4. âœ… **Skeptic Gate** â€” Validates confidence
5. âœ… **Distillation** â€” Compresses knowledge
6. âœ… **Report** â€” Generates summary

### Step 3: Check Results
```bash
# View audit logs
tail -f state/audit/*.jsonl

# View learned skills
cat state/skillbank.jsonl | jq '.skill_name'

# View task status
gcc-evo pipe status GCC-0001
```

---

## View Dashboard

### Open Dashboard
```bash
# macOS/Linux
open .GCC/dashboard.html

# Windows
start .GCC/dashboard.html

# Web server
cd .GCC && python -m http.server 8000
# Then visit: http://localhost:8000/dashboard.html
```

### Dashboard Sections
- **Tasks** â€” GCC task hierarchy + status
- **Skills** â€” Learned patterns + accuracy
- **Timeline** â€” Loop execution history
- **Metrics** â€” Success rate by category
- **Issues** â€” Identified problems

---

## Common Commands

### Task Management
```bash
# List all tasks
gcc-evo pipe list

# Create new task
gcc-evo pipe task "Fix bug in parser" -k KEY-002 -m parser -p P1

# View task details
gcc-evo pipe status GCC-0001

# Check task details
gcc-evo pipe status GCC-0001
```

### Loop Execution
```bash
# Single iteration (test)
gcc-evo loop GCC-0001 --once

# Continuous loop (5-minute intervals)
gcc-evo loop GCC-0001

# Switch LLM provider mid-loop
gcc-evo loop GCC-0001 --provider gemini --once

# Background execution
gcc-evo loop GCC-0001 &
```

### Memory Management
```bash
# Check project health before memory maintenance
gcc-evo health

# Compact old memories
gcc-evo memory compact

# Export all state
gcc-evo memory export

# Export to backup file
gcc-evo memory export --output backup.json
```

### Debugging
```bash
# View generated loop audit logs
ls state/audit
tail -n 20 state/audit/GCC-0001_log.jsonl

# Enable debug logging
GCC_LOG_LEVEL=DEBUG gcc-evo loop GCC-0001 --once

# System health check
gcc-evo health
```

---

## Next Steps

### 1. Read Documentation
- **[README.en.md](README.en.md)** â€” Full feature overview
- **[TUTORIAL.en.md](TUTORIAL.en.md)** â€” Deep-dive guide
- **[CHANGELOG.en.md](CHANGELOG.en.md)** â€” Version history

### 2. Configure for Your Use Case
```bash
# Edit configuration
cat > config/params.yaml << 'EOF'
memory:
  sensory_ttl: 86400      # 24 hours
  shortterm_ttl: 604800   # 7 days

skeptic:
  confidence_threshold: 0.75

loop:
  interval: 300            # 5 minutes
  max_iterations: null     # unlimited
EOF
```

### 3. Create Real Tasks
```bash
# Example for trading system
gcc-evo pipe task "Reduce false signals" \
  -k KEY-001 \
  -m signals \
  -p P0

# Example for API optimization
gcc-evo pipe task "Improve retry logic" \
  -k KEY-002 \
  -m api \
  -p P1
```

### 4. Monitor Progress
```bash
# Watch dashboard in browser
open .GCC/dashboard.html

# Monitor logs in terminal
tail -f state/audit/*.jsonl | jq '.level, .message'

# Check skill quality
grep "skill_confidence" state/skillbank.jsonl | \
  jq -r '[.skill_name, .confidence] | @csv' | \
  column -t -s','
```

### 5. Customize for Scale
```bash
# For production, run in background
nohup gcc-evo loop GCC-0001 > logs/loop.log 2>&1 &

# Or use systemd service
cat > /etc/systemd/system/gcc-evo.service << 'EOF'
[Unit]
Description=gcc-evo Loop Service
After=network.target

[Service]
Type=simple
User=nobody
WorkingDirectory=/path/to/project
ExecStart=/usr/local/bin/gcc-evo loop GCC-0001
Restart=always
RestartSec=60

[Install]
WantedBy=multi-user.target
EOF

systemctl start gcc-evo
systemctl enable gcc-evo
```

---

## Troubleshooting

### Issue: API key not found
```bash
# Check environment
echo $ANTHROPIC_API_KEY

# Reload .env
source .env
export ANTHROPIC_API_KEY=sk-ant-...
```

### Issue: Loop not running
```bash
# Check logs
tail -f logs/gcc-evo.log

# Verify L0 config
gcc-evo setup --show

# Run in debug mode
GCC_LOG_LEVEL=DEBUG gcc-evo loop GCC-0001 --once
```

### Issue: Dashboard not loading
```bash
# Check file exists
ls -la .GCC/dashboard.html

# Serve with Python
cd .GCC && python -m http.server 8000

# Open in browser
curl http://localhost:8000/dashboard.html
```

### Issue: Out of memory
```bash
# Compact old memories
gcc-evo memory compact

# Check memory usage
du -sh state/

# Export if needed
gcc-evo memory export --output backup.json
```

---

## Key Concepts

### Three-Tier Memory
```
Sensory (24h) â†’ Recent events, raw observations
    â†“ (consolidation)
Short-term (7 days) â†’ Recent decisions, context
    â†“ (distillation)
Long-term (âˆž) â†’ Verified rules, patterns
```

### Skeptic Verification Gate
- Prevents unverified conclusions from entering memory
- Requires human review when confidence < threshold (0.75)
- Blocks LLM hallucinations from feedback loop

### Loop Cycle
```
Observe â†’ Analyze â†’ Extract â†’ Verify â†’ Distill â†’ Report â†’ Observe...
 (logs)    (audit)   (rules)  (gate)   (skills) (dashboard)
```

---

## Development

### Run Tests
```bash
make install-dev
make test
```

### Build Locally
```bash
make build
pip install dist/gcc_evo-5.305-py3-none-any.whl
```

### Contribute
See [CONTRIBUTING.en.md](CONTRIBUTING.en.md)

---

## Support

- ðŸ“– **Docs** â€” https://github.com/baodexiang/gcc-evo
- ðŸ› **Issues** â€” https://github.com/baodexiang/gcc-evo/issues
- ðŸ’¬ **Discussions** â€” https://github.com/baodexiang/gcc-evo/discussions
- ðŸ” **Security** â€” security@gcc-evo.dev

---

**Happy evolving! ðŸš€**

[English](QUICKSTART.en.md) | [ä¸­æ–‡](QUICKSTART.md)

