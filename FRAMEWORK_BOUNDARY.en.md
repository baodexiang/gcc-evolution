# gcc-evo v5.325 Framework Boundary

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

## 2. Free vs Paid

| Unit | Canonical status | Scope |
|------|------------------|-------|
| `UI` | Free | Setup dashboard, connector setup, status visibility |
| `L0` | Mixed | `Phase 1` free, `Phase 2-4` paid |
| `L1` | Mixed | Base free, full memory paid |
| `L2` | Mixed | Base retrieval free, full retrieval paid |
| `L3` | Mixed | Base distillation free, full distillation paid |
| `L4` | Paid only | Decision evolution engine |
| `L5` | Mixed | Base orchestration free, advanced orchestration paid |
| `DA` | Paid only | Direction Anchor constitutional gate |

## 3. Canonical Directory Structure

```text
opensource/gcc_evolution/
  free/
    ui/
    l0/
    l1/
    l2/
    l3/
    l5/
  paid/
    l0/
    l1/
    l2/
    l3/
    l4/
    l5/
    da/
  layer_manifest.py
```

## 4. Hard Rules Before Open Source Release

- `L4` must not be described as free.
- `DA` must not be described as free.
- `L0` must explicitly distinguish free `Phase 1` from paid `Phase 2-4`.
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
- `gcc_evolution/free/`
- `gcc_evolution/paid/`

## 6. Release Interpretation

If someone asks "what is free?" answer with the `free/` tree.
If someone asks "what is paid?" answer with the `paid/` tree.
If someone asks "is L4 free?" answer `No`.
If someone asks "is DA free?" answer `No`.
