# gcc-evo v5.340 Program Split Map

This file is the release-facing inventory that places every public program surface
into the canonical model: `5 Free foundation layers + 3 Paid core layers`, plus enhancement packs and legacy compatibility.

## Canonical Programs

| Unit | Tier | Canonical path | Backing source |
|---|---|---|---|
| `UI` | free | `gcc_evolution/free/ui/dashboard_server.py` | `gcc_evolution/dashboard_server.py` |
| `UI` | free | `gcc_evolution/free/ui/event_bus.py` | `gcc_evolution/observer/event_bus.py` |
| `UI` | free | `gcc_evolution/free/ui/layer_emitter.py` | `gcc_evolution/observer/layer_emitter.py` |
| `UI` | free | `gcc_evolution/free/ui/run_tracer.py` | `gcc_evolution/observer/run_tracer.py` |
| `L0` | free | `gcc_evolution/free/l0/session_config.py` | `gcc_evolution/session_config.py` |
| `L0` | free | `gcc_evolution/free/l0/setup_wizard.py` | `gcc_evolution/setup_wizard.py` |
| `L0` | free | `gcc_evolution/free/l0/governance.py` | `gcc_evolution/l0_governance.py` |
| `L0` | paid | `gcc_evolution/paid/l0/phase2_quality.py` | paid boundary stub |
| `L0` | paid | `gcc_evolution/paid/l0/phase3_math.py` | `gcc/papers/formulas/P002_nowcasting.py` modeling entrypoint |
| `L0` | paid | `gcc_evolution/paid/l0/phase4_truth_table.py` | `gcc/papers/formulas/P003_alphaforgebench.py` acceptance/truth-table entrypoint |
| `L1` | free | `gcc_evolution/free/l1/memory_tiers.py` | `gcc_evolution/L1_memory/memory_tiers.py` |
| `L1` | free | `gcc_evolution/free/l1/storage.py` | `gcc_evolution/L1_memory/storage.py` |
| `L1` | paid | `gcc_evolution/paid/l1/advanced_memory.py` | `gcc_evolution/L1_memory/memory_tiers.py` |
| `L2` | free | `gcc_evolution/free/l2/retriever.py` | `gcc_evolution/L2_retrieval/retriever.py` |
| `L2` | free | `gcc_evolution/free/l2/rag_pipeline.py` | `gcc_evolution/L2_retrieval/rag_pipeline.py` |
| `L2` | paid | `gcc_evolution/paid/l2/advanced_retrieval.py` | paid boundary stub |
| `L3` | free | `gcc_evolution/free/l3/distiller.py` | `gcc_evolution/L3_distillation/distiller.py` |
| `L3` | free | `gcc_evolution/free/l3/experience_card.py` | `gcc_evolution/L3_distillation/experience_card.py` |
| `L3` | paid | `gcc_evolution/paid/l3/advanced_distillation.py` | paid boundary stub |
| `L4` | paid | `gcc_evolution/paid/l4/skeptic.py` | `gcc_evolution/L4_decision/skeptic.py` |
| `L4` | paid | `gcc_evolution/paid/l4/multi_model.py` | `gcc_evolution/L4_decision/multi_model.py` |
| `L4` | paid | `gcc_evolution/paid/l4/knn_evolution.py` | `gcc_evolution/enterprise/knn_evolution.py` |
| `L4` | paid | `gcc_evolution/paid/l4/walk_forward.py` | `gcc_evolution/enterprise/walk_forward.py` |
| `L4` | paid | `gcc_evolution/paid/l4/bandit_scheduler.py` | `gcc_evolution/enterprise/bandit_scheduler.py` |
| `L4` | paid | `gcc_evolution/paid/l4/adaptive_dag.py` | `gcc_evolution/enterprise/adaptive_dag.py` |
| `L5` | paid | `gcc_evolution/paid/l5/drift_gate.py` | `gcc/papers/formulas/P006_drift_aware_streaming.py` orchestration drift gate |
| `L5` | paid | `gcc_evolution/paid/l5/pipeline.py` | `gcc_evolution/L5_orchestration/pipeline.py` + `gcc_evolution/enterprise/adaptive_dag.py` |
| `L5` | paid | `gcc_evolution/paid/l5/loop_engine.py` | `gcc_evolution/L5_orchestration/loop_engine_base.py` |
| `DA` | paid | `gcc_evolution/paid/da/anchor.py` | `gcc_evolution/direction_anchor/anchor.py` |

## Root Public Entry Programs

| Path | Canonical role |
|---|---|
| `gcc_evolution/cli.py` | release CLI, must describe canonical split |
| `gcc_evolution/__init__.py` | root package facade, must export canonical surface |
| `gcc_evolution/layer_manifest.py` | canonical tier truth table |
| `gcc_evolution/l0_governance.py` | L0 governance backing implementation |
| `gcc_evolution/session_config.py` | legacy-backed free `L0` source |
| `gcc_evolution/setup_wizard.py` | legacy-backed free `L0` source |

## Compatibility-Only Packages

These remain in the repository for backward compatibility only:

| Package | Canonical unit | Status |
|---|---|---|
| `gcc_evolution/L0_setup` | `L0` | legacy |
| `gcc_evolution/L1_memory` | `L1` | legacy |
| `gcc_evolution/L2_retrieval` | `L2` | legacy |
| `gcc_evolution/L3_distillation` | `L3` | legacy |
| `gcc_evolution/L4_decision` | `L4` | legacy |
| `gcc_evolution/L5_orchestration` | `L5` | legacy |
| `gcc_evolution/free/l5` | `L5` | legacy compatibility shim |
| `gcc_evolution/observer` | `UI` | legacy |
| `gcc_evolution/direction_anchor` | `DA` | legacy |
| `gcc_evolution/enterprise` | `paid support` | legacy support source |

## Hard Rule

- Release-facing documentation must reference canonical paths first.
- Commercial boundary is defined by `gcc_evolution/free/` and `gcc_evolution/paid/`.
- Legacy paths are compatibility shims, not tier definitions.

