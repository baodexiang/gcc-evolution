"""
GCC v4.0 — Normalizer
Standardizes experience cards to a consistent format, regardless of input quality.
Supports two modes: rule-based (offline) and LLM-enhanced (API-dependent).

Card Lifecycle:
  draft → active → validated → archived
    ↑        ↑         ↑          ↑
  论文/人   seed/     session    KEY close
  手写输入  格式化    验证修正    最终归档
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from .models import ExperienceCard, ExperienceType, CardStatus


# ── LLM Prompt ─────────────────────────────────────────────

NORMALIZE_SYSTEM = """You are the knowledge card normalizer for GCC v4.0.
Rewrite the given card into a standardized format. Rules:

1. key_insight: ONE actionable sentence, start with a verb. Max 120 chars.
   BAD:  "I found that when we removed the HOLD band it caused issues"
   GOOD: "Replace HOLD band with N-gate before removal to prevent false signals"

2. trigger_symptom: WHEN does this apply? One short phrase.
   BAD:  "when you're working on the domain system signals"
   GOOD: "modifying signal filtering logic"

3. strategy: HOW to do it. 1-2 concrete sentences.
   BAD:  "just be careful"
   GOOD: "Add N-structure gate first, validate false positive rate < 10%, then remove HOLD band"

4. pitfalls: List of specific things to AVOID. Each starts with a verb.
   BAD:  "it might break"
   GOOD: "Removing filter without replacement causes 40% false signal increase"

5. tags: 3-8 lowercase keywords, no duplicates, no generic words like "code" or "work".

Output ONLY a JSON object with these fields:
{
  "key_insight": "...",
  "trigger_symptom": "...",
  "strategy": "...",
  "pitfalls": ["..."],
  "tags": ["..."],
  "confidence": 0.0-1.0
}"""

NORMALIZE_USER = """Standardize this knowledge card:

Source: {source}
Type: {exp_type}
Current insight: {key_insight}
Current trigger: {trigger_symptom}
Current strategy: {strategy}
Current pitfalls: {pitfalls}
Current tags: {tags}
Attachments: {attachments}

