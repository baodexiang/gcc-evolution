"""
GCC v4.1 — Session Manager
Full lifecycle: plan → execute → evaluate → distill → mutate → crossover
"""

from __future__ import annotations

import json
from pathlib import Path

from .config import GCCConfig, load_config, init_config
from .crossover import Crossover
from .distiller import Distiller
from .evaluator import Evaluator
from .experience_store import GlobalMemory, LocalMemory
from .llm_client import LLMClient
from .models import (
    CardStatus,
    ExperienceCard,
    ExperienceType,
    ImprovementPlan,
    MemoryDiagnostic,
    SessionSummary,
    SessionTrajectory,
    TrajectoryEvaluation,
)
from .normalizer import Normalizer
from .planner import Planner
from .retriever import Retriever, RetrievalResult


class SessionManager:
    """
    Main API for GCC v4.1.

    v3.7: + trajectory mutation (revise failed steps)
    v3.8: + trajectory crossover (merge best practices)
    v4.0: + dual-layer retrieval (Agent KB) + VF injection
    v4.1: + graph-aware retrieval + goal-aware pruning + always-record scores
    """

    def __init__(self, config: GCCConfig, llm=None, normalize_mode: str = "auto"):
        self.config = config
        self.llm = llm

        self.global_mem = GlobalMemory(config.global_db)
        self.local_mem: LocalMemory | None = None

        self.evaluator = Evaluator(llm=self.llm, weights=config.eval_weights)
        self.distiller = Distiller(llm=self.llm, project=config.project_name)
        self.retriever = Retriever(self.global_mem, config)
        self.crossover = Crossover(llm=self.llm)
        self.planner = Planner(llm=self.llm)
        self.normalizer = Normalizer(llm=self.llm, mode=normalize_mode)

        self._trajectory: SessionTrajectory | None = None
        self._experiences_used: list[str] = []
        self._experiences_gated: list[tuple[str, str]] = []  # v4.0: (card_id, reason)

    @classmethod
    def from_config(cls, path: str | None = None, use_llm: bool = True) -> SessionManager:
        config = load_config(path)
        llm = None
        if use_llm and config.llm_api_key:
            try:
                llm = LLMClient(config)
            except Exception:
                llm = None
        return cls(config, llm=llm)

    @classmethod
    def init_project(cls, project_name: str, project_type: str = "custom") -> SessionManager:
        config_path = init_config(project_name, project_type)
        config = load_config(config_path)
        return cls(config)

    # ════════════════════════════════════════════════════════
    # Session Lifecycle
    # ════════════════════════════════════════════════════════

    def start_session(self, task: str, key: str = "",
                      retrieve_experience: bool = True) -> str:
        self._trajectory = SessionTrajectory(
            task=task, project=self.config.project_name, key=key,
        )
        self.local_mem = LocalMemory(
            self._trajectory.session_id, self.config.local_dir,
        )
        self._experiences_used = []
        self._experiences_gated = []

        if retrieve_experience:
            # v4.0: dual-layer retrieval with disagreement gate
            result = self.retriever.retrieve_dual(task, project=self.config.project_name)
            self._experiences_used = result.all_ids
            self._experiences_gated = [(c.id, r) for c, r in result.gated_out]

        return self._trajectory.session_id

    def record_step(self, description: str, result: str = "pass",
                    feedback: str = "", metrics: dict | None = None) -> None:
        if not self._trajectory:
            raise RuntimeError("No active session.")
        self._trajectory.add_step(description, result, feedback, metrics)
        if result == "fail" and self.local_mem:
            self.local_mem.record_failure(description)

    def add_note(self, note: str) -> None:
        if self._trajectory:
            self._trajectory.notes.append(note)

    def finish_session(self) -> SessionSummary:
        """
        End session — full evolution loop:
        1. Evaluate trajectory (+ delta vs previous sessions)
        2. Distill experience cards
        3. Generate mutations for failed steps
        4. Quality gate: filter low-quality cards before storage
        5. Store cards that pass gate
        6. Try crossover
        7. Record downstream impact for used cards
        8. Build diagnostic + summary
        """
        if not self._trajectory:
            raise RuntimeError("No active session.")

        from datetime import datetime, timezone
        self._trajectory.ended_at = datetime.now(timezone.utc).isoformat()

        # ── 1. Evaluate with delta (v4.0) ──
        prev_scores = []
        if self._trajectory.key:
            prev_scores = self.global_mem.get_key_score_history(self._trajectory.key)
        evaluation = self.evaluator.evaluate_with_delta(self._trajectory, prev_scores)

        # ── 2. Distill ──
        cards = self.distiller.distill(self._trajectory, evaluation)

        # ── 3. Mutate ──
        mutations = self.distiller.mutate(self._trajectory)

        # ── 4. Normalize ──
        cards = self.normalizer.normalize_batch(cards)
        mutations = self.normalizer.normalize_batch(mutations)

        # ── 5. Quality gate (v4.0) ──
        quality_submitted = len(cards) + len(mutations)
        quality_passed = 0
        quality_rejected = 0
        quality_reasons: list[str] = []
        accepted_cards: list[ExperienceCard] = []
        accepted_mutations: list[ExperienceCard] = []

        for card in cards:
            card.embedding = self.retriever.embedder.embed(card.searchable_text())
            passed, quality = self.global_mem.store_with_gate(card)
            if passed:
                quality_passed += 1
                accepted_cards.append(card)
            else:
                quality_rejected += 1
                quality_reasons.extend(quality.rejection_reasons[:2])

        for mut in mutations:
            mut.embedding = self.retriever.embedder.embed(mut.searchable_text())
            passed, quality = self.global_mem.store_with_gate(mut)
            if passed:
                quality_passed += 1
                accepted_mutations.append(mut)
            else:
                quality_rejected += 1
                quality_reasons.extend(quality.rejection_reasons[:2])

        # ── 6. Crossover ──
        crossovers = []
        if self._trajectory.key:
            success_cards = [
                c for c in self.global_mem.get_all(limit=500)
                if c.exp_type == ExperienceType.SUCCESS
                and self._trajectory.key.lower() in c.searchable_text().lower()
            ]
            cross_card = self.crossover.crossover(
                self._trajectory.key, self._trajectory.task, success_cards)
            if cross_card:
                cross_card.embedding = self.retriever.embedder.embed(cross_card.searchable_text())
                self.global_mem.store(cross_card)
                crossovers.append(cross_card)

        # ── 7. Record session score (v4.1: always, not just when cards used) ──
        used_card_ids = self._experiences_used or []
        if self._trajectory.key:
            self.global_mem.record_session_score(
                session_id=self._trajectory.session_id,
                key=self._trajectory.key,
                task=self._trajectory.task,
                score=evaluation.overall_score,
                card_ids=used_card_ids,
            )
        # Update downstream impact for actually used cards
        elif self._experiences_used:
            self.global_mem.record_session_score(
                session_id=self._trajectory.session_id,
                key=self._trajectory.key,
                task=self._trajectory.task,
                score=evaluation.overall_score,
                card_ids=self._experiences_used,
            )

        # ── 8. Memory diagnostic ──
        diagnostic = self._compute_diagnostic(
            accepted_cards, accepted_mutations, evaluation, self._experiences_used)
        diagnostic.quality_submitted = quality_submitted
        diagnostic.quality_passed = quality_passed
        diagnostic.quality_rejected = quality_rejected
        diagnostic.quality_reasons = quality_reasons[:5]

        # ── 9. Experience feedback ──
        exp_feedback = self._compute_experience_feedback(
            self._experiences_used, self._trajectory)

        # ── 10. Auto-validate used cards on success ──
        if evaluation.overall_score >= 0.7:
            for card_id in self._experiences_used:
                self.validate_card(card_id,
                                   reason=f"contributed to score {evaluation.overall_score:.2f}")

        # ── 11. Build summary ──
        summary = SessionSummary(
            session_id=self._trajectory.session_id,
            task=self._trajectory.task,
            key=self._trajectory.key,
            total_steps=len(self._trajectory.steps),
            passed_steps=self._trajectory.passed,
            failed_steps=self._trajectory.failed,
            evaluation=evaluation,
            experiences_distilled=accepted_cards,
            mutations_generated=accepted_mutations,
            crossovers_generated=crossovers,
            experiences_used=self._experiences_used,
            diagnostic=diagnostic,
            experience_feedback=exp_feedback,
        )

        self._save_trajectory()
        self._trajectory = None
        self.local_mem = None

        return summary

    # ════════════════════════════════════════════════════════
    # Planning (v4.0)
    # ════════════════════════════════════════════════════════

    def generate_plans(self, task: str) -> list[ImprovementPlan]:
        """Generate diverse improvement plans for a task."""
        experiences = self.retriever.retrieve(task, project=self.config.project_name)
        return self.planner.generate_plans(task, experiences)

    # ════════════════════════════════════════════════════════
    # Experience Access (v4.0: dual-layer + VF)
    # ════════════════════════════════════════════════════════

    def get_experience_context(self, task: str, mode: str = "verify") -> str:
        """
        Get formatted experience context for injection.
        mode="verify" (default): Verification-First format
        mode="reference": legacy format
        """
        return self.retriever.get_context(task, project=self.config.project_name, mode=mode)

    def get_retrieval_summary(self, task: str) -> str:
        """Get dual-layer retrieval summary without injecting."""
        result = self.retriever.retrieve_dual(task, project=self.config.project_name)
        return result.summary()

    def search_experiences(self, query: str, limit: int = 10) -> list[ExperienceCard]:
        return self.retriever.retrieve(query, top_k=limit)

    def get_experience_stats(self) -> dict:
        return self.global_mem.stats()

    # ════════════════════════════════════════════════════════
    # v4.0: Quality & Maintenance
    # ════════════════════════════════════════════════════════

    def compress_experiences(self, threshold: float = 0.70) -> int:
        """Merge similar cards. Returns count of deprecated cards."""
        return self.global_mem.compress(overlap_threshold=threshold)

    def get_card_impact(self, card_id: str) -> dict:
        """Get downstream impact report for a card."""
        card = self.global_mem.get(card_id)
        if not card:
            return {"error": "card not found"}
        return {
            "card_id": card_id,
            "insight": card.key_insight,
            "use_count": card.use_count,
            "downstream_sessions": len(card.downstream_sessions),
            "downstream_avg_score": card.downstream_avg,
            "downstream_scores": card.downstream_scores,
            "children": [c.id for c in self.global_mem.get_children(card_id)],
            "supersedes": card.supersedes_id or None,
        }

    def get_key_trend(self, key: str) -> list[dict]:
        """Get score trend for a KEY across sessions."""
        return self.global_mem.get_key_score_history(key)

    def mid_session_retrieve(self, step_context: str, top_k: int = 2) -> str:
        """
        v4.1: Retrieve experiences mid-session for a specific step.
        Uses goal-aware pruning (SWE-Pruner) + graph expansion.
        """
        task_context = ""
        if self._trajectory:
            task_context = self._trajectory.task
        return self.retriever.get_step_context(
            step_context, task_context=task_context,
            project=self.config.project_name, mode="verify")

    def export_experiences(self, path: str = ".gcc/experiences/export.json") -> int:
        return self.global_mem.export_json(path)

    def export_bundle(self, output_path: str = "gcc_bundle.zip") -> dict:
        """
        v4.1: One-click bundle for device migration.
        Packs all project state into a single zip:
          - .gcc/evolution.yaml (config)
          - .gcc/experiences/global.db (all cards + scores)
          - .gcc/keys.yaml (KEY registry)
          - .gcc/local_memory/ (session logs)
          - configs/seed_experiences.yaml (if customized)
          - manifest.json (metadata for restore validation)
        """
        import zipfile
        import json as _json
        from datetime import datetime, timezone

        manifest = {
            "gcc_version": "4.2.0",
            "project": self.config.project_name,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "card_count": self.global_mem.count(),
            "embedder": self.embedder_info(),
            "files": [],
        }

        # Files to bundle (relative path → actual path)
        bundle_files: list[tuple[str, Path]] = []

        candidates = [
            (".gcc/evolution.yaml", Path(".gcc/evolution.yaml")),
            (".gcc/evolution.yml", Path(".gcc/evolution.yml")),
            (".gcc/keys.yaml", Path(".gcc/keys.yaml")),
            (".gcc/experiences/global.db", Path(self.config.global_db)),
            ("configs/seed_experiences.yaml",
             Path("configs/seed_experiences.yaml")),
        ]
        for arc_name, fpath in candidates:
            if fpath.exists():
                bundle_files.append((arc_name, fpath))

        # Local memory directory
        local_dir = Path(self.config.local_dir)
        if local_dir.exists():
            for f in local_dir.rglob("*"):
                if f.is_file():
                    arc = str(f.relative_to(local_dir.parent.parent))
                    bundle_files.append((arc, f))

        # Write zip
        with zipfile.ZipFile(output_path, "w",
                             zipfile.ZIP_DEFLATED) as zf:
            for arc_name, fpath in bundle_files:
                zf.write(fpath, arc_name)
                manifest["files"].append(arc_name)
            # Add manifest
            zf.writestr("manifest.json",
                        _json.dumps(manifest, indent=2, ensure_ascii=False))

        return manifest

    def import_bundle(self, bundle_path: str,
                      overwrite: bool = False) -> dict:
        """
        v4.1: Restore from migration bundle.
        Returns manifest with restore results.
        """
        import zipfile
        import json as _json

        if not Path(bundle_path).exists():
            return {"error": f"Bundle not found: {bundle_path}"}

        with zipfile.ZipFile(bundle_path, "r") as zf:
            # Read manifest
            try:
                manifest = _json.loads(zf.read("manifest.json"))
            except KeyError:
                manifest = {"gcc_version": "unknown", "files": []}

            restored = []
            skipped = []

            for name in zf.namelist():
                if name == "manifest.json":
                    continue
                target = Path(name)

                if target.exists() and not overwrite:
                    skipped.append(name)
                    continue

                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zf.read(name))
                restored.append(name)

        # Re-init store connection if DB was replaced
        db_path = self.config.global_db
        if any("global.db" in f for f in restored):
            self.global_mem.close()
            self.global_mem = GlobalMemory(db_path)
            self.retriever = Retriever(self.global_mem, self.config)

        return {
            "manifest": manifest,
            "restored": restored,
            "skipped": skipped,
            "card_count": self.global_mem.count(),
        }

    def reembed_all(self) -> int:
        """v4.1: Re-embed all cards with current embedder (after upgrading)."""
        return self.retriever.reembed_all()

    def embedder_info(self) -> dict:
        """v4.1: Report which embedder is active."""
        emb = self.retriever.embedder
        return {
            "type": emb.name,
            "dim": emb.dim,
            "model": getattr(emb, 'model_name', 'N/A'),
        }

    def import_experiences(self, path: str) -> int:
        count = self.global_mem.import_json(path)
        self.retriever.ensure_embeddings()
        return count

    def seed_experiences(self, project_types: list[str],
                         seed_file: str | None = None) -> int:
        """
        v4.0: Load pre-built experience cards from seed config.
        project_types: e.g. ["domain_system", "general"]
        Skips cards whose key_insight already exists in the store.
        """
        import yaml

        # Find seed file
        if seed_file and Path(seed_file).exists():
            seed_path = Path(seed_file)
        else:
            # Search in known locations
            candidates = [
                Path("configs/seed_experiences.yaml"),
                Path(".gcc/seed_experiences.yaml"),
                Path(__file__).parent.parent / "configs" / "seed_experiences.yaml",
            ]
            seed_path = next((p for p in candidates if p.exists()), None)

        if not seed_path:
            return 0

        raw = yaml.safe_load(seed_path.read_text("utf-8")) or {}

        # Always include "general"
        types_to_load = list(set(project_types) | {"general"})

        # Get existing insights to skip duplicates
        existing = set()
        for c in self.global_mem.get_all(limit=1000):
            existing.add(c.key_insight.strip().lower()[:80])

        loaded = 0
        for ptype in types_to_load:
            seeds = raw.get(ptype, [])
            for s in seeds:
                insight = s.get("insight", "")
                if insight.strip().lower()[:80] in existing:
                    continue

                card = ExperienceCard(
                    exp_type=ExperienceType.SUCCESS,
                    source_session="seed",
                    trigger_task_type=ptype,
                    trigger_symptom=s.get("trigger", ""),
                    trigger_keywords=s.get("tags", []),
                    strategy=insight,
                    key_insight=insight,
                    confidence=float(s.get("confidence", 0.8)),
                    pitfalls=s.get("pitfalls", []),
                    tags=["seed", ptype] + s.get("tags", []),
                    attachments=s.get("attachments", []),
                    source_ref=s.get("source_ref", ""),
                    project=self.config.project_name,
                )
                # Normalize before storing
                card = self.normalizer.normalize(card)
                card.embedding = self.retriever.embedder.embed(card.searchable_text())
                self.global_mem.store(card)
                loaded += 1

        return loaded

    def validate_card(self, card_id: str, reason: str = "confirmed by session") -> bool:
        """Mark a card as validated (confirmed working by real results)."""
        card = self.global_mem.get(card_id)
        if not card:
            return False
        if card.status == CardStatus.DRAFT or card.status == CardStatus.ACTIVE:
            Normalizer.promote(card, CardStatus.VALIDATED, reason)
        # Always update last_validated timestamp
        from datetime import datetime, timezone
        card.last_validated = datetime.now(timezone.utc).isoformat()
        self.global_mem.store(card)
        return True

    def archive_key(self, key: str, final_insight: str = "") -> int:
        """
        Archive all validated cards for a KEY when it closes.
        Returns number of cards archived.
        """
        all_cards = self.global_mem.get_all(limit=1000)
        archived = Normalizer.archive_key(all_cards, key, final_insight)
        for card in archived:
            self.global_mem.store(card)
        return len(archived)

    def normalize_card(self, card_id: str) -> ExperienceCard | None:
        """Re-normalize an existing card."""
        card = self.global_mem.get(card_id)
        if not card:
            return None
        card = self.normalizer.normalize(card)
        self.global_mem.store(card)
        return card

    def add_draft_card(
        self,
        key_insight: str,
        trigger: str = "",
        strategy: str = "",
        pitfalls: list[str] | None = None,
        tags: list[str] | None = None,
        source_ref: str = "",
        attachments: list[str] | None = None,
        key: str = "",
        exp_type: str = "success",
    ) -> ExperienceCard:
        """
        Add a manually created card (e.g. from paper reading, expert input).
        Card starts as DRAFT, gets normalized to ACTIVE.
        """
        card = ExperienceCard(
            exp_type=ExperienceType(exp_type),
            source_session="manual",
            trigger_symptom=trigger,
            key_insight=key_insight,
            strategy=strategy,
            pitfalls=pitfalls or [],
            tags=tags or [],
            source_ref=source_ref,
            attachments=attachments or [],
            key=key,
            project=self.config.project_name,
            status=CardStatus.DRAFT,
        )
        # Normalize: draft → active, format standardized
        card = self.normalizer.normalize(card)
        card.embedding = self.retriever.embedder.embed(card.searchable_text())
        self.global_mem.store(card)
        return card

    # ════════════════════════════════════════════════════════
    # Memory Diagnostic (v4.0, from AMemGym)
    # ════════════════════════════════════════════════════════

    def _compute_diagnostic(
        self,
        cards: list[ExperienceCard],
        mutations: list[ExperienceCard],
        evaluation: TrajectoryEvaluation,
        used_ids: list[str],
    ) -> MemoryDiagnostic:
        """
        Three-stage diagnostic: write / read / utilization.
        From AMemGym paper Section 3.3.
        """
        diag = MemoryDiagnostic()

        # Write diagnostic: how many steps produced experience cards?
        if self._trajectory:
            diag.write_total = len(self._trajectory.steps)
            diag.write_success = len(cards) + len(mutations)
            if diag.write_total > diag.write_success:
                diag.write_failures = [
                    s.description[:60] for s in self._trajectory.steps
                    if s.result.value == "pass"
                    and not any(s.description[:30] in c.searchable_text() for c in cards)
                ][:5]

        # Read diagnostic: were useful experiences retrieved?
        diag.read_queries = 1 if self._trajectory else 0
        diag.read_hits = len(used_ids) if used_ids else 0
        # v4.0: count gated-out cards as partial read failures
        gated_count = len(self._experiences_gated)
        if gated_count > 0:
            diag.read_misses = [f"gated:{cid[:12]}({reason})" for cid, reason in self._experiences_gated[:3]]
        elif diag.read_queries > 0 and diag.read_hits == 0:
            diag.read_misses = [self._trajectory.task[:60] if self._trajectory else ""]

        # Utilization diagnostic: were retrieved experiences actually applied?
        if used_ids and self._trajectory:
            diag.util_injected = len(used_ids)
            # Heuristic: if session passed and used experiences, they were applied
            pass_rate = self._trajectory.passed / max(len(self._trajectory.steps), 1)
            diag.util_applied = int(len(used_ids) * pass_rate)
            if diag.util_applied < diag.util_injected:
                diag.util_ignored = [
                    uid for uid in used_ids[diag.util_applied:]
                ]

        return diag

    def _compute_experience_feedback(
        self,
        used_ids: list[str],
        trajectory: SessionTrajectory | None,
    ) -> list[dict]:
        """
        v4.0: Record what experience was given, whether it was applied,
        and what the deviation was. Complete feedback for self-evolution.
        """
        feedback = []
        if not trajectory or not used_ids:
            return feedback

        pass_rate = trajectory.passed / max(len(trajectory.steps), 1)

        for card_id in used_ids:
            card = self.global_mem.get(card_id)
            if not card:
                continue

            fb = {
                "card_id": card_id,
                "card_insight": card.key_insight[:80],
                "injected": True,
                "applied": pass_rate > 0.5,
                "session_pass_rate": round(pass_rate, 2),
                "deviation": "",
            }

            # Check if any failed step contradicts the card's advice
            for step in trajectory.steps:
                if step.result.value == "fail":
                    if card.strategy and any(
                        w in step.description.lower()
                        for w in card.strategy.lower().split()[:5]
                    ):
                        fb["deviation"] = f"Failed at: {step.description[:60]}"
                        fb["applied"] = False
                        break

            feedback.append(fb)

        return feedback

    # ════════════════════════════════════════════════════════
    # Internal
    # ════════════════════════════════════════════════════════

    def _save_trajectory(self) -> None:
        if not self._trajectory:
            return
        traj_dir = Path(self.config.local_dir) / "trajectories"
        traj_dir.mkdir(parents=True, exist_ok=True)
        path = traj_dir / f"{self._trajectory.session_id}.json"
        data = {
            "session_id": self._trajectory.session_id,
            "task": self._trajectory.task,
            "key": self._trajectory.key,
            "project": self._trajectory.project,
            "started_at": self._trajectory.started_at,
            "ended_at": self._trajectory.ended_at,
            "plan_selected": self._trajectory.plan_selected,
            "steps": [
                {"step_id": s.step_id, "description": s.description,
                 "result": s.result.value, "feedback": s.feedback,
                 "metrics": s.metrics, "timestamp": s.timestamp}
                for s in self._trajectory.steps
            ],
            "notes": self._trajectory.notes,
        }
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), "utf-8")

    def close(self) -> None:
        self.global_mem.close()
