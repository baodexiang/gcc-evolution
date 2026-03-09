"""
Experience Card Data Structures

Standardized format for knowledge representation and versioning.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Dict, Any, Optional
from enum import Enum


class CardType(Enum):
    """Classification of experience cards."""

    SIGNAL_PATTERN = "signal_pattern"
    TRADE_RULE = "trade_rule"
    RISK_MITIGATION = "risk_mitigation"
    PORTFOLIO_STRATEGY = "portfolio_strategy"
    MARKET_REGIME = "market_regime"
    CUSTOM = "custom"


@dataclass
class CardMetadata:
    """Metadata for experience cards."""

    created_by: str = "system"
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    author: str = "gcc-evo"
    license: str = "BUSL 1.1"
    tags: List[str] = field(default_factory=list)
    reliability_score: float = 0.5  # 0-1, increases with validation
    validation_count: int = 0
    source: str = "learning"  # learning / human / research


@dataclass
class CardVersion:
    """Version information for an experience card."""

    version: str  # e.g., "1.0.0"
    changelog: str
    released_at: str
    confidence: float
    validation_count: int
    improvements: List[str] = field(default_factory=list)


@dataclass
class ExperienceCard:
    """
    Standard experience card format.

    Represents a reusable piece of knowledge (pattern, rule, strategy).

    Example usage:
      >>> card = ExperienceCard(
      ...     card_id="CARD-MACD-DIV",
      ...     title="MACD Bullish Divergence Signal",
      ...     card_type=CardType.SIGNAL_PATTERN,
      ...     description="Price makes new low but MACD higher low",
      ...     conditions=[
      ...         "price_at_new_low == True",
      ...         "macd_at_higher_low == True",
      ...         "previous_signal == bearish"
      ...     ],
      ...     actions=["generate_buy_signal", "notify_trader"],
      ...     success_rate=0.72
      ... )
    """

    # Core identity
    card_id: str  # Unique identifier (e.g., CARD-0001)
    title: str
    card_type: CardType
    description: str

    # Knowledge content
    conditions: List[str]  # Prerequisites (AND logic)
    actions: List[str]  # Recommended actions
    success_rate: float  # Historical accuracy (0-1)
    edge_cases: List[Dict[str, Any]] = field(default_factory=list)

    # Quality metrics
    confidence: float = 0.5  # Creator confidence (0-1)
    sample_size: int = 0  # Number of observations
    standard_error: float = 0.0

    # Versioning
    version: str = "1.0.0"
    previous_versions: List[CardVersion] = field(default_factory=list)

    # Metadata
    metadata: CardMetadata = field(default_factory=CardMetadata)

    # Experimental flag (for Phase 1 features)
    experimental: bool = False
    phase: int = 1  # Phase for rollout: 1=observe, 2=enable, 3+=mature

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        data = asdict(self)
        data["card_type"] = self.card_type.value
        return data

    def validate(self, observation: Dict[str, Any]) -> bool:
        """
        Check if observation matches card conditions.

        Args:
            observation: Dictionary of observable variables

        Returns:
            True if all conditions are met
        """
        for condition in self.conditions:
            # Simple condition evaluation (production would use safe eval)
            parts = condition.split("==")
            if len(parts) != 2:
                continue

            key = parts[0].strip()
            value = parts[1].strip().strip("'\"")

            if key not in observation:
                return False

            obs_value = str(observation[key])
            if obs_value != value:
                return False

        return True

    def update_success_rate(self, successes: int, total: int) -> None:
        """Update success rate from new validation data."""
        if total > 0:
            new_rate = successes / total
            # Weighted average with historical data
            weight = total / (total + self.sample_size) if self.sample_size else 1.0
            self.success_rate = (
                weight * new_rate + (1 - weight) * self.success_rate
            )
            self.sample_size += total
            # Update confidence based on sample size
            self.confidence = min(1.0, self.sample_size / 100)

    def increment_validation_count(self) -> None:
        """Record that this card was validated."""
        self.metadata.validation_count += 1
        self.metadata.reliability_score = min(
            1.0, self.metadata.validation_count / 50
        )
        self.metadata.updated_at = datetime.utcnow().isoformat()

    def create_version(self, version: str, changelog: str, improvements: List[str] = None) -> None:
        """Create new version of this card."""
        new_version = CardVersion(
            version=version,
            changelog=changelog,
            released_at=datetime.utcnow().isoformat(),
            confidence=self.confidence,
            validation_count=self.metadata.validation_count,
            improvements=improvements or [],
        )
        self.previous_versions.append(new_version)
        self.version = version
        self.metadata.updated_at = datetime.utcnow().isoformat()
