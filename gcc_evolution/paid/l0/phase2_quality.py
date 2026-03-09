"""Canonical paid L0 program: Phase 2 quality validation boundary."""
from ..common import PaidBoundary

PHASE2_QUALITY = PaidBoundary("L0", "Paid", ("quality_report", "quality_data", "effective source validation"), "Phase 2 quality validation is paid.")

__all__ = ["PHASE2_QUALITY"]
