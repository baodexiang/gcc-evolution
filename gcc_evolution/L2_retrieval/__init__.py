"""
L2 Retrieval — gcc-evo Open Core
License: BUSL 1.1 | Free for personal/academic/<$1M revenue
Commercial: gcc-evo.dev/licensing

Hybrid retrieval system combining semantic, temporal, and keyword matching.
Weighted composition: semantic 50% + temporal 30% + keyword 20%
"""

from .retriever import HybridRetriever, SemanticRetriever, KeywordRetriever
from .rag_pipeline import RAGPipeline, ContextCompressor

__all__ = [
    "HybridRetriever",
    "SemanticRetriever",
    "KeywordRetriever",
    "RAGPipeline",
    "ContextCompressor",
]

__version__ = "1.0.0"
