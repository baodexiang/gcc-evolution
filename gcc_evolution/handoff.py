"""
GCC v4.5 — Handoff Protocol
Cross-LLM task handoff with zero-memory-burden design.

v4.5: Smart context — auto-detects branch/KEY, interactive pickup,
      no IDs to remember. Just `gcc-evo ho create` and `gcc-evo ho pickup`.

Usage:
    # Upstream agent commits, then:
    handoff = HandoffProtocol.from_git()   # auto-detects branch + KEY
    handoff.generate()

    # Downstream agent:
    handoff = HandoffProtocol.load_latest()  # or pick interactively
    tasks = handoff.pending_tasks()
"""

from __future__ import annotations

import json
import logging
import subprocess
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _short_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


# ── Enums ──────────────────────────────────────────────────

class HandoffStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class HandoffTaskType(str, Enum):
    DOC_UPDATE = "doc_update"        # README, CHANGELOG, etc.
    CONFIG_SYNC = "config_sync"      # YAML/JSON config updates
    TEST_UPDATE = "test_update"      # Test file updates
    CHANGELOG = "changelog"          # CHANGELOG.md entry
    COMMENT_UPDATE = "comment_update" # Code comment/docstring updates
    CUSTOM = "custom"


# ── Data Models ────────────────────────────────────────────

@dataclass
class HandoffTask:
    """A single task for the downstream agent."""
    task_id: str = ""
    task_type: HandoffTaskType = HandoffTaskType.CUSTOM
    target_file: str = ""
    description: str = ""
    context: str = ""           # What changed and why
    instructions: str = ""      # Specific instructions for the agent
    status: HandoffStatus = HandoffStatus.PENDING
    completed_at: str = ""
    agent: str = ""             # Which agent completed this

    # v4.5: Anchor to improvement item
    anchor_key: str = ""        # Linked KEY (e.g. "SPY-ATR")
    anchor_task_id: str = ""    # Linked pipeline task (e.g. "GCC-0001")
    anchor_note: str = ""       # Why this link, or "NEW: suggest creating KEY xxx"

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type.value,
            "target_file": self.target_file,
            "description": self.description,
            "context": self.context,
            "instructions": self.instructions,
            "status": self.status.value,
            "completed_at": self.completed_at,
            "agent": self.agent,
            "anchor_key": self.anchor_key,
            "anchor_task_id": self.anchor_task_id,
            "anchor_note": self.anchor_note,
        }

    @classmethod
    def from_dict(cls, d: dict) -> HandoffTask:
        return cls(
            task_id=d.get("task_id", ""),
            task_type=HandoffTaskType(d.get("task_type", "custom")),
            target_file=d.get("target_file", ""),
            description=d.get("description", ""),
            context=d.get("context", ""),
            instructions=d.get("instructions", ""),
            status=HandoffStatus(d.get("status", "pending")),
            completed_at=d.get("completed_at", ""),
            agent=d.get("agent", ""),
            anchor_key=d.get("anchor_key", ""),
            anchor_task_id=d.get("anchor_task_id", ""),
            anchor_note=d.get("anchor_note", ""),
        )