Rewrite into standardized format. JSON only."""


class Normalizer:
    """
    Standardizes experience cards to consistent quality and format.

    Two modes:
    - rule-based: deterministic, no API needed, handles 80% of cases
    - llm-enhanced: uses LLM for deeper rewriting, falls back to rules

    Also manages card lifecycle status transitions.
    """

    def __init__(self, llm=None, mode: str = "auto"):
        """
        mode: "rules" | "llm" | "auto"
          rules — pure rule-based, no API calls
          llm   — always use LLM (fails if no API)
          auto  — use LLM if available, rules fallback
        """
        self.llm = llm
        self.mode = mode

    # ════════════════════════════════════════════════════════
    # Main API
    # ════════════════════════════════════════════════════════

    def normalize(self, card: ExperienceCard) -> ExperienceCard:
        """
        Standardize a card's format. Always applies rules first,
        then optionally LLM polish.
        """
        # Step 1: Always apply rule-based cleanup
        card = self._normalize_rules(card)

        # Step 2: LLM polish if configured and available
        if self._should_use_llm():
            card = self._normalize_llm(card)

        return card

    def normalize_batch(self, cards: list[ExperienceCard]) -> list[ExperienceCard]:
        """Normalize a list of cards."""
        return [self.normalize(c) for c in cards]

    # ════════════════════════════════════════════════════════
    # Lifecycle Status Transitions
    # ════════════════════════════════════════════════════════

    @staticmethod
    def promote(card: ExperienceCard, to_status: CardStatus,
                reason: str = "") -> ExperienceCard:
        """
        Transition a card to a new lifecycle status.

        draft → active:     Card has been formatted, ready for use
        active → validated: Card confirmed by session results
        validated → archived: KEY closed, card is final reference
        """
        valid_transitions = {
            CardStatus.DRAFT: [CardStatus.ACTIVE],
            CardStatus.ACTIVE: [CardStatus.VALIDATED, CardStatus.DEPRECATED],
            CardStatus.VALIDATED: [CardStatus.ARCHIVED, CardStatus.DEPRECATED],
            CardStatus.ARCHIVED: [CardStatus.DEPRECATED],
        }

        allowed = valid_transitions.get(card.status, [])
        if to_status not in allowed:
            raise ValueError(
                f"Cannot transition {card.status.value} → {to_status.value}. "
                f"Allowed: {[s.value for s in allowed]}"
            )

        card.status = to_status
        card.status_history.append({
            "from": card.status.value if card.status != to_status else "init",
            "to": to_status.value,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        return card

    @staticmethod
    def archive_key(cards: list[ExperienceCard], key: str,
                    final_insight: str = "") -> list[ExperienceCard]:
        """
        Archive all validated cards for a KEY when it closes.
        Optionally update the top card with a final consolidated insight.
        """
        archived = []
        best_card = None
        best_conf = -1

        for c in cards:
            if c.key != key:
                continue

            if c.status == CardStatus.VALIDATED:
                c.status = CardStatus.ARCHIVED
                c.status_history.append({
                    "from": "validated",
                    "to": "archived",
                    "reason": f"KEY {key} closed",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                if c.confidence > best_conf:
                    best_conf = c.confidence
                    best_card = c
                archived.append(c)

            elif c.status == CardStatus.ACTIVE:
                # Active but unvalidated → deprecated
                c.status = CardStatus.DEPRECATED
                c.status_history.append({
                    "from": "active",
                    "to": "deprecated",
                    "reason": f"KEY {key} closed without validation",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

        # Update best card with final insight if provided
        if final_insight and best_card:
            best_card.key_insight = final_insight

        return archived

    # ════════════════════════════════════════════════════════
    # Rule-Based Normalization
    # ════════════════════════════════════════════════════════

    def _normalize_rules(self, card: ExperienceCard) -> ExperienceCard:
        """Deterministic cleanup. No API calls."""

        # ── key_insight cleanup ──
        card.key_insight = self._clean_insight(card.key_insight)

        # ── trigger_symptom cleanup ──
        card.trigger_symptom = self._clean_trigger(card.trigger_symptom)

        # ── strategy cleanup ──
        card.strategy = self._clean_strategy(card.strategy)

        # ── pitfalls cleanup ──
        card.pitfalls = self._clean_pitfalls(card.pitfalls)

        # ── tags cleanup ──
        card.tags = self._clean_tags(card.tags)

        # ── trigger_keywords from content ──
        if not card.trigger_keywords:
            card.trigger_keywords = self._extract_keywords(
                f"{card.key_insight} {card.trigger_symptom} {card.strategy}"
            )

        # ── Set status to ACTIVE if still DRAFT ──
        if card.status == CardStatus.DRAFT:
            card.status = CardStatus.ACTIVE
            card.status_history.append({
                "from": "draft",
                "to": "active",
                "reason": "rule-based normalization",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        return card

    def _clean_insight(self, text: str) -> str:
        if not text:
            return text

        # Remove common filler prefixes
        fillers = [
            "I found that ", "I noticed that ", "I realized that ",
            "It turns out that ", "It seems that ", "We discovered that ",
            "Basically, ", "In conclusion, ", "Overall, ",
            "The key insight is that ", "The main takeaway is ",
        ]
        lower = text.strip()
        for f in fillers:
            if lower.lower().startswith(f.lower()):
                lower = lower[len(f):]
                break

        # Capitalize first letter
        if lower:
            lower = lower[0].upper() + lower[1:]

        # Truncate to ~120 chars at word boundary
        if len(lower) > 140:
            cut = lower[:130].rsplit(" ", 1)[0]
            lower = cut.rstrip(".,;:") + "..."

        # Remove trailing period duplication
        lower = lower.rstrip(".")
        if not lower.endswith("..."):
            lower += ""

        return lower.strip()

    def _clean_trigger(self, text: str) -> str:
        if not text:
            return text

        # Remove prefixes like "When:", "Trigger:", "Step:"
        prefixes = ["When: ", "Trigger: ", "Step: ", "Failed: ",
                     "When you ", "If you "]
        stripped = text.strip()
        for p in prefixes:
            if stripped.startswith(p):
                stripped = stripped[len(p):]
                break

        # Lowercase first word if it's a gerund/verb
        if stripped and stripped[0].isupper():
            words = stripped.split(" ", 1)
            if words[0].endswith("ing") or words[0].endswith("ed"):
                stripped = stripped[0].lower() + stripped[1:]

        return stripped.strip()

    def _clean_strategy(self, text: str) -> str:
        if not text:
            return text

        # Remove vague strategies
        vague = ["just be careful", "try harder", "do it better",
                 "be more thorough"]
        if text.strip().lower() in vague:
            return ""

        # Capitalize
        text = text.strip()
        if text:
            text = text[0].upper() + text[1:]

        return text

    def _clean_pitfalls(self, pitfalls: list[str]) -> list[str]:
        cleaned = []
        seen = set()

        for p in pitfalls:
            p = p.strip()
            if not p or len(p) < 5:
                continue

            # Capitalize
            p = p[0].upper() + p[1:]

            # Dedup by lowercase prefix
            sig = p.lower()[:50]
            if sig in seen:
                continue
            seen.add(sig)

            cleaned.append(p)

        return cleaned[:5]  # Max 5 pitfalls

    def _clean_tags(self, tags: list[str]) -> list[str]:
        # Lowercase, dedup, remove generic
        generic = {"code", "work", "good", "bad", "thing", "stuff",
                   "important", "general", "misc", "other"}
        cleaned = []
        seen = set()

        for t in tags:
            t = t.strip().lower().replace(" ", "_")
            if not t or t in generic or t in seen or len(t) < 2:
                continue
            seen.add(t)
            cleaned.append(t)

        return cleaned[:8]  # Max 8 tags

    # ════════════════════════════════════════════════════════
    # LLM-Enhanced Normalization
    # ════════════════════════════════════════════════════════

    def _should_use_llm(self) -> bool:
        if self.mode == "rules":
            return False
        if self.mode == "llm":
            return self.llm is not None
        # auto: use LLM if available
        return self.llm is not None

    def _normalize_llm(self, card: ExperienceCard) -> ExperienceCard:
        if not self.llm:
            return card

        prompt = NORMALIZE_USER.format(
            source=card.source_session or "manual",
            exp_type=card.exp_type.value,
            key_insight=card.key_insight,
            trigger_symptom=card.trigger_symptom,
            strategy=card.strategy,
            pitfalls="; ".join(card.pitfalls) or "(none)",
            tags=", ".join(card.tags) or "(none)",
            attachments=", ".join(card.attachments) or "(none)",
        )

        try:
            raw = self.llm.generate(
                system=NORMALIZE_SYSTEM, user=prompt, temperature=0.2,
            )
            text = raw.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            d = json.loads(text)

            # Only overwrite if LLM output is non-empty and reasonable
            if d.get("key_insight") and len(d["key_insight"]) > 10:
                card.key_insight = d["key_insight"]
            if d.get("trigger_symptom"):
                card.trigger_symptom = d["trigger_symptom"]
            if d.get("strategy") and len(d["strategy"]) > 10:
                card.strategy = d["strategy"]
            if d.get("pitfalls"):
                card.pitfalls = d["pitfalls"]
            if d.get("tags"):
                card.tags = self._clean_tags(d["tags"])
            if d.get("confidence"):
                card.confidence = float(d["confidence"])

        except Exception:
            pass  # Silently fall back to rule-based result

        return card

    # ════════════════════════════════════════════════════════
    # Helpers
    # ════════════════════════════════════════════════════════

    @staticmethod
    def _extract_keywords(text: str) -> list[str]:
        stop = {"the", "a", "an", "is", "was", "are", "to", "in", "of",
                "for", "and", "or", "on", "at", "by", "with", "from",
                "this", "that", "it", "be", "as", "do", "not", "but",
                "if", "no", "so", "has", "have", "had", "will", "can"}
        words = re.findall(r'[a-zA-Z_]{3,}', text.lower())
        return list(dict.fromkeys(w for w in words if w not in stop))[:10]
