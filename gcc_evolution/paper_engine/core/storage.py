"""
DuckDB Storage Layer — persistent store for papers and knowledge cards.
Designed for GCC integration: fast query, tag-based retrieval, dedup.
"""
import json
import os
from typing import List, Optional, Dict, Any
from pathlib import Path

try:
    import duckdb
    HAS_DUCKDB = True
except ImportError:
    HAS_DUCKDB = False

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from core.base_source import Paper
from core.knowledge_card import KnowledgeCard


class PaperStore:
    """
    DuckDB-backed storage for papers and knowledge cards.
    Falls back to JSON file if DuckDB not available.
    """

    def __init__(self, db_path: str = "papers.duckdb"):
        self.db_path = db_path
        self.use_duckdb = HAS_DUCKDB
        if self.use_duckdb:
            self.con = duckdb.connect(db_path)
            self._init_tables()
        else:
            print("[PaperStore] DuckDB not found, using JSON fallback")
            self.json_path = db_path.replace(".duckdb", ".json")
            self._data = self._load_json()

    # ─────────────────────────────────────────────
    # Table init
    # ─────────────────────────────────────────────

    def _init_tables(self):
        self.con.execute("""
        CREATE TABLE IF NOT EXISTS papers (
            paper_id        VARCHAR PRIMARY KEY,
            source          VARCHAR,
            title           VARCHAR,
            abstract        VARCHAR,
            authors         VARCHAR,   -- JSON array
            year            INTEGER,
            published_date  VARCHAR,
            venue           VARCHAR,
            doi             VARCHAR,
            arxiv_id        VARCHAR,
            url             VARCHAR,
            pdf_url         VARCHAR,
            citation_count  INTEGER DEFAULT 0,
            tags            VARCHAR,   -- JSON array
            categories      VARCHAR,   -- JSON array
            combined_score  FLOAT DEFAULT 0,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            raw             VARCHAR    -- JSON object
        )
        """)

        self.con.execute("""
        CREATE TABLE IF NOT EXISTS knowledge_cards (
            card_id         VARCHAR PRIMARY KEY,
            raw_paper_id    VARCHAR,
            domain          VARCHAR,
            headline        VARCHAR,
            tldr            VARCHAR,
            problem         VARCHAR,
            method          VARCHAR,
            result          VARCHAR,
            limitation      VARCHAR,
            contribution    VARCHAR,
            source          VARCHAR,   -- JSON
            tags            VARCHAR,   -- JSON array
            relevance_scores VARCHAR,  -- JSON
            citation_count  INTEGER DEFAULT 0,
            related_card_ids VARCHAR,  -- JSON array
            created_at      VARCHAR,
            FOREIGN KEY (raw_paper_id) REFERENCES papers(paper_id)
        )
        """)

        # Indexes for fast lookup
        self.con.execute("""
        CREATE INDEX IF NOT EXISTS idx_papers_arxiv ON papers(arxiv_id)
        """)
        self.con.execute("""
        CREATE INDEX IF NOT EXISTS idx_cards_domain ON knowledge_cards(domain)
        """)
        self.con.execute("""
        CREATE INDEX IF NOT EXISTS idx_cards_paper ON knowledge_cards(raw_paper_id)
        """)

    # ─────────────────────────────────────────────
    # Paper storage
    # ─────────────────────────────────────────────

    def save_paper(self, paper: Paper):
        if self.use_duckdb:
            self._save_paper_duckdb(paper)
        else:
            self._data.setdefault("papers", {})[paper.paper_id] = paper.to_dict()
            self._save_json()

    def save_papers(self, papers: List[Paper]):
        for p in papers:
            self.save_paper(p)

    def _save_paper_duckdb(self, paper: Paper):
        self.con.execute("""
        INSERT OR REPLACE INTO papers VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP,?)
        """, [
            paper.paper_id, paper.source, paper.title, paper.abstract,
            json.dumps(paper.authors, ensure_ascii=False),
            paper.year, paper.published_date, paper.venue,
            paper.doi, paper.arxiv_id, paper.url, paper.pdf_url,
            paper.citation_count,
            json.dumps(paper.tags, ensure_ascii=False),
            json.dumps(paper.categories, ensure_ascii=False),
            paper.combined_score,
            json.dumps(paper.raw, ensure_ascii=False),
        ])

    # ─────────────────────────────────────────────
    # Knowledge card storage
    # ─────────────────────────────────────────────

    def save_card(self, card: KnowledgeCard):
        if self.use_duckdb:
            self._save_card_duckdb(card)
        else:
            self._data.setdefault("cards", {})[card.card_id] = card.to_dict()
            self._save_json()

    def save_cards(self, cards: List[KnowledgeCard]):
        for c in cards:
            self.save_card(c)

    def _save_card_duckdb(self, card: KnowledgeCard):
        self.con.execute("""
        INSERT OR REPLACE INTO knowledge_cards VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, [
            card.card_id, card.raw_paper_id, card.domain,
            card.headline, card.tldr, card.problem, card.method,
            card.result, card.limitation, card.contribution,
            json.dumps(card.source, ensure_ascii=False),
            json.dumps(card.tags, ensure_ascii=False),
            json.dumps(card.relevance_scores, ensure_ascii=False),
            card.citation_count,
            json.dumps(card.related_card_ids, ensure_ascii=False),
            card.created_at,
        ])

    # ─────────────────────────────────────────────
    # Query
    # ─────────────────────────────────────────────

    def get_cards_by_domain(self, domain: str) -> List[Dict]:
        if self.use_duckdb:
            rows = self.con.execute(
                "SELECT * FROM knowledge_cards WHERE domain = ? ORDER BY citation_count DESC",
                [domain]
            ).fetchall()
            cols = [d[0] for d in self.con.description]
            return [dict(zip(cols, r)) for r in rows]
        else:
            return [
                c for c in self._data.get("cards", {}).values()
                if c.get("domain") == domain
            ]

    def get_cards_by_tag(self, tag: str) -> List[Dict]:
        if self.use_duckdb:
            rows = self.con.execute(
                "SELECT * FROM knowledge_cards WHERE tags LIKE ? ORDER BY citation_count DESC",
                [f"%{tag}%"]
            ).fetchall()
            cols = [d[0] for d in self.con.description]
            return [dict(zip(cols, r)) for r in rows]
        else:
            return [
                c for c in self._data.get("cards", {}).values()
                if tag.lower() in " ".join(c.get("tags", [])).lower()
            ]

    def search_cards(self, keyword: str, domain: str = None) -> List[Dict]:
        """Full-text search across headline, problem, method, result."""
        if self.use_duckdb:
            query = """
            SELECT * FROM knowledge_cards
            WHERE (headline LIKE ? OR problem LIKE ? OR method LIKE ? OR result LIKE ? OR tldr LIKE ?)
            """
            params = [f"%{keyword}%"] * 5
            if domain:
                query += " AND domain = ?"
                params.append(domain)
            query += " ORDER BY citation_count DESC LIMIT 50"
            rows = self.con.execute(query, params).fetchall()
            cols = [d[0] for d in self.con.description]
            return [dict(zip(cols, r)) for r in rows]
        else:
            results = []
            for c in self._data.get("cards", {}).values():
                text = " ".join([
                    c.get("headline",""), c.get("problem",""),
                    c.get("method",""), c.get("result","")
                ]).lower()
                if keyword.lower() in text:
                    if not domain or c.get("domain") == domain:
                        results.append(c)
            return results

    def get_stats(self) -> Dict:
        if self.use_duckdb:
            papers_count = self.con.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
            cards_count = self.con.execute("SELECT COUNT(*) FROM knowledge_cards").fetchone()[0]
            domains = self.con.execute(
                "SELECT domain, COUNT(*) FROM knowledge_cards GROUP BY domain"
            ).fetchall()
            return {
                "total_papers": papers_count,
                "total_cards": cards_count,
                "cards_by_domain": dict(domains),
            }
        else:
            cards = self._data.get("cards", {})
            from collections import Counter
            domain_counts = Counter(c.get("domain") for c in cards.values())
            return {
                "total_papers": len(self._data.get("papers", {})),
                "total_cards": len(cards),
                "cards_by_domain": dict(domain_counts),
            }

    # ─────────────────────────────────────────────
    # JSON fallback helpers
    # ─────────────────────────────────────────────

    def _load_json(self) -> Dict:
        if os.path.exists(self.json_path):
            with open(self.json_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"papers": {}, "cards": {}}

    def _save_json(self):
        with open(self.json_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def close(self):
        if self.use_duckdb:
            self.con.close()
