from modules.key001_master_validation import MasterContext, MasterValidationHub
from modules.key001_master_validation.audit import MasterAuditLogger
from modules.key001_master_validation.decision_policy import DecisionThresholds, evaluate_decision
from modules.key001_master_validation.evo.proposal_gate import GateMetrics, evaluate_gate
from modules.key001_master_validation.evo.replay_runner import run_replay
from modules.key001_master_validation.masters.connors import ConnorsModule
from modules.key001_master_validation.masters.druckenmiller import DruckenmillerModule
from modules.key001_master_validation.decision_policy import _blocked_reason_contains


def _base_context(direction: str = "BUY") -> MasterContext:
    return MasterContext(
        symbol="TSLA",
        direction=direction,
        signal_type="DOUBLE_BOTTOM",
        signal_strength=0.82,
        filter_passed=True,
        blocked_reason=None,
        market={
            "rvol": 1.3,
            "breakout_distance_pct": 0.02,
            "pivot_distance_pct": 0.02,
            "pullback_pct": 0.02,
            "pullback_rvol": 0.8,
            "trend_position_pct": 0.55,
            "rr_ratio": 2.0,
            "signal_freq_5d": 2,
        },
        macro={
            "fed_stance": "NEUTRAL",
            "m2_yoy": 0.02,
            "credit_spread": 0.02,
            "vix": 21,
            "macro_rr_ratio": 2.0,
            "macro_tech_alignment": 0.7,
            "risk_discipline": 0.8,
            "ttl_sec": 600,
        },
        stats={
            "rsi2": 8,
            "connors_rsi": 11,
            "streak_days": 4,
            "above_ma200": True,
            "pattern_sample_size": 120,
            "pattern_winrate": 0.62,
            "has_exit_plan": True,
            "position_discipline": 0.8,
        },
    )


def test_buy_path_confirms_with_valid_data():
    hub = MasterValidationHub.from_config_files()
    decision = hub.evaluate(_base_context("BUY"))
    assert decision.action in ("CONFIRM", "DOWNGRADE")


def test_sell_path_is_validated_not_fallthrough():
    hub = MasterValidationHub.from_config_files()
    decision = hub.evaluate(_base_context("SELL"))
    assert "NON_STANDARD" not in " ".join(decision.reasons)


def test_hold_upgrade_blocked_by_macro_veto():
    ctx = _base_context("HOLD")
    ctx.signal_strength = 0.95
    ctx.blocked_reason = None
    ctx.blocked_gate_count = 0
    ctx.macro["fed_stance"] = "HAWKISH"

    druck = DruckenmillerModule()
    connors = ConnorsModule()
    opinions = [
        druck.evaluate(MasterContext(**{**ctx.__dict__, "direction": "BUY"})),
        connors.evaluate(MasterContext(**{**ctx.__dict__, "direction": "BUY"})),
        connors.evaluate(MasterContext(**{**ctx.__dict__, "direction": "BUY"})),
    ]
    opinions[1].master = "Livermore"

    cfg = DecisionThresholds()
    decision = evaluate_decision(ctx, opinions, {"Livermore": 1.0, "Druckenmiller": 1.2, "Connors": 1.0}, cfg)
    assert decision.action != "UPGRADE"


def test_empty_context_downgrades_actionable_direction():
    ctx = MasterContext(
        symbol="TSLA",
        direction="BUY",
        signal_type="DOUBLE_BOTTOM",
        signal_strength=0.9,
        filter_passed=True,
        blocked_reason=None,
    )
    hub = MasterValidationHub.from_config_files()
    decision = hub.evaluate(ctx)
    assert decision.action == "DOWNGRADE"


def test_connors_uses_experience_db_when_stats_missing():
    ctx = _base_context("BUY")
    ctx.stats = {"rsi2": 8, "connors_rsi": 10, "streak_days": 3, "above_ma200": True, "has_exit_plan": True}
    ctx.experience_db = {"pattern_sample_size": 150, "pattern_winrate": 0.64}
    op = ConnorsModule().evaluate(ctx)
    assert op.subscores["C4_HIST_EDGE"] > 0.45


def test_replay_runner_returns_real_metrics_shape():
    records = [
        {"pnl_before": -10, "pnl_after": 5},
        {"pnl_before": 3, "pnl_after": 2},
        {"pnl_before": -4, "pnl_after": 1},
        {"pnl_before": 1, "pnl_after": -2},
    ]
    out = run_replay(records)
    assert out.samples == 4
    assert 0.0 <= out.p_value <= 1.0
    assert out.discordant_pairs >= 0


def test_proposal_gate_checks_discordant_pairs():
    gate = evaluate_gate(
        GateMetrics(
            samples=60,
            p_value=0.01,
            max_drawdown_not_worse=True,
            winrate_lift=0.08,
            discordant_pairs=2,
        )
    )
    assert gate["approved"] is False
    checks = gate.get("checks", {})
    assert isinstance(checks, dict)
    assert "discordant_ok" in checks


def test_audit_log_and_summary_roundtrip(tmp_path):
    log_path = tmp_path / "audit.jsonl"
    summary_path = tmp_path / "summary.json"
    logger = MasterAuditLogger(str(log_path), str(summary_path))
    ctx = _base_context("BUY")
    decision = MasterValidationHub.from_config_files().evaluate(ctx)
    assert logger.log(ctx, decision) is True
    summary = logger.build_daily_summary()
    assert summary["samples"] >= 1
    assert "by_symbol" in summary


def test_blocked_reason_matching_token_boundaries():
    assert _blocked_reason_contains("DANGER_ZONE", ["DANGER"]) is True
    assert _blocked_reason_contains("PRE_DANGER_ZONE", ["DANGER"]) is True
    assert _blocked_reason_contains("NOT_DANGEROUS", ["DANGER"]) is False


def test_macro_veto_can_be_disabled():
    ctx = _base_context("BUY")
    # Build opinions that include Druckenmiller veto
    druck = DruckenmillerModule()
    d_op = druck.evaluate(MasterContext(**{**ctx.__dict__, "macro": {**ctx.macro, "fed_stance": "HAWKISH"}}))
    assert d_op.veto is True

    opinions = [
        d_op,
        ConnorsModule().evaluate(ctx),
        ConnorsModule().evaluate(ctx),
    ]
    opinions[1].master = "Livermore"

    cfg = DecisionThresholds(macro_veto_enabled=False)
    decision = evaluate_decision(
        ctx,
        opinions,
        {"Livermore": 1.0, "Druckenmiller": 1.2, "Connors": 1.0},
        cfg,
    )
    assert "DOWNGRADE_D1_VETO" not in decision.reasons


def test_stale_macro_downweights_scores():
    fresh_ctx = _base_context("BUY")
    stale_ctx = _base_context("BUY")
    stale_ctx.macro["ttl_sec"] = 500000

    mod = DruckenmillerModule()
    fresh = mod.evaluate(fresh_ctx)
    stale = mod.evaluate(stale_ctx)

    assert stale.subscores["D1_POLICY_ALIGN"] <= fresh.subscores["D1_POLICY_ALIGN"]
    assert stale.score <= fresh.score


def test_replay_runner_large_discordant_sample():
    records = [{"pnl_before": -1.0, "pnl_after": 1.0} for _ in range(200)]
    out = run_replay(records)
    assert out.samples == 200
    assert 0.0 <= out.p_value <= 1.0
