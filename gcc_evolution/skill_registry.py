"""
GCC v5.050 — Skill Registry
Inspired by FactorMiner: Modular Skill Architecture.

Wraps GCC capabilities as callable skills with tool-use compatible interface.
Agent calls skill by name, zero internal knowledge needed.
"""

from __future__ import annotations

import json
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SkillResult:
    """Standard return from any skill call."""
    skill_name: str
    success: bool
    data: Any = None
    error: str = ""
    duration_ms: int = 0
    called_at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        return {
            "skill": self.skill_name, "success": self.success,
            "data": self.data, "error": self.error,
            "duration_ms": self.duration_ms, "called_at": self.called_at,
        }


@dataclass
class SkillDef:
    """Skill definition in registry."""
    name: str
    description: str
    input_schema: dict = field(default_factory=dict)
    output_type: str = "dict"
    handler: Callable | None = None


class SkillRegistry:
    """
    Central registry of GCC skills.
    Each skill wraps an existing GCC capability as a callable tool.
    """

    def __init__(self, distiller=None):
        self._skills: dict[str, SkillDef] = {}
        self._call_log: list[dict] = []
        self._failure_cards: list[dict] = []  # v5.010 P0-SkillRL-1: s⁻蒸馏缓存
        self._distiller = distiller
        self._register_builtins()

    def _register_builtins(self):
        """Register all built-in GCC skills."""

        # -- Params skills --
        self.register(SkillDef(
            name="params_gate_check",
            description="Run gate check for a product. Returns pass/fail with 7 metrics.",
            input_schema={"product_id": "str", "previous_backtest": "dict? (optional)"},
            output_type="ParamGateResult",
            handler=self._h_params_gate,
        ))

        self.register(SkillDef(
            name="params_show",
            description="Show all parameters for a product.",
            input_schema={"product_id": "str"},
            output_type="dict (full params YAML)",
            handler=self._h_params_show,
        ))

        self.register(SkillDef(
            name="params_update_backtest",
            description="Update backtest results for a product after optimization.",
            input_schema={"product_id": "str", "results": "dict {sharpe, max_dd_pct, win_rate, ...}"},
            output_type="Path",
            handler=self._h_params_update_bt,
        ))

        # -- Constraint skills --
        self.register(SkillDef(
            name="get_constraints",
            description="Get active DO NOT constraints for a KEY. Used to prune search space.",
            input_schema={"key": "str? (optional KEY filter)"},
            output_type="str (formatted constraints for LLM context)",
            handler=self._h_get_constraints,
        ))

        self.register(SkillDef(
            name="add_constraint",
            description="Add a new DO NOT constraint from failure observation.",
            input_schema={"rule": "str", "context": "str?", "key": "str?", "confidence": "float?"},
            output_type="Constraint",
            handler=self._h_add_constraint,
        ))

        # -- Pipeline skills --
        self.register(SkillDef(
            name="pipeline_status",
            description="Get current pipeline dashboard: all tasks with stages and status.",
            input_schema={},
            output_type="dict {tasks: [...], summary: {...}}",
            handler=self._h_pipeline_status,
        ))

        self.register(SkillDef(
            name="pipeline_advance",
            description="Advance a pipeline task to next stage.",
            input_schema={"task_id": "str"},
            output_type="dict {task_id, old_stage, new_stage}",
            handler=self._h_pipeline_advance,
        ))

        # -- Handoff skills --
        self.register(SkillDef(
            name="handoff_create",
            description="Create a handoff anchored to an improvement KEY.",
            input_schema={"description": "str", "key": "str? (auto-detect if empty)"},
            output_type="dict {handoff_id, key, file}",
            handler=self._h_handoff_create,
        ))

        self.register(SkillDef(
            name="handoff_pickup",
            description="Pick up the latest pending handoff for a KEY.",
            input_schema={"key": "str? (optional KEY filter)"},
            output_type="dict {handoff_id, tasks, context}",
            handler=self._h_handoff_pickup,
        ))

        # -- Self-check skill --
        self.register(SkillDef(
            name="self_check",
            description="Run GCC self-check: verify all modules, files, and config integrity.",
            input_schema={},
            output_type="dict {status, checks: [...], issues: [...]}",
            handler=self._h_self_check,
        ))

    def register(self, skill: SkillDef):
        self._skills[skill.name] = skill

    def list_skills(self) -> list[dict]:
        """List all available skills with descriptions."""
        return [
            {"name": s.name, "description": s.description,
             "input": s.input_schema, "output": s.output_type}
            for s in self._skills.values()
        ]

    def call(self, name: str, **kwargs) -> SkillResult:
        """Call a skill by name with keyword arguments."""
        import time
        start = time.time()

        if name not in self._skills:
            return SkillResult(skill_name=name, success=False,
                             error=f"Unknown skill: {name}")

        skill = self._skills[name]
        if not skill.handler:
            return SkillResult(skill_name=name, success=False,
                             error=f"Skill {name} has no handler")

        try:
            data = skill.handler(**kwargs)
            duration = int((time.time() - start) * 1000)
            result = SkillResult(skill_name=name, success=True,
                               data=data, duration_ms=duration)
        except Exception as e:
            duration = int((time.time() - start) * 1000)
            result = SkillResult(skill_name=name, success=False,
                               error=f"{type(e).__name__}: {e}",
                               duration_ms=duration)
            # v5.010 P0-SkillRL-1: 失败Skill独立蒸馏(s⁻类型)
            self._distill_failure(name, kwargs, e)

        self._call_log.append(result.to_dict())
        return result

    def call_log(self) -> list[dict]:
        return list(self._call_log)

    def _distill_failure(self, skill_name: str, kwargs: dict, error: Exception):
        """v5.010 P0-SkillRL-1: Failed Skill independent distillation -- generate s- experience card"""
        card_dict = {
            "skill": skill_name,
            "args": {k: str(v)[:100] for k, v in kwargs.items()},
            "error_type": type(error).__name__,
            "error_msg": str(error)[:200],
            "timestamp": _now(),
        }
        self._failure_cards.append(card_dict)

    def get_failure_cards(self) -> list[dict]:
        """Return failure distillation records (for Distiller to consume)"""
        return list(self._failure_cards)

    def clear_failure_cards(self):
        self._failure_cards.clear()

    # === Handlers ===

    @staticmethod
    def _h_params_gate(product_id: str, previous_backtest: dict | None = None):
        from .params import ParamGate
        result = ParamGate.check(product_id, previous_backtest)
        return result.to_dict()

    @staticmethod
    def _h_params_show(product_id: str):
        from .params import ParamStore
        return ParamStore.load(product_id)

    @staticmethod
    def _h_params_update_bt(product_id: str, results: dict):
        from .params import ParamStore
        path = ParamStore.update_backtest(product_id, results)
        return str(path)

    @staticmethod
    def _h_get_constraints(key: str = ""):
        from .constraints import ConstraintStore
        store = ConstraintStore()
        return store.format_for_injection(key)

    @staticmethod
    def _h_add_constraint(rule: str, context: str = "", key: str = "",
                          confidence: float = 0.5):
        from .constraints import Constraint, ConstraintStore
        store = ConstraintStore()
        c = Constraint(rule=rule, context=context, key=key, confidence=confidence)
        added = store.add(c)
        return added.to_dict()

    @staticmethod
    def _h_pipeline_status():
        from .pipeline import TaskPipeline
        pipe = TaskPipeline()
        tasks = []
        for t in pipe.tasks.values():
            tasks.append({
                "id": t.task_id, "title": t.title,
                "key": t.key, "stage": t.stage.value,
                "priority": t.priority, "progress": f"{t.iterations}/{t.max_iterations}",
            })
        summary = pipe.dashboard_summary() if hasattr(pipe, 'dashboard_summary') else {}
        return {"tasks": tasks, "summary": summary}

    @staticmethod
    def _h_pipeline_advance(task_id: str):
        from .pipeline import TaskPipeline
        pipe = TaskPipeline()
        if task_id not in pipe.tasks:
            raise ValueError(f"Task {task_id} not found")
        task = pipe.tasks[task_id]
        old = task.stage.value
        pipe.advance_task(task_id)
        return {"task_id": task_id, "old_stage": old, "new_stage": task.stage.value}

    @staticmethod
    def _h_handoff_create(description: str, key: str = ""):
        from .handoff import HandoffProtocol
        from .config import load_config
        config = load_config()
        hp = HandoffProtocol(project=config.project_name, key=key)
        hp.auto_detect_context()
        hp.set_changes_summary(description)
        if key:
            hp.manifest.key = key
            hp.manifest.handoff_id = hp._make_id()
        path = hp.save()
        md = hp.save_slim_markdown()
        return {
            "handoff_id": hp.manifest.handoff_id,
            "key": hp.manifest.key,
            "file": str(md) if md else str(path),
        }

    @staticmethod
    def _h_handoff_pickup(key: str = ""):
        from .handoff import HandoffProtocol
        from .config import load_config
        config = load_config()
        hp = HandoffProtocol(project=config.project_name, key=key)
        pending = hp.load_all_pending()
        if not pending:
            return {"handoff_id": None, "tasks": [], "context": "No pending handoffs"}
        # Pick most recent
        latest = pending[-1]
        return {
            "handoff_id": latest.handoff_id,
            "key": latest.key,
            "tasks": [{"id": t.task_id, "desc": t.description, "status": t.status}
                     for t in latest.tasks],
            "context": latest.changes_summary,
        }

    @staticmethod
    def _h_self_check():
        """Run comprehensive GCC health check."""
        checks = []
        issues = []

        # 1. Config
        try:
            from .config import load_config
            config = load_config()
            checks.append({"name": "config", "status": "ok",
                          "detail": f"project={config.project_name} v={config.version}"})
        except Exception as e:
            checks.append({"name": "config", "status": "fail", "detail": str(e)})
            issues.append(f"Config: {e}")

        # 2. Experience DB
        try:
            from .experience_store import GlobalMemory
            gm = GlobalMemory()
            count = gm.count()
            checks.append({"name": "experience_db", "status": "ok",
                          "detail": f"{count} cards"})
        except Exception as e:
            checks.append({"name": "experience_db", "status": "fail", "detail": str(e)})
            issues.append(f"Experience DB: {e}")

        # 3. Pipeline
        try:
            from .pipeline import TaskPipeline
            pipe = TaskPipeline()
            tc = len(pipe.tasks)
            checks.append({"name": "pipeline", "status": "ok",
                          "detail": f"{tc} tasks"})
        except Exception as e:
            checks.append({"name": "pipeline", "status": "warn", "detail": str(e)})

        # 4. Keys
        keys_path = Path(".gcc/keys.yaml")
        if keys_path.exists():
            try:
                import yaml
                keys = yaml.safe_load(keys_path.read_text("utf-8")) or {}
                checks.append({"name": "keys", "status": "ok",
                              "detail": f"{len(keys)} KEYs"})
            except Exception as e:
                checks.append({"name": "keys", "status": "warn", "detail": str(e)})
        else:
            checks.append({"name": "keys", "status": "skip", "detail": "no keys.yaml"})

        # 5. Params
        try:
            from .params import ParamStore
            products = ParamStore.list_products()
            checks.append({"name": "params", "status": "ok",
                          "detail": f"{len(products)} products"})
        except Exception as e:
            checks.append({"name": "params", "status": "warn", "detail": str(e)})

        # 6. Constraints
        try:
            from .constraints import ConstraintStore
            cs = ConstraintStore()
            stats = cs.stats()
            checks.append({"name": "constraints", "status": "ok",
                          "detail": f"{stats['active']} active / {stats['total']} total"})
        except Exception as e:
            checks.append({"name": "constraints", "status": "warn", "detail": str(e)})

        # 7. Handoffs
        handoff_dir = Path(".gcc/handoffs")
        if handoff_dir.exists():
            ho_count = len(list(handoff_dir.glob("HO_*.json")))
            checks.append({"name": "handoffs", "status": "ok",
                          "detail": f"{ho_count} handoffs"})
        else:
            checks.append({"name": "handoffs", "status": "skip",
                          "detail": "no handoffs dir"})

        # 8. Git
        import subprocess
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True, text=True, timeout=5)
            dirty = len(result.stdout.strip().split("\n")) if result.stdout.strip() else 0
            branch = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True, timeout=5).stdout.strip()
            checks.append({"name": "git", "status": "ok",
                          "detail": f"branch={branch} dirty={dirty}"})
            if dirty > 0:
                issues.append(f"Git: {dirty} dirty files")
        except Exception:
            checks.append({"name": "git", "status": "skip", "detail": "not a git repo"})

        # 9. Directory structure
        expected_dirs = [".gcc", ".gcc/experiences", ".gcc/params",
                        ".gcc/pipeline", ".gcc/handoffs", ".gcc/verification"]
        missing = [d for d in expected_dirs if not Path(d).exists()]
        if missing:
            checks.append({"name": "directories", "status": "warn",
                          "detail": f"missing: {', '.join(missing)}"})
            issues.append(f"Missing dirs: {', '.join(missing)}")
        else:
            checks.append({"name": "directories", "status": "ok",
                          "detail": "all present"})

        overall = "healthy" if not issues else "issues"
        return {"status": overall, "checks": checks, "issues": issues}


