"""
Storage Backends for Memory Persistence

Pluggable storage layer for long-term memory serialization.
"""

import json
import sqlite3
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, List, Optional


class MemoryStorage(ABC):
    """Abstract storage interface."""

    @abstractmethod
    def write(self, key: str, value: Any) -> None:
        """Persist a key-value pair."""
        pass

    @abstractmethod
    def read(self, key: str) -> Optional[Any]:
        """Retrieve a stored value."""
        pass

    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete a stored value."""
        pass

    @abstractmethod
    def search(self, pattern: str) -> List[Any]:
        """Search by pattern."""
        pass


class JSONStorage(MemoryStorage):
    """
    File-based JSON storage.

    Example:
      >>> storage = JSONStorage("memory.json")
      >>> storage.write("model_state", {"version": 5.295})
      >>> storage.read("model_state")
      {'version': 5.295}
    """

    def __init__(self, filepath: str):
        self.filepath = Path(filepath)
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_file()

    def _ensure_file(self) -> None:
        """Create file if not exists."""
        if not self.filepath.exists():
            self.filepath.write_text("{}")

    def write(self, key: str, value: Any) -> None:
        """Write key-value to JSON file."""
        data = json.loads(self.filepath.read_text())
        data[key] = value
        self.filepath.write_text(json.dumps(data, indent=2))

    def read(self, key: str) -> Optional[Any]:
        """Read value from JSON file."""
        data = json.loads(self.filepath.read_text())
        return data.get(key)

    def delete(self, key: str) -> None:
        """Delete key from JSON file."""
        data = json.loads(self.filepath.read_text())
        data.pop(key, None)
        self.filepath.write_text(json.dumps(data, indent=2))

    def search(self, pattern: str) -> List[Any]:
        """Find keys matching pattern."""
        data = json.loads(self.filepath.read_text())
        return [v for k, v in data.items() if pattern.lower() in k.lower()]


class SQLiteStorage(MemoryStorage):
    """
    SQLite-backed storage for structured memory.

    Example:
      >>> storage = SQLiteStorage("memory.db")
      >>> storage.write("training_run", {"epoch": 50, "loss": 0.023})
    """

    def __init__(self, filepath: str):
        self.filepath = filepath
        self._init_schema()

    def _init_schema(self) -> None:
        """Create table if not exists."""
        with sqlite3.connect(self.filepath) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def write(self, key: str, value: Any) -> None:
        """Store value as JSON."""
        json_value = json.dumps(value)
        with sqlite3.connect(self.filepath) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO memory (key, value) VALUES (?, ?)",
                (key, json_value),
            )
            conn.commit()

    def read(self, key: str) -> Optional[Any]:
        """Retrieve and deserialize value."""
        with sqlite3.connect(self.filepath) as conn:
            cursor = conn.execute("SELECT value FROM memory WHERE key = ?", (key,))
            row = cursor.fetchone()
            return json.loads(row[0]) if row else None

    def delete(self, key: str) -> None:
        """Remove key from database."""
        with sqlite3.connect(self.filepath) as conn:
            conn.execute("DELETE FROM memory WHERE key = ?", (key,))
            conn.commit()

    def search(self, pattern: str) -> List[Any]:
        """Search keys by pattern."""
        with sqlite3.connect(self.filepath) as conn:
            cursor = conn.execute(
                "SELECT value FROM memory WHERE key LIKE ?",
                (f"%{pattern}%",),
            )
            return [json.loads(row[0]) for row in cursor.fetchall()]
