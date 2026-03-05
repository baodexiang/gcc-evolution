"""
GCC v4.75 — Auto Knowledge Card Generator
每次 gcc-evo check 时自动从 git diff + task 信息生成知识卡。

原则：
  - 零人工干预：代码变更自动产生知识卡
  - 只记录有意义的变更（不记录 config/STATUS.md 等自动生成文件）
  - 每次 commit 最多生成一张卡，避免噪音
  - 卡片格式：人可读 markdown，放入 improvements/{KEY}/

触发时机：
  selfcheck → 检测到 dirty files → 生成卡 → 一起 auto-commit
"""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ── Noise filter ──

_NOISE_PATTERNS = {
    "STATUS.md", "STATUS", "evolution.yaml", ".gcc_state",
    "__pycache__", ".pyc", ".DS_Store", "Thumbs.db",
    ".log", "watchdog.log", "consolidation",
}

_CODE_EXTS = {".py", ".js", ".ts", ".jsx", ".tsx", ".rs", ".go", ".c", ".cpp", ".h",
              ".java", ".rb", ".sh", ".bat", ".ps1"}

_CONFIG_EXTS = {".yaml", ".yml", ".json", ".toml", ".cfg", ".ini", ".env"}


def _is_meaningful(path: str) -> bool:
    """Is this file change worth recording in a knowledge card?"""
    fname = Path(path).name
    if any(pat in fname for pat in _NOISE_PATTERNS):
        return False
    ext = Path(fname).suffix.lower()
    return ext in _CODE_EXTS or ext in _CONFIG_EXTS or ext == ".md"


def _classify_change(path: str) -> str:
    """Classify a file change for the knowledge card."""
    ext = Path(path).suffix.lower()
    if ext in _CODE_EXTS:
        return "code"
    if ext in _CONFIG_EXTS:
        return "config"
    if ext == ".md":
        return "docs"
    return "other"


# ── Git diff summary ──

def _get_diff_summary() -> dict:
    """Get a structured summary of uncommitted changes."""
    try:
        # Staged + unstaged changes
        result = subprocess.run(
            ["git", "diff", "--stat", "HEAD"],
            capture_output=True, text=True, timeout=10)
        staged = subprocess.run(
            ["git", "diff", "--cached", "--stat"],
            capture_output=True, text=True, timeout=10)

        # Untracked files
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            capture_output=True, text=True, timeout=5).stdout.strip()

        # Porcelain for file list
        porcelain = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, timeout=5).stdout.strip()

        files = []
        for line in porcelain.split("\n"):
            if not line.strip():
                continue
            status = line[:2].strip()
            path = line[3:].strip().strip('"')
            if _is_meaningful(path):
                files.append({
                    "path": path,
                    "status": status,  # M=modified, A=added, D=deleted, ?=untracked
                    "type": _classify_change(path),
                })

        return {
            "files": files,
            "total_dirty": len(porcelain.split("\n")) if porcelain else 0,
            "meaningful": len(files),
        }
    except Exception as e:
        logger.warning("[AUTO_CARD] git diff failed: %s", e)
        return {"files": [], "total_dirty": 0, "meaningful": 0}


# ── Task context ──

def _find_active_task() -> dict | None:
    """Find the most relevant active task from pipeline."""
    # Try both .gcc and .GCC
    for gcc_dir in [".gcc", ".GCC"]:
        tasks_path = Path(f"{gcc_dir}/pipeline/tasks.json")
        if tasks_path.exists():
            try:
                tasks = json.loads(tasks_path.read_text("utf-8"))
                # Priority: integrate > test > implement > design > analyze
                stage_priority = ["integrate", "test", "implement", "design", "analyze"]
                for stage in stage_priority:
                    for t in tasks:
                        if t.get("stage") == stage:
                            return t
                # Fallback: any non-done task
                for t in tasks:
                    if t.get("stage") not in ("done", "failed", "suspended", "pending"):
                        return t
            except Exception as e:
                logger.warning("[AUTO_CARD] load pipeline tasks failed: %s", e)
    return None


def _find_key_from_files(files: list[dict]) -> str:
    """Try to infer KEY from file paths."""
    # Check improvements/{KEY}/ paths
    for f in files:
        parts = Path(f["path"]).parts
        for i, part in enumerate(parts):
            if part in ("improvements",):
                if i + 1 < len(parts):
                    return parts[i + 1]

    # Check .gcc/params/{SYMBOL}.yaml
    for f in files:
        p = Path(f["path"])
        if "params" in str(p) and p.suffix in (".yaml", ".yml"):
            return p.stem.upper()

    return ""


# ── Card generator ──

