# gcc-evo v5.330

See also: [FRAMEWORK_BOUNDARY.md](FRAMEWORK_BOUNDARY.md) | [FRAMEWORK_BOUNDARY.en.md](FRAMEWORK_BOUNDARY.en.md) | [LAYER_STRUCTURE.md](LAYER_STRUCTURE.md) | [PRICING.en.md](PRICING.en.md)

`gcc-evo` is an AI self-evolution framework with a strict release boundary:

- `5 Free foundation layers`: `UI`, `L0`, `L1`, `L2`, `L3`
- `3 Paid core layers`: `L4`, `L5`, `DA`
- `paid/l0-l3` are commercial enhancement packs for the free foundation layers

## Release Model

### Free Foundation

| Layer | Purpose | CLI / Entry |
|---|---|---|
| `UI` | Dashboard, setup, visibility | `gcc-evo version`, `gcc-evo health` |
| `L0` | Setup, prerequisites, safe bootstrap | `gcc-evo setup KEY-001`, `gcc-evo l0 scaffold`, `gcc-evo l0 check` |
| `L1` | Persistent memory | `gcc-evo memory compact`, `gcc-evo memory export` |
| `L2` | Retrieval and normalization | Integrated module surface in the free foundation; no standalone CLI in the opensource package |
| `L3` | Distillation and reusable skills | Integrated module surface in the free foundation; task-driven through `pipe` and runtime outputs |

### Paid Core

| Layer | Purpose | Why it is paid |
|---|---|---|
| `L4` | Decision evolution, skeptic gate, benchmark acceptance | It is the model-comparison and acceptance control center |
| `L5` | Closed-loop orchestration, adaptive scheduling, drift-aware execution | It turns isolated tools into a self-improving operating loop |
| `DA` | Direction Anchor constitutional governance | It enforces non-negotiable strategic constraints |

### Commercial Enhancement Packs

`paid/l0`, `paid/l1`, `paid/l2`, and `paid/l3` are commercial enhancement packs. They strengthen the free layers, but they do not change the public release count.

The release-facing statement must always remain:

- `5 Free + 3 Paid`

## Why the Paid Core Exists

The strongest gcc-evo design goal is not simple memory or retrieval. It is a governed improvement engine that can:

1. evaluate competing decisions with measurable acceptance criteria
2. orchestrate a closed loop instead of isolated commands
3. enforce a constitutional direction anchor so the system does not drift

That design goal lives in the paid core: `L4 + L5 + DA`.

## Installation

### Community

```bash
pip install gcc-evo
gcc-evo version
```

### Source

```bash
git clone https://github.com/baodexiang/gcc-evo.git
cd gcc-evo/opensource
pip install -e "."
```

## Quick Start

### Free Foundation Flow

```bash
gcc-evo init
gcc-evo setup KEY-001
gcc-evo l0 scaffold
gcc-evo l0 check
gcc-evo pipe task "Improve error handling" -k KEY-001 -m core -p P1
gcc-evo pipe list
gcc-evo pipe status GCC-0001
gcc-evo memory compact
gcc-evo memory export
gcc-evo health
```

### Paid Core Flow

```bash
gcc-evo loop GCC-0001 --once
```

The paid core flow activates decision evolution and closed-loop orchestration. In the canonical model, `loop` belongs to paid `L5` and depends on paid `L4` controls.

## Pricing

| Tier | Includes |
|---|---|
| `Community` | `UI + L0 + L1 + L2 + L3` |
| `Evolve` | `Community + paid/l0-l3` |
| `Pro` | `Evolve + L4 + L5` |
| `Enterprise` | `Pro + DA + enterprise deployment` |

## Stability Notes

- Free layers should run independently for setup, memory, retrieval, distillation, and visibility.
- Paid layers should fail clearly with upgrade guidance rather than silently pretending to be available.
- Legacy packages remain for compatibility only and do not define the commercial boundary.

## Documents

- [QUICKSTART.en.md](QUICKSTART.en.md)
- [README.zh.md](README.zh.md)
- [PRICING.md](PRICING.md)
- [FRAMEWORK_BOUNDARY.md](FRAMEWORK_BOUNDARY.md)
- [LAYER_STRUCTURE.md](LAYER_STRUCTURE.md)
