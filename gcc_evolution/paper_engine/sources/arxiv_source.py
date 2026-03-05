"""
arXiv Source — free, no API key, covers all CS/Physics/Math/Finance preprints.
Uses the arXiv API v2 (atom feed).
"""
import asyncio
import aiohttp
import xml.etree.ElementTree as ET
from typing import List, Optional, Dict, Any
from datetime import datetime
import re
import logging

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from core.base_source import BaseSource, Paper

logger = logging.getLogger(__name__)


NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}


class ArxivSource(BaseSource):
    name = "arxiv"
    base_url = "https://export.arxiv.org/api/query"

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
            categories: List[str]  e.g. ["cs.AI", "cs.LG", "q-fin.CP"]
            search_field: str      "all" | "ti" | "abs" | "au" (default: all)
        """
        extra_filters = extra_filters or {}
        categories = extra_filters.get("categories", [])
        search_field = extra_filters.get("search_field", "all")

        # Build query
        parts = [f"{search_field}:{query}"]
        if categories:
            cat_query = " OR ".join(f"cat:{c}" for c in categories)
            parts.append(f"({cat_query})")
        search_query = " AND ".join(parts)

        params = {
            "search_query": search_query,
            "start": 0,
            "max_results": min(max_results, 100),
            "sortBy": "relevance",
            "sortOrder": "descending",
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(self.base_url, params=params) as resp:
                if resp.status != 200:
                    return []
                xml_text = await resp.text()

        return self._parse_feed(xml_text, year_from, year_to)

    async def fetch_detail(self, paper_id: str) -> Optional[Paper]:
        """paper_id: arxiv short id like '2505.10468'"""
        clean_id = paper_id.replace("arxiv:", "")
        params = {"id_list": clean_id, "max_results": 1}
        async with aiohttp.ClientSession() as session:
            async with session.get(self.base_url, params=params) as resp:
                if resp.status != 200:
                    return None
                xml_text = await resp.text()
        papers = self._parse_feed(xml_text)
        return papers[0] if papers else None

    def _parse_feed(
        self,
        xml_text: str,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
    ) -> List[Paper]:
        root = ET.fromstring(xml_text)
        papers = []

        for entry in root.findall("atom:entry", NS):
            try:
                paper = self._parse_entry(entry)
                # Year filter
                if year_from and paper.year and paper.year < year_from:
                    continue
                if year_to and paper.year and paper.year > year_to:
                    continue
                papers.append(paper)
            except Exception as e:
                logger.warning("[ARXIV] failed to parse feed entry: %s", e)
                continue

        return papers

    def _parse_entry(self, entry) -> Paper:
        def text(tag, ns="atom"):
            el = entry.find(f"{ns}:{tag}", NS)
            return el.text.strip() if el is not None and el.text else ""

        raw_id = text("id")
        arxiv_id = raw_id.split("/abs/")[-1].split("v")[0]

        published = text("published")
        year = None
        if published:
            try:
                year = int(published[:4])
            except Exception as e:
                logger.warning("[ARXIV] failed to parse year from published date: %s", e)
                pass

        authors = [
            a.find("atom:name", NS).text.strip()
            for a in entry.findall("atom:author", NS)
            if a.find("atom:name", NS) is not None
        ]

        categories = [
            t.get("term", "")
            for t in entry.findall("atom:category", NS)
        ]

        # PDF link
        pdf_url = None
        for link in entry.findall("atom:link", NS):
            if link.get("type") == "application/pdf":
                pdf_url = link.get("href")

        comment = text("comment", ns="arxiv")
        journal_ref = text("journal_ref", ns="arxiv")

        return Paper(
            paper_id=f"arxiv:{arxiv_id}",
            source="arxiv",
            arxiv_id=arxiv_id,
            title=text("title").replace("\n", " ").strip(),
            abstract=text("summary").replace("\n", " ").strip(),
            authors=authors,
            year=year,
            published_date=published[:10] if published else None,
            venue=journal_ref or None,
            url=f"https://arxiv.org/abs/{arxiv_id}",
            pdf_url=pdf_url or f"https://arxiv.org/pdf/{arxiv_id}",
            categories=categories,
            tags=categories,
            raw={"comment": comment, "journal_ref": journal_ref},
        )
