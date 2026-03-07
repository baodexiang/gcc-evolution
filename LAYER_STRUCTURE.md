# gcc-evo v5.325 Canonical 8-Layer Split

This file is the authoritative directory split for the v5.300/v5.325 commercial boundary.

## Canonical Layers

1. `UI` - free
2. `L0` - Phase 1 free, Phase 2-4 paid
3. `L1` - base free, full paid
4. `L2` - base free, full paid
5. `L3` - base free, full paid
6. `L4` - paid only
7. `L5` - base free, full paid
8. `DA` - paid only

## Canonical Directory Tree

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
  legacy/
  layer_manifest.py
```

## Mapping Rule

- `free/` is the canonical community surface.
- `paid/` is the canonical paid boundary.
- `legacy/` documents the compatibility packages that still remain at the root.
- New code and documentation should map to `free/` and `paid/` first.

## Strict Commercial Boundary

- `L4` must not be treated as free in the canonical structure.
- `DA` must not be treated as free in the canonical structure.
- `L0` must distinguish free `Phase 1` from paid `Phase 2-4`.
- Directory layout and documentation should always reflect this split.
