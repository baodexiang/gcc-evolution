# gcc-evo v5.345 Paper-to-Layer Audit

This document summarizes the current local audit baseline for gcc-evo paper usage across the canonical 8-layer model:

- `UI`
- `L0`
- `L1`
- `L2`
- `L3`
- `L4`
- `L5`
- `DA`

Audit basis:
- Source paper baseline: `.GCC/doc/paper_audit_v5200.md`
- Canonical 8-layer split: `.GCC/gcc_evolution/layer_manifest.py`

Important note:
- The original `21-paper` audit was written mainly around the core functional layers, not the later `UI / L0 / DA` release split.
- Therefore, the counts below are a `primary ownership mapping` for the current 8-layer model.
- One paper is better treated as `cross-layer shared reference` instead of being forced into a single layer.

## Summary

| Priority | Layer | Paper Count | Notes |
|---|---:|---:|---|
| P0 | `L1 Memory` | 5 | Highest memory-system density |
| P0 | `L2 Retrieval` | 4 | Retrieval and ranking core |
| P0 | `L3 Distillation` | 5 | Skill extraction and experience learning |
| P1 | `L4 Decision` | 3 | Skeptic and decision evolution |
| P1 | `L5 Orchestration` | 3 | Loop closure and workflow automation |
| P2 | `UI` | 0 | No standalone paper ownership in current 21-paper audit |
| P2 | `L0` | 0 | Governance/setup implemented, but not paper-owned in current audit |
| P2 | `DA` | 0 | DA exists as paid constitutional layer, but not counted in current 21-paper audit |
| Shared | `L1-L3` | 1 | Shared reference, not assigned to one layer |

Total:
- Primary layer ownership: `20`
- Shared cross-layer reference: `1`
- Audit baseline total: `21`

## Layer Mapping

### P0

#### `L1 Memory` — 5 papers

1. `#02 HGM`
   - Role: CMP descendant tracking, downstream impact
2. `#04 AMemGym`
   - Role: cross-session memory evaluation, confidence decay
3. `#06 StockMem`
   - Role: event/reflection dual-layer memory, causal triplets
4. `#12 LightMem`
   - Role: three-tier memory, sleep-style consolidation
5. `#21 TiM`
   - Role: forgetting and merge heuristics for memory maintenance

#### `L2 Retrieval` — 4 papers

1. `#17 RAG`
   - Role: retrieval-augmented generation baseline
2. `#13 SWE-Pruner`
   - Role: goal-aware retrieval pruning
3. `#05 GA`
   - Role: importance scoring, decay, candidate prioritization
4. `#07 THGNN`
   - Role: regime/context routing, graph-aware weighting

#### `L3 Distillation` — 5 papers

1. `#10 ExpeL`
   - Role: cross-card insight distillation
2. `#08 SF/SEP`
   - Role: faithfulness and semantic preservation
3. `#09 SkillRL`
   - Role: hierarchical skill bank and recursive co-evolution
4. `#11 Reflexion`
   - Role: failure-triggered self-reflection
5. `#19 CL-bench`
   - Role: card utilization benchmark reference

### P1

#### `L4 Decision` — 3 papers

1. `#03 FactorMiner`
   - Role: success/failure dual-channel decision memory
2. `#15 Xu & Yang`
   - Role: independent skeptic validation
3. `#14 QuantaAlpha`
   - Role: diversified planning and crossover guidance

#### `L5 Orchestration` — 3 papers

1. `#01 Cornell Agentic AI`
   - Role: overall agentic architecture and autonomy framing
2. `#20 FARS / Agent Laboratory`
   - Role: staged research workflow and pipeline framing
3. `#16 NSM`
   - Role: embedding-space diagnostic support for orchestration monitoring

### P2

#### `UI` — 0 papers

Current status:
- UI is implemented as dashboard/observer/visibility tooling
- No standalone paper ownership is explicitly recorded in the current `21-paper` audit

#### `L0` — 0 papers

Current status:
- L0 exists as setup/governance/gate/bootstrap layer
- The present audit baseline does not assign a dedicated paper to `L0`

#### `DA` — 0 papers

Current status:
- DA exists as constitutional/direction-anchor paid layer
- The current `21-paper` audit does not include a dedicated DA paper count

## Shared Cross-Layer Reference

### `L1-L3 shared` — 1 paper

1. `#18 Mischler et al.`
   - Role: hierarchical feature extraction reference
   - Better treated as a shared reference across memory, retrieval, and distillation
   - Not forced into a single primary layer

## Practical Interpretation

- The current paper density is concentrated in `L1 + L2 + L3`
- `L4 + L5` are also paper-backed, but with lower paper count than the middle knowledge stack
- `UI + L0 + DA` are architecturally real layers, but they are not yet represented as standalone paper-owned layers in the current `21-paper` audit baseline

## Recommended Priority Order

1. `L1 Memory`
2. `L3 Distillation`
3. `L2 Retrieval`
4. `L4 Decision`
5. `L5 Orchestration`
6. `UI`
7. `L0`
8. `DA`

This ordering reflects:
- current paper density
- architectural centrality
- practical relevance to the public free-path foundation

