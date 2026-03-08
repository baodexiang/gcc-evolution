# gcc_evolution Package Boundary

This package uses one canonical release-facing split:

- `free/`: community surface
- `paid/`: paid boundary
- `legacy/`: compatibility documentation only

The commercial boundary must be interpreted from canonical paths first.

## Canonical Tree

```text
gcc_evolution/
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
  cli.py
```

## Rule

- Public docs should point to `free/` and `paid/`.
- Old packages such as `L1_memory` or `L4_decision` are implementation compatibility, not tier definition.
- `L4` and `DA` are never free in the canonical model.
