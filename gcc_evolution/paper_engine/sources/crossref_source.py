"""
CrossRef Source — free, 150M+ DOI-registered works.
Best for: peer-reviewed journals, conference proceedings, exact DOI lookup.
"""
import aiohttp
import logging
from typing import List, Optional, Dict, Any

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from core.base_source import BaseSource, Paper

logger = logging.getLogger(__name__)


class CrossrefSource(BaseSource):
    name = "crossref"
    base_url = "https://api.crossref.org/works"

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)
        self.email = self.config.get("email", "research@example.com")
        # Polite pool header → higher rate limits
        self.headers = {
            "User-Agent": f"PaperEngine/1.0 (mailto:{self.email})"
        }

    async def search(
        self,
        query: str,
        max_results: int = 20,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
        extra_filters: Optional[Dict] = None,
    ) -> List[Paper]:
        """
        extra_filters:
            type: str           "journal-article" | "proceedings-article" | "book-chapter"
            publisher: str
            issn: str           Filter by journal ISSN
        """
        extra_filters = extra_filters or {}

        params = {
            "query": query,
            "rows": min(max_results, 100),
            "sort": "relevance",
            "order": "desc",
        }

        # Date range filter
        if year_from:
            params["filter"] = params.get("filter", "") + f",from-pub-date:{year_from}"
        if year_to:
            params["filter"] = params.get("filter", "") + f",until-pub-date:{year_to}"
        if extra_filters.get("type"):
            params["filter"] = params.get("filter", "") + f",type:{extra_filters['type']}"
        if extra_filters.get("issn"):
            params["filter"] = params.get("filter", "") + f",issn:{extra_filters['issn']}"

        # Clean leading comma
        if params.get("filter", "").startswith(","):
            params["filter"] = params["filter"][1:]
        if not params.get("filter"):
            params.pop("filter", None)

        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.get(self.base_url, params=params) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()

        papers = []
        for item in data.get("message", {}).get("items", []):
            try:
                papers.append(self._parse_item(item))
            except Exception as e:
                logger.warning("[CROSSREF] failed to parse item: %s", e)
                continue
        return papers

    async def fetch_detail(self, paper_id: str) -> Optional[Paper]:
        """paper_id: DOI string like '10.1145/1234567'"""
        doi = paper_id.replace("crossref:", "")
        url = f"{self.base_url}/{doi}"
        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
        item = data.get("message", {})
        return self._parse_item(item) if item else None

    def _parse_item(self, item: Dict) -> Paper:
        doi = item.get("DOI", "")

        # Title
        titles = item.get("title", [])
        title = titles[0] if titles else ""

        # Abstract (often empty in CrossRef)
        abstract = item.get("abstract", "")
        # Strip JATS XML tags if present
        if abstract:
            import re
            abstract = re.sub(r"<[^>]+>", " ", abstract).strip()

        # Authors
        authors = []
        for a in item.get("author", []):
            given = a.get("given", "")
            family = a.get("family", "")
            name = f"{given} {family}".strip()
            if name:
                authors.append(name)

        # Date
        pub_date_parts = (
            item.get("published-print", {}).get("date-parts")
            or item.get("published-online", {}).get("date-parts")
            or [[None]]
        )
        parts = pub_date_parts[0] if pub_date_parts else []
        year = parts[0] if parts else None
        pub_date = "-".join(str(p).zfill(2) for p in parts[:3]) if parts and parts[0] else None

        # Venue
        container = item.get("container-title", [])
        venue = container[0] if container else item.get("publisher")

        # Citations
        citation_count = item.get("is-referenced-by-count", 0)

        # URL
        url = item.get("URL", f"https://doi.org/{doi}" if doi else "")

        # Tags from subjects
        tags = item.get("subject", [])

        return Paper(
            paper_id=f"crossref:{doi}",
            source="crossref",
            doi=doi,
            title=title,
            abstract=abstract,
            authors=authors,
            year=year,
            published_date=pub_date,
            venue=venue,
            url=url,
            citation_count=citation_count,
            tags=tags,
            categories=tags,
            raw={"type": item.get("type", ""), "publisher": item.get("publisher", "")},
        )