# ==============================================================
# v4.90 — SkillBank(借鉴 SkillRL，论文 #16，arxiv:2602.08234)
#
# SkillRL core idea:
#   Raw trajectories -> noisy, hard to generalize
#   -> Auto-distill into reusable Skills
#   -> General Skills (cross-task universal) + Task-Specific Skills (product-specific)
#   -> Recursive evolution: new experience auto-updates old Skills
#
# GCC implementation:
#   General Skills  = knowledge cards (cards table, cross-product universal rules)
#   Task-Specific   = product yaml (each product unique params and strategies)
#   Distillation    = retrospective -> suggest -> human review -> update
#   Recursive evo   = after each db sync, new data influences next opinion
# ==============================================================

from dataclasses import dataclass as _dc
from typing import Literal as _Lit


@_dc
class SkillEntry:
    """A skill entry in SkillBank"""
    skill_id:    str
    name:        str
    skill_type:  _Lit["general", "task_specific"]  # General or Task-Specific
    product_id:  str                  # task_specific: has value; general: empty
    key_id:      str                  # Associated improvement KEY
    content:     str                  # Skill description/rule
    source:      str                  # card/suggest/retrospective/human
    confidence:  float = 0.8          # Confidence, increases after validation
    use_count:   int   = 0            # Reference count
    success_rate: float = 0.0         # Application success rate
    created_at:  str   = ""
    updated_at:  str   = ""
    version:     int   = 1            # Recursive evolution version number
    embedding:   list  = None         # v5.010 P1-SkillRL-1: 懒加载embedding向量
    when_to_apply: str = ""          # v5.010 P2-SkillRL-1: 适用场景描述(与content分离)

    def __post_init__(self):
        if self.embedding is None:
            self.embedding = []


