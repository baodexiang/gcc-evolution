# gcc-evo v5.420

See also: [FRAMEWORK_BOUNDARY.md](FRAMEWORK_BOUNDARY.md) | [FRAMEWORK_BOUNDARY.en.md](FRAMEWORK_BOUNDARY.en.md) | [LAYER_STRUCTURE.md](LAYER_STRUCTURE.md) | [PRICING.en.md](PRICING.en.md)

`gcc-evo` is released with one strict product boundary:

- `5 Free foundation layers`: `UI`, `L0`, `L1`, `L2`, `L3`
- `3 Paid core layers`: `L4`, `L5`, `DA`
- `paid/l0-l3` are enhancement packs, not extra top-level layers

## Free Foundation

| Layer | Responsibility | Typical command |
|---|---|---|
| `UI` | Dashboard and operational visibility | `gcc-evo version`, `gcc-evo health` |
| `L0` | Setup, prerequisites, session bootstrap | `gcc-evo setup KEY-001`, `gcc-evo l0 check` |
| `L1` | Persistent memory | `gcc-evo memory compact` |
| `L2` | Retrieval and normalization | Integrated free module surface; no standalone CLI command in the opensource package |
| `L3` | Distillation and reusable skills | Integrated free module surface; primarily task-driven through `pipe` and runtime outputs |

## Paid Core

| Layer | Responsibility | Product purpose |
|---|---|---|
| `L4` | Decision evolution and skeptic acceptance | turn raw outputs into governed decisions |
| `L5` | Closed-loop orchestration and adaptive scheduling | turn tools into a self-improving operating loop |
| `DA` | Direction Anchor constitutional governance | keep the system aligned to fixed strategic rules |

## Commercial Enhancement Packs

`paid/l0-l3` exist to enhance setup governance, memory quality, retrieval quality, and distillation quality. They are commercial modules, but the public top-level message must still be `5 Free + 3 Paid`.

## Strongest Design Goal

The strongest part of gcc-evo is the paid core:

1. `L4` gives measurable decision acceptance
2. `L5` gives closed-loop execution and drift-aware orchestration
3. `DA` gives constitutional direction control

Without those three layers, gcc-evo is a strong foundation. With them, it becomes a governed self-evolution engine.

## Installation

```bash
pip install gcc-evo
gcc-evo version
```

## Free Workflow

```bash
gcc-evo init
gcc-evo setup KEY-001
gcc-evo l0 scaffold
gcc-evo l0 check
gcc-evo l0 set-prereq data_quality --status pass --evidence "acceptance"
gcc-evo l0 set-prereq deterministic_rules --status pass --evidence "acceptance"
gcc-evo l0 set-prereq mathematical_filters --status pass --evidence "acceptance"
gcc-evo pipe task "Improve retrieval quality" -k KEY-001 -m retrieval -p P1
gcc-evo pipe list
gcc-evo pipe status GCC-0001
gcc-evo memory compact
gcc-evo memory export
gcc-evo health
gcc-evo loop DEMO-001 --once --dry-run
```

## OCR and Knowledge Card Flow

OCR and card generation are currently shipped as repository scripts, not `gcc-evo` subcommands.

```bash
python ocr_pdf.py paper.pdf output_cards
python pdf_to_cards_v3.py output_cards --book "Wyckoff Methodology" --chapter "Chapter 1" --refine
```

If an LLM is configured, you can run an additional refinement pass:

```bash
python pdf_to_cards_v3.py output_cards --book "Wyckoff Methodology" --chapter "Chapter 1" --refine --llm-refine --llm-repeat 3
```

This flow produces:

- `page_*.md` page text
- `page_*.json` structured knowledge cards
- optional DuckDB storage

## Paid Workflow

```bash
gcc-evo loop GCC-0001 --once
```

The open-source package also includes a community smoke path via `gcc-evo loop DEMO-001 --once --dry-run`.
For a non-dry-run loop, make sure the three `L0` prerequisites above are marked `pass` first.

## Pricing

| Tier | Includes |
|---|---|
| `Community` | `UI + L0 + L1 + L2 + L3` |
| `Evolve` | `Community + paid/l0-l3` |
| `Pro` | `Evolve + L4 + L5` |
| `Enterprise` | `Pro + DA + enterprise deployment` |

## Stability and Release Rules

- Free layers must run cleanly on their own.
- Paid layers must show explicit upgrade boundaries.
- Legacy modules may remain in the tree, but they do not define the product boundary.
- Release-facing docs and packages must always use the `5 Free + 3 Paid` model.
