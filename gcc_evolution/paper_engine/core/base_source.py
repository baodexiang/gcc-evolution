"""
Base class for all paper sources.
Every source must implement: search() and fetch_detail()
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime


@dataclass
class Paper:
    """Universal paper schema across all sources."""
    # Identity
    paper_id: str                          # source:id, e.g. "arxiv:2505.10468"
    source: str                            # arxiv | semantic_scholar | openalex | ...
    title: str
    
    # Content
    abstract: str = ""
    full_text: Optional[str] = None        # if available
    
    # Metadata
    authors: List[str] = field(default_factory=list)
    year: Optional[int] = None
    published_date: Optional[str] = None
    venue: Optional[str] = None            # journal / conference
    doi: Optional[str] = None
    arxiv_id: Optional[str] = None
    url: str = ""
    pdf_url: Optional[str] = None
    
    # Citation signals
    citation_count: int = 0
    influential_citation_count: int = 0
    
    # Topics
    tags: List[str] = field(default_factory=list)
    categories: List[str] = field(default_factory=list)
    
    # Quality signals (computed later)
    relevance_score: float = 0.0
    recency_score: float = 0.0
    combined_score: float = 0.0
    
    # Raw payload for debugging
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "paper_id": self.paper_id,
            "source": self.source,
            "title": self.title,
            "abstract": self.abstract,
            "authors": self.authors,
            "year": self.year,
            "published_date": self.published_date,
            "venue": self.venue,
            "doi": self.doi,
            "arxiv_id": self.arxiv_id,
            "url": self.url,
            "pdf_url": self.pdf_url,
            "citation_count": self.citation_count,
            "influential_citation_count": self.influential_citation_count,
            "tags": self.tags,
            "categories": self.categories,
            "relevance_score": self.relevance_score,
            "recency_score": self.recency_score,
            "combined_score": self.combined_score,
        }


class BaseSource(ABC):
    """Abstract base for all paper sources."""

    name: str = "base"
    base_url: str = ""

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.enabled = self.config.get("enabled", True)
        self.rate_limit_delay = self.config.get("rate_limit_delay", 1.0)  # seconds
        self.max_results = self.config.get("max_results", 20)

    @abstractmethod
    async def search(
        self,
        query: str,
        max_results: int = 20,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
        extra_filters: Optional[Dict] = None,
    ) -> List[Paper]:
        """Search papers by query string. Returns list of Paper objects."""
        ...

    @abstractmethod
    async def fetch_detail(self, paper_id: str) -> Optional[Paper]:
        """Fetch full details for a single paper by its source-specific ID."""
        ...

    def is_enabled(self) -> bool:
        return self.enabled

    def __repr__(self):
        return f"<Source:{self.name}>"