class SkillBank:
    """
    Skill bank，实现 SkillRL 的 General + Task-Specific 分层。
    Persistence到 .gcc/skillbank.jsonl。

    Retrieval策略(借鉴 SkillRL AdaptiveRetrieval)：
      - 通用任务 → 优先Retrieval General Skills
      - 特定品种 → General + Task-Specific 合并，Task-Specific Weight更高
      - confidence * success_rate determines ranking
    """

    def __init__(self, gcc_dir="./gcc"):
        import json
        from pathlib import Path
        from datetime import datetime, timezone

        self._gcc_dir = Path(gcc_dir)
        self._gcc_dir.mkdir(exist_ok=True)
        self._file = self._gcc_dir / "skillbank.jsonl"
        self._skills: dict[str, SkillEntry] = {}
        self._load()

    # -- Write ----------------------------------------------

    def add(self, entry: SkillEntry) -> SkillEntry:
        """Add or update skill"""
        import json
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        if not entry.created_at:
            entry.created_at = now
        entry.updated_at = now

        existing = self._skills.get(entry.skill_id)
        if existing:
            # Recursive evolution: version incremented, statistics preserved
            entry.version      = existing.version + 1
            entry.use_count    = existing.use_count
            entry.success_rate = existing.success_rate

        self._skills[entry.skill_id] = entry
        self._save()
        return entry

    def record_usage(self, skill_id: str, success: bool):
        """Record skill usage result, update success rate (data foundation for recursive evolution)"""
        entry = self._skills.get(skill_id)
        if not entry:
            return
        total = entry.use_count + 1
        entry.success_rate = (entry.success_rate * entry.use_count + (1.0 if success else 0.0)) / total
        entry.use_count    = total
        entry.updated_at   = __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()
        self._save()

    # -- Retrieval(Adaptive，借鉴 SkillRL)-------------------------

    @staticmethod
    def _cosine_sim(a: list[float], b: list[float]) -> float:
        """Vector cosine similarity"""
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = sum(x * x for x in a) ** 0.5
        nb = sum(x * x for x in b) ** 0.5
        return dot / (na * nb) if na > 0 and nb > 0 else 0.0

    def retrieve(self, query: str = "", product_id: str = "",
                 top_k: int = 5,
                 embedder: "Callable[[str], list[float]] | None" = None,
                 ) -> list[SkillEntry]:
        """
        v5.010 P1-SkillRL-1: AdaptiveRetrieval，支持embedding相似度。

        embedder: 可选的文本→向量函数。提供时用cosine相似度，
                  否则回退关键词匹配。
        """
        results = []
        q = query.lower()

        # v5.010: 如果有embedder，计算query embedding
        query_emb: list[float] = []
        if embedder and query:
            try:
                query_emb = embedder(query)
            except Exception:
                query_emb = []

        for entry in self._skills.values():
            # Filter
            if product_id and entry.skill_type == "task_specific" and entry.product_id != product_id:
                continue

            # v5.010: embedding相似度优先，fallback关键词
            if query_emb and entry.embedding:
                relevance = max(0.0, self._cosine_sim(query_emb, entry.embedding))
            elif q:
                text = (entry.name + " " + entry.content).lower()
                hits = sum(1 for word in q.split() if word in text)
                relevance = min(1.0, 0.3 + hits * 0.2)
            else:
                relevance = 0.5

            # Weight
            weight = 1.5 if (product_id and entry.skill_type == "task_specific") else 1.0

            score = entry.confidence * max(entry.success_rate, 0.5) * relevance * weight
            results.append((score, entry))

        results.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in results[:top_k]]

    def ensure_embeddings(self, embedder: "Callable[[str], list[float]]") -> int:
        """Lazy-load embeddings for all skills. Returns count of newly generated."""
        count = 0
        for entry in self._skills.values():
            if entry.embedding:
                continue
            try:
                text = f"{entry.name} {entry.content}"
                entry.embedding = embedder(text)
                count += 1
            except Exception:
                pass
        if count > 0:
            self._save()
        return count

    def retrieve_for_opinion(self, product_id: str = "", key_id: str = "") -> str:
        """
        Format skill context for opinion command, inject into prompt.
        General Skills first, Task-Specific second.
        """
        generals   = [e for e in self._skills.values()
                      if e.skill_type == "general"
                      and (not key_id or e.key_id == key_id)]
        task_specs = [e for e in self._skills.values()
                      if e.skill_type == "task_specific"
                      and (not product_id or e.product_id == product_id)]

        lines = []
        if generals:
            lines.append("General Skills:")
            for e in sorted(generals, key=lambda x: -x.confidence)[:5]:
                lines.append(f"  [{e.key_id}] {e.name} (confidence{e.confidence:.0%}) - {e.content[:60]}")

        if task_specs:
            lines.append(f"\nProduct skills ({product_id or 'Task-Specific'}):")
            for e in sorted(task_specs, key=lambda x: -x.confidence)[:5]:
                lines.append(f"  [{e.product_id}] {e.name} (success_rate{e.success_rate:.0%}) - {e.content[:60]}")

        return "\n".join(lines) if lines else ""

    # -- Distill from existing data ------------------------------------

    # -- v4.97 SkillRL: Recursive Co-evolution (#16 SkillRL 2026) --

    def mark_needs_revision(self, skill_id: str, reason: str = "") -> bool:
        """
        v4.97 — SkillRL Recursive Co-evolution 自动触发 (#16 SkillRL 2026)

        原论文缺口：SkillRL 在验证失败时自动更新Skill bank，GCC 4.96 需手动操作。
        修复：skeptic 失败 → 调用此方法标记 skill 需复审
              consolidate 时自动对标记 skill 重蒸馏(auto_redist_marked)

        被 skeptic._apply() 在验证失败时调用：
            skillbank.mark_needs_revision(
                skill_id=f"GEN_{card.id}",
                reason=verdict.new_pitfalls[0] if verdict.new_pitfalls else ""
            )
        """
        from datetime import datetime, timezone
        entry = self._skills.get(skill_id)
        if not entry:
            return False
        # Lower confidence, mark for review
        entry.confidence = max(0.1, entry.confidence - 0.15)
        entry.updated_at = datetime.now(timezone.utc).isoformat()
        # Append failure record to content
        if reason:
            entry.content = (entry.content + f" [NEEDS_REVISION: {reason[:80]}]")[:200]
        self._save()
        return True

    def auto_redist_marked(self, gcc_root=None) -> int:
        """
        v4.97 — consolidate 时自动重蒸馏被标记需复审的 skills。
        对 content 含 [NEEDS_REVISION] 标记的条目，从最新 card 重蒸馏覆盖。

        Returns:
            int: 重蒸馏的 skill 数量
        """
        marked = [
            e for e in self._skills.values()
            if "NEEDS_REVISION" in e.content
        ]
        if not marked:
            return 0

        # Re-distill from knowledge cards (overwrite old content)
        redist_count = self.distill_from_cards(gcc_root=gcc_root)

        # Clear NEEDS_REVISION marks
        for entry in self._skills.values():
            if "NEEDS_REVISION" in entry.content:
                entry.content = entry.content.split("[NEEDS_REVISION:")[0].strip()
        self._save()
        return len(marked)

    def distill_from_cards(self, gcc_root=None) -> int:
        """
        Distill General Skills from knowledge cards.
        Knowledge cards -> extract core rules -> write to SkillBank.
        Corresponds to SkillRL experience-based distillation.
        """
        import json
        from pathlib import Path

        root   = Path(gcc_root or ".").parent if gcc_root else Path(".")
        db_path = root / ".gcc" / "gcc.db"
        if not db_path.exists():
            return 0

        import sqlite3
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cards = conn.execute(
            "SELECT id, key_id, title, lessons_text, why_text FROM cards WHERE lessons_text != ''"
        ).fetchall()

        n = 0
        for card in cards:
            if not card["lessons_text"]:
                continue
            skill_id = f"GEN_{card['id']}"
            entry = SkillEntry(
                skill_id   = skill_id,
                name       = card["title"] or card["id"],
                skill_type = "general",
                product_id = "",
                key_id     = card["key_id"] or "",
                content    = (card["lessons_text"] or "")[:200],
                source     = "card",
                confidence = 0.75,
            )
            self.add(entry)
            n += 1

        conn.close()
        return n

    def distill_from_suggestions(self, gcc_root=None) -> int:
        """
        Distill Task-Specific Skills from applied parameter suggestions.
        applied suggestions -> write to SkillBank, with product label.
        """
        import sqlite3
        from pathlib import Path

        root    = Path(gcc_root or ".").parent if gcc_root else Path(".")
        db_path = root / ".gcc" / "gcc.db"
        if not db_path.exists():
            return 0

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        sugs = conn.execute("""
            SELECT s.suggestion_id, s.description, s.evidence, s.suggested_value,
                   l.key_id,
                   (SELECT symbol FROM improvement_product_links WHERE key_id=l.key_id LIMIT 1) as product_id
            FROM suggestions s
            JOIN improvement_suggestion_links l ON s.suggestion_id=l.suggestion_id
            WHERE s.status='applied'
        """).fetchall()

        n = 0
        for sug in sugs:
            if not sug["product_id"]:
                continue
            skill_id = f"TS_{sug['suggestion_id']}"
            content  = sug["description"] or ""
            if sug["evidence"]:
                content += f" Evidence: {sug['evidence'][:80]}"
            entry = SkillEntry(
                skill_id   = skill_id,
                name       = (sug["description"] or "")[:50],
                skill_type = "task_specific",
                product_id = sug["product_id"],
                key_id     = sug["key_id"] or "",
                content    = content[:200],
                source     = "suggest",
                confidence = 0.85,
            )
            self.add(entry)
            n += 1

        conn.close()
        return n

    # -- Statistics ----------------------------------------------

    def status(self) -> dict:
        generals   = [e for e in self._skills.values() if e.skill_type == "general"]
        task_specs = [e for e in self._skills.values() if e.skill_type == "task_specific"]
        return {
            "total":          len(self._skills),
            "general":        len(generals),
            "task_specific":  len(task_specs),
            "products":        list({e.product_id for e in task_specs if e.product_id}),
            "avg_confidence": sum(e.confidence for e in self._skills.values()) / max(len(self._skills), 1),
        }

    # -- Persistence --------------------------------------------

    def _save(self):
        import json
        lines = []
        for e in self._skills.values():
            lines.append(json.dumps({
                "skill_id":    e.skill_id,
                "name":        e.name,
                "skill_type":  e.skill_type,
                "product_id":  e.product_id,
                "key_id":      e.key_id,
                "content":     e.content,
                "source":      e.source,
                "confidence":  e.confidence,
                "use_count":   e.use_count,
                "success_rate": e.success_rate,
                "created_at":  e.created_at,
                "updated_at":  e.updated_at,
                "version":     e.version,
                "embedding":   e.embedding if e.embedding else [],
                "when_to_apply": e.when_to_apply,
            }, ensure_ascii=False))
        self._file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _load(self):
        import json
        if not self._file.exists():
            return
        for line in self._file.read_text(encoding="utf-8").strip().split("\n"):
            if not line.strip():
                continue
            try:
                d = json.loads(line)
                self._skills[d["skill_id"]] = SkillEntry(**d)
            except Exception:
                pass
