"""
GCC v4.75 — Self-Check & Project Adaptor
Runs on every `gcc-evo` startup or explicitly via `gcc-evo check`.

1. Verifies all GCC modules and files
2. Auto-creates missing directories
3. Checks config version and migrates if needed
4. Generates .gcc/STATUS.md for LLM context on restart
5. Auto-commits with smart message (shows key files changed)
6. Auto-push to remote if configured
"""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    import yaml
except ImportError:
    yaml = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ═══ Directory Structure ═══

REQUIRED_DIRS = [
    ".gcc",
    ".gcc/experiences",
    ".gcc/local_memory",
    ".gcc/params",
    ".gcc/pipeline",
    ".gcc/handoffs",
    ".gcc/verification",
    ".gcc/branches",
    ".gcc/consolidation",
]

REQUIRED_FILES = {
    ".gcc/evolution.yaml": "config",
    ".gcc/keys.yaml": "keys",
}


def ensure_directories() -> list[str]:
    """Create missing directories. Returns list of created."""
    created = []
    for d in REQUIRED_DIRS:
        p = Path(d)
        if not p.exists():
            p.mkdir(parents=True, exist_ok=True)
            created.append(d)
    return created


def ensure_keys_yaml() -> bool:
    """Create keys.yaml if missing."""
    p = Path(".gcc/keys.yaml")
    if not p.exists():
        if yaml:
            p.write_text(yaml.dump({}, allow_unicode=True), "utf-8")
        else:
            p.write_text("{}\n", "utf-8")
        return True
    return False


# ═══ Config Migration ═══

