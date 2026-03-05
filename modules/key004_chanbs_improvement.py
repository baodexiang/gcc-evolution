#!/usr/bin/env python3
"""
modules/key004_chanbs_improvement.py
v1.0  KEY-004 ChanBS Improvement Utilities (opencode 2026-02-22)

Standalone utilities for ChanBS (Chan Theory Buy/Sell Points) signal quality
analysis and policy management. No integration with main program files.

Provides:
  - ChanBSPolicy: Configuration dataclass for ChanBS parameters
  - ChanBSSignalSample: Individual signal record with metadata
  - ChanBSQualityMetrics: Aggregated quality statistics
  - infer_market_tier: Classify symbol as stock/crypto based on name
  - parse_chanbs_section_from_symbol_yaml: Light YAML parser for plugin.chan_bs
  - load_symbol_chanbs_policy: Load policy from .GCC/params/<SYMBOL>.yaml
  - should_accept_signal: Decision logic for signal acceptance
  - evaluate_signal_quality: Compute quality metrics from samples
  - build_three_step_plan: Generate improvement recommendations
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from typing import Dict, List, Literal, Optional, Tuple


__all__ = [
    "ChanBSPolicy",
    "ChanBSSignalSample",
    "ChanBSQualityMetrics",
    "MarketTier",
    "infer_market_tier",
    "parse_chanbs_section_from_symbol_yaml",
    "load_symbol_chanbs_policy",
    "should_accept_signal",
    "evaluate_signal_quality",
    "build_three_step_plan",
]


# ── Type Definitions ─────────────────────────────────────────────────────────

MarketTier = Literal["STOCK", "CRYPTO"]


# ── Data Structures ──────────────────────────────────────────────────────────

@dataclass
class ChanBSPolicy:
    """ChanBS configuration policy for a symbol."""
    symbol: str
    enabled: bool = True
    weight: float = 0.6  # 0.0-1.0
    min_confidence: float = 0.6  # 0.0-1.0
    note: str = ""
    market_tier: MarketTier = "STOCK"
    version: str = "key004-v1"


@dataclass
class ChanBSSignalSample:
    """Individual ChanBS signal record."""
    timestamp: float  # Unix timestamp
    symbol: str
    signal_type: Literal["BUY", "SELL"]
    confidence: float  # 0.0-1.0
    price: float
    market_tier: MarketTier
    accepted: bool  # Whether signal passed policy gate
    pnl_pct: Optional[float] = None  # Realized P&L if closed
    mfe_pct: Optional[float] = None  # Max Favorable Excursion
    mae_pct: Optional[float] = None  # Max Adverse Excursion
    notes: str = ""


@dataclass
class ChanBSQualityMetrics:
    """Aggregated quality statistics for ChanBS signals."""
    symbol: str
    market_tier: MarketTier
    total_signals: int = 0
    accepted_signals: int = 0
    acceptance_rate: float = 0.0  # accepted / total
    
    # By signal type
    buy_signals: int = 0
    sell_signals: int = 0
    buy_acceptance_rate: float = 0.0
    sell_acceptance_rate: float = 0.0
    
    # Quality metrics
    avg_confidence: float = 0.0
    median_confidence: float = 0.0
    confidence_std: float = 0.0
    
    # P&L analysis (closed signals only)
    closed_signals: int = 0
    win_rate: float = 0.0  # Signals with pnl_pct > 0
    avg_pnl_pct: float = 0.0
    median_pnl_pct: float = 0.0
    
    # Risk metrics
    avg_mfe_pct: float = 0.0
    avg_mae_pct: float = 0.0
    mfe_mae_ratio: float = 0.0  # avg_mfe / avg_mae
    
    # Recommendations
    recommended_weight: float = 0.6
    recommended_min_confidence: float = 0.6
    recommendation_reason: str = ""
    
    version: str = "key004-metrics-v1"


# ── Market Tier Inference ────────────────────────────────────────────────────

def infer_market_tier(symbol: str) -> MarketTier:
    """
    Classify symbol as STOCK or CRYPTO based on naming convention.
    
    Args:
        symbol: Trading symbol (e.g., "TSLA", "BTCUSDC")
    
    Returns:
        MarketTier: "STOCK" or "CRYPTO"
    """
    symbol_upper = symbol.upper()
    
    # Crypto indicators
    crypto_keywords = ["BTC", "ETH", "SOL", "ZEC", "USDC", "USDT"]
    if any(kw in symbol_upper for kw in crypto_keywords):
        return "CRYPTO"
    
    # Default to STOCK
    return "STOCK"


# ── YAML Parsing ─────────────────────────────────────────────────────────────

def parse_chanbs_section_from_symbol_yaml(yaml_path: str) -> Optional[Dict]:
    """
    Light YAML parser to extract plugin.chan_bs section.
    
    Reads .GCC/params/<SYMBOL>.yaml and extracts chan_bs configuration.
    Does NOT use full YAML library to keep dependencies minimal.
    
    Args:
        yaml_path: Path to symbol YAML file
    
    Returns:
        Dict with keys: enabled, weight, min_confidence, note
        None if file not found or section missing
    """
    if not os.path.exists(yaml_path):
        return None
    
    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return None
    
    # Find "chan_bs:" line
    chan_bs_idx = None
    for i, line in enumerate(lines):
        if "chan_bs:" in line:
            chan_bs_idx = i
            break
    
    if chan_bs_idx is None:
        return None
    
    result = {}
    # Parse indented lines after chan_bs:
    base_indent = len(lines[chan_bs_idx]) - len(lines[chan_bs_idx].lstrip())
    
    for i in range(chan_bs_idx + 1, len(lines)):
        line = lines[i]
        
        # Stop if we hit a non-indented line or next section
        if line.strip() and not line.startswith(" " * (base_indent + 2)):
            break
        
        # Parse key: value pairs
        if ":" in line:
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()
            
            # Remove inline comments
            if "#" in value:
                value = value.split("#")[0].strip()
            
            # Parse value
            if value.lower() in ("true", "false"):
                result[key] = value.lower() == "true"
            elif value.replace(".", "", 1).isdigit():
                result[key] = float(value) if "." in value else int(value)
            else:
                # String value (remove quotes if present)
                result[key] = value.strip('"\'')
    
    return result if result else None


def load_symbol_chanbs_policy(
    symbol: str,
    params_dir: str = ".GCC/params"
) -> ChanBSPolicy:
    """
    Load ChanBS policy from .GCC/params/<SYMBOL>.yaml.
    
    Args:
        symbol: Trading symbol
        params_dir: Directory containing symbol YAML files
    
    Returns:
        ChanBSPolicy with loaded values or defaults
    """
    yaml_path = os.path.join(params_dir, f"{symbol}.yaml")
    
    # Default policy
    policy = ChanBSPolicy(
        symbol=symbol,
        market_tier=infer_market_tier(symbol)
    )
    
    # Try to load from YAML
    chan_bs_section = parse_chanbs_section_from_symbol_yaml(yaml_path)
    if chan_bs_section:
        if "enabled" in chan_bs_section:
            policy.enabled = chan_bs_section["enabled"]
        if "weight" in chan_bs_section:
            policy.weight = float(chan_bs_section["weight"])
        if "min_confidence" in chan_bs_section:
            policy.min_confidence = float(chan_bs_section["min_confidence"])
        if "note" in chan_bs_section:
            policy.note = str(chan_bs_section["note"])
    
    return policy


# ── Signal Acceptance Logic ──────────────────────────────────────────────────

def should_accept_signal(
    signal: ChanBSSignalSample,
    policy: ChanBSPolicy
) -> Tuple[bool, str]:
    """
    Determine if a ChanBS signal should be accepted based on policy.
    
    Args:
        signal: Signal to evaluate
        policy: ChanBS policy for the symbol
    
    Returns:
        Tuple of (accepted: bool, reason: str)
    """
    if not policy.enabled:
        return False, "ChanBS disabled for symbol"
    
    if signal.confidence < policy.min_confidence:
        return False, f"Confidence {signal.confidence:.2f} < threshold {policy.min_confidence:.2f}"
    
    return True, "Passed policy gate"


# ── Quality Evaluation ───────────────────────────────────────────────────────

def evaluate_signal_quality(
    samples: List[ChanBSSignalSample],
    symbol: str,
    market_tier: MarketTier
) -> ChanBSQualityMetrics:
    """
    Compute quality metrics from signal samples.
    
    Args:
        samples: List of ChanBSSignalSample records
        symbol: Trading symbol
        market_tier: STOCK or CRYPTO
    
    Returns:
        ChanBSQualityMetrics with computed statistics
    """
    metrics = ChanBSQualityMetrics(
        symbol=symbol,
        market_tier=market_tier
    )
    
    if not samples:
        return metrics
    
    # Basic counts
    metrics.total_signals = len(samples)
    metrics.accepted_signals = sum(1 for s in samples if s.accepted)
    metrics.acceptance_rate = (
        metrics.accepted_signals / metrics.total_signals
        if metrics.total_signals > 0 else 0.0
    )
    
    # By signal type
    buy_samples = [s for s in samples if s.signal_type == "BUY"]
    sell_samples = [s for s in samples if s.signal_type == "SELL"]
    
    metrics.buy_signals = len(buy_samples)
    metrics.sell_signals = len(sell_samples)
    
    if buy_samples:
        metrics.buy_acceptance_rate = (
            sum(1 for s in buy_samples if s.accepted) / len(buy_samples)
        )
    if sell_samples:
        metrics.sell_acceptance_rate = (
            sum(1 for s in sell_samples if s.accepted) / len(sell_samples)
        )
    
    # Confidence statistics
    confidences = [s.confidence for s in samples]
    if confidences:
        metrics.avg_confidence = sum(confidences) / len(confidences)
        sorted_conf = sorted(confidences)
        metrics.median_confidence = (
            sorted_conf[len(sorted_conf) // 2]
            if len(sorted_conf) % 2 == 1
            else (sorted_conf[len(sorted_conf) // 2 - 1] + sorted_conf[len(sorted_conf) // 2]) / 2
        )
        
        # Standard deviation
        if len(confidences) > 1:
            variance = sum((c - metrics.avg_confidence) ** 2 for c in confidences) / len(confidences)
            metrics.confidence_std = variance ** 0.5
    
    # P&L analysis
    closed_samples = [s for s in samples if s.pnl_pct is not None]
    metrics.closed_signals = len(closed_samples)
    
    if closed_samples:
        wins = sum(1 for s in closed_samples if (s.pnl_pct is not None and s.pnl_pct > 0))
        metrics.win_rate = wins / len(closed_samples)

        pnls = [float(s.pnl_pct) for s in closed_samples if s.pnl_pct is not None]
        metrics.avg_pnl_pct = sum(pnls) / len(pnls)

        sorted_pnl = sorted(pnls)
        metrics.median_pnl_pct = (
            sorted_pnl[len(sorted_pnl) // 2]
            if len(sorted_pnl) % 2 == 1
            else (sorted_pnl[len(sorted_pnl) // 2 - 1] + sorted_pnl[len(sorted_pnl) // 2]) / 2
        )
    
    # Risk metrics
    mfe_values = [float(s.mfe_pct) for s in samples if s.mfe_pct is not None]
    mae_values = [float(s.mae_pct) for s in samples if s.mae_pct is not None]
    
    if mfe_values:
        metrics.avg_mfe_pct = sum(mfe_values) / len(mfe_values)
    if mae_values:
        metrics.avg_mae_pct = sum(mae_values) / len(mae_values)
    
    if metrics.avg_mae_pct > 0:
        metrics.mfe_mae_ratio = metrics.avg_mfe_pct / metrics.avg_mae_pct
    
    return metrics


# ── Improvement Recommendations ──────────────────────────────────────────────

def build_three_step_plan(
    metrics: ChanBSQualityMetrics,
    current_policy: ChanBSPolicy
) -> Dict:
    """
    Generate three-step improvement plan based on quality metrics.
    
    Returns:
        Dict with keys:
          - step1_diagnosis: Current state analysis
          - step2_recommendation: Suggested parameter changes
          - step3_validation: How to verify improvement
    """
    plan = {
        "symbol": metrics.symbol,
        "market_tier": metrics.market_tier,
        "step1_diagnosis": {},
        "step2_recommendation": {},
        "step3_validation": {},
    }
    
    # Step 1: Diagnosis
    diagnosis = plan["step1_diagnosis"]
    diagnosis["total_signals"] = metrics.total_signals
    diagnosis["acceptance_rate"] = f"{metrics.acceptance_rate:.1%}"
    diagnosis["avg_confidence"] = f"{metrics.avg_confidence:.2f}"
    diagnosis["win_rate"] = f"{metrics.win_rate:.1%}" if metrics.closed_signals > 0 else "N/A"
    diagnosis["mfe_mae_ratio"] = f"{metrics.mfe_mae_ratio:.2f}" if metrics.mfe_mae_ratio > 0 else "N/A"
    
    # Identify issues
    issues = []
    if metrics.total_signals < 10:
        issues.append("Insufficient sample size (< 10 signals)")
    if metrics.acceptance_rate < 0.3:
        issues.append("Low acceptance rate (< 30%)")
    if metrics.win_rate < 0.4 and metrics.closed_signals > 0:
        issues.append("Low win rate (< 40%)")
    if metrics.avg_confidence < 0.5:
        issues.append("Low average confidence (< 0.5)")
    
    diagnosis["issues"] = issues
    
    # Step 2: Recommendation
    recommendation = plan["step2_recommendation"]
    recommendation["current_weight"] = current_policy.weight
    recommendation["current_min_confidence"] = current_policy.min_confidence
    
    # Recommend weight adjustment
    if metrics.win_rate > 0.6 and metrics.acceptance_rate > 0.5:
        recommended_weight = min(1.0, current_policy.weight + 0.1)
        recommendation["suggested_weight"] = recommended_weight
        recommendation["weight_reason"] = "Strong performance, increase weight"
    elif metrics.win_rate < 0.4 or metrics.acceptance_rate < 0.3:
        recommended_weight = max(0.0, current_policy.weight - 0.1)
        recommendation["suggested_weight"] = recommended_weight
        recommendation["weight_reason"] = "Weak performance, decrease weight"
    else:
        recommendation["suggested_weight"] = current_policy.weight
        recommendation["weight_reason"] = "Maintain current weight"
    
    # Recommend confidence threshold adjustment
    if metrics.avg_confidence > 0.7:
        recommended_conf = min(0.9, current_policy.min_confidence + 0.05)
        recommendation["suggested_min_confidence"] = recommended_conf
        recommendation["confidence_reason"] = "High avg confidence, raise threshold"
    elif metrics.avg_confidence < 0.5:
        recommended_conf = max(0.3, current_policy.min_confidence - 0.05)
        recommendation["suggested_min_confidence"] = recommended_conf
        recommendation["confidence_reason"] = "Low avg confidence, lower threshold"
    else:
        recommendation["suggested_min_confidence"] = current_policy.min_confidence
        recommendation["confidence_reason"] = "Maintain current threshold"
    
    # Step 3: Validation
    validation = plan["step3_validation"]
    validation["metrics_to_track"] = [
        "acceptance_rate",
        "win_rate",
        "avg_pnl_pct",
        "mfe_mae_ratio"
    ]
    validation["success_criteria"] = {
        "acceptance_rate": "> 40%",
        "win_rate": "> 50%",
        "avg_pnl_pct": "> 0.5%",
        "mfe_mae_ratio": "> 1.5"
    }
    validation["sample_size_required"] = 20
    validation["observation_period_days"] = 7
    
    return plan


# ── Utility Functions ────────────────────────────────────────────────────────

def export_metrics_to_json(
    metrics: ChanBSQualityMetrics,
    output_path: str
) -> None:
    """Export metrics to JSON file."""
    data = asdict(metrics)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def export_samples_to_jsonl(
    samples: List[ChanBSSignalSample],
    output_path: str
) -> None:
    """Export signal samples to JSONL file."""
    with open(output_path, "w", encoding="utf-8") as f:
        for sample in samples:
            line = json.dumps(asdict(sample), ensure_ascii=False)
            f.write(line + "\n")


# ── Main (for testing) ───────────────────────────────────────────────────────

if __name__ == "__main__":
    # Example usage
    print("KEY-004 ChanBS Improvement Module")
    print("=" * 60)
    
    # Test market tier inference
    print("\n1. Market Tier Inference:")
    for symbol in ["TSLA", "BTCUSDC", "ETHUSDC", "AMD"]:
        tier = infer_market_tier(symbol)
        print(f"  {symbol:12} -> {tier}")
    
    # Test YAML parsing
    print("\n2. YAML Parsing:")
    policy = load_symbol_chanbs_policy("AMD")
    print(f"  Symbol: {policy.symbol}")
    print(f"  Enabled: {policy.enabled}")
    print(f"  Weight: {policy.weight}")
    print(f"  Min Confidence: {policy.min_confidence}")
    print(f"  Note: {policy.note}")
    
    # Test signal acceptance
    print("\n3. Signal Acceptance:")
    sample = ChanBSSignalSample(
        timestamp=1708608000.0,
        symbol="AMD",
        signal_type="BUY",
        confidence=0.75,
        price=150.0,
        market_tier="STOCK",
        accepted=False
    )
    accepted, reason = should_accept_signal(sample, policy)
    print(f"  Signal: {sample.signal_type} @ {sample.price}")
    print(f"  Confidence: {sample.confidence}")
    print(f"  Accepted: {accepted}")
    print(f"  Reason: {reason}")
    
    # Test quality evaluation
    print("\n4. Quality Metrics:")
    samples = [
        ChanBSSignalSample(
            timestamp=1708608000.0 + i * 3600,
            symbol="AMD",
            signal_type="BUY" if i % 2 == 0 else "SELL",
            confidence=0.6 + (i % 5) * 0.05,
            price=150.0 + i,
            market_tier="STOCK",
            accepted=True,
            pnl_pct=0.5 + (i % 3) * 0.3
        )
        for i in range(10)
    ]
    
    metrics = evaluate_signal_quality(samples, "AMD", "STOCK")
    print(f"  Total Signals: {metrics.total_signals}")
    print(f"  Acceptance Rate: {metrics.acceptance_rate:.1%}")
    print(f"  Avg Confidence: {metrics.avg_confidence:.2f}")
    print(f"  Win Rate: {metrics.win_rate:.1%}")
    
    # Test improvement plan
    print("\n5. Improvement Plan:")
    plan = build_three_step_plan(metrics, policy)
    print(f"  Step 1 Issues: {plan['step1_diagnosis']['issues']}")
    print(f"  Step 2 Weight: {plan['step2_recommendation']['suggested_weight']}")
    print(f"  Step 3 Sample Size: {plan['step3_validation']['sample_size_required']}")
    
    print("\n" + "=" * 60)
    print("Module test complete.")
