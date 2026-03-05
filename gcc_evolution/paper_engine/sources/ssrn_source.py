"""
SSRN Source — Social Science Research Network.
Best for: finance, economics, law, management preprints (pre-publication).
Uses SSRN public search (no official API — uses scraping-friendly endpoint).
"""
import aiohttp
import logging
from typing import List, Optional, Dict, Any
import re

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from core.base_source import BaseSource, Paper

logger = logging.getLogger(__name__)


class SSRNSource(BaseSource):
    name = "ssrn"
    # SSRN provides a basic search API through their platform
    base_url = "https://api.ssrn.com/content/v1/bindings"
    search_url = "https://papers.ssrn.com/sol3/results.cfm"

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
            journal_id: str     SSRN journal/network ID
            network: str        e.g. "FEN" (Finance), "EEN" (Economics)
        Note: SSRN has limited API access; falls back to CrossRef for SSRN DOIs.
        """
        extra_filters = extra_filters or {}

        # SSRN papers are indexed in CrossRef and Semantic Scholar
        # Best strategy: search CrossRef filtered to SSRN ISSN
        # SSRN working papers ISSN: 1556-5068
        params = {
            "query": query,
            "rows": min(max_results, 50),
            "sort": "relevance",
            "filter": "issn:1556-5068",  # SSRN working paper series
        }
        if year_from:
            params["filter"] += f",from-pub-date:{year_from}"
        if year_to:
            params["filter"] += f",until-pub-date:{year_to}"

        headers = {"User-Agent": "PaperEngine/1.0 (mailto:research@example.com)"}
        crossref_url = "https://api.crossref.org/works"

        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(crossref_url, params=params) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()

        papers = []
        for item in data.get("message", {}).get("items", []):
            try:
                papers.append(self._parse_crossref_item(item))
            except Exception as e:
                logger.warning("[SSRN] failed to parse crossref item: %s", e)
                continue
        return papers

    async def fetch_detail(self, paper_id: str) -> Optional[Paper]:
        """paper_id: 'ssrn:12345678' (abstract ID) or DOI"""
        ssrn_id = paper_id.replace("ssrn:", "")
        # Try as DOI via CrossRef
        doi_url = f"https://api.crossref.org/works/10.2139/ssrn.{ssrn_id}"
        headers = {"User-Agent": "PaperEngine/1.0"}
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(doi_url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
        item = data.get("message", {})
        return self._parse_crossref_item(item) if item else None

    def _parse_crossref_item(self, item: Dict) -> Paper:
        doi = item.get("DOI", "")
        titles = item.get("title", [])
        title = titles[0] if titles else ""

        abstract = item.get("abstract", "")
        if abstract:
            abstract = re.sub(r"<[^>]+>", " ", abstract).strip()

        authors = []
        for a in item.get("author", []):
            given = a.get("given", "")
            family = a.get("family", "")
            name = f"{given} {family}".strip()
            if name:
                authors.append(name)

        pub_date_parts = (
            item.get("published-print", {}).get("date-parts")
            or item.get("published-online", {}).get("date-parts")
            or [[None]]
        )
        parts = pub_date_parts[0] if pub_date_parts else []
        year = parts[0] if parts else None

        container = item.get("container-title", [])
        venue = container[0] if container else "SSRN Working Paper"

        # Extract SSRN abstract ID from DOI
        ssrn_id = ""
        if doi and "ssrn." in doi:
            ssrn_id = doi.split("ssrn.")[-1]

        url = (
            f"https://papers.ssrn.com/sol3/papers.cfm?abstract_id={ssrn_id}"
            if ssrn_id else item.get("URL", f"https://doi.org/{doi}")
        )

        tags = item.get("subject", [])

        return Paper(
            paper_id=f"ssrn:{ssrn_id}" if ssrn_id else f"crossref:{doi}",
            source="ssrn",
            doi=doi,
            title=title,
            abstract=abstract,
            authors=authors,
            year=year,
            venue=venue,
            url=url,
            citation_count=item.get("is-referenced-by-count", 0),
            tags=tags,
            categories=tags,
        )