def migrate_config() -> list[str]:
    """Migrate evolution.yaml to v4.75 format. Returns list of changes."""
    changes = []
    config_path = Path(".gcc/evolution.yaml")

    if not config_path.exists():
        return changes

    if not yaml:
        return changes

    raw = yaml.safe_load(config_path.read_text("utf-8")) or {}

    # Ensure version
    old_version = raw.get("version", "")
    if old_version != "5.050":
        raw["version"] = "5.050"
        changes.append(f"version: {old_version} -> 5.050")

    # Ensure constraints section
    if "constraints" not in raw:
        raw["constraints"] = {
            "enabled": True,
            "max_per_key": 20,
            "min_confidence": 0.3,
            "auto_generate_from_failures": True,
        }
        changes.append("added constraints section")

    # Ensure skills section
    if "skills" not in raw:
        raw["skills"] = {
            "enabled": True,
            "log_calls": True,
        }
        changes.append("added skills section")

    # Ensure self_check section
    if "self_check" not in raw:
        raw["self_check"] = {
            "on_startup": True,
            "generate_status_md": True,
        }
        changes.append("added self_check section")

    # Ensure pipeline section has v4.5 fields
    if "pipeline" not in raw:
        raw["pipeline"] = {
            "max_concurrent": 3,
            "max_iterations": 3,
            "gate_strict": True,
        }
        changes.append("added pipeline section")

    # Ensure handoff section has v4.5 fields
    if "handoff" not in raw:
        raw["handoff"] = {
            "auto_detect": True,
            "source_agent": "claude-code",
        }
        changes.append("added handoff section")

    if changes:
        config_path.write_text(
            yaml.dump(raw, allow_unicode=True, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )

    return changes


# ═══ Status Generation ═══

def generate_status_md() -> Path:
    """
    Generate .gcc/STATUS.md — the single file any LLM reads on restart.
    Contains: project state, active KEYs, pipeline status, constraints, recent handoffs.
    """
    lines = [
        f"# GCC Status — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
    ]

    # Project info
    try:
        config_path = Path(".gcc/evolution.yaml")
        if config_path.exists() and yaml:
            raw = yaml.safe_load(config_path.read_text("utf-8")) or {}
            proj = raw.get("project", {})
            lines.append(f"## Project: {proj.get('name', 'unknown')}")
            lines.append(f"GCC version: {raw.get('version', '?')}")
        else:
            lines.append("## Project: (no config)")
    except Exception as e:
        logger.warning("[SELFCHECK] failed to read project config: %s", e)
        lines.append("## Project: (config error)")

    lines.append("")

    # Git status
    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, timeout=5).stdout.strip()
        dirty_count = len(dirty.split("\n")) if dirty else 0
        last_commit = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            capture_output=True, text=True, timeout=5).stdout.strip()
        lines.append(f"## Git: {branch}")
        lines.append(f"Last commit: {last_commit}")
        if dirty_count > 0:
            lines.append(f"**Dirty: {dirty_count} files**")
        lines.append("")
    except Exception as e:
        logger.warning("[SELFCHECK] failed to read git status: %s", e)

    # Active KEYs
    keys_path = Path(".gcc/keys.yaml")
    if keys_path.exists() and yaml:
        try:
            keys = yaml.safe_load(keys_path.read_text("utf-8")) or {}
            open_keys = {k: v for k, v in keys.items()
                        if isinstance(v, dict) and v.get("status") == "open"}
            if open_keys:
                lines.append(f"## Active KEYs ({len(open_keys)})")
                for k, v in open_keys.items():
                    task = v.get("task", "")
                    lines.append(f"- **{k}**: {task}")
                lines.append("")
        except Exception as e:
            logger.warning("[SELFCHECK] failed to parse keys.yaml: %s", e)

    # Pipeline tasks
    try:
        pipeline_path = Path(".gcc/pipeline/tasks.json")
        if pipeline_path.exists():
            tasks = json.loads(pipeline_path.read_text("utf-8"))
            active = [t for t in tasks if t.get("stage") not in ("done", "failed")]
            if active:
                lines.append(f"## Pipeline ({len(active)} active)")
                for t in active[:10]:
                    lines.append(f"- [{t.get('task_id')}] {t.get('title', '')} "
                               f"({t.get('stage', '?')}) P{t.get('priority', '?')}")
                lines.append("")
    except Exception as e:
        logger.warning("[SELFCHECK] failed to read pipeline tasks: %s", e)

    # Params status
    try:
        params_dir = Path(".gcc/params")
        if params_dir.exists():
            yamls = list(params_dir.glob("*.yaml"))
            if yamls:
                lines.append(f"## Params ({len(yamls)} products)")
                for yf in sorted(yamls)[:12]:
                    sym = yf.stem.upper()
                    try:
                        data = yaml.safe_load(yf.read_text("utf-8")) or {}
                        bt = data.get("backtest", {})
                        sharpe = bt.get("sharpe")
                        if sharpe is not None:
                            lines.append(f"- {sym}: Sharpe={sharpe:.2f}")
                        else:
                            lines.append(f"- {sym}: no backtest")
                    except Exception as e:
                        logger.warning("[SELFCHECK] failed to read params for %s: %s", sym, e)
                        lines.append(f"- {sym}: (read error)")
                lines.append("")
    except Exception as e:
        logger.warning("[SELFCHECK] failed to read params directory: %s", e)

    # Constraints
    try:
        cpath = Path(".gcc/constraints.json")
        if cpath.exists():
            cdata = json.loads(cpath.read_text("utf-8"))
            active_c = [c for c in cdata if c.get("active", True)]
            if active_c:
                lines.append(f"## Constraints ({len(active_c)} active)")
                for c in active_c[:5]:
                    lines.append(f"- {c.get('rule', '?')}")
                if len(active_c) > 5:
                    lines.append(f"- ... and {len(active_c)-5} more")
                lines.append("")
    except Exception as e:
        logger.warning("[SELFCHECK] failed to read constraints: %s", e)

    # Recent handoffs
    try:
        ho_dir = Path(".gcc/handoffs")
        if ho_dir.exists():
            hos = sorted(ho_dir.glob("HO_*.json"), reverse=True)[:3]
            if hos:
                lines.append(f"## Recent Handoffs")
                for hf in hos:
                    try:
                        hdata = json.loads(hf.read_text("utf-8"))
                        lines.append(
                            f"- [{hdata.get('handoff_id', '?')}] "
                            f"{hdata.get('key', '')} — "
                            f"{hdata.get('changes_summary', '')[:50]}"
                        )
                    except Exception as e:
                        logger.warning("[SELFCHECK] failed to parse handoff %s: %s", hf.name, e)
                lines.append("")
    except Exception as e:
        logger.warning("[SELFCHECK] failed to read handoffs directory: %s", e)

    # Branch-specific handoffs
    try:
        branches_dir = Path(".gcc/branches")
        if branches_dir.exists():
            for md in sorted(branches_dir.glob("*/handoff.md")):
                key_slug = md.parent.name
                content = md.read_text("utf-8")
                # Show first 3 lines
                first_lines = content.strip().split("\n")[:3]
                lines.append(f"## Branch: {key_slug}")
                for fl in first_lines:
                    lines.append(fl)
                lines.append("")
    except Exception as e:
        logger.warning("[SELFCHECK] failed to read branch handoffs: %s", e)

    # Write
    status_path = Path(".gcc/STATUS.md")
    status_path.write_text("\n".join(lines), encoding="utf-8")
    return status_path


