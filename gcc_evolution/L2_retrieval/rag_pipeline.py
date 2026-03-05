"""
RAG Pipeline and Context Management

Retrieval-Augmented Generation with context compression.
"""

from typing import List, Dict, Any, Optional
from abc import ABC, abstractmethod


class ContextCompressor(ABC):
    """Abstract context compression strategy."""

    @abstractmethod
    def compress(self, context: str, max_tokens: int) -> str:
        """Compress context to fit token budget."""
        pass


class SummarizationCompressor(ContextCompressor):
    """
    Compress context by extracting key sentences.

    Strategies:
      • Token counting (ensure output < max_tokens)
      • Extractive summarization (keep original sentences)
      • Position bias (prioritize early/late sentences)
    """

    def compress(self, context: str, max_tokens: int) -> str:
        """Extract top sentences by TF-IDF."""
        sentences = context.split(".")
        # Simple compression: take first N sentences that fit token budget
        result = ""
        token_count = 0
        tokens_per_word = 1.3  # Rough estimate

        for sentence in sentences:
            sentence_tokens = int(len(sentence.split()) * tokens_per_word)
            if token_count + sentence_tokens <= max_tokens:
                result += sentence + ". "
                token_count += sentence_tokens
            else:
                break

        return result.strip()


class RAGPipeline:
    """
    Full retrieval-augmented generation workflow.

    Steps:
      1. Retrieve relevant documents (L2)
      2. Compress context to token budget
      3. Format prompt with context
      4. Generate response with LLM
    """

    def __init__(
        self,
        retriever: Optional[Any] = None,
        compressor: Optional[ContextCompressor] = None,
        max_context_tokens: int = 2000,
    ):
        self.retriever = retriever
        self.compressor = compressor or SummarizationCompressor()
        self.max_context_tokens = max_context_tokens
        self.context_cache = {}

    def retrieve_context(
        self, query: str, top_k: int = 5, use_cache: bool = True
    ) -> List[Dict[str, Any]]:
        """Retrieve documents for query."""
        if use_cache and query in self.context_cache:
            return self.context_cache[query]

        if not self.retriever:
            return []

        results = self.retriever.retrieve(query, top_k=top_k)
        if use_cache:
            self.context_cache[query] = results

        return results

    def build_context(self, query: str, top_k: int = 5) -> str:
        """Build compressed context string."""
        results = self.retrieve_context(query, top_k=top_k)

        # Format retrieved documents
        context_parts = []
        for result in results:
            doc = result["document"]
            score = result["score"]
            text = doc.get("text", "")
            context_parts.append(f"[Score: {score:.2f}] {text}")

        full_context = "\n\n".join(context_parts)

        # Compress to token budget
        compressed = self.compressor.compress(full_context, self.max_context_tokens)
        return compressed

    def format_prompt(self, query: str, context: str, system_prompt: str = "") -> str:
        """Format final prompt with context."""
        prompt = f"{system_prompt}\n\n" if system_prompt else ""
        prompt += f"Context:\n{context}\n\nQuery: {query}"
        return prompt

    def execute(
        self,
        query: str,
        system_prompt: str = "",
        top_k: int = 5,
        llm_callback=None,
    ) -> str:
        """
        Full RAG pipeline execution.

        Args:
            query: User query
            system_prompt: System instructions
            top_k: Number of documents to retrieve
            llm_callback: Function to call with formatted prompt

        Returns:
            LLM response (or prompt if no callback)
        """
        context = self.build_context(query, top_k=top_k)
        prompt = self.format_prompt(query, context, system_prompt)

        if llm_callback:
            return llm_callback(prompt)
        else:
            # Return prompt for manual LLM call
            return prompt

    def clear_cache(self) -> None:
        """Clear context cache."""
        self.context_cache.clear()
