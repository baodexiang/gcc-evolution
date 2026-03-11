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

    def observe(self) -> Dict[str, Any]:
        observation = {
            "task_id": self.task_id,
            "iteration": len(self.iteration_history) + 1,
            "timestamp": datetime.utcnow().isoformat(),
        }
        self.sensory_memory.store("current_observation", observation)
        self.short_term_memory.store("observations", observation)
        return observation

    def analyze(self, observations: Dict[str, Any]) -> Dict[str, Any]:
        documents = [
            {
                "id": f"obs-{observations['iteration']}",
                "text": json.dumps(observations, ensure_ascii=False),
                "created_at": observations["timestamp"],
            }
        ]
        self.retriever.index(documents)
        retrieval = self.retriever.retrieve(self.task_id, top_k=3)
        return {
            "query": self.task_id,
            "matches": retrieval,
            "match_count": len(retrieval),
        }

    def hypothesize(self, analysis: Dict[str, Any]) -> str:
        match_count = analysis.get("match_count", 0)
        return (
            f"Iteration {len(self.iteration_history) + 1}: "
            f"continue baseline learning with {match_count} retrieved context items"
        )

    def test_hypothesis(self, hypothesis: str) -> Dict[str, Any]:
        decision = {
            "signal": "IMPROVE",
            "action": "OPTIMIZE",
            "confidence": 0.8,
            "conditions": ["+baseline_learning"],
            "reasoning": hypothesis,
        }
        validation = self.skeptic.validate(decision, context={})
        return {
            "valid": validation.is_valid,
            "confidence": validation.confidence,
            "soft_score": getattr(validation, "soft_score", validation.confidence),
            "issues": validation.issues,
            "suggestions": validation.suggestions,
            "decision": decision,
        }

    def improve(self, hypothesis: str) -> str:
        iteration = len(self.iteration_history) + 1
        self.distiller.add_experience(
            {
                "conditions": {"task": self.task_id, "iteration": iteration},
                "outcome": {"success": True, "action": "baseline"},
            }
        )
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
        generated = len(cards)
        return f"Stored {generated} distilled card(s) for {self.task_id}"

    def integrate(self, improvement: str) -> None:
        audit_dir = self.state_dir / "audit"
        audit_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "task_id": self.task_id,
            "iteration": len(self.iteration_history) + 1,
            "improvement": improvement,
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
