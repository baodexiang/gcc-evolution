# KEY-001 Master Validation

This package implements a standalone master validation layer for KEY-001.

## Architecture

- contracts.py: shared contracts (MasterContext, MasterOpinion, MasterDecision).
- masters/: three independent advisors.
  - livermore.py: timing quality and entry quality.
  - druckenmiller.py: macro alignment and veto.
  - connors.py: statistical edge and discipline.
- hub.py: parallel orchestration with fail-open fallback.
- decision_policy.py: asymmetric policy for DOWNGRADE and UPGRADE.
- audit.py: JSONL evidence and daily summary.
- evo/: replay plus proposal gate for gcc-evo.

## Current Scope

- Implemented as a standalone module.
- Not integrated into llm_server_v3640.py or price_scan_engine_v21.py.

## Decision Rules

- BUY and SELL: can be downgraded if composite score is low, multi-master low, or macro veto fires.
- HOLD: can be upgraded only when all strict conditions pass (all-high, strong signal, gate count limit, no blocked keyword, no macro veto).
- Empty context data is treated conservatively and forces downgrade for actionable directions.

## Config

- config/key001_master_policy.yaml: thresholds and missing-data policy.
- config/key001_master_weights.yaml: master weighting.

## Testing

Run:

python -m compileall modules/key001_master_validation
pytest test_key001_master_validation.py
