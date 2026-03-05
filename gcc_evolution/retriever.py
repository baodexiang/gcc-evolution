"""
GCC v4.1 — Retriever ("Dynamic Retrieval")
Implements full v4.2 roadmap features under v4.1 label.

v3.98: Anti-reuse-bias diversity, confidence decay, type diversity.
v4.0:  Dual-layer retrieval (Agent KB) + Verification-First injection (VF).
v4.1:  + Semantic embedding (sentence-transformers, graceful fallback)
       + Graph-aware retrieval (1-hop along parent/supersedes/related)
       + Goal-aware pruning (SWE-Pruner: step-level context filtering)
       + EmbedderFactory (config-driven embedder selection)

Embedder priority:
  1. SemanticEmbedder (sentence-transformers) — if available
  2. LocalEmbedder (SHA256 word hashing) — always available, offline fallback
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
import sys
from datetime import datetime, timezone

from .config import GCCConfig
from .experience_store import GlobalMemory
from .models import CardStatus, ExperienceCard, ExperienceType

logger = logging.getLogger("gcc.retriever")


# ════════════════════════════════════════════════════════════
# Embedders
# ════════════════════════════════════════════════════════════

class LocalEmbedder:
    """Deterministic local embedder using word hashing. No dependencies."""

    name = "local"

    def __init__(self, dim: int = 128):
        self.dim = dim

    def embed(self, text: str) -> list[float]:
        words = re.findall(r'\w+', text.lower())
        if not words:
            return [0.0] * self.dim
        vec = [0.0] * self.dim
        for word in words:
            h = int(hashlib.sha256(word.encode()).hexdigest(), 16)
            idx = h % self.dim
            sign = 1.0 if (h >> 8) % 2 == 0 else -1.0
            weight = 1.0 / math.log2(max(len(word), 2))
            vec[idx] += sign * weight
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [x / norm for x in vec]
        return vec


class SemanticEmbedder:
    """
    v4.1: Real semantic embedder using sentence-transformers.
    Supports bilingual (Chinese/English) with multilingual models.

    Recommended models:
      - all-MiniLM-L6-v2 (English, fast, 384-dim)
      - paraphrase-multilingual-MiniLM-L12-v2 (bilingual, 384-dim)

    Auto-install: On first use, attempts `pip install sentence-transformers`.
    If install fails (no network, no disk space, etc.), silently falls back
    to LocalEmbedder. No user intervention needed.

    Model is lazy-loaded on first embed() call.
    """

    name = "semantic"
    _install_attempted = False  # class-level: only try pip install once per process
    _install_result = None      # class-level: cache install result

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self._model = None
        self._available = None  # None = not checked yet
        self.dim = 384  # default for MiniLM models

    @property
    def available(self) -> bool:
        if self._available is None:
            self._available = self._check_available()
        return self._available

    def _check_available(self) -> bool:
        # Step 1: try importing directly
        try:
            from sentence_transformers import SentenceTransformer  # noqa: F401
            print("  ✓ sentence-transformers: already installed", flush=True)
            return True
        except ImportError:
            pass

        # Step 2: auto-install (once per process, class-level)
        if not SemanticEmbedder._install_attempted:
            SemanticEmbedder._install_attempted = True
            SemanticEmbedder._install_result = self._try_install()
            if SemanticEmbedder._install_result:
                try:
                    from sentence_transformers import SentenceTransformer  # noqa: F401
                    return True
                except ImportError:
                    pass
        elif SemanticEmbedder._install_result:
            try:
                from sentence_transformers import SentenceTransformer  # noqa: F401
                return True
            except ImportError:
                pass

        print("  ℹ sentence-transformers unavailable, "
              "using LocalEmbedder (keyword-based)", flush=True)
        return False

    @staticmethod
    def _try_install() -> bool:
        """Attempt pip install sentence-transformers with user feedback."""
        import subprocess
        print("  ⚡ First use: installing sentence-transformers "
              "(semantic embedding)...", flush=True)
        print("    This may take 1-2 minutes. "
              "If it fails, LocalEmbedder will be used.", flush=True)
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install",
                 "sentence-transformers", "--quiet",
                 "--break-system-packages"],
                capture_output=True, text=True, timeout=300,
            )
            if result.returncode == 0:
                print("  ✓ sentence-transformers installed successfully")
                return True
            else:
                stderr = result.stderr.strip().split('\n')[-1] if result.stderr else ""
                print(f"  ✗ Install failed: {stderr}")
                print("  ℹ Falling back to LocalEmbedder (still works, "
                      "just keyword-based)")
                return False
        except subprocess.TimeoutExpired:
            print("  ✗ Install timed out (>5min)")
            print("  ℹ Falling back to LocalEmbedder")
            return False
        except Exception as e:
            print(f"  ✗ Install skipped: {e}")
            print("  ℹ Falling back to LocalEmbedder")
            return False

    def _load_model(self):
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer
            print(f"  ⚡ Loading embedding model: {self.model_name}...",
                  flush=True)
            self._model = SentenceTransformer(self.model_name)
            self.dim = self._model.get_sentence_embedding_dimension()
            print(f"  ✓ Model loaded (dim={self.dim})")
        except Exception as e:
            print(f"  ✗ Model load failed: {e}")
            print("  ℹ Falling back to LocalEmbedder")
            self._available = False

    def embed(self, text: str) -> list[float]:
        if not self.available:
            return []  # caller should fallback
        self._load_model()
        if self._model is None:
            return []
        try:
            vec = self._model.encode(text, normalize_embeddings=True)
            return vec.tolist()
        except Exception as e:
            print(f"  ✗ Embed failed: {e}", flush=True)
            return []


class EmbedderFactory:
    """
    v4.1: Config-driven embedder selection with graceful fallback.

    Priority: semantic (if available) → local (always works)
    """

    @staticmethod
    def create(config: GCCConfig | None = None) -> LocalEmbedder | SemanticEmbedder:
        if config is None:
            return LocalEmbedder()

        embedding_type = getattr(config, 'embedding', 'local')
        model_name = getattr(config, 'embedding_model', 'all-MiniLM-L6-v2')

        if embedding_type == "semantic":
            sem = SemanticEmbedder(model_name=model_name)
            if sem.available:
                return sem
            logger.info("Semantic embedder unavailable, using LocalEmbedder")
            return LocalEmbedder()
        elif embedding_type == "auto":
            # Try semantic first, fallback to local
            sem = SemanticEmbedder(model_name=model_name)
            if sem.available:
                return sem
            return LocalEmbedder()
        else:
            return LocalEmbedder()


# ════════════════════════════════════════════════════════════
# Retrieval Result
# ════════════════════════════════════════════════════════════

class RetrievalResult:
    """Structured retrieval output with dual layers."""

    def __init__(self):
        self.planning_cards: list[ExperienceCard] = []
        self.execution_cards: list[ExperienceCard] = []
        self.gated_out: list[tuple[ExperienceCard, str]] = []
        # v4.1: graph-expanded cards tracked separately
        self.graph_expanded: list[ExperienceCard] = []
        # v5.010 P1-SF/SEP-2: 检索Grounding监控
        self.total_candidates: int = 0
        self.avg_score: float = 0.0
        self.top_score: float = 0.0
        self.regime_matched: int = 0

    @property
    def all_cards(self) -> list[ExperienceCard]:
        return self.planning_cards + self.execution_cards

    @property
    def all_ids(self) -> list[str]:
        return [c.id for c in self.all_cards]

    def grounding_report(self) -> dict:
        """v5.010 P1-SF/SEP-2: 检索Grounding可观察报告"""
        total = len(self.all_cards)
        return {
            "candidates_scanned": self.total_candidates,
            "cards_returned": total,
            "gated_out": len(self.gated_out),
            "graph_expanded": len(self.graph_expanded),
            "avg_score": round(self.avg_score, 4),
            "top_score": round(self.top_score, 4),
            "regime_matched": self.regime_matched,
            "hit_rate": round(total / max(self.total_candidates, 1), 4),
        }

    def summary(self) -> str:
        gated = len(self.gated_out)
        graph = len(self.graph_expanded)
        base = (
            f"Planning: {len(self.planning_cards)} | "
            f"Execution: {len(self.execution_cards)} | "
            f"Gated out: {gated}"
        )
        if graph > 0:
            base += f" | Graph-expanded: {graph}"
        if self.total_candidates > 0:
            base += f" | Grounding: {self.avg_score:.2f}avg/{self.top_score:.2f}top"
        return base


# ════════════════════════════════════════════════════════════
# Retriever
# ════════════════════════════════════════════════════════════

class Retriever:
    """
    v4.85 Retriever: hierarchical priority + anchor alignment + dual-layer + graph-hop.

    v4.85 additions (AdaptiveNN coarse-to-fine):
      - layer_priority weight: C1 direction(1.3x) > C2 project(1.0x) > C3 exec(0.7x)
      - Human Anchor cards: 2.5x boost — never buried by execution detail noise
      - anchor_aligned gate: misaligned cards downweighted to 0.3x
      - Active pause: if anchor confidence < threshold, retrieval warns caller

    Scoring:
      base = keyword*0.30 + embedding*0.25 + confidence*0.15
             + status*0.10 + freshness*0.10 + downstream*0.10
      layer_mult  = {1:0.7, 2:1.0, 3:1.3}[layer_priority]
      anchor_mult = 2.5 if is_human_anchor else 1.0
      align_mult  = 1.0 if anchor_aligned else 0.3
      reuse_penalty = log2(use_count+1) * 0.05
      final = base * layer_mult * anchor_mult * align_mult - reuse_penalty

    v4.1 additions:
      - graph_expand(): 1-hop along parent/supersedes/related edges
      - retrieve_for_step(): SWE-Pruner style step-level filtering
      - EmbedderFactory: auto-select best available embedder
      - downstream_impact in scoring
    """

    PLANNING_TYPES = {ExperienceType.CROSSOVER, ExperienceType.SUCCESS}
    EXECUTION_TYPES = {ExperienceType.MUTATION, ExperienceType.FAILURE,
                       ExperienceType.PARTIAL}

    def __init__(self, store: GlobalMemory, config: GCCConfig | None = None,
                 current_regime: str = ""):
        self.store = store
        self.current_regime = current_regime  # v5.010 P1-THGNN-2: 市场状态匹配
        self.top_k = (config.retrieval_top_k if config else 5)
        self.graph_hop_depth = (
            getattr(config, 'graph_hop_depth', 1) if config else 1)
        self.embedder = EmbedderFactory.create(config)

    # ════════════════════════════════════════════════════════
    # Dual-layer Retrieval (v4.0, from Agent KB)
    # ════════════════════════════════════════════════════════

    def retrieve_dual(self, task: str, project: str | None = None,
                      top_k: int | None = None,
                      cross_key: bool = False) -> RetrievalResult:
        """
        Two-stage retrieval + v4.1 graph expansion + v4.97 LLM re-ranking.
        v5.010 P0-StockMem-1: cross_key=True 解锁跨KEY全库检索
        """
        k = top_k or self.top_k
        result = RetrievalResult()

        candidates = self._get_candidates(project, cross_key=cross_key)
        if not candidates:
            return result

        q_emb = self.embedder.embed(task)
        q_kw = set(re.findall(r'\w{3,}', task.lower()))

        scored: list[tuple[float, ExperienceCard]] = []
        for card in candidates:
            score = self._score(card, q_emb, q_kw)
            scored.append((score, card))
        scored.sort(key=lambda x: x[0], reverse=True)

        # v5.010 P1-SF/SEP-2: Grounding监控数据
        result.total_candidates = len(candidates)
        if scored:
            scores_only = [s for s, _ in scored]
            result.top_score = scores_only[0]
            result.avg_score = sum(scores_only) / len(scores_only)
            result.regime_matched = sum(
                1 for _, c in scored
                if getattr(c, 'market_regime', '') == self.current_regime
                and self.current_regime
            )

        planning_pool = [(s, c) for s, c in scored
                         if c.exp_type in self.PLANNING_TYPES]
        execution_pool = [(s, c) for s, c in scored
                          if c.exp_type in self.EXECUTION_TYPES]

        for s, c in scored:
            if (c.exp_type not in self.PLANNING_TYPES
                    and c.exp_type not in self.EXECUTION_TYPES):
                if c.strategy and len(c.strategy) > 20:
                    planning_pool.append((s, c))
                else:
                    execution_pool.append((s, c))

        plan_k = max(1, int(k * 0.4))
        exec_k = k - plan_k

        # v4.97: Re-rank 前先取 3× 候选，再通过 LLM 精选
        plan_selected  = self._rerank(self._diversify(planning_pool,  plan_k  * 3), task, plan_k)
        exec_selected  = self._rerank(self._diversify(execution_pool, exec_k  * 3), task, exec_k)

        # v4.1: Graph expansion
        graph_extra = self._graph_expand(
            plan_selected + exec_selected, candidates, k)
        result.graph_expanded = graph_extra

        all_selected_ids = {c.id for c in plan_selected + exec_selected}
        for card in graph_extra:
            if card.id not in all_selected_ids:
                if card.exp_type in self.PLANNING_TYPES:
                    plan_selected.append(card)
                else:
                    exec_selected.append(card)
                all_selected_ids.add(card.id)

        # Disagreement gate
        all_selected = plan_selected + exec_selected
        for card in all_selected:
            passed, reason = self._disagreement_gate(card, task, q_kw)
            if passed:
                if card in plan_selected:
                    result.planning_cards.append(card)
                else:
                    result.execution_cards.append(card)
            else:
                result.gated_out.append((card, reason))

        for card in result.all_cards:
            self.store.increment_use(card.id)

        return result

    # ════════════════════════════════════════════════════════
    # v4.97: LLM Re-ranking  (#05 RAG: Lewis et al. NeurIPS 2020)
    # ════════════════════════════════════════════════════════

    def _rerank(
        self,
        candidates: list[ExperienceCard],
        task: str,
        top_k: int,
    ) -> list[ExperienceCard]:
        """
        v4.97 — RAG Re-ranking (#05 RAG NeurIPS 2020 缺口修复)

        原论文：检索 top-k 后用模型打分重排，GCC 4.96 只取 top-k 直接注入。
        修复：先取 top-(3×k) 候选，LLM 打分选 top-k，无 LLM 时直接返回前 k 个。

        只在候选数量 > top_k 且有 LLM 时才触发，保证零副作用。
        """
        if len(candidates) <= top_k:
            return candidates

        # 无 LLM → 直接返回前 k 个（向后兼容）
        llm = self._get_llm()
        if not llm:
            return candidates[:top_k]

        # 构造打分 prompt
        card_lines = []
        for i, c in enumerate(candidates, 1):
            ki = (c.key_insight or c.strategy or "")[:100]
            t  = c.exp_type.value if hasattr(c.exp_type, "value") else str(c.exp_type)
            sr = ""
            if hasattr(c, "self_reflection") and c.self_reflection:
                sr = f" [reflection: {c.self_reflection[:50]}]"
            card_lines.append(f"[{i}] [{t}] {ki}{sr}")

        system = """你是检索重排引擎。
给定一个任务描述和若干候选经验卡，返回最相关的卡片编号列表（JSON 数组）。
只输出 JSON，例如：[2, 5, 1]
要求：按相关性从高到低排序，只选 {k} 个。""".replace("{k}", str(top_k))

        user = (
            f"任务: {task[:200]}\n\n"
            + "候选经验卡:\n"
            + "\n".join(card_lines)
            + f"\n\n请选出最相关的 {top_k} 个，输出编号 JSON 数组。"
        )

        try:
            raw = llm.generate(system=system, user=user,
                               temperature=0.1, max_tokens=100, repeat=2)
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            import json as _json
            indices = _json.loads(raw)
            result = []
            seen = set()
            for idx in indices:
                i = int(idx) - 1
                if 0 <= i < len(candidates) and i not in seen:
                    result.append(candidates[i])
                    seen.add(i)
                if len(result) >= top_k:
                    break
            # 如果 LLM 返回结果不够，补齐
            for i, c in enumerate(candidates):
                if len(result) >= top_k:
                    break
                if i not in seen:
                    result.append(c)
            return result
        except Exception as e:
            logger.warning("[RETRIEVER] LLM re-ranking failed, using default order: %s", e)
            return candidates[:top_k]

    def _get_llm(self):
        """懒加载 LLM（复用 GCCConfig）。"""
        if hasattr(self, "_llm") and self._llm:
            return self._llm
        try:
            from .config import GCCConfig
            from .llm_client import LLMClient
            cfg = GCCConfig.load()
            if cfg.llm_api_key:
                self._llm = LLMClient(cfg)
                return self._llm
        except Exception as e:
            logger.warning("[RETRIEVER] LLM client initialization failed: %s", e)
        return None

    def retrieve(self, query: str, top_k: int | None = None,
                 project: str | None = None,
                 cross_key: bool = False) -> list[ExperienceCard]:
        """Backward-compatible single-layer retrieve."""
        result = self.retrieve_dual(query, project=project, top_k=top_k,
                                    cross_key=cross_key)
        return result.all_cards

    # ════════════════════════════════════════════════════════
    # v4.1: Graph-Aware Retrieval (from ARG-Designer)
    # ════════════════════════════════════════════════════════

    def _graph_expand(self, selected: list[ExperienceCard],
                      all_candidates: list[ExperienceCard],
                      budget: int) -> list[ExperienceCard]:
        """
        1-hop expansion along experience graph edges.
        Walks: parent_id, supersedes_id, related_ids, children.
        """
        if self.graph_hop_depth <= 0:
            return []

        selected_ids = {c.id for c in selected}
        candidate_map = {c.id: c for c in all_candidates}
        expanded: list[ExperienceCard] = []

        for card in selected:
            if len(expanded) + len(selected) >= budget * 2:
                break

            neighbor_ids: list[str] = []
            if card.parent_id and card.parent_id not in selected_ids:
                neighbor_ids.append(card.parent_id)
            if card.supersedes_id and card.supersedes_id not in selected_ids:
                neighbor_ids.append(card.supersedes_id)
            # v5.010 P2-THGNN-2: related_ids最多展开3个，避免过度扩展
            for rid in card.related_ids[:3]:
                if rid not in selected_ids:
                    neighbor_ids.append(rid)

            children = self.store.get_children(card.id)
            for child in children:
                if child.id not in selected_ids:
                    neighbor_ids.append(child.id)

            for nid in neighbor_ids:
                if nid in selected_ids:
                    continue
                neighbor = candidate_map.get(nid) or self.store.get(nid)
                if neighbor and neighbor.status != CardStatus.DEPRECATED:
                    # v5.050 P2-THGNN-2: 同体制邻居优先，不同体制降低优先级
                    n_regime = getattr(neighbor, 'market_regime', '')
                    if self.current_regime and n_regime and n_regime != self.current_regime:
                        # 不同体制放到末尾（仍可扩展，只是优先级低）
                        expanded.append(neighbor)
                    else:
                        expanded.insert(0, neighbor)
                    selected_ids.add(nid)

        return expanded

    # ════════════════════════════════════════════════════════
    # v4.1: Goal-Aware Step Retrieval (from SWE-Pruner)
    # ════════════════════════════════════════════════════════

    def retrieve_for_step(self, step_goal: str, task_context: str = "",
                          project: str | None = None,
                          top_k: int = 2,
                          cross_key: bool = False) -> RetrievalResult:
        """
        Step-level retrieval with goal-aware pruning.
        Combines task_context (broad) + step_goal (specific).
        Stricter relevance threshold than session-level retrieval.
        v5.010 P0-StockMem-1: cross_key=True 跨KEY检索
        """
        result = RetrievalResult()
        candidates = self._get_candidates(project, cross_key=cross_key)
        if not candidates:
            return result

        combined_query = f"{task_context} {step_goal}".strip() or step_goal
        q_emb = self.embedder.embed(combined_query)
        step_kw = set(re.findall(r'\w{3,}', step_goal.lower()))
        task_kw = set(re.findall(r'\w{3,}', task_context.lower()))

        scored: list[tuple[float, ExperienceCard]] = []
        for card in candidates:
            score = self._score(card, q_emb, step_kw | task_kw)
            step_boost = self._goal_relevance(card, step_kw)
            final = score + step_boost * 0.15
            scored.append((final, card))

        scored.sort(key=lambda x: x[0], reverse=True)

        # Stricter pruning threshold
        threshold = 0.15
        pruned = [(s, c) for s, c in scored if s >= threshold]

        selected = self._diversify(pruned, top_k)

        # Graph expand
        graph_extra = self._graph_expand(selected, candidates, top_k)
        result.graph_expanded = graph_extra

        selected_ids = {c.id for c in selected}
        for card in graph_extra:
            if card.id not in selected_ids:
                selected.append(card)
                selected_ids.add(card.id)

        # Gate
        for card in selected:
            passed, reason = self._disagreement_gate(
                card, step_goal, step_kw)
            if passed:
                if card.exp_type in self.PLANNING_TYPES:
                    result.planning_cards.append(card)
                else:
                    result.execution_cards.append(card)
            else:
                result.gated_out.append((card, reason))

        # v5.010 P1-GA-1: 检索命中后更新last_used (与retrieve_dual一致)
        for card in result.all_cards:
            self.store.increment_use(card.id)

        return result

    def _goal_relevance(self, card: ExperienceCard,
                        goal_kw: set[str]) -> float:
        """Score how relevant a card is to a specific step goal."""
        if not goal_kw:
            return 0.0
        card_kw = set(re.findall(r'\w{3,}',
                                  card.searchable_text().lower()))
        if not card_kw:
            return 0.0
        overlap = len(goal_kw & card_kw)
        return min(1.0, overlap / max(len(goal_kw), 1))

    # ════════════════════════════════════════════════════════
    # Disagreement Gate (v4.0, from Agent KB)
    # ════════════════════════════════════════════════════════

    def _disagreement_gate(self, card: ExperienceCard, task: str,
                           task_kw: set[str]) -> tuple[bool, str]:
        """Rule-based contradiction check."""
        card_kw = set(re.findall(r'\w{3,}',
                                  card.searchable_text().lower()))
        if task_kw and card_kw:
            overlap = len(task_kw & card_kw) / max(len(task_kw), 1)
            if overlap < 0.05:
                return False, (f"low relevance "
                               f"({overlap:.0%} keyword overlap)")

        if card.exp_type == ExperienceType.FAILURE:
            if card.trigger_symptom:
                trigger_words = set(re.findall(
                    r'\w{3,}', card.trigger_symptom.lower()))
                if trigger_words & task_kw:
                    return True, ""

        if card.strategy:
            avoid_phrases = ["avoid", "don't", "do not", "never",
                             "remove", "disable"]
            implement_phrases = ["implement", "add", "enable", "use",
                                 "apply", "create"]

            strat_lower = card.strategy.lower()
            has_avoid = any(p in strat_lower for p in avoid_phrases)

            if has_avoid:
                avoid_words = set(re.findall(r'\w{3,}', strat_lower))
                implement_words = set()
                for phrase in implement_phrases:
                    if phrase in task.lower():
                        idx = task.lower().find(phrase)
                        after = task[idx:idx+60]
                        implement_words.update(
                            re.findall(r'\w{3,}', after.lower()))

                contradiction = (avoid_words & implement_words
                                 - {"the", "and", "for"})
                if len(contradiction) >= 2:
                    return False, (
                        f"contradicts task "
                        f"(avoid vs implement: {contradiction})")

        return True, ""

    # ════════════════════════════════════════════════════════
    # Verification-First Context (v4.0, from VF paper)
    # ════════════════════════════════════════════════════════

    def get_context(self, task: str, project: str | None = None,
                    mode: str = "verify") -> str:
        """mode="verify" (VF) | mode="reference" (legacy)"""
        result = self.retrieve_dual(task, project=project)
        if not result.all_cards:
            return ""
        if mode == "verify":
            return self._format_verify_first(result, task)
        else:
            return self._format_reference(result)

    def get_step_context(self, step_goal: str, task_context: str = "",
                         project: str | None = None,
                         mode: str = "verify") -> str:
        """v4.1: Goal-aware step-level context generation."""
        result = self.retrieve_for_step(
            step_goal, task_context=task_context, project=project)
        if not result.all_cards:
            return ""
        if mode == "verify":
            return self._format_verify_first(result, step_goal)
        else:
            return self._format_reference(result)

    def _format_verify_first(self, result: RetrievalResult,
                             task: str) -> str:
        lines = [
            "═══ EXPERIENCE VERIFICATION REQUIRED ═══",
            f"Task: {task}",
            "",
            "Before proceeding, verify each experience below.",
            "For each: (1) Does it apply to this task? "
            "(2) Should you follow it?",
            "State your verification, then proceed with the task.",
            "",
        ]

        if result.planning_cards:
            lines.append("── Planning Guidance (workflow-level) ──")
            lines.append(
                "Verify: Does this overall approach fit your task?\n")
            for i, card in enumerate(result.planning_cards, 1):
                lines.append(f"  [P{i}] {card.to_context_string()}")
                lines.append("")

        if result.execution_cards:
            lines.append("── Execution Details (step-level) ──")
            lines.append(
                "Verify: Are these specific warnings/tips relevant?\n")
            for i, card in enumerate(result.execution_cards, 1):
                lines.append(f"  [E{i}] {card.to_context_string()}")
                lines.append("")

        if result.gated_out:
            lines.append(
                f"── {len(result.gated_out)} experience(s) filtered out ──")
            for card, reason in result.gated_out:
                lines.append(
                    f"  [SKIP] {card.key_insight[:50]}... ({reason})")
            lines.append("")

        if result.graph_expanded:
            lines.append(
                f"── {len(result.graph_expanded)} card(s) "
                f"via graph expansion ──")
            lines.append("")

        lines.append("═══ END — Now verify above, then proceed ═══")
        return "\n".join(lines)

    def _format_reference(self, result: RetrievalResult) -> str:
        cards = result.all_cards
        lines = [
            "═══ Experience from previous sessions ═══",
            f"({len(cards)} relevant experiences found)\n",
        ]
        for i, card in enumerate(cards, 1):
            lines.append(f"--- Experience {i} ---")
            lines.append(card.to_context_string())
            lines.append("")
        lines.append("═══ End of experience context ═══")
        return "\n".join(lines)

    def ensure_embeddings(self) -> int:
        """Backfill embeddings for cards missing them."""
        all_cards = self.store.get_all(limit=100000)
        updated = 0
        for card in all_cards:
            if card.embedding:
                continue
            card.embedding = self.embedder.embed(card.searchable_text())
            self.store.store(card)
            updated += 1
        return updated

    def reembed_all(self) -> int:
        """
        v4.1: Re-embed all cards with current embedder.
        Useful after upgrading from LocalEmbedder to SemanticEmbedder.
        """
        all_cards = self.store.get_all(limit=100000)
        count = 0
        for card in all_cards:
            new_emb = self.embedder.embed(card.searchable_text())
            if new_emb:
                card.embedding = new_emb
                self.store.store(card)
                count += 1
        return count

    # ════════════════════════════════════════════════════════
    # Internal helpers
    # ════════════════════════════════════════════════════════

    def _get_candidates(self, project: str | None,
                        cross_key: bool = False) -> list[ExperienceCard]:
        """v5.010 P0-StockMem-1: cross_key=True 跳过project过滤，全库检索"""
        candidates = self.store.get_all(limit=500)
        if project and not cross_key:
            proj_match = [c for c in candidates
                          if project.lower() in (c.project or "").lower()]
            if proj_match:
                candidates = proj_match
        return [c for c in candidates
                if c.status != CardStatus.DEPRECATED]

    def _score(self, card: ExperienceCard, q_emb: list[float],
               q_kw: set[str]) -> float:
        card_text = card.searchable_text().lower()
        card_kw = set(re.findall(r'\w{3,}', card_text))
        kw_score = ((len(q_kw & card_kw) / max(len(q_kw | card_kw), 1))
                     if q_kw and card_kw else 0.0)

        if not card.embedding:
            card.embedding = self.embedder.embed(card.searchable_text())
        emb_score = self._cosine(q_emb, card.embedding)

        conf = self._effective_confidence(card)

        status_score = {
            "archived": 1.0, "validated": 0.9, "active": 0.6,
            "draft": 0.3, "deprecated": 0.0,
        }.get(card.status.value, 0.3)

        freshness = self._freshness_score(card)

        # v4.1: downstream impact boost
        # v5.050 P1-DATA-5: downstream_avg<0.3时降权(低相关性)
        raw_downstream = card.downstream_avg if card.downstream_avg > 0 else 0.0
        if 0 < raw_downstream < 0.3 and len(card.downstream_scores) >= 3:
            downstream = raw_downstream * 0.5   # 低相关性降权
        else:
            downstream = min(1.0, raw_downstream)

        # v5.010 P0-GA-2: LLM重要性评分权重 (GA论文2304.03442)
        importance = getattr(card, 'importance_score', 0.5)

        # v5.010 P0-GA-2: 权重重构 — embedding>keyword, +importance
        base_score = (
            emb_score * 0.30 + kw_score * 0.25 + conf * 0.15
            + importance * 0.10 + status_score * 0.08
            + freshness * 0.07 + downstream * 0.05
        )

        # v5.010 P0-THGNN-1: ExperienceType分路由检索权重
        TYPE_WEIGHTS = {
            "success": 1.0, "crossover": 1.0, "mutation": 0.85,
            "partial": 0.7, "failure": 0.6,
        }
        type_mult = TYPE_WEIGHTS.get(card.exp_type.value, 0.8)

        # v5.010 P1-THGNN-2: 市场状态匹配加分
        regime_mult = 1.0
        card_regime = getattr(card, 'market_regime', '')
        if self.current_regime and card_regime:
            regime_mult = 1.15 if card_regime == self.current_regime else 0.9

        # v4.85: Hierarchical priority weights (AdaptiveNN coarse-to-fine)
        # Direction layer (C1) > Project layer (C2) > Execution layer (C3)
        layer = getattr(card, 'layer_priority', 2)
        layer_mult = {1: 0.7, 2: 1.0, 3: 1.3}.get(layer, 1.0)

        # Human Anchor cards get maximum priority — never buried by detail noise
        anchor_mult = 2.5 if getattr(card, 'is_human_anchor', False) else 1.0

        # Cards misaligned with current Human Anchor direction are down-weighted
        aligned = getattr(card, 'anchor_aligned', True)
        align_mult = 1.0 if aligned else 0.3

        reuse_penalty = math.log2(max(card.use_count, 0) + 1) * 0.05
        return max(0.0, base_score * type_mult * regime_mult * layer_mult
                   * anchor_mult * align_mult - reuse_penalty)

    def _effective_confidence(self, card: ExperienceCard) -> float:
        if not card.last_validated:
            return card.confidence
        try:
            validated = datetime.fromisoformat(card.last_validated)
            now = datetime.now(timezone.utc)
            days = (now - validated).days
            decay = days * card.decay_rate
            return max(0.1, card.confidence - decay)
        except (ValueError, TypeError):
            return card.confidence

    @staticmethod
    def _freshness_score(card: ExperienceCard) -> float:
        """v5.010 P0-GA-1: 优先last_used + 指数衰减 (GA论文2304.03442)"""
        import math
        try:
            ref_time = card.last_used or card.created_at
            t = datetime.fromisoformat(ref_time)
            now = datetime.now(timezone.utc)
            days = max(0, (now - t).days)
            return max(0.05, math.exp(-0.01 * days))
        except (ValueError, TypeError):
            return 0.5

    @staticmethod
    def _diversify(scored: list[tuple[float, ExperienceCard]],
                   k: int) -> list[ExperienceCard]:
        if not scored:
            return []
        max_per_type = max(2, int(k * 0.6))
        type_counts: dict[str, int] = {}
        results: list[ExperienceCard] = []
        for score, card in scored:
            if len(results) >= k:
                break
            t = card.exp_type.value
            if type_counts.get(t, 0) >= max_per_type:
                continue
            type_counts[t] = type_counts.get(t, 0) + 1
            results.append(card)
        return results

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        if len(a) != len(b) or not a:
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(x * x for x in b))
        if na == 0 or nb == 0:
            return 0.0
        return max(0.0, dot / (na * nb))
