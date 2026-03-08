# Quick Start - gcc-evo v5.330

This guide follows the canonical release model:

- `Free foundation`: `UI + L0 + L1 + L2 + L3`
- `Paid core`: `L4 + L5 + DA`
- `paid/l0-l3` are enhancement packs

## 1. Install

```bash
pip install gcc-evo
gcc-evo version
```

## 2. Free Foundation Workflow

### Step 1: Initialize the project

```bash
gcc-evo init
```

### Step 2: Configure L0

```bash
gcc-evo setup KEY-001
gcc-evo l0 scaffold
gcc-evo l0 check
```

### Step 3: Create a task

```bash
gcc-evo pipe task "Improve retrieval quality" -k KEY-001 -m retrieval -p P1
```

### Step 4: Use free foundation capabilities

```bash
gcc-evo memory compact
gcc-evo memory export
gcc-evo health
gcc-evo pipe list
gcc-evo pipe status GCC-0001
```

### Step 5: OCR documents and generate knowledge cards

```bash
gcc-evo knowledge ocr-pdf paper.pdf output_cards
gcc-evo knowledge cards output_cards --book "Wyckoff Methodology" --chapter "Chapter 1" --refine
```

If an LLM is configured, you can continue with:

```bash
gcc-evo knowledge cards output_cards --book "Wyckoff Methodology" --chapter "Chapter 1" --refine --llm-refine --llm-repeat 3
```

## 3. Paid Core Workflow

The strongest gcc-evo workflow starts when the paid core is enabled.

```bash
gcc-evo loop GCC-0001 --once
```

This is paid-core because it relies on:

- `L4` decision evolution and skeptic acceptance
- `L5` closed-loop orchestration and drift-aware execution
- `DA` constitutional direction control in enterprise deployments

## 4. Pricing Logic

| Tier | Includes |
|---|---|
| `Community` | `UI + L0 + L1 + L2 + L3` |
| `Evolve` | `Community + paid/l0-l3` |
| `Pro` | `Evolve + L4 + L5` |
| `Enterprise` | `Pro + DA` |

## 5. Stability Rules

- Free commands must work without paid modules.
- Paid commands must fail with explicit upgrade guidance if unavailable.
- Public release notes must always use the `5 Free + 3 Paid` model.
