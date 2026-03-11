from datetime import datetime, timedelta

from gcc_evolution.L2_retrieval.retriever import HybridRetriever


def test_current_regime_bias_promotes_matching_document():
    retriever = HybridRetriever(current_regime="bull")
    now = datetime.utcnow().isoformat()
    retriever.index(
        [
            {"id": "mismatch", "text": "market signal", "created_at": now, "regime": "bear"},
            {"id": "match", "text": "market signal", "created_at": now, "regime": "bull"},
        ]
    )

    results = retriever.retrieve("market signal", top_k=2)

    assert [item["document"]["id"] for item in results] == ["match", "mismatch"]
    assert results[0]["score"] > results[1]["score"]


def test_decay_rate_changes_temporal_penalty_strength():
    stale_doc = {
        "id": "stale",
        "text": "market signal",
        "created_at": (datetime.utcnow() - timedelta(days=10)).isoformat(),
    }

    slow_decay = HybridRetriever(decay_rate=0.01)
    slow_decay.index([stale_doc])
    slow_score = slow_decay.retrieve("market signal", top_k=1)[0]["score"]

    fast_decay = HybridRetriever(decay_rate=0.5)
    fast_decay.index([stale_doc])
    fast_score = fast_decay.retrieve("market signal", top_k=1)[0]["score"]

    assert slow_score > fast_score
