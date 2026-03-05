"""
Memory Tier Abstractions

Three-level memory architecture:
  • Sensory: Real-time signal processing (current observation)
  • Short-term: Sliding window history (recent N steps)
  • Long-term: Persistent knowledge base (historical patterns)
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, List, Dict, Optional


class MemoryTier(ABC):
    """Abstract base for memory tier."""

    @abstractmethod
    def store(self, key: str, value: Any, metadata: Dict[str, Any] = None) -> None:
        """Store value in this memory tier."""
        pass

    @abstractmethod
    def retrieve(self, key: str) -> Optional[Any]:
        """Retrieve value from this memory tier."""
        pass

    @abstractmethod
    def list_keys(self) -> List[str]:
        """List all stored keys."""
        pass


class SensoryMemory(MemoryTier):
    """
    Real-time signal processing layer.

    Characteristics:
      • Latest observation only (no history)
      • Updated every step with current state
      • Used for immediate signal detection

    Example:
      >>> sensory = SensoryMemory()
      >>> sensory.store("price", 45230.50)
      >>> sensory.retrieve("price")
      45230.50
    """

    def __init__(self):
        self._current_state: Dict[str, Any] = {}
        self._last_update: Dict[str, datetime] = {}

    def store(self, key: str, value: Any, metadata: Dict[str, Any] = None) -> None:
        """Store latest value, overwriting previous."""
        self._current_state[key] = value
        self._last_update[key] = datetime.utcnow()

    def retrieve(self, key: str) -> Optional[Any]:
        """Get current value if exists."""
        return self._current_state.get(key)

    def list_keys(self) -> List[str]:
        """List all tracked signals."""
        return list(self._current_state.keys())

    def get_all(self) -> Dict[str, Any]:
        """Snapshot of all current state."""
        return dict(self._current_state)


class ShortTermMemory(MemoryTier):
    """
    Sliding window history layer.

    Characteristics:
      • Keeps last N observations
      • Useful for trend detection, pattern matching
      • Fixed capacity with FIFO eviction

    Example:
      >>> stm = ShortTermMemory(window_size=10)
      >>> for i in range(15):
      ...     stm.store("price", 100 + i)
      >>> len(stm.retrieve("price"))  # Only 10 latest
      10
    """

    def __init__(self, window_size: int = 100):
        self.window_size = window_size
        self._windows: Dict[str, List[Any]] = {}

    def store(self, key: str, value: Any, metadata: Dict[str, Any] = None) -> None:
        """Add value to sliding window."""
        if key not in self._windows:
            self._windows[key] = []
        self._windows[key].append(value)
        if len(self._windows[key]) > self.window_size:
            self._windows[key].pop(0)

    def retrieve(self, key: str) -> Optional[List[Any]]:
        """Get all values in window."""
        return self._windows.get(key)

    def list_keys(self) -> List[str]:
        """List all tracked keys."""
        return list(self._windows.keys())

    def get_latest(self, key: str) -> Optional[Any]:
        """Get most recent value."""
        window = self._windows.get(key)
        return window[-1] if window else None


class LongTermMemory(MemoryTier):
    """
    Persistent knowledge base layer.

    Characteristics:
      • Unbounded storage (persisted to disk)
      • Historical patterns, learned rules
      • Indexed for fast retrieval

    Example:
      >>> ltm = LongTermMemory(storage=JSONStorage("kb.json"))
      >>> ltm.store("pattern_divergence", {"type": "macd", "accuracy": 0.75})
      >>> pattern = ltm.retrieve("pattern_divergence")
    """

    def __init__(self, storage=None):
        self.storage = storage  # Pluggable storage backend
        self._index: Dict[str, List[str]] = {}  # Key -> value_ids

    def store(self, key: str, value: Any, metadata: Dict[str, Any] = None) -> None:
        """Persist value to long-term storage."""
        if self.storage:
            self.storage.write(key, value)
        if key not in self._index:
            self._index[key] = []

    def retrieve(self, key: str) -> Optional[Any]:
        """Load value from long-term storage."""
        if self.storage:
            return self.storage.read(key)
        return None

    def list_keys(self) -> List[str]:
        """List all stored keys."""
        return list(self._index.keys())

    def query(self, pattern: str) -> List[Any]:
        """Search by pattern (requires storage support)."""
        if self.storage:
            return self.storage.search(pattern)
        return []