def _auto_commit(dirty_lines: list[str]) -> bool:
    """
    Auto-commit all dirty files with a smart descriptive message.
    Shows key files changed, hides noise. Auto-push if remote exists.
    Returns True if commit succeeded.
    """
    try:
        # Ensure .gitignore exists (separates code from runtime data)
        _ensure_gitignore()

        # Ensure git user is configured
        name = subprocess.run(
            ["git", "config", "user.name"],
            capture_output=True, text=True, timeout=5).stdout.strip()
        if not name:
            subprocess.run(
                ["git", "config", "user.name", "GCC"],
                capture_output=True, timeout=5)
            subprocess.run(
                ["git", "config", "user.email", "gcc@local"],
                capture_output=True, timeout=5)

        # Stage all (respects .gitignore — runtime data won't be added)
        subprocess.run(
            ["git", "add", "-A"],
            capture_output=True, timeout=10)

        # Build smart commit message
        msg = _build_commit_msg(dirty_lines)
        result = subprocess.run(
            ["git", "commit", "-m", msg],
            capture_output=True, text=True, timeout=15)

        if result.returncode != 0:
            return False

        # Auto-push if remote exists (silent fail if no remote)
        try:
            has_remote = subprocess.run(
                ["git", "remote"],
                capture_output=True, text=True, timeout=5).stdout.strip()
            if has_remote:
                subprocess.run(
                    ["git", "push"],
                    capture_output=True, text=True, timeout=30)
        except Exception as e:
            logger.warning("[SELFCHECK] auto-push failed: %s", e)

        return True
    except Exception as e:
        logger.warning("[SELFCHECK] auto-commit failed: %s", e)
        return False


# Files that are "noise" — auto-generated, not worth mentioning in commit msg
_NOISE_PATTERNS = {
    "STATUS.md", "evolution.yaml", "__pycache__", ".pyc",
    ".DS_Store", "Thumbs.db",
}

# Meaningful file extensions
_CODE_EXTS = {".py", ".yaml", ".yml", ".json", ".md", ".toml", ".cfg", ".txt"}


def _build_commit_msg(dirty_lines: list[str]) -> str:
    """
    Build commit message highlighting meaningful changes.
    Example: [GCC] signal_filter.py, SPY-ATR/params.yaml (+2 other)
    """
    meaningful = []
    noise_count = 0

    for line in dirty_lines:
        path = line[3:].strip().strip('"')
        fname = Path(path).name

        if any(pat in fname for pat in _NOISE_PATTERNS):
            noise_count += 1
            continue

        ext = Path(fname).suffix.lower()
        if ext in _CODE_EXTS or not ext:
            meaningful.append(path)
        else:
            noise_count += 1

    if not meaningful:
        return f"[GCC] auto-sync {len(dirty_lines)} files"

    # Show up to 3 key files with shortened paths
    shown = []
    for p in meaningful[:3]:
        parts = Path(p).parts
        if len(parts) > 2:
            short = "/".join(parts[-2:])
        else:
            short = Path(p).name
        shown.append(short)

    remainder = len(meaningful) - len(shown) + noise_count
    msg = "[GCC] " + ", ".join(shown)
    if remainder > 0:
        msg += f" (+{remainder} other)"

    if len(msg) > 72:
        msg = msg[:69] + "..."

    return msg


