"""
Multi-Model Ensemble and Comparison

Combines predictions from multiple models to improve robustness.
Community version: Dual-model comparison (reference + primary)
Enterprise version: Full ensemble with weighted aggregation
"""

from typing import Dict, List, Any, Optional, Tuple
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
import statistics


class EnsembleStrategy(Enum):
    """How to combine model predictions."""

    MAJORITY_VOTE = "majority_vote"  # Community: simple voting
    WEIGHTED_AVERAGE = "weighted_average"  # Weighted by confidence
    CONSENSUS = "consensus"  # All must agree


@dataclass
class ModelPrediction:
    """Single model prediction."""

    model_id: str
    signal: str  # BUY, SELL, HOLD
    confidence: float
    reasoning: str
    metadata: Dict[str, Any] = None


@dataclass
class EnsembleResult:
    """Combined ensemble decision."""

    consensus_signal: str
    agreement_level: float  # 0-1, how much models agree
    confidence: float
    predictions: List[ModelPrediction]
    variance: float  # How much predictions differ
    recommendation: str  # Final advice


class ModelComparator:
    """
    Compare predictions from different models.

    Identifies:
      • Disagreements (model divergence)
      • Outliers (extreme predictions)
      • Patterns in disagreement
    """

    def __init__(self):
        self.comparison_history = []

    def compare(self, predictions: List[ModelPrediction]) -> Dict[str, Any]:
        """
        Analyze disagreement between models.

        Returns:
            Analysis of model predictions
        """
        if len(predictions) < 2:
            return {"error": "Need at least 2 predictions to compare"}

        signals = [p.signal for p in predictions]
        confidences = [p.confidence for p in predictions]

        # Count signal votes
        signal_votes = {}
        for signal in signals:
            signal_votes[signal] = signal_votes.get(signal, 0) + 1

        # Calculate statistics
        confidence_mean = statistics.mean(confidences)
        confidence_stdev = (
            statistics.stdev(confidences) if len(confidences) > 1 else 0
        )

        # Identify disagreement
        max_votes = max(signal_votes.values())
        agreement_pct = max_votes / len(predictions)

        result = {
            "signal_votes": signal_votes,
            "dominant_signal": max(signal_votes, key=signal_votes.get),
            "agreement_level": agreement_pct,
            "confidence_mean": confidence_mean,
            "confidence_stdev": confidence_stdev,
            "disagreement": "HIGH" if agreement_pct < 0.7 else "LOW",
            "outliers": self._detect_outliers(predictions),
        }

        self.comparison_history.append(result)
        return result

    def _detect_outliers(self, predictions: List[ModelPrediction]) -> List[str]:
        """Identify outlier predictions."""
        outliers = []
        confidences = [p.confidence for p in predictions]

        if len(confidences) > 1:
            mean = statistics.mean(confidences)
            stdev = statistics.stdev(confidences)
            threshold = mean - 2 * stdev

            for pred in predictions:
                if pred.confidence < threshold:
                    outliers.append(pred.model_id)

        return outliers

    def explain_disagreement(self, predictions: List[ModelPrediction]) -> str:
        """Generate human-readable explanation of disagreement."""
        comparison = self.compare(predictions)

        if comparison.get("disagreement") == "LOW":
            return "Models agree strongly on decision"

        explanations = []
        for model_id in comparison.get("outliers", []):
            explanations.append(f"{model_id} is an outlier")

        if explanations:
            return "; ".join(explanations)
        else:
            return "Models have moderate disagreement"


