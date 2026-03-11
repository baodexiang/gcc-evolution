"""
6-Step self-improvement loop primitives.

This module exposes both the abstract orchestration contract and a small
community-safe implementation that can run the free edition end-to-end.
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Dict, List, Any, Optional, Callable
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
import json

from gcc_evolution.skill_registry import SkillBank
from gcc_evolution.L5_orchestration.pipeline import build_research_workflow


class LoopPhase(Enum):
    """Phases of self-improvement loop."""

    OBSERVE = "observe"  # Phase 1: Collect data
    ANALYZE = "analyze"  # Phase 2: Pattern detection
    HYPOTHESIZE = "hypothesize"  # Phase 3: Generate theories
    TEST = "test"  # Phase 4: Validate hypotheses
    IMPROVE = "improve"  # Phase 5: Implement improvements
    INTEGRATE = "integrate"  # Phase 6: Deploy and monitor


@dataclass
class LoopIteration:
    """Single iteration of the 6-step loop."""

    iteration_id: str
    phase: LoopPhase
    observations: Dict[str, Any] = field(default_factory=dict)
    analysis: Optional[Dict[str, Any]] = None
    hypothesis: Optional[str] = None
    test_result: Optional[Dict[str, Any]] = None
    improvement: Optional[str] = None
    timestamp: str = None

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.utcnow().isoformat()


class SelfImprovementLoop(ABC):
    """
    Base class for self-improvement systems.

    The 6-step loop:
      1. OBSERVE: Gather real-world data
      2. ANALYZE: Identify patterns and anomalies
      3. HYPOTHESIZE: Generate improvement hypotheses
      4. TEST: Validate in controlled environment
      5. IMPROVE: Implement successful improvements
      6. INTEGRATE: Deploy and monitor production effects
    """

    def __init__(self):
        self.iteration_history: List[LoopIteration] = []
        self.current_phase = LoopPhase.OBSERVE
        self.metrics = {}
        self.improvement_log = []

    def run_iteration(self) -> LoopIteration:
        """Execute one full iteration of the loop."""
        iteration_id = f"ITER-{len(self.iteration_history) + 1:04d}"
        iteration = LoopIteration(iteration_id=iteration_id, phase=LoopPhase.OBSERVE)

        # Phase 1: Observe
        iteration.observations = self.observe()

        # Phase 2: Analyze
        iteration.analysis = self.analyze(iteration.observations)

        # Phase 3: Hypothesize
        iteration.hypothesis = self.hypothesize(iteration.analysis)

        # Phase 4: Test
        iteration.test_result = self.test_hypothesis(iteration.hypothesis)

        # Phase 5: Improve
        if iteration.test_result.get("valid", False):
            iteration.improvement = self.improve(iteration.hypothesis)

        # Phase 6: Integrate
        if iteration.improvement:
            self.integrate(iteration.improvement)

        self.iteration_history.append(iteration)
        return iteration

    @abstractmethod
    def observe(self) -> Dict[str, Any]:
        """
        Phase 1: Collect observations from the system.

        Returns:
            Dictionary of observations (market data, metrics, events)
        """
        pass

    @abstractmethod
    def analyze(self, observations: Dict[str, Any]) -> Dict[str, Any]:
        """
        Phase 2: Analyze observations for patterns.

        Args:
            observations: Raw data from observe()

        Returns:
            Analysis results (patterns, anomalies, insights)
        """
        pass

    @abstractmethod
    def hypothesize(self, analysis: Dict[str, Any]) -> str:
        """
        Phase 3: Generate improvement hypotheses.

        Args:
            analysis: Analysis results from Phase 2

        Returns:
            Hypothesis description (proposed improvement)
        """
        pass

    @abstractmethod
    def test_hypothesis(self, hypothesis: str) -> Dict[str, Any]:
        """
        Phase 4: Test hypothesis in safe environment.

        Args:
            hypothesis: Proposed improvement from Phase 3

        Returns:
            Test results with validity flag
        """
        pass

    @abstractmethod
    def improve(self, hypothesis: str) -> str:
        """
        Phase 5: Implement successful improvement.

        Args:
            hypothesis: Validated hypothesis from Phase 4

        Returns:
            Description of implemented change
        """
        pass

    @abstractmethod
    def integrate(self, improvement: str) -> None:
        """
        Phase 6: Deploy improvement to production.

        Args:
            improvement: Implemented change from Phase 5
        """
        pass

    def get_improvement_rate(self) -> float:
        """Calculate how many iterations resulted in improvements."""
        if not self.iteration_history:
            return 0.0

        improved = sum(
            1 for it in self.iteration_history if it.improvement is not None
        )
        return improved / len(self.iteration_history)

    def get_last_iteration(self) -> Optional[LoopIteration]:
        """Get most recent iteration."""
        return self.iteration_history[-1] if self.iteration_history else None

    def get_summary(self) -> Dict[str, Any]:
        """Get loop performance summary."""
        return {
            "total_iterations": len(self.iteration_history),
            "improvement_rate": self.get_improvement_rate(),
            "last_improvement": next(
                (it.improvement for it in reversed(self.iteration_history) if it.improvement),
                None,
            ),
            "metrics": self.metrics,
        }


class SimpleImprovementLoop(SelfImprovementLoop):
    """
    Minimal implementation of self-improvement loop for testing.

    This is a concrete example showing how to implement the loop.
    """

    def __init__(self):
        super().__init__()
        self.observations_history = []
        self.test_environment = {}

    def observe(self) -> Dict[str, Any]:
        """Collect basic metrics."""
        observation = {
            "timestamp": datetime.utcnow().isoformat(),
            "iterations": len(self.iteration_history),
        }
        self.observations_history.append(observation)
        return observation

    def analyze(self, observations: Dict[str, Any]) -> Dict[str, Any]:
        """Simple pattern detection."""
        return {
            "pattern": "cyclical",
            "confidence": 0.7,
            "trend": "improving"
            if len(self.observations_history) > 1
            else "baseline",
        }

    def hypothesize(self, analysis: Dict[str, Any]) -> str:
        """Generate simple hypothesis."""
        trend = analysis.get("trend", "baseline")
        return f"System improving on {trend} trajectory"

    def test_hypothesis(self, hypothesis: str) -> Dict[str, Any]:
        """Test in safe mode."""
        # Simulated test: always valid for demo
        return {"valid": True, "score": 0.85}

    def improve(self, hypothesis: str) -> str:
        """Apply improvement."""
        improvement = f"Applied: {hypothesis}"
        self.improvement_log.append(improvement)
        return improvement

    def integrate(self, improvement: str) -> None:
        """Deploy to test environment."""
        self.test_environment["last_improvement"] = improvement
        self.test_environment["timestamp"] = datetime.utcnow().isoformat()


class CommunitySelfImprovementLoop(SelfImprovementLoop):
    """
    Free-edition concrete loop implementation.

    It wires together L1-L4 community-safe components and persists a minimal
    audit trail so `gcc-evo loop TASK --once` works in a fresh open-source
    install without paid services.
    """

    def __init__(
        self,
        task_id: str,
        sensory_memory,
        short_term_memory,
        long_term_memory,
        retriever,
        distiller,
        skeptic,
        state_dir: str | Path = "state",
    ):
        super().__init__()
        self.task_id = task_id
        self.sensory_memory = sensory_memory
        self.short_term_memory = short_term_memory
        self.long_term_memory = long_term_memory
        self.retriever = retriever
        self.distiller = distiller
        self.skeptic = skeptic
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.reflection_path = self.state_dir / "audit" / f"{self.task_id}_reflections.jsonl"
        self.causal_path = self.state_dir / "audit" / f"{self.task_id}_causal.jsonl"
        self.graph_path = self.state_dir / "audit" / f"{self.task_id}_graph.json"
        self.auto_task_path = self.state_dir / "audit" / f"{self.task_id}_auto_tasks.jsonl"
        self._latest_observation: Dict[str, Any] = {}
        self._latest_analysis: Dict[str, Any] = {}
        self._latest_test_result: Dict[str, Any] = {}
        self._promotion_threshold = 3
        self._merge_similarity_threshold = 0.6
        self.skillbank = SkillBank(self.state_dir / "skillbank.jsonl")

    def observe(self) -> Dict[str, Any]:
        observation = {
            "task_id": self.task_id,
            "iteration": len(self.iteration_history) + 1,
            "timestamp": datetime.utcnow().isoformat(),
        }
        self._latest_observation = observation
        self.sensory_memory.store("current_observation", observation)
        self.short_term_memory.store("observations", observation)
        return observation

    def analyze(self, observations: Dict[str, Any]) -> Dict[str, Any]:
        reflections = self._load_reflections(limit=3)
        causal_triplets = self._load_causal_triplets(limit=3)
        success_patterns = self._load_success_patterns(limit=3)
        failure_constraints = self._load_failure_constraints(limit=3)
        skill_context = self._load_skill_context(limit=4)
        graph_context = self._load_graph_context(limit=3)
        documents = [
            {
                "id": f"obs-{observations['iteration']}",
                "text": json.dumps(observations, ensure_ascii=False),
                "created_at": observations["timestamp"],
            }
        ]
        for idx, reflection in enumerate(reflections, 1):
            documents.append(
                {
                    "id": f"reflection-{observations['iteration']}-{idx}",
                    "text": reflection.get("reflection", ""),
                    "created_at": reflection.get("timestamp", observations["timestamp"]),
                    "metadata": {"source": "self_reflection"},
                }
            )
        for idx, triplet in enumerate(causal_triplets, 1):
            documents.append(
                {
                    "id": f"causal-{observations['iteration']}-{idx}",
                    "text": (
                        f"cause={triplet.get('cause','')} | "
                        f"action={triplet.get('action','')} | "
                        f"outcome={triplet.get('outcome','')}"
                    ),
                    "created_at": triplet.get("timestamp", observations["timestamp"]),
                    "metadata": {"source": "causal_triplet"},
                }
            )
        for idx, pattern in enumerate(success_patterns, 1):
            documents.append(
                {
                    "id": f"success-{observations['iteration']}-{idx}",
                    "text": (
                        f"success_pattern conditions={pattern.get('conditions',{})} | "
                        f"success_rate={pattern.get('success_rate', 0):.2f} | "
                        f"actions={pattern.get('actions', [])}"
                    ),
                    "created_at": observations["timestamp"],
                    "metadata": {"source": "success_pattern"},
                }
            )
        for idx, constraint in enumerate(failure_constraints, 1):
            documents.append(
                {
                    "id": f"failure-{observations['iteration']}-{idx}",
                    "text": (
                        f"failure_constraint issues={constraint.get('issues', [])} | "
                        f"reflection={constraint.get('reflection', '')} | "
                        f"outcome={constraint.get('outcome', '')}"
                    ),
                    "created_at": constraint.get("timestamp", observations["timestamp"]),
                    "metadata": {"source": "failure_constraint"},
                }
            )
        for idx, skill in enumerate(skill_context, 1):
            documents.append(
                {
                    "id": f"skill-{observations['iteration']}-{idx}",
                    "text": f"{skill.skill_type} skill {skill.name} | {skill.content}",
                    "created_at": skill.updated_at,
                    "metadata": {"source": "skillbank", "skill_type": skill.skill_type},
                }
            )
        for idx, node in enumerate(graph_context, 1):
            documents.append(
                {
                    "id": f"graph-{observations['iteration']}-{idx}",
                    "text": (
                        f"lineage hypothesis={node.get('hypothesis','')} | "
                        f"downstream_avg={node.get('downstream_avg', 0.0):.3f} | "
                        f"visits={node.get('visits', 0)}"
                    ),
                    "created_at": node.get("updated_at", observations["timestamp"]),
                    "metadata": {
                        "source": "improvement_graph",
                        "graph_node_id": node.get("node_id", ""),
                    },
                }
            )
        self.retriever.index(documents)
        retrieval = self.retriever.retrieve(self.task_id, top_k=3)
        analysis = {
            "query": self.task_id,
            "matches": retrieval,
            "match_count": len(retrieval),
            "reflections": reflections,
            "reflection_count": len(reflections),
            "causal_triplets": causal_triplets,
            "causal_count": len(causal_triplets),
            "success_patterns": success_patterns,
            "success_count": len(success_patterns),
            "failure_constraints": failure_constraints,
            "failure_count": len(failure_constraints),
            "skills": [skill.to_dict() for skill in skill_context],
            "skill_count": len(skill_context),
            "graph_context": graph_context,
            "graph_count": len(graph_context),
        }
        self._latest_analysis = analysis
        return analysis

    def hypothesize(self, analysis: Dict[str, Any]) -> str:
        match_count = analysis.get("match_count", 0)
        reflection_count = analysis.get("reflection_count", 0)
        causal_count = analysis.get("causal_count", 0)
        success_count = analysis.get("success_count", 0)
        failure_count = analysis.get("failure_count", 0)
        skill_count = analysis.get("skill_count", 0)
        graph_count = analysis.get("graph_count", 0)
        reflection_hint = ""
        reflections = analysis.get("reflections") or []
        if reflections:
            reflection_hint = f"; avoid repeating: {reflections[0].get('reflection', '')[:120]}"
        return (
            f"Iteration {len(self.iteration_history) + 1}: "
            f"continue baseline learning with {match_count} retrieved context items"
            f" and {reflection_count} prior reflections"
            f" and {causal_count} causal triplets"
            f" and {success_count} success patterns"
            f" and {failure_count} failure constraints"
            f" and {skill_count} skills{reflection_hint}"
            f" and {graph_count} lineage nodes"
        )

    def _build_decision_payload(self, hypothesis: str) -> Dict[str, Any]:
        analysis = self._latest_analysis or {}
        match_count = int(analysis.get("match_count", 0))
        data_references = [
            "task_id", "iteration", "timestamp", "match_count",
            "reflection_count", "causal_count", "success_count", "failure_count", "skill_count", "graph_count",
        ]
        if analysis.get("matches"):
            data_references.append("matches")
        if analysis.get("reflections"):
            data_references.append("reflections")
        if analysis.get("causal_triplets"):
            data_references.append("causal_triplets")
        if analysis.get("success_patterns"):
            data_references.append("success_patterns")
        if analysis.get("failure_constraints"):
            data_references.append("failure_constraints")
        if analysis.get("skills"):
            data_references.append("skills")
        if analysis.get("graph_context"):
            data_references.append("graph_context")
        conditions = ["+baseline_learning"]
        if match_count > 0:
            conditions.append("+retrieved_context")
        if analysis.get("reflection_count", 0) > 0:
            conditions.append("+self_reflection")
        if analysis.get("causal_count", 0) > 0:
            conditions.append("+causal_memory")
        if analysis.get("success_count", 0) > 0:
            conditions.append("+success_patterns")
        if analysis.get("failure_count", 0) > 0:
            conditions.append("+failure_constraints")
        if analysis.get("skill_count", 0) > 0:
            conditions.append("+skillbank")
        if analysis.get("graph_count", 0) > 0:
            conditions.append("+lineage_graph")
        return {
            "signal": "IMPROVE",
            "action": "OPTIMIZE",
            "confidence": 0.8 if match_count > 0 else 0.65,
            "conditions": conditions,
            "reasoning": hypothesis,
            "data_references": data_references,
            "metadata": {
                "task_id": self.task_id,
                "match_count": match_count,
            },
        }

    def _build_validation_context(self) -> Dict[str, Any]:
        analysis = self._latest_analysis or {}
        return {
            "task_id": self.task_id,
            "iteration": (self._latest_observation or {}).get("iteration"),
            "timestamp": (self._latest_observation or {}).get("timestamp"),
            "match_count": analysis.get("match_count", 0),
            "matches": analysis.get("matches", []),
            "reflection_count": analysis.get("reflection_count", 0),
            "reflections": analysis.get("reflections", []),
            "causal_count": analysis.get("causal_count", 0),
            "causal_triplets": analysis.get("causal_triplets", []),
            "success_count": analysis.get("success_count", 0),
            "success_patterns": analysis.get("success_patterns", []),
            "failure_count": analysis.get("failure_count", 0),
            "failure_constraints": analysis.get("failure_constraints", []),
            "skill_count": analysis.get("skill_count", 0),
            "skills": analysis.get("skills", []),
            "graph_count": analysis.get("graph_count", 0),
            "graph_context": analysis.get("graph_context", []),
        }

    def _load_reflections(self, limit: int = 3) -> List[Dict[str, Any]]:
        if not self.reflection_path.exists():
            return []
        items: List[Dict[str, Any]] = []
        try:
            lines = self.reflection_path.read_text(encoding="utf-8").splitlines()
            for line in lines[-limit:]:
                try:
                    items.append(json.loads(line))
                except Exception:
                    continue
        except Exception:
            return []
        return list(reversed(items))

    def _record_reflection(self, hypothesis: str, issues: List[str], suggestions: List[str]) -> None:
        self.reflection_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "task_id": self.task_id,
            "iteration": len(self.iteration_history) + 1,
            "reflection": f"{hypothesis} | issues={issues[:3]} | suggestions={suggestions[:2]}",
            "issues": issues,
            "suggestions": suggestions,
            "timestamp": datetime.utcnow().isoformat(),
        }
        with self.reflection_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _load_causal_triplets(self, limit: int = 3) -> List[Dict[str, Any]]:
        if not self.causal_path.exists():
            return []
        items: List[Dict[str, Any]] = []
        try:
            lines = self.causal_path.read_text(encoding="utf-8").splitlines()
            for line in lines[-limit:]:
                try:
                    items.append(json.loads(line))
                except Exception:
                    continue
        except Exception:
            return []
        return list(reversed(items))

    def _record_causal_triplet(
        self,
        hypothesis: str,
        validation_ok: bool,
        issues: List[str],
    ) -> None:
        self.causal_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "task_id": self.task_id,
            "iteration": len(self.iteration_history) + 1,
            "cause": "retrieved_context" if (self._latest_analysis or {}).get("match_count", 0) > 0 else "baseline_only",
            "action": "OPTIMIZE",
            "outcome": "validated" if validation_ok else f"blocked:{'; '.join(issues[:2])}",
            "timestamp": datetime.utcnow().isoformat(),
            "hypothesis": hypothesis,
        }
        with self.causal_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _load_success_patterns(self, limit: int = 3) -> List[Dict[str, Any]]:
        storage = getattr(self.long_term_memory, "storage", None)
        if not storage:
            return []
        try:
            items = storage.search(f"promoted::{self.task_id}::")
        except Exception:
            return []
        items = [x for x in items if isinstance(x, dict)]
        items.sort(key=lambda x: (x.get("count", 0), x.get("success_rate", 0.0)), reverse=True)
        return items[:limit]

    def _load_failure_constraints(self, limit: int = 3) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        items.extend(self._load_reflections(limit=limit))
        for triplet in self._load_causal_triplets(limit=limit * 2):
            outcome = str(triplet.get("outcome", ""))
            if outcome.startswith("blocked:"):
                items.append(
                    {
                        "issues": [outcome],
                        "reflection": triplet.get("hypothesis", ""),
                        "outcome": outcome,
                        "timestamp": triplet.get("timestamp", ""),
                    }
                )
        return items[:limit]

    def _load_skill_context(self, limit: int = 4):
        general = self.skillbank.top_skills(skill_type="general", top_k=limit)
        task_specific = self.skillbank.retrieve(query=self.task_id, symbol=self.task_id, top_k=limit)
        merged = []
        seen = set()
        for entry in task_specific + general:
            if entry.skill_id in seen:
                continue
            seen.add(entry.skill_id)
            merged.append(entry)
        return merged[:limit]

    def _load_graph(self) -> Dict[str, Any]:
        if not self.graph_path.exists():
            return {"nodes": {}, "last_node_id": ""}
        try:
            payload = json.loads(self.graph_path.read_text(encoding="utf-8"))
        except Exception:
            return {"nodes": {}, "last_node_id": ""}
        if not isinstance(payload, dict):
            return {"nodes": {}, "last_node_id": ""}
        payload.setdefault("nodes", {})
        payload.setdefault("last_node_id", "")
        return payload

    def _save_graph(self, graph: Dict[str, Any]) -> None:
        self.graph_path.parent.mkdir(parents=True, exist_ok=True)
        self.graph_path.write_text(
            json.dumps(graph, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _propagate_graph_scores(self, graph: Dict[str, Any], leaf_id: str) -> None:
        visited = set()
        queue = [leaf_id]
        while queue:
            current_id = queue.pop(0)
            if current_id in visited:
                continue
            visited.add(current_id)
            node = graph["nodes"].get(current_id)
            if not isinstance(node, dict):
                continue
            child_scores = [
                float(graph["nodes"].get(child_id, {}).get("score", 0.0))
                for child_id in node.get("children", [])
                if isinstance(graph["nodes"].get(child_id), dict)
            ]
            if child_scores:
                node["downstream_avg"] = sum(child_scores) / len(child_scores)
            else:
                node["downstream_avg"] = float(node.get("score", 0.0))
            node["updated_at"] = datetime.utcnow().isoformat()
            parent_id = node.get("parent_id")
            if parent_id:
                queue.append(parent_id)

    def _update_improvement_graph(self, hypothesis: str, validation: Dict[str, Any]) -> None:
        graph = self._load_graph()
        node_id = f"{self.task_id}:{len(self.iteration_history) + 1:04d}"
        parent_id = graph.get("last_node_id") or ""
        score = float(validation.get("soft_score", validation.get("confidence", 0.0)))
        issues = list(validation.get("issues", []))
        node = {
            "node_id": node_id,
            "task_id": self.task_id,
            "hypothesis": hypothesis,
            "score": score,
            "valid": bool(validation.get("valid", False)),
            "issues": issues[:5],
            "parent_id": parent_id,
            "children": [],
            "visits": 1,
            "downstream_avg": score,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }
        nodes = graph.setdefault("nodes", {})
        nodes[node_id] = node
        if parent_id and parent_id in nodes:
            parent = nodes[parent_id]
            children = list(parent.get("children", []))
            if node_id not in children:
                children.append(node_id)
            parent["children"] = children
            parent["visits"] = int(parent.get("visits", 0)) + 1
        graph["last_node_id"] = node_id
        self._propagate_graph_scores(graph, node_id)
        self._save_graph(graph)

    def _load_graph_context(self, limit: int = 3) -> List[Dict[str, Any]]:
        graph = self._load_graph()
        nodes = list(graph.get("nodes", {}).values())
        nodes = [node for node in nodes if isinstance(node, dict)]
        nodes.sort(
            key=lambda node: (
                float(node.get("downstream_avg", 0.0)),
                int(node.get("visits", 0)),
                node.get("updated_at", ""),
            ),
            reverse=True,
        )
        return nodes[:limit]

    def _pipeline_task_path(self) -> Path:
        for candidate_root in [self.state_dir, *self.state_dir.parents]:
            candidate = candidate_root / ".GCC" / "pipeline" / "tasks.json"
            if candidate.exists():
                return candidate
        return self.state_dir.parent / ".GCC" / "pipeline" / "tasks.json"

    def _create_auto_improvement_task(self, validation: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        issues = list(validation.get("issues", []))
        suggestions = list(validation.get("suggestions", []))
        if validation.get("valid", False) and float(validation.get("soft_score", 1.0)) >= 0.75:
            return None
        headline = issues[0] if issues else "improve validation robustness"
        headline = str(headline).replace("\n", " ").strip()[:72]
        fingerprint = f"{self.task_id}|{headline}"
        payload = {
            "origin_task_id": self.task_id,
            "fingerprint": fingerprint,
            "title": f"Auto improve: {headline}",
            "priority": "P2" if validation.get("valid", False) else "P1",
            "description": f"Generated from observation feedback for {self.task_id}",
            "issues": issues[:5],
            "suggestions": suggestions[:5],
            "created_at": datetime.utcnow().isoformat(),
        }
        self.auto_task_path.parent.mkdir(parents=True, exist_ok=True)
        existing = []
        if self.auto_task_path.exists():
            for line in self.auto_task_path.read_text(encoding="utf-8").splitlines():
                try:
                    existing.append(json.loads(line))
                except Exception:
                    continue
        if any(item.get("fingerprint") == fingerprint for item in existing):
            return None
        with self.auto_task_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        pipeline_path = self._pipeline_task_path()
        if pipeline_path.exists():
            try:
                data = json.loads(pipeline_path.read_text(encoding="utf-8"))
                tasks = data.get("tasks", [])
                if not any(task.get("description", "").endswith(f"[fingerprint={fingerprint}]") for task in tasks):
                    counter = int(data.get("counter", len(tasks)))
                    counter += 1
                    data["counter"] = counter
                    tasks.append(
                        {
                            "task_id": f"GCC-{counter:04d}",
                            "title": payload["title"],
                            "description": f"{payload['description']} [fingerprint={fingerprint}]",
                            "key": "KEY-011",
                            "module": "auto_improvement",
                            "priority": payload["priority"],
                            "stage": "planning",
                            "status": "pending",
                            "dependencies": [],
                            "steps": [
                                {"id": "S1", "title": "review observation issues", "status": "pending", "note": ""},
                                {"id": "S2", "title": "implement mitigation", "status": "pending", "note": ""},
                                {"id": "S3", "title": "validate improvement effect", "status": "pending", "note": ""},
                            ],
                            "created_at": datetime.utcnow().date().isoformat(),
                            "updated_at": datetime.utcnow().date().isoformat(),
                        }
                    )
                    data["tasks"] = tasks
                    pipeline_path.write_text(
                        json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
            except Exception:
                pass
        return payload

    def test_hypothesis(self, hypothesis: str) -> Dict[str, Any]:
        decision = self._build_decision_payload(hypothesis)
        validation_context = self._build_validation_context()
        validation = self.skeptic.validate(decision, context=validation_context)
        result = {
            "valid": validation.is_valid,
            "confidence": validation.confidence,
            "soft_score": getattr(validation, "soft_score", validation.confidence),
            "issues": validation.issues,
            "suggestions": validation.suggestions,
            "decision": decision,
            "context": validation_context,
        }
        self._record_causal_triplet(hypothesis, validation.is_valid, validation.issues)
        self._update_improvement_graph(hypothesis, result)
        auto_task = self._create_auto_improvement_task(result)
        if auto_task:
            result["auto_task"] = auto_task
        if not validation.is_valid:
            self._record_reflection(hypothesis, validation.issues, validation.suggestions)
        self._latest_test_result = result
        return result

    def improve(self, hypothesis: str) -> str:
        iteration = len(self.iteration_history) + 1
        experience = {
            "conditions": {"task": self.task_id, "iteration": iteration},
            "outcome": {
                "success": bool((self._latest_test_result or {}).get("valid", True)),
                "action": "baseline",
            },
        }
        self.distiller.add_experience(experience)
        cards = self.distiller.distill()
        for card in cards:
            self.long_term_memory.store(
                card.card_id,
                {
                    "title": card.title,
                    "confidence": card.confidence,
                    "summary": card.summary,
                },
            )
        promoted = self._promote_short_term_patterns(experience)
        self.skillbank.distill_from_cards()
        self.skillbank.distill_from_suggestions()
        generated = len(cards)
        return (
            f"Stored {generated} distilled card(s) for {self.task_id}"
            f"; promoted {promoted} short-term pattern(s)"
        )

    def integrate(self, improvement: str) -> None:
        audit_dir = self.state_dir / "audit"
        audit_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "task_id": self.task_id,
            "iteration": len(self.iteration_history) + 1,
            "improvement": improvement,
            "skeptic_valid": bool((self._latest_test_result or {}).get("valid", False)),
            "skeptic_confidence": float((self._latest_test_result or {}).get("confidence", 0.0)),
            "skeptic_soft_score": float((self._latest_test_result or {}).get("soft_score", 0.0)),
            "skeptic_issues": (self._latest_test_result or {}).get("issues", []),
            "timestamp": datetime.utcnow().isoformat(),
        }
        with (audit_dir / f"{self.task_id}_log.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def run_once(self) -> Dict[str, Any]:
        """Execute a single community-safe loop iteration and return a summary."""
        iteration = self.run_iteration()
        return {
            "iteration_id": iteration.iteration_id,
            "task_id": self.task_id,
            "phase": iteration.phase.value,
            "observation": iteration.observations,
            "analysis": iteration.analysis,
            "hypothesis": iteration.hypothesis,
            "test_result": iteration.test_result,
            "improvement": iteration.improvement,
            "summary": self.get_summary(),
        }

    def run_research_workflow(self) -> Dict[str, Any]:
        """
        Execute a fixed 5-stage workflow on top of the current loop implementation.

        Stage mapping:
          exploration -> observe + analyze
          hypothesis -> hypothesize
          implement -> improve preview
          validate -> test_hypothesis
          distill -> integrate-compatible summary
        """
        local: Dict[str, Any] = {}

        def exploration(_: Dict[str, Any]) -> Dict[str, Any]:
            observation = self.observe()
            analysis = self.analyze(observation)
            local["observation"] = observation
            local["analysis"] = analysis
            return {"observation": observation, "analysis": analysis}

        def hypothesis_stage(_: Dict[str, Any]) -> Dict[str, Any]:
            hypothesis = self.hypothesize(local["analysis"])
            local["hypothesis"] = hypothesis
            return {"hypothesis": hypothesis}

        def implement(_: Dict[str, Any]) -> Dict[str, Any]:
            preview = {
                "task_id": self.task_id,
                "proposal": local["hypothesis"],
                "action": "prepare_improvement",
            }
            local["implement_preview"] = preview
            return preview

        def validate(_: Dict[str, Any]) -> Dict[str, Any]:
            validation = self.test_hypothesis(local["hypothesis"])
            local["validation"] = validation
            return validation

        def distill(_: Dict[str, Any]) -> Dict[str, Any]:
            if local["validation"].get("valid", False):
                improvement = self.improve(local["hypothesis"])
                self.integrate(improvement)
            else:
                improvement = ""
            return {
                "hypothesis": local["hypothesis"],
                "validation": local["validation"],
                "improvement": improvement,
            }

        workflow = build_research_workflow(
            {
                "exploration": exploration,
                "hypothesis": hypothesis_stage,
                "implement": implement,
                "validate": validate,
                "distill": distill,
            }
        )
        results = workflow.execute(context={})
        iteration = LoopIteration(
            iteration_id=f"WF-{len(self.iteration_history) + 1:04d}",
            phase=LoopPhase.INTEGRATE,
            observations=local.get("observation", {}),
            analysis=local.get("analysis"),
            hypothesis=local.get("hypothesis"),
            test_result=local.get("validation"),
            improvement=results.get("distill", {}).get("improvement"),
        )
        self.iteration_history.append(iteration)
        return {
            "task_id": self.task_id,
            "workflow_results": results,
            "workflow_summary": workflow.get_summary(),
            "iteration_id": iteration.iteration_id,
        }

    def _promote_short_term_patterns(self, experience: Dict[str, Any]) -> int:
        """Promote frequently repeated short-term patterns into long-term memory."""
        self.short_term_memory.store("experience_patterns", experience)
        window = self.short_term_memory.retrieve("experience_patterns") or []
        if not window:
            return 0

        counts: Dict[str, Dict[str, Any]] = {}
        for item in window:
            conditions = dict(item.get("conditions", {}))
            stable_conditions = {k: v for k, v in conditions.items() if k != "iteration"}
            key = json.dumps(stable_conditions, sort_keys=True, ensure_ascii=False)
            bucket = counts.setdefault(
                key,
                {"count": 0, "conditions": stable_conditions, "success": 0, "actions": set()},
            )
            bucket["count"] += 1
            outcome = item.get("outcome", {})
            if outcome.get("success"):
                bucket["success"] += 1
            if outcome.get("action"):
                bucket["actions"].add(outcome["action"])

        promoted = 0
        for key, bucket in counts.items():
            if bucket["count"] < self._promotion_threshold:
                continue
            long_term_key, existing = self._find_merge_candidate(bucket["conditions"])
            if existing:
                merged = self._merge_promoted_entry(existing, bucket)
                self.long_term_memory.store(long_term_key, merged)
                promoted += 1
                continue
            long_term_key = f"promoted::{self.task_id}::{abs(hash(key))}"
            self.long_term_memory.store(
                long_term_key,
                {
                    "task_id": self.task_id,
                    "conditions": bucket["conditions"],
                    "count": bucket["count"],
                    "success_rate": bucket["success"] / max(1, bucket["count"]),
                    "actions": sorted(bucket["actions"]),
                    "source": "short_term_promotion",
                    "merged_from": [],
                },
            )
            promoted += 1
        return promoted

    def _load_promoted_entries(self) -> List[tuple[str, Dict[str, Any]]]:
        storage = getattr(self.long_term_memory, "storage", None)
        if storage is None:
            return []
        filepath = getattr(storage, "filepath", None)
        if filepath is None:
            return []
        try:
            raw = json.loads(Path(filepath).read_text(encoding="utf-8"))
        except Exception:
            return []
        items = []
        for key, value in raw.items():
            if key.startswith(f"promoted::{self.task_id}::") and isinstance(value, dict):
                items.append((key, value))
        return items

    def _condition_similarity(self, left: Dict[str, Any], right: Dict[str, Any]) -> float:
        left_items = {f"{k}={v}" for k, v in left.items()}
        right_items = {f"{k}={v}" for k, v in right.items()}
        if not left_items and not right_items:
            return 1.0
        union = left_items | right_items
        if not union:
            return 0.0
        return len(left_items & right_items) / len(union)

    def _find_merge_candidate(self, conditions: Dict[str, Any]) -> tuple[Optional[str], Optional[Dict[str, Any]]]:
        best_key = None
        best_value = None
        best_score = 0.0
        for key, value in self._load_promoted_entries():
            score = self._condition_similarity(conditions, value.get("conditions", {}))
            if score >= self._merge_similarity_threshold and score > best_score:
                best_key = key
                best_value = value
                best_score = score
        return best_key, best_value

    def _merge_promoted_entry(self, existing: Dict[str, Any], bucket: Dict[str, Any]) -> Dict[str, Any]:
        prev_count = int(existing.get("count", 0))
        new_count = int(bucket["count"])
        total = max(1, prev_count + new_count)
        prev_success = float(existing.get("success_rate", 0.0)) * prev_count
        new_success = float(bucket["success"])
        actions = sorted(set(existing.get("actions", [])) | set(bucket["actions"]))
        merged_from = list(existing.get("merged_from", []))
        merged_from.append(
            {
                "conditions": bucket["conditions"],
                "count": new_count,
            }
        )
        return {
            **existing,
            "count": total,
            "success_rate": (prev_success + new_success) / total,
            "actions": actions,
            "source": "short_term_promotion_merged",
            "merged_from": merged_from[-10:],
        }