# Default .gitignore content — v4.98 comprehensive rules
_GITIGNORE_GCC_MARKER = "# GCC v4.98 — runtime data"

_GITIGNORE_TEMPLATE = """\
# GCC v4.98 — runtime data (auto-generated, do not track)
.gcc/experiences/
.gcc/local_memory/
.gcc/verification/
.gcc/consolidation/
.gcc/STATUS.md
.GCC/.gcc/
.GCC/*.db
.GCC/anchor_log.jsonl
.GCC/anchor_state.json
.GCC/anchor_today.json
.GCC/human_anchors.json
.GCC/state.json
.GCC/duckdb_sources.json
.GCC/graph.json
.GCC/suggestions.jsonl
.GCC/tasks.jsonl
.GCC/knowledge_index.jsonl
.GCC/paper_fetch.jsonl
.GCC/research_history.jsonl
.GCC/research_processed.json
.GCC/research_workflow.jsonl
.GCC/skillbank.jsonl
.GCC/STATUS.md
.GCC/.gcc_state.yaml
.GCC/schedule.json
.GCC/nul
.GCC/analysis/
.GCC/experiences/
.GCC/local_memory/
.GCC/verification/
.GCC/consolidation/
.GCC/knowledge/
.GCC/knowledge_drafts/
.GCC/sensory/
.GCC/snapshots/
.GCC/pipeline/
.GCC/scripts/
.GCC/build/
.GCC/failure_logs/
.GCC/handoffs/*.json
.GCC/dashboard.html
.GCC/gcc_dashboard.html
.GCC/doc/*.tar
.GCC/doc/*.tar.gz
.GCC/doc/*.gz
.GCC/doc/*.zip
.GCC/gcc_v*.zip
.GCC/**/__pycache__/

# Python
__pycache__/
*.pyc
*.pyo
*.egg-info/

# System
.DS_Store
Thumbs.db
*.swp
*~

# Logs
*.log
logs/
"""


def _ensure_gitignore():
    """Ensure .gitignore has GCC runtime exclusion rules (v4.98+)."""
    gi = Path(".gitignore")
    if not gi.exists():
        gi.write_text(_GITIGNORE_TEMPLATE, encoding="utf-8")
        return

    content = gi.read_text("utf-8")
    # Already has v4.98+ comprehensive rules — skip
    if _GITIGNORE_GCC_MARKER in content:
        return
    # Has externally managed comprehensive rules — skip
    if ".GCC/*.db" in content or ".GCC/gcc.db" in content:
        return
    # No GCC rules at all — append
    if ".gcc/experiences/" not in content:
        content += "\n" + _GITIGNORE_TEMPLATE
        gi.write_text(content, encoding="utf-8")


# ═══ Full Self-Check ═══