@dataclass
class HandoffManifest:
    """
    Complete handoff document — self-contained context for any downstream agent.
    Design principle: downstream agent needs ONLY this file, no project history.
    """
    handoff_id: str = ""
    created_at: str = field(default_factory=_now)
    source_agent: str = "claude-code"
    project: str = ""
    key: str = ""                # v4.5: associated KEY (auto-detected from branch)
    version: str = "5.050"

    # Git context
    commit_hash: str = ""
    commit_message: str = ""
    branch: str = ""
    files_changed: list[str] = field(default_factory=list)
    diff_summary: str = ""

    # What was done (by upstream agent)
    changes_summary: str = ""
    design_decisions: list[str] = field(default_factory=list)

    # What needs to be done (by downstream agent)
    tasks: list[HandoffTask] = field(default_factory=list)

    # Metrics
    upstream_tokens: int = 0
    upstream_cost: float = 0.0
    upstream_duration_sec: int = 0

    # Completion tracking
    completed_at: str = ""
    downstream_agent: str = ""
    downstream_tokens: int = 0
    downstream_cost: float = 0.0

    def to_dict(self) -> dict:
        return {
            "handoff_id": self.handoff_id,
            "created_at": self.created_at,
            "source_agent": self.source_agent,
            "project": self.project,
            "key": self.key,
            "version": self.version,
            "git": {
                "commit": self.commit_hash,
                "message": self.commit_message,
                "branch": self.branch,
                "files_changed": self.files_changed,
                "diff_summary": self.diff_summary,
            },
            "upstream": {
                "changes_summary": self.changes_summary,
                "design_decisions": self.design_decisions,
                "tokens": self.upstream_tokens,
                "cost": self.upstream_cost,
                "duration_sec": self.upstream_duration_sec,
            },
            "tasks": [t.to_dict() for t in self.tasks],
            "completion": {
                "completed_at": self.completed_at,
                "downstream_agent": self.downstream_agent,
                "downstream_tokens": self.downstream_tokens,
                "downstream_cost": self.downstream_cost,
            },
        }

    @classmethod
    def from_dict(cls, d: dict) -> HandoffManifest:
        git = d.get("git", {})
        up = d.get("upstream", {})
        comp = d.get("completion", {})
        m = cls(
            handoff_id=d.get("handoff_id", ""),
            created_at=d.get("created_at", ""),
            source_agent=d.get("source_agent", ""),
            project=d.get("project", ""),
            key=d.get("key", ""),
            version=d.get("version", "4.5"),
            commit_hash=git.get("commit", ""),
            commit_message=git.get("message", ""),
            branch=git.get("branch", ""),
            files_changed=git.get("files_changed", []),
            diff_summary=git.get("diff_summary", ""),
            changes_summary=up.get("changes_summary", ""),
            design_decisions=up.get("design_decisions", []),
            upstream_tokens=up.get("tokens", 0),
            upstream_cost=up.get("cost", 0.0),
            upstream_duration_sec=up.get("duration_sec", 0),
            completed_at=comp.get("completed_at", ""),
            downstream_agent=comp.get("downstream_agent", ""),
            downstream_tokens=comp.get("downstream_tokens", 0),
            downstream_cost=comp.get("downstream_cost", 0.0),
        )
        m.tasks = [HandoffTask.from_dict(t) for t in d.get("tasks", [])]
        return m

    def pending_tasks(self) -> list[HandoffTask]:
        return [t for t in self.tasks if t.status == HandoffStatus.PENDING]

    def complete_task(self, task_id: str, agent: str = "") -> bool:
        for t in self.tasks:
            if t.task_id == task_id:
                t.status = HandoffStatus.COMPLETED
                t.completed_at = _now()
                t.agent = agent
                return True
        return False

    def fail_task(self, task_id: str, agent: str = "") -> bool:
        for t in self.tasks:
            if t.task_id == task_id:
                t.status = HandoffStatus.FAILED
                t.completed_at = _now()
                t.agent = agent
                return True
        return False

    def is_complete(self) -> bool:
        return all(
            t.status in (HandoffStatus.COMPLETED, HandoffStatus.SKIPPED)
            for t in self.tasks
        )

    def completion_rate(self) -> float:
        if not self.tasks:
            return 1.0
        done = sum(
            1 for t in self.tasks
            if t.status in (HandoffStatus.COMPLETED, HandoffStatus.SKIPPED)
        )
        return done / len(self.tasks)

    def to_markdown(self) -> str:
        """
        v4.5: Generate clean, single-page handoff markdown.
        Format from Codex audit: 当前状态 / 今日变更 / 未完成边界 / 下一步3条
        Replaces the old bloated handoff.md.
        """
        key_label = f" [{self.key}]" if self.key else ""
        lines = [
            f"# Handoff: {self.handoff_id}{key_label}",
            "",
            f"> Generated by `gcc-evo ho create` | {self.created_at[:19]}",
            f"> From: {self.source_agent} | Branch: {self.branch} | Commit: {self.commit_hash}",
            "",
        ]

        # ── 1. Current State ──
        lines.append("## Current State")
        lines.append("")
        lines.append(self.changes_summary or "(no summary)")
        lines.append("")

        if self.design_decisions:
            lines.append("**Decisions:**")
            for d in self.design_decisions:
                lines.append(f"- {d}")
            lines.append("")

        # ── 2. Files Changed ──
        if self.files_changed:
            lines.append("## Files Changed")
            lines.append("")
            for f in self.files_changed:
                lines.append(f"- `{f}`")
            lines.append("")

        # ── 3. Unfinished Boundary ──
        pending = self.pending_tasks()
        completed = [t for t in self.tasks
                     if t.status in (HandoffStatus.COMPLETED, HandoffStatus.SKIPPED)]

        if completed:
            lines.append("## Done")
            lines.append("")
            for t in completed:
                lines.append(f"- ✅ `{t.target_file}` — {t.description}")
            lines.append("")

        if pending:
            lines.append("## Pending (for downstream agent)")
            lines.append("")
            for t in pending:
                lines.append(f"- ⏳ **{t.target_file}** — {t.description}")
                if t.instructions:
                    lines.append(f"  - {t.instructions}")
            lines.append("")

        # ── 4. Next Steps (max 3) ──
        lines.append("## Next Steps")
        lines.append("")
        if pending:
            for i, t in enumerate(pending[:3], 1):
                lines.append(f"{i}. {t.description}")
        else:
            lines.append("All tasks completed.")
        lines.append("")

        return "\n".join(lines)


