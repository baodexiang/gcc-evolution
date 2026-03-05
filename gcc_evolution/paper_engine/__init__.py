"""
Paper Engine — Main Entry Point
================================
Universal multi-source academic paper retrieval + knowledge card generation.

FARS-inspired pipeline:
  Topic → multi-query expansion → parallel multi-source fetch
       → dedup → rank → knowledge card generation → DuckDB storage

Quick start:
    from paper_engine import PaperResearcher
    
    researcher = PaperResearcher(domain="gcc")
    cards = await researcher.research("agentic AI memory systems", top_k=20)
    for card in cards:
        print(card.to_markdown())
"""
import asyncio
import sys, os

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "core"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "sources"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "domains"))

from typing import List, Dict, Any, Optional, Callable

from core.base_source import BaseSource, Paper
from core.engine import PaperEngine
from core.knowledge_card import KnowledgeCard, KnowledgeCardGenerator
from domains.registry import get_domain, list_domains, register_domain, DomainConfig

from sources.arxiv_source import ArxivSource
from sources.semantic_scholar_source import SemanticScholarSource
from sources.openalex_source import OpenAlexSource
from sources.crossref_source import CrossrefSource
from sources.pubmed_source import PubMedSource
from sources.ssrn_source import SSRNSource


# Source class registry
SOURCE_CLASSES = {
    "arxiv":            ArxivSource,
    "semantic_scholar": SemanticScholarSource,
    "openalex":         OpenAlexSource,
    "crossref":         CrossrefSource,
    "pubmed":           PubMedSource,
    "ssrn":             SSRNSource,
}


class PaperResearcher:
    """
    High-level API: topic → papers → knowledge cards.
    
    Example:
        researcher = PaperResearcher(
            domain="gcc",
            llm_client=my_llm,          # optional, for card extraction
            source_configs={
                "semantic_scholar": {"api_key": "YOUR_KEY"},
                "openalex": {"email": "you@example.com"},
            }
        )
        cards = await researcher.research("persistent memory for LLM agents", top_k=15)
    """

    def __init__(
        self,
        domain: str = "general",
        llm_client: Optional[Callable] = None,
        source_configs: Optional[Dict[str, Dict]] = None,
        custom_domain: Optional[DomainConfig] = None,
    ):
        self.domain_config = custom_domain or get_domain(domain)
        self.llm_client = llm_client
        self.source_configs = source_configs or {}

        # Build enabled sources
        sources = self._build_sources()

        # Build engine with domain scoring weights
        engine_config = dict(self.domain_config.scoring_weights)
        self.engine = PaperEngine(sources=sources, config=engine_config)

        # Card generator
        self.card_gen = KnowledgeCardGenerator(
            llm_client=llm_client,
            config={"default_domain": self.domain_config.card_domain_label},
        )

    async def research(
        self,
        topic: str,
        top_k: Optional[int] = None,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
        generate_cards: bool = True,
        expand_citations: bool = False,
        citation_top_k: int = 5,
    ) -> List[KnowledgeCard]:
        """
        Full pipeline: topic → knowledge cards.
        
        Args:
            topic: Research topic or question
            top_k: Override domain default top_k
            year_from / year_to: Override domain default year range
            generate_cards: Whether to generate knowledge cards (requires LLM for best results)
            expand_citations: Also pull papers that cite the top results (S2 only)
            citation_top_k: How many citation-expanded papers to include
        
        Returns:
            List of KnowledgeCard objects, ranked by relevance
        """
        top_k = top_k or self.domain_config.top_k
        year_from = year_from or self.domain_config.default_year_from
        year_to = year_to or self.domain_config.default_year_to

        # Step 1: Multi-query expansion
        queries = self.domain_config.build_queries(topic)
        print(f"[{self.domain_config.name}] Searching with {len(queries)} query variants...")

        # Step 2: Multi-source parallel search
        source_filters = self.domain_config.to_source_filter_map()
        papers = await self.engine.multi_query_search(
            queries=queries,
            top_k=top_k,
            year_from=year_from,
            year_to=year_to,
            source_filters=source_filters,
        )
        print(f"[{self.domain_config.name}] Retrieved {len(papers)} papers after dedup+rank")

        # Step 3: Optional citation expansion
        if expand_citations and papers:
            top_papers = papers[:min(5, len(papers))]
            expanded = await self.engine.expand_by_citations(
                seed_papers=top_papers,
                top_k=citation_top_k,
            )
            print(f"[{self.domain_config.name}] Citation expansion: +{len(expanded)} papers")
            papers.extend(expanded)
            # Re-rank
            papers = self.engine._score_papers(papers, topic)
            papers.sort(key=lambda p: p.combined_score, reverse=True)
            papers = papers[:top_k]

        if not generate_cards:
            # Return papers as minimal cards
            return [self._paper_to_minimal_card(p) for p in papers]

        # Step 4: Generate knowledge cards
        print(f"[{self.domain_config.name}] Generating {len(papers)} knowledge cards...")
        cards = self.card_gen.generate_batch(
            papers=papers,
            domain=self.domain_config.card_domain_label,
        )
        print(f"[{self.domain_config.name}] Done. {len(cards)} cards generated.")
        return cards

    async def search_papers_only(
        self,
        topic: str,
        top_k: Optional[int] = None,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
    ) -> List[Paper]:
        """Return raw Paper objects (no card generation)."""
        top_k = top_k or self.domain_config.top_k
        year_from = year_from or self.domain_config.default_year_from
        queries = self.domain_config.build_queries(topic)
        source_filters = self.domain_config.to_source_filter_map()
        return await self.engine.multi_query_search(
            queries=queries,
            top_k=top_k,
            year_from=year_from,
            year_to=year_to,
            source_filters=source_filters,
        )

    def _build_sources(self) -> List[BaseSource]:
        """Instantiate enabled source objects from domain config."""
        sources = []
        for name in self.domain_config.enabled_sources:
            cls = SOURCE_CLASSES.get(name)
            if cls is None:
                print(f"[Warning] Unknown source: {name}")
                continue
            cfg = self.source_configs.get(name, {})
            cfg["enabled"] = True
            sources.append(cls(config=cfg))
        return sources

    def _paper_to_minimal_card(self, paper: Paper) -> KnowledgeCard:
        """Create a minimal card without LLM extraction."""
        return self.card_gen.generate_card(paper)


