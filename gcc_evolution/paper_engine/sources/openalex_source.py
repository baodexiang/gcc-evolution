"""
OpenAlex Source — completely free, no API key, 250M+ scholarly works.
Best for: cross-disciplinary, full citation graph, institutional data.
https://docs.openalex.org/
"""
import aiohttp
import logging
from typing import List, Optional, Dict, Any

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from core.base_source import BaseSource, Paper

logger = logging.getLogger(__name__)


class OpenAlexSource(BaseSource):
    name = "openalex"
    base_url = "https://api.openalex.org"

    FIELDS = ",".join([
        "id", "title", "abstract_inverted_index",
        "authorships", "publication_year", "publication_date",
        "primary_location", "best_oa_location",
        "cited_by_count", "doi",
        "concepts", "topics", "keywords",
        "open_access", "ids",
    ])

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)
        # Polite pool: add your email for faster responses
        self.email = self.config.get("email", "research@example.com")
        self.headers = {"User-Agent": f"PaperEngine/1.0 (mailto:{self.email})"}

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
            concepts: List[str]       OpenAlex concept IDs or names
            type: str                 "article" | "preprint" | "book-chapter"
            open_access: bool
            min_citations: int
        """
        extra_filters = extra_filters or {}

        params = {
            "search": query,
            "per-page": min(max_results, 200),
            "select": self.FIELDS,
            "sort": "relevance_score:desc",
            "mailto": self.email,
        }

        # Build filter string
        filters = []
        if year_from:
            filters.append(f"publication_year:>{year_from - 1}")
        if year_to:
            filters.append(f"publication_year:<{year_to + 1}")
        if extra_filters.get("open_access"):
            filters.append("is_oa:true")
        if extra_filters.get("type"):
            filters.append(f"type:{extra_filters['type']}")
        min_cit = extra_filters.get("min_citations", 0)
        if min_cit:
            filters.append(f"cited_by_count:>{min_cit - 1}")

        if filters:
            params["filter"] = ",".join(filters)

        url = f"{self.base_url}/works"
        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()

        papers = []
        for item in data.get("results", []):
            try:
                papers.append(self._parse_item(item))
            except Exception as e:
                logger.warning("[OPENALEX] failed to parse item: %s", e)
                continue
        return papers

    async def fetch_detail(self, paper_id: str) -> Optional[Paper]:
        """paper_id: OpenAlex Work ID like 'W2741809807' or full URL."""
        clean_id = paper_id.replace("openalex:", "")
        if not clean_id.startswith("http"):
            clean_id = f"https://openalex.org/{clean_id}"
        url = f"{self.base_url}/works/{clean_id.split('/')[-1]}"
        params = {"select": self.FIELDS, "mailto": self.email}
        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
        return self._parse_item(data)

    def _reconstruct_abstract(self, inverted_index: Optional[Dict]) -> str:
        """OpenAlex stores abstracts as inverted index — reconstruct."""
        if not inverted_index:
            return ""
        words = {}
        for word, positions in inverted_index.items():
            for pos in positions:
                words[pos] = word
        return " ".join(words[i] for i in sorted(words.keys()))

    def _parse_item(self, item: Dict) -> Paper:
        # Abstract
        abstract = self._reconstruct_abstract(
            item.get("abstract_inverted_index")
        )

        # Authors
        authors = [
            a.get("author", {}).get("display_name", "")
            for a in item.get("authorships", [])
        ]

        # IDs
        ids = item.get("ids", {}) or {}
        arxiv_id = None
        raw_arxiv = ids.get("arxiv", "")
        if raw_arxiv:
            arxiv_id = raw_arxiv.split("/")[-1]
        doi = ids.get("doi", "") or item.get("doi", "")
        if doi and doi.startswith("https://doi.org/"):
            doi = doi.replace("https://doi.org/", "")

        oa_id = item.get("id", "").split("/")[-1]

        # Venue
        primary_loc = item.get("primary_location") or {}
        source_info = primary_loc.get("source") or {}
        venue = source_info.get("display_name")

        # PDF
        best_oa = item.get("best_oa_location") or {}
        pdf_url = best_oa.get("pdf_url")

        # Concepts / Topics as tags
        concepts = [
            c.get("display_name", "") for c in item.get("concepts", [])
            if c.get("level", 99) <= 2  # top-level concepts only
        ]
        topics = [
            t.get("display_name", "") for t in item.get("topics", [])
        ]
        keywords = [k.get("keyword", "") for k in item.get("keywords", [])]
        all_tags = list(set(filter(None, concepts + topics + keywords)))

        year = item.get("publication_year")
        pub_date = item.get("publication_date", "")

        return Paper(
            paper_id=f"openalex:{oa_id}",
            source="openalex",
            arxiv_id=arxiv_id,
            doi=doi,
            title=item.get("title", ""),
            abstract=abstract,
            authors=authors,
            year=year,
            published_date=pub_date[:10] if pub_date else None,
            venue=venue,
            url=f"https://openalex.org/{oa_id}",
            pdf_url=pdf_url or (f"https://arxiv.org/pdf/{arxiv_id}" if arxiv_id else None),
            citation_count=item.get("cited_by_count", 0) or 0,
            categories=concepts,
            tags=all_tags,
            raw={"oa_id": oa_id},
        )
