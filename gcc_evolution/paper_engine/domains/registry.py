"""
Domain Configurations — Plug-and-play domain profiles.
Each domain defines: which sources, which filters, which queries, scoring weights.

Usage:
    from domains.registry import get_domain
    domain = get_domain("gcc")
    engine = domain.build_engine()
    papers = await engine.search(domain.build_queries("agentic memory"))
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


@dataclass
class DomainConfig:
    """
    Complete domain configuration for the paper engine.
    Customize sources, filters, scoring, and query templates.
    """
    name: str
    description: str

    # Which sources to enable (must match source.name)
    enabled_sources: List[str] = field(default_factory=lambda: [
        "arxiv", "semantic_scholar", "openalex"
    ])

    # Per-source extra filters applied to every search in this domain
    source_filters: Dict[str, Dict] = field(default_factory=dict)

    # Scoring weight overrides (override engine defaults)
    scoring_weights: Dict[str, float] = field(default_factory=dict)

    # Query templates: given a user topic, expand into multiple queries
    query_templates: List[str] = field(default_factory=lambda: ["{topic}"])

    # Default year range (None = no filter)
    default_year_from: Optional[int] = None
    default_year_to: Optional[int] = None

    # Minimum citation count (0 = no filter, good for fresh preprints)
    min_citations: int = 0

    # Top-k papers to return per search
    top_k: int = 20

    # Card tagging
    card_domain_label: str = "general"
    relevance_dimensions: List[str] = field(default_factory=lambda: ["general"])

    def build_queries(self, topic: str) -> List[str]:
        """Expand topic into domain-specific query variants."""
        return [t.format(topic=topic) for t in self.query_templates]

    def to_source_filter_map(self) -> Dict[str, Dict]:
        """Merge per-source filters with global min_citations."""
        result = {}
        for src in self.enabled_sources:
            filters = dict(self.source_filters.get(src, {}))
            if self.min_citations and src in ("semantic_scholar", "openalex", "crossref"):
                filters["min_citations"] = self.min_citations
            result[src] = filters
        return result


# ═══════════════════════════════════════════════════════════
# DOMAIN DEFINITIONS
# ═══════════════════════════════════════════════════════════

GCC_DOMAIN = DomainConfig(
    name="gcc",
    description="GCC - AI coding agents, agentic systems, LLM memory, code generation",
    card_domain_label="gcc",
    relevance_dimensions=["gcc", "general_ml"],

    enabled_sources=["arxiv", "semantic_scholar", "openalex"],

    source_filters={
        "arxiv": {
            "categories": [
                "cs.AI",   # AI general
                "cs.LG",   # Machine learning
                "cs.SE",   # Software engineering
                "cs.PL",   # Programming languages
                "cs.MA",   # Multi-agent systems
            ],
            "search_field": "all",
        },
        "semantic_scholar": {
            "fields_of_study": ["Computer Science"],
        },
        "openalex": {
            "type": "article",
        },
    },

    query_templates=[
        "{topic}",
        "{topic} large language model agent",
        "{topic} code generation LLM",
        "{topic} autonomous agent memory",
        "{topic} agentic AI system",
    ],

    default_year_from=2022,
    min_citations=0,        # Include fresh preprints
    top_k=25,

    scoring_weights={
        "w_relevance":  0.55,
        "w_recency":    0.30,   # Recency matters more in fast-moving AI field
        "w_citation":   0.10,
        "w_source_pri": 0.05,
    },
)


TRADING_DOMAIN = DomainConfig(
    name="trading",
    description="Quantitative trading, factor investing, ML for finance, market microstructure",
    card_domain_label="trading",
    relevance_dimensions=["trading_finance", "general_ml"],

    enabled_sources=["arxiv", "semantic_scholar", "ssrn", "openalex"],

    source_filters={
        "arxiv": {
            "categories": [
                "q-fin.CP",  # Computational finance
                "q-fin.PM",  # Portfolio management
                "q-fin.TR",  # Trading and market microstructure
                "q-fin.ST",  # Statistical finance
                "q-fin.RM",  # Risk management
                "cs.LG",     # ML methods
                "stat.ML",   # Statistical ML
            ],
            "search_field": "all",
        },
        "semantic_scholar": {
            "fields_of_study": ["Economics", "Computer Science", "Mathematics"],
        },
        "ssrn": {},  # Finance preprints
        "openalex": {
            "type": "article",
        },
    },

    query_templates=[
        "{topic}",
        "{topic} quantitative trading strategy",
        "{topic} stock market prediction machine learning",
        "{topic} alpha factor investing",
        "{topic} financial time series",
        "{topic} portfolio optimization",
    ],

    default_year_from=2019,
    min_citations=0,
    top_k=25,

    scoring_weights={
        "w_relevance":  0.50,
        "w_recency":    0.25,
        "w_citation":   0.15,   # Citations matter more in finance (peer-reviewed)
        "w_source_pri": 0.10,
    },
)


CHAN_THEORY_DOMAIN = DomainConfig(
    name="chan_theory",
    description="缠论 (Chan Theory), technical analysis, price action, Wyckoff, market structure",
    card_domain_label="chan_theory",
    relevance_dimensions=["trading_finance", "general_ml"],

    enabled_sources=["arxiv", "semantic_scholar", "openalex"],

    source_filters={
        "arxiv": {
            "categories": ["q-fin.TR", "q-fin.ST", "cs.LG", "q-fin.CP"],
        },
        "semantic_scholar": {
            "fields_of_study": ["Economics", "Computer Science"],
        },
    },

    query_templates=[
        "{topic}",
        "{topic} candlestick pattern recognition deep learning",
        "{topic} technical analysis chart pattern neural network",
        "{topic} price action trend reversal detection",
        "{topic} market microstructure fractal",
        "{topic} Elliott wave Wyckoff analysis AI",
    ],

    default_year_from=2018,
    min_citations=0,
    top_k=20,
)


INDUSTRIAL_AI_DOMAIN = DomainConfig(
    name="industrial_ai",
    description="Industrial AI, manufacturing automation, robotics, edge AI, air-gapped systems",
    card_domain_label="industrial_ai",
    relevance_dimensions=["industrial_automation", "general_ml"],

    enabled_sources=["arxiv", "semantic_scholar", "openalex", "crossref"],

    source_filters={
        "arxiv": {
            "categories": [
                "cs.RO",   # Robotics
                "cs.AI",   # AI
                "cs.SY",   # Systems and control
                "eess.SP", # Signal processing
                "cs.LG",   # ML
            ],
        },
        "semantic_scholar": {
            "fields_of_study": ["Computer Science", "Engineering"],
        },
        "crossref": {
            "type": "journal-article",
        },
    },

    query_templates=[
        "{topic}",
        "{topic} industrial manufacturing automation",
        "{topic} edge AI embedded system deployment",
        "{topic} predictive maintenance machine learning",
        "{topic} robot programming welding CNC",
        "{topic} air-gapped offline AI inference",
    ],

    default_year_from=2020,
    min_citations=0,
    top_k=20,

    scoring_weights={
        "w_relevance":  0.50,
        "w_recency":    0.20,
        "w_citation":   0.20,   # Peer-reviewed engineering papers matter
        "w_source_pri": 0.10,
    },
)


MEDICAL_DOMAIN = DomainConfig(
    name="medical",
    description="Clinical AI, biomedical NLP, drug discovery, medical imaging",
    card_domain_label="medical",
    relevance_dimensions=["medical_health", "general_ml"],

    enabled_sources=["pubmed", "arxiv", "semantic_scholar", "crossref"],

    source_filters={
        "pubmed": {
            "free_full_text": False,
        },
        "arxiv": {
            "categories": ["cs.LG", "cs.AI", "q-bio.QM", "stat.ML", "eess.IV"],
        },
        "semantic_scholar": {
            "fields_of_study": ["Medicine", "Biology", "Computer Science"],
        },
        "crossref": {
            "type": "journal-article",
        },
    },

    query_templates=[
        "{topic}",
        "{topic} clinical AI deep learning",
        "{topic} medical imaging diagnosis neural network",
        "{topic} biomedical NLP text mining",
        "{topic} drug discovery machine learning",
    ],

    default_year_from=2020,
    min_citations=5,   # Medical: require some peer validation
    top_k=20,

    scoring_weights={
        "w_relevance":  0.45,
        "w_recency":    0.20,
        "w_citation":   0.25,   # Citations very important in medicine
        "w_source_pri": 0.10,
    },
)


GENERAL_DOMAIN = DomainConfig(
    name="general",
    description="General AI/ML research — catch-all domain",
    card_domain_label="general",
    relevance_dimensions=["general_ml"],

    enabled_sources=["arxiv", "semantic_scholar", "openalex"],

    source_filters={
        "arxiv": {
            "categories": ["cs.AI", "cs.LG", "stat.ML"],
        },
    },

    query_templates=[
        "{topic}",
        "{topic} machine learning",
        "{topic} artificial intelligence",
    ],

    default_year_from=2020,
    top_k=20,
)


# ═══════════════════════════════════════════════════════════
# Registry
# ═══════════════════════════════════════════════════════════

DOMAIN_REGISTRY: Dict[str, DomainConfig] = {
    "gcc":            GCC_DOMAIN,
    "trading":        TRADING_DOMAIN,
    "chan_theory":    CHAN_THEORY_DOMAIN,
    "industrial_ai":  INDUSTRIAL_AI_DOMAIN,
    "medical":        MEDICAL_DOMAIN,
    "general":        GENERAL_DOMAIN,
}


def get_domain(name: str) -> DomainConfig:
    """Get a domain config by name. Falls back to 'general'."""
    return DOMAIN_REGISTRY.get(name, GENERAL_DOMAIN)


def list_domains() -> List[str]:
    """List all registered domain names."""
    return list(DOMAIN_REGISTRY.keys())


def register_domain(config: DomainConfig):
    """Register a custom domain."""
    DOMAIN_REGISTRY[config.name] = config


def create_custom_domain(
    name: str,
    description: str,
    sources: List[str],
    arxiv_categories: List[str] = None,
    query_templates: List[str] = None,
    year_from: int = 2020,
    **kwargs,
) -> DomainConfig:
    """Helper to quickly create and register a custom domain config."""
    source_filters = {}
    if arxiv_categories and "arxiv" in sources:
        source_filters["arxiv"] = {"categories": arxiv_categories}
    templates = query_templates or ["{topic}", "{topic} machine learning"]
    config = DomainConfig(
        name=name,
        description=description,
        enabled_sources=sources,
        source_filters=source_filters,
        query_templates=templates,
        default_year_from=year_from,
        **kwargs,
    )
    register_domain(config)
    return config
