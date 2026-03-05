from __future__ import annotations

from modules.key004_chanbs_improvement import (
    ChanBSPolicy,
    ChanBSSignalSample,
    build_three_step_plan,
    evaluate_signal_quality,
    infer_market_tier,
    load_symbol_chanbs_policy,
    should_accept_signal,
)


def test_infer_market_tier_crypto_and_stock():
    assert infer_market_tier("BTCUSDC") == "CRYPTO"
    assert infer_market_tier("TSLA") == "STOCK"


def test_load_symbol_chanbs_policy_reads_plugin_section(tmp_path):
    params = tmp_path / "params"
    params.mkdir(parents=True, exist_ok=True)
    (params / "CRWV.yaml").write_text(
        "\n".join(
            [
                "symbol: \"CRWV\"",
                "plugin:",
                "  chan_bs:",
                "    enabled: true",
                "    weight: 0.85",
                "    min_confidence: 0.55",
            ]
        ),
        encoding="utf-8",
    )

    policy = load_symbol_chanbs_policy("CRWV", params_dir=str(params))
    assert policy.enabled is True
    assert policy.weight == 0.85
    assert policy.min_confidence == 0.55


def test_should_accept_signal_respects_min_confidence():
    policy = ChanBSPolicy(symbol="CRWV", enabled=True, weight=0.85, min_confidence=0.55)
    signal = ChanBSSignalSample(
        timestamp=1.0,
        symbol="CRWV",
        signal_type="BUY",
        confidence=0.50,
        price=100.0,
        market_tier="STOCK",
        accepted=False,
    )
    accepted, reason = should_accept_signal(signal, policy)
    assert accepted is False
    assert "threshold" in reason


def test_evaluate_signal_quality_and_plan_outputs():
    samples = [
        ChanBSSignalSample(
            timestamp=1.0,
            symbol="CRWV",
            signal_type="BUY",
            confidence=0.70,
            price=100.0,
            market_tier="STOCK",
            accepted=True,
            pnl_pct=1.2,
            mfe_pct=2.0,
            mae_pct=0.6,
        ),
        ChanBSSignalSample(
            timestamp=2.0,
            symbol="CRWV",
            signal_type="SELL",
            confidence=0.60,
            price=101.0,
            market_tier="STOCK",
            accepted=True,
            pnl_pct=-0.8,
            mfe_pct=0.9,
            mae_pct=1.1,
        ),
    ]
    metrics = evaluate_signal_quality(samples, symbol="CRWV", market_tier="STOCK")
    assert metrics.total_signals == 2
    assert metrics.closed_signals == 2
    assert metrics.win_rate == 0.5

    policy = ChanBSPolicy(symbol="CRWV", enabled=True, weight=0.85, min_confidence=0.55)
    plan = build_three_step_plan(metrics, policy)
    assert "step1_diagnosis" in plan
    assert "step2_recommendation" in plan
    assert "step3_validation" in plan
