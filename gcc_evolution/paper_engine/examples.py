"""
Paper Engine — Usage Examples
=================================
Copy-paste ready examples for GCC, Trading, Industrial AI integration.
"""
import asyncio
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from paper_engine import PaperResearcher, quick_search, create_custom_domain
from paper_engine.core.storage import PaperStore


# ═══════════════════════════════════════════════════════════
# Example 1: GCC Research — Agentic Memory Systems
# ═══════════════════════════════════════════════════════════

async def example_gcc_research():
    """
    Use case: GCC 5.0 wants to automatically pull latest papers
    on 'persistent memory for coding agents' and generate knowledge cards.
    """
    researcher = PaperResearcher(
        domain="gcc",
        # Optional: plug in your LLM client for structured extraction
        # llm_client=lambda prompt: deepseek_call(prompt),
        source_configs={
            "semantic_scholar": {"api_key": ""},  # optional key
            "openalex": {"email": "your@email.com"},
        }
    )

    cards = await researcher.research(
        topic="persistent memory agentic coding assistant",
        top_k=15,
        year_from=2023,
        generate_cards=True,
        expand_citations=True,    # Also pull papers that cite top results
        citation_top_k=5,
    )

    print(f"\n{'='*60}")
    print(f"GCC Research: Found {len(cards)} knowledge cards")
    print(f"{'='*60}")

    for i, card in enumerate(cards[:5], 1):
        print(f"\n--- Card #{i} ---")
        print(card.to_markdown())

    # Save to DuckDB
    store = PaperStore("gcc_papers.duckdb")
    store.save_cards(cards)
    print(f"\n[Storage] Saved {len(cards)} cards to DuckDB")
    print(f"[Stats] {store.get_stats()}")
    store.close()

    return cards


# ═══════════════════════════════════════════════════════════
# Example 2: Trading Research — Chan Theory + ML
# ═══════════════════════════════════════════════════════════

async def example_trading_research():
    """
    Use case: Pull latest papers on trend reversal detection,
    candlestick patterns, and multi-timeframe analysis.
    """
    researcher = PaperResearcher(domain="trading")

    # Multiple focused topics
    topics = [
        "candlestick pattern recognition deep learning",
        "trend reversal detection transformer",
        "multi-timeframe trading signal fusion",
    ]

    all_cards = []
    for topic in topics:
        cards = await researcher.research(topic, top_k=8, generate_cards=True)
        all_cards.extend(cards)
        print(f"[Trading] '{topic}' → {len(cards)} cards")

    # Dedup by card_id
    seen = set()
    unique_cards = []
    for c in all_cards:
        if c.card_id not in seen:
            seen.add(c.card_id)
            unique_cards.append(c)

    print(f"\n[Trading] Total unique cards: {len(unique_cards)}")

    store = PaperStore("trading_papers.duckdb")
    store.save_cards(unique_cards)
    store.close()
    return unique_cards


# ═══════════════════════════════════════════════════════════
# Example 3: Industrial AI — Air-Gapped Deployment
# ═══════════════════════════════════════════════════════════

async def example_industrial_research():
    """
    Use case: Research on deploying LLMs in air-gapped factory environments,
    edge inference, welding robot AI.
    """
    researcher = PaperResearcher(domain="industrial_ai")

    cards = await researcher.research(
        topic="edge AI deployment offline inference manufacturing",
        top_k=15,
        year_from=2021,
        generate_cards=True,
    )

    print(f"\n[Industrial AI] {len(cards)} cards found")
    for card in cards[:3]:
        print(f"\n📄 {card.headline}")
        print(f"   Method: {card.method[:120]}...")
        print(f"   Result: {card.result[:100]}...")
        print(f"   Source: {card.source.get('url')}")

    return cards


# ═══════════════════════════════════════════════════════════
# Example 4: Custom Domain — Create your own
# ═══════════════════════════════════════════════════════════