def generate_card(diff_summary: dict, task: dict | None = None) -> str | None:
    """
    Generate a knowledge card markdown from git diff + task context.
    Returns the card content or None if nothing worth recording.
    """
    files = diff_summary.get("files", [])
    if not files:
        return None

    # Classify changes
    code_files = [f for f in files if f["type"] == "code"]
    config_files = [f for f in files if f["type"] == "config"]
    doc_files = [f for f in files if f["type"] == "docs"]

    # Determine KEY
    key = ""
    if task:
        key = task.get("key", "")
    if not key:
        key = _find_key_from_files(files)

    # Build card
    lines = []

    # Title
    if task:
        title = task.get("title", task.get("description", "Code changes"))
        task_id = task.get("task_id", "")
        stage = task.get("stage", "")
        lines.append(f"# 📝 {title}")
        lines.append("")
        lines.append(f"- **Task:** {task_id}")
        lines.append(f"- **Stage:** {stage}")
    else:
        # No task context — describe from files
        if code_files:
            main_file = Path(code_files[0]["path"]).name
            lines.append(f"# 📝 Changes to {main_file}")
        else:
            lines.append(f"# 📝 Configuration update")
        lines.append("")

    lines.append(f"- **Date:** {_ts()}")
    if key:
        lines.append(f"- **KEY:** {key}")
    lines.append(f"- **Type:** auto-generated from git diff")
    lines.append(f"- **Files changed:** {len(files)}")

    # Code changes
    if code_files:
        lines.append("")
        lines.append("## Code Changes")
        for f in code_files[:10]:
            status_icon = {"M": "✏️", "A": "➕", "D": "🗑️", "??": "🆕"}.get(f["status"], "📄")
            short = "/".join(Path(f["path"]).parts[-2:]) if len(Path(f["path"]).parts) > 1 else f["path"]
            lines.append(f"- {status_icon} `{short}`")
        if len(code_files) > 10:
            lines.append(f"- ... and {len(code_files) - 10} more")

    # Config changes
    if config_files:
        lines.append("")
        lines.append("## Config Changes")
        for f in config_files[:5]:
            short = Path(f["path"]).name
            lines.append(f"- `{short}`")

    # Task context
    if task:
        desc = task.get("description", "")
        if desc:
            lines.append("")
            lines.append("## Context")
            lines.append(desc[:500])

    # Diff summary snippet (first meaningful file)
    try:
        if code_files:
            diff_out = subprocess.run(
                ["git", "diff", "HEAD", "--", code_files[0]["path"]],
                capture_output=True, text=True, timeout=5).stdout
            if not diff_out:
                diff_out = subprocess.run(
                    ["git", "diff", "--cached", "--", code_files[0]["path"]],
                    capture_output=True, text=True, timeout=5).stdout

            # Extract added/removed lines (not full diff)
            added = []
            removed = []
            for dl in diff_out.split("\n"):
                if dl.startswith("+") and not dl.startswith("+++"):
                    added.append(dl[1:].strip())
                elif dl.startswith("-") and not dl.startswith("---"):
                    removed.append(dl[1:].strip())

            if added or removed:
                lines.append("")
                lines.append("## Key Changes")
                if removed[:3]:
                    lines.append("**Removed:**")
                    for r in removed[:3]:
                        if r.strip():
                            lines.append(f"- ~~`{r[:80]}`~~")
                if added[:5]:
                    lines.append("**Added:**")
                    for a in added[:5]:
                        if a.strip():
                            lines.append(f"- `{a[:80]}`")
                if len(added) > 5:
                    lines.append(f"- ... +{len(added) - 5} more lines")
    except Exception as e:
        logger.warning("[AUTO_CARD] diff summary failed: %s", e)

    return "\n".join(lines)


# ── Save card ──

def save_card(card_content: str, key: str = "") -> Path | None:
    """
    Save a knowledge card to improvements/{KEY}/ directory.
    Returns the saved path or None.
    """
    if not card_content:
        return None

    # Find improvements dir (support both .gcc and .GCC)
    imp_dir = None
    for gcc_dir in [".gcc", ".GCC"]:
        candidate = Path(f"{gcc_dir}/improvements")
        if candidate.exists():
            imp_dir = candidate
            break

    if not imp_dir:
        # Create under whichever exists
        for gcc_dir in [".gcc", ".GCC"]:
            if Path(gcc_dir).exists():
                imp_dir = Path(f"{gcc_dir}/improvements")
                imp_dir.mkdir(parents=True, exist_ok=True)
                break

    if not imp_dir:
        return None

    # Determine target folder
    if key:
        target_dir = imp_dir / key
    else:
        target_dir = imp_dir / "_AUTO"

    target_dir.mkdir(parents=True, exist_ok=True)

    # Find next card number
    existing = sorted(target_dir.glob("card_*.md"))
    if existing:
        last_num = 0
        for e in existing:
            try:
                num = int(e.stem.split("_")[1])
                last_num = max(last_num, num)
            except (ValueError, IndexError):
                pass
        next_num = last_num + 1
    else:
        next_num = 1

    card_path = target_dir / f"card_{next_num:03d}.md"
    card_path.write_text(card_content, encoding="utf-8")

    return card_path


# ── Main entry point (called from selfcheck) ──

def auto_generate_card() -> Path | None:
    """
    Auto-generate a knowledge card from current dirty files.
    Called by selfcheck before auto-commit.
    Returns card path if generated, None otherwise.
    """
    diff = _get_diff_summary()

    # Skip if no meaningful changes
    if diff["meaningful"] < 1:
        return None

    # Find active task for context
    task = _find_active_task()

    # Determine KEY
    key = ""
    if task:
        key = task.get("key", "")
    if not key:
        key = _find_key_from_files(diff["files"])

    # Generate card
    content = generate_card(diff, task)
    if not content:
        return None

    # Save
    return save_card(content, key)
