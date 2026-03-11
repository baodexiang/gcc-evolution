"""Community fallbacks for walk-forward analysis helpers."""

from . import unavailable_result


def WalkForwardAnalyzer(*args, **kwargs):
    """Walk-forward optimization for out-of-sample testing."""
    return unavailable_result(
        "WalkForwardAnalyzer",
        tier="Evolve",
        fallback="Using simple train/test split instead",
        value=None,
    )


def walk_forward_backtest(*args, **kwargs):
    """Execute walk-forward backtest with retraining."""
    return unavailable_result(
        "walk_forward_backtest",
        tier="Evolve",
        fallback="Using static backtest instead",
        value={"mode": "holdout", "trades": [], "metrics": {}},
    )


def out_of_sample_metrics(*args, **kwargs):
    """Calculate out-of-sample performance metrics."""
    return unavailable_result(
        "out_of_sample_metrics",
        tier="Pro",
        fallback="No out-of-sample metrics available",
        value={},
    )


__all__ = ["WalkForwardAnalyzer", "walk_forward_backtest", "out_of_sample_metrics"]
