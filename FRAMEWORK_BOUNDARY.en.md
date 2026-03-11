# gcc-evo v5.345 Framework Boundary

This file defines the only release-facing framework boundary for the open-source package.

## 1. Canonical 8 Layers

1. `UI`
2. `L0`
3. `L1`
4. `L2`
5. `L3`
6. `L4`
7. `L5`
8. `DA`

## 2. Commercial Split

### Free Foundation: 5 Layers

| Layer | Status | Scope |
|------|--------|-------|
| `UI` | Free | Dashboard, setup flow, status visibility |
| `L0` | Free foundation | Basic setup, prerequisite scaffold, release-safe session bootstrap |
| `L1` | Free foundation | Base memory storage and hierarchy |
| `L2` | Free foundation | Base retrieval and query normalization |
| `L3` | Free foundation | Base distillation and skill packaging |

### Paid Core: 3 Layers

| Layer | Status | Scope |
|------|--------|-------|
| `L4` | Paid only | Decision evolution, skeptic gate, benchmark acceptance |
| `L5` | Paid only | Closed-loop orchestration, adaptive scheduling, drift-aware execution |
| `DA` | Paid only | Direction Anchor constitutional control |

### Commercial Enhancement Packs

The repository also contains `paid/l0`, `paid/l1`, `paid/l2`, and `paid/l3`.
Those modules are enhancement packs for the free foundation layers. They do not change the
release-facing count, which must always remain:

- `5 Free layers`
- `3 Paid core layers`

## 3. Canonical Directory Structure

```text
opensource/gcc_evolution/
  free/
    ui/
    l0/
    l1/
    l2/
    l3/
  paid/
    l0/   # commercial enhancement pack
    l1/   # commercial enhancement pack
    l2/   # commercial enhancement pack
    l3/   # commercial enhancement pack
    l4/
    l5/
    da/
  legacy/
  layer_manifest.py
```

## 4. Hard Release Rules

- Release-facing documentation must describe the framework as `5 Free + 3 Paid`.
- `L4` must never be described as free.
- `L5` must never be described as free.
- `DA` must never be described as free.
- `paid/l0-l3` may be described as enhancement packs, but not as additional top-level layers.
- Packaging, README files, and user manuals must all follow the same boundary.

## 5. Legacy Compatibility

Legacy packages remain in the repository for compatibility only:

- `L0_setup`
- `L1_memory`
- `L2_retrieval`
- `L3_distillation`
- `L4_decision`
- `L5_orchestration`
- `direction_anchor`
- `observer`
- `enterprise`

They do not define the commercial boundary.
The canonical boundary is defined only by:

- `FRAMEWORK_BOUNDARY.md`
- `FRAMEWORK_BOUNDARY.en.md`
- `LAYER_STRUCTURE.md`
- `gcc_evolution/free/`
- `gcc_evolution/paid/`

## 6. Release Interpretation

If someone asks "what is free?", answer with:

- `UI, L0, L1, L2, L3`

If someone asks "what is paid?", answer with:

- `L4, L5, DA`

If someone asks about `paid/l0-l3`, answer:

- "Those are paid enhancement packs for the free foundation layers, not additional top-level layers."
