"""Canonical paid L1 program: advanced memory."""
from ...L1_memory.memory_tiers import ArchivalMemory, MemoryStack
from ..common import PaidBoundary

L1_ADVANCED = PaidBoundary("L1", "Paid", ("archival memory", "memory stack", "higher-capacity memory workflows"))

__all__ = ["ArchivalMemory", "MemoryStack", "L1_ADVANCED"]