def run_self_check(verbose: bool = False) -> dict:
    """
    Complete self-check. Returns structured result.
    Called on startup or via `gcc-evo check`.
    """
    result = {
        "timestamp": _now(),
        "version": "4.8",
        "checks": [],
        "issues": [],
        "actions": [],
    }

    # 1. Directories
    created = ensure_directories()
    if created:
        result["actions"].extend([f"Created dir: {d}" for d in created])
    result["checks"].append({"name": "directories", "ok": True,
                            "detail": f"{len(created)} created"})

    # 2. Keys YAML
    if ensure_keys_yaml():
        result["actions"].append("Created .gcc/keys.yaml")

    # 3. Config migration
    changes = migrate_config()
    if changes:
        result["actions"].extend([f"Config: {c}" for c in changes])
    result["checks"].append({"name": "config", "ok": True,
                            "detail": f"{len(changes)} migrations"})

    # 4. Experience DB
    try:
        from .experience_store import GlobalMemory
        gm = GlobalMemory()
        count = gm.count()
        result["checks"].append({"name": "experience_db", "ok": True,
                                "detail": f"{count} cards"})
    except Exception as e:
        result["checks"].append({"name": "experience_db", "ok": False,
                                "detail": str(e)})
        result["issues"].append(f"Experience DB: {e}")

    # 5. Params
    try:
        from .params import ParamStore
        products = ParamStore.list_products()
        result["checks"].append({"name": "params", "ok": True,
                                "detail": f"{len(products)} products"})
    except Exception as e:
        result["checks"].append({"name": "params", "ok": False,
                                "detail": str(e)})

    # 6. Constraints
    try:
        from .constraints import ConstraintStore
        cs = ConstraintStore()
        stats = cs.stats()
        result["checks"].append({"name": "constraints", "ok": True,
                                "detail": f"{stats['active']} active"})
    except Exception as e:
        result["checks"].append({"name": "constraints", "ok": False,
                                "detail": str(e)})

    # 7. Generate STATUS.md (before git, so it gets committed)
    try:
        status_path = generate_status_md()
        result["checks"].append({"name": "status_md", "ok": True,
                                "detail": str(status_path)})
    except Exception as e:
        result["checks"].append({"name": "status_md", "ok": False,
                                "detail": str(e)})

    # 7.5 Auto-generate knowledge card from dirty files
    try:
        from .auto_card import auto_generate_card
        card_path = auto_generate_card()
        if card_path:
            result["actions"].append(f"Auto-generated card: {card_path.name}")
            result["checks"].append({"name": "auto_card", "ok": True,
                                    "detail": str(card_path.name)})
    except Exception as e:
        logger.warning("[SELFCHECK] auto-card generation failed: %s", e)
        # Non-blocking — card generation failure shouldn't stop check

    # 8. Git — auto-commit dirty files (after STATUS.md + card so they're included)
    try:
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, timeout=5).stdout.strip()
        dirty_lines = [l for l in dirty.split("\n") if l.strip()] if dirty else []
        dirty_count = len(dirty_lines)

        # Skip if only STATUS.md changed (timestamp update, not worth a commit)
        if dirty_count == 1 and dirty_lines[0].strip().endswith("STATUS.md"):
            result["checks"].append({"name": "git", "ok": True,
                                    "detail": "clean (STATUS.md only)"})
        elif dirty_count > 0:
            auto_committed = _auto_commit(dirty_lines)
            if auto_committed:
                result["actions"].append(f"Auto-committed {dirty_count} dirty files")
                result["checks"].append({"name": "git", "ok": True,
                                        "detail": f"auto-committed {dirty_count} files"})
            else:
                result["checks"].append({"name": "git", "ok": True,
                                        "detail": f"{dirty_count} dirty (auto-commit failed, non-blocking)"})
        else:
            result["checks"].append({"name": "git", "ok": True,
                                    "detail": "clean"})
    except Exception as e:
        logger.warning("[SELFCHECK] git check failed: %s", e)
        result["checks"].append({"name": "git", "ok": True,
                                "detail": "not a git repo"})

    result["healthy"] = len(result["issues"]) == 0
    return result


def format_check_report(result: dict) -> str:
    """Human-readable self-check report."""
    lines = [
        f"  GCC v4.8 Self-Check — {result['timestamp'][:19]}",
        f"  {'═'*50}",
    ]

    for c in result["checks"]:
        icon = "✓" if c["ok"] else "✗"
        lines.append(f"  {icon} {c['name']}: {c['detail']}")

    if result["actions"]:
        lines.append("")
        lines.append("  Actions taken:")
        for a in result["actions"]:
            lines.append(f"    → {a}")

    if result["issues"]:
        lines.append("")
        lines.append("  ⚠ Issues:")
        for i in result["issues"]:
            lines.append(f"    ! {i}")

    status = "✅ Healthy" if result["healthy"] else "⚠ Issues found"
    lines.append("")
    lines.append(f"  Status: {status}")
    return "\n".join(lines)