async def example_custom_domain():
    """
    Create a totally custom domain for a niche topic.
    E.g.: Yaskawa welding robot AI control systems.
    """
    # Register custom domain
    welding_domain = create_custom_domain(
        name="welding_ai",
        description="AI for robotic welding quality control and parameter optimization",
        sources=["arxiv", "semantic_scholar", "crossref"],
        arxiv_categories=["cs.RO", "cs.AI", "cs.SY", "eess.SP"],
        query_templates=[
            "{topic}",
            "{topic} robotic welding quality control",
            "{topic} welding defect detection neural network",
            "{topic} weld seam tracking machine learning",
            "{topic} arc welding process optimization AI",
        ],
        year_from=2019,
        top_k=15,
        card_domain_label="welding_ai",
    )

    researcher = PaperResearcher(custom_domain=welding_domain)
    cards = await researcher.research("welding parameter optimization deep learning")
    print(f"\n[Custom: welding_ai] {len(cards)} cards found")
    return cards


# ═══════════════════════════════════════════════════════════
# Example 5: Quick one-liner search
# ═══════════════════════════════════════════════════════════

async def example_quick_search():
    """
    Simplest possible usage — one function call.
    """
    cards = await quick_search(
        topic="information coefficient factor analysis stock returns",
        domain="trading",
        top_k=5,
    )
    for card in cards:
        print(f"• {card.headline}")
        print(f"  {card.source.get('url')}\n")
    return cards


# ═══════════════════════════════════════════════════════════
# Example 6: GCC Integration — agents.md injection
# ═══════════════════════════════════════════════════════════

async def example_gcc_agents_md_integration():
    """
    Integrate with GCC's agents.md persistent memory.
    Pull top papers and format them for injection into GCC context.
    """
    researcher = PaperResearcher(domain="gcc")
    cards = await researcher.research(
        "agentic AI persistent memory coding",
        top_k=10,
        generate_cards=True,
    )

    # Format for agents.md injection
    agents_md_section = "## Recent Research (Auto-fetched)\n\n"
    for card in cards:
        agents_md_section += f"""### {card.headline}
- **Source**: [{card.source.get('title', '')}]({card.source.get('url', '')}) ({card.source.get('year', '')})
- **Method**: {card.method}
- **Result**: {card.result}
- **Tags**: {', '.join(card.tags[:5])}

"""

    print("[GCC agents.md injection preview:]")
    print(agents_md_section[:2000])

    # Write to agents.md (adjust path to your GCC installation)
    # with open("path/to/agents.md", "a") as f:
    #     f.write(agents_md_section)

    return agents_md_section


# ═══════════════════════════════════════════════════════════
# Example 7: Search stored cards (no new fetch)
# ═══════════════════════════════════════════════════════════

def example_query_stored():
    """Query already-stored cards without fetching new papers."""
    store = PaperStore("gcc_papers.duckdb")

    # By domain
    gcc_cards = store.get_cards_by_domain("gcc")
    print(f"Total GCC cards stored: {len(gcc_cards)}")

    # Full-text search
    memory_cards = store.search_cards("memory", domain="gcc")
    print(f"Cards about 'memory': {len(memory_cards)}")

    # By tag
    agent_cards = store.get_cards_by_tag("agent")
    print(f"Cards tagged 'agent': {len(agent_cards)}")

    print(f"\nDB Stats: {store.get_stats()}")
    store.close()


# ═══════════════════════════════════════════════════════════
# Run all examples
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--example", default="gcc",
        choices=["gcc", "trading", "industrial", "custom", "quick", "agents_md", "query"])
    args = parser.parse_args()

    examples = {
        "gcc":        example_gcc_research,
        "trading":    example_trading_research,
        "industrial": example_industrial_research,
        "custom":     example_custom_domain,
        "quick":      example_quick_search,
        "agents_md":  example_gcc_agents_md_integration,
    }

    if args.example == "query":
        example_query_stored()
    else:
        asyncio.run(examples[args.example]())
