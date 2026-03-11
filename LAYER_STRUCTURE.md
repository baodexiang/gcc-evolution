# gcc-evo v5.345 Canonical 8-Layer Split

This file is the authoritative directory split for the v5.300/v5.345 commercial boundary.

## Canonical Release Model

1. `UI` - free
2. `L0` - free
3. `L1` - free
4. `L2` - free
5. `L3` - free
6. `L4` - paid only
7. `L5` - paid only
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

## Mapping Rule

- `free/` is the canonical 5-layer community foundation.
- `paid/` contains the canonical paid core (`l4/l5/da`) and commercial enhancement packs (`paid/l0-l3`).
- `legacy/` documents the compatibility packages that still remain at the root.
- New code and documentation should map to `free/` and `paid/` first.

## Strict Commercial Boundary

- `L4` must not be treated as free in the canonical structure.
- `L5` must not be treated as free in the canonical structure.
- `DA` must not be treated as free in the canonical structure.
- Directory layout and documentation should always reflect the `5 Free + 3 Paid` release model.