# ─────────────────────────────────────────────
# Convenience functions
# ─────────────────────────────────────────────

async def quick_search(
    topic: str,
    domain: str = "general",
    top_k: int = 10,
    llm_client=None,
    source_configs: Dict = None,
) -> List[KnowledgeCard]:
    """One-shot research function."""
    researcher = PaperResearcher(
        domain=domain,
        llm_client=llm_client,
        source_configs=source_configs or {},
    )
    return await researcher.research(topic, top_k=top_k)


def get_available_domains() -> List[str]:
    return list_domains()


def create_custom_domain(
    name: str,
    description: str,
    sources: List[str],
    arxiv_categories: List[str] = None,
    query_templates: List[str] = None,
    year_from: int = 2020,
    **kwargs,
) -> DomainConfig:
    """Helper to quickly create a custom domain config."""
    source_filters = {}
    if arxiv_categories and "arxiv" in sources:
        source_filters["arxiv"] = {"categories": arxiv_categories}

    templates = query_templates or ["{topic}", "{topic} machine learning"]

    config = DomainConfig(
        name=name,
        description=description,
        enabled_sources=sources,
        source_filters=source_filters,
        query_templates=templates,
        default_year_from=year_from,
        **kwargs,
    )
    register_domain(config)
    return config


# ─────────────────────────────────────────────
# CLI runner
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Paper Engine CLI")
    parser.add_argument("topic", help="Research topic")
    parser.add_argument("--domain", default="general", help=f"Domain: {get_available_domains()}")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--year-from", type=int)
    parser.add_argument("--output", choices=["markdown", "json"], default="markdown")
    args = parser.parse_args()

    async def run():
        researcher = PaperResearcher(domain=args.domain)
        cards = await researcher.research(
            topic=args.topic,
            top_k=args.top_k,
            year_from=args.year_from,
            generate_cards=True,
        )
        if args.output == "json":
            print(json.dumps([c.to_dict() for c in cards], indent=2, ensure_ascii=False))
        else:
            for i, card in enumerate(cards, 1):
                print(f"\n{'='*60}")
                print(f"#{i} Score: {card.relevance_scores}")
                print(card.to_markdown())

    asyncio.run(run())
