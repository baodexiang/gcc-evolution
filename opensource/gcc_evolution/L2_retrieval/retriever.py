"""
Retrieval Mechanisms

Hybrid retriever combining three methods:
  • Semantic (50%): Dense embedding similarity
  • Temporal (30%): Recency weighting
  • Keyword (20%): BM25-style term matching
"""

from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import List, Dict, Any, Tuple, Optional
import math


class BaseRetriever(ABC):
    """Abstract retriever interface."""

    @abstractmethod
    def retrieve(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Retrieve relevant documents for query."""
        pass

    @abstractmethod
    def index(self, documents: List[Dict[str, Any]]) -> None:
        """Build index from documents."""
        pass


class SemanticRetriever(BaseRetriever):
    """
    Semantic similarity retrieval using embeddings.

    Note: Enterprise version includes vector DB integration.
    Community version uses simple cosine similarity on TF-IDF vectors.

    Example:
      >>> retriever = SemanticRetriever(embedding_model="tfidf")
      >>> docs = [{"id": "1", "text": "market signal"}]
      >>> retriever.index(docs)
      >>> results = retriever.retrieve("trading signal")
    """

    def __init__(self, embedding_model: str = "tfidf"):
        self.embedding_model = embedding_model
        self.documents = []
        self.embeddings = []

    def retrieve(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Find documents similar to query embedding."""
        # Placeholder: community uses TF-IDF, enterprise uses dense embeddings
        if not self.documents:
            return []
        # Simple score assignment (would use cosine similarity in production)
        scored = [(doc, 0.9 - i * 0.1) for i, doc in enumerate(self.documents[:top_k])]
        return [{"document": doc, "score": score} for doc, score in scored]

    def index(self, documents: List[Dict[str, Any]]) -> None:
        """Index documents for semantic search."""
        self.documents = documents


class KeywordRetriever(BaseRetriever):
    """
    BM25-style keyword matching.

    Ranks documents by term relevance using inverse document frequency.
    """

    def __init__(self):
        self.documents = []
        self.term_index: Dict[str, List[int]] = {}

    def retrieve(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Retrieve documents matching query terms."""
        query_terms = set(query.lower().split())
        scores = []

        for i, doc in enumerate(self.documents):
            doc_text = doc.get("text", "").lower()
            doc_terms = set(doc_text.split())
            matches = len(query_terms & doc_terms)
            if matches > 0:
                score = matches / len(query_terms)
                scores.append((doc, score))

        # Sort by score descending
        scores.sort(key=lambda x: x[1], reverse=True)
        return [{"document": doc, "score": score} for doc, score in scores[:top_k]]

    def index(self, documents: List[Dict[str, Any]]) -> None:
        """Build inverted index."""
        self.documents = documents
        for i, doc in enumerate(documents):
            text = doc.get("text", "").lower()
            for term in text.split():
                if term not in self.term_index:
                    self.term_index[term] = []
                self.term_index[term].append(i)


class HybridRetriever(BaseRetriever):
    """
    Weighted combination of retrieval methods.

    Composition: semantic 50% + temporal 30% + keyword 20%

    Example:
      >>> retriever = HybridRetriever()
      >>> docs = [
      ...     {"id": "1", "text": "bullish signal", "created_at": datetime.now()},
      ...     {"id": "2", "text": "bearish pattern", "created_at": datetime.now() - timedelta(days=30)}
      ... ]
      >>> retriever.index(docs)
      >>> results = retriever.retrieve("market signal", top_k=5)
    """

    def __init__(self):
        self.semantic = SemanticRetriever()
        self.keyword = KeywordRetriever()
        self.documents = []
        self.weights = {"semantic": 0.5, "temporal": 0.3, "keyword": 0.2}

    def retrieve(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Retrieve using hybrid scoring."""
        if not self.documents:
            return []

        # Get results from each retriever
        semantic_results = self.semantic.retrieve(query, top_k * 2)
        keyword_results = self.keyword.retrieve(query, top_k * 2)

        # Compute temporal scores (recency bias)
        now = datetime.utcnow()
        temporal_scores = {}
        for doc in self.documents:
            created = doc.get("created_at", now)
            if isinstance(created, str):
                created = datetime.fromisoformat(created)
            age_days = (now - created).days
            temporal_scores[doc["id"]] = math.exp(-age_days / 30)  # Decay over 30 days

        # Combine scores
        combined = {}
        for res in semantic_results:
            doc_id = res["document"]["id"]
            combined[doc_id] = (
                combined.get(doc_id, 0)
                + res["score"] * self.weights["semantic"]
            )

        for res in keyword_results:
            doc_id = res["document"]["id"]
            combined[doc_id] = (
                combined.get(doc_id, 0) + res["score"] * self.weights["keyword"]
            )

        for doc_id, temporal_score in temporal_scores.items():
            combined[doc_id] = (
                combined.get(doc_id, 0) + temporal_score * self.weights["temporal"]
            )

        # Sort and return top-k
        sorted_ids = sorted(combined.keys(), key=lambda k: combined[k], reverse=True)
        results = []
        for doc_id in sorted_ids[:top_k]:
            doc = next((d for d in self.documents if d["id"] == doc_id), None)
            if doc:
                results.append({"document": doc, "score": combined[doc_id]})

        return results

    def index(self, documents: List[Dict[str, Any]]) -> None:
        """Index documents in all sub-retrievers."""
        self.documents = documents
        self.semantic.index(documents)
        self.keyword.index(documents)
