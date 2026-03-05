# KEY-003-T01: MVP Scope Lock

Date: 2026-02-16
Owner: core
Status: DONE

## Objective
Lock KEY-003 phase-1 implementation boundary before coding to avoid scope drift and rework.

## In Scope (MVP)
1. Three-layer scoring engine:
   - Valuation
   - Momentum
   - Quality (with veto rule)
2. Composite score formula and label mapping.
3. Position modifier mapping (only modifies max position cap; does not replace entry logic).
4. Single-symbol API contract (synchronous).
5. Batch API contract and async task status model.
6. Cache/TTL/degraded mode and quota budget guard.
7. Score history persistence and query capability.

## Out of Scope (Non-MVP)
1. Crypto-specific valuation replacement model.
2. New trading entry/exit strategy logic.
3. New broker execution path changes.
4. Full-scale optimization beyond agreed KPI thresholds.
5. UI dashboard redesign.

## Fixed Rules
1. Quality veto hard rule:
   - audit negative OR Altman Z < 1.8 => is_tradeable=false.
2. Position modifier cannot override hard risk controls.
3. API response keys must be complete (values may be null).

## Acceptance Baseline (for later tasks)
1. API schema completeness: 100% keys present.
2. Batch 50 tickers success rate >= 95%.
3. Composite calculation error <= 1e-6 (sampling check).
4. Backtest IC mean >= 0.05 (5-year weekly cross-section).

## Execution Sequence
T02 -> T03 -> T04 -> T05 -> T06 -> T07 -> T08 -> T09 -> T10

## Notes
- This file is the scope authority for KEY-003 implementation.
- Any scope change should be recorded as a new T01 addendum, not silent edits in later tasks.