class MultiModelEnsemble:
    """
    Ensemble of multiple prediction models.

    Community: Dual-model (reference pattern + primary logic)
    Enterprise: 3+ models with weighted combination

    Example:
      >>> ensemble = MultiModelEnsemble(strategy=EnsembleStrategy.MAJORITY_VOTE)
      >>> ensemble.add_prediction(ModelPrediction(...))
      >>> ensemble.add_prediction(ModelPrediction(...))
      >>> result = ensemble.aggregate()
    """

    def __init__(self, strategy: EnsembleStrategy = EnsembleStrategy.MAJORITY_VOTE):
        self.strategy = strategy
        self.predictions: List[ModelPrediction] = []
        self.model_weights: Dict[str, float] = {}
        self.comparator = ModelComparator()

    def add_prediction(
        self,
        model_id: str,
        signal: str,
        confidence: float,
        reasoning: str,
        weight: float = 1.0,
    ) -> None:
        """Add model prediction to ensemble."""
        pred = ModelPrediction(
            model_id=model_id,
            signal=signal,
            confidence=confidence,
            reasoning=reasoning,
        )
        self.predictions.append(pred)
        self.model_weights[model_id] = weight

    def aggregate(self) -> EnsembleResult:
        """Combine predictions using configured strategy."""
        if not self.predictions:
            return EnsembleResult(
                consensus_signal="HOLD",
                agreement_level=0.0,
                confidence=0.0,
                predictions=[],
                variance=0.0,
                recommendation="No predictions available",
            )

        if self.strategy == EnsembleStrategy.MAJORITY_VOTE:
            return self._aggregate_majority_vote()
        elif self.strategy == EnsembleStrategy.WEIGHTED_AVERAGE:
            return self._aggregate_weighted()
        elif self.strategy == EnsembleStrategy.CONSENSUS:
            return self._aggregate_consensus()

    def _aggregate_majority_vote(self) -> EnsembleResult:
        """Simple majority voting."""
        signal_votes = {}
        total_confidence = 0

        for pred in self.predictions:
            signal_votes[pred.signal] = signal_votes.get(pred.signal, 0) + 1
            total_confidence += pred.confidence

        consensus_signal = max(signal_votes, key=signal_votes.get)
        agreement = max(signal_votes.values()) / len(self.predictions)
        avg_confidence = total_confidence / len(self.predictions)

        comparison = self.comparator.compare(self.predictions)
        variance = comparison.get("confidence_stdev", 0)

        return EnsembleResult(
            consensus_signal=consensus_signal,
            agreement_level=agreement,
            confidence=avg_confidence,
            predictions=self.predictions,
            variance=variance,
            recommendation=f"{consensus_signal} with {agreement:.0%} agreement",
        )

    def _aggregate_weighted(self) -> EnsembleResult:
        """Weighted average by model confidence."""
        weighted_sum = 0
        weight_sum = 0
        signal_weighted_votes = {}

        for pred in self.predictions:
            model_weight = self.model_weights.get(pred.model_id, 1.0)
            effective_weight = pred.confidence * model_weight

            weighted_sum += effective_weight
            weight_sum += effective_weight

            if pred.signal not in signal_weighted_votes:
                signal_weighted_votes[pred.signal] = 0
            signal_weighted_votes[pred.signal] += effective_weight

        consensus_signal = max(signal_weighted_votes, key=signal_weighted_votes.get)
        agreement = signal_weighted_votes[consensus_signal] / weight_sum if weight_sum > 0 else 0
        avg_confidence = weighted_sum / len(self.predictions) if self.predictions else 0

        comparison = self.comparator.compare(self.predictions)
        variance = comparison.get("confidence_stdev", 0)

        return EnsembleResult(
            consensus_signal=consensus_signal,
            agreement_level=agreement,
            confidence=avg_confidence,
            predictions=self.predictions,
            variance=variance,
            recommendation=f"{consensus_signal} (weighted consensus)",
        )

    def _aggregate_consensus(self) -> EnsembleResult:
        """Require all models to agree."""
        signals = [p.signal for p in self.predictions]

        if len(set(signals)) == 1:
            # All agree
            signal = signals[0]
            confidence = statistics.mean([p.confidence for p in self.predictions])
            return EnsembleResult(
                consensus_signal=signal,
                agreement_level=1.0,
                confidence=confidence,
                predictions=self.predictions,
                variance=0.0,
                recommendation=f"Strong consensus: {signal}",
            )
        else:
            # Disagreement → HOLD
            return EnsembleResult(
                consensus_signal="HOLD",
                agreement_level=0.0,
                confidence=0.0,
                predictions=self.predictions,
                variance=1.0,
                recommendation="Models disagree, holding position",
            )

    def reset(self) -> None:
        """Clear predictions for next round."""
        self.predictions.clear()
