---
name: gcc-context
description: Local Claude skill mirror for gcc-evo v5.325. Use when the user wants to inspect, update, validate, or run gcc-evo commands, dashboard, handoff, pipeline, memory, or release packaging from the local Windows workspace.
---

# gcc-context

Use this skill when the task is about `gcc-evo`, `.GCC`, handoff flow, pipeline tasks, dashboard export, release packaging, or syncing the local Claude skill mirror.

## Primary entrypoints

- Preferred command: `gcc-evo <command>`
- Direct script fallback: `python C:/Users/baode/.claude/skills/gcc-context/gcc_evo.py <command>`
- Package fallback: `python -m gcc_evolution <command>`

## Current local baseline

- Skill mirror version: `5.325`
- Workspace root: `C:/Users/baode/onedrive/桌面/ai-trading-bot`
- Project GCC source of truth: `.GCC/`
- Opensource release source: `opensource/`

## Working rules

- Read `.GCC/skill/SKILL.md` when the task needs current project architecture or runtime truth.
- Read `.GCC/pipeline/tasks.json` for task truth, not stale dashboard exports.
- If dashboard content is missing, regenerate `.GCC/dashboard.html` instead of editing the HTML manually.
- For opensource release sync, align version strings first, then rebuild the zip, then verify command smoke checks.
- Keep `.claude/skills/gcc-context` self-contained enough that `python .../gcc_evo.py version` works even if global PATH is stale.

## Local utility scripts

- `ocr.py`
- `load_db.py`
- `ocr_pdf.sh`

Use them only when the user is explicitly working on OCR / paper ingestion.
