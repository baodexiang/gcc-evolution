"""
GCC v4.8 — Context Chain Retrieval
灵感来源：Mischler et al. (Nature MI, 2024) 层级特征提取与脑对齐

核心发现：
  1. 高性能 LLM 的内部层与大脑皮层层级对齐
  2. 去掉上下文后 LLM-脑对齐急剧下降
  3. 高效模型用更少层达到同样编码

GCC 应用：
  - 经验卡片不再孤立注入，带上下文链一起传递
  - 分层检索：L1(操作) / L2(策略) / L3(元认知)
  - 注入格式：Context → Constraints → Cards + Chain

使用方式：
  chain = ContextChain()
  context = chain.retrieve("SPY choppy market ATR optimization")
  # Returns layered context string for LLM injection
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Context Layers ──

@dataclass
class ContextLayer:
    """A single layer of context information."""
    level: int          # 1=操作, 2=策略, 3=元认知
    label: str          # "L1-Operations", "L2-Strategy", "L3-Meta"
    items: list[str] = field(default_factory=list)

    def render(self) -> str:
        if not self.items:
            return ""
        lines = [f"### {self.label}"]
        for item in self.items:
            lines.append(f"- {item}")
        return "\n".join(lines)


@dataclass
class ContextChainResult:
    """Complete context chain ready for LLM injection."""
    key: str = ""
    query: str = ""
    layers: list[ContextLayer] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    chain_cards: list[str] = field(default_factory=list)  # card IDs in chain
    token_estimate: int = 0

    def render(self) -> str:
        """Render full context for LLM injection."""
        sections = []

        # Header
        sections.append(f"## GCC Context for: {self.key or self.query}")
        sections.append("")

        # Constraints first (DO NOT rules)
        if self.constraints:
            sections.append("### ⛔ Constraints (DO NOT)")
            for c in self.constraints:
                sections.append(f"- {c}")
            sections.append("")

        # Layers
        for layer in self.layers:
            rendered = layer.render()
            if rendered:
                sections.append(rendered)
                sections.append("")

        # Chain info
        if self.chain_cards:
            sections.append(f"_Context chain: {len(self.chain_cards)} cards linked_")

        return "\n".join(sections)


# ── Context Chain Engine ──

class ContextChain:
    """
    Hierarchical context retrieval engine.

    Instead of flat card injection, builds a layered context:
      L1 (Operations): specific params, code, numbers
      L2 (Strategy): patterns, methodologies, trade-offs
      L3 (Meta-cognition): constraints, principles, gate standards
    """

    def __init__(self, gcc_dir: str | None = None):
        self._gcc_dir = self._find_gcc_dir(gcc_dir)

    def _find_gcc_dir(self, hint: str | None = None) -> Path:
        """Find .gcc or .GCC directory."""
        if hint:
            return Path(hint)
        for name in [".gcc", ".GCC"]:
            p = Path(name)
            if p.exists():
                return p
        return Path(".gcc")

    def retrieve(self, query: str, key: str = "",
                 max_cards: int = 10,
                 include_constraints: bool = True,
                 check_anchor: bool = True) -> ContextChainResult:
        """
        Build a layered context chain for the given query/key.

        v4.85: Checks Human Anchor confidence first (C1 layer).
        If anchor is missing or expired, injects pause signal into L3.

        Flow:
          0. [v4.85] Check Human Anchor → inject into L3 or signal pause
          1. Find relevant cards (from improvements/ markdown or experience DB)
          2. Classify each card into L1/L2/L3
          3. Follow parent/related chains
          4. Load constraints for the KEY
          5. Render layered context
        """
        result = ContextChainResult(key=key, query=query)

        # v4.85: Step 0 — Human Anchor check (C1 direction layer)
        if check_anchor:
            anchor_item = self._inject_human_anchor(key)
            if anchor_item:
                result._anchor_injected = anchor_item
                result._anchor_paused = anchor_item.get("paused", False)

        # 1. Gather cards
        cards = self._gather_cards(key, max_cards)

        # 2. Classify into layers
        l1 = ContextLayer(level=1, label="L1 — Operations (具体操作)")
        l2 = ContextLayer(level=2, label="L2 — Strategy (策略方法)")
        l3 = ContextLayer(level=3, label="L3 — Meta-cognition (元认知)")

        # v4.85: Inject Human Anchor as L3 item (highest priority)
        if check_anchor and hasattr(result, '_anchor_injected'):
            ai = result._anchor_injected
            if not ai.get("paused"):
                anchor_text = ai.get("text", "")
                if anchor_text:
                    l3.items.insert(0, f"[HUMAN ANCHOR] {anchor_text}")

        for card in cards:
            level = self._classify_level(card)
            item = self._card_to_item(card)
            if level == 1:
                l1.items.append(item)
            elif level == 2:
                l2.items.append(item)
            else:
                l3.items.append(item)
            result.chain_cards.append(card.get("id", ""))

        result.layers = [l3, l2, l1]  # Meta first, operations last

        # 3. Load constraints
        if include_constraints:
            result.constraints = self._load_constraints(key)

        # 4. Estimate tokens (~4 chars per token)
        rendered = result.render()
        result.token_estimate = len(rendered) // 4

        return result

    def retrieve_for_card(self, card_id: str, key: str = "") -> ContextChainResult:
        """
        Retrieve context chain for a specific card.
        Follows parent → related → supersedes links.
        """
        result = ContextChainResult(key=key, query=f"chain for {card_id}")

        card = self._find_card(card_id, key)
        if not card:
            return result

        # Build chain: this card + parent + related
        chain = [card]
        seen = {card_id}

        # Follow parent
        parent_id = card.get("parent_id", "")
        if parent_id and parent_id not in seen:
            parent = self._find_card(parent_id, key)
            if parent:
                chain.append(parent)
                seen.add(parent_id)

        # Follow related
        for rel_id in card.get("related_ids", []):
            if rel_id not in seen:
                rel = self._find_card(rel_id, key)
                if rel:
                    chain.append(rel)
                    seen.add(rel_id)

        # Classify all
        l1 = ContextLayer(level=1, label="L1 — Operations")
        l2 = ContextLayer(level=2, label="L2 — Strategy")
        l3 = ContextLayer(level=3, label="L3 — Meta-cognition")

        for c in chain:
            level = self._classify_level(c)
            item = self._card_to_item(c)
            target = {1: l1, 2: l2, 3: l3}[level]
            target.items.append(item)
            result.chain_cards.append(c.get("id", ""))

        result.layers = [l3, l2, l1]
        result.constraints = self._load_constraints(key)
        result.token_estimate = len(result.render()) // 4

        return result

    # ── Card gathering ──

    def _gather_cards(self, key: str, max_cards: int) -> list[dict]:
        """Gather cards from improvements/ markdown files."""
        cards = []

        # Strategy 1: Read from improvements/{KEY}/card_*.md
        if key:
            imp_dir = self._gcc_dir / "improvements" / key
            if imp_dir.exists():
                for card_path in sorted(imp_dir.glob("card_*.md")):
                    card = self._parse_card_md(card_path)
                    if card:
                        cards.append(card)
                        if len(cards) >= max_cards:
                            break

        # Strategy 2: If no key or not enough cards, scan all improvements
        if len(cards) < max_cards:
            imp_root = self._gcc_dir / "improvements"
            if imp_root.exists():
                for key_dir in sorted(imp_root.iterdir()):
                    if key_dir.is_dir() and key_dir.name != "_UNKEYED":
                        for card_path in sorted(key_dir.glob("card_*.md")):
                            card = self._parse_card_md(card_path)
                            if card and card.get("id", "") not in {c.get("id") for c in cards}:
                                cards.append(card)
                                if len(cards) >= max_cards:
                                    break

        # Strategy 3: Fallback to experience DB
        if not cards:
            cards = self._load_from_db(key, max_cards)

        return cards

    def _parse_card_md(self, path: Path) -> dict | None:
        """Parse a markdown knowledge card into a dict."""
        try:
            text = path.read_text("utf-8")
            card = {
                "id": path.stem,
                "path": str(path),
                "key": path.parent.name,
                "raw_text": text,
            }

            # Extract metadata from frontmatter-style fields
            for line in text.split("\n"):
                line = line.strip()
                if line.startswith("- **Type:**"):
                    card["type"] = line.split(":**")[1].strip()
                elif line.startswith("- **Confidence:**"):
                    try:
                        card["confidence"] = float(line.split(":**")[1].strip().replace("%", "")) / 100
                    except ValueError:
                        pass
                elif line.startswith("- **KEY:**"):
                    card["key"] = line.split(":**")[1].strip()
                elif line.startswith("- **Stage:**"):
                    card["stage"] = line.split(":**")[1].strip()
                elif line.startswith("- **Task:**"):
                    card["task"] = line.split(":**")[1].strip()

            # Extract title (first # line)
            for line in text.split("\n"):
                if line.startswith("# "):
                    card["title"] = line[2:].strip()
                    break

            # Extract sections
            current_section = ""
            section_content = []
            for line in text.split("\n"):
                if line.startswith("## "):
                    if current_section and section_content:
                        card[current_section.lower().replace(" ", "_")] = "\n".join(section_content).strip()
                    current_section = line[3:].strip()
                    section_content = []
                elif current_section:
                    section_content.append(line)
            if current_section and section_content:
                card[current_section.lower().replace(" ", "_")] = "\n".join(section_content).strip()

            return card
        except Exception as e:
            logger.warning("[CONTEXT_CHAIN] parse card md failed: %s", e)
            return None

    def _load_from_db(self, key: str, limit: int) -> list[dict]:
        """Fallback: load from SQLite experience store."""
        try:
            from .experience_store import GlobalMemory
            gm = GlobalMemory()
            if key:
                cards = gm.get_by_key(key)[:limit]
            else:
                cards = gm.get_all(limit=limit)
            gm.close()
            return [self._experience_card_to_dict(c) for c in cards]
        except Exception as e:
            logger.warning("[CONTEXT_CHAIN] load from db failed: %s", e)
            return []

    def _experience_card_to_dict(self, card) -> dict:
        """Convert ExperienceCard to dict for classification."""
        return {
            "id": card.id,
            "key": card.key,
            "type": card.exp_type.value if hasattr(card.exp_type, 'value') else str(card.exp_type),
            "title": card.key_insight,
            "strategy": card.strategy or "",
            "trigger_symptom": card.trigger_symptom or "",
            "confidence": card.confidence,
            "pitfalls": card.pitfalls or [],
            "tags": card.tags or [],
            "parent_id": card.parent_id or "",
            "related_ids": card.related_ids or [],
        }

    def _find_card(self, card_id: str, key: str = "") -> dict | None:
        """Find a specific card by ID."""
        # Check improvements/ first
        imp_root = self._gcc_dir / "improvements"
        if imp_root.exists():
            search_dirs = []
            if key:
                search_dirs.append(imp_root / key)
            search_dirs.extend([d for d in imp_root.iterdir() if d.is_dir()])

            for d in search_dirs:
                for card_path in d.glob("card_*.md"):
                    if card_path.stem == card_id or card_id in card_path.read_text("utf-8")[:200]:
                        return self._parse_card_md(card_path)

        # Fallback to DB
        try:
            from .experience_store import GlobalMemory
            gm = GlobalMemory()
            card = gm.retrieve(card_id)
            gm.close()
            if card:
                return self._experience_card_to_dict(card)
        except Exception as e:
            logger.warning("[CONTEXT_CHAIN] find card in db failed: %s", e)

        return None

    # ── Classification ──

    _L1_KEYWORDS = {
        "atr", "period", "lookback", "threshold", "multiplier", "ratio",
        "stop", "target", "entry", "exit", "param", "value", "config",
        "=", "→", "from", "to", "set", "change",
    }

    _L2_KEYWORDS = {
        "strategy", "pattern", "regime", "trend", "choppy", "breakout",
        "filter", "signal", "method", "approach", "when", "condition",
        "market", "analysis", "structure", "fibonacci", "wyckoff",
    }

    _L3_KEYWORDS = {
        "constraint", "do not", "never", "always", "principle", "rule",
        "gate", "standard", "requirement", "must", "sharpe", "drawdown",
        "risk", "management", "priority", "meta",
    }

    def _classify_level(self, card: dict) -> int:
        """
        Classify a card into L1/L2/L3 based on content analysis.

        L1 (Operations): concrete numbers, params, code changes
        L2 (Strategy): patterns, methodologies, conditions
        L3 (Meta-cognition): constraints, principles, standards
        """
        text = " ".join([
            card.get("title", ""),
            card.get("strategy", ""),
            card.get("trigger_symptom", ""),
            card.get("raw_text", "")[:300],
        ]).lower()

        l1_score = sum(1 for kw in self._L1_KEYWORDS if kw in text)
        l2_score = sum(1 for kw in self._L2_KEYWORDS if kw in text)
        l3_score = sum(1 for kw in self._L3_KEYWORDS if kw in text)

        # Constraints and failures → L3
        card_type = card.get("type", "")
        if card_type == "failure" or "constraint" in text or "do not" in text:
            l3_score += 5

        # Auto-generated from code changes → L1
        if card.get("stage") == "integrate" or "auto-generated" in text:
            l1_score += 3

        scores = {1: l1_score, 2: l2_score, 3: l3_score}
        return max(scores, key=scores.get)

    def _card_to_item(self, card: dict) -> str:
        """Convert a card dict to a concise context item string."""
        title = card.get("title", card.get("key_insight", "Unknown"))
        # Clean emoji prefixes
        for prefix in ["✅ ", "❌ ", "📝 ", "⚠️ "]:
            title = title.replace(prefix, "")

        parts = [title]

        confidence = card.get("confidence", 0)
        if confidence:
            parts[0] += f" ({confidence:.0%})"

        strategy = card.get("strategy", "")
        if strategy and len(strategy) < 100:
            parts.append(f"  → {strategy}")

        trigger = card.get("trigger_symptom", "")
        if trigger:
            parts.append(f"  When: {trigger}")

        return "\n".join(parts)

    # ── Constraints ──

    def _inject_human_anchor(self, key: str = "") -> dict:
        """
        v4.85: Check Human Anchor state and return injection dict.
        Returns {"text": ..., "paused": bool, "confidence": float}
        """
        try:
            from .human_anchor import HumanAnchorStore
            store = HumanAnchorStore(str(self._gcc_dir))
            anchor = store.get_latest()
            conf = store.get_confidence()
            needs, reason = store.needs_calibration()

            if needs:
                pause = store.build_pause_signal()
                return {
                    "paused": True,
                    "confidence": conf,
                    "pause_reason": reason,
                    "pause_text": pause.format(),
                    "text": f"⚠️ 需要校准: {reason}",
                }

            if anchor:
                direction_text = f"方向={anchor.direction}"
                constraints_text = ""
                if anchor.constraints:
                    constraints_text = "  约束: " + "; ".join(anchor.constraints[:3])
                return {
                    "paused": False,
                    "confidence": conf,
                    "anchor_id": anchor.anchor_id,
                    "text": (
                        f"{direction_text}  置信度={conf:.0%}"
                        f"  关注={anchor.main_concern}"
                        f"{constraints_text}"
                    ),
                }
        except Exception as e:
            logger.warning("[CONTEXT_CHAIN] build constraints context failed: %s", e)
        return {}

    def _load_constraints(self, key: str = "") -> list[str]:
        """Load constraints for a KEY."""
        constraints = []

        # From constraints.json
        cj = self._gcc_dir / "constraints.json"
        if cj.exists():
            try:
                data = json.loads(cj.read_text("utf-8"))
                for c in data:
                    if not key or c.get("key", "") == key or c.get("key", "") == "":
                        if c.get("active", True):
                            constraints.append(c.get("rule", ""))
            except Exception as e:
                logger.warning("[CONTEXT_CHAIN] load constraints json failed: %s", e)

        # From card pitfalls
        if key:
            imp_dir = self._gcc_dir / "improvements" / key
            if imp_dir.exists():
                for card_path in imp_dir.glob("card_*.md"):
                    try:
                        text = card_path.read_text("utf-8")
                        in_pitfalls = False
                        for line in text.split("\n"):
                            if "## Pitfalls" in line:
                                in_pitfalls = True
                                continue
                            if in_pitfalls:
                                if line.startswith("## "):
                                    break
                                if line.strip().startswith("- ⚠️"):
                                    pitfall = line.strip()[4:].strip()
                                    if pitfall and pitfall not in constraints:
                                        constraints.append(pitfall)
                    except Exception as e:
                        logger.warning("[CONTEXT_CHAIN] parse card pitfall failed: %s", e)

        return constraints


# ── CLI entry point ──

def format_context_report(result: ContextChainResult) -> str:
    """Format context chain for CLI display."""
    lines = [
        f"  Context Chain for: {result.key or result.query}",
        f"  {'═' * 50}",
        f"  Cards: {len(result.chain_cards)} | Constraints: {len(result.constraints)} | ~{result.token_estimate} tokens",
        "",
    ]

    for layer in result.layers:
        if layer.items:
            lines.append(f"  {layer.label} ({len(layer.items)} items)")
            for item in layer.items:
                for i, line in enumerate(item.split("\n")):
                    lines.append(f"    {'•' if i == 0 else ' '} {line}")
            lines.append("")

    if result.constraints:
        lines.append(f"  ⛔ Constraints ({len(result.constraints)})")
        for c in result.constraints:
            lines.append(f"    • {c}")

    return "\n".join(lines)
