# gcc-evo v5.340 Framework Boundary

This is the authoritative release-facing boundary for gcc-evo before open-source publication.

## 1. Canonical 8 Units

1. `UI`
2. `L0`
3. `L1`
4. `L2`
5. `L3`
6. `L4`
7. `L5`
8. `DA`

## 2. Free 5 Layers vs Paid 3 Layers

| Unit | Canonical status | Scope |
|------|------------------|-------|
| `UI` | Free | Setup dashboard, connector setup, status visibility |
| `L0` | Free | Foundation setup, governance, source intake |
| `L1` | Free | Foundation memory layer |
| `L2` | Free | Foundation retrieval layer |
| `L3` | Free | Foundation distillation layer |
| `L4` | Paid core | Decision evolution engine |
| `L5` | Paid core | Closed-loop orchestration and execution |
| `DA` | Paid core | Direction Anchor constitutional gate |

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
    l4/
    l5/
    da/
    l0/
    l1/
    l2/
    l3/
  legacy/
  layer_manifest.py
```

## 4. Hard Rules Before Open Source Release

- `L4` must not be described as free.
- `L5` must not be described as free in the canonical release model.
- `DA` must not be described as free.
- Release-facing layer count must read as `5 Free + 3 Paid`.
- Any release-facing doc must follow this exact split.
- Packaging and release notes must treat `free/` and `paid/` as the canonical commercial boundary.

## 5. Legacy Compatibility

Legacy packages remain temporarily in the repo for backward compatibility:

- `L0_setup`
- `L1_memory`
- `L2_retrieval`
- `L3_distillation`
- `L4_decision`
- `L5_orchestration`
- `direction_anchor`
- `observer`
- `enterprise`

These legacy packages do not redefine the canonical commercial boundary.
The canonical boundary is defined only by:

- `FRAMEWORK_BOUNDARY.md`
- `LAYER_STRUCTURE.md`
- `PROGRAM_SPLIT_MAP.md`
- `gcc_evolution/free/`
- `gcc_evolution/paid/`

## 6. Release Interpretation

If someone asks "what is free?" answer with the `free/` tree.
If someone asks "what is paid?" answer with the paid core `l4/l5/da` tree first.
If someone asks "is L4 free?" answer `No`.
If someone asks "is L5 free?" answer `No`.
If someone asks "is DA free?" answer `No`.