# ── Protocol Implementation ────────────────────────────────

class HandoffProtocol:
    """
    Cross-LLM handoff protocol — v4.5 zero-memory-burden design.

    User only needs two commands:
        gcc-evo ho create    # auto-detects everything
        gcc-evo ho pickup    # interactive selection if multiple

    Everything else (branch → KEY mapping, task detection, ID generation)
    is automatic.
    """

    HANDOFF_DIR = ".gcc/handoffs"

    def __init__(self, project: str = "", source_agent: str = "claude-code",
                 key: str = ""):
        self._key = key
        self.manifest = HandoffManifest(
            handoff_id="",  # generated after branch detection
            project=project,
            key=key,
            source_agent=source_agent,
        )
        self._task_counter = 0

    # ── Smart Context Detection (v4.5) ─────────────────────

    def auto_detect_context(self) -> None:
        """
        Auto-detect everything from git state:
        1. Current branch → KEY
        2. Latest commit → changes summary
        3. Files changed → downstream tasks
        No user input needed.
        """
        self.capture_git_state()

        # Auto-detect KEY from branch name
        if not self._key:
            self._key = self._branch_to_key(self.manifest.branch)
        self.manifest.key = self._key

        # Generate human-readable handoff ID
        self.manifest.handoff_id = self._make_id()

        # Auto-detect changes summary from commit message
        if not self.manifest.changes_summary and self.manifest.commit_message:
            self.manifest.changes_summary = self.manifest.commit_message

        # Auto-detect downstream tasks
        self.auto_detect_tasks()

    @staticmethod
    def _branch_to_key(branch: str) -> str:
        """
        Extract KEY from branch name.
        feature/spy-atr       → SPY-ATR
        fix/n-structure       → N-STRUCTURE
        dev/chan-divergence    → CHAN-DIVERGENCE
        main                  → MAIN
        """
        if not branch:
            return ""
        # Strip common prefixes
        for prefix in ("feature/", "fix/", "dev/", "hotfix/", "release/"):
            if branch.startswith(prefix):
                branch = branch[len(prefix):]
                break
        # Convert to KEY format
        return branch.upper().replace("/", "-").replace("_", "-")

    def _make_id(self) -> str:
        """Generate readable ID: HO_{KEY}_{date} or HO_{date}"""
        ts = _short_ts()[:8]  # YYYYMMDD only
        if self._key:
            return f"HO_{self._key}_{ts}"
        return f"HO_{ts}"

    # ── Git Integration ────────────────────────────────────

    def capture_git_state(self, commit: str = "HEAD") -> None:
        """Capture current git state for the handoff."""
        try:
            self.manifest.commit_hash = self._git(
                "rev-parse", "--short", commit).strip()
            self.manifest.commit_message = self._git(
                "log", "-1", "--format=%s", commit).strip()
            self.manifest.branch = self._git(
                "rev-parse", "--abbrev-ref", "HEAD").strip()

            # Files changed in last commit
            diff_output = self._git(
                "diff", "--name-only", f"{commit}~1", commit)
            self.manifest.files_changed = [
                f.strip() for f in diff_output.strip().split("\n") if f.strip()
            ]

            # Diff stat summary
            self.manifest.diff_summary = self._git(
                "diff", "--stat", f"{commit}~1", commit).strip()

        except Exception as e:
            # Not in a git repo or git not available — still usable
            logger.warning("[HANDOFF] git context failed: %s", e)

    @staticmethod
    def _git(*args) -> str:
        result = subprocess.run(
            ["git"] + list(args),
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr)
        return result.stdout

    # ── Task Builders ──────────────────────────────────────

    def _next_task_id(self) -> str:
        self._task_counter += 1
        return f"T{self._task_counter:03d}"

    def set_changes_summary(self, summary: str) -> None:
        self.manifest.changes_summary = summary

    def add_decision(self, decision: str) -> None:
        self.manifest.design_decisions.append(decision)

    def add_task(
        self,
        task_type: HandoffTaskType,
        target_file: str,
        description: str,
        context: str = "",
        instructions: str = "",
    ) -> HandoffTask:
        task = HandoffTask(
            task_id=self._next_task_id(),
            task_type=task_type,
            target_file=target_file,
            description=description,
            context=context,
            instructions=instructions,
        )
        self.manifest.tasks.append(task)
        return task

    def add_doc_task(self, target: str, description: str,
                     context: str = "", instructions: str = "") -> HandoffTask:
        return self.add_task(
            HandoffTaskType.DOC_UPDATE, target, description, context, instructions)

    def add_config_task(self, target: str, description: str,
                        context: str = "", instructions: str = "") -> HandoffTask:
        return self.add_task(
            HandoffTaskType.CONFIG_SYNC, target, description, context, instructions)

    def add_test_task(self, target: str, description: str,
                      context: str = "", instructions: str = "") -> HandoffTask:
        return self.add_task(
            HandoffTaskType.TEST_UPDATE, target, description, context, instructions)

    def add_changelog_task(self, description: str, context: str = "",
                           instructions: str = "") -> HandoffTask:
        return self.add_task(
            HandoffTaskType.CHANGELOG, "CHANGELOG.md", description, context, instructions)

    def set_metrics(self, tokens: int = 0, cost: float = 0.0,
                    duration_sec: int = 0) -> None:
        self.manifest.upstream_tokens = tokens
        self.manifest.upstream_cost = cost
        self.manifest.upstream_duration_sec = duration_sec

    # ── Auto-detect Tasks ──────────────────────────────────

    def auto_detect_tasks(self) -> list[HandoffTask]:
        """
        Analyze git diff to auto-generate downstream tasks.
        This is the key automation — upstream agent just commits,
        and handoff protocol figures out what docs/configs need updating.
        """
        tasks_added = []
        changed = set(self.manifest.files_changed)

        if not changed:
            return tasks_added

        # Detect source code changes that need doc updates
        code_files = [f for f in changed if f.endswith(('.py', '.ts', '.js'))]
        doc_files = [f for f in changed if f.endswith(('.md', '.rst', '.txt'))]
        config_files = [f for f in changed if f.endswith(('.yaml', '.yml', '.json', '.toml'))]
        test_files = [f for f in changed if 'test' in f.lower()]

        # Rule 1: If source changed but README didn't, probably needs update
        if code_files and 'README.md' not in changed:
            t = self.add_doc_task(
                "README.md",
                f"Update README to reflect changes in: {', '.join(code_files[:5])}",
                context=self.manifest.changes_summary,
                instructions="Update relevant sections. Add new features if applicable.",
            )
            tasks_added.append(t)

        # Rule 2: If source changed but CHANGELOG didn't, add entry
        if code_files and 'CHANGELOG.md' not in changed:
            t = self.add_changelog_task(
                f"Add changelog entry for: {self.manifest.commit_message}",
                context=self.manifest.changes_summary,
            )
            tasks_added.append(t)

        # Rule 3: If __init__.py or models changed, check for docstring updates
        init_changes = [f for f in code_files if '__init__' in f or 'models' in f]
        if init_changes:
            for f in init_changes:
                t = self.add_doc_task(
                    f,
                    f"Update module docstrings and version references in {f}",
                    context=self.manifest.changes_summary,
                    instructions="Ensure docstrings match new functionality. Update version if needed.",
                )
                tasks_added.append(t)

        # Rule 4: If config structure changed, sync documentation
        if config_files:
            for f in config_files:
                t = self.add_config_task(
                    f,
                    f"Verify config file {f} is consistent with code changes",
                    context=self.manifest.changes_summary,
                )
                tasks_added.append(t)

        # Rule 5: If source changed but tests didn't, flag for test update
        non_test_code = [f for f in code_files if 'test' not in f.lower()]
        if non_test_code and not test_files:
            t = self.add_test_task(
                "tests/",
                f"Add/update tests for: {', '.join(non_test_code[:5])}",
                context=self.manifest.changes_summary,
                instructions="Add tests for new functions/methods. Update existing tests if APIs changed.",
            )
            tasks_added.append(t)

        return tasks_added

    # ── Persistence ────────────────────────────────────────

    def save(self, path: str | Path | None = None) -> Path:
        """
        Save handoff:
        1. JSON manifest → .gcc/handoffs/{ID}.json (structured, for machines)
        2. Markdown → .gcc/branches/{branch}/handoff.md (clean, for agents)
        """
        handoff_dir = Path(self.HANDOFF_DIR)
        handoff_dir.mkdir(parents=True, exist_ok=True)

        if path is None:
            path = handoff_dir / f"{self.manifest.handoff_id}.json"
        else:
            path = Path(path)

        # Save JSON
        path.write_text(
            json.dumps(self.manifest.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        # v4.5: Also write clean markdown to branch directory
        self._write_branch_handoff()

        return path

    def _write_branch_handoff(self) -> Path | None:
        """
        Write a clean, single-page handoff.md into .gcc/branches/{branch}/.
        This replaces the old bloated handoff files.
        """
        branch = self.manifest.branch
        if not branch:
            return None

        # Normalize branch name for directory
        branch_dir_name = branch.replace("/", "-")
        branch_dir = Path(f".gcc/branches/{branch_dir_name}")
        branch_dir.mkdir(parents=True, exist_ok=True)

        md_path = branch_dir / "handoff.md"
        md_path.write_text(self.manifest.to_markdown(), encoding="utf-8")
        return md_path

    @classmethod
    def load(cls, path: str | Path) -> HandoffProtocol:
        """Load handoff from a specific file."""
        data = json.loads(Path(path).read_text("utf-8"))
        hp = cls.__new__(cls)
        hp.manifest = HandoffManifest.from_dict(data)
        hp._task_counter = len(hp.manifest.tasks)
        return hp

    @classmethod
    def load_latest(cls, status: str = "pending",
                    key: str = "") -> HandoffProtocol | None:
        """Load the most recent handoff, optionally filtered by KEY."""
        handoff_dir = Path(cls.HANDOFF_DIR)
        if not handoff_dir.exists():
            return None

        files = sorted(handoff_dir.glob("HO_*.json"), reverse=True)
        for f in files:
            try:
                hp = cls.load(f)
                # Key filter
                if key and hp.manifest.key.upper() != key.upper():
                    continue
                if status == "any":
                    return hp
                if status == "pending" and hp.manifest.pending_tasks():
                    return hp
                if status == "completed" and hp.manifest.is_complete():
                    return hp
            except Exception as e:
                logger.warning("[HANDOFF] load handoff %s failed: %s", f.name, e)
                continue
        return None

    @classmethod
    def load_all_pending(cls) -> list[HandoffProtocol]:
        """Load all handoffs with pending tasks (for interactive pickup)."""
        handoff_dir = Path(cls.HANDOFF_DIR)
        if not handoff_dir.exists():
            return []
        results = []
        files = sorted(handoff_dir.glob("HO_*.json"), reverse=True)
        for f in files:
            try:
                hp = cls.load(f)
                if hp.manifest.pending_tasks():
                    results.append(hp)
            except Exception as e:
                logger.warning("[HANDOFF] load pending handoff %s failed: %s", f.name, e)
                continue
        return results

    @classmethod
    def list_all(cls) -> list[dict]:
        """List all handoffs with summary info."""
        handoff_dir = Path(cls.HANDOFF_DIR)
        if not handoff_dir.exists():
            return []

        results = []
        for f in sorted(handoff_dir.glob("HO_*.json"), reverse=True):
            try:
                data = json.loads(f.read_text("utf-8"))
                m = HandoffManifest.from_dict(data)
                total = len(m.tasks)
                done = sum(1 for t in m.tasks
                          if t.status in (HandoffStatus.COMPLETED, HandoffStatus.SKIPPED))
                results.append({
                    "id": m.handoff_id,
                    "key": m.key,
                    "created": m.created_at,
                    "source": m.source_agent,
                    "commit": m.commit_hash,
                    "summary": m.changes_summary[:60],
                    "tasks": f"{done}/{total}",
                    "complete": m.is_complete(),
                    "file": str(f),
                })
            except Exception as e:
                logger.warning("[HANDOFF] list handoff %s failed: %s", f.name, e)
                continue
        return results

    # ── Context String (for agent injection) ───────────────

    def to_context_string(self) -> str:
        """
        v4.5: Clean context string for downstream agent injection.
        Format: Current State / Files / Pending Tasks / Next 3 Steps
        No history, no self-corrections, no dangerous commands.
        """
        m = self.manifest
        key_label = f" [{m.key}]" if m.key else ""
        lines = [
            f"═══ HANDOFF: {m.handoff_id}{key_label} ═══",
            "",
            f"## Current State",
            f"Branch: {m.branch} | Commit: {m.commit_hash}",
            f"{m.changes_summary}",
        ]

        if m.design_decisions:
            lines.append("")
            lines.append("Decisions:")
            for d in m.design_decisions:
                lines.append(f"  • {d}")

        if m.files_changed:
            lines.append("")
            lines.append(f"## Files Changed ({len(m.files_changed)})")
            for f in m.files_changed[:10]:
                lines.append(f"  {f}")

        pending = m.pending_tasks()
        if pending:
            lines.append("")
            lines.append(f"## Your Tasks ({len(pending)})")
            for t in pending:
                lines.append(f"  [{t.task_id}] {t.target_file}: {t.description}")
                if t.instructions:
                    lines.append(f"    → {t.instructions}")
            lines.append("")
            lines.append("## Next Steps")
            for i, t in enumerate(pending[:3], 1):
                lines.append(f"  {i}. {t.description}")
        else:
            lines.append("")
            lines.append("All tasks completed.")

        lines.append("")
        lines.append("═══ END HANDOFF ═══")
        return "\n".join(lines)

    def to_slim_markdown(self) -> str:
        """
        v4.5: Per-KEY handoff markdown — replaces monolithic handoff.md.
        Codex audit format: 当前状态 / 今日变更 / 未完成边界 / 下一步3条
        Always <1 page. Zero ambiguity. No history, no self-corrections.
        """
        m = self.manifest
        key_label = f" [{m.key}]" if m.key else ""
        # Extract pipeline task ID from decisions if present
        pipe_label = ""
        for d in m.design_decisions:
            if d.startswith("Pipeline:"):
                pipe_label = f" → {d.split(':')[1].strip().split(' ')[0]}"
                break
        lines = [
            f"# Handoff: {m.handoff_id}{key_label}{pipe_label}",
            "",
            "## 当前状态",
            f"- Branch: `{m.branch}`",
            f"- Commit: `{m.commit_hash}`",
            f"- Agent: {m.source_agent}",
            "",
            "## 今日变更",
            m.changes_summary,
        ]

        if m.files_changed:
            lines.append("")
            lines.append("Files:")
            for f in m.files_changed[:15]:
                lines.append(f"- `{f}`")

        if m.design_decisions:
            lines.append("")
            lines.append("Decisions:")
            for d in m.design_decisions:
                lines.append(f"- {d}")

        # Done
        done = [t for t in m.tasks
                if t.status in (HandoffStatus.COMPLETED, HandoffStatus.SKIPPED)]
        if done:
            lines.append("")
            lines.append(f"## 已完成 ({len(done)})")
            for t in done:
                lines.append(f"- ✅ {t.description}")

        # Pending = boundary
        pending = m.pending_tasks()
        if pending:
            lines.append("")
            lines.append(f"## 未完成边界 ({len(pending)})")
            for t in pending:
                lines.append(f"- ⏳ [{t.task_id}] {t.target_file}: {t.description}")

        # Next 3 max
        lines.append("")
        lines.append("## 下一步")
        if pending:
            for i, t in enumerate(pending[:3], 1):
                lines.append(f"{i}. {t.description}")
                if t.instructions:
                    lines.append(f"   → {t.instructions}")
        else:
            lines.append("All done. Ready for merge.")

        return "\n".join(lines)

    def save_slim_markdown(self, output_dir: str = ".gcc/branches") -> Path | None:
        """
        v4.5: Save per-KEY slim handoff markdown.
        Overwrites previous — always reflects current state only.
        Also writes to .gcc/handoff_{KEY}.md for flat access.
        """
        m = self.manifest
        if not m.key:
            return None

        # 1. Write to branch dir (for gcc-evo show to pick up)
        key_slug = m.key.lower().replace("-", "_")
        branch_dir = Path(output_dir) / key_slug
        branch_dir.mkdir(parents=True, exist_ok=True)
        branch_path = branch_dir / "handoff.md"
        content = self.to_slim_markdown()
        branch_path.write_text(content, encoding="utf-8")

        # 2. Also write flat file for easy access
        flat_path = Path(".gcc") / f"handoff_{key_slug}.md"
        flat_path.write_text(content, encoding="utf-8")

        return branch_path
