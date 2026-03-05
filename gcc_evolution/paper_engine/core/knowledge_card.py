"""
Knowledge Card Generator
FARS-inspired: paper → structured, citable knowledge card with verifiable claims.
"""
import json
import hashlib
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
from datetime import datetime

import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from base_source import Paper


@dataclass
class KnowledgeCard:
    """
    Structured knowledge card with verifiable source attribution.
    Every claim traces back to a specific paper section.
    """
    # Identity
    card_id: str = ""
    created_at: str = ""

    # Content
    headline: str = ""              # one-sentence takeaway
    problem: str = ""               # what problem does this solve
    method: str = ""                # how — key technical approach
    result: str = ""                # quantified result if available
    limitation: str = ""            # stated limitations
    contribution: str = ""          # main contribution in own words
    tldr: str = ""                  # ultra-short (tweet-length)

    # Source (fully verifiable)
    source: Dict[str, Any] = field(default_factory=dict)
    # e.g. {
    #   "paper_id": "arxiv:2505.10468",
    #   "title": "...",
    #   "authors": [...],
    #   "year": 2025,
    #   "url": "https://...",
    #   "pdf_url": "https://...",
    #   "venue": "..."
    # }

    # Classification
    tags: List[str] = field(default_factory=list)
    domain: str = ""                # gcc | trading | medical | general

    # Applicability scores (0-1, domain-specific)
    relevance_scores: Dict[str, float] = field(default_factory=dict)
    # e.g. {"gcc": 0.9, "trading": 0.4}

    # Card relations (filled later by graph builder)
    related_card_ids: List[str] = field(default_factory=list)
    citation_count: int = 0

    # Raw paper data (for downstream reprocessing)
    raw_paper_id: str = ""

    def to_dict(self) -> Dict:
        return asdict(self)

    def to_markdown(self) -> str:
        lines = [
            f"# {self.headline}",
            "",
            f"**TL;DR**: {self.tldr}",
            "",
            "## Source",
            f"- **Paper**: [{self.source.get('title', '')}]({self.source.get('url', '')})",
            f"- **Authors**: {', '.join(self.source.get('authors', [])[:3])}{'...' if len(self.source.get('authors', [])) > 3 else ''}",
            f"- **Year**: {self.source.get('year', 'N/A')} | **Venue**: {self.source.get('venue', 'N/A')}",
            f"- **Citations**: {self.citation_count}",
            "",
            "## Structured Analysis",
            f"**Problem**: {self.problem}",
            "",
            f"**Method**: {self.method}",
            "",
            f"**Result**: {self.result}",
            "",
            f"**Limitation**: {self.limitation}",
            "",
            "## Tags",
            f"`{'` `'.join(self.tags)}`",
        ]
        if self.relevance_scores:
            lines += ["", "## Domain Relevance"]
            for domain, score in self.relevance_scores.items():
                bar = "█" * int(score * 10) + "░" * (10 - int(score * 10))
                lines.append(f"- **{domain}**: {bar} {score:.0%}")
        return "\n".join(lines)


