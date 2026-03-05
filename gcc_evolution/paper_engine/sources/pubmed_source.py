"""
PubMed Source — free, 35M+ biomedical papers via NCBI E-utilities.
Best for: medical, life science, neuro, psychology domains.
API key optional (higher rate: 10 req/s vs 3/s without key).
"""
import aiohttp
import logging
import xml.etree.ElementTree as ET
from typing import List, Optional, Dict, Any

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from core.base_source import BaseSource, Paper

logger = logging.getLogger(__name__)


class PubMedSource(BaseSource):
    name = "pubmed"
    esearch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    efetch_url  = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    elink_url   = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi"

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)
        self.api_key = self.config.get("api_key", "")  # optional

    def _base_params(self) -> Dict:
        p = {"retmode": "json"}
        if self.api_key:
            p["api_key"] = self.api_key
        return p

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
            mesh_terms: List[str]   MeSH term filters
            article_type: str       "Review" | "Clinical Trial" | etc.
            free_full_text: bool
        """
        extra_filters = extra_filters or {}

        # Build query
        parts = [query]
        if year_from and year_to:
            parts.append(f'("{year_from}"[PDAT]:"{year_to}"[PDAT])')
        elif year_from:
            parts.append(f'"{year_from}"[PDAT]:"3000"[PDAT]')

        mesh_terms = extra_filters.get("mesh_terms", [])
        for term in mesh_terms:
            parts.append(f'"{term}"[MeSH Terms]')

        if extra_filters.get("free_full_text"):
            parts.append("free full text[filter]")
        if extra_filters.get("article_type"):
            parts.append(f'{extra_filters["article_type"]}[pt]')

        full_query = " AND ".join(f"({p})" for p in parts)

        # Step 1: Search for IDs
        params = {
            **self._base_params(),
            "db": "pubmed",
            "term": full_query,
            "retmax": min(max_results, 200),
            "sort": "relevance",
            "usehistory": "y",
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(self.esearch_url, params=params) as resp:
                if resp.status != 200:
                    return []
                search_data = await resp.json()

        pmids = search_data.get("esearchresult", {}).get("idlist", [])
        if not pmids:
            return []

        # Step 2: Fetch details
        return await self._fetch_by_ids(pmids)

    async def fetch_detail(self, paper_id: str) -> Optional[Paper]:
        """paper_id: 'pubmed:12345678' or just '12345678'"""
        pmid = paper_id.replace("pubmed:", "")
        papers = await self._fetch_by_ids([pmid])
        return papers[0] if papers else None

    async def _fetch_by_ids(self, pmids: List[str]) -> List[Paper]:
        params = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "xml",
            "rettype": "abstract",
        }
        if self.api_key:
            params["api_key"] = self.api_key

        async with aiohttp.ClientSession() as session:
            async with session.get(self.efetch_url, params=params) as resp:
                if resp.status != 200:
                    return []
                xml_text = await resp.text()

        return self._parse_xml(xml_text)

    def _parse_xml(self, xml_text: str) -> List[Paper]:
        papers = []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return []

        for article in root.findall(".//PubmedArticle"):
            try:
                papers.append(self._parse_article(article))
            except Exception as e:
                logger.warning("[PUBMED] failed to parse article: %s", e)
                continue
        return papers

    def _parse_article(self, article) -> Paper:
        med = article.find("MedlineCitation")
        art = med.find("Article")

        pmid = med.findtext("PMID", "")
        title = art.findtext("ArticleTitle", "")

        # Abstract
        abs_texts = []
        for abs_el in art.findall(".//AbstractText"):
            label = abs_el.get("Label", "")
            text = abs_el.text or ""
            if label:
                abs_texts.append(f"{label}: {text}")
            else:
                abs_texts.append(text)
        abstract = " ".join(abs_texts)

        # Authors
        authors = []
        for author in art.findall(".//Author"):
            last = author.findtext("LastName", "")
            fore = author.findtext("ForeName", "")
            if last:
                authors.append(f"{fore} {last}".strip())

        # Date
        pub_date = art.find(".//PubDate")
        year = None
        pub_date_str = None
        if pub_date is not None:
            year_txt = pub_date.findtext("Year")
            month = pub_date.findtext("Month", "01")
            day = pub_date.findtext("Day", "01")
            if year_txt:
                year = int(year_txt)
                pub_date_str = f"{year_txt}-{month[:2].zfill(2)}-{day.zfill(2)}"

        # Journal
        journal = art.find("Journal")
        venue = journal.findtext("Title") if journal is not None else None

        # MeSH tags
        mesh_tags = [
            h.findtext("DescriptorName", "")
            for h in med.findall(".//MeshHeading")
        ]
        mesh_tags = list(filter(None, mesh_tags))

        # DOI
        doi = None
        for id_el in article.findall(".//ArticleId"):
            if id_el.get("IdType") == "doi":
                doi = id_el.text
                break

        return Paper(
            paper_id=f"pubmed:{pmid}",
            source="pubmed",
            doi=doi,
            title=title,
            abstract=abstract,
            authors=authors,
            year=year,
            published_date=pub_date_str,
            venue=venue,
            url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            tags=mesh_tags,
            categories=mesh_tags,
        )
