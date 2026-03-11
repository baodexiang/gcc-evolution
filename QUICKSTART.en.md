# Quick Start - gcc-evo v5.400

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
gcc-evo l0 set-prereq data_quality --status pass --evidence "acceptance"
gcc-evo l0 set-prereq deterministic_rules --status pass --evidence "acceptance"
gcc-evo l0 set-prereq mathematical_filters --status pass --evidence "acceptance"
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

### Step 5: Run the community smoke loop

```bash
gcc-evo loop DEMO-001 --once --dry-run
```

This command is the open-source smoke path. It runs one local iteration,
persists audit output under `state/`, and verifies that the free package is
installed correctly.

### Step 6: Optional OCR utilities

The repository includes helper scripts such as `ocr.py`, `ocr_pdf.py`, and
`pdf_to_cards_v3.py`, but the current open-source `gcc-evo` CLI does not ship a
`knowledge` command group.

## 3. Paid Core Workflow

The strongest gcc-evo workflow starts when the paid core is enabled.

```bash
gcc-evo loop GCC-0001 --once
```

This is paid-core production orchestration because it relies on:

- `L4` decision evolution and skeptic acceptance
- `L5` closed-loop orchestration and drift-aware execution
- `DA` constitutional direction control in enterprise deployments

If `gcc-evo l0 check` still reports `BLOCKED`, complete the three
`gcc-evo l0 set-prereq ... --status pass` steps before running the loop.

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
