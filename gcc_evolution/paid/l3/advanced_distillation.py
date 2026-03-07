"""Canonical paid L3 program: advanced distillation boundary."""
from ..common import PaidBoundary

L3_ADVANCED = PaidBoundary("L3", "Paid", ("invalid source exclusion", "cross-session distillation", "quality-aware compression"))

__all__ = ["L3_ADVANCED"]
