"""
GCC v4.8 — Migration: Scattered Files → Unified Structure

One-time migration that reorganizes all GCC data into a clean hierarchy:

  .gcc/
  ├── CHANGELOG.md              ← 统一记账本
  ├── handoffs.md               ← 交接索引（单文件）
  ├── constraints.json          ← DO NOT 规则
  ├── evolution.yaml            ← 配置
  └── improvements/             ← 改善总目录
      ├── REGISTRY.yaml         ← 改善清单
      ├── SPY-ATR/              ← 每个改善项
      │   ├── README.md
      │   ├── card_001.md
      │   └── params.yaml
      └── ...

Usage:
  gcc-evo migrate          # Scan + report what will happen
  gcc-evo migrate --run    # Execute migration
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# ═══════════════════════════════════════════════════
# Card → Markdown
# ═══════════════════════════════════════════════════

def _card_to_markdown(card) -> str:
    """Convert ExperienceCard to readable markdown."""
    icon = {
        "success": "✅", "failure": "❌", "partial": "⚠️",
        "mutation": "🔄", "crossover": "⭐",
    }.get(getattr(card.exp_type, 'value', str(card.exp_type)), "📝")

    lines = [
        f"# {icon} {card.key_insight}",
        "",
        f"- **ID:** {card.id}",
        f"- **Type:** {getattr(card.exp_type, 'value', str(card.exp_type))}",
        f"- **Status:** {getattr(card.status, 'value', str(card.status))}",
        f"- **Confidence:** {card.confidence:.0%}",
        f"- **Created:** {card.created_at[:10]}",
    ]

    if card.key:
        lines.append(f"- **KEY:** {card.key}")
    if card.source_session:
        lines.append(f"- **Session:** {card.source_session}")

    if card.trigger_symptom:
        lines.append(f"\n## When")
        lines.append(card.trigger_symptom)

    if card.strategy:
        lines.append(f"\n## Strategy")
        lines.append(card.strategy)

    if getattr(card.exp_type, 'value', '') == 'mutation':
        if card.original_step:
            lines.append(f"\n## Before")
            lines.append(card.original_step)
        if card.revised_step:
            lines.append(f"\n## After")
            lines.append(card.revised_step)

    if getattr(card.exp_type, 'value', '') == 'crossover' and card.merged_steps:
        lines.append(f"\n## Best Practice")
        for i, step in enumerate(card.merged_steps, 1):
            lines.append(f"{i}. {step}")

    if card.pitfalls:
        lines.append(f"\n## Pitfalls")
        for pit in card.pitfalls:
            lines.append(f"- ⚠️ {pit}")

    if card.metrics_before or card.metrics_after:
        lines.append(f"\n## Metrics")
        if card.metrics_before:
            lines.append(f"- Before: {json.dumps(card.metrics_before, ensure_ascii=False)}")
        if card.metrics_after:
            lines.append(f"- After: {json.dumps(card.metrics_after, ensure_ascii=False)}")

    if card.tags:
        lines.append(f"\n## Tags")
        lines.append(", ".join(card.tags))

    if card.downstream_scores:
        avg = card.downstream_avg or 0
        lines.append(f"\n## Downstream Impact")
        lines.append(f"- Sessions: {len(card.downstream_scores)}")
        lines.append(f"- Avg score: {avg:.2f}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════
# Handoff → Markdown
# ═══════════════════════════════════════════════════

def _handoff_to_md_entry(data: dict) -> str:
    """Convert a handoff JSON to a markdown log entry."""
    ho_id = data.get("handoff_id", "?")
    key = data.get("key", "")
    created = data.get("created_at", "")[:16]
    source = data.get("source_agent", "")
    target = data.get("target_agent", "")
    status = data.get("status", "")
    summary = data.get("changes_summary", "")

    lines = [f"### {ho_id}"]
    lines.append(f"- **KEY:** {key}")
    lines.append(f"- **Time:** {created}")
    if source:
        lines.append(f"- **From:** {source}")
    if target:
        lines.append(f"- **To:** {target}")
    lines.append(f"- **Status:** {status}")
    if summary:
        lines.append(f"- **Summary:** {summary[:200]}")

    tasks = data.get("tasks", [])
    if tasks:
        lines.append(f"- **Tasks:**")
        for t in tasks:
            desc = t.get("description", t.get("task_id", "?"))
            st = t.get("status", "")
            lines.append(f"  - [{st}] {desc}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════
# Key README Generator
# ═══════════════════════════════════════════════════

def _generate_key_readme(key: str, info: dict, cards_count: int,
                         has_params: bool) -> str:
    """Generate README.md for an improvement folder."""
    status = info.get("status", "open")
    priority = info.get("priority", "")
    task = info.get("task", "")
    icon = "🟢" if status == "open" else "✅" if status == "done" else "⏸️"

    lines = [
        f"# {icon} {key}",
        "",
        f"- **Status:** {status}",
    ]
    if priority:
        lines.append(f"- **Priority:** {priority}")
    if task:
        lines.append(f"- **Description:** {task}")
    lines.append(f"- **Cards:** {cards_count}")
    if has_params:
        lines.append(f"- **Has params.yaml:** yes")
    lines.append(f"- **Updated:** {_ts()}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════
# Scanner — Report what will happen
# ═══════════════════════════════════════════════════

def scan() -> dict:
    """Scan current .gcc/ and report what migration will do."""
    report = {
        "keys": [],
        "cards_total": 0,
        "cards_by_key": {},
        "cards_no_key": 0,
        "handoffs": 0,
        "branch_handoffs": 0,
        "params": [],
        "pipeline_tasks": 0,
        "constraints": 0,
        "already_migrated": False,
    }

    # Check if already migrated
    if Path(".gcc/improvements/REGISTRY.yaml").exists():
        report["already_migrated"] = True

    # Keys
    keys_path = Path(".gcc/keys.yaml")
    if keys_path.exists() and yaml:
        try:
            keys = yaml.safe_load(keys_path.read_text("utf-8")) or {}
            report["keys"] = list(keys.keys())
        except Exception as e:
            logger.warning("[MIGRATE] load keys yaml failed: %s", e)

    # Experience cards from SQLite
    try:
        from gcc_evolution.experience_store import GlobalMemory
        gm = GlobalMemory()
        all_cards = gm.get_all(limit=9999)
        report["cards_total"] = len(all_cards)
        for card in all_cards:
            k = card.key.upper() if card.key else "_UNKEYED"
            report["cards_by_key"][k] = report["cards_by_key"].get(k, 0) + 1
        report["cards_no_key"] = report["cards_by_key"].get("_UNKEYED", 0)
        gm.close()
    except Exception as e:
        logger.warning("[MIGRATE] load cards from db failed: %s", e)

    # Handoffs
    ho_dir = Path(".gcc/handoffs")
    if ho_dir.exists():
        report["handoffs"] = len(list(ho_dir.glob("HO_*.json")))

    # Branch handoffs
    branches_dir = Path(".gcc/branches")
    if branches_dir.exists():
        report["branch_handoffs"] = len(list(branches_dir.glob("*/handoff.md")))

    # Params
    params_dir = Path(".gcc/params")
    if params_dir.exists():
        report["params"] = [f.stem.upper() for f in params_dir.glob("*.yaml")]

    # Pipeline
    pipeline_path = Path(".gcc/pipeline/tasks.json")
    if pipeline_path.exists():
        try:
            tasks = json.loads(pipeline_path.read_text("utf-8"))
            report["pipeline_tasks"] = len(tasks)
        except Exception as e:
            logger.warning("[MIGRATE] load pipeline tasks failed: %s", e)

    # Constraints
    c_path = Path(".gcc/constraints.json")
    if c_path.exists():
        try:
            cdata = json.loads(c_path.read_text("utf-8"))
            report["constraints"] = len(cdata)
        except Exception as e:
            logger.warning("[MIGRATE] load constraints failed: %s", e)

    return report


def format_scan_report(report: dict) -> str:
    """Human-readable scan report."""
    lines = [
        "  GCC v4.8 Migration Scan",
        f"  {'═'*50}",
    ]

    if report["already_migrated"]:
        lines.append("  ⚠ Already migrated (improvements/REGISTRY.yaml exists)")
        lines.append("  Use --force to re-migrate")
        return "\n".join(lines)

    lines.append(f"  Keys found: {len(report['keys'])}")
    for k in report["keys"]:
        lines.append(f"    → {k}")

    lines.append(f"  Experience cards: {report['cards_total']}")
    for k, cnt in sorted(report["cards_by_key"].items()):
        lines.append(f"    → {k}: {cnt} cards")

    lines.append(f"  Handoffs: {report['handoffs']} JSON + {report['branch_handoffs']} branch MD")
    lines.append(f"  Params: {len(report['params'])} products ({', '.join(report['params'][:6])})")
    lines.append(f"  Pipeline tasks: {report['pipeline_tasks']}")
    lines.append(f"  Constraints: {report['constraints']}")

    lines.append("")
    lines.append("  Migration will:")
    lines.append(f"    1. Backup .gcc/ → .gcc/backup_pre475/")
    lines.append(f"    2. Create .gcc/improvements/ with {len(report['keys'])} folders")
    lines.append(f"    3. Export {report['cards_total']} cards to markdown")
    lines.append(f"    4. Merge {report['handoffs'] + report['branch_handoffs']} handoffs → handoffs.md")
    lines.append(f"    5. Move params → improvement folders")
    lines.append(f"    6. Create REGISTRY.yaml + CHANGELOG.md")
    lines.append("")
    lines.append("  Run: gcc-evo migrate --run")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════
# Execute Migration
# ═══════════════════════════════════════════════════

def execute(force: bool = False) -> dict:
    """Execute the full migration."""
    result = {
        "actions": [],
        "errors": [],
        "keys_created": 0,
        "cards_exported": 0,
        "handoffs_merged": 0,
    }

    # Pre-check
    if Path(".gcc/improvements/REGISTRY.yaml").exists() and not force:
        result["errors"].append("Already migrated. Use --force to redo.")
        return result

    if not yaml:
        result["errors"].append("pyyaml required. pip install pyyaml")
        return result

    # ── Step 1: Backup ──
    backup_dir = Path(".gcc/backup_pre475")
    if not backup_dir.exists():
        # Copy key files to backup
        backup_dir.mkdir(parents=True, exist_ok=True)
        for src in ["keys.yaml", "constraints.json", "evolution.yaml"]:
            s = Path(f".gcc/{src}")
            if s.exists():
                shutil.copy2(s, backup_dir / src)
        for src_dir in ["handoffs", "branches", "params", "pipeline"]:
            s = Path(f".gcc/{src_dir}")
            if s.exists():
                shutil.copytree(s, backup_dir / src_dir, dirs_exist_ok=True)
        result["actions"].append(f"Backed up to .gcc/backup_pre475/")

    # ── Step 2: Create improvements structure ──
    imp_dir = Path(".gcc/improvements")
    imp_dir.mkdir(parents=True, exist_ok=True)

    # Load existing keys
    keys_data = {}
    keys_path = Path(".gcc/keys.yaml")
    if keys_path.exists():
        keys_data = yaml.safe_load(keys_path.read_text("utf-8")) or {}

    # Load pipeline tasks and merge into keys
    pipeline_path = Path(".gcc/pipeline/tasks.json")
    if pipeline_path.exists():
        try:
            tasks = json.loads(pipeline_path.read_text("utf-8"))
            for t in tasks:
                k = t.get("key", "").upper()
                if k and k not in keys_data:
                    keys_data[k] = {
                        "status": "open" if t.get("stage") != "done" else "done",
                        "task": t.get("title", ""),
                        "priority": f"P{t.get('priority', 2)}",
                        "task_id": t.get("task_id", ""),
                    }
                elif k and k in keys_data:
                    # Merge pipeline info
                    if not keys_data[k].get("task_id"):
                        keys_data[k]["task_id"] = t.get("task_id", "")
                    if not keys_data[k].get("priority"):
                        keys_data[k]["priority"] = f"P{t.get('priority', 2)}"
        except Exception as e:
            result["errors"].append(f"Pipeline parse: {e}")

    # ── Step 3: Load all experience cards ──
    cards_by_key = {}
    try:
        from gcc_evolution.experience_store import GlobalMemory
        gm = GlobalMemory()
        all_cards = gm.get_all(limit=9999)
        for card in all_cards:
            k = card.key.upper() if card.key else "_UNKEYED"
            if k not in cards_by_key:
                cards_by_key[k] = []
            cards_by_key[k].append(card)
            # Ensure KEY exists in registry
            if k != "_UNKEYED" and k not in keys_data:
                keys_data[k] = {"status": "open", "task": "(from experience cards)"}
        gm.close()
    except Exception as e:
        result["errors"].append(f"Experience DB: {e}")

    # ── Step 4: Create improvement folders ──
    # Also discover keys from params
    params_dir = Path(".gcc/params")
    param_symbol_to_key = {}  # SPY → SPY-ATR (if match), else SPY
    if params_dir.exists():
        for pf in params_dir.glob("*.yaml"):
            sym = pf.stem.upper()
            # Try to find matching KEY
            matched_key = None
            for k in keys_data:
                if sym in k or k.startswith(sym):
                    matched_key = k
                    break
            param_symbol_to_key[sym] = matched_key or sym

    for key, info in keys_data.items():
        if key == "_UNKEYED":
            continue
        key_dir = imp_dir / key
        key_dir.mkdir(exist_ok=True)

        # Export cards
        cards = cards_by_key.get(key, [])
        for i, card in enumerate(cards, 1):
            card_path = key_dir / f"card_{i:03d}.md"
            card_path.write_text(_card_to_markdown(card), encoding="utf-8")
            result["cards_exported"] += 1

        # Move params if matched
        for sym, matched_key in param_symbol_to_key.items():
            if matched_key == key:
                src = params_dir / f"{sym.lower()}.yaml"
                if not src.exists():
                    src = params_dir / f"{sym.upper()}.yaml"
                if src.exists():
                    dst = key_dir / "params.yaml"
                    shutil.copy2(src, dst)

        # Generate README
        has_params = (key_dir / "params.yaml").exists()
        readme = _generate_key_readme(key, info, len(cards), has_params)
        (key_dir / "README.md").write_text(readme, encoding="utf-8")

        result["keys_created"] += 1

    # Handle unkeyed cards
    if "_UNKEYED" in cards_by_key:
        unkeyed_dir = imp_dir / "_UNKEYED"
        unkeyed_dir.mkdir(exist_ok=True)
        for i, card in enumerate(cards_by_key["_UNKEYED"], 1):
            card_path = unkeyed_dir / f"card_{i:03d}.md"
            card_path.write_text(_card_to_markdown(card), encoding="utf-8")
            result["cards_exported"] += 1
        readme = _generate_key_readme("_UNKEYED",
                                      {"status": "open", "task": "Unassigned cards"},
                                      len(cards_by_key["_UNKEYED"]), False)
        (unkeyed_dir / "README.md").write_text(readme, encoding="utf-8")

    # Handle params without matching KEY
    for sym, matched_key in param_symbol_to_key.items():
        if matched_key == sym and sym not in keys_data:
            # Params product without a KEY — create a KEY for it
            key_dir = imp_dir / sym
            key_dir.mkdir(exist_ok=True)
            src = params_dir / f"{sym.lower()}.yaml"
            if not src.exists():
                src = params_dir / f"{sym.upper()}.yaml"
            if src.exists():
                shutil.copy2(src, key_dir / "params.yaml")
            keys_data[sym] = {"status": "open", "task": f"Trading product {sym}"}
            readme = _generate_key_readme(sym, keys_data[sym], 0, True)
            (key_dir / "README.md").write_text(readme, encoding="utf-8")
            result["keys_created"] += 1

    # ── Step 5: Write REGISTRY.yaml ──
    registry = {}
    for key, info in sorted(keys_data.items()):
        if key == "_UNKEYED":
            continue
        registry[key] = {
            "status": info.get("status", "open"),
            "priority": info.get("priority", ""),
            "task": info.get("task", ""),
            "task_id": info.get("task_id", ""),
            "cards": len(cards_by_key.get(key, [])),
            "has_params": (imp_dir / key / "params.yaml").exists(),
        }

    registry_path = imp_dir / "REGISTRY.yaml"
    registry_path.write_text(
        yaml.dump(registry, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    result["actions"].append(f"Created REGISTRY.yaml with {len(registry)} items")

    # ── Step 6: Merge handoffs → handoffs.md ──
    ho_entries = []

    # From JSON handoffs
    ho_dir = Path(".gcc/handoffs")
    if ho_dir.exists():
        for hf in sorted(ho_dir.glob("HO_*.json")):
            try:
                data = json.loads(hf.read_text("utf-8"))
                ho_entries.append(_handoff_to_md_entry(data))
                result["handoffs_merged"] += 1
            except Exception as e:
                logger.warning("[MIGRATE] merge handoff %s failed: %s", hf.name, e)

    # From branch handoffs
    branches_dir = Path(".gcc/branches")
    if branches_dir.exists():
        for md in sorted(branches_dir.glob("*/handoff.md")):
            key_slug = md.parent.name
            content = md.read_text("utf-8").strip()
            ho_entries.append(f"### Branch: {key_slug}\n{content}")
            result["handoffs_merged"] += 1

    handoffs_md = Path(".gcc/handoffs.md")
    ho_lines = [
        "# Handoff Log",
        f"_Last updated: {_ts()}_",
        "",
    ]
    if ho_entries:
        ho_lines.extend(ho_entries)
    else:
        ho_lines.append("No handoffs yet.")

    handoffs_md.write_text("\n\n".join(ho_lines), encoding="utf-8")
    result["actions"].append(f"Created handoffs.md with {result['handoffs_merged']} entries")

    # ── Step 7: Create CHANGELOG.md ──
    changelog = Path(".gcc/CHANGELOG.md")
    if not changelog.exists():
        cl_lines = [
            "# CHANGELOG",
            "",
            f"## {_ts()}",
            f"- Migrated to GCC v4.8 unified structure",
            f"- Created {result['keys_created']} improvement folders",
            f"- Exported {result['cards_exported']} experience cards to markdown",
            f"- Merged {result['handoffs_merged']} handoffs into handoffs.md",
            "",
        ]
        changelog.write_text("\n".join(cl_lines), encoding="utf-8")
        result["actions"].append("Created CHANGELOG.md")
    else:
        # Prepend migration entry
        existing = changelog.read_text("utf-8")
        entry = (
            f"\n## {_ts()}\n"
            f"- Re-migrated to GCC v4.8 unified structure\n"
            f"- {result['keys_created']} improvement folders, "
            f"{result['cards_exported']} cards exported\n\n"
        )
        # Insert after first line
        parts = existing.split("\n", 2)
        if len(parts) >= 2:
            new_content = parts[0] + "\n" + entry + parts[2] if len(parts) > 2 else parts[0] + "\n" + entry
        else:
            new_content = existing + entry
        changelog.write_text(new_content, encoding="utf-8")
        result["actions"].append("Updated CHANGELOG.md")

    return result


def format_migration_report(result: dict) -> str:
    """Human-readable migration result."""
    lines = [
        "  GCC v4.8 Migration Complete",
        f"  {'═'*50}",
    ]

    if result["errors"]:
        for e in result["errors"]:
            lines.append(f"  ✗ {e}")
        if not result["actions"]:
            return "\n".join(lines)

    lines.append(f"  ✓ Created {result['keys_created']} improvement folders")
    lines.append(f"  ✓ Exported {result['cards_exported']} cards to markdown")
    lines.append(f"  ✓ Merged {result['handoffs_merged']} handoffs")

    for a in result["actions"]:
        lines.append(f"  → {a}")

    lines.append("")
    lines.append("  New structure:")
    lines.append("  .gcc/CHANGELOG.md            ← 统一记账本")
    lines.append("  .gcc/handoffs.md             ← 交接索引")
    lines.append("  .gcc/improvements/REGISTRY.yaml ← 改善清单")
    lines.append("  .gcc/improvements/{KEY}/     ← 每个改善项")

    return "\n".join(lines)
