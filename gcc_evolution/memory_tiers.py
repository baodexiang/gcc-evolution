"""
GCC v4.8 — 3-Tier Memory System
灵感来源：LightMem (ZJU 2025) 三层记忆 + 睡眠巩固机制

三层结构：
  Sensory  (即时) → 当前 session 的原始观察，过期自动丢弃
  Short-term (短期) → 近期 session 的关键发现，improvements/{KEY}/card_*.md
  Long-term (长期) → 经过验证的高置信度知识，自动从 short-term 晋升

Auto-consolidation (睡眠巩固)：
  触发条件：手动 / 每 N 个 session / card 数量超阈值
  执行内容：
    1. 重复合并（word overlap > 70%）
    2. 低置信淘汰（< 30% 且无 downstream）
    3. 短期→长期晋升（confidence > 80% + use_count > 3）

使用方式：
  tiers = MemoryTiers()
  tiers.observe("ATR=10 performed 20% better in choppy SPY")  # Sensory
  tiers.promote_sensory()     # Sensory → Short-term (auto-card)
  tiers.consolidate()         # Short-term → Long-term (auto)
  gcc-evo consolidate         # CLI trigger
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M")


# ── Data Structures ──

@dataclass
class SensoryItem:
    """Raw observation, not yet distilled into a card."""
    id: str = ""
    timestamp: str = field(default_factory=_now)
    session_id: str = ""
    key: str = ""
    observation: str = ""       # Raw text
    source: str = ""            # "git_diff", "agent_note", "metric_change"
    promoted: bool = False      # Promoted to short-term?
    # v4.97 LightMem: 话题分组，避免跨资产合并 (#11 LightMem ZJU 2025)
    topic: str = ""             # e.g. "equity_trading", "crypto", "gcc", "options"


@dataclass
class ConsolidationResult:
    """Result of a consolidation cycle."""
    timestamp: str = field(default_factory=_now)
    merged: int = 0             # Cards merged (duplicates)
    deprecated: int = 0         # Cards deprecated (low quality)
    promoted: int = 0           # Cards promoted (short→long)
    total_before: int = 0
    total_after: int = 0
    details: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "merged": self.merged,
            "deprecated": self.deprecated,
            "promoted": self.promoted,
            "total_before": self.total_before,
            "total_after": self.total_after,
            "details": self.details,
        }


# ── Memory Tiers Engine ──

class MemoryTiers:
    """
    3-tier memory system for GCC.

    Tier 1 (Sensory): .gcc/sensory/ — raw observations, ephemeral
    Tier 2 (Short-term): .gcc/improvements/{KEY}/card_*.md — recent findings
    Tier 3 (Long-term): cards with status=validated + high confidence
    """

    def __init__(self, gcc_dir: str | None = None,
                 max_sensory_sessions: int = 5,
                 consolidation_threshold: int = 50,
                 promote_confidence: float = 0.8,
                 promote_use_count: int = 3,
                 deprecate_confidence: float = 0.3,
                 merge_overlap: float = 0.7):
        self._gcc_dir = self._find_gcc_dir(gcc_dir)
        self._sensory_dir = self._gcc_dir / "sensory"
        self._sensory_dir.mkdir(parents=True, exist_ok=True)
        self._max_sensory_sessions = max_sensory_sessions
        self._consolidation_threshold = consolidation_threshold
        self._promote_confidence = promote_confidence
        self._promote_use_count = promote_use_count
        self._deprecate_confidence = deprecate_confidence
        self._merge_overlap = merge_overlap

    def _find_gcc_dir(self, hint: str | None = None) -> Path:
        if hint:
            return Path(hint)
        for name in [".gcc", ".GCC"]:
            p = Path(name)
            if p.exists():
                return p
        return Path(".gcc")

    # ═══ Tier 1: Sensory ═══

    def observe(self, observation: str, key: str = "",
                session_id: str = "", source: str = "agent_note",
                topic: str = "") -> SensoryItem:
        """
        Record a raw observation in the sensory tier.
        These are ephemeral — auto-cleaned after N sessions.

        Args:
            topic: v4.97 LightMem 话题标签 (#11 LightMem ZJU 2025)
                   例如 "equity_trading" / "crypto" / "gcc" / "options"
                   相同 topic 的卡片才参与合并，跨 topic 隔离。
        """
        item = SensoryItem(
            id=f"obs_{datetime.now(timezone.utc).strftime('%H%M%S')}",
            session_id=session_id,
            key=key,
            observation=observation,
            source=source,
            topic=topic,
        )

        # Save to sensory dir
        session_dir = self._sensory_dir / (session_id or "current")
        session_dir.mkdir(parents=True, exist_ok=True)

        obs_file = session_dir / f"{item.id}.json"
        obs_file.write_text(json.dumps({
            "id": item.id,
            "timestamp": item.timestamp,
            "session_id": item.session_id,
            "key": item.key,
            "observation": item.observation,
            "source": item.source,
            "promoted": False,
            "topic": item.topic,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

        return item

    def get_sensory(self, session_id: str = "") -> list[SensoryItem]:
        """Get all sensory observations for a session."""
        items = []
        target = self._sensory_dir / (session_id or "current")
        if not target.exists():
            return items

        for f in sorted(target.glob("*.json")):
            try:
                data = json.loads(f.read_text("utf-8"))
                items.append(SensoryItem(**{k: v for k, v in data.items()
                                            if k in SensoryItem.__dataclass_fields__}))
            except Exception as e:
                logger.warning("[MEMORY] load sensory item %s failed: %s", f.name, e)

        return items

    def cleanup_sensory(self) -> int:
        """Remove old sensory data beyond max_sensory_sessions."""
        if not self._sensory_dir.exists():
            return 0

        sessions = sorted([d for d in self._sensory_dir.iterdir() if d.is_dir()],
                         key=lambda p: p.stat().st_mtime, reverse=True)

        removed = 0
        for old_session in sessions[self._max_sensory_sessions:]:
            shutil.rmtree(old_session, ignore_errors=True)
            removed += 1

        return removed

    def promote_sensory(self, session_id: str = "", key: str = "") -> list[Path]:
        """
        Promote sensory observations to short-term (card_*.md).
        Groups observations by KEY and creates one card per KEY.
        """
        observations = self.get_sensory(session_id)
        if not observations:
            return []

        # Group by KEY
        by_key: dict[str, list[SensoryItem]] = {}
        for obs in observations:
            if obs.promoted:
                continue
            k = obs.key or key or "_AUTO"
            by_key.setdefault(k, []).append(obs)

        created_cards = []
        for k, obs_list in by_key.items():
            if not obs_list:
                continue

            # Build card content
            lines = [f"# 📝 Session observations for {k}"]
            lines.append("")
            lines.append(f"- **Date:** {datetime.now(timezone.utc).strftime('%Y-%m-%d')}")
            lines.append(f"- **KEY:** {k}")
            lines.append(f"- **Type:** auto-promoted from sensory")
            lines.append(f"- **Confidence:** 50%")
            lines.append(f"- **Observations:** {len(obs_list)}")
            lines.append("")
            lines.append("## Observations")
            for obs in obs_list:
                lines.append(f"- [{obs.source}] {obs.observation}")

            # Save as card
            imp_dir = self._gcc_dir / "improvements" / k
            imp_dir.mkdir(parents=True, exist_ok=True)

            existing = sorted(imp_dir.glob("card_*.md"))
            next_num = 1
            for e in existing:
                try:
                    num = int(e.stem.split("_")[1])
                    next_num = max(next_num, num + 1)
                except (ValueError, IndexError):
                    pass

            card_path = imp_dir / f"card_{next_num:03d}.md"
            card_path.write_text("\n".join(lines), encoding="utf-8")
            created_cards.append(card_path)

            # Mark as promoted
            for obs in obs_list:
                obs.promoted = True

        return created_cards

    # ═══ Tier 2 → Tier 3: Consolidation ═══

    def consolidate(self, force: bool = False) -> ConsolidationResult:
        """
        Run auto-consolidation (sleep mechanism).

        1. Scan all cards in improvements/
        2. Merge duplicates (word overlap > threshold)
        3. Deprecate low-quality cards
        4. Promote high-quality cards to long-term (validated status)
        5. Snapshot before changes
        """
        result = ConsolidationResult()
        imp_root = self._gcc_dir / "improvements"

        if not imp_root.exists():
            return result

        # Count cards before
        all_cards = list(imp_root.rglob("card_*.md"))
        result.total_before = len(all_cards)

        if not force and result.total_before < self._consolidation_threshold:
            result.details.append(
                f"Skipped: {result.total_before} cards < threshold {self._consolidation_threshold}")
            result.total_after = result.total_before
            return result

        # Snapshot
        self._snapshot()

        # Load all cards
        card_data = []
        for card_path in all_cards:
            try:
                text = card_path.read_text("utf-8")
                # v4.97 LightMem: 从卡片内容提取 topic 标签
                topic = self._extract_topic(text, card_path)
                card_data.append({
                    "path": card_path,
                    "text": text,
                    "words": set(text.lower().split()),
                    "confidence": self._extract_confidence(text),
                    "key": card_path.parent.name,
                    "topic": topic,
                })
            except Exception as e:
                logger.warning("[MEMORY] load card %s failed: %s", card_path.name, e)

        # 1. Merge duplicates (v4.97: topic-aware — 跨 topic 不合并)
        merged_ids = set()
        for i, a in enumerate(card_data):
            if a["path"] in merged_ids:
                continue
            for j, b in enumerate(card_data[i+1:], i+1):
                if b["path"] in merged_ids:
                    continue
                if a["key"] != b["key"]:
                    continue
                # v4.97 LightMem: 跨 topic 不合并（例如股票经验不和加密货币经验合并）
                if a["topic"] and b["topic"] and a["topic"] != b["topic"]:
                    continue
                overlap = self._word_overlap(a["words"], b["words"])
                if overlap >= self._merge_overlap:
                    # Keep the one with higher confidence
                    if a["confidence"] >= b["confidence"]:
                        merged_ids.add(b["path"])
                        result.details.append(
                            f"Merged: {b['path'].name} → {a['path'].name} (overlap={overlap:.0%})")
                    else:
                        merged_ids.add(a["path"])
                        result.details.append(
                            f"Merged: {a['path'].name} → {b['path'].name} (overlap={overlap:.0%})")
                    result.merged += 1

        # 2. Deprecate low-quality
        for card in card_data:
            if card["path"] in merged_ids:
                continue
            if card["confidence"] < self._deprecate_confidence:
                merged_ids.add(card["path"])
                result.deprecated += 1
                result.details.append(
                    f"Deprecated: {card['path'].name} (confidence={card['confidence']:.0%})")

        # 3. Mark merged/deprecated as archived
        archive_dir = self._gcc_dir / "consolidation" / "archived"
        archive_dir.mkdir(parents=True, exist_ok=True)
        for path in merged_ids:
            try:
                target = archive_dir / f"{path.parent.name}_{path.name}"
                shutil.move(str(path), str(target))
            except Exception as e:
                logger.warning("[MEMORY] archive card %s failed: %s", path.name, e)

        # 4. Promote high-quality
        for card in card_data:
            if card["path"] in merged_ids:
                continue
            if card["confidence"] >= self._promote_confidence:
                # Add "validated" marker to card
                text = card["text"]
                if "**Status:** validated" not in text and "**Status:** active" in text:
                    new_text = text.replace("**Status:** active", "**Status:** validated")
                    try:
                        card["path"].write_text(new_text, encoding="utf-8")
                        result.promoted += 1
                        result.details.append(
                            f"Promoted: {card['path'].name} → long-term (confidence={card['confidence']:.0%})")
                    except Exception as e:
                        logger.warning("[MEMORY] promote card failed: %s", e)

        result.total_after = result.total_before - len(merged_ids)

        # Save audit trail
        self._save_audit(result)

        # Cleanup old sensory data
        self.cleanup_sensory()

        # v4.97 SkillRL: 重蒸馏被标记需复审的 skills (#16 SkillRL 2026)
        try:
            from .skill_registry import SkillBank
            sb = SkillBank(str(self._gcc_dir))
            redist_n = sb.auto_redist_marked()
            if redist_n > 0:
                result.details.append(f"SkillRL: 重蒸馏 {redist_n} 个 skills")
        except Exception as e:
            logger.warning("[MEMORY] skill redist failed: %s", e)

        return result

    def should_consolidate(self) -> bool:
        """Check if consolidation should run."""
        imp_root = self._gcc_dir / "improvements"
        if not imp_root.exists():
            return False
        count = sum(1 for _ in imp_root.rglob("card_*.md"))
        return count >= self._consolidation_threshold

    # ── Helpers ──

    def _extract_topic(self, text: str, card_path: "Path") -> str:
        """
        v4.97 LightMem: 从卡片内容提取 topic 标签 (#11 LightMem ZJU 2025)。
        优先读 card 头部的 **Topic:** 字段，其次按关键词推断。
        """
        import re as _re
        # 显式标记（如果 auto_card 写入了 **Topic:** 字段）
        m = _re.search(r"\*\*Topic:\*\*\s*(\S+)", text)
        if m:
            return m.group(1).strip().lower()

        # 关键词推断（基于内容）
        t = text.lower()
        if any(w in t for w in ["crypto", "bitcoin", "btc", "eth", "加密"]):
            return "crypto"
        if any(w in t for w in ["spy", "qqq", "equity", "股票", "a股", "纳斯达克"]):
            return "equity_trading"
        if any(w in t for w in ["option", "期权", "put", "call", "delta"]):
            return "options"
        if any(w in t for w in ["welding", "cnc", "robot", "yaskawa", "工厂", "焊接"]):
            return "industrial"
        if any(w in t for w in ["agent", "code", "llm", "gcc", "agentic", "memory"]):
            return "gcc"
        # 用目录名作为 fallback topic
        return card_path.parent.name.lower()

    def _word_overlap(self, a: set, b: set) -> float:
        """Compute word overlap ratio between two sets."""
        if not a or not b:
            return 0.0
        intersection = len(a & b)
        union = len(a | b)
        return intersection / union if union > 0 else 0.0

    def _extract_confidence(self, text: str) -> float:
        """Extract confidence from card markdown."""
        for line in text.split("\n"):
            if "**Confidence:**" in line:
                try:
                    val = line.split(":**")[1].strip().replace("%", "")
                    return float(val) / 100 if float(val) > 1 else float(val)
                except (ValueError, IndexError):
                    pass
        return 0.5  # Default

    def _snapshot(self):
        """Create pre-consolidation snapshot."""
        imp_root = self._gcc_dir / "improvements"
        if not imp_root.exists():
            return

        snap_dir = self._gcc_dir / "consolidation" / f"snapshot_{_ts()}"
        try:
            shutil.copytree(str(imp_root), str(snap_dir))
        except Exception as e:
            logger.warning("[MEMORY] snapshot copy failed: %s", e)

    def _save_audit(self, result: ConsolidationResult):
        """Save consolidation audit trail."""
        audit_dir = self._gcc_dir / "consolidation"
        audit_dir.mkdir(parents=True, exist_ok=True)
        audit_path = audit_dir / f"consolidation_{_ts()}.json"
        audit_path.write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8")

    # ── Stats ──

    def stats(self) -> dict:
        """Memory tier statistics."""
        sensory_count = 0
        if self._sensory_dir.exists():
            sensory_count = sum(1 for _ in self._sensory_dir.rglob("*.json"))

        short_term = 0
        long_term = 0
        imp_root = self._gcc_dir / "improvements"
        if imp_root.exists():
            for card_path in imp_root.rglob("card_*.md"):
                try:
                    text = card_path.read_text("utf-8")
                    if "**Status:** validated" in text:
                        long_term += 1
                    else:
                        short_term += 1
                except Exception as e:
                    logger.warning("[MEMORY] classify card failed: %s", e)
                    short_term += 1

        return {
            "sensory": sensory_count,
            "short_term": short_term,
            "long_term": long_term,
            "total": sensory_count + short_term + long_term,
            "should_consolidate": self.should_consolidate(),
        }


# ── CLI formatting ──

def format_tiers_report(stats: dict) -> str:
    """Format memory tier stats for CLI display."""
    lines = [
        "  Memory Tiers",
        f"  {'═' * 50}",
        f"  Sensory (Tier 1):    {stats['sensory']} observations",
        f"  Short-term (Tier 2): {stats['short_term']} cards",
        f"  Long-term (Tier 3):  {stats['long_term']} validated cards",
        f"  Total:               {stats['total']}",
    ]
    if stats.get("should_consolidate"):
        lines.append("")
        lines.append("  ⚠ Consolidation recommended: run `gcc-evo consolidate`")
    return "\n".join(lines)


def format_consolidation_report(result: ConsolidationResult) -> str:
    """Format consolidation result for CLI display."""
    lines = [
        "  Consolidation Result",
        f"  {'═' * 50}",
        f"  Cards before: {result.total_before}",
        f"  Cards after:  {result.total_after}",
        f"  Merged:       {result.merged}",
        f"  Deprecated:   {result.deprecated}",
        f"  Promoted:     {result.promoted}",
    ]
    if result.details:
        lines.append("")
        lines.append("  Details:")
        for d in result.details[:10]:
            lines.append(f"    → {d}")
        if len(result.details) > 10:
            lines.append(f"    ... and {len(result.details) - 10} more")
    return "\n".join(lines)


# ── E7: Infinite Memory — 4-tier architecture ─────────────────────────────
# Engram#7 (P2): L1=Working / L2=Episodic / L3=Semantic / L4=Archival
# Write-once archival tier with access-count-driven promotion to semantic tier.

class ArchivalMemory:
    """
    E7 — L4 Archival tier.

    Write-once, unbounded, rarely accessed historical records.
    Tracks access count per key for promotion/eviction decisions.
    """

    PROMOTE_THRESHOLD: int = 3  # accesses before promoting to semantic tier

    def __init__(self) -> None:
        self._archive: dict[str, Any] = {}
        self._access_count: dict[str, int] = {}
        self._stored_at: dict[str, datetime] = {}

    def store(self, key: str, value: Any) -> None:
        """Archive value; does not overwrite existing entry (write-once)."""
        if key not in self._archive:
            self._archive[key] = value
            self._access_count[key] = 0
            self._stored_at[key] = datetime.now(timezone.utc)

    def retrieve(self, key: str) -> Any | None:
        """Read archived value and increment access count."""
        if key in self._archive:
            self._access_count[key] += 1
            return self._archive[key]
        return None

    def access_stats(self) -> dict[str, int]:
        """Return access count per key (used by MemoryStack for promotion)."""
        return dict(self._access_count)

    def hot_keys(self) -> list[str]:
        """Keys that have reached the promotion threshold."""
        return [k for k, c in self._access_count.items() if c >= self.PROMOTE_THRESHOLD]


class MemoryStack:
    """
    E7: Infinite Memory Stack — 4-tier promotion manager.

    Tiers (Engram naming):
      L1 = Working   → SensoryMemory   (real-time, latest observation per key)
      L2 = Episodic  → ShortTermMemory (sliding window, FIFO eviction)
      L3 = Semantic  → LongTermMemory  (persistent knowledge)
      L4 = Archival  → ArchivalMemory  (write-once historical records)

    Promotion rule: L4 key with access_count >= PROMOTE_THRESHOLD → copy to L3 (MemoryTiers).
    """

    def __init__(self, gcc_dir: str | None = None) -> None:
        self.tiers = MemoryTiers(gcc_dir=gcc_dir)  # L1-L3 via existing MemoryTiers
        self.archival = ArchivalMemory()            # L4

    def archive(self, key: str, value: Any) -> None:
        """Store value in L4 archival tier."""
        self.archival.store(key, value)

    def recall(self, key: str) -> tuple[Any | None, int]:
        """
        Recall value searching L4 archival, return (value, tier).
        Returns (None, -1) if not found.
        """
        v = self.archival.retrieve(key)
        if v is not None:
            return v, 4
        return None, -1

    def promote_hot_archival(self) -> list[str]:
        """
        Promotion: move frequently-accessed L4 keys to L3 (MemoryTiers sensory observe).
        Returns list of promoted keys.
        """
        promoted = []
        for key in self.archival.hot_keys():
            value = self.archival.retrieve(key)
            if value is not None:
                # Promote to L3 via MemoryTiers.observe()
                try:
                    self.tiers.observe(str(value), key=key)
                    promoted.append(key)
                except Exception:
                    pass
        return promoted
