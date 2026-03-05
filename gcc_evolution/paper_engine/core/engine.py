"""
Paper Engine Core — orchestrates multi-source search, dedup, ranking.
FARS-inspired: parallel fetch → merge → rank → structured output
"""
import asyncio
import hashlib
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
import re

import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from base_source import BaseSource, Paper


class PaperEngine:
    """
    Universal multi-source paper retrieval and ranking engine.
    
    Flow (FARS-inspired):
    Query → [multi-source parallel fetch] → dedup → score → rank → output
    """

    def __init__(
        self,
        sources: List[BaseSource],
        config: Dict[str, Any] = None,
    ):
        self.sources = [s for s in sources if s.is_enabled()]
        self.config = config or {}

        # Scoring weights (tunable per domain)
        self.w_relevance  = self.config.get("w_relevance",  0.50)
        self.w_recency    = self.config.get("w_recency",    0.25)
        self.w_citation   = self.config.get("w_citation",   0.15)
        self.w_source_pri = self.config.get("w_source_pri", 0.10)

        # Source priority (higher = preferred when deduplicating)
        self.source_priority = self.config.get("source_priority", {
            "arxiv":            1.0,
            "semantic_scholar": 0.9,
            "openalex":         0.8,
            "crossref":         0.7,
            "pubmed":           0.9,
            "ssrn":             0.8,
        })

        self.current_year = datetime.now().year

    # ─────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────

    async def search(
        self,
        query: str,
        max_results_per_source: int = 20,
        top_k: int = 30,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
        source_filters: Optional[Dict[str, Dict]] = None,
        deduplicate: bool = True,
    ) -> List[Paper]:
        """
        Search across all enabled sources in parallel.

        Args:
            query: Natural language or keyword query
            max_results_per_source: How many to fetch from each source
            top_k: Final number of results to return after ranking
            year_from / year_to: Optional year range filter
            source_filters: Per-source extra_filters dict
              e.g. {"arxiv": {"categories": ["cs.AI"]}, "pubmed": {"free_full_text": True}}
            deduplicate: Merge papers appearing in multiple sources

        Returns:
            Ranked list of Paper objects
        """
        source_filters = source_filters or {}

        # Parallel fetch from all sources
        tasks = []
        for source in self.sources:
            extra = source_filters.get(source.name, {})
            tasks.append(
                self._safe_search(
                    source, query, max_results_per_source,
                    year_from, year_to, extra
                )
            )

        results = await asyncio.gather(*tasks)

        # Flatten
        all_papers: List[Paper] = []
        for source_papers in results:
            all_papers.extend(source_papers)

        # Dedup
        if deduplicate:
            all_papers = self._deduplicate(all_papers)

        # Score
        all_papers = self._score_papers(all_papers, query)

        # Sort by combined score
        all_papers.sort(key=lambda p: p.combined_score, reverse=True)

        return all_papers[:top_k]

    async def multi_query_search(
        self,
        queries: List[str],
        top_k: int = 30,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
        source_filters: Optional[Dict[str, Dict]] = None,
    ) -> List[Paper]:
        """
        Run multiple query variants and merge results.
        Useful for FARS-style: keyword + semantic + citation-based queries.
        """
        tasks = [
            self.search(q, top_k=top_k, year_from=year_from,
                       year_to=year_to, source_filters=source_filters)
            for q in queries
        ]
        results = await asyncio.gather(*tasks)

        # Merge all
        all_papers: List[Paper] = []
        seen = set()
        for source_papers in results:
            for p in source_papers:
                key = self._dedup_key(p)
                if key not in seen:
                    seen.add(key)
                    all_papers.append(p)

        # Re-rank merged set
        primary_query = queries[0]
        all_papers = self._score_papers(all_papers, primary_query)
        all_papers.sort(key=lambda p: p.combined_score, reverse=True)
        return all_papers[:top_k]

    async def expand_by_citations(
        self,
        seed_papers: List[Paper],
        depth: int = 1,
        top_k: int = 10,
    ) -> List[Paper]:
        """
        Citation graph expansion: find related papers via S2 citation links.
        Only works when SemanticScholarSource is present.
        """
        from sources.semantic_scholar_source import SemanticScholarSource
        s2 = next(
            (s for s in self.sources if isinstance(s, SemanticScholarSource)),
            None
        )
        if not s2:
            return []

        expanded = []
        seen_ids = {p.paper_id for p in seed_papers}

        async def expand_one(paper: Paper):
            tasks = [
                s2.fetch_citations(paper.paper_id, limit=top_k),
                s2.fetch_references(paper.paper_id, limit=top_k),
            ]
            citations, references = await asyncio.gather(*tasks)
            new_papers = []
            for p in citations + references:
                if p.paper_id not in seen_ids:
                    seen_ids.add(p.paper_id)
                    new_papers.append(p)
            return new_papers

        for paper in seed_papers:
            new = await expand_one(paper)
            expanded.extend(new)

        # Score expanded papers
        expanded = self._score_papers(expanded, query="")
        expanded.sort(key=lambda p: p.combined_score, reverse=True)
        return expanded[:top_k]

    # ─────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────

    async def _safe_search(
        self,
        source: BaseSource,
        query: str,
        max_results: int,
        year_from: Optional[int],
        year_to: Optional[int],
        extra_filters: Dict,
    ) -> List[Paper]:
        """Wrap source.search() with error handling."""
        try:
            papers = await source.search(
                query=query,
                max_results=max_results,
                year_from=year_from,
                year_to=year_to,
                extra_filters=extra_filters,
            )
            return papers or []
        except Exception as e:
            print(f"[{source.name}] search failed: {e}")
            return []

    def _dedup_key(self, paper: Paper) -> str:
        """Generate a canonical dedup key for a paper."""
        # Priority: DOI > arxiv_id > normalized title
        if paper.doi:
            return f"doi:{paper.doi.lower().strip()}"
        if paper.arxiv_id:
            return f"arxiv:{paper.arxiv_id.split('v')[0]}"
        # Title normalization
        norm_title = re.sub(r"[^a-z0-9]", "", paper.title.lower())[:60]
        year_str = str(paper.year) if paper.year else "0000"
        return f"title:{norm_title}:{year_str}"

    def _deduplicate(self, papers: List[Paper]) -> List[Paper]:
        """
        Merge papers with the same DOI/arxiv_id/title.
        Prefer the version from the highest-priority source.
        """
        seen: Dict[str, Paper] = {}
        for paper in papers:
            key = self._dedup_key(paper)
            if key not in seen:
                seen[key] = paper
            else:
                existing = seen[key]
                # Prefer higher-priority source
                p_prio = self.source_priority.get(paper.source, 0.5)
                e_prio = self.source_priority.get(existing.source, 0.5)
                if p_prio > e_prio:
                    # Merge: keep new as base, fill gaps from existing
                    seen[key] = self._merge_papers(paper, existing)
                else:
                    seen[key] = self._merge_papers(existing, paper)

        return list(seen.values())

    def _merge_papers(self, primary: Paper, secondary: Paper) -> Paper:
        """Merge two representations of the same paper. Primary takes precedence."""
        # Fill missing fields from secondary
        if not primary.abstract and secondary.abstract:
            primary.abstract = secondary.abstract
        if not primary.doi and secondary.doi:
            primary.doi = secondary.doi
        if not primary.arxiv_id and secondary.arxiv_id:
            primary.arxiv_id = secondary.arxiv_id
        if not primary.pdf_url and secondary.pdf_url:
            primary.pdf_url = secondary.pdf_url
        if primary.citation_count == 0 and secondary.citation_count > 0:
            primary.citation_count = secondary.citation_count
        if not primary.venue and secondary.venue:
            primary.venue = secondary.venue
        # Merge tags
        combined_tags = list(set(primary.tags + secondary.tags))
        primary.tags = combined_tags
        return primary

    def _score_papers(self, papers: List[Paper], query: str) -> List[Paper]:
        """
        Score each paper on 3 dimensions → combine into final score.
        
        1. Relevance  — title/abstract keyword overlap with query (simple BM25-ish)
        2. Recency    — exponential decay by age
        3. Citation   — log-normalized citation count
        """
        if not papers:
            return papers

        query_tokens = set(re.findall(r"\w+", query.lower()))

        # Normalize citation counts (log scale)
        max_cit = max((p.citation_count for p in papers), default=1) or 1

        for paper in papers:
            # 1. Relevance score (token overlap)
            text = f"{paper.title} {paper.abstract}".lower()
            text_tokens = set(re.findall(r"\w+", text))
            if query_tokens:
                overlap = len(query_tokens & text_tokens) / len(query_tokens)
            else:
                overlap = 0.5  # no query → neutral
            paper.relevance_score = min(overlap * 1.5, 1.0)  # boost and cap

            # 2. Recency score (half-life = 3 years)
            if paper.year:
                age = max(0, self.current_year - paper.year)
                paper.recency_score = 0.5 ** (age / 3.0)
            else:
                paper.recency_score = 0.3

            # 3. Citation score (log-normalized)
            if paper.citation_count > 0:
                import math
                cit_score = math.log(paper.citation_count + 1) / math.log(max_cit + 1)
            else:
                cit_score = 0.0

            # 4. Source priority
            source_score = self.source_priority.get(paper.source, 0.5)

            # Combined
            paper.combined_score = (
                self.w_relevance  * paper.relevance_score
                + self.w_recency    * paper.recency_score
                + self.w_citation   * cit_score
                + self.w_source_pri * source_score
            )

        return papers