class KnowledgeCardGenerator:
    """
    Converts Paper objects → KnowledgeCards via LLM extraction.
    Supports local LLM (DeepSeek/Qwen) or API (Claude/OpenAI).
    """

    EXTRACT_PROMPT = """You are a research analyst creating structured knowledge cards.

Given this paper's title and abstract, extract the following in JSON format:

Paper Title: {title}
Authors: {authors}
Year: {year}
Abstract: {abstract}

Extract and return ONLY valid JSON with these fields:
{{
  "headline": "One sentence capturing the core finding (max 20 words)",
  "tldr": "Tweet-length summary (max 280 chars)",
  "problem": "What specific problem does this paper solve?",
  "method": "What is the key technical approach or method? Be specific.",
  "result": "What are the quantified results? Include metrics/numbers if mentioned.",
  "limitation": "What are the main limitations acknowledged?",
  "contribution": "What is the main contribution to the field?",
  "tags": ["tag1", "tag2", "tag3"],
  "domain_relevance": {{
    "ai_research": 0.0,
    "trading_finance": 0.0,
    "industrial_automation": 0.0,
    "general_ml": 0.0
  }}
}}

Rules:
- result MUST include numbers/metrics if available (e.g., "improved by 12.3% on benchmark X")
- method should be specific, not generic (e.g., "multi-head cross-attention with positional bias" not "neural network")
- tags should be 3-8 specific technical terms
- domain_relevance scores from 0.0 to 1.0
- Return ONLY the JSON object, no other text"""

    def __init__(self, llm_client=None, config: Dict[str, Any] = None):
        """
        llm_client: any callable with signature:
            llm_client(prompt: str) -> str
        If None, uses a simple fallback (abstract-only card).
        """
        self.llm = llm_client
        self.config = config or {}
        self.default_domain = self.config.get("default_domain", "general")

    def generate_card(self, paper: Paper, domain: str = None) -> KnowledgeCard:
        """Generate a knowledge card from a Paper object."""
        domain = domain or self.default_domain
        card_id = self._make_card_id(paper)

        # Source attribution (verifiable)
        source_info = {
            "paper_id": paper.paper_id,
            "title": paper.title,
            "authors": paper.authors,
            "year": paper.year,
            "venue": paper.venue,
            "url": paper.url,
            "pdf_url": paper.pdf_url,
            "doi": paper.doi,
            "arxiv_id": paper.arxiv_id,
        }

        if self.llm:
            extracted = self._extract_with_llm(paper)
        else:
            extracted = self._extract_fallback(paper)

        card = KnowledgeCard(
            card_id=card_id,
            created_at=datetime.now().isoformat(),
            headline=extracted.get("headline", paper.title),
            tldr=extracted.get("tldr", paper.abstract[:280] if paper.abstract else ""),
            problem=extracted.get("problem", ""),
            method=extracted.get("method", ""),
            result=extracted.get("result", ""),
            limitation=extracted.get("limitation", ""),
            contribution=extracted.get("contribution", ""),
            source=source_info,
            tags=list(set(
                extracted.get("tags", []) + paper.tags[:5]
            ))[:10],
            domain=domain,
            relevance_scores=extracted.get("domain_relevance", {}),
            citation_count=paper.citation_count,
            raw_paper_id=paper.paper_id,
        )
        return card

    def generate_batch(
        self,
        papers: List[Paper],
        domain: str = None,
    ) -> List[KnowledgeCard]:
        """Generate cards for a list of papers."""
        cards = []
        for paper in papers:
            try:
                card = self.generate_card(paper, domain)
                cards.append(card)
            except Exception as e:
                print(f"Card generation failed for {paper.paper_id}: {e}")
                continue
        return cards

    def _extract_with_llm(self, paper: Paper) -> Dict:
        """Call LLM to extract structured fields."""
        prompt = self.EXTRACT_PROMPT.format(
            title=paper.title,
            authors=", ".join(paper.authors[:5]),
            year=paper.year or "Unknown",
            abstract=paper.abstract[:2000] if paper.abstract else "No abstract available.",
        )
        try:
            response = self.llm(prompt)
            # Parse JSON from response
            json_str = self._extract_json(response)
            return json.loads(json_str)
        except Exception as e:
            print(f"LLM extraction failed: {e}")
            return self._extract_fallback(paper)

    def _extract_json(self, text: str) -> str:
        """Extract JSON from LLM response (handles markdown code blocks)."""
        import re
        # Try to find JSON block
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            return match.group(1)
        # Try raw JSON
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return match.group(0)
        return text

    def _extract_fallback(self, paper: Paper) -> Dict:
        """Simple fallback when no LLM is available."""
        abstract = paper.abstract or ""
        sentences = abstract.split(". ")
        return {
            "headline": paper.title[:100],
            "tldr": abstract[:280],
            "problem": sentences[0] if sentences else "",
            "method": "",
            "result": "",
            "limitation": "",
            "contribution": abstract[:500],
            "tags": paper.tags[:5],
            "domain_relevance": {},
        }

    def _make_card_id(self, paper: Paper) -> str:
        key = f"{paper.paper_id}:{paper.title}"
        return hashlib.md5(key.encode()).hexdigest()[:12]
