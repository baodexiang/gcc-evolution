"""
Semantic Scholar Source — free API, 200M+ papers, citation graph, full-text search.
API key optional (higher rate limits with key).
"""
import asyncio
import aiohttp
import logging
from typing import List, Optional, Dict, Any

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from core.base_source import BaseSource, Paper

logger = logging.getLogger(__name__)


class SemanticScholarSource(BaseSource):
    name = "semantic_scholar"
    base_url = "https://api.semanticscholar.org/graph/v1"

    FIELDS = ",".join([
        "paperId", "externalIds", "title", "abstract",
        "authors", "year", "publicationDate", "venue",
        "publicationVenue", "citationCount", "influentialCitationCount",
        "fieldsOfStudy", "s2FieldsOfStudy", "openAccessPdf",
        "url", "referenceCount", "tldr",
    ])

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)
        self.api_key = self.config.get("api_key", "")  # optional
        self.headers = {}
        if self.api_key:
            self.headers["x-api-key"] = self.api_key

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
            fields_of_study: List[str]  e.g. ["Computer Science", "Economics"]
            open_access_only: bool
            min_citations: int
        """
        extra_filters = extra_filters or {}

        params = {
            "query": query,
            "limit": min(max_results, 100),
            "fields": self.FIELDS,
        }

        # Year range filter
        if year_from or year_to:
            yf = year_from or 1900
            yt = year_to or 2100
            params["year"] = f"{yf}-{yt}"

        # Fields of study filter
        fos = extra_filters.get("fields_of_study", [])
        if fos:
            params["fieldsOfStudy"] = ",".join(fos)

        # Open access filter
        if extra_filters.get("open_access_only"):
            params["openAccessPdf"] = ""

        url = f"{self.base_url}/paper/search"
        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()

        papers = []
        for item in data.get("data", []):
            try:
                paper = self._parse_item(item)
                # Citation filter
                min_cit = extra_filters.get("min_citations", 0)
                if paper.citation_count < min_cit:
                    continue
                papers.append(paper)
            except Exception as e:
                logger.warning("[SEMANTIC_SCHOLAR] failed to parse item: %s", e)
                continue

        return papers

    async def fetch_detail(self, paper_id: str) -> Optional[Paper]:
        """paper_id: S2 paperId or 'arxiv:2505.10468'"""
        clean_id = paper_id.replace("semantic_scholar:", "")
        url = f"{self.base_url}/paper/{clean_id}"
        params = {"fields": self.FIELDS}
        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
        return self._parse_item(data)

    async def fetch_citations(self, paper_id: str, limit: int = 10) -> List[Paper]:
        """Get papers that CITE this paper (downstream)."""
        clean_id = paper_id.replace("semantic_scholar:", "")
        url = f"{self.base_url}/paper/{clean_id}/citations"
        params = {"fields": self.FIELDS, "limit": limit}
        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
        return [
            self._parse_item(item["citingPaper"])
            for item in data.get("data", [])
            if item.get("citingPaper")
        ]

    async def fetch_references(self, paper_id: str, limit: int = 10) -> List[Paper]:
        """Get papers REFERENCED BY this paper (upstream)."""
        clean_id = paper_id.replace("semantic_scholar:", "")
        url = f"{self.base_url}/paper/{clean_id}/references"
        params = {"fields": self.FIELDS, "limit": limit}
        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
        return [
            self._parse_item(item["citedPaper"])
            for item in data.get("data", [])
            if item.get("citedPaper")
        ]

    def _parse_item(self, item: Dict) -> Paper:
        authors = [
            a.get("name", "") for a in item.get("authors", [])
        ]

        ext_ids = item.get("externalIds", {}) or {}
        arxiv_id = ext_ids.get("ArXiv")
        doi = ext_ids.get("DOI")

        # PDF
        oap = item.get("openAccessPdf") or {}
        pdf_url = oap.get("url")

        # Venue
        pub_venue = item.get("publicationVenue") or {}
        venue = (
            item.get("venue")
            or pub_venue.get("name")
            or pub_venue.get("type")
        )

        # TLDR summary (S2 generated)
        tldr_obj = item.get("tldr") or {}
        tldr = tldr_obj.get("text", "")

        # Fields of study
        fos = [f.get("category", "") for f in item.get("s2FieldsOfStudy", [])]
        fos += item.get("fieldsOfStudy", []) or []
        fos = list(set(filter(None, fos)))

        year = item.get("year")
        pub_date = item.get("publicationDate") or ""

        s2_id = item.get("paperId", "")

        return Paper(
            paper_id=f"semantic_scholar:{s2_id}",
            source="semantic_scholar",
            arxiv_id=arxiv_id,
            doi=doi,
            title=item.get("title", ""),
            abstract=item.get("abstract", "") or tldr,
            authors=authors,
            year=year,
            published_date=pub_date[:10] if pub_date else None,
            venue=venue,
            url=item.get("url", f"https://www.semanticscholar.org/paper/{s2_id}"),
            pdf_url=pdf_url or (f"https://arxiv.org/pdf/{arxiv_id}" if arxiv_id else None),
            citation_count=item.get("citationCount", 0) or 0,
            influential_citation_count=item.get("influentialCitationCount", 0) or 0,
            categories=fos,
            tags=fos,
            raw={"tldr": tldr, "s2_id": s2_id},
        )
