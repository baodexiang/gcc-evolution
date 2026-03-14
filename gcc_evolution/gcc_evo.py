#!/usr/bin/env python3
"""gcc-evo v5.405 — GCC Evolution Engine with Visual Dashboard"""
from __future__ import annotations

import json
import os
import sys
import shutil
from pathlib import Path

try:
    import click
except ImportError:
    import subprocess
    print("  ⚡ First run: installing click...", flush=True)
    r = subprocess.run([sys.executable, "-m", "pip", "install",
                        "click", "--quiet", "--break-system-packages"],
                       capture_output=True, text=True)
    if r.returncode == 0:
        print("  ✓ click installed")
        import click
    else:
        print(f"  ✗ click install failed. Fix: pip install click")
        sys.exit(1)


# Ensure .GCC/ dir is on sys.path so sibling modules (log_to_decision_adapter etc.) resolve
_GCC_SELF_DIR = str(Path(__file__).resolve().parent)
if _GCC_SELF_DIR not in sys.path:
    sys.path.insert(0, _GCC_SELF_DIR)

KEYS_FILE = Path(".gcc/keys.yaml")

HELP_TEXT = """  GCC v5.405 — Active Evolution Engine
  ═══════════════════════════════════════════════════

  Daily Use:
    gcc-evo                  Dashboard (auto-scans branches)
    gcc-evo check            Self-check + generate STATUS.md
    gcc-evo show NAME        Detail + handoff + trend
    gcc-evo cards            List cards
    gcc-evo cards -k NAME    Cards for a KEY
    gcc-evo diag             Global diagnostic
    gcc-evo diag NAME        Score trend

  Pipeline:
    gcc-evo pipe             Pipeline status
    gcc-evo pipe add TITLE   Create task (-p P0/P1/P2)
    gcc-evo pipe show ID     Task detail
    gcc-evo pipe next        Advance next stage
    gcc-evo pipe gate        Run gate check

  Handoff (zero-memory — auto-detects everything):
    gcc-evo ho               List handoffs
    gcc-evo ho create        Auto-detect branch → KEY → tasks
    gcc-evo ho pickup        Interactive selection if multiple
    gcc-evo ho done          Complete tasks interactively
    gcc-evo commit "msg"     Git commit with auto [KEY:ID] prefix

  Parameters (KEY-001):
    gcc-evo params           All products dashboard
    gcc-evo params init --all  Init param files for all products
    gcc-evo params show SPY  Show SPY params + backtest
    gcc-evo params gate SPY  Run gate check
    gcc-evo params gate-all  Gate check all products
    gcc-evo params set SPY entry atr_period 10
    gcc-evo params backtest SPY --sharpe 2.3 --max-dd 12 --win-rate 0.58
    gcc-evo params diff SPY  Compare vs defaults

  Constraints (v4.6):
    gcc-evo constraints      List active constraints
    gcc-evo constraints add  Add a DO NOT rule
    gcc-evo constraints for KEY  Get constraints for a KEY

  Skills (v4.6):
    gcc-evo skills           List all callable skills

  Knowledge:
    gcc-evo seed             Show seed types
    gcc-evo seed trading     Load seeds
    gcc-evo compress         Merge duplicates
    gcc-evo embed            Embedder info

  Closed Loop (闭环):
    gcc-evo loop GCC-0172 GCC-0173 --once   绑定任务单次闭环
    gcc-evo loop -k KEY-009 --once          KEY下所有活跃任务
    gcc-evo loop GCC-0172                   绑定任务持续循环(5min)
    gcc-evo loop --dry-run                  预览模式

  Retrospective (回溯分析):
    gcc-evo retro summary          trade_events汇总
    gcc-evo retro analyze SYMBOL   品种回溯分析
    gcc-evo retro report SYMBOL    生成报告(--json-out)
    gcc-evo retro rules SYMBOL     导出结构化规则JSON

  Card Bridge (知识卡活化):
    gcc-evo card index       Scan JSON cards, build index
    gcc-evo card query -m X  Query rules by module
    gcc-evo card report      Effectiveness report
    gcc-evo card distill     Run distillation (update confidence)

  Setup:
    gcc-evo init myproject   Init current dir
    gcc-evo reload           Update engine files

  Migration:
    gcc-evo export           Bundle to gcc_bundle.zip
    gcc-evo import file.zip  Restore bundle

  Info:
    gcc-evo help             This page
    gcc-evo version          Version
    gcc-evo all              All KEYs (incl. closed)

  Data Sources (auto-detected):
    .gcc/branches/*/         Branch dirs as KEYs
    .gcc/improvements.md     Legacy registry
    .gcc/keys.yaml           Explicit KEYs
    .gcc/pipeline/           Task queue
    .gcc/handoffs/           Cross-LLM handoffs
    .gcc/constraints.json    Failure constraints (v4.6)
    .gcc/STATUS.md           Auto-generated status (v4.6)
"""


# ════════════════════════════════════════════════════════════
# GCC-0147: 统一路径
def _gcc_dir() -> Path:
    script_dir = Path(__file__).resolve().parent
    # Prefer the real repo root when running .GCC/gcc_evo.py from inside .GCC/.
    if (script_dir / "pipeline").exists() and (script_dir / "skill").exists():
        return script_dir
    return Path(".GCC") if Path(".GCC").exists() else Path(".gcc")


# Skill Directory / Bootstrap
# ════════════════════════════════════════════════════════════

def _build_search_paths() -> list[Path]:
    paths = []
    env_dir = os.environ.get("GCC_SKILL_DIR")
    if env_dir:
        paths.append(Path(env_dir))
    paths.append(Path("/mnt/skills/user/gcc"))
    paths.append(Path("/mnt/skills/private/gcc"))
    paths.append(Path.home() / ".gcc-global")
    for ev in ("APPDATA", "LOCALAPPDATA"):
        v = os.environ.get(ev)
        if v:
            paths.append(Path(v) / "gcc")
    paths.append(Path.home() / ".claude" / "skills" / "gcc-context")
    paths.append(Path(__file__).parent)
    return paths


SKILL_SEARCH_PATHS = _build_search_paths()

REQUIRED_FILES = {
    "gcc_evolution/__init__.py": "gcc_evolution/__init__.py",
    "gcc_evolution/models.py": "gcc_evolution/models.py",
    "gcc_evolution/config.py": "gcc_evolution/config.py",
    "gcc_evolution/evaluator.py": "gcc_evolution/evaluator.py",
    "gcc_evolution/distiller.py": "gcc_evolution/distiller.py",
    "gcc_evolution/crossover.py": "gcc_evolution/crossover.py",
    "gcc_evolution/planner.py": "gcc_evolution/planner.py",
    "gcc_evolution/experience_store.py": "gcc_evolution/experience_store.py",
    "gcc_evolution/retriever.py": "gcc_evolution/retriever.py",
    "gcc_evolution/session_manager.py": "gcc_evolution/session_manager.py",
    "gcc_evolution/normalizer.py": "gcc_evolution/normalizer.py",
    "gcc_evolution/llm_client.py": "gcc_evolution/llm_client.py",
    "gcc_evolution/handoff.py": "gcc_evolution/handoff.py",
    "gcc_evolution/pipeline.py": "gcc_evolution/pipeline.py",
    "gcc_evolution/params.py": "gcc_evolution/params.py",
    "gcc_evolution/constraints.py": "gcc_evolution/constraints.py",
    "gcc_evolution/skill_registry.py": "gcc_evolution/skill_registry.py",
    "gcc_evolution/selfcheck.py": "gcc_evolution/selfcheck.py",
    "configs/seed_experiences.yaml": "configs/seed_experiences.yaml",
}


def _find_skill_dir() -> Path | None:
    for p in SKILL_SEARCH_PATHS:
        if p.exists() and (p / "gcc_evolution").is_dir():
            return p
    return None


def ensure_init():
    missing = [f for f in REQUIRED_FILES if not Path(f).exists()]
    if missing:
        skill_dir = _find_skill_dir()
        if not skill_dir:
            click.echo("  ✗ gcc_evolution/ not found. Run: gcc-evo reload")
            sys.exit(1)
        click.echo(f"  ⚡ First run — copying engine from {skill_dir}")
        Path("gcc_evolution").mkdir(exist_ok=True)
        copied = 0
        for lp, sp in REQUIRED_FILES.items():
            src, dst = skill_dir / sp, Path(lp)
            if not dst.exists() and src.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                copied += 1
        if copied:
            click.echo(f"  ✓ Copied {copied} files")
    if not (_gcc_dir() / "evolution.yaml").exists():
        from gcc_evolution.config import init_config
        init_config(Path.cwd().name, "custom")
        click.echo(f"  ✓ Created .gcc/evolution.yaml")


def _get_mgr():
    ensure_init()
    from gcc_evolution.session_manager import SessionManager
    return SessionManager.from_config(use_llm=False)


_keys_cache: dict | None = None
_keys_cache_mtimes: dict = {}

def _load_keys() -> dict:
    """
    Read KEYs from all existing sources (never creates files):
      1. .gcc/branches/*/  — auto-scan branch directories
      2. .gcc/improvements.md — legacy registry
      3. .gcc/keys.yaml — explicit KEYs
    Later sources overwrite earlier for same KEY.
    GCC-0147: mtime缓存 — 源文件未变时直接返回缓存结果。
    """
    global _keys_cache, _keys_cache_mtimes
    import re
    import yaml

    # GCC-0147: mtime缓存检查
    _gd = _gcc_dir()
    _check_paths = {
        "branches": _gd / "branches",
        "improvements": _gd / "improvements.md",
        "keys": KEYS_FILE,
    }
    _current_mtimes = {}
    for _ck, _cp in _check_paths.items():
        try:
            if _cp.is_dir():
                # 目录: 用最新子文件的mtime
                _sub_mtimes = [f.stat().st_mtime for f in _cp.rglob("*") if f.is_file()]
                _current_mtimes[_ck] = max(_sub_mtimes) if _sub_mtimes else 0
            elif _cp.exists():
                _current_mtimes[_ck] = _cp.stat().st_mtime
            else:
                _current_mtimes[_ck] = 0
        except Exception:
            _current_mtimes[_ck] = -1  # 强制刷新
    if _keys_cache is not None and _current_mtimes == _keys_cache_mtimes:
        return _keys_cache

    keys = {}

    # ── Source 1: .gcc/branches/*/ ──
    branches_dir = _gd / "branches"
    if branches_dir.is_dir():
        for bdir in sorted(branches_dir.iterdir()):
            if not bdir.is_dir():
                continue
            name = bdir.name
            key = name.upper()
            info = {"task": name, "status": "open", "source": "branch",
                    "branch_dir": str(bdir)}

            # Extract task from commit.md (Branch Purpose line)
            commit_path = bdir / "commit.md"
            if commit_path.exists():
                try:
                    txt = commit_path.read_text("utf-8", errors="ignore")
                    # "### Branch Purpose\n...description..."
                    bp = re.search(
                        r'###?\s*Branch Purpose\s*\n+(.+)',
                        txt, re.IGNORECASE)
                    if bp:
                        info["task"] = bp.group(1).strip().rstrip(".")
                    # Count commits
                    info["commits"] = len(re.findall(
                        r'^## Commit:', txt, re.MULTILINE))
                except Exception:
                    pass

            # Extract richer info from handoff*.md if present
            for hf in bdir.glob("handoff*.md"):
                try:
                    txt = hf.read_text("utf-8", errors="ignore")
                    # "## Current State" section
                    cs = re.search(
                        r'## Current State\s*\n([\s\S]*?)(?=\n## |\Z)',
                        txt)
                    if cs:
                        info["current_state"] = cs.group(1).strip()[:300]
                    # "## Immediate Next Steps" section
                    ns = re.search(
                        r'## Immediate Next Steps\s*\n([\s\S]*?)(?=\n## |\Z)',
                        txt)
                    if ns:
                        info["next_steps"] = ns.group(1).strip()[:300]
                    # "## Known Issues" section
                    ki = re.search(
                        r'## Known Issues[^\n]*\n([\s\S]*?)(?=\n## |\Z)',
                        txt)
                    if ki:
                        info["known_issues"] = ki.group(1).strip()[:300]
                    info["has_handoff"] = True
                except Exception:
                    pass
                break  # only first handoff

            # metadata.yaml — check for key/status overrides
            meta_path = bdir / "metadata.yaml"
            if meta_path.exists():
                try:
                    m = yaml.safe_load(
                        meta_path.read_text("utf-8")) or {}
                    # These fields may or may not exist
                    if m.get("task") or m.get("title") or m.get("description"):
                        info["task"] = (m.get("task") or m.get("title")
                                        or m.get("description"))
                    if m.get("status"):
                        info["status"] = m["status"]
                    if m.get("key"):
                        key = m["key"].upper()
                except Exception:
                    pass

            if (bdir / "log.md").exists():
                info["has_log"] = True

            keys[key] = info

    # ── Source 2: .gcc/improvements.md ──
    imp_path = _gd / "improvements.md"
    if imp_path.exists():
        try:
            text = imp_path.read_text("utf-8", errors="ignore")
            import re
            for h in re.finditer(
                    r'^##\s+([A-Za-z0-9_-]+)(?::\s*(.+))?$',
                    text, re.MULTILINE):
                k = h.group(1).upper()
                task = (h.group(2) or h.group(1)).strip()
                after = text[h.end():h.end()+200]
                sm = re.search(r'status:\s*(open|closed|done|active)',
                               after, re.IGNORECASE)
                status = ("closed" if sm and sm.group(1).lower()
                          in ("closed","done") else "open")
                if k not in keys:
                    keys[k] = {"task": task, "status": status,
                                "source": "improvements.md"}
            for r_ in re.finditer(
                    r'^\|\s*([A-Za-z0-9_-]+)\s*\|\s*(.+?)\s*\|\s*(\w+)\s*\|',
                    text, re.MULTILINE):
                k = r_.group(1).upper()
                if k in ("KEY","---","NAME"): continue
                if k not in keys:
                    keys[k] = {"task": r_.group(2).strip(),
                        "status": "closed" if r_.group(3).lower()
                            in ("closed","done") else "open",
                        "source": "improvements.md"}
        except Exception as e:
            click.echo(f"  ⚠ improvements.md parse error: {e}", err=True)

    # ── Source 3: .gcc/keys.yaml (highest priority) ──
    if KEYS_FILE.exists():
        try:
            raw = yaml.safe_load(KEYS_FILE.read_text("utf-8")) or {}
            for k, v in raw.items():
                if isinstance(v, str):
                    keys[k] = {"task": v, "status": "open",
                                "source": "keys.yaml"}
                else:
                    v.setdefault("source", "keys.yaml")
                    keys[k] = v
        except Exception as e:
            click.echo(f"  ⚠ keys.yaml parse error: {e}", err=True)

    # GCC-0147: 更新缓存
    _keys_cache = keys
    _keys_cache_mtimes = _current_mtimes
    return keys


def _get_key_cards(key, task, all_cards):
    task_words = set(w for w in task.lower().split() if len(w) >= 3)
    return [c for c in all_cards
            if key.lower() in c.searchable_text().lower()
            or len(task_words & set(c.searchable_text().lower().split())) >= 2]


# ════════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════════

@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx):
    """GCC v5.290 — Self-Evolution Engine + Smart Handoff"""
    if ctx.invoked_subcommand is None:
        _show_dashboard(False)


# ── help ──

@cli.command("help")
def cmd_help():
    """Show all commands with examples."""
    click.echo(HELP_TEXT)


# ── show ──

@cli.command("show")
@click.argument("key")
def cmd_show(key):
    """Show KEY detail + score trend."""
    _show_key(key)


# ── all ──

@cli.command("all")
def cmd_all():
    """All improvements (including closed)."""
    _show_dashboard(True)


# ── cards ──

@cli.command("cards")
@click.option("-k", "--key", default=None, help="Filter by KEY")
@click.option("-s", "--status", default=None,
              type=click.Choice(["draft","active","validated","archived","deprecated"]))
@click.option("-t", "--type", "exp_type", default=None,
              type=click.Choice(["success","failure","mutation","crossover","partial"]))
@click.option("-n", "--limit", default=20)
def cmd_cards(key, status, exp_type, limit):
    """List experience cards."""
    mgr = _get_mgr()
    cards = mgr.global_mem.get_by_key(key.upper()) if key else mgr.global_mem.get_all(limit=limit*3)
    if status:
        cards = [c for c in cards if c.status.value == status]
    if exp_type:
        cards = [c for c in cards if c.exp_type.value == exp_type]
    cards = cards[:limit]

    if not cards:
        click.echo("\n  No cards found.\n"); mgr.close(); return

    click.echo(f"\n  ✦ Experience Cards ({len(cards)})")
    click.echo(f"  {'═'*45}")
    icons = {"success":"✓","failure":"✗","mutation":"↻","crossover":"★","partial":"~"}
    for c in cards:
        i = icons.get(c.exp_type.value, "?")
        k = f" [{c.key}]" if c.key else ""
        d = f" ↑{c.downstream_avg:.0%}" if c.downstream_avg > 0 else ""
        click.echo(f"  {i} {c.confidence:.0%}{d} {c.key_insight[:55]}{k}")
    click.echo()
    mgr.close()


# ── diag ──

@cli.command("diag")
@click.argument("key", required=False)
def cmd_diag(key):
    """Diagnostic & score trend."""
    mgr = _get_mgr()
    if key:
        key = key.upper()
        trend = mgr.get_key_trend(key)
        click.echo(f"\n  ✦ {key} Diagnostic")
        click.echo(f"  {'═'*40}")
        if trend:
            click.echo(f"  Score Trend ({len(trend)} sessions):")
            for i, t in enumerate(trend):
                d = ""
                if i > 0:
                    v = t["score"] - trend[i-1]["score"]
                    d = f" ({'+' if v>=0 else ''}{v:.2f})"
                click.echo(f"    {i+1}. {t['score']:.2f}{d}  {t['task'][:35]}")
        else:
            click.echo(f"  No scores for {key}")
        cards = mgr.global_mem.get_by_key(key)
        hi = sorted([c for c in cards if c.downstream_avg > 0],
                     key=lambda c: c.downstream_avg, reverse=True)[:5]
        if hi:
            click.echo(f"\n  Top Impact:")
            for c in hi:
                click.echo(f"    ↑{c.downstream_avg:.0%} {c.key_insight[:45]}")
    else:
        stats = mgr.get_experience_stats()
        click.echo(f"\n  ✦ Global Diagnostic")
        click.echo(f"  {'═'*40}")
        click.echo(f"  Cards: {stats['total']}  Conf: {stats['avg_confidence']:.0%}")
        click.echo(f"  Types: ✓{stats['by_type'].get('success',0)} "
                   f"✗{stats['by_type'].get('failure',0)} "
                   f"↻{stats['by_type'].get('mutation',0)} "
                   f"★{stats['by_type'].get('crossover',0)}")
        keys = _load_keys()
        if keys:
            click.echo(f"\n  KEY Trends:")
            for k in keys:
                t = mgr.get_key_trend(k)
                if t:
                    scores = [x["score"] for x in t]
                    arrow = "↑" if len(scores)>1 and scores[-1]>scores[0] else "→"
                    click.echo(f"    {k}: {arrow} {' → '.join(f'{s:.2f}' for s in scores)}")
    click.echo()
    mgr.close()


# ── seed ──

@cli.command("seed")
@click.argument("types", nargs=-1)
def cmd_seed(types):
    """Load seed experiences."""
    mgr = _get_mgr()
    if not types:
        import yaml
        p = Path("configs/seed_experiences.yaml")
        if not p.exists():
            click.echo("  ✗ No seed file. Run: gcc-evo reload"); mgr.close(); return
        raw = yaml.safe_load(p.read_text("utf-8")) or {}
        click.echo("\n  Available seed types:")
        for k, v in raw.items():
            click.echo(f"    {k:25s} ({len(v)} cards)")
        click.echo(f"\n  Usage: gcc-evo seed <type>\n"); mgr.close(); return
    loaded = mgr.seed_experiences(list(types))
    click.echo(f"  ✓ Loaded {loaded} cards for: {', '.join(types)}")
    mgr.close()


# ── compress ──

@cli.command("compress")
@click.option("-t", "--threshold", default=0.70)
@click.option("--dry-run", is_flag=True)
def cmd_compress(threshold, dry_run):
    """Merge similar cards."""
    mgr = _get_mgr()
    if dry_run:
        cards = sorted(mgr.global_mem.get_all(limit=10000),
                       key=lambda c: c.confidence, reverse=True)
        from gcc_evolution.experience_store import GlobalMemory
        dupes, seen = 0, []
        for c in cards:
            if c.status.value == "deprecated": continue
            for s in seen:
                if GlobalMemory._word_overlap(c.key_insight, s.key_insight) > threshold:
                    click.echo(f"  ≈ KEEP [{s.confidence:.0%}] {s.key_insight[:45]}")
                    click.echo(f"    DROP [{c.confidence:.0%}] {c.key_insight[:45]}")
                    dupes += 1; break
            else:
                seen.append(c)
        click.echo(f"\n  Would deprecate {dupes} cards")
    else:
        n = mgr.compress_experiences(threshold=threshold)
        click.echo(f"  ✓ Deprecated {n} duplicate cards")
    mgr.close()


# ── embed ──

@cli.command("embed")
@click.option("--reembed", is_flag=True, help="Rebuild all vectors")
def cmd_embed(reembed):
    """Embedder info & management."""
    mgr = _get_mgr()
    info = mgr.embedder_info()
    click.echo(f"\n  Embedder: {info['type']} (dim={info['dim']}, model={info['model']})")
    if reembed:
        n = mgr.reembed_all()
        click.echo(f"  ✓ Re-embedded {n} cards")
    else:
        no = sum(1 for c in mgr.global_mem.get_all(limit=10000) if not c.embedding)
        if no:
            click.echo(f"  ⚠ {no} cards missing vectors → gcc-evo embed --reembed")
    click.echo()
    mgr.close()


# ── export / import ──

@cli.command("export")
@click.option("-o", "--output", default="gcc_bundle.zip")
def cmd_export(output):
    """Bundle project for device migration."""
    mgr = _get_mgr()
    m = mgr.export_bundle(output)
    click.echo(f"\n  ✦ Exported: {m['project']} ({m['card_count']} cards)")
    for f in m["files"]:
        click.echo(f"    📦 {f}")
    click.echo(f"\n  ✓ Saved: {output}")
    click.echo(f"  Restore: gcc-evo import {output}\n")
    mgr.close()


@cli.command("import")
@click.argument("bundle", type=click.Path(exists=True))
@click.option("--overwrite", is_flag=True)
def cmd_import(bundle, overwrite):
    """Restore from migration bundle."""
    mgr = _get_mgr()
    r = mgr.import_bundle(bundle, overwrite=overwrite)
    if "error" in r:
        click.echo(f"  ✗ {r['error']}"); mgr.close(); return
    m = r["manifest"]
    click.echo(f"\n  Source: {m.get('project','?')} v{m.get('gcc_version','?')} "
               f"({m.get('card_count','?')} cards)")
    if r["restored"]:
        click.echo(f"  ✓ Restored {len(r['restored'])} files:")
        for f in r["restored"]:
            click.echo(f"    📥 {f}")
    if r["skipped"]:
        click.echo(f"  ⊘ Skipped {len(r['skipped'])} (use --overwrite)")
    click.echo(f"  Current: {r['card_count']} cards\n")
    mgr.close()


# ── reload ──

@cli.command("reload")
def cmd_reload():
    """Update engine files from skill directory."""
    skill_dir = _find_skill_dir()
    if not skill_dir:
        click.echo("  ✗ Skill dir not found"); return
    Path("gcc_evolution").mkdir(exist_ok=True)
    copied = 0
    for lp, sp in REQUIRED_FILES.items():
        src, dst = skill_dir / sp, Path(lp)
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst); copied += 1
    click.echo(f"  ✓ Updated {copied} files from {skill_dir}")


# ── init ──

@cli.command("init")
@click.argument("name", required=False)
@click.option("-t", "--type", "ptype", default="custom")
def cmd_init(name, ptype):
    """Initialize GCC in current directory."""
    name = name or Path.cwd().name
    from gcc_evolution.config import init_config
    init_config(name, ptype)
    click.echo(f"  ✓ Initialized '{name}' ({ptype})")
    click.echo(f"  Next: gcc-evo seed {ptype}")


# ── version ──

@cli.command("version")
def cmd_version():
    """Show version."""
    try:
        from gcc_evolution import __version__
        click.echo(f"  gcc-evo v{__version__}")
    except ImportError:
        click.echo("  gcc-evo (engine not found)")


# ── check (v4.75) ──

@cli.command("check")
def cmd_check():
    """Self-check all GCC modules + generate STATUS.md."""
    from gcc_evolution.selfcheck import run_self_check, format_check_report
    result = run_self_check(verbose=True)
    click.echo(f"\n{format_check_report(result)}\n")


# ── config audit (GCC-0155/S19) ──

@cli.command("config-audit")
def cmd_config_audit():
    """GCC-0155/S19: Scan config files for sensitive information (API keys, secrets)."""
    from gcc_evolution.config import load_config, CONFIG_SEARCH_PATHS, LOCAL_CONFIG_SEARCH_PATHS
    from pathlib import Path

    click.echo("🔍 GCC Config Security Audit\n")

    # 1. 检查配置文件存在性
    click.echo("── Config Files ──")
    found_main = None
    for p in CONFIG_SEARCH_PATHS:
        exists = Path(p).exists()
        status = "✓" if exists else "·"
        click.echo(f"  {status} {p}")
        if exists and not found_main:
            found_main = p

    found_local = None
    for p in LOCAL_CONFIG_SEARCH_PATHS:
        exists = Path(p).exists()
        status = "✓" if exists else "·"
        click.echo(f"  {status} {p} (private)")
        if exists:
            found_local = p

    # 2. API key 安全检查
    click.echo("\n── API Key Safety ──")
    config = load_config()
    warnings = config.check_api_key_safety()

    if warnings:
        for w in warnings:
            click.echo(f"  ⚠ {w}")
    else:
        click.echo("  ✓ No hardcoded API keys detected")

    # 3. API key 来源
    click.echo("\n── Key Source ──")
    import os
    if os.environ.get("GCC_API_KEY"):
        click.echo("  ✓ GCC_API_KEY env var set")
    elif os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY"):
        provider_key = "ANTHROPIC_API_KEY" if os.environ.get("ANTHROPIC_API_KEY") else "OPENAI_API_KEY"
        click.echo(f"  ✓ {provider_key} env var set")
    elif found_local:
        click.echo(f"  ✓ Key loaded from {found_local}")
    elif config.llm_api_key:
        click.echo("  ⚠ Key present but source unclear — check for hardcoded values")
    else:
        click.echo("  · No API key configured (LLM calls will fail)")

    # 4. .gitignore 检查
    click.echo("\n── .gitignore Check ──")
    gitignore = Path(".gitignore")
    if gitignore.exists():
        content = gitignore.read_text(encoding="utf-8", errors="ignore")
        if "evolution.local.yaml" in content or "*.local.yaml" in content:
            click.echo("  ✓ evolution.local.yaml is in .gitignore")
        else:
            click.echo("  ⚠ evolution.local.yaml NOT in .gitignore — add it!")
        if ".env" in content:
            click.echo("  ✓ .env is in .gitignore")
        else:
            click.echo("  ⚠ .env NOT in .gitignore")
    else:
        click.echo("  ⚠ No .gitignore found!")

    # 5. 总结
    click.echo("")
    if not warnings:
        click.echo("✅ Config security audit passed")
    else:
        click.echo(f"⚠ {len(warnings)} issue(s) found — fix before publishing")


# ── rules (GCC-0155/S74) ──

@cli.command("rules")
@click.option("--status", type=click.Choice(["DISCOVERED", "VALIDATING", "ACTIVE", "RETIRED", "all"]),
              default="all", help="Filter by status")
@click.option("--key", default="", help="Filter by KEY")
@click.option("--decay", is_flag=True, help="Run decay check on active rules")
def cmd_rules(status, key, decay):
    """Show rule registry and lifecycle status."""
    from gcc_evolution.rule_registry import RuleRegistry, RuleStatus

    registry = RuleRegistry()

    if decay:
        retired = registry.check_decay()
        if retired:
            click.echo(f"⚠ Retired {len(retired)} stale rules: {retired}")
        else:
            click.echo("✓ No stale rules found")
        return

    summary = registry.summary()
    click.echo(f"📋 Rule Registry — {summary['total']} rules")
    for s, c in summary["by_status"].items():
        click.echo(f"  {s}: {c}")

    if status == "all":
        rules = list(registry.rules.values())
    else:
        rules = registry.get_rules_by_status(RuleStatus(status))

    if key:
        rules = [r for r in rules if r.key == key]

    if not rules:
        click.echo("\n  (no matching rules)")
        return

    click.echo("")
    for r in rules[:30]:
        click.echo(f"  {r.rule_id} [{r.status.value}] {r.trigger_condition} → {r.action} "
                    f"(conf={r.confidence:.2f}, n={r.sample_count})")


# ── migrate (v4.75) ──

@cli.command("migrate")
@click.option("--run", is_flag=True, help="Execute migration (default: scan only)")
@click.option("--force", is_flag=True, help="Force re-migration")
def cmd_migrate(run, force):
    """Migrate scattered files → unified improvements/ structure."""
    from gcc_evolution.migrate import scan, format_scan_report, execute, format_migration_report
    if run:
        result = execute(force=force)
        click.echo(f"\n{format_migration_report(result)}\n")
    else:
        report = scan()
        click.echo(f"\n{format_scan_report(report)}\n")


# ════════════════════════════════════════════════════════════
# Context Chain (v4.8)
# ════════════════════════════════════════════════════════════

@cli.command("context")
@click.argument("key", default="")
@click.option("--query", "-q", default="", help="Search query")
@click.option("--max-cards", "-n", default=10, help="Max cards to retrieve")
def cmd_context(key, query, max_cards):
    """Retrieve layered context chain for a KEY."""
    from gcc_evolution.context_chain import ContextChain, format_context_report
    chain = ContextChain()
    result = chain.retrieve(query=query or key, key=key, max_cards=max_cards)
    click.echo(f"\n{format_context_report(result)}\n")


# ════════════════════════════════════════════════════════════
# Memory Tiers (v4.8)
# ════════════════════════════════════════════════════════════

@cli.group("memory", invoke_without_command=True)
@click.pass_context
def cmd_memory(ctx):
    """3-tier memory management."""
    if ctx.invoked_subcommand is None:
        from gcc_evolution.memory_tiers import MemoryTiers, format_tiers_report
        tiers = MemoryTiers()
        click.echo(f"\n{format_tiers_report(tiers.stats())}\n")


@cmd_memory.command("observe")
@click.argument("text")
@click.option("--key", "-k", default="", help="Improvement KEY")
def cmd_memory_observe(text, key):
    """Record a sensory observation."""
    from gcc_evolution.memory_tiers import MemoryTiers
    tiers = MemoryTiers()
    item = tiers.observe(text, key=key)
    click.echo(f"  Recorded observation: {item.id}")


@cmd_memory.command("promote")
@click.option("--session", "-s", default="", help="Session ID")
@click.option("--key", "-k", default="", help="KEY filter")
def cmd_memory_promote(session, key):
    """Promote sensory observations to short-term cards."""
    from gcc_evolution.memory_tiers import MemoryTiers
    tiers = MemoryTiers()
    cards = tiers.promote_sensory(session_id=session, key=key)
    if cards:
        for c in cards:
            click.echo(f"  → Created: {c}")
    else:
        click.echo("  No observations to promote")


@cli.command("consolidate")
@click.option("--force", is_flag=True, help="Force consolidation even below threshold")
def cmd_consolidate(force):
    """Run memory consolidation (merge duplicates, prune low-quality)."""
    from gcc_evolution.memory_tiers import MemoryTiers, format_consolidation_report
    tiers = MemoryTiers()
    result = tiers.consolidate(force=force)
    click.echo(f"\n{format_consolidation_report(result)}\n")


# ════════════════════════════════════════════════════════════
# Constraints Commands (v4.6)
# ════════════════════════════════════════════════════════════

@cli.group("constraints", invoke_without_command=True)
@click.pass_context
def cmd_constraints(ctx):
    """Failure constraint management."""
    if ctx.invoked_subcommand is None:
        from gcc_evolution.constraints import ConstraintStore
        store = ConstraintStore()
        active = store.active_constraints()
        stats = store.stats()
        click.echo(f"\n  ✦ Constraints ({stats['active']} active / {stats['total']} total)")
        click.echo(f"  {'═'*50}")
        if not active:
            click.echo("  No constraints yet. Add: gcc-evo constraints add")
        else:
            for c in active:
                eff = c.effectiveness()
                click.echo(f"  [{c.id}] {c.rule}")
                detail = f"    conf={c.confidence:.0%}"
                if c.key:
                    detail += f" key={c.key}"
                if c.adoption_count + c.violation_count > 0:
                    detail += f" adopt={c.adoption_count} violate={c.violation_count} eff={eff:.0%}"
                click.echo(detail)
        click.echo()


@cmd_constraints.command("add")
@click.argument("rule")
@click.option("-k", "--key", default="", help="KEY this constraint applies to")
@click.option("-c", "--confidence", default=0.7, type=float)
@click.option("--context", default="", help="When this constraint applies")
def cmd_constraints_add(rule, key, confidence, context):
    """Add a DO NOT constraint."""
    from gcc_evolution.constraints import Constraint, ConstraintStore
    store = ConstraintStore()
    c = Constraint(rule=rule, key=key, confidence=confidence, context=context)
    added = store.add(c)
    click.echo(f"  ✓ [{added.id}] DO NOT: {added.rule}")


@cmd_constraints.command("for")
@click.argument("key")
def cmd_constraints_for(key):
    """Show constraints for a KEY (formatted for LLM context)."""
    from gcc_evolution.constraints import ConstraintStore
    store = ConstraintStore()
    output = store.format_for_injection(key)
    if output:
        click.echo(f"\n{output}\n")
    else:
        click.echo(f"  No constraints for {key}")


# ════════════════════════════════════════════════════════════
# Skills Commands (v4.6)
# ════════════════════════════════════════════════════════════

@cli.group("skills", invoke_without_command=True)
@click.pass_context
def cmd_skills(ctx):
    """Skill registry — callable GCC capabilities."""
    if ctx.invoked_subcommand is None:
        from gcc_evolution.skill_registry import SkillRegistry
        reg = SkillRegistry()
        skills = reg.list_skills()
        click.echo(f"\n  ✦ Skills ({len(skills)} registered)")
        click.echo(f"  {'═'*50}")
        for s in skills:
            click.echo(f"  {s['name']}")
            click.echo(f"    {s['description'][:70]}")
        click.echo()


@cmd_skills.command("call")
@click.argument("name")
@click.argument("args", nargs=-1)
def cmd_skills_call(name, args):
    """Call a skill by name. Args as key=value pairs."""
    from gcc_evolution.skill_registry import SkillRegistry
    reg = SkillRegistry()
    kwargs = {}
    for a in args:
        if "=" in a:
            k, v = a.split("=", 1)
            try:
                v = json.loads(v)
            except (json.JSONDecodeError, ValueError):
                pass
            kwargs[k] = v
    result = reg.call(name, **kwargs)
    if result.success:
        click.echo(f"  ✓ {name} ({result.duration_ms}ms)")
        if isinstance(result.data, dict):
            click.echo(json.dumps(result.data, indent=2, ensure_ascii=False))
        elif isinstance(result.data, str):
            click.echo(result.data)
        else:
            click.echo(f"  {result.data}")
    else:
        click.echo(f"  ✗ {name}: {result.error}")


# ════════════════════════════════════════════════════════════
# Dashboard & Detail
# ════════════════════════════════════════════════════════════

def _show_dashboard(include_closed):
    mgr = _get_mgr()
    stats = mgr.get_experience_stats()
    keys = _load_keys()
    all_cards = mgr.global_mem.get_all(limit=500)

    label = "All" if include_closed else "Active"
    click.echo(f"\n  ✦ GCC v4.6 — {label} Improvements")
    click.echo(f"  {'═'*38}")

    if not keys:
        click.echo("    No KEYs, branches, or improvements found.\n")
        mgr.close(); return

    shown = 0
    for key, info in keys.items():
        task, status = info["task"], info.get("status", "open")
        if not include_closed and status == "closed":
            continue
        kc = _get_key_cards(key, task, all_cards)
        s = len(set(c.source_session for c in kc if c.source_session))
        ok = sum(1 for c in kc if c.exp_type.value == "success")
        fail = sum(1 for c in kc if c.exp_type.value == "failure")
        mut = sum(1 for c in kc if c.exp_type.value == "mutation")
        xo = sum(1 for c in kc if c.exp_type.value == "crossover")
        conf = sum(c.confidence for c in kc) / len(kc) if kc else 0

        # Branch source extras
        commits = info.get("commits", 0)
        src_tag = {"branch": "⎇", "improvements.md": "📋",
                   "keys.yaml": ""}.get(info.get("source", ""), "")

        if status == "closed": icon = "✅"
        elif kc: icon = "🟢" if conf > 0.7 else "🟡" if conf > 0.4 else "🔴"
        else: icon = "⚪"

        trend = mgr.get_key_trend(key)
        ts = ""
        if trend:
            sc = [t["score"] for t in trend[-3:]]
            ts = f" | {'→'.join(f'{v:.0%}' for v in sc)}"

        click.echo(f"\n  {icon} {key}: {task}")
        # Line 2: stats
        p = []
        src = info.get("source", "")
        if src == "branch":
            c_count = info.get("commits", 0)
            extras = []
            if c_count: extras.append(f"{c_count} commits")
            if info.get("has_handoff"): extras.append("handoff")
            if info.get("has_log"): extras.append("log")
            if extras: p.append(f"⎇ {', '.join(extras)}")
        if s: p.append(f"S:{s}")
        if ok or fail:
            p.append(f"✓{ok} ✗{fail}")
        if mut: p.append(f"↻{mut}")
        if xo: p.append(f"★{xo}")
        if kc: p.append(f"C:{conf:.0%}")
        if ts: p.append(ts.lstrip(" | "))
        if p:
            click.echo(f"     {' | '.join(p)}")
        shown += 1

    if not shown:
        click.echo("    None found.")

    total = len(keys)
    op = sum(1 for v in keys.values() if v.get("status","open") == "open")
    click.echo(f"\n  {'─'*38}")
    click.echo(f"  KEYs: {op} open, {total-op} closed | "
               f"Cards: {stats['total']} | "
               f"Embedder: {mgr.embedder_info()['type']}")
    click.echo()
    mgr.close()


def _show_key(key):
    mgr = _get_mgr()
    key = key.upper()
    keys = _load_keys()

    if key not in keys:
        click.echo(f"\n  {key} not found. Registered:")
        for k, v in keys.items():
            i = "✅" if v.get("status","open") == "closed" else "○"
            click.echo(f"    {i} {k}: {v['task']}")
        click.echo(); mgr.close(); return

    info = keys[key]
    task, status = info["task"], info.get("status", "open")
    all_cards = mgr.global_mem.get_all(limit=500)
    kc = _get_key_cards(key, task, all_cards)

    sl = "✅ CLOSED" if status == "closed" else "○ OPEN"
    click.echo(f"\n  ✦ {key}: {task} [{sl}]")
    click.echo(f"  {'═'*40}")

    # Branch context (from handoff/commit/log)
    if info.get("source") == "branch":
        extras = []
        if info.get("commits"):
            extras.append(f"{info['commits']} commits")
        if info.get("has_handoff"):
            extras.append("handoff")
        if info.get("has_log"):
            extras.append("log")
        if extras:
            click.echo(f"  Source: ⎇ branch ({', '.join(extras)})")

        if info.get("current_state"):
            click.echo(f"\n  ── Current State ──")
            for line in info["current_state"].split("\n")[:6]:
                line = line.strip()
                if line:
                    click.echo(f"    {line}")

        if info.get("next_steps"):
            click.echo(f"\n  ── Next Steps ──")
            for line in info["next_steps"].split("\n")[:5]:
                line = line.strip()
                if line:
                    click.echo(f"    {line}")

        if info.get("known_issues"):
            click.echo(f"\n  ── Known Issues ──")
            for line in info["known_issues"].split("\n")[:5]:
                line = line.strip()
                if line:
                    click.echo(f"    {line}")

    trend = mgr.get_key_trend(key)
    if trend:
        click.echo(f"  Score Trend:")
        for i, t in enumerate(trend):
            d = ""
            if i > 0:
                v = t["score"] - trend[i-1]["score"]
                d = f" ({'+' if v>=0 else ''}{v:.2f})"
            click.echo(f"    {i+1}. {t['score']:.2f}{d}")

    if not kc:
        click.echo("    No experience yet.\n"); mgr.close(); return

    sess = len(set(c.source_session for c in kc if c.source_session))
    click.echo(f"  Sessions: {sess} | Cards: {len(kc)}")

    for label, tp, icon in [("What worked", "success", "✓"),
                             ("What to avoid", "failure", "✗"),
                             ("Revised", "mutation", "↻"),
                             ("Best practice", "crossover", "★")]:
        subset = [c for c in kc if c.exp_type.value == tp]
        if not subset:
            continue
        click.echo(f"\n  ── {label} ──")
        for c in subset:
            click.echo(f"    {icon} [{c.confidence:.0%}] {c.key_insight}")
            if tp == "failure":
                for pit in c.pitfalls[:2]:
                    click.echo(f"      → {pit}")
            if tp == "mutation" and c.revised_step:
                click.echo(f"      Was:    {c.original_step}")
                click.echo(f"      Should: {c.revised_step}")
            if tp == "crossover" and c.merged_steps:
                click.echo(f"      Steps: {' → '.join(c.merged_steps)}")

    hi = sorted([c for c in kc if c.downstream_avg > 0],
                key=lambda c: c.downstream_avg, reverse=True)[:3]
    if hi:
        click.echo(f"\n  ── Impact ──")
        for c in hi:
            click.echo(f"    ↑{c.downstream_avg:.0%} "
                       f"({len(c.downstream_sessions)}s) {c.key_insight[:45]}")
    click.echo()
    mgr.close()


# ════════════════════════════════════════════════════════════
# v4.97 — ExpeL Insights + SkillRL Distillation
# ════════════════════════════════════════════════════════════

@cli.command("distill")
@click.argument("subcommand", type=click.Choice(["insights", "skills", "all"]), default="all")
@click.option("--days", "-d", default=30, type=int, help="读取最近N天的经验卡")
@click.option("--max", "-n", "max_insights", default=5, type=int, help="最多归纳几条规律")
@click.option("--project", "-p", default="", help="限定项目")
@click.option("--single-card", is_flag=True, default=False, help="多卡合并为单张汇总卡")
@click.option("--merge", is_flag=True, default=False, help="与 --max 1 等效的合并标记")
@click.option("--dry-run", is_flag=True, default=False, help="预览结果，不写入数据库")
def cmd_distill(subcommand, days, max_insights, project, single_card, merge, dry_run):
    """v5.100 — ExpeL跨卡洞察归纳 + 单卡蒸馏 + SkillRL技能蒸馏。

    \b
    子命令:
      insights  从近N天经验卡归纳通用规律（ExpeL #06）
      skills    从知识卡蒸馏 SkillBank（SkillRL #16）
      all       同时执行两者（默认）

    \b
    示例:
      gcc-evo distill
      gcc-evo distill insights --days 60 --max 8
      gcc-evo distill insights --project pcsui-laser --single-card
      gcc-evo distill insights --project pcsui-laser --max 1 --merge
      gcc-evo distill insights --dry-run
      gcc-evo distill skills
    """
    try:
        from gcc_evolution.experience_store import GlobalMemory
        from gcc_evolution.distiller import Distiller, InsightCard
        from gcc_evolution.config import GCCConfig
    except ImportError as _e:
        click.echo(f"  ⚠  distill 跳过: 依赖模块未找到 ({_e})")
        sys.exit(2)  # exit code 2 = skip (不是错误)
    from datetime import datetime, timezone, timedelta

    # --merge 等效 --single-card + --max 1
    if merge:
        single_card = True
        max_insights = 1

    if subcommand in ("insights", "all"):
        mode_label = "单卡蒸馏" if single_card else "ExpeL Insights"
        click.echo(f"\n  🔬 {mode_label} — 读取近 {days} 天经验卡...")
        if dry_run:
            click.echo("  📋 dry-run 模式：仅预览，不写入")
        try:
            store = GlobalMemory()
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            # 读取近期经验卡（修复v5.100: 正确参数签名）
            all_cards = store.search(keywords=[], project=project or None, limit=200)
            recent = [c for c in all_cards
                      if not c.created_at or c.created_at >= cutoff]
            click.echo(f"  找到 {len(recent)} 张近期经验卡")

            if recent:
                # 构建 LLM
                llm = None
                try:
                    cfg = GCCConfig.load()
                    if cfg.llm_api_key:
                        from gcc_evolution.llm_client import LLMClient
                        llm = LLMClient(cfg)
                except Exception as e:
                    click.echo(f"  ⚠ LLM init failed: {e}", err=True)

                d = Distiller(llm=llm)

                if single_card:
                    # ── 单卡蒸馏模式 ──
                    merged = d.distill_single_card(recent)
                    if merged:
                        _display_single_card(merged, dry_run)
                        if not dry_run:
                            _save_single_card_to_store(store, merged, project)
                    else:
                        click.echo("  ⚠  单卡蒸馏失败")
                        _fallback_template(recent, project)
                else:
                    # ── 多条规律归纳模式 ──
                    insights = d.distill_insights(recent, max_insights=max_insights)

                    if insights:
                        _display_insights(insights, dry_run)
                        if not dry_run:
                            _save_insights_to_skillbank(insights)
                    else:
                        click.echo("  没有归纳出规律（经验卡数量可能不足）")
            else:
                click.echo("  ℹ  无近期卡片")
        except Exception as e:
            click.echo(f"  ⚠  distill 失败: {e}")
            # P2: 失败回退模板
            try:
                if 'recent' in dir() and recent:
                    _fallback_template(recent, project)
                else:
                    click.echo("  无法生成回退模板（无可用卡片）")
            except Exception:
                click.echo("  回退模板也失败，请手工处理")

    if subcommand in ("skills", "all"):
        click.echo(f"\n  🛠  SkillRL — 重蒸馏需复审的 skills...")
        try:
            from gcc_evolution.skill_registry import SkillBank
            sb = SkillBank()
            n = sb.auto_redist_marked()
            if n > 0:
                click.echo(f"  ✅ 重蒸馏 {n} 个 skills")
            else:
                n2 = sb.distill_from_cards()
                click.echo(f"  ✅ 从知识卡蒸馏 {n2} 个 general skills")
        except Exception as e:
            click.echo(f"  ⚠  {e}")


# ── v5.100 Distill Helper Functions ──────────────────────

def _display_single_card(card, dry_run: bool = False):
    """显示单卡蒸馏结果（可审计格式）。"""
    prefix = "[DRY-RUN] " if dry_run else ""
    click.echo(f"\n  ✅ {prefix}单卡蒸馏完成:\n")
    click.echo(f"  📝 汇总结论:")
    click.echo(f"     {card.insight}\n")
    if card.key_strategies:
        click.echo(f"  🎯 关键策略:")
        for i, s in enumerate(card.key_strategies, 1):
            click.echo(f"     {i}. {s}")
        click.echo()
    if card.metrics_before or card.metrics_after:
        click.echo(f"  📊 前后指标:")
        if card.metrics_before:
            click.echo(f"     Before: {card.metrics_before}")
        if card.metrics_after:
            click.echo(f"     After:  {card.metrics_after}")
        click.echo()
    click.echo(f"  🔗 来源卡: {card.evidence_count} 张 | 置信度: {card.confidence:.0%}")
    click.echo(f"     置信度计算: 来源卡confidence加权平均")
    if card.source_card_ids:
        ids_preview = ", ".join(card.source_card_ids[:5])
        if len(card.source_card_ids) > 5:
            ids_preview += f" ...等{len(card.source_card_ids)}个"
        click.echo(f"     来源IDs: {ids_preview}")
    click.echo()


def _display_insights(insights, dry_run: bool = False):
    """显示多条规律归纳结果（可审计格式）。"""
    prefix = "[DRY-RUN] " if dry_run else ""
    click.echo(f"\n  ✅ {prefix}归纳出 {len(insights)} 条通用规律:\n")
    for i, ins in enumerate(insights, 1):
        click.echo(f"  [{i}] {ins.insight}")
        click.echo(f"      证据: {ins.evidence_count} 张卡 | 置信度: {ins.confidence:.0%}")
        if ins.applies_to:
            click.echo(f"      适用: {', '.join(ins.applies_to)}")
        if ins.source_card_ids:
            ids_preview = ", ".join(ins.source_card_ids[:3])
            if len(ins.source_card_ids) > 3:
                ids_preview += f" ...等{len(ins.source_card_ids)}个"
            click.echo(f"      来源IDs: {ids_preview}")
        click.echo()


def _save_single_card_to_store(store, card, project: str):
    """将单卡蒸馏结果存入 GlobalMemory + SkillBank。"""
    from gcc_evolution.models import ExperienceCard, ExperienceType
    try:
        exp = ExperienceCard(
            exp_type=ExperienceType.CROSSOVER,
            key_insight=card.insight,
            strategy="; ".join(card.key_strategies[:5]) if card.key_strategies else "",
            metrics_before=card.metrics_before,
            metrics_after=card.metrics_after,
            confidence=card.confidence,
            project=project or "",
            tags=card.tags[:10],
            related_ids=card.related_ids,
            source_sessions=[],
        )
        store.store(exp)
        click.echo(f"  💾 新卡ID: {exp.id}")
        click.echo(f"     related_ids: {len(card.related_ids)} 张来源卡")
    except Exception as e:
        click.echo(f"  ⚠  存入 GlobalMemory 失败: {e}")

    # 同时写入 SkillBank
    try:
        from gcc_evolution.skill_registry import SkillBank, SkillEntry
        sb = SkillBank()
        entry = SkillEntry(
            skill_id=f"DISTILL_{abs(hash(card.insight)) % 100000:05d}",
            name=card.insight[:50],
            skill_type="general",
            symbol="",
            key_id="",
            content=card.to_skill_content(),
            source="distill_single_card",
            confidence=card.confidence,
        )
        sb.add(entry)
        click.echo(f"  💾 已存入 SkillBank（skill_type=general）")
    except Exception as e:
        click.echo(f"  ⚠  SkillBank 写入失败: {e}")


def _save_insights_to_skillbank(insights):
    """将多条规律存入 SkillBank。"""
    try:
        from gcc_evolution.skill_registry import SkillBank, SkillEntry
        sb = SkillBank()
        for ins in insights:
            entry = SkillEntry(
                skill_id=f"INSIGHT_{abs(hash(ins.insight)) % 100000:05d}",
                name=ins.insight[:50],
                skill_type="general",
                symbol="",
                key_id="",
                content=ins.to_skill_content(),
                source="expel_insights",
                confidence=ins.confidence,
            )
            sb.add(entry)
        click.echo(f"  💾 已存入 SkillBank（skill_type=general）")
    except Exception as e:
        click.echo(f"  ⚠  SkillBank 写入失败: {e}")


def _fallback_template(cards, project: str):
    """P2: distill 失败时的回退模板（输出到 stdout + 文件）。"""
    import os
    click.echo("\n  📄 回退模式: 生成手工汇总草案...\n")

    key_insights = [c.key_insight for c in cards if c.key_insight][:10]
    strategies = [c.strategy for c in cards if c.strategy][:5]
    card_ids = [c.id for c in cards]

    template = f"""# Distill 手工汇总草案
## 项目: {project or '(全部)'}
## 来源卡: {len(cards)} 张
## 生成时间: {_now_iso_fallback()}

### 汇总结论
（请手工编辑以下要点为一段话）
{chr(10).join(f'- {ki}' for ki in key_insights)}

### 关键策略
{chr(10).join(f'{i+1}. {s}' for i, s in enumerate(strategies))}

### 来源卡IDs
{', '.join(card_ids[:20])}
"""
    click.echo(template)

    # 写文件
    out_dir = os.path.join(".GCC", "improvement", "distill_drafts")
    os.makedirs(out_dir, exist_ok=True)
    fname = f"draft_{project or 'all'}_{_now_iso_fallback()[:10]}.md"
    out_path = os.path.join(out_dir, fname)
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(template)
        click.echo(f"  📁 草案已保存: {out_path}")
    except Exception as e:
        click.echo(f"  ⚠  草案保存失败: {e}")


def _now_iso_fallback() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# ════════════════════════════════════════════════════════════
# Pipeline Commands (v4.4+)
# ════════════════════════════════════════════════════════════

@cli.group("pipe", invoke_without_command=True)
@click.pass_context
def cmd_pipe(ctx):
    """Pipeline status & management."""
    if ctx.invoked_subcommand is None:
        _pipe_dashboard()


def _pipe_dashboard():
    from gcc_evolution.pipeline import TaskPipeline
    pipe = TaskPipeline()
    s = pipe.summary()

    click.echo(f"\n  ✦ Pipeline Dashboard")
    click.echo(f"  {'═'*50}")

    if not pipe.tasks:
        click.echo("    No tasks. Create: gcc-evo pipe add \"title\"")
        click.echo(); return

    stage_icons = {
        "pending": "⏳", "analyze": "🔍", "design": "📐",
        "implement": "⚙️", "test": "🧪", "integrate": "🔗",
        "done": "✅", "failed": "❌", "suspended": "⏸️",
    }

    # v5.010: 三层分组 KEY → pipeline(module) → 子任务
    grouped = {}  # {key: {module: [task]}}
    for tid, task in pipe.tasks.items():
        k = task.key or "(no-key)"
        m = getattr(task, "module", "") or ""
        grouped.setdefault(k, {}).setdefault(m, []).append(task)

    for key in sorted(grouped.keys()):
        modules = grouped[key]
        all_tasks = [t for mm in modules.values() for t in mm]
        done_count = sum(1 for t in all_tasks if t.stage.value == "done")
        click.echo(f"\n  ┌─ {key} ({done_count}/{len(all_tasks)} done)")

        sorted_mods = sorted(modules.keys())
        for mi, mod in enumerate(sorted_mods):
            tasks_in_mod = modules[mod]
            is_last_mod = (mi == len(sorted_mods) - 1)
            branch = "└" if is_last_mod else "├"
            vert = " " if is_last_mod else "│"

            if mod:
                # --- Pipeline层 (第二层): 显示 pipeline 名字 + 进度 ---
                mod_done = sum(1 for t in tasks_in_mod if t.stage.value == "done")
                click.echo(f"  │  {branch}─ 📦 {mod} ({mod_done}/{len(tasks_in_mod)})")
                # --- 子任务 (第三层): 这里才显示优先级 ---
                for ti, task in enumerate(tasks_in_mod):
                    icon = stage_icons.get(task.stage.value, "?")
                    is_last = (ti == len(tasks_in_mod) - 1)
                    sub_br = "└" if is_last else "├"
                    if task.stage.value == "done":
                        click.echo(f"  │  {vert}  {sub_br}─ {icon} {task.task_id} {task.title}")
                    else:
                        gate_info = ""
                        if task.gate_results:
                            last = task.gate_results[-1]
                            gate_info = f" Gate:{last.get('result', '?')}"
                        click.echo(f"  │  {vert}  {sub_br}─ {icon} {task.task_id} [{task.priority}] {task.title}")
                        click.echo(f"  │  {vert}  {'  ' if is_last else '│ '} Stage: {task.stage.value}{gate_info}")
            else:
                # --- 无 pipeline 分组: task 直接作为子任务显示 ---
                for task in tasks_in_mod:
                    icon = stage_icons.get(task.stage.value, "?")
                    if task.stage.value == "done":
                        click.echo(f"  │  {icon} {task.task_id} {task.title}")
                    else:
                        gate_info = ""
                        if task.gate_results:
                            last = task.gate_results[-1]
                            gate_info = f" Gate:{last.get('result', '?')}"
                        click.echo(f"  │  {icon} {task.task_id} [{task.priority}] {task.title}")
                        click.echo(f"  │     Stage: {task.stage.value}{gate_info}")

        click.echo(f"  └{'─'*49}")

    click.echo(f"\n  Total: {s['total_tasks']} | Done: {s['completed']} | "
               f"Tokens: {s['total_tokens']:,} | Cost: ${s['total_cost']:.2f}")
    click.echo()


@cmd_pipe.command("add")
@click.argument("title")
@click.option("-p", "--priority", default="P2",
              type=click.Choice(["P0","P1","P2","P3","P4"]))
@click.option("-d", "--desc", default="")
@click.option("-k", "--key", default="")
def cmd_pipe_add(title, priority, desc, key):
    """Create a new pipeline task."""
    from gcc_evolution.pipeline import TaskPipeline
    pipe = TaskPipeline()
    task = pipe.create_task(title, description=desc, priority=priority, key=key)
    click.echo(f"  ✓ Created {task.task_id}: {title} [{priority}]")


def _auto_export_dashboard():
    """Pipeline变更后自动重新导出dashboard.html"""
    try:
        import shutil
        _gcc = _gcc_dir()
        src_tpl = _gcc / "gcc_dashboard.html"
        dst_tpl = _gcc / "gcc_evolution" / "gcc_dashboard.html"
        if src_tpl.exists() and dst_tpl.parent.exists():
            shutil.copy2(src_tpl, dst_tpl)
        from click.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(cmd_dashboard, ["--export"])
        if result.exit_code == 0:
            click.echo("  ✓ Dashboard 已自动更新")
        else:
            click.echo(f"  ⚠ Dashboard 自动更新失败: {result.output}")
    except Exception as e:
        click.echo(f"  ⚠ Dashboard 自动更新跳过: {e}")


@cmd_pipe.command("task")
@click.argument("title")
@click.option("-k", "--key", default="", help="KEY编号 (如 KEY-007)")
@click.option("-m", "--module", default="", help="模块名 (如 全路径审查)")
@click.option("-p", "--priority", default="P2", help="优先级 P0/P1/P2")
@click.option("-d", "--desc", default="", help="描述")
@click.option("--dep", default="", help="依赖的父任务ID (如 GCC-0103)")
@click.option("-s", "--steps", default="", help="Pipeline步骤,逗号分隔 (如 '扫描静默异常,改为logging,添加计数器')")
def cmd_pipe_task(title, key, module, priority, desc, dep, steps):
    """直接往 pipeline/tasks.json 添加任务并自动更新 dashboard。

    三级结构: KEY → GCC任务 → Pipeline steps

    示例:
      gcc-evo pipe task "审计brooks_vision" -k KEY-007 -m 全路径审查 -p P1
      gcc-evo pipe task "异常处理加固" -k KEY-008 -p P0 -s "扫描静默异常,改logging,加计数器"
    """
    import json as _json
    _gcc = _gcc_dir()
    pipe_path = _gcc / "pipeline" / "tasks.json"
    if not pipe_path.exists():
        click.echo(f"  ✗ {pipe_path} 不存在"); return

    data = _json.loads(pipe_path.read_text(encoding="utf-8"))
    counter = data.get("counter", 0) + 1
    task_id = f"GCC-{counter:04d}"

    from datetime import date
    today = date.today().isoformat()

    # 解析 steps
    step_list = []
    if steps:
        for i, s in enumerate(steps.split(","), 1):
            s = s.strip()
            if s:
                step_list.append({"id": f"S{i}", "title": s, "status": "pending", "note": ""})

    new_task = {
        "task_id": task_id,
        "title": title,
        "description": desc or title,
        "key": key,
        "module": module,
        "stage": "pending",
        "status": "pending",
        "priority": priority,
        "dependencies": [dep] if dep else [],
        "steps": step_list,
        "created_at": today,
        "updated_at": today,
    }
    data["tasks"].append(new_task)
    data["counter"] = counter
    pipe_path.write_text(_json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    click.echo(f"  ✓ Created {task_id}: {title} [{priority}] key={key} module={module}")
    if step_list:
        click.echo(f"    Steps ({len(step_list)}):")
        for st in step_list:
            click.echo(f"      {st['id']}: {st['title']}")
    _auto_export_dashboard()


@cmd_pipe.command("show")
@click.argument("task_id")
def cmd_pipe_show(task_id):
    """Show task detail + gate history."""
    from gcc_evolution.pipeline import TaskPipeline
    pipe = TaskPipeline()
    task = pipe.get_task(task_id.upper())
    if not task:
        click.echo(f"  ✗ Task {task_id} not found"); return

    click.echo(f"\n  ✦ {task.task_id}: {task.title}")
    click.echo(f"  {'═'*40}")
    click.echo(f"  Priority: {task.priority} | Stage: {task.stage.value}")
    if task.started_at:
        click.echo(f"  Started: {task.started_at[:19]}")
    if task.completed_at:
        click.echo(f"  Done: {task.completed_at[:19]} ({task.duration_sec}s)")

    if task.stage_history:
        click.echo(f"\n  ── Stage History ──")
        for h in task.stage_history:
            click.echo(f"    {h['from']} → {h['to']}  ({h['at'][:19]})")

    if task.steps:
        done = sum(1 for s in task.steps if s.get("status") == "done")
        click.echo(f"\n  ── Pipeline Steps ({done}/{len(task.steps)}) ──")
        for s in task.steps:
            st = s.get("status", "pending")
            icon = "✓" if st == "done" else "⊘" if st == "skip" else "○"
            note = f"  ({s['note']})" if s.get("note") else ""
            click.echo(f"    {icon} {s['id']}: {s['title']}{note}")

    if task.gate_results:
        click.echo(f"\n  ── Gate Results ──")
        for g in task.gate_results:
            r = g.get("result", "?")
            icon = "✅" if r == "passed" else "❌" if r == "failed" else "⚠️"
            click.echo(f"    {icon} {g['stage']} v{g.get('iteration',0)}: "
                       f"{r} ({g.get('pass_rate', 0):.0%})")
            for c in g.get("checks", []):
                ci = "✓" if c["passed"] else "✗"
                req = " *" if c.get("required") else ""
                click.echo(f"      {ci} {c['name']}{req}")
    click.echo()


@cmd_pipe.command("step")
@click.argument("task_id")
@click.argument("action", type=click.Choice(["add", "done", "skip", "list"]))
@click.argument("step_arg", required=False, default="")
def cmd_pipe_step(task_id, action, step_arg):
    """管理GCC任务的Pipeline步骤 (三级结构第三层)。

    示例:
      gcc-evo pipe step GCC-0163 add "扫描静默异常"
      gcc-evo pipe step GCC-0163 done S1
      gcc-evo pipe step GCC-0163 skip S2
      gcc-evo pipe step GCC-0163 list
    """
    import json as _json
    _gcc = _gcc_dir()
    pipe_path = _gcc / "pipeline" / "tasks.json"
    if not pipe_path.exists():
        click.echo(f"  ✗ {pipe_path} 不存在"); return

    data = _json.loads(pipe_path.read_text(encoding="utf-8"))
    tasks = data if isinstance(data, list) else data.get("tasks", data)
    task_list = tasks if isinstance(tasks, list) else []

    # 兼容两种格式
    target = None
    for t in task_list:
        if t.get("task_id", "").upper() == task_id.upper():
            target = t; break
    if not target:
        click.echo(f"  ✗ Task {task_id} not found"); return

    steps = target.setdefault("steps", [])

    if action == "list":
        if not steps:
            click.echo(f"  {task_id}: 无Pipeline步骤"); return
        done = sum(1 for s in steps if s.get("status") == "done")
        click.echo(f"  {task_id} Pipeline Steps ({done}/{len(steps)}):")
        for s in steps:
            st = s.get("status", "pending")
            icon = "✓" if st == "done" else "⊘" if st == "skip" else "○"
            click.echo(f"    {icon} {s['id']}: {s['title']}")
        return

    if action == "add":
        if not step_arg:
            click.echo("  ✗ 需要步骤标题"); return
        sid = f"S{len(steps) + 1}"
        steps.append({"id": sid, "title": step_arg, "status": "pending", "note": ""})
        pipe_path.write_text(_json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        click.echo(f"  ✓ {task_id} 添加步骤 {sid}: {step_arg}")
        return

    if action in ("done", "skip"):
        if not step_arg:
            click.echo(f"  ✗ 需要步骤ID (如 S1)"); return
        for s in steps:
            if s["id"].upper() == step_arg.upper():
                s["status"] = action
                pipe_path.write_text(_json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                icon = "✓" if action == "done" else "⊘"
                click.echo(f"  {icon} {task_id}/{s['id']}: {s['title']} → {action}")
                # 检查是否所有步骤都完成
                all_done = all(st.get("status") in ("done", "skip") for st in steps)
                if all_done and steps:
                    click.echo(f"  ★ {task_id} 所有步骤已完成!")
                return
        click.echo(f"  ✗ 步骤 {step_arg} 不存在"); return


@cmd_pipe.command("advance")
@click.argument("task_id", required=False)
def cmd_pipe_advance(task_id):
    """Advance task to next stage. If no ID, advances next queued task."""
    from gcc_evolution.pipeline import TaskPipeline
    pipe = TaskPipeline()
    if not task_id:
        # Smart: advance the next available task
        task = pipe.get_next()
        if not task:
            active = pipe.get_active()
            if active:
                task = active[0]
            else:
                click.echo("  No tasks to advance."); return
        task_id = task.task_id
    new_stage = pipe.advance(task_id.upper())
    if new_stage:
        click.echo(f"  ✓ {task_id.upper()} → {new_stage.value}")
    else:
        click.echo(f"  ✗ Cannot advance {task_id}")


@cmd_pipe.command("gate")
@click.argument("task_id", required=False)
@click.option("--pass-all", is_flag=True, help="Auto-pass all checks")
def cmd_pipe_gate(task_id, pass_all):
    """Run gate check. If no ID, uses first active task."""
    from gcc_evolution.pipeline import TaskPipeline
    pipe = TaskPipeline()
    if not task_id:
        active = pipe.get_active()
        if not active:
            click.echo("  No active tasks."); return
        task_id = active[0].task_id
    task = pipe.get_task(task_id.upper())
    if not task:
        click.echo(f"  ✗ Task {task_id} not found"); return

    gate = pipe.run_gate(task_id.upper(), None if pass_all else None)
    icon = "✅" if gate.result.value == "passed" else "❌"
    click.echo(f"  {icon} Gate {task.stage.value} v{gate.iteration}: "
               f"{gate.result.value} ({gate.pass_rate:.0%})")
    for c in gate.checks:
        ci = "✓" if c.passed else "✗"
        click.echo(f"    {ci} {c.name}")
    if gate.result.value == "failed" and pipe.should_retry(task_id.upper()):
        click.echo(f"\n  Retry available ({task.current_iteration}/{task.max_iterations})")


# ════════════════════════════════════════════════════════════
# Handoff Commands (v4.5 — zero memory burden)
# ════════════════════════════════════════════════════════════

@cli.group("ho", invoke_without_command=True)
@click.pass_context
def cmd_ho(ctx):
    """Handoff protocol — cross-LLM task delegation."""
    if ctx.invoked_subcommand is None:
        _ho_list()


def _ho_list():
    from gcc_evolution.handoff import HandoffProtocol
    handoffs = HandoffProtocol.list_all()
    if not handoffs:
        click.echo("\n  No handoffs. Create: gcc-evo ho create")
        click.echo(); return

    click.echo(f"\n  ✦ Handoffs")
    click.echo(f"  {'═'*55}")
    for h in handoffs[:10]:
        icon = "✅" if h["complete"] else "⏳"
        key_tag = f" [{h['key']}]" if h.get("key") else ""
        click.echo(f"  {icon} {h['id']}{key_tag} [{h['tasks']}] {h['summary']}")
        click.echo(f"     {h['source']} → {h['commit']} | {h['created'][:19]}")
    click.echo()


@cmd_ho.command("create")
@click.argument("description", required=False, default="")
@click.option("-k", "--key", default="", help="KEY (skip matching, anchor directly)")
def cmd_ho_create(description, key):
    """Create handoff anchored to an improvement item.

    Usage:
      gcc-evo ho create "改SPY的ATR参数"
      gcc-evo ho create                  # auto from git commit
      gcc-evo ho create -k SPY-ATR       # skip matching, anchor directly
    """
    from gcc_evolution.handoff import HandoffProtocol
    from gcc_evolution.pipeline import TaskPipeline
    from gcc_evolution.config import load_config
    config = load_config()

    # ── Step 1: Get description ──
    hp = HandoffProtocol(project=config.project_name, key=key)
    hp.auto_detect_context()

    if description:
        hp.set_changes_summary(description)

    desc = hp.manifest.changes_summary
    if not desc:
        desc = click.prompt("  What did you change?")
        hp.set_changes_summary(desc)

    # ── Step 2: Anchor to KEY ──
    if not key:
        key = _anchor_to_key(desc, hp.manifest.key)
        hp.manifest.key = key
        hp.manifest.handoff_id = hp._make_id()

    # ── Step 3: Link to pipeline task if exists ──
    pipe_task_id = ""
    try:
        pipe = TaskPipeline()
        if pipe.tasks:
            matching = [
                t for t in pipe.tasks.values()
                if t.key and t.key.upper() == key.upper()
                and t.stage.value not in ("done", "failed")
            ]
            if matching:
                pipe_task_id = matching[0].task_id
                hp.manifest.design_decisions.insert(
                    0, f"Pipeline: {pipe_task_id} ({matching[0].title})")
    except Exception:
        pass

    # ── Step 4: Save ──
    path = hp.save()

    key_tag = f" [{key}]" if key else ""
    pipe_tag = f" → {pipe_task_id}" if pipe_task_id else ""
    click.echo(f"  ✓ Handoff {hp.manifest.handoff_id}{key_tag}{pipe_tag}")
    click.echo(f"    {desc[:60]}")
    click.echo(f"    Tasks: {len(hp.manifest.tasks)}")
    click.echo(f"    File: .gcc/branches/{hp.manifest.branch}/handoff.md")

    # ── Step 5: Suggest commit format ──
    if key:
        commit_prefix = f"[{pipe_task_id}:{key}]" if pipe_task_id else f"[{key}]"
        click.echo(f"\n  Commit format:")
        click.echo(f'    git commit -m "{commit_prefix} {desc[:50]}"')

    # ── Step 6: Auto-sync database ──
    try:
        _db_auto_sync()
        click.echo("  ✓ Database synced")
    except Exception as e:
        click.echo(f"  · db sync skipped ({e})")

    # ── Step 7: Auto-update dashboard ──
    _auto_export_dashboard()


def _db_auto_sync():
    """在 handoff 后自动同步数据库，导入 yaml/improvements/cards/handoff"""
    from gcc_evolution.gcc_db import GccDb
    from gcc_evolution.config import load_config
    from pathlib import Path

    config = load_config()
    gcc_root = Path(config.gcc_dir) if hasattr(config, 'gcc_dir') else Path('.gcc')
    if not gcc_root.exists():
        gcc_root = Path('.GCC')
    if not gcc_root.exists():
        raise FileNotFoundError(".gcc dir not found")

    project_root = gcc_root.parent
    db = GccDb(gcc_root)

    # yaml params
    for params_dir in [gcc_root / 'params', project_root / 'params']:
        if params_dir.exists():
            db.import_yaml_dir(params_dir)

    # improvements.json
    for imp in [project_root / 'state' / 'improvements.json',
                gcc_root / 'improvements.json']:
        if imp.exists():
            db.import_improvements(imp)
            break

    # cards
    for cards_dir in [project_root / 'improvement', gcc_root / 'knowledge']:
        if cards_dir.exists():
            db.import_cards_dir(cards_dir)

    # handoff.md — read from branches/
    branches_dir = gcc_root / 'branches'
    if branches_dir.exists():
        for hf in sorted(branches_dir.glob("*/handoff.md")):
            db.import_handoff_md(hf)


def _anchor_to_key(description: str, auto_key: str) -> str:
    """
    v4.5: Anchor handoff to an existing improvement KEY.
    1. Search keys + pipeline for matches
    2. If 1 match → auto-anchor
    3. If multiple → interactive pick
    4. If none → suggest creating new KEY
    """
    from gcc_evolution.pipeline import TaskPipeline

    # Collect all known KEYs
    candidates = []

    # From keys.yaml / branches / improvements.md
    try:
        keys = _load_keys()
        for k, info in keys.items():
            if info.get("status", "open") != "closed":
                candidates.append({
                    "key": k,
                    "task": info.get("task", k),
                    "source": info.get("source", ""),
                })
    except Exception as e:
        click.echo(f"  ⚠ key load failed: {e}", err=True)

    # From pipeline
    try:
        pipe = TaskPipeline()
        for tid, task in pipe.tasks.items():
            if task.key and task.stage.value not in ("done", "failed"):
                # Don't duplicate if already in keys
                if not any(c["key"] == task.key.upper() for c in candidates):
                    candidates.append({
                        "key": task.key.upper(),
                        "task": task.title,
                        "source": f"pipeline:{tid}",
                    })
    except Exception as e:
        click.echo(f"  ⚠ pipeline load failed: {e}", err=True)

    if not candidates:
        return _suggest_new_key(description, auto_key)

    # Score candidates by keyword overlap + substring matching
    desc_lower = description.lower()
    desc_words = set(w.lower() for w in description.split() if len(w) >= 2)
    scored = []
    for c in candidates:
        key_lower = c["key"].lower().replace("-", " ").replace("_", " ")
        task_lower = c["task"].lower()
        target_words = set(w.lower() for w in
                          f"{c['key']} {c['task']}".replace("-", " ").split()
                          if len(w) >= 2)
        # Word overlap
        overlap = len(desc_words & target_words)
        # Substring match (handles Chinese): KEY name in description
        for part in c["key"].lower().split("-"):
            if len(part) >= 2 and part in desc_lower:
                overlap += 2
        # Task description substring match
        for word in desc_lower.split():
            if len(word) >= 2 and word in task_lower:
                overlap += 1
        # Description chars in task (Chinese char matching)
        for ch in description:
            if ch in c["task"] and ch not in " -_/.":
                overlap += 0.5
        scored.append((overlap, c))

    # Also check if auto_key from branch matches
    if auto_key:
        for score, c in scored:
            if c["key"] == auto_key.upper():
                # Branch name matches a known KEY — auto-anchor
                click.echo(f"  🔗 Anchored to: {c['key']} ({c['task']})")
                return c["key"]

    # Sort by score descending
    scored.sort(key=lambda x: x[0], reverse=True)
    matches = [(s, c) for s, c in scored if s >= 2]

    if not matches:
        return _suggest_new_key(description, auto_key)

    if len(matches) == 1:
        c = matches[0][1]
        click.echo(f"  🔗 Matched: {c['key']} ({c['task']})")
        confirm = click.prompt(f"  Anchor to {c['key']}?", type=bool, default=True)
        if confirm:
            return c["key"]
        return _suggest_new_key(description, auto_key)

    # Multiple matches — interactive
    click.echo(f"\n  Found {len(matches)} matching improvement items:")
    for i, (score, c) in enumerate(matches[:5], 1):
        src = f" [{c['source']}]" if c.get("source") else ""
        click.echo(f"  {i}. {c['key']}: {c['task']}{src}")
    click.echo(f"  n. Create new KEY")
    click.echo()
    choice = click.prompt("  Anchor to", default="1")

    if choice.lower() == "n":
        return _suggest_new_key(description, auto_key)
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(matches):
            c = matches[idx][1]
            click.echo(f"  🔗 Anchored to: {c['key']}")
            return c["key"]
    except ValueError:
        pass

    return _suggest_new_key(description, auto_key)


def _suggest_new_key(description: str, auto_key: str) -> str:
    """Suggest creating a new KEY and add to improvement tracking."""
    # Generate KEY suggestion from description or branch
    if auto_key:
        suggested = auto_key.upper()
    else:
        # Extract key words
        words = [w.upper() for w in description.split()
                 if len(w) >= 3 and w.isalpha()][:3]
        suggested = "-".join(words) if words else "NEW-TASK"

    click.echo(f"\n  No matching improvement item found.")
    key = click.prompt(f"  Create new KEY", default=suggested)
    key = key.upper().replace(" ", "-")

    # Add to keys.yaml
    import yaml
    keys_file = _gcc_dir() / "keys.yaml"
    keys_file.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if keys_file.exists():
        try:
            existing = yaml.safe_load(keys_file.read_text("utf-8")) or {}
        except Exception:
            pass

    if key not in existing:
        existing[key] = {"task": description[:80], "status": "open"}
        keys_file.write_text(
            yaml.dump(existing, allow_unicode=True, default_flow_style=False),
            encoding="utf-8",
        )
        click.echo(f"  ✓ Created KEY: {key} → tracked in .gcc/keys.yaml")

    # Also create pipeline task
    try:
        from gcc_evolution.pipeline import TaskPipeline
        pipe = TaskPipeline()
        task = pipe.create_task(description[:80], key=key, priority="P2")
        click.echo(f"  ✓ Pipeline: {task.task_id} [{key}]")
    except Exception:
        pass

    return key


@cmd_ho.command("show")
@click.argument("handoff_id", required=False)
def cmd_ho_show(handoff_id):
    """Show handoff detail. If no ID, shows latest pending."""
    from gcc_evolution.handoff import HandoffProtocol
    if handoff_id:
        # Find by ID
        for h in HandoffProtocol.list_all():
            if h["id"] == handoff_id or h["id"].startswith(handoff_id):
                hp = HandoffProtocol.load(h["file"])
                break
        else:
            click.echo(f"  ✗ Handoff {handoff_id} not found"); return
    else:
        hp = HandoffProtocol.load_latest()
        if not hp:
            click.echo("  No pending handoffs."); return

    m = hp.manifest
    key_tag = f" [{m.key}]" if m.key else ""
    click.echo(f"\n  ✦ {m.handoff_id}{key_tag}")
    click.echo(f"  {'═'*50}")
    click.echo(f"  From: {m.source_agent} | Branch: {m.branch}")
    click.echo(f"  Commit: {m.commit_hash}")
    click.echo(f"  Changes: {m.changes_summary}")

    if m.files_changed:
        click.echo(f"\n  Files ({len(m.files_changed)}):")
        for f in m.files_changed[:10]:
            click.echo(f"    {f}")

    for label, filter_fn in [("Pending", lambda t: t.status.value == "pending"),
                              ("Done", lambda t: t.status.value == "completed")]:
        subset = [t for t in m.tasks if filter_fn(t)]
        if subset:
            click.echo(f"\n  ── {label} ({len(subset)}) ──")
            for t in subset:
                icon = "⏳" if t.status.value == "pending" else "✅"
                click.echo(f"    {icon} [{t.task_id}] {t.task_type.value}: {t.target_file}")
                click.echo(f"      {t.description}")
    click.echo()


@cmd_ho.command("pickup")
def cmd_ho_pickup():
    """Pick up handoff tasks. Interactive if multiple pending."""
    from gcc_evolution.handoff import HandoffProtocol
    pending = HandoffProtocol.load_all_pending()

    if not pending:
        click.echo("  No pending handoffs."); return

    if len(pending) == 1:
        hp = pending[0]
    else:
        # Interactive selection
        click.echo(f"\n  Multiple pending handoffs:")
        for i, hp in enumerate(pending, 1):
            m = hp.manifest
            key_tag = f" [{m.key}]" if m.key else ""
            n = len(m.pending_tasks())
            click.echo(f"  {i}. {m.handoff_id}{key_tag}: "
                       f"{m.changes_summary[:50]} ({n} tasks)")
        click.echo()
        choice = click.prompt("  Pick", type=int, default=1)
        if choice < 1 or choice > len(pending):
            click.echo("  ✗ Invalid choice"); return
        hp = pending[choice - 1]

    # 合并 orchestrator pending tasks 一起显示
    try:
        from gcc_evolution.orchestrator import Orchestrator
        orc = Orchestrator()
        orc_pending = [t for t in orc.list_tasks() if t.stage.value == "pending"]
        if orc_pending:
            extra = ["", "## Pending Tasks (gcc-evo task create)"]
            for t in orc_pending:
                extra.append(f"  [{t.task_id}] {t.key or '-'}: {t.title}")
            ctx = hp.to_context_string() + "\n".join(extra)
        else:
            ctx = hp.to_context_string()
    except Exception:
        ctx = hp.to_context_string()

    click.echo(ctx)


@cmd_ho.command("done")
@click.argument("task_id", required=False)
@click.option("-a", "--agent", default="", help="Agent that completed")
def cmd_ho_done(task_id, agent):
    """Mark handoff task as done. Interactive if no task ID."""
    from gcc_evolution.handoff import HandoffProtocol
    hp = HandoffProtocol.load_latest(status="pending")
    if not hp:
        click.echo("  No pending handoffs."); return

    m = hp.manifest
    pending = m.pending_tasks()
    if not pending:
        click.echo(f"  All tasks in {m.handoff_id} already done."); return

    if task_id:
        # Direct completion
        if m.complete_task(task_id.upper(), agent=agent):
            hp.save()
            click.echo(f"  ✓ {task_id.upper()} done"
                       + (f" by {agent}" if agent else ""))
        else:
            click.echo(f"  ✗ Task {task_id} not found"); return
    else:
        # Interactive: show pending, ask which to complete
        key_tag = f" [{m.key}]" if m.key else ""
        click.echo(f"\n  {m.handoff_id}{key_tag} — pending tasks:")
        for i, t in enumerate(pending, 1):
            click.echo(f"  {i}. [{t.task_id}] {t.task_type.value}: "
                       f"{t.target_file} — {t.description[:40]}")
        click.echo(f"  a. All done")
        click.echo()
        choice = click.prompt("  Complete", default="a")

        if choice.lower() == "a":
            for t in pending:
                m.complete_task(t.task_id, agent=agent)
            hp.save()
            click.echo(f"  ✓ All {len(pending)} tasks done")
        else:
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(pending):
                    m.complete_task(pending[idx].task_id, agent=agent)
                    hp.save()
                    click.echo(f"  ✓ {pending[idx].task_id} done")
                else:
                    click.echo("  ✗ Invalid choice")
            except ValueError:
                click.echo("  ✗ Invalid choice")

    if m.is_complete():
        click.echo(f"  🎉 All tasks in {m.handoff_id} complete!")

    # v4.5: refresh per-KEY markdown
    hp.save_slim_markdown()


# ════════════════════════════════════════════════════════════
# Params Commands (v4.5 — KEY-001 P0)
# ════════════════════════════════════════════════════════════

@cli.group("params", invoke_without_command=True)
@click.pass_context
def cmd_params(ctx):
    """Product parameter management."""
    if ctx.invoked_subcommand is None:
        _params_dashboard()


def _params_dashboard():
    from gcc_evolution.params import ParamStore, ParamGate
    products = ParamStore.list_products()
    if not products:
        click.echo("\n  No product params. Init: gcc-evo params init")
        click.echo(); return

    click.echo(f"\n  ✦ Product Parameters ({len(products)} products)")
    click.echo(f"  {'═'*50}")
    for sym in products:
        status = ParamGate.quick_status(sym)
        click.echo(f"  {status}")
    click.echo()


@cmd_params.command("init")
@click.argument("symbol", required=False)
@click.option("--all", "init_all", is_flag=True, help="Init all known products")
def cmd_params_init(symbol, init_all):
    """Initialize product param YAML files."""
    from gcc_evolution.params import ParamStore, init_all_products
    if init_all:
        created = init_all_products()
        click.echo(f"  ✓ Created {len(created)} param files: {', '.join(created)}")
    elif symbol:
        path = ParamStore.init_product(symbol)
        click.echo(f"  ✓ Created {path}")
    else:
        click.echo("  Usage: gcc-evo params init SPY  or  gcc-evo params init --all")


@cmd_params.command("show")
@click.argument("symbol")
def cmd_params_show(symbol):
    """Show product parameters and backtest status."""
    from gcc_evolution.params import ParamStore
    params = ParamStore.load(symbol)

    click.echo(f"\n  ✦ {params['symbol']} ({params['market']}) — {params['timeframe']}/{params['trend_tf']}")
    click.echo(f"  {'═'*50}")

    for section in ("entry", "risk", "regime"):
        click.echo(f"\n  ── {section} ──")
        sec = params.get(section, {})
        for k, v in sec.items():
            click.echo(f"    {k}: {v}")

    # Targets vs backtest
    targets = params.get("targets", {})
    bt = params.get("backtest", {})

    click.echo(f"\n  ── targets vs backtest ──")
    click.echo(f"  {'Metric':<20} {'Target':>10} {'Backtest':>10} {'Status':>8}")
    click.echo(f"  {'─'*50}")

    metric_map = [
        ("Sharpe", "sharpe_min", "sharpe", ">="),
        ("Max DD %", "max_dd_pct", "max_dd_pct", "<="),
        ("Win Rate", "win_rate_min", "win_rate", ">="),
        ("Calmar", "calmar_min", "calmar", ">="),
        ("Profit Factor", "profit_factor_min", "profit_factor", ">="),
        ("Sortino", "sortino_min", "sortino", ">="),
        ("CAGR", "cagr_min", "cagr", ">="),
    ]
    for name, tgt_key, bt_key, direction in metric_map:
        t = targets.get(tgt_key)
        b = bt.get(bt_key)
        t_str = f"{t:.2f}" if t is not None else "-"
        b_str = f"{b:.2f}" if b is not None else "-"
        if t is not None and b is not None:
            ok = b >= t if direction == ">=" else b <= t
            s = "✓" if ok else "✗"
        else:
            s = "-"
        click.echo(f"  {name:<20} {t_str:>10} {b_str:>10} {s:>8}")

    if bt.get("updated_at"):
        click.echo(f"\n  Last backtest: {bt['updated_at'][:19]}")
    click.echo()


@cmd_params.command("gate")
@click.argument("symbol")
def cmd_params_gate(symbol):
    """Run gate check on product parameters."""
    from gcc_evolution.params import ParamGate
    result = ParamGate.check(symbol)
    click.echo(f"\n{result.report()}\n")


@cmd_params.command("gate-all")
def cmd_params_gate_all():
    """Run gate check on all products with backtest data."""
    from gcc_evolution.params import gate_check_all
    results = gate_check_all()
    if not results:
        click.echo("  No products with backtest data."); return
    click.echo(f"\n  ✦ Gate Results")
    click.echo(f"  {'═'*50}")
    for sym, r in results.items():
        icon = "✅" if r.passed else "❌"
        click.echo(f"  {icon} {sym}: {r.pass_rate:.0%} ({r.required_pass_rate:.0%} required)")
    click.echo()


@cmd_params.command("set")
@click.argument("symbol")
@click.argument("section")
@click.argument("key")
@click.argument("value")
def cmd_params_set(symbol, section, key, value):
    """Set a single parameter value."""
    from gcc_evolution.params import ParamStore
    # Auto-convert value type
    try:
        v = json.loads(value)
    except (json.JSONDecodeError, ValueError):
        v = value
    path = ParamStore.update_param(symbol, section, key, v)
    click.echo(f"  ✓ {symbol}.{section}.{key} = {v}")


@cmd_params.command("backtest")
@click.argument("symbol")
@click.option("--sharpe", type=float)
@click.option("--max-dd", "max_dd", type=float)
@click.option("--win-rate", "win_rate", type=float)
@click.option("--calmar", type=float)
@click.option("--pf", "profit_factor", type=float, help="Profit factor")
@click.option("--sortino", type=float)
@click.option("--cagr", type=float)
@click.option("--trades", "total_trades", type=int)
@click.option("--period", type=str, help="Backtest period e.g. 2024-01-01/2025-01-01")
def cmd_params_backtest(symbol, **kwargs):
    """Update backtest results for a product."""
    from gcc_evolution.params import ParamStore
    results = {k: v for k, v in kwargs.items() if v is not None}
    if "max_dd" in results:
        results["max_dd_pct"] = results.pop("max_dd")
    if not results:
        click.echo("  No values provided. Use --sharpe, --max-dd, --win-rate, etc."); return
    path = ParamStore.update_backtest(symbol, results)
    click.echo(f"  ✓ Updated {symbol} backtest: {results}")


@cmd_params.command("diff")
@click.argument("symbol")
def cmd_params_diff(symbol):
    """Show parameter changes vs defaults."""
    from gcc_evolution.params import ParamStore
    changes = ParamStore.diff(symbol)
    if not changes:
        click.echo(f"  {symbol}: all defaults"); return
    click.echo(f"\n  ✦ {symbol} parameter changes vs defaults")
    click.echo(f"  {'═'*50}")
    for c in changes:
        click.echo(f"  {c['section']}.{c['param']}: {c['old']} → {c['new']}")
    click.echo()


# ════════════════════════════════════════════════════════════
# Commit Command (v4.5 — auto-prefix with improvement ID)
# ════════════════════════════════════════════════════════════

@cli.command("commit")
@click.argument("message", required=False, default="")
@click.option("-k", "--key", default="", help="KEY (auto-detected from branch)")
@click.option("--amend", is_flag=True, help="Amend last commit")
def cmd_commit(message, key, amend):
    """Git commit with auto-prefixed improvement ID.

    Usage:
      gcc-evo commit "ATR改为自适应"
        → git commit -m "[GCC-0001:SPY-ATR] ATR改为自适应"

      gcc-evo commit                # prompts for message
      gcc-evo commit -k SPY-ATR     # override KEY
    """
    import subprocess

    # Auto-detect KEY from branch
    if not key:
        try:
            branch = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
            from gcc_evolution.handoff import HandoffProtocol
            key = HandoffProtocol._branch_to_key(branch)
        except Exception:
            pass

    # Find pipeline task for this KEY
    pipe_task_id = ""
    if key:
        try:
            from gcc_evolution.pipeline import TaskPipeline
            pipe = TaskPipeline()
            for t in pipe.tasks.values():
                if (t.key and t.key.upper() == key.upper()
                        and t.stage.value not in ("done", "failed")):
                    pipe_task_id = t.task_id
                    break
        except Exception:
            pass

    # Build prefix
    if pipe_task_id and key:
        prefix = f"[{pipe_task_id}:{key}]"
    elif key:
        prefix = f"[{key}]"
    else:
        prefix = ""

    # Get message
    if not message:
        message = click.prompt("  Commit message")

    full_msg = f"{prefix} {message}" if prefix else message

    # Execute git commit
    cmd = ["git", "commit"]
    if amend:
        cmd.append("--amend")
    cmd.extend(["-m", full_msg])

    click.echo(f"  → {full_msg}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        # Extract short hash
        hash_result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True,
        )
        short_hash = hash_result.stdout.strip() if hash_result.returncode == 0 else ""
        click.echo(f"  ✓ {short_hash} {prefix}")
        try:
            _db_auto_sync()
            click.echo("  OK Database synced")
        except Exception as e:
            click.echo(f"  - db sync skipped ({e})")
        _auto_export_dashboard()
    else:
        err = result.stderr.strip().split("\n")[0] if result.stderr else "commit failed"
        click.echo(f"  ✗ {err}")


# ════════════════════════════════════════════════════════════

def main():
    # Windows default cp1252 can crash on unicode CLI output (emoji/CJK).
    # Reconfigure streams to UTF-8 so commands like `gcc-evo ho create` are stable.
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    cli(standalone_mode=True)


# ── watch ──

@cli.command("watch")
@click.argument("action", type=click.Choice(["start", "stop", "status", "now", "log"]))
@click.option("--interval", "-i", default=5, show_default=True,
              help="Auto-commit interval in minutes")
def cmd_watch(action, interval):
    """Auto-commit daemon. Prevents progress loss on quota/crash."""
    from gcc_evolution.watchdog import WatchdogCLI
    WatchdogCLI.run(action, interval)


# ── skeptic ──

@cli.command("skeptic")
@click.argument("symbol")
@click.option("--key", "-k", default="", help="Improvement KEY context")
@click.option("--history", is_flag=True, help="Show verification history")
def cmd_skeptic(symbol, key, history):
    """Run Skeptic verification gate for a symbol after improvement."""
    from gcc_evolution.skeptic import cli_skeptic_cmd
    cli_skeptic_cmd(symbol.upper(), key.upper() if key else "", history)


# ════════════════════════════════════════════════════════════
# v4.85: Human Anchor Commands
# ════════════════════════════════════════════════════════════

@cli.group("anchor")
def cmd_anchor():
    """Human Anchor direction management (v4.85)."""
    pass


@cmd_anchor.command("status")
def anchor_status():
    """Show current Human Anchor status and confidence."""
    from gcc_evolution.human_anchor import HumanAnchorStore, format_anchor_status
    store = HumanAnchorStore()
    click.echo(format_anchor_status(store))


@cmd_anchor.command("calibrate")
@click.option("--direction", "-d", default="",
              help="LONG / SHORT / NEUTRAL")
@click.option("--key", "-k", default="", help="Improvement KEY")
@click.option("--constraint", "-c", multiple=True,
              help="Add constraint rule (can repeat)")
@click.option("--expires", default="5_trading_days",
              help="Expiry: 5_trading_days or 10_sessions")
@click.option("--concern", default="",
              help="Main concern / trigger (skip interactive prompt)")
def anchor_calibrate(direction, key, constraint, expires, concern):
    """Write a new Human Anchor after calibration."""
    from gcc_evolution.human_anchor import HumanAnchorStore

    click.echo("  ── Human Anchor Calibration ──")

    if not direction:
        direction = click.prompt(
            "  Market direction",
            type=click.Choice(["LONG", "SHORT", "NEUTRAL"], case_sensitive=False),
        ).upper()

    if not concern:
        concern = click.prompt("  Main concern / trigger (one sentence)")
    constraints = list(constraint)
    if not constraints:
        add_more = click.confirm("  Add constraints now?", default=False)
        while add_more:
            c = click.prompt("  Constraint rule")
            constraints.append(c)
            add_more = click.confirm("  Add another?", default=False)

    store = HumanAnchorStore()
    anchor = store.write_anchor(
        trigger=concern,
        direction=direction,
        constraints=constraints,
        main_concern=concern,
        key=key,
        expires_after=expires,
    )
    click.echo(f"\n  ✅ Anchor written: {anchor.anchor_id}")
    click.echo(f"  Direction: {anchor.direction}  |  Expires: {anchor.expires_after}")
    if constraints:
        click.echo(f"  Constraints ({len(constraints)}):")
        for c in constraints:
            click.echo(f"    → {c}")


@cmd_anchor.command("history")
def anchor_history():
    """Show all historical Human Anchors."""
    from gcc_evolution.human_anchor import HumanAnchorStore
    store = HumanAnchorStore()
    anchors = store.get_all()
    if not anchors:
        click.echo("  No Human Anchors found.")
        return
    click.echo(f"  Human Anchor History ({len(anchors)} total)")
    click.echo(f"  {'═' * 50}")
    for a in reversed(anchors[-10:]):
        valid = "✅" if a.is_valid() else "⚠️"
        click.echo(f"  {valid} [{a.anchor_id}]  {a.direction:8s}  {a.created_at[:10]}")
        click.echo(f"     {a.trigger}")


# ════════════════════════════════════════════════════════════
# v4.85: Ask (Natural Language Direction Injection)
# ════════════════════════════════════════════════════════════

@cli.command("ask")
@click.argument("question")
def cmd_ask(question):
    """
    自然语言指令入口，靠模型理解意图。

    示例：
      gcc-evo ask "帮我看下001"
      gcc-evo ask "今天偏空"
      gcc-evo ask "001做完了"
      gcc-evo ask "有什么建议"
      gcc-evo ask "继续上次的分析"
    """
    from gcc_evolution.human_anchor import NLQParser
    from gcc_evolution.orchestrator import Orchestrator
    from gcc_evolution.advisor import AnchorStore
    from gcc_evolution.suggest import SuggestStore

    # 收集当前系统状态，注入提示词
    state = _collect_system_state()

    # 尝试获取 LLM client
    llm = None
    try:
        from gcc_evolution.config import GCCConfig
        from gcc_evolution.llm_client import LLMClient
        cfg = GCCConfig.load()
        if cfg.llm_api_key:
            llm = LLMClient(cfg)
    except Exception as e:
        click.echo(f"  ⚠ LLM init failed: {e}", err=True)

    parser = NLQParser(llm_client=llm)
    result = parser.parse(question, state=state)

    method = result.get("method", "")
    confidence = result.get("confidence", 0)
    command = result.get("command")
    reply = result.get("reply", "")

    # 先输出模型的回复
    if reply:
        click.echo(f"\n  {reply}")

    if not command:
        # 不确定时列出候选
        candidates = result.get("candidates", [])
        if candidates:
            click.echo("\n  你是想：")
            for i, c in enumerate(candidates, 1):
                click.echo(f"    [{i}] gcc-evo {c}")
        return

    # 确认执行
    click.echo(f"  → gcc-evo {command}")
    if confidence < 0.6:
        if not click.confirm("  确认执行？", default=True):
            return

    # 执行对应命令
    _dispatch_command(command, result.get("args", {}))



@cli.command("opinion")
@click.argument("question")
@click.option("--key", "-k", default="", help="聚焦某个改善号，如 001")
@click.option("--depth", "-d", default="normal", help="simple / normal / deep")
def cmd_opinion(question, key, depth):
    """
    让模型基于当前数据给出自己的看法。

    示例：
      gcc-evo opinion "001值得继续投入吗"
      gcc-evo opinion "最近交易数据说明什么问题"
      gcc-evo opinion "今天该不该开新仓"
      gcc-evo opinion "哪个改善点最紧急" --depth deep
    """
    from gcc_evolution.config import GCCConfig
    from gcc_evolution.llm_client import LLMClient

    # 获取 LLM
    llm = None
    try:
        cfg = GCCConfig.load()
        if cfg.llm_api_key:
            llm = LLMClient(cfg)
    except Exception as e:
        click.echo(f"  ⚠ LLM init failed: {e}", err=True)

    if not llm:
        click.echo("  ⚠ 未配置 LLM，无法给出意见")
        click.echo("  请在 .gcc/evolution.yaml 中配置 llm_api_key")
        return

    # 收集数据
    key_id = _normalize_key(key) if key else ""
    context = _collect_opinion_context(key_id, depth)

    # 系统提示词
    system = """你是 GCC 进化引擎的分析顾问。
你能看到项目的完整数据：改善点状态、任务进展、交易数据、参数建议等。
你的职责是基于数据给出真实判断，不是泛泛而谈。

原则：
- 直接说结论，不要铺垫
- 有数据支撑时引用具体数字
- 不确定的地方直接说不确定
- 如果数据不够，说需要哪些数据才能判断
- 用中文回答，简洁有力，不超过200字
"""

    user = f"""当前系统数据：

{context}

问题：{question}

请给出你的看法。"""

    click.echo(f"\n  💬 正在分析...")
    try:
        reply = llm.generate(system=system, user=user, max_tokens=400)
        click.echo(f"\n  {reply.strip()}")
    except Exception as e:
        click.echo(f"  ⚠ 模型调用失败: {e}")


# ══════════════════════════════════════════════════════
# gcc-evo research   (自动研究迭代 workflow)
# ══════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════
# gcc-evo local  (本地 LLM 可选模块)
# ══════════════════════════════════════════════════════

@cli.group("local")
def cmd_local():
    """本地 LLM 管理（气隙/局域网环境，可选模块）。"""
    pass


@cmd_local.command("setup")
def local_setup():
    """检测硬件，推荐模型，生成配置（引导安装）。"""
    from gcc_evolution.local_llm import LocalLLMSetup, RECOMMENDED_MODELS

    click.echo("\n  ── GCC Local LLM 安装引导 ──\n")

    # 1. 检测硬件
    click.echo("  检测硬件配置...")
    hw = LocalLLMSetup.detect_hardware()
    click.echo(f"    OS:      {hw['os']} {hw['arch']}")
    click.echo(f"    RAM:     {hw['ram_gb']} GB")
    click.echo(f"    GPU:     {'是，VRAM ' + str(hw['gpu_vram_gb']) + 'GB' if hw['gpu'] else '无'}")

    # 2. 推荐模型
    rec = LocalLLMSetup.recommend_model(hw)
    click.echo(f"\n  推荐模型: {rec['model']}")
    click.echo(f"    出品:    {rec['vendor']}")
    click.echo(f"    说明:    {rec['note']}")

    # 3. 检查 Ollama
    click.echo("\n  检查 Ollama...")
    if LocalLLMSetup.check_ollama_installed():
        click.echo("  ✓ Ollama 已安装")
    else:
        click.echo("  ✗ Ollama 未安装")
        click.echo("    安装方式: https://ollama.com/download")
        click.echo("    macOS:    brew install ollama")
        click.echo("    Linux:    curl -fsSL https://ollama.com/install.sh | sh")
        click.echo("    Windows:  下载安装包")
        return

    # 4. 检查模型是否已下载
    from gcc_evolution.local_llm import LocalLLMClient
    client = LocalLLMClient(model=rec["model"])
    local_models = client.list_local_models()
    if rec["model"] in local_models:
        click.echo(f"  ✓ 模型 {rec['model']} 已下载")
    else:
        click.echo(f"  ! 模型 {rec['model']} 未下载")
        click.echo(f"    下载命令（需要联网，仅需一次）:")
        click.echo(f"    ollama pull {rec['model']}")

    # 5. 生成配置
    config_snippet = LocalLLMSetup.generate_config(rec["model"])
    click.echo(f"\n  .gcc/evolution.yaml 配置:")
    click.echo("  " + "─" * 40)
    for line in config_snippet.split("\n"):
        click.echo(f"  {line}")
    click.echo("  " + "─" * 40)

    click.echo("\n  配置完成后运行: gcc-evo local check")


@cmd_local.command("check")
def local_check():
    """检查本地 LLM 连接状态和任务能力。"""
    from gcc_evolution.local_llm import LocalLLMClient
    from gcc_evolution.config import GCCConfig

    try:
        cfg    = GCCConfig.load()
        model  = cfg.llm_model or "llama3.1:8b"
        url    = cfg.llm_api_base or "http://localhost:11434"
    except Exception:
        model, url = "llama3.1:8b", "http://localhost:11434"

    client = LocalLLMClient(model=model, base_url=url)

    click.echo(f"\n  本地 LLM 状态")
    click.echo(f"  模型:     {model}")
    click.echo(f"  地址:     {url}")

    # 健康检查
    healthy = client.is_healthy(cache_seconds=0)
    click.echo(f"  Ollama:   {'✓ 在线' if healthy else '✗ 离线（ollama serve 启动）'}")

    if not healthy:
        return

    # 列出本地模型
    models = client.list_local_models()
    click.echo(f"  已下载:   {', '.join(models) or '无'}")

    # 能力评估
    cap = client.capability_check()
    click.echo(f"\n  任务能力评估:")
    for task, result in cap["tasks"].items():
        icon = "✓" if result["supported"] else "△"
        click.echo(f"    {icon} {task:<20} {result['quality']}")

    click.echo(f"\n  建议: {cap['suggestion']}")


@cmd_local.command("models")
def local_models():
    """查看推荐模型列表。"""
    from gcc_evolution.local_llm import RECOMMENDED_MODELS, TASK_MODEL_MAP

    click.echo("\n  推荐模型（英文主场景 / 美国合规）:")
    click.echo(f"  {'场景':<20} {'模型':<20} {'内存':<8} {'GPU':<6} {'说明'}")
    click.echo(f"  {'─'*75}")
    for key, info in RECOMMENDED_MODELS.items():
        gpu_str = f"需要 {info.get('vram_gb',0)}GB" if info.get("gpu") else "不需要"
        click.echo(f"  {key:<20} {info['model']:<20} {str(info['ram_gb'])+'GB':<8} {gpu_str:<10} {info['note']}")

    click.echo(f"\n  GCC 任务最低模型要求:")
    for task, min_size in TASK_MODEL_MAP.items():
        click.echo(f"    {task:<20} {min_size}+")


@cmd_local.command("test")
@click.option("--prompt", "-p", default="What is 2+2?", help="测试提示词")
def local_test(prompt):
    """向本地模型发送测试请求。"""
    from gcc_evolution.local_llm import LocalLLMClient
    from gcc_evolution.config import GCCConfig

    try:
        cfg   = GCCConfig.load()
        model = cfg.llm_model or "llama3.1:8b"
        url   = cfg.llm_api_base or "http://localhost:11434"
    except Exception:
        model, url = "llama3.1:8b", "http://localhost:11434"

    client = LocalLLMClient(model=model, base_url=url)

    if not client.is_healthy(cache_seconds=0):
        click.echo("  ✗ Ollama 未运行，请先执行: ollama serve")
        return

    click.echo(f"  测试模型: {model}")
    click.echo(f"  提示词:   {prompt}")
    click.echo(f"  回答中...")
    try:
        resp = client.generate(system="You are a helpful assistant.", user=prompt, max_tokens=200)
        click.echo(f"\n  回答: {resp}")
    except Exception as e:
        click.echo(f"  ✗ 失败: {e}")


@cli.group("research")
def cmd_research():
    """自动研究迭代 workflow（论文/文档/URL → 蒸馏 → opinion）。"""
    pass


@cmd_research.command("inbox")
@click.option("--key", "-k", default="", help="关联改善号")
@click.option("--auto", is_flag=True, help="LLM 自动审核，跳过人工")
def research_inbox(key, auto):
    """扫描 research_inbox/ 目录，自动处理所有新文件。"""
    from gcc_evolution.research_workflow import ResearchWorkflow
    key_id = _normalize_key(key) if key else ""
    wf     = ResearchWorkflow(auto_approve=auto)
    click.echo("  扫描 research_inbox/ ...")
    results = wf.run_inbox(key_id=key_id)
    if not results:
        click.echo("  无新文件"); return
    for r in results:
        icon = {"success":"✓","skipped":"○","failed":"✗","pending_review":"⏳"}.get(r.status,"?")
        click.echo(f"  {icon} {Path(r.source).name}  [{r.status}]")
        if r.opinion:
            click.echo(f"    → {r.opinion}")
        if r.error and r.status != "success":
            click.echo(f"    ⚠ {r.error}")


@cmd_research.command("file")
@click.argument("path")
@click.option("--key", "-k", default="")
@click.option("--auto", is_flag=True)
def research_file(path, key, auto):
    """处理单个文件。

    示例：gcc-evo research file paper.pdf --key 001
    """
    from gcc_evolution.research_workflow import ResearchWorkflow
    key_id = _normalize_key(key) if key else ""
    wf     = ResearchWorkflow(auto_approve=auto)
    r      = wf.run_file(path, key_id=key_id)
    icon   = {"success":"✓","skipped":"○","failed":"✗","pending_review":"⏳"}.get(r.status,"?")
    click.echo(f"  {icon} {Path(path).name}  [{r.status}]")
    if r.draft_id:
        click.echo(f"    草稿: {r.draft_id}")
    if r.skill_count:
        click.echo(f"    蒸馏技能: {r.skill_count} 条")
    if r.opinion:
        click.echo(f"    💬 {r.opinion}")
    if r.error:
        click.echo(f"    ⚠ {r.error}")


@cmd_research.command("note")
@click.argument("text")
@click.option("--title", "-t", default="随手记")
@click.option("--key", "-k", default="")
def research_note(text, title, key):
    """随手记录想法，直接进知识库。

    示例：gcc-evo research note "高位量缩时不应追多" --key 001
    """
    from gcc_evolution.research_workflow import ResearchWorkflow
    key_id = _normalize_key(key) if key else ""
    wf     = ResearchWorkflow(auto_approve=True, min_quality=0.3)
    r      = wf.run_text(text, title=title, key_id=key_id)
    if r.status == "success":
        click.echo(f"  ✓ 已记录到知识库")
        if r.opinion:
            click.echo(f"  💬 {r.opinion}")
    else:
        click.echo(f"  ⚠ {r.error}")


@cmd_research.command("history")
@click.option("--limit", "-n", default=10, type=int)
def research_history(limit):
    """查看研究迭代历史。"""
    from gcc_evolution.research_workflow import ResearchWorkflow
    wf   = ResearchWorkflow()
    hist = wf.history(limit=limit)
    s    = wf.status_summary()
    click.echo(f"\n  研究迭代统计: 总{s['total']} 成功{s['success']} 待审核{s['pending_review']} 技能+{s['skills_added']}")
    click.echo(f"  {'─'*55}")
    for r in hist:
        icon = {"success":"✓","skipped":"○","failed":"✗","pending_review":"⏳"}.get(r.status,"?")
        src  = Path(r.source).name if "/" in r.source or "\\" in r.source else r.source[:40]
        click.echo(f"  {icon} {src[:40]:<40} {r.ran_at[:10]}")


@cmd_research.command("fetch")
@click.argument("topic")
@click.option("--key",    "-k", default="",     help="关联改善号，如 001")
@click.option("--domain", "-d", default="",     help="gcc|trading|chan_theory|industrial_ai|medical（留空自动推断）")
@click.option("--top-k",  "-n", default=5, type=int, help="拉取论文数量")
@click.option("--year",   "-y", default=2022, type=int, help="起始年份")
@click.option("--auto",   is_flag=True, help="跳过人工审核，自动写入知识库")
def research_fetch(topic, key, domain, top_k, year, auto):
    """从学术 API 自动拉取论文，走完 knowledge 全流程。

    \b
    示例：
      gcc-evo research fetch "agentic memory"
      gcc-evo research fetch "缠论趋势反转" --domain trading --key 012
      gcc-evo research fetch "welding defect detection" --domain industrial_ai --top-k 8
    """
    from gcc_evolution.paper_fetch import PaperFetch
    key_id = _normalize_key(key) if key else ""
    pf = PaperFetch(auto_approve=auto)
    click.echo(f"\n  🔍 拉取: \"{topic}\"  领域: {domain or '自动'}  数量: {top_k}")
    click.echo(f"  {'─'*55}")
    result = pf.fetch_and_import(
        topic=topic,
        key_id=key_id,
        domain=domain or None,
        top_k=top_k,
        year_from=year,
        auto_run_workflow=True,
    )
    click.echo(f"\n  ✅ 拉取 {result['fetched']} 篇")
    for r in result.get("results", []):
        icon = {"success": "✓", "skipped": "○", "failed": "✗", "pending_review": "⏳"}.get(r.status, "?")
        src  = Path(r.source).name if r.source else ""
        click.echo(f"  {icon} {src[:50]:<50} [{r.status}]")
        if r.opinion:
            click.echo(f"      💬 {r.opinion}")
        if r.error and r.status not in ("success", "pending_review"):
            click.echo(f"      ⚠  {r.error}")
    if not auto:
        click.echo(f"\n  ⏳ 草稿待审核: gcc-evo knowledge list")


@cmd_research.command("update")
@click.option("--md",   default="RESEARCH.md", help="RESEARCH.md 路径")
@click.option("--top-k", "-n", default=3, type=int, help="每个主题拉取数量")
@click.option("--auto", is_flag=True, help="自动审核写入")
def research_update(md, top_k, auto):
    """解析 RESEARCH.md，为每篇论文自动搜索最新相关进展。

    \b
    示例：
      gcc-evo research update
      gcc-evo research update --top-k 5 --auto
    """
    from gcc_evolution.paper_fetch import PaperFetch
    pf = PaperFetch(auto_approve=auto)
    click.echo(f"\n  📚 基于 {md} 更新论文库...")
    result = pf.update_from_research_md(research_md_path=md, top_k_per_topic=top_k)
    if "error" in result:
        click.echo(f"  ⚠  {result['error']}")
    else:
        click.echo(f"\n  ✅ 扫描 {result['topics']} 个主题，拉取 {result['fetched']} 篇，导入 {result['imported']} 篇")


# ══════════════════════════════════════════════════════
# gcc-evo datasource  (DuckDB 数据源管理)
# ══════════════════════════════════════════════════════

@cli.group("datasource")
def cmd_datasource():
    """DuckDB 数据源管理（注册/查询任意格式的数据文件）。"""
    pass


@cmd_datasource.command("add")
@click.argument("name")
@click.argument("path")
@click.option("--format", "fmt", default="jsonl", help="jsonl/parquet/csv/sqlite")
@click.option("--time-field", default="", help="时间字段名，用于时间段查询")
@click.option("--desc", default="")
def datasource_add(name, path, fmt, time_field, desc):
    """注册数据源。

    示例：
      gcc-evo datasource add events logs/server.log --format jsonl --time-field timestamp
      gcc-evo datasource add history data/*.parquet --format parquet
    """
    from gcc_evolution.duckdb_adapter import DuckDbAdapter
    da  = DuckDbAdapter()
    src = da.register_source(name, path, format=fmt,
                              time_field=time_field, description=desc)
    click.echo(f"  ✓ 数据源已注册: {name}")
    click.echo(f"    路径:   {path}")
    click.echo(f"    格式:   {fmt}")
    if time_field:
        click.echo(f"    时间字段: {time_field}")


@cmd_datasource.command("list")
def datasource_list():
    """查看所有已注册数据源。"""
    from gcc_evolution.duckdb_adapter import DuckDbAdapter
    da      = DuckDbAdapter()
    sources = da.list_sources()
    if not sources:
        click.echo("  无已注册数据源"); return
    click.echo(f"\n  {'名称':<15} {'格式':<8} {'说明'}")
    click.echo(f"  {'─'*55}")
    for s in sources:
        click.echo(f"  {s.name:<15} {s.format:<8} {s.path[:35]}")


@cmd_datasource.command("query")
@click.argument("sql")
@click.option("--limit", "-n", default=20, type=int)
def datasource_query(sql, limit):
    """执行 SQL 查询。

    示例：gcc-evo datasource query "SELECT * FROM events LIMIT 5"
    """
    from gcc_evolution.duckdb_adapter import DuckDbAdapter
    da     = DuckDbAdapter()
    result = da.query(sql)
    if result.error:
        click.echo(f"  ✗ {result.error}"); return
    click.echo(f"  {result.row_count} 行  ({result.duration_ms}ms)")
    for row in result.rows[:limit]:
        click.echo(f"  {row}")


@cmd_datasource.command("summary")
@click.argument("source_name")
@click.option("--hours", "-h", default=24, type=int)
@click.option("--group-by", "-g", default="")
def datasource_summary(source_name, hours, group_by):
    """时间段聚合统计。

    示例：gcc-evo datasource summary events --hours 12 --group-by source_id
    """
    from gcc_evolution.duckdb_adapter import DuckDbAdapter
    da     = DuckDbAdapter()
    result = da.period_summary(source_name, hours=hours, group_by=group_by)
    if result.error:
        click.echo(f"  ✗ {result.error}"); return
    click.echo(f"  过去 {hours}h，{source_name}:")
    for row in result.rows[:20]:
        click.echo(f"    {row}")


# ══════════════════════════════════════════════════════
# gcc-evo dashboard  (启动 Streamlit 看板)
# ══════════════════════════════════════════════════════

@cli.command("dashboard")
@click.option("--export", "-e", is_flag=True, default=False, help="只导出 HTML 文件，不打开浏览器")
@click.option("--out", "-o", default="", help="输出路径（默认 .gcc/dashboard.html）")
@click.option("--serve", "-s", is_flag=True, default=False, help="启动本地HTTP服务器（支持刷新按钮动态加载数据）")
@click.option("--port", "-p", default=8765, type=int, help="HTTP服务器端口（默认8765）")
def cmd_dashboard(export, out, serve, port):
    """打开 GCC 可视化看板（单文件 HTML，无需安装 Streamlit）。

    看板功能：
      · 改善台账：状态环 + 过滤 + 进度条 + 知识卡片数
      · 任务追踪：运行中 / 待开始 / 已完成 全览
      · 知识卡片：L1/L2/L3 层级展示
      · SkillBank：技能成功率排行
      · 待审建议：参数变更对比
      · 会话历史：handoff 时间线

    使用方式：
      gcc-evo dashboard            # 打开看板（浏览器）
      gcc-evo dashboard --export   # 只导出 HTML 文件
      gcc-evo dashboard --serve    # 启动HTTP服务器（支持动态刷新数据）
      gcc-evo dashboard -o /tmp/dash.html  # 导出到指定路径

    在看板中：
      1. 点「⚡ 演示数据」预览效果
      2. 点「↻ 刷新数据」动态加载最新 improvements.json（需 --serve 模式）
      3. 上传 .gcc/ 目录下的文件加载真实数据
         improvements.json / tasks.jsonl / skillbank.jsonl
         suggestions.jsonl / handoff.md
    """
    import shutil
    import webbrowser

    # 找内置 HTML — 按优先级搜索 (优先用项目根目录的最新模板)
    candidates = [
        Path("gcc_dashboard_v497.html"),                                   # 项目根目录最新版
        Path(__file__).parent / "gcc_evolution" / "gcc_dashboard.html",  # site-packages
        Path(__file__).parent / "gcc_dashboard.html",                     # 同级目录
        Path(".GCC") / "gcc_evolution" / "gcc_dashboard.html",            # 项目大写
        Path(".gcc") / "gcc_evolution" / "gcc_dashboard.html",            # 项目小写
    ]
    builtin_html = next((p for p in candidates if p.exists()), None)
    if not builtin_html:
        click.echo("  ✗ 找不到内置 dashboard.html", err=True)
        return

    # 输出路径 — 直接写入模板文件(gcc_evolution/gcc_dashboard.html)，打开即有数据
    if out:
        dest = Path(out)
    elif _gcc_dir().exists():
        dest = _gcc_dir() / "dashboard.html"
    else:
        dest = _gcc / "dashboard.html"
    dest.parent.mkdir(parents=True, exist_ok=True)

    # ── 尝试将 .gcc/ 数据内嵌到 HTML ──────────────────────
    html = builtin_html.read_text(encoding="utf-8")

    loaded = []
    import json as _json

    # 支持 .GCC 和 .gcc 两种大小写
    _gcc = _gcc_dir()

    all_tasks = []
    ho_sessions = []
    seen_tasks = set()

    def _norm_prio(p):
        return {'normal':'average','high':'high','low':'low'}.get((p or 'average').lower(), 'average')

    def _add_task(t):
        if not isinstance(t, dict): return
        k = t.get("task_id") or t.get("id") or t.get("title") or t.get("description") or str(id(t))
        if k in seen_tasks:
            # Pipeline数据更丰富时覆盖handoff版本(如有steps/stage/description)
            if t.get("steps") or t.get("stage") or (t.get("description") and t.get("source") == "pipeline"):
                all_tasks[:] = [x for x in all_tasks if x.get("task_id") != k]
            else:
                return
        seen_tasks.add(k)
        _out = {
            "task_id": t.get("task_id") or t.get("id", ""),
            "title": t.get("title") or t.get("description") or "未命名",
            "status": t.get("status", "pending"),
            "priority": _norm_prio(t.get("priority")),
            "key_id": t.get("key_id") or t.get("key") or t.get("anchor_key", ""),
            "updated_at": (t.get("updated_at") or t.get("created_at") or "")[:10],
            "current_step": (t.get("current_step") or t.get("instructions") or t.get("context") or "")[:200],
            "source": t.get("source", ""),
            "handoff_id": t.get("handoff_id", ""),
            "progress": t.get("progress", ""),
            "dependencies": t.get("dependencies", []),
        }
        # Pipeline-specific fields for detail rendering
        if t.get("stage"):
            _out["stage"] = t["stage"]
        if t.get("module"):
            _out["module"] = t["module"]
        if t.get("description") and t.get("title"):
            _out["description"] = t["description"][:300]
        if t.get("gate_results"):
            _out["gate_results"] = t["gate_results"]
        if t.get("steps"):
            _out["steps"] = t["steps"]
        all_tasks.append(_out)

    inject_lines = []

    # ① improvements — from file OR DB fallback
    # 优先 .GCC/improvements.json, 其次 state/improvements.json, 最后 gcc.db
    imp_path = _gcc / "improvements.json"
    if not imp_path.exists():
        _state_imp = Path("state") / "improvements.json"
        if _state_imp.exists():
            imp_path = _state_imp
    _imp_loaded = False
    if imp_path.exists():
        try:
            d = _json.loads(imp_path.read_text(encoding="utf-8", errors="ignore"))
            js = _json.dumps(d, ensure_ascii=False)
            inject_lines.append(
                f"try {{ const _d={js};"
                f"DATA.improvements=Array.isArray(_d)?_d:flattenImprovements(_d);"
                f"}} catch(e) {{}}"
            )
            loaded.append(imp_path.name)
            _imp_loaded = True
        except Exception as _e:
            click.echo(f"  ⚠ improvements.json load error: {_e}", err=True)

    # ①-b DB fallback for improvements (only if file not loaded)
    if not _imp_loaded:
        _db_path = _gcc / "gcc.db"
        if _db_path.exists():
            try:
                import sqlite3 as _sql
                _db = _sql.connect(str(_db_path))
                _db.row_factory = _sql.Row
                _imp_rows = [dict(r) for r in _db.execute(
                    "SELECT id, parent_key, title, status, phase_text, note, item_type FROM improvements"
                ).fetchall()]
                _db.close()
                if _imp_rows:
                    for r in _imp_rows:
                        r["status"] = (r.get("status") or "UNKNOWN").upper()
                        r.pop("observations_json", None)
                    js = _json.dumps(_imp_rows, ensure_ascii=False)
                    inject_lines.append(f"DATA.improvements = {js};")
                    loaded.append(f"gcc.db (improvements: {len(_imp_rows)})")
            except Exception:
                pass

    # ①-c Cards + Skills — ALWAYS load from gcc.db + skill/cards/ (independent of improvements)
    _cards_out = []
    _skills_out = []
    _db_path = _gcc / "gcc.db"
    if _db_path.exists():
        try:
            import sqlite3 as _sql
            _db = _sql.connect(str(_db_path))
            _db.row_factory = _sql.Row
            _card_rows = [dict(r) for r in _db.execute(
                "SELECT id, key_id, title, card_type, layer_priority FROM cards"
            ).fetchall()]
            _db.close()
            for c in _card_rows:
                _cards_out.append({
                    "key_id": c.get("key_id") or "",
                    "title": c.get("title") or "",
                    "card_type": c.get("card_type") or "knowledge",
                    "layer_priority": c.get("layer_priority") or 2,
                })
        except Exception:
            pass

    # Scan skill/cards/ directories for knowledge cards (supplemental)
    _skill_cards_dir = _gcc / "skill" / "cards"
    _card_dirs_seen = set()
    if _skill_cards_dir.exists():
        for _md_file in _skill_cards_dir.rglob("*.md"):
            _cat = _md_file.parent.name
            _card_id = f"sk_{_md_file.stem[:40]}"
            if _card_id not in _card_dirs_seen:
                _card_dirs_seen.add(_card_id)
                _cards_out.append({
                    "key_id": _cat,
                    "title": _md_file.stem.replace("_", " "),
                    "card_type": "knowledge",
                    "layer_priority": 2,
                })
        # Generate skill entries from card categories
        _cat_counts = {}
        for c in _cards_out:
            k = c.get("key_id") or "general"
            _cat_counts[k] = _cat_counts.get(k, 0) + 1
        _sk_idx = 1
        for _cat_name, _cnt in sorted(_cat_counts.items(), key=lambda x: -x[1])[:20]:
            _skills_out.append({
                "skill_id": f"SK-{_sk_idx:03d}",
                "name": _cat_name,
                "skill_type": "general",
                "success_rate": 0.75,
                "use_count": _cnt,
                "confidence": 0.8,
                "version": 1,
                "source": "knowledge_cards",
            })
            _sk_idx += 1

    if _cards_out:
        inject_lines.append(f"DATA.cards = {_json.dumps(_cards_out, ensure_ascii=False)};")
        loaded.append(f"cards: {len(_cards_out)}")
    if _skills_out:
        inject_lines.append(f"DATA.skills = {_json.dumps(_skills_out, ensure_ascii=False)};")
        loaded.append(f"skills: {len(_skills_out)}")

    # ①-d Skillbank from file (override generated skills if exists)
    _sb_path = _gcc / "skillbank.jsonl"
    if _sb_path.exists():
        _sb_rows = []
        for line in _sb_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip():
                try: _sb_rows.append(_json.loads(line))
                except Exception: pass
        if _sb_rows:
            inject_lines.append(f"DATA.skills = {_json.dumps(_sb_rows, ensure_ascii=False)};")
            loaded.append(f"skillbank.jsonl: {len(_sb_rows)}")

    # ② tasks.jsonl
    tasks_path = _gcc / "tasks.jsonl"
    if tasks_path.exists():
        for line in tasks_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip():
                try: _add_task(_json.loads(line))
                except Exception: pass
        loaded.append(tasks_path.name)

    # ③ handoffs/*.json
    # 过滤自动生成的机械化任务(config verify / docstring update / changelog / README)
    _HO_NOISE_PREFIXES = (
        "Verify config file",
        "Update module docstrings",
        "Add changelog entry",
        "Update README",
    )
    handoff_dir = _gcc / "handoffs"
    if handoff_dir.exists():
        ho_count = 0
        for ho_file in sorted(handoff_dir.glob("HO_*.json"), reverse=True)[:30]:
            try:
                d = _json.loads(ho_file.read_text(encoding="utf-8", errors="ignore"))
                for t in d.get("tasks", []):
                    if not isinstance(t, dict): continue
                    _t_title = t.get("title") or t.get("description") or ""
                    if any(_t_title.startswith(pfx) for pfx in _HO_NOISE_PREFIXES):
                        continue
                    t["key_id"] = d.get("key", "")
                    t["updated_at"] = (d.get("created_at") or "")[:10]
                    t["source"] = "handoff"
                    t["handoff_id"] = d.get("handoff_id", ho_file.stem)
                    _add_task(t)
                    ho_count += 1
                ho_sessions.append({
                    "handoff_id": d.get("handoff_id", ho_file.stem),
                    "created_at": d.get("created_at", ""),
                    "key": d.get("key", ""),
                    "project": d.get("project", ""),
                    "changes_summary": d.get("upstream", {}).get("changes_summary", ""),
                    "task_count": len(d.get("tasks", [])),
                    "done_count": sum(1 for t in d.get("tasks", []) if isinstance(t, dict) and t.get("status") in ("completed", "done")),
                })
            except Exception:
                pass
        if ho_count:
            loaded.append(f"handoffs/ ({ho_count} tasks)")

    # ④ pipeline/tasks.json
    pipe_path = _gcc / "pipeline/tasks.json"
    if pipe_path.exists():
        try:
            _pd = _json.loads(pipe_path.read_text(encoding="utf-8", errors="ignore"))
            if isinstance(_pd, list):
                _pt = _pd
            elif isinstance(_pd, dict) and "tasks" in _pd:
                _pt = _pd["tasks"]
            elif isinstance(_pd, dict):
                _pt = list(_pd.values())
            else:
                _pt = []
            _stage_map = {'done':'completed','closed':'completed',
                          'implement':'running','test':'running','testing':'running',
                          'integrate':'running','analyze':'running','design':'running',
                          'pending':'pending','suspended':'paused'}
            _pipe_count = 0
            for t in _pt:
                if isinstance(t, dict):
                    t.setdefault("source", "pipeline")
                    if "stage" in t and "status" not in t:
                        t["status"] = _stage_map.get(t["stage"], "pending")
                    _add_task(t)
                    _pipe_count += 1
            if _pipe_count: loaded.append(f"pipeline/tasks.json ({_pipe_count})")
        except Exception:
            pass

    # ⑤ inject tasks + sessions as plain JS objects
    if all_tasks:
        js = _json.dumps(all_tasks, ensure_ascii=False)
        inject_lines.append(f"DATA.tasks = {js};")

    if ho_sessions:
        js = _json.dumps(ho_sessions, ensure_ascii=False)
        inject_lines.append(f"DATA.sessions = {js};")

    # ⑥ suggestions (skillbank already handled in ①-c/①-d)
    _sug_path = _gcc / "suggestions.jsonl"
    if _sug_path.exists():
        _sug_rows = []
        for line in _sug_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip():
                try: _sug_rows.append(_json.loads(line))
                except Exception: pass
        if _sug_rows:
            inject_lines.append(f"DATA.suggestions = {_json.dumps(_sug_rows, ensure_ascii=False)};")
            loaded.append(f"suggestions.jsonl: {len(_sug_rows)}")

    # ⑦ GCC-0171: Vision Filter 准确率数据
    _vf_acc_path = Path("state") / "vision_filter_accuracy.json"
    if _vf_acc_path.exists():
        try:
            _vf_raw = _json.loads(_vf_acc_path.read_text(encoding="utf-8"))
            _vf_dash = {
                "last_review": _vf_raw.get("last_3day_review", 0),
                "pending_count": sum(1 for e in _vf_raw.get("events", []) if e.get("result") == "pending"),
                "total_events": len(_vf_raw.get("events", [])),
                "symbols": _vf_raw.get("accuracy", {}),
            }
            inject_lines.append(f"DATA.vf_accuracy = {_json.dumps(_vf_dash, ensure_ascii=False)};")
            loaded.append(f"vf_accuracy: {len(_vf_dash['symbols'])} symbols")
        except Exception:
            pass

    # ⑧ GCC-0172: BrooksVision 形态回测准确率
    _bv_acc_path = Path("state") / "bv_signal_accuracy.json"
    if _bv_acc_path.exists():
        try:
            _bv_raw = _json.loads(_bv_acc_path.read_text(encoding="utf-8"))
            inject_lines.append(f"DATA.bv_accuracy = {_json.dumps(_bv_raw, ensure_ascii=False)};")
            loaded.append(f"bv_accuracy: {_bv_raw.get('overall', {}).get('total', 0)} signals")
        except Exception:
            pass

    # ⑨ GCC-0173: MACD背离回测准确率
    _macd_acc_path = Path("state") / "macd_signal_accuracy.json"
    if _macd_acc_path.exists():
        try:
            _macd_raw = _json.loads(_macd_acc_path.read_text(encoding="utf-8"))
            inject_lines.append(f"DATA.macd_accuracy = {_json.dumps(_macd_raw, ensure_ascii=False)};")
            loaded.append(f"macd_accuracy: {_macd_raw.get('overall', {}).get('decisive', 0)} signals")
        except Exception as _e:
            loaded.append(f"macd_accuracy: load failed ({_e})")

    # ⑩ GCC-0174 S5f: 知识卡准确率
    _card_acc_path = Path("state") / "card_signal_accuracy.json"
    if _card_acc_path.exists():
        try:
            _card_raw = _json.loads(_card_acc_path.read_text(encoding="utf-8"))
            inject_lines.append(f"DATA.card_accuracy = {_json.dumps(_card_raw, ensure_ascii=False)};")
            loaded.append(f"card_accuracy: {_card_raw.get('overall', {}).get('decisive', 0)} signals")
        except Exception as _e:
            loaded.append(f"card_accuracy: load failed ({_e})")

    # ⑪ GCC-0197: 外挂信号准确率 (4H回填)
    _plugin_acc_path = Path("state") / "plugin_signal_accuracy.json"
    if _plugin_acc_path.exists():
        try:
            _plugin_raw = _json.loads(_plugin_acc_path.read_text(encoding="utf-8"))
            _plugin_acc = _plugin_raw.get("accuracy", {})
            inject_lines.append(f"DATA.plugin_accuracy = {_json.dumps(_plugin_acc, ensure_ascii=False)};")
            _pa_total = sum(v.get("_overall", {}).get("total", 0) for v in _plugin_acc.values())
            loaded.append(f"plugin_accuracy: {len(_plugin_acc)} sources, {_pa_total} decisive")
        except Exception as _e:
            loaded.append(f"plugin_accuracy: load failed ({_e})")

    # ⑫ GCC-0197 S3: 外挂Phase状态
    _plugin_phase_path = Path("state") / "plugin_phase_state.json"
    if _plugin_phase_path.exists():
        try:
            _phase_raw = _json.loads(_plugin_phase_path.read_text(encoding="utf-8"))
            inject_lines.append(f"DATA.plugin_phases = {_json.dumps(_phase_raw, ensure_ascii=False)};")
            _downgraded = sum(1 for v in _phase_raw.values() if v.get("phase") == "DOWNGRADED")
            loaded.append(f"plugin_phases: {len(_phase_raw)} plugins, {_downgraded} downgraded")
        except Exception as _e:
            loaded.append(f"plugin_phases: load failed ({_e})")

    # ⑬ GCC-0202: system_evo 进化评分 (来自 key009_audit.json)
    _audit_path = Path("state") / "key009_audit.json"
    if _audit_path.exists():
        try:
            _audit_raw = _json.loads(_audit_path.read_text(encoding="utf-8"))
            _sevo = _audit_raw.get("24h", {}).get("system_evo", {})
            if _sevo:
                # 精简字段：只注入 dashboard 展示所需
                _sevo_dash = {
                    "score": _sevo.get("score", 0),
                    "win_rate": _sevo.get("win_rate", 0),
                    "errors": _sevo.get("errors", 0),
                    "exec_eff": _sevo.get("exec_eff", 0),
                    "stability": _sevo.get("stability", 0),
                    "trend": _sevo.get("trend", "UNKNOWN"),
                    "collab_count": _sevo.get("collab_count", 0),
                }
                inject_lines.append(f"DATA.system_evo = {_json.dumps(_sevo_dash, ensure_ascii=False)};")
                loaded.append(f"system_evo: score={_sevo_dash['score']}, trend={_sevo_dash['trend']}")
        except Exception as _e:
            loaded.append(f"system_evo: load failed ({_e})")

    # inject BEFORE // INIT so render() sees the data
    if inject_lines:
        inject_js = "\n".join(inject_lines) + "\n"
        if "// INIT\n" in html:
            html = html.replace("// INIT\n", inject_js + "render();\n// INIT\n")
        else:
            html = html.replace(
                "document.getElementById('lastUpdated').textContent = new Date().toLocaleString('zh-CN');",
                inject_js + "render();\ndocument.getElementById('lastUpdated').textContent = new Date().toLocaleString('zh-CN');"
            )

    # GCC-0149: 增量导出 — 数据未变时跳过写入
    import hashlib
    _new_hash = hashlib.md5(html.encode("utf-8")).hexdigest()
    _skip_write = False
    if dest.exists():
        _old_hash = hashlib.md5(dest.read_bytes()).hexdigest()
        if _old_hash == _new_hash:
            _skip_write = True

    if _skip_write:
        click.echo(f"  ✓ 看板数据未变，跳过写入: {dest}")
    else:
        dest.write_text(html, encoding="utf-8")
        if loaded:
            click.echo(f"  ✓ 已内嵌数据: {', '.join(loaded)}")
        else:
            click.echo(f"  ℹ  未找到 .gcc/ 数据文件，看板将使用手动上传模式")
        click.echo(f"  ✓ 看板已生成: {dest}")

    if serve:
        # --serve: 启动本地HTTP服务器，支持刷新按钮fetch动态加载数据
        import http.server
        import functools
        import threading

        # GCC-0149: serve模式 — 每次请求dashboard时重新导出
        serve_dir = Path(".").resolve()
        _dash_rel = dest.resolve().relative_to(serve_dir).as_posix()

        class _LiveDashHandler(http.server.SimpleHTTPRequestHandler):
            """请求dashboard.html时先重新导出，确保数据最新"""
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(serve_dir), **kwargs)
            def do_GET(self):
                # 匹配dashboard路径时触发重新导出
                req_path = self.path.lstrip("/").split("?")[0]
                if req_path == _dash_rel:
                    try:
                        from click.testing import CliRunner
                        CliRunner().invoke(cmd_dashboard, ["--export"])
                    except Exception:
                        pass
                super().do_GET()
            def log_message(self, format, *args):
                pass  # 静默HTTP日志

        click.echo(f"  → 启动本地HTTP服务器: http://localhost:{port}")
        click.echo(f"  → 根目录: {serve_dir}")
        click.echo(f"  → 每次刷新浏览器自动重新导出最新数据")
        click.echo(f"  → 按 Ctrl+C 停止服务器")

        # 打开浏览器(指向HTTP地址)
        url = f"http://localhost:{port}/{_dash_rel}"
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

        with http.server.HTTPServer(("", port), _LiveDashHandler) as httpd:
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                click.echo("\n  ✓ 服务器已停止")
    elif not export:
        click.echo(f"  → 正在用浏览器打开...")
        click.echo(f"  → 提示: 使用 gcc-evo dashboard --serve 可启用刷新按钮动态加载数据")
        webbrowser.open(dest.resolve().as_uri())
    else:
        click.echo(f"  → 用浏览器打开此文件查看看板")


# ══════════════════════════════════════════════════════
# gcc-evo init  (初始化项目，生成 agents.md)
# ══════════════════════════════════════════════════════

@cli.command("init")
@click.option("--name", "-n", default="", help="项目名称")
def cmd_init(name):
    """初始化 GCC 项目结构，生成 agents.md 模板。"""
    import shutil
    from gcc_evolution import __file__ as pkg_file

    # 创建 .gcc 目录结构
    dirs = [
        ".gcc", ".gcc/knowledge_drafts", ".gcc/snapshots", ".gcc/analysis"
    ]
    for d in dirs:
        Path(d).mkdir(parents=True, exist_ok=True)

    # 生成 agents.md（如果不存在）
    agents_md = Path("agents.md")
    if not agents_md.exists():
        # 从包里复制模板
        template = Path(pkg_file).parent.parent / "agents.md"
        if template.exists():
            shutil.copy(template, agents_md)
        else:
            agents_md.write_text(
                f"# agents.md\n> 项目: {name or 'My GCC Project'}\n\n"
                "## 当前聚焦\n[KEY-001]\n\n## 重要约束\n- [约束]\n",
                encoding="utf-8"
            )
        click.echo("  ✓ agents.md 已生成")

    # 创建 research_inbox
    Path("research_inbox").mkdir(exist_ok=True)

    click.echo("  ✓ .gcc/ 目录结构已创建")
    click.echo("  ✓ research_inbox/ 已创建")
    click.echo("\n  下一步:")
    click.echo("    1. 编辑 agents.md，填入项目信息")
    click.echo("    2. 配置 .gcc/evolution.yaml（LLM API Key）")
    click.echo("    3. gcc-evo db sync")


@cli.group("bt")
def cmd_bt():
    """Backtest store — record, query, analyze (v4.85)."""
    pass


@cmd_bt.command("record")
@click.option("--symbol", "-s", required=True, help="Symbol e.g. SPY")
@click.option("--signal", required=True,
              type=click.Choice(["BUY", "SELL", "HOLD"]))
@click.option("--position", "-p",
              type=click.Choice(["LOW", "MID", "HIGH", "UNKNOWN"]),
              default="MID")
@click.option("--pnl", default=0.0, help="PnL percentage e.g. -1.8")
@click.option("--executed/--no-executed", default=True)
@click.option("--anchor", default="", help="Human Anchor ID to link")
def bt_record(symbol, signal, position, pnl, executed, anchor):
    """Record a trade event into backtest store."""
    from gcc_evolution.backtest_store import BacktestStore, TradeEvent
    store = BacktestStore()
    event = TradeEvent(
        symbol=symbol.upper(),
        signal=signal,
        price_position=position,
        pnl_pct=pnl / 100 if abs(pnl) > 1 else pnl,
        executed=executed,
        anchor_id=anchor,
    )
    event = store.record(event)
    click.echo(f"  ✅ Recorded: {event.event_id}")
    click.echo(f"  {symbol} {signal} @ {position}  PnL={event.pnl_pct:+.1%}")


@cmd_bt.command("stats")
@click.option("--position", "-p", default="", help="Filter by position: LOW/MID/HIGH")
@click.option("--signal", "-s", default="", help="Filter by signal: BUY/SELL/HOLD")
@click.option("--days", "-d", default=30, show_default=True)
def bt_stats(position, signal, days):
    """Show pattern statistics from backtest store."""
    from gcc_evolution.backtest_store import BacktestStore
    store = BacktestStore()
    pattern = {}
    if position:
        pattern["position"] = position.upper()
    if signal:
        pattern["signal"] = signal.upper()
    if not pattern:
        total = store.get_total_count(days=days)
        click.echo(f"  Total events in last {days} days: {total}")
        return
    stats = store.pattern_stats(pattern, days=days)
    click.echo(f"\n  {stats.format()}")


@cmd_bt.command("drawdown")
@click.option("--days", "-d", default=14, show_default=True)
def bt_drawdown(days):
    """Show drawdown attribution report."""
    from gcc_evolution.backtest_store import BacktestStore, DrawdownAnalyzer
    store = BacktestStore()
    da = DrawdownAnalyzer(store)
    click.echo(da.generate_report(period_days=days))


@cmd_bt.command("counterfactual")
@click.option("--position", "-p", default="", help="Position filter: LOW/MID/HIGH")
@click.option("--signal", "-s", default="", help="Signal filter: BUY/SELL")
@click.option("--action", "-a", default="HOLD",
              type=click.Choice(["HOLD", "REVERSE"]))
@click.option("--days", "-d", default=30, show_default=True)
def bt_counterfactual(position, signal, action, days):
    """Run counterfactual: what if this rule existed historically?"""
    from gcc_evolution.backtest_store import BacktestStore, CounterfactualEngine
    rule = {}
    if position:
        rule["position"] = position.upper()
    if signal:
        rule["signal"] = signal.upper()
    rule["action"] = action
    if len(rule) < 2:
        click.echo("  Provide at least --position or --signal")
        return
    store = BacktestStore()
    engine = CounterfactualEngine(store)
    result = engine.run(rule=rule, lookback_days=days)
    click.echo(f"\n  {result.format()}")


# ── update ──────────────────────────────────────────────────

@cli.command("update")
@click.option("--source", "-s", default="", help="新版 tar 包路径或解压目录（留空自动查找）")
@click.option("--dry-run", is_flag=True, help="只显示会覆盖哪些位置，不实际执行")
def cmd_update(source, dry_run):
    """一键更新 GCC —— 自动覆盖所有位置。

    自动检测并更新三个位置：
      1. ~/.claude/skills/gcc-context/   Claude Code 引擎
      2. 当前项目 .GCC/ 或 .gcc/         项目内引擎文件
      3. pip site-packages                gcc-evo 终端命令

    示例：
      gcc-evo update                          # 自动查找新版，全量更新
      gcc-evo update --source ~/Desktop/gcc_v4_92.tar.gz
      gcc-evo update --source ~/Desktop/gcc_v4_85/
      gcc-evo update --dry-run                # 预览更新位置
    """
    import subprocess
    import shutil
    import tarfile
    import tempfile
    from pathlib import Path

    click.echo("\n  GCC 一键更新")
    click.echo("  " + "─" * 45)

    # ══ Step 0: 找新版源目录 ══════════════════════════════

    src_dir = None

    if source:
        src_path = Path(source).expanduser()
        # 如果是 tar 包，先解压
        if src_path.suffix in (".gz", ".tar") or str(src_path).endswith(".tar.gz"):
            click.echo(f"  解压 {src_path.name} ...")
            tmp = Path(tempfile.mkdtemp())
            with tarfile.open(src_path, "r:gz") as tf:
                tf.extractall(tmp)
            # 找解压后的子目录（通常是 gcc_v4_xx）
            subdirs = [d for d in tmp.iterdir() if d.is_dir()]
            src_dir = subdirs[0] if subdirs else tmp
        else:
            src_dir = src_path
    else:
        # 自动查找：skills 目录本身就是源
        candidates = [
            Path.home() / ".claude" / "skills" / "gcc-context",
        ]
        src_dir = next((p for p in candidates if (p / "pyproject.toml").exists()), None)

    if not src_dir or not (src_dir / "pyproject.toml").exists():
        click.echo("  ✗ 找不到新版源目录")
        click.echo("    请指定 tar 包或解压目录：")
        click.echo("    gcc-evo update --source ~/Desktop/gcc_v4_92.tar.gz")
        return

    click.echo(f"  新版来源: {src_dir}")

    # ══ Step 1: 检测所有需要更新的位置 ══════════════════════

    targets = []

    # 位置 A：~/.claude/skills/gcc-context/
    claude_skills = Path.home() / ".claude" / "skills" / "gcc-context"
    if claude_skills.exists() and claude_skills != src_dir:
        targets.append(("Claude Code 引擎", claude_skills))

    # 位置 B：当前项目的 .GCC/ 或 .gcc/
    # 判断条件：目录存在即覆盖（不要求 gcc_evo.py 必须存在）
    found_project = False
    for name in [".GCC", ".gcc"]:
        p = Path.cwd() / name
        if p.exists() and p.is_dir():
            targets.append((f"项目引擎 ({name}/)", p))
            found_project = True
            break

    # 向上查找项目目录（最多4层），找到第一个就停
    if not found_project:
        cur = Path.cwd()
        for _ in range(4):
            cur = cur.parent
            if cur == cur.parent:  # 到根目录了
                break
            for name in [".GCC", ".gcc"]:
                p = cur / name
                if p.exists() and p.is_dir():
                    targets.append((f"项目引擎 ({cur.name}/{name}/)", p))
                    found_project = True
                    break
            if found_project:
                break

    # 去重
    seen = set()
    unique_targets = []
    for label, path in targets:
        key = str(path.resolve())
        if key not in seen:
            seen.add(key)
            unique_targets.append((label, path))
    targets = unique_targets

    # ══ 显示将要覆盖的位置，确认后执行 ══════════════════════

    click.echo(f"\n  将更新以下 {len(targets)} 个位置：")
    for label, path in targets:
        click.echo(f"    ▸ {label}")
        click.echo(f"      {path}")
    click.echo(f"    ▸ pip 包（gcc-evo 终端命令）")

    if not targets:
        click.echo("\n  ⚠ 没有找到需要更新的位置")
        click.echo("  请在项目目录下运行，或用 --source 指定新版路径")
        return

    click.echo("")
    confirm = click.prompt("  确认更新？(y/n)", default="y")
    if confirm.lower() not in ("y", "yes", "是"):
        click.echo("  已取消")
        return

    click.echo("")

    # ══ Step 2: 全量覆盖所有目标位置 ═══════════════════════

    errors = []
    for label, dst in targets:
        click.echo(f"  覆盖 {label} ...", nl=False)
        try:
            # 全量复制：src_dir/* → dst/，跳过 .git 等特殊目录
            SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "build", "dist", "*.egg-info"}
            for item in src_dir.iterdir():
                # 跳过不应覆盖的目录
                if item.name in SKIP_DIRS or item.name.endswith(".egg-info"):
                    continue
                s = src_dir / item.name
                d = dst / item.name
                if s.is_dir():
                    if d.exists():
                        shutil.rmtree(d)
                    shutil.copytree(s, d,
                        ignore=shutil.ignore_patterns(".git","__pycache__","*.pyc","build","dist"))
                else:
                    shutil.copy2(s, d)
            click.echo(" ✓")
        except Exception as e:
            click.echo(f" ✗ {e}")
            errors.append((label, str(e)))

    # ══ Step 3: 重新安装 pip 包 ═══════════════════════════

    click.echo(f"  重新安装 pip 包 ...", nl=False)
    result = subprocess.run(
        ["pip", "install", str(src_dir), "--force-reinstall", "--quiet"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        click.echo(" ✓")
    else:
        # 尝试加 --break-system-packages
        result2 = subprocess.run(
            ["pip", "install", str(src_dir), "--force-reinstall",
             "--quiet", "--break-system-packages"],
            capture_output=True, text=True
        )
        if result2.returncode == 0:
            click.echo(" ✓")
        else:
            click.echo(f" ✗\n    {result.stderr[:200]}")
            errors.append(("pip install", result.stderr[:200]))

    # ══ 结果 ════════════════════════════════════════════════

    click.echo("")
    if errors:
        click.echo(f"  ⚠ 完成（{len(errors)} 个错误）：")
        for label, msg in errors:
            click.echo(f"    ✗ {label}: {msg}")
    else:
        try:
            # 重新导入获取新版本号
            import importlib
            import gcc_evolution
            importlib.reload(gcc_evolution)
            ver = gcc_evolution.__version__
        except Exception:
            ver = "unknown"
        click.echo(f"  ✓ 更新完成  GCC v{ver}")
        click.echo(f"  ✓ 更新了 {len(targets)} 个位置 + pip 包")
        click.echo("")
        click.echo("  建议重启 Claude Code 使新版生效")



# ══════════════════════════════════════════════════════
# gcc-evo analyze
# ══════════════════════════════════════════════════════

@cli.group("analyze")
def cmd_analyze():
    """定期分析执行记录，生成改善建议。"""
    pass


@cmd_analyze.command("run")
@click.option("--period", "-p", default="24h", help="分析周期: 12h / 24h / 7d / 30d")
@click.option("--key", "-k", default="", help="只分析指定 KEY")
@click.option("--no-llm", is_flag=True, help="跳过 LLM，只用规则引擎")
def analyze_run(period, key, no_llm):
    """运行回溯分析，生成参数建议。

    统计 trade_events → 识别异常模式 → LLM 生成建议 → 写入 suggest store。

    示例：
      gcc-evo analyze run
      gcc-evo analyze run --period 7d
      gcc-evo analyze run --key 001 --period 12h
    """
    from gcc_evolution.analyzer import Analyzer

    # 获取 LLM client
    llm = None
    if not no_llm:
        try:
            from gcc_evolution.config import GCCConfig
            from gcc_evolution.llm_client import LLMClient
            cfg = GCCConfig.load()
            if cfg.llm_api_key or cfg.llm_provider == "local":
                llm = LLMClient(cfg)
        except Exception as e:
            click.echo(f"  ⚠ LLM init failed: {e}", err=True)

    key_id = _normalize_key(key) if key else ""
    analyzer = Analyzer(llm_client=llm)

    click.echo(f"\n  分析中... 周期: {period}" + (f"  KEY: {key_id}" if key_id else ""))

    try:
        result = analyzer.run(period=period, key_id=key_id)
    except ValueError as e:
        click.echo(f"  ✗ {e}"); return

    if result.total_events == 0:
        click.echo(f"  ⚠ {result.since[:16]} 后无数据")
        click.echo("    数据来源：trade_events 表")
        click.echo("    确认交易系统是否在写入数据：gcc-evo datasource list")
        return

    # 输出统计
    click.echo(f"  总信号: {result.total_events}")
    for s in result.symbols:
        click.echo(f"    {s.symbol:<10} 总{s.total:>4}  执行{s.exec_rate:>5.0%}  过滤{s.filter_rate:>5.0%}")

    # 输出模式
    if result.patterns:
        click.echo(f"\n  发现异常模式 {len(result.patterns)} 个:")
        for p in result.patterns:
            click.echo(f"    ⚠ {p['desc']}")

    # 输出建议
    if result.suggestions:
        click.echo(f"\n  产生建议 {len(result.suggestions)} 条（已写入）")
        for s in result.suggestions:
            icon = {"high": "🔴", "normal": "🟡", "low": "⚪"}.get(s.get("priority", "normal"), "🟡")
            click.echo(f"    {icon} {s.get('subject', '')}")
        click.echo(f"\n  审核建议: gcc-evo suggest review")
    else:
        click.echo("\n  ✓ 数据正常，无异常模式")

    if hasattr(result, "_report_path"):
        click.echo(f"  报告: {result._report_path}")


@cmd_analyze.command("batch")
@click.option("--period", "-p", default="7d", help="分析周期: 24h / 7d / 30d")
@click.option("--no-llm", is_flag=True, help="跳过 LLM，只用规则引擎")
def analyze_batch(period, no_llm):
    """GCC-0155/S75: 批量分析所有KEY，结果注入RuleRegistry。

    自动遍历 improvements.json 中所有活跃KEY，
    逐个运行analyze → 提取规则 → 注入RuleRegistry。

    示例：
      gcc-evo analyze batch
      gcc-evo analyze batch --period 30d
    """
    import json as _json
    from gcc_evolution.analyzer import Analyzer
    from gcc_evolution.retrospective import RetrospectiveAnalyzer
    from gcc_evolution.rule_registry import RuleRegistry

    # 获取 LLM client
    llm = None
    if not no_llm:
        try:
            from gcc_evolution.config import GCCConfig
            from gcc_evolution.llm_client import LLMClient
            cfg = GCCConfig.load()
            if cfg.llm_api_key or cfg.llm_provider == "local":
                llm = LLMClient(cfg)
        except Exception as e:
            click.echo(f"  ⚠ LLM init failed: {e}", err=True)

    # 收集活跃KEY
    keys = []
    for imp_path in ["state/improvements.json", ".GCC/state/improvements.json"]:
        p = Path(imp_path)
        if p.exists():
            try:
                imp = _json.loads(p.read_text("utf-8"))
                for k in imp.get("keys", []):
                    kid = k.get("key_id", "")
                    status = k.get("status", "")
                    if kid and status not in ("CLOSED", "DEFERRED"):
                        keys.append(kid)
            except Exception:
                pass
            break

    if not keys:
        click.echo("  ⚠ 未找到活跃KEY (检查 state/improvements.json)")
        return

    click.echo(f"\n  📊 批量分析 — {len(keys)} 个KEY × {period}")
    click.echo(f"  {'─' * 50}")

    analyzer = Analyzer(llm_client=llm)
    registry = RuleRegistry()
    total_rules = 0

    for key_id in keys:
        try:
            result = analyzer.run(period=period, key_id=key_id)
        except Exception as e:
            click.echo(f"  ✗ {key_id}: {e}")
            continue

        if result.total_events == 0:
            click.echo(f"  · {key_id}: 无数据")
            continue

        click.echo(f"  ✓ {key_id}: {result.total_events} 信号, "
                    f"{len(result.patterns)} 异常, {len(result.suggestions)} 建议")

        # 尝试运行Retrospective并注入RuleRegistry
        try:
            retro = RetrospectiveAnalyzer(llm_client=llm)
            report = retro.run(key=key_id, period=period)
            if report:
                report_json = report.to_json()
                new_ids = registry.ingest_from_retrospective(report_json)
                if new_ids:
                    total_rules += len(new_ids)
                    click.echo(f"    → {len(new_ids)} 新规则注入RuleRegistry")
        except Exception as e:
            click.echo(f"    ⚠ Retrospective: {e}")

    # 运行衰减检查
    retired = registry.check_decay()

    click.echo(f"\n  {'─' * 50}")
    summary = registry.summary()
    click.echo(f"  📋 RuleRegistry: {summary['total']} 规则")
    for s, c in summary.get("by_status", {}).items():
        click.echo(f"    {s}: {c}")
    if total_rules:
        click.echo(f"  ✚ 本次新增: {total_rules}")
    if retired:
        click.echo(f"  ⚠ 衰减退役: {len(retired)}")
    click.echo("")


# ══════════════════════════════════════════════════════
# gcc-evo knowledge
# ══════════════════════════════════════════════════════

@cli.group("knowledge")
def cmd_knowledge():
    """外部知识导入与管理。"""
    pass


@cmd_knowledge.command("import")
@click.argument("source")
@click.option("--title", "-t", default="", help="标题")
@click.option("--key", "-k", default="", help="关联 KEY")
def knowledge_import(source, title, key):
    """导入外部知识（文件路径）。"""
    from gcc_evolution.knowledge import KnowledgeImporter
    from pathlib import Path

    imp = KnowledgeImporter()
    path = Path(source)

    if path.exists():
        ks = imp.import_file(path)
        click.echo(f"  导入: {ks.source_id}  [{ks.source_type}] {ks.title}")
    else:
        t = title or source[:30]
        ks = imp.import_text(source, t)
        click.echo(f"  导入文本: {ks.source_id}")

    draft = imp.generate_draft(ks, existing_keys=[key] if key else [])
    imp.save_draft(draft)
    click.echo(f"  草稿已生成: {draft.draft_id}")
    click.echo(f"  运行 gcc-evo knowledge review {draft.draft_id} 审核")


@cmd_knowledge.command("pdf")
@click.argument("pdf_path")
@click.option("--key", "-k", default="", help="关联 KEY")
@click.option("--no-llm", is_flag=True, help="跳过LLM，只用规则提取")
def knowledge_pdf(pdf_path, key, no_llm):
    """GCC-0155/S77: PDF→知识卡一站式管道。

    PDF读取(pdfplumber/PyMuPDF) → OCR回退(扫描PDF) →
    文本提取 → LLM知识卡提取 → 保存草稿。

    示例：
      gcc-evo knowledge pdf paper.pdf
      gcc-evo knowledge pdf paper.pdf --key KEY-007
    """
    from gcc_evolution.knowledge import KnowledgeImporter
    from pathlib import Path

    path = Path(pdf_path)
    if not path.exists():
        click.echo(f"  ✗ 文件不存在: {pdf_path}"); return

    imp = KnowledgeImporter()

    # 获取LLM
    llm = None
    if not no_llm:
        try:
            from gcc_evolution.config import GCCConfig
            from gcc_evolution.llm_client import LLMClient
            cfg = GCCConfig.load()
            if cfg.llm_api_key or cfg.llm_provider == "local":
                llm = LLMClient(cfg)
        except Exception as e:
            click.echo(f"  ⚠ LLM init failed: {e}, using rule-based extraction")

    key_id = _normalize_key(key) if key else ""
    click.echo(f"  📄 Processing: {path.name}")

    draft = imp.pdf_to_knowledge_card(path, key=key_id, llm_client=llm)
    if draft:
        imp.save_draft(draft)
        click.echo(f"  ✓ 知识卡草稿: {draft.draft_id}")
        click.echo(f"    标题: {draft.title}")
        click.echo(f"    要点: {len(draft.key_points)} 条")
        click.echo(f"    建议KEY: {draft.suggested_key}")
        click.echo(f"  → 审核: gcc-evo knowledge review {draft.draft_id}")
    else:
        click.echo("  ✗ PDF处理失败（内容太少或格式不支持）")


@cmd_knowledge.command("list")
def knowledge_list():
    """列出待审核知识草稿。"""
    from gcc_evolution.knowledge import KnowledgeImporter
    imp = KnowledgeImporter()
    drafts = imp.list_drafts()
    if not drafts:
        click.echo("  无待审核草稿"); return
    click.echo(f"\n  待审核草稿 ({len(drafts)} 条):")
    for d in drafts:
        click.echo(f"  {d.draft_id}  {d.title}  → {d.suggested_key}")


@cmd_knowledge.command("review")
@click.argument("draft_id")
def knowledge_review(draft_id):
    """审核知识草稿。"""
    from gcc_evolution.knowledge import KnowledgeImporter
    imp = KnowledgeImporter()
    draft = imp._load_draft(draft_id)
    if not draft:
        click.echo(f"  草稿 {draft_id} 不存在"); return

    click.echo(f"\n  标题: {draft.title}")
    click.echo(f"  建议关联: {draft.suggested_key}")
    click.echo(f"\n  核心要点:")
    for p in draft.key_points:
        click.echo(f"    - {p}")

    action = click.prompt("\n  操作 [a=应用 / r=拒绝 / s=跳过]", default="s")
    if action == "a":
        note = click.prompt("  备注", default="")
        path = imp.approve_draft(draft_id, note)
        click.echo(f"  ✓ 已写入知识卡: {path}")
        click.echo("  运行 gcc-evo db import --cards 同步到数据库")
    elif action == "r":
        note = click.prompt("  拒绝原因", default="")
        imp.reject_draft(draft_id, note)
        click.echo("  已拒绝")
    else:
        click.echo("  已跳过")


@cmd_knowledge.command("ocr-pdf")
@click.argument("pdf_path")
@click.argument("output_dir", required=False)
@click.option("--skip-db", is_flag=True, help="跳过 DuckDB 入库")
@click.option("--db", default="knowledge.duckdb", show_default=True, help="DuckDB 文件路径")
@click.option("--min-text-chars", default=100, show_default=True, help="直接文本抽取最小字符数")
def knowledge_ocr_pdf(pdf_path, output_dir, skip_db, db, min_text_chars):
    """Windows 友好的 PDF OCR：PDF -> page_*.md / page_*.json / DuckDB。"""
    import subprocess
    import sys
    from pathlib import Path

    script = Path(__file__).resolve().parent.parent / "opensource" / "ocr_pdf.py"
    pdf = Path(pdf_path)
    out = Path(output_dir) if output_dir else Path("output_md")
    if not pdf.exists():
        click.echo(f"  ✗ 文件不存在: {pdf_path}")
        return
    cmd = [
        sys.executable, str(script), str(pdf), str(out),
        "--db", str(db), "--min-text-chars", str(min_text_chars),
    ]
    if skip_db:
        cmd.append("--skip-db")
    proc = subprocess.run(cmd, text=True, check=False)
    raise SystemExit(proc.returncode)


@cmd_knowledge.command("cards")
@click.argument("work_dir")
@click.option("--book", default="", help="来源书籍/课程名")
@click.option("--chapter", default="", help="章节名")
@click.option("--module", default="KnowledgeExtractor", show_default=True, help="system_mapping.module")
@click.option("--overwrite", is_flag=True, help="覆盖已有 page_*.json")
@click.option("--refine", is_flag=True, help="对现有 json 执行 refine")
@click.option("--llm-refine", is_flag=True, help="用已配置 LLM 精修卡片字段")
@click.option("--llm-repeat", default=1, show_default=True, help="LLM 调用次数")
def knowledge_cards(work_dir, book, chapter, module, overwrite, refine, llm_refine, llm_repeat):
    """page_*.md -> 专业知识卡 JSON。"""
    import subprocess
    import sys
    from pathlib import Path

    script = Path(__file__).resolve().parent.parent / "opensource" / "pdf_to_cards_v3.py"
    wd = Path(work_dir)
    if not wd.exists():
        click.echo(f"  ✗ 目录不存在: {work_dir}")
        return
    cmd = [sys.executable, str(script), str(wd), "--book", book, "--chapter", chapter, "--module", module]
    if overwrite:
        cmd.append("--overwrite")
    if refine:
        cmd.append("--refine")
    if llm_refine:
        cmd.extend(["--llm-refine", "--llm-repeat", str(llm_repeat)])
    proc = subprocess.run(cmd, text=True, check=False)
    raise SystemExit(proc.returncode)


# ══════════════════════════════════════════════════════
# gcc-evo suggest
# ══════════════════════════════════════════════════════

@cli.group("suggest")
def cmd_suggest():
    """参数调整建议管理（人类审核后才生效）。"""
    pass


@cmd_suggest.command("list")
@click.option("--status", default="pending", help="pending / applied / rejected / all")
def suggest_list(status):
    """列出建议。"""
    from gcc_evolution.suggest import SuggestStore
    store = SuggestStore()
    items = store.list_all("" if status == "all" else status)
    if not items:
        click.echo(f"  无 {status} 建议"); return
    click.echo(f"\n  {status} 建议 ({len(items)} 条):")
    click.echo(f"  {'ID':<22} {'KEY':<10} {'对象':<12} {'优先级':<8} 描述")
    click.echo("  " + "─" * 80)
    for s in items:
        click.echo(f"  {s.suggestion_id:<22} {s.related_key:<10} {s.subject:<12} {s.priority:<8} {s.description[:38]}")


@cmd_suggest.command("review")
def suggest_review():
    """逐条审核待处理建议。"""
    from gcc_evolution.suggest import SuggestStore
    store = SuggestStore()
    pending = store.list_pending()
    if not pending:
        click.echo("  无待审核建议 🎉"); return

    click.echo(f"\n  待审核: {len(pending)} 条\n")
    for i, s in enumerate(pending, 1):
        click.echo(f"  [{i}/{len(pending)}] {s.suggestion_id}")
        click.echo(f"  来源: {s.source}  关联: {s.related_key}  优先级: {s.priority}")
        click.echo(f"  对象: {s.subject}")
        click.echo(f"  内容: {s.description}")
        if s.current_value:
            click.echo(f"  当前值: {s.current_value}  →  建议值: {s.suggested_value}")
        if s.evidence:
            click.echo(f"  证据: {s.evidence}")

        action = click.prompt("  [a=应用 / r=拒绝 / s=跳过 / q=退出]", default="s")
        click.echo("")
        if action == "q":
            break
        elif action == "a":
            note = click.prompt("  备注", default="")
            store.apply(s.suggestion_id, note)
            click.echo("  ✓ 已应用\n")
        elif action == "r":
            note = click.prompt("  拒绝原因", default="")
            store.reject(s.suggestion_id, note)
            click.echo("  ✗ 已拒绝\n")
        else:
            store.skip(s.suggestion_id)
            click.echo("  → 已跳过\n")

    stats = store.stats()
    click.echo(f"  统计: 待审核 {stats['pending']}  已应用 {stats['applied']}  已拒绝 {stats['rejected']}")


@cmd_suggest.command("apply")
@click.argument("suggestion_id")
@click.option("--note", default="")
def suggest_apply(suggestion_id, note):
    """直接应用指定建议。"""
    from gcc_evolution.suggest import SuggestStore
    if SuggestStore().apply(suggestion_id, note):
        click.echo(f"  ✓ {suggestion_id} 已应用")
    else:
        click.echo(f"  未找到 {suggestion_id}")


@cmd_suggest.command("reject")
@click.argument("suggestion_id")
@click.option("--note", default="")
def suggest_reject(suggestion_id, note):
    """拒绝指定建议。"""
    from gcc_evolution.suggest import SuggestStore
    if SuggestStore().reject(suggestion_id, note):
        click.echo(f"  ✗ {suggestion_id} 已拒绝")
    else:
        click.echo(f"  未找到 {suggestion_id}")


# ══════════════════════════════════════════════════════
# gcc-evo task  (Orchestrator)
# ══════════════════════════════════════════════════════


# ── Task 辅助函数 ─────────────────────────────────────────────

def _collect_opinion_context(key_id: str = "", depth: str = "normal") -> str:
    """收集数据库中的真实数据，供 opinion 命令注入模型"""
    import sqlite3
    from gcc_evolution.gcc_db import GccDb

    lines = []

    try:
        db   = GccDb()
        conn = db._connect()

        # ── 改善点状态 ─────────────────────────────
        rows = conn.execute(
            "SELECT id, title, status FROM improvements ORDER BY id"
        ).fetchall()
        if rows:
            lines.append("=== 改善点 ===")
            for r in rows:
                lines.append(f"  {r['id']}: {r['title']} [{r['status']}]")

        # ── 聚焦某个 KEY ────────────────────────────
        if key_id:
            lines.append(f"\n=== {key_id} 详情 ===")

            # 知识卡
            cards = conn.execute(
                "SELECT title FROM cards WHERE key_id=?", (key_id,)
            ).fetchall()
            lines.append(f"知识卡: {len(cards)} 张")
            for c in cards:
                lines.append(f"  - {c['title']}")

            # 任务
            tasks = conn.execute("""
                SELECT t.title, t.status, t.progress
                FROM tasks t
                JOIN improvement_task_links l ON t.task_id=l.task_id
                WHERE l.key_id=?
            """, (key_id,)).fetchall()
            lines.append(f"任务: {len(tasks)} 个")
            for t in tasks:
                lines.append(f"  - {t['title']} [{t['status']}] {t['progress']}")

            # 参数建议
            sugs = conn.execute("""
                SELECT s.description, s.status, s.evidence
                FROM suggestions s
                JOIN improvement_suggestion_links l ON s.suggestion_id=l.suggestion_id
                WHERE l.key_id=?
            """, (key_id,)).fetchall()
            if sugs:
                lines.append(f"参数建议: {len(sugs)} 条")
                for s in sugs:
                    lines.append(f"  [{s['status']}] {s['description']}")
                    if s['evidence']:
                        lines.append(f"    证据: {s['evidence'][:60]}")

        # ── 活跃任务 ────────────────────────────────
        active = conn.execute(
            "SELECT title, status, progress FROM tasks WHERE status IN ('running','paused')"
        ).fetchall()
        if active:
            lines.append("\n=== 活跃任务 ===")
            for t in active:
                lines.append(f"  [{t['status']}] {t['title']} {t['progress']}")

        # ── 待审核建议 ───────────────────────────────
        pending_sugs = conn.execute(
            "SELECT COUNT(*) as n FROM suggestions WHERE status='pending'"
        ).fetchone()
        lines.append(f"\n待审核建议: {pending_sugs['n']} 条")

        # ── 今日锚定 ────────────────────────────────
        try:
            from gcc_evolution.advisor import AnchorStore
            anchor = AnchorStore().get_today()
            if anchor:
                lines.append(f"今日锚定: {anchor.direction.value} (确信率{anchor.confidence:.0%})")
                if anchor.conditions:
                    lines.append(f"附加条件: {'; '.join(anchor.conditions)}")
            else:
                lines.append("今日锚定: 未设置")
        except Exception:
            pass

        # ── 交易数据摘要（deep 模式）────────────────
        if depth == "deep":
            lines.append("\n=== 近期交易摘要 ===")
            symbols = conn.execute(
                "SELECT DISTINCT symbol FROM trade_events ORDER BY event_time DESC LIMIT 5"
            ).fetchall()
            for s in symbols:
                sym = s['symbol']
                stats = conn.execute("""
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN final_action='BUY' THEN 1 ELSE 0 END) as buys,
                        SUM(CASE WHEN final_action='SELL' THEN 1 ELSE 0 END) as sells,
                        SUM(CASE WHEN ai_action != final_action THEN 1 ELSE 0 END) as filtered
                    FROM trade_events WHERE symbol=?
                    AND event_time >= datetime('now','-7 days')
                """, (sym,)).fetchone()
                if stats and stats['total']:
                    lines.append(
                        f"  {sym}: {stats['total']}条 买{stats['buys']} 卖{stats['sells']} 过滤{stats['filtered']}"
                    )

        # ── 产品参数概况 ────────────────────────────
        products = conn.execute(
            "SELECT symbol, version, last_updated FROM products ORDER BY symbol"
        ).fetchall()
        if products:
            lines.append(f"\n=== 产品参数 ({len(products)} 个) ===")
            for p in products:
                lines.append(f"  {p['symbol']} v{p['version'] or '?'} 更新:{(p['last_updated'] or '')[:10]}")

    except Exception as e:
        lines.append(f"[数据读取错误: {e}]")

    return "\n".join(lines) if lines else "暂无数据"


def _collect_system_state() -> dict:
    """收集当前系统状态，供 ask 命令注入提示词"""
    state = {}
    try:
        from gcc_evolution.orchestrator import Orchestrator
        orc = Orchestrator()
        active = orc.active_tasks()
        state["active_tasks"] = [
            {"key": t.key, "title": t.title, "progress": t.progress}
            for t in active[:3]
        ]
    except Exception:
        pass
    try:
        from gcc_evolution.advisor import AnchorStore
        anchor = AnchorStore().get_today()
        if anchor:
            state["anchor"] = {
                "direction": anchor.direction.value,
                "confidence": anchor.confidence,
            }
    except Exception:
        pass
    try:
        from gcc_evolution.suggest import SuggestStore
        state["pending_suggests"] = len(SuggestStore().list_pending())
    except Exception:
        pass
    try:
        from gcc_evolution.handoff import HandoffStore
        hs = HandoffStore()
        latest = hs.get_latest()
        if latest:
            state["last_handoff"] = getattr(latest, "agent_summary", "")[:100]
    except Exception:
        pass
    return state


def _dispatch_command(command: str, args: dict):
    """把解析出的命令字符串分发执行"""
    import subprocess, sys
    parts = ["gcc-evo"] + command.split()
    # 注入参数
    key = args.get("key", "")
    if key and "{key}" not in command:
        # 自动补充改善号参数
        if any(cmd in command for cmd in ["task start", "task done", "task pause", "task status"]):
            parts.append(key)
    try:
        subprocess.run(parts, check=False)
    except FileNotFoundError:
        # 直接用 python 调用
        subprocess.run([sys.executable, "-m", "gcc_evolution"] + parts[1:], check=False)


def _normalize_key(key: str) -> str:
    """把 '001' 或 '1' 统一转成 'KEY-001'"""
    if not key:
        return ""
    key = key.strip()
    if key.upper().startswith("KEY-"):
        return key.upper()
    # 纯数字，补齐3位
    if key.isdigit():
        return f"KEY-{int(key):03d}"
    return key.upper()


def _resolve_task(orc, key: str, preferred_status: list = None):
    """
    从 KEY 下找到最合适的任务。
    preferred_status: 优先返回这些状态的任务。
    多个活跃任务时让用户选。
    """
    tasks = orc.list_tasks(key=key)
    if not tasks:
        return None

    preferred = preferred_status or ["running", "paused", "pending"]
    candidates = [t for t in tasks if t.status.value in preferred]

    if not candidates:
        candidates = tasks

    if len(candidates) == 1:
        return candidates[0]

    # 多个任务，让用户选
    click.echo(f"  改善号 {key} 下有多个任务，请选择：")
    for i, t in enumerate(candidates, 1):
        click.echo(f"  [{i}] {t.status.value:<10} {t.title}  进度 {t.progress}")
    choice = click.prompt("  选择", default="1")
    try:
        idx = int(choice) - 1
        return candidates[idx]
    except Exception:
        return candidates[0]

@cli.group("task")
def cmd_task():
    """任务编排管理（跨会话持久化）。"""
    pass


@cmd_task.command("create")
@click.argument("title")
@click.option("--key", "-k", default="", help="改善号，如 001 或 KEY-001")
@click.option("--priority", "-p", default="normal", help="high / normal / low")
@click.option("--steps", "-s", multiple=True, help="步骤描述（可多次）")
def task_create(title, key, priority, steps):
    """创建新任务，关联改善号。

    示例：gcc-evo task create "分析信号质量" --key 001 --steps "提取日志" "统计胜率"
    """
    from gcc_evolution.orchestrator import Orchestrator
    orc = Orchestrator()
    key = _normalize_key(key)
    task = orc.create_task(title, key=key, priority=priority, steps=list(steps))
    click.echo(f"  ✓ 任务已创建")
    click.echo(f"    改善号: {task.key}  标题: {task.title}  优先级: {task.priority}")
    if task.steps:
        click.echo(f"    步骤: {' → '.join(s.description for s in task.steps)}")


@cmd_task.command("list")
@click.argument("key", required=False)
@click.option("--status", default="", help="running / paused / pending / completed")
def task_list(key, status):
    """列出任务。可按改善号过滤。

    示例：gcc-evo task list 001
    """
    from gcc_evolution.orchestrator import Orchestrator
    orc = Orchestrator()
    key = _normalize_key(key) if key else ""
    tasks = orc.list_tasks(status=status, key=key)
    if not tasks:
        click.echo("  无任务"); return
    click.echo(f"\n  {'改善号':<10} {'状态':<10} {'进度':<8} {'优先级':<8} 标题")
    click.echo("  " + "─" * 65)
    for i, t in enumerate(tasks, 1):
        click.echo(f"  [{i}] {t.key:<8} {t.status.value:<10} {t.progress:<8} {t.priority:<8} {t.title[:28]}")


@cmd_task.command("start")
@click.argument("key")
def task_start(key):
    """开始改善号下的任务。

    示例：gcc-evo task start 001
    """
    from gcc_evolution.orchestrator import Orchestrator
    orc = Orchestrator()
    key = _normalize_key(key)
    task = _resolve_task(orc, key, preferred_status=["paused", "pending"])
    if not task:
        click.echo(f"  改善号 {key} 下无待开始任务"); return
    if orc.start_task(task.task_id):
        t = orc.get_task(task.task_id)
        click.echo(f"  ✓ 已开始: {t.title}")
        if t.steps and t.current_step_index < len(t.steps):
            click.echo(f"  当前步骤 [{t.current_step_index+1}/{len(t.steps)}]: {t.steps[t.current_step_index].description}")
    else:
        click.echo(f"  无法开始任务")


@cmd_task.command("done")
@click.argument("key")
@click.option("--result", "-r", default="", help="结果说明")
def task_done(key, result):
    """完成改善号下当前任务的当前步骤。

    示例：gcc-evo task done 001 --result "1876条导入完成"
    """
    from gcc_evolution.orchestrator import Orchestrator
    orc = Orchestrator()
    key = _normalize_key(key)
    task = _resolve_task(orc, key, preferred_status=["running"])
    if not task:
        click.echo(f"  改善号 {key} 下无运行中任务"); return
    idx = task.current_step_index
    if orc.complete_step(task.task_id, idx, result=result):
        t = orc.get_task(task.task_id)
        if t.status.value == "completed":
            click.echo(f"  ✓ 任务全部完成: {t.title}")
        else:
            nxt = t.steps[t.current_step_index] if t.current_step_index < len(t.steps) else None
            click.echo(f"  ✓ 步骤完成，进度 {t.progress}")
            if nxt:
                click.echo(f"  下一步 [{t.current_step_index+1}/{len(t.steps)}]: {nxt.description}")


@cmd_task.command("pause")
@click.argument("key")
@click.option("--reason", default="")
def task_pause(key, reason):
    """暂停改善号下的任务（跨会话等待）。

    示例：gcc-evo task pause 001 --reason "等Vision结果"
    """
    from gcc_evolution.orchestrator import Orchestrator
    orc = Orchestrator()
    key = _normalize_key(key)
    task = _resolve_task(orc, key, preferred_status=["running"])
    if not task:
        click.echo(f"  改善号 {key} 下无运行中任务"); return
    if orc.pause_task(task.task_id, reason):
        click.echo(f"  ⏸ 已暂停: {task.title}")
        click.echo(f"  下次运行 gcc-evo task start {key} 继续")
    else:
        click.echo(f"  无法暂停")


@cmd_task.command("status")
@click.argument("key", required=False)
def task_status(key):
    """查看任务状态。可按改善号过滤。

    示例：
      gcc-evo task status        # 全部
      gcc-evo task status 001    # 只看改善号001
    """
    from gcc_evolution.orchestrator import Orchestrator
    orc = Orchestrator()

    if key:
        key = _normalize_key(key)
        tasks = orc.list_tasks(key=key)
        if not tasks:
            click.echo(f"  改善号 {key} 下无任务"); return
        click.echo(f"\n  改善号 {key} 的任务:")
        click.echo("  " + "─" * 55)
        for i, t in enumerate(tasks, 1):
            icon = {"running":"▶","paused":"⏸","completed":"✓","pending":"○","failed":"✗"}.get(t.status.value, "?")
            click.echo(f"  [{i}] {icon} {t.title}  进度 {t.progress}")
            if t.steps:
                for s in t.steps:
                    s_icon = {"completed":"✓","running":"▶","pending":"○","failed":"✗","skipped":"↷"}.get(s.status.value,"?")
                    result = f" → {s.result[:30]}" if s.result else ""
                    click.echo(f"       {s_icon} {s.description}{result}")
    else:
        s = orc.status()
        click.echo(f"\n  任务总览: 运行中 {s['running']}  暂停 {s['paused']}  待开始 {s['pending']}  已完成 {s['completed']}")
        active = orc.active_tasks()
        if active:
            click.echo("\n  活跃任务:")
            for t in active:
                icon = "▶" if t.status.value == "running" else "⏸"
                click.echo(f"    {icon} [{t.key}] {t.title}  进度 {t.progress}")
                if t.steps and t.current_step_index < len(t.steps):
                    click.echo(f"      当前: {t.steps[t.current_step_index].description}")


# ══════════════════════════════════════════════════════
# gcc-evo state  (StateManager)
# ══════════════════════════════════════════════════════

@cli.group("state")
def cmd_state():
    """系统全局状态管理（跨会话持久化）。"""
    pass


@cmd_state.command("get")
@click.argument("key")
def state_get(key):
    """读取状态值。"""
    from gcc_evolution.state_manager import StateManager
    sm = StateManager()
    entry = sm.get_entry(key)
    if not entry:
        click.echo(f"  {key}: 不存在或已过期"); return
    click.echo(f"  {key}: {entry.value}")
    click.echo(f"  版本: v{entry.version}  来源: {entry.source}  更新: {entry.updated_at[:19]}")


@cmd_state.command("set")
@click.argument("key")
@click.argument("value")
@click.option("--source", default="human")
@click.option("--ttl", default=0.0, type=float, help="有效期（小时），0=永久")
def state_set(key, value, source, ttl):
    """设置状态值。"""
    from gcc_evolution.state_manager import StateManager
    sm = StateManager()
    sm.set(key, value, source=source, ttl_hours=ttl)
    click.echo(f"  ✓ {key} = {value}")


@cmd_state.command("list")
@click.option("--tag", default="")
def state_list(tag):
    """列出所有状态。"""
    from gcc_evolution.state_manager import StateManager
    sm = StateManager()
    keys = sm.keys(tag=tag)
    if not keys:
        click.echo("  无状态记录"); return
    header = f"  {'KEY':<35} {'值':<25} {'版本':<6} 来源"
    click.echo("\n" + header)
    click.echo("  " + "─" * 75)
    for k in sorted(keys):
        e = sm.get_entry(k)
        if e:
            val = str(e.value)[:24]
            click.echo(f"  {k:<35} {val:<25} v{e.version:<5} {e.source}")


@cmd_state.command("snapshot")
@click.argument("name")
def state_snapshot(name):
    """保存当前状态快照。"""
    from gcc_evolution.state_manager import StateManager
    path = StateManager().snapshot(name)
    click.echo(f"  ✓ 快照已保存: {path}")


@cmd_state.command("diff")
@click.argument("snapshot_name")
def state_diff(snapshot_name):
    """对比当前状态与快照差异。"""
    from gcc_evolution.state_manager import StateManager
    result = StateManager().diff(snapshot_name)
    if "error" in result:
        click.echo(f"  {result['error']}"); return
    click.echo(f"  对比快照: {result['snapshot'][:19]}")
    if result['added']:
        click.echo(f"新增 ({len(result['added'])}):")
        for k, v in result['added'].items():
            click.echo(f"    + {k}: {v['value']}")
    if result['removed']:
        click.echo(f"删除 ({len(result['removed'])}):")
        for k, v in result['removed'].items():
            click.echo(f"    - {k}: {v['value']}")
    if result['changed']:
        click.echo(f"变更 ({len(result['changed'])}):")
        for k, v in result['changed'].items():
            click.echo(f"    ~ {k}: {v['old']} → {v['new']}")
    if not any([result['added'], result['removed'], result['changed']]):
        click.echo("  无变更")


# ══════════════════════════════════════════════════════
# gcc-evo schedule  (Scheduler)
# ══════════════════════════════════════════════════════

@cli.group("schedule")
def cmd_schedule():
    """定时任务管理。"""
    pass


@cmd_schedule.command("list")
def schedule_list():
    """列出所有定时任务。"""
    from gcc_evolution.scheduler import Scheduler
    sch = Scheduler()
    entries = sch.list_all()
    if not entries:
        click.echo("  无定时任务"); return
    click.echo(f"{'名称':<20} {'间隔':>6} {'状态':<8} {'下次到期':<12} 描述")
    click.echo("  " + "─" * 72)
    for e in entries:
        status = "启用" if e.enabled else "停用"
        due    = e.time_until_due()
        click.echo(f"  {e.name:<20} {e.interval_hours:>5}h {status:<8} {due:<12} {e.description}")


@cmd_schedule.command("done")
@click.argument("name")
def schedule_done(name):
    """标记定时任务已执行。"""
    from gcc_evolution.scheduler import Scheduler
    sch = Scheduler()
    if sch.mark_done(name):
        e = sch.get(name)
        click.echo(f"  ✓ {name} 已完成，下次: {e.time_until_due()}")
    else:
        click.echo(f"  任务 {name} 不存在")


@cmd_schedule.command("check")
def schedule_check():
    """检查到期任务。"""
    from gcc_evolution.scheduler import Scheduler
    sch = Scheduler()
    due = sch.check_due()
    if not due:
        click.echo("  无到期任务 ✓"); return
    click.echo(f"⏰ 到期任务 ({len(due)} 条):")
    for e in due:
        click.echo(f"  [{e.name}] {e.description}")
        click.echo(f"    命令: {e.command}")


@cmd_schedule.command("set-interval")
@click.argument("name")
@click.argument("hours", type=float)
def schedule_set_interval(name, hours):
    """修改定时任务间隔（小时）。"""
    from gcc_evolution.scheduler import Scheduler
    if Scheduler().set_interval(name, hours):
        click.echo(f"  ✓ {name} 间隔改为 {hours}h")
    else:
        click.echo(f"  任务 {name} 不存在")




# ── db ──────────────────────────────────────────────────────

# ══════════════════════════════════════════════════════
# gcc-evo skillbank  (SkillBank — SkillRL #19)
# ══════════════════════════════════════════════════════

@cli.group("skillbank")
def cmd_skillbank():
    """技能库管理（General + Task-Specific 分层，借鉴 SkillRL）。"""
    pass


@cmd_skillbank.command("status")
def skillbank_status():
    """查看技能库状态。"""
    from gcc_evolution.skill_registry import SkillBank
    sb = SkillBank()
    s  = sb.status()
    click.echo(f"\n  SkillBank 状态:")
    click.echo(f"    总技能:         {s['total']}")
    click.echo(f"    General Skills: {s['general']}  (跨品种通用规律)")
    click.echo(f"    Task-Specific:  {s['task_specific']}  (品种独特策略)")
    click.echo(f"    涵盖品种:       {', '.join(s['symbols']) or '无'}")
    click.echo(f"    平均置信度:     {s['avg_confidence']:.0%}")


@cmd_skillbank.command("distill")
def skillbank_distill():
    """从知识卡和已应用建议蒸馏技能（对应 SkillRL 蒸馏机制）。"""
    from gcc_evolution.skill_registry import SkillBank
    sb = SkillBank()
    n1 = sb.distill_from_cards()
    n2 = sb.distill_from_suggestions()
    click.echo(f"  ✓ 蒸馏完成")
    click.echo(f"    General Skills（来自知识卡）:     {n1} 条")
    click.echo(f"    Task-Specific（来自已应用建议）: {n2} 条")


@cmd_skillbank.command("retrieve")
@click.argument("query")
@click.option("--symbol", "-s", default="", help="聚焦品种，如 AMD")
@click.option("--top", "-n", default=5, type=int)
def skillbank_retrieve(query, symbol, top):
    """检索相关技能。

    示例：gcc-evo skillbank retrieve "N字结构拦截" --symbol AMD
    """
    from gcc_evolution.skill_registry import SkillBank
    sb      = SkillBank()
    results = sb.retrieve(query=query, symbol=symbol, top_k=top)
    if not results:
        click.echo("  无匹配技能"); return
    click.echo(f"\n  检索结果（{len(results)} 条）:")
    for e in results:
        tag = f"[{e.symbol}]" if e.symbol else "[通用]"
        click.echo(f"  {tag} {e.name}")
        click.echo(f"    {e.content[:80]}")
        click.echo(f"    置信度 {e.confidence:.0%}  使用 {e.use_count} 次  成功率 {e.success_rate:.0%}  v{e.version}")


@cmd_skillbank.command("add")
@click.argument("name")
@click.argument("content")
@click.option("--type", "skill_type", default="general", help="general / task_specific")
@click.option("--symbol", "-s", default="")
@click.option("--key", "-k", default="")
@click.option("--confidence", "-c", default=0.8, type=float)
def skillbank_add(name, content, skill_type, symbol, key, confidence):
    """手动添加技能。

    示例：gcc-evo skillbank add "高位禁止追多" "当日涨幅>5%不做多" --key 001
    """
    import uuid
    from gcc_evolution.skill_registry import SkillBank, SkillEntry
    sb = SkillBank()
    key_id = _normalize_key(key) if key else ""
    entry  = SkillEntry(
        skill_id   = f"MAN_{uuid.uuid4().hex[:8]}",
        name       = name,
        skill_type = skill_type,
        symbol     = symbol,
        key_id     = key_id,
        content    = content,
        source     = "human",
        confidence = confidence,
    )
    sb.add(entry)
    click.echo(f"  ✓ 技能已添加: {entry.skill_id}")
    click.echo(f"    [{skill_type}] {name}")


@cli.group("db", invoke_without_command=True)
@click.pass_context
def cmd_db(ctx):
    """Unified database: products, cards, improvements, sessions."""
    if ctx.invoked_subcommand is None:
        from gcc_evolution.gcc_db import GccDb
        db = GccDb()
        s = db.stats()
        click.echo("\n  GCC Database")
        click.echo(f"  {'─'*40}")
        click.echo(f"  Products:     {s['products']}")
        click.echo(f"  Improvements: {s['improvements']}")
        click.echo(f"  Cards:        {s['cards']}")
        click.echo(f"  Sessions:     {s['sessions']}")
        click.echo(f"  Trade events: {s['trade_events']}")
        click.echo(f"\n  Path: {s['db_path']}")



@cmd_db.command("sync")
def db_sync():
    """
    全量同步：文件系统 → 数据库，确保对齐。
    每次 pip install 新版本后运行一次。

    同步顺序：improvements → cards → products →
              tasks → suggestions → knowledge → analysis → sessions
    """
    from gcc_evolution.gcc_db import sync_all
    click.echo("\n  开始全量同步...")
    results = sync_all()

    click.echo(f"  改善台账:  {results['improvements']} 条")
    click.echo(f"  知识卡:    {results['cards']} 条")
    click.echo(f"  产品参数:  {results['products']} 个")
    click.echo(f"  任务:      {results['tasks']} 条")
    click.echo(f"  参数建议:  {results['suggestions']} 条")
    click.echo(f"  外部知识:  {results['knowledge']} 条")
    click.echo(f"  分析报告:  {results['analysis']} 条")
    click.echo(f"  会话历史:  {results['sessions']} 条")

    if results['errors']:
        click.echo(f"\n  ⚠ 错误 ({len(results['errors'])} 条):")
        for e in results['errors']:
            click.echo(f"    {e}")
    else:
        click.echo("\n  ✓ 全量同步完成，无错误")


@cmd_db.command("check")
def db_check():
    """
    目录对齐检查：验证项目结构是否与当前版本匹配。
    每次版本更新后运行一次。
    """
    from gcc_evolution.gcc_db import check_layout
    result = check_layout()

    click.echo(f"\n  GCC v{result['version']} 目录对齐检查")
    click.echo(f"  项目根目录: {result['root']}")
    click.echo(f"  {'─' * 50}")

    if result['ok']:
        click.echo(f"  ✓ 已存在 ({len(result['ok'])} 项)")

    if result['missing']:
        click.echo(f"\n  ✗ 缺失 ({len(result['missing'])} 项):")
        for path, desc in result['missing']:
            click.echo(f"    {path:<35} ← {desc}")
        click.echo("\n  运行 gcc-evo db sync 自动创建缺失目录并同步数据")
    else:
        click.echo("\n  ✓ 目录结构完整，与当前版本对齐")


@cmd_db.command("key")
@click.argument("key_num")
def db_key(key_num):
    """
    查看改善点的全部关联数据。

    示例：gcc-evo db key 001
    """
    from gcc_evolution.gcc_db import GccDb
    import sqlite3

    key_id = _normalize_key(key_num)
    db   = GccDb()
    conn = db._connect()

    # 改善点基本信息
    row = conn.execute(
        "SELECT * FROM improvements WHERE id=?", (key_id,)
    ).fetchone()
    if not row:
        click.echo(f"  改善点 {key_id} 不存在"); return

    click.echo(f"\n  {key_id}: {row['title']}")
    click.echo(f"  状态: {row['status']}")
    click.echo(f"  {'─' * 55}")

    # 知识卡
    cards = conn.execute(
        "SELECT id, title FROM cards WHERE key_id=?", (key_id,)
    ).fetchall()
    click.echo(f"\n  知识卡 ({len(cards)} 张):")
    for c in cards:
        click.echo(f"    {c['id']}: {c['title']}")

    # 任务
    tasks = conn.execute("""
        SELECT t.task_id, t.title, t.status, t.progress
        FROM tasks t
        JOIN improvement_task_links l ON t.task_id = l.task_id
        WHERE l.key_id=?
    """, (key_id,)).fetchall()
    click.echo(f"\n  任务 ({len(tasks)} 个):")
    for t in tasks:
        icon = {"completed":"✓","running":"▶","paused":"⏸","failed":"✗"}.get(t['status'],"○")
        click.echo(f"    {icon} {t['title']}  进度 {t['progress']}")

    # 产品参数关联
    products = conn.execute("""
        SELECT DISTINCT symbol, section, field_key, note
        FROM improvement_product_links WHERE key_id=?
    """, (key_id,)).fetchall()
    if products:
        click.echo(f"\n  影响产品参数 ({len(products)} 条):")
        for p in products:
            click.echo(f"    {p['symbol']} / {p['section']}.{p['field_key']}  {p['note'] or ''}")

    # 参数建议
    sugs = conn.execute("""
        SELECT s.description, s.status, s.suggested_value
        FROM suggestions s
        JOIN improvement_suggestion_links l ON s.suggestion_id = l.suggestion_id
        WHERE l.key_id=?
    """, (key_id,)).fetchall()
    if sugs:
        click.echo(f"\n  参数建议 ({len(sugs)} 条):")
        for s in sugs:
            icon = {"applied":"✓","rejected":"✗","pending":"○"}.get(s['status'],"?")
            click.echo(f"    {icon} {s['description'][:45]}")

    # 外部知识
    knows = conn.execute("""
        SELECT k.title, k.source_type, k.draft_status
        FROM knowledge_sources k
        JOIN improvement_knowledge_links l ON k.source_id = l.source_id
        WHERE l.key_id=?
    """, (key_id,)).fetchall()
    if knows:
        click.echo(f"\n  外部知识 ({len(knows)} 条):")
        for k in knows:
            click.echo(f"    [{k['source_type']}] {k['title']}  ({k['draft_status']})")

@cmd_db.command("import")
@click.option("--yaml", "yaml_dir", default="", help="Dir with product YAML files")
@click.option("--improvements", "imp_path", default="", help="improvements.json path")
@click.option("--cards", "cards_dir", default="", help="Dir with card .md files")
@click.option("--handoff", "handoff_path", default="", help="handoff.md path")
@click.option("--log", "log_path", default="", help="server.log 路径，解析 ACTION_LOG 导入 trade_events")
@click.option("--auto", is_flag=True, help="Auto-detect all sources")
def db_import(yaml_dir, imp_path, cards_dir, handoff_path, log_path, auto):
    """Import existing data into database (read-only, originals untouched)."""
    from gcc_evolution.gcc_db import GccDb, auto_import
    if auto:
        result = auto_import()
        click.echo(f"\n  Auto import complete:")
        click.echo(f"    Products:     {result['products']}")
        click.echo(f"    Improvements: {result['improvements']}")
        click.echo(f"    Cards:        {result['cards']}")
        click.echo(f"    Sessions:     {result['sessions']}")
        return
    db = GccDb()
    total = 0
    if yaml_dir:
        n = db.import_yaml_dir(yaml_dir)
        click.echo(f"  Products: {n}")
        total += n
    if imp_path:
        n = db.import_improvements(imp_path)
        click.echo(f"  Improvements: {n}")
        total += n
    if cards_dir:
        n = db.import_cards_dir(cards_dir)
        click.echo(f"  Cards: {n}")
        total += n
    if handoff_path:
        n = db.import_handoff_md(handoff_path)
        click.echo(f"  Sessions: {n}")
        total += n
    if log_path:
        from gcc_evolution.log_parser import parse_action_logs
        from gcc_evolution.gcc_db import GccDb
        db2 = GccDb()
        result = parse_action_logs(log_path, db2._db_path)
        click.echo(f"  Trade events: {result['inserted']} inserted, {result['skipped']} skipped, {result['errors']} errors")
        total += result['inserted']
    if total == 0:
        click.echo("  Use --auto or specify --yaml/--improvements/--cards/--handoff/--log")


@cmd_db.command("products")
@click.argument("symbol", required=False)
def db_products(symbol):
    """List products or show detail for a symbol."""
    from gcc_evolution.gcc_db import GccDb
    db = GccDb()
    if symbol:
        p = db.query_product(symbol.upper())
        if not p:
            click.echo(f"  {symbol} not found"); return
        click.echo(f"\n  {p['symbol']}  v{p['version']}  {p['market']}")
        click.echo(f"  Updated: {p.get('last_updated', 'N/A')}")
        for sec in ["n_gate", "entry", "risk", "timing", "quantity"]:
            if p.get(sec):
                click.echo(f"\n  [{sec}]")
                for k, v in p[sec].items():
                    click.echo(f"    {k}: {v}")
    else:
        products = db.query_all_products()
        if not products:
            click.echo("  No products. Run: gcc-evo db import --auto"); return
        click.echo(f"\n  {'SYMBOL':<12} {'VERSION':<8} {'MARKET':<12} UPDATED")
        click.echo(f"  {'─'*50}")
        for p in products:
            click.echo(f"  {p['symbol']:<12} {p['version']:<8} {p['market']:<12} {p.get('last_updated','')}")


@cmd_db.command("improvements")
@click.option("--key", "-k", default="", help="Filter by KEY id")
@click.option("--status", "-s", default="", help="Filter by status")
def db_improvements(key, status):
    """Show improvements table."""
    from gcc_evolution.gcc_db import GccDb
    db = GccDb()
    items = db.query_improvements(key=key or None, status=status or None)
    if not items:
        click.echo("  No data. Run: gcc-evo db import --improvements <path>"); return
    click.echo(f"\n  {'ID':<18} {'STATUS':<14} {'TYPE':<6} TITLE")
    click.echo(f"  {'─'*70}")
    for item in items:
        indent = "    " if item.get("parent_key") else ""
        click.echo(f"  {indent}{item['id']:<16} {item.get('status',''):<14} {item.get('item_type',''):<6} {item.get('title','')[:42]}")


@cmd_db.command("cards")
@click.option("--key", "-k", default="", help="Filter by KEY id")
def db_cards(key):
    """Show knowledge cards."""
    from gcc_evolution.gcc_db import GccDb
    db = GccDb()
    cards = db.query_cards(key_id=key or None)
    if not cards:
        click.echo("  No cards. Run: gcc-evo db import --cards <dir>"); return
    click.echo(f"\n  {'ID':<28} {'KEY':<10} {'L':<4} TITLE")
    click.echo(f"  {'─'*65}")
    for c in cards:
        lp = c.get('layer_priority') or 2
        click.echo(f"  {c['id']:<28} {c.get('key_id',''):<10} L{lp}  {c.get('title','')[:32]}")



@cmd_db.command("trades")
@click.argument("symbol", required=False)
@click.option("--date", "-d", default="", help="过滤日期，如 2026-02-20")
@click.option("--action", "-a", default="", help="过滤 final_action: BUY/SELL/HOLD")
@click.option("-n", "--limit", default=50, help="显示条数")
@click.option("--summary", is_flag=True, help="按品种汇总")
def db_trades(symbol, date, action, limit, summary):
    """查询 trade_events（从 server.log 导入的历史信号）。"""
    from gcc_evolution.gcc_db import GccDb
    from gcc_evolution.log_parser import query_summary
    db = GccDb()

    if summary:
        rows = query_summary(db.db_path)
        if not rows:
            click.echo("  No trade events. Run: gcc-evo db import --log logs/server.log")
            return
        click.echo(f"\n  {'SYMBOL':<12} {'TOTAL':>6} {'BUY':>5} {'SELL':>5} {'HOLD':>5} {'BLOCK':>6} {'PnL':>10} {'PERIOD'}")
        click.echo("  " + "─" * 70)
        for r in rows:
            sym, total, buys, sells, holds, blocked, pnl, d1, d2 = r
            click.echo(f"  {sym:<12} {total:>6} {buys:>5} {sells:>5} {holds:>5} {blocked:>6} {pnl or 0:>10.4f}  {d1}~{d2}")
        return

    import sqlite3
    conn = sqlite3.connect(db.db_path)
    where = []
    params = []
    if symbol:
        where.append("symbol=?"); params.append(symbol.upper())
    if date:
        where.append("event_date=?"); params.append(date)
    if action:
        where.append("final_action=?"); params.append(action.upper())
    sql = "SELECT symbol, event_time, timeframe, final_action, n_gate_result, signal_raw, wyckoff_phase, cycle_pnl FROM trade_events"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY event_time DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    conn.close()

    if not rows:
        click.echo("  No records found.")
        return

    click.echo(f"\n  {'SYMBOL':<10} {'TIME':<20} {'TF':>4} {'ACTION':<6} {'GATE':<6} {'SIGNAL':<15} {'PHASE':<20} {'PnL':>8}")
    click.echo("  " + "─" * 95)
    for r in rows:
        sym, t, tf, act, gate, sig, phase, pnl = r
        gate = gate or "-"
        sig = (sig or "")[:14]
        phase = (phase or "")[:19]
        click.echo(f"  {sym:<10} {t:<20} {tf:>4} {act:<6} {gate:<6} {sig:<15} {phase:<20} {pnl or 0:>8.4f}")



@cmd_db.command("sessions")
@click.option("--limit", "-n", default=20, show_default=True)
def db_sessions(limit):
    """Show session history from handoff."""
    from gcc_evolution.gcc_db import GccDb
    db = GccDb()
    sessions = db.query_sessions(limit=limit)
    if not sessions:
        click.echo("  No sessions. Run: gcc-evo db import --handoff <path>"); return
    click.echo(f"\n  {'#':<5} {'DATE':<12} {'KEY':<10} AGENT")
    click.echo(f"  {'─'*58}")
    for s in sessions:
        click.echo(f"  {str(s.get('session_num','')):<5} {s.get('session_date',''):<12} {s.get('key_anchor',''):<10} {s.get('agent','')[:35]}")


# ── knn (KEY-007) ─────────────────────────────────────────────
# GCC-0199: 切换到 modules/knn 五层架构 (原 vision_pre_filter 已废弃)

@cli.group("knn", invoke_without_command=True)
@click.pass_context
def cmd_knn(ctx):
    """KEY-007 KNN进化引擎 — 五层架构完整闭环

    直接运行 gcc-evo knn 执行完整进化流程:
      ① status    — 库状态概览 (plugin×symbol粒度)
      ② accuracy  — 准确率总览
      ③ evolve    — 统计→漂移检测→反思→gcc-evo闭环
    """
    if ctx.invoked_subcommand is None:
        click.echo("\n  ╔══════════════════════════════════════════╗")
        click.echo("  ║  KNN 五层架构进化引擎 (modules/knn)     ║")
        click.echo("  ╚══════════════════════════════════════════╝")
        click.echo()
        click.echo("  Step 1/3: 库状态")
        ctx.invoke(knn_status)
        click.echo()
        click.echo("  Step 2/3: 准确率总览")
        ctx.invoke(knn_accuracy)
        click.echo()
        click.echo("  Step 3/3: 回溯验证 + 进化")
        ctx.invoke(knn_evolve, days=365, prune=False)


@cmd_knn.command("status")
def knn_status():
    """KNN库状态概览 — plugin×symbol粒度"""
    import numpy as np
    sys.path.insert(0, str(Path.cwd()))
    try:
        from modules.knn import get_plugin_knn_db
    except ImportError as e:
        click.echo(f"  ❌ modules.knn 加载失败: {e}"); return

    db = get_plugin_knn_db()
    stats = db.get_stats()
    pending_count = stats.pop("_pending", 0)
    all_keys = sorted(stats.keys())

    if not all_keys:
        click.echo("\n  KNN历史库: ❌ 空 (state/plugin_knn_history.npz)")
        click.echo("  运行 gcc-evo knn bootstrap 构建")
        return

    # 按plugin聚合
    plugins = {}
    symbols = set()
    total_samples = 0
    for key in all_keys:
        parts = key.split("_", 1)
        if len(parts) < 2:
            continue
        plugin, symbol = parts[0], parts[1]
        if plugin not in plugins:
            plugins[plugin] = {}
        plugins[plugin][symbol] = stats[key]
        symbols.add(symbol)
        total_samples += stats[key]["samples"]

    import time as _t
    hist_file = Path("state/plugin_knn_history.npz")
    age_h = (_t.time() - hist_file.stat().st_mtime) / 3600 if hist_file.exists() else -1
    click.echo(f"\n  KNN五层架构历史库 — {len(plugins)}外挂 × {len(symbols)}品种 = {len(all_keys)}组合")
    click.echo(f"  总样本: {total_samples:,}  待回填: {pending_count}  更新: {age_h:.1f}h前")
    click.echo(f"  {'─'*65}")
    click.echo(f"  {'外挂':<18} {'品种数':>6} {'总样本':>8} {'平均胜率':>8}")
    click.echo(f"  {'─'*65}")

    for plugin in sorted(plugins.keys()):
        sym_data = plugins[plugin]
        n_syms = len(sym_data)
        n_samples = sum(d["samples"] for d in sym_data.values())
        avg_wr = np.mean([d["win_rate"] for d in sym_data.values()]) if sym_data else 0
        click.echo(f"  {plugin:<18} {n_syms:>6} {n_samples:>8} {avg_wr:>7.1%}")

    click.echo(f"  {'─'*65}")
    click.echo(f"  {'合计':<18} {len(symbols):>6} {total_samples:>8}")

    # 健康度诊断: 偏斜检测
    click.echo(f"\n  健康度诊断 (前20组合):")
    click.echo(f"  {'组合':<25} {'样本':>6} {'胜率':>6} {'偏斜':>6}")
    click.echo(f"  {'─'*50}")
    sorted_keys = sorted(all_keys, key=lambda k: stats[k]["samples"], reverse=True)[:20]
    for key in sorted_keys:
        s = stats[key]
        wr = s["win_rate"]
        skew_warn = "⚠偏斜" if wr > 0.7 or wr < 0.3 else "✓"
        click.echo(f"  {key:<25} {s['samples']:>6} {wr:>5.0%} {skew_warn:>6}")

    # L5 alignment状态
    click.echo(f"\n  L5 gcc-evo对齐状态:")
    evo_tune = Path("state/knn_evo_tune.json")
    if evo_tune.exists():
        try:
            tune = json.loads(evo_tune.read_text("utf-8"))
            click.echo(f"  调参建议: k={tune.get('k_adjust','N/A')} "
                       f"精英卡={tune.get('elite_count',0)}张 "
                       f"avg_acc={tune.get('avg_accuracy',0):.1%}")
        except Exception:
            click.echo(f"  调参文件: 读取失败")
    else:
        click.echo(f"  调参文件: 尚未生成 (L5未执行过)")

    drift_log = Path("state/knn_drift_log.jsonl")
    if drift_log.exists():
        try:
            lines = drift_log.read_text("utf-8").strip().splitlines()
            if lines:
                last = json.loads(lines[-1])
                click.echo(f"  漂移告警: {len(lines)}条 最近={last.get('key','')} "
                           f"drift={last.get('drift',0):.1%} [{last.get('level','')}]")
        except Exception:
            pass
    else:
        click.echo(f"  漂移告警: 无记录")

    # evolve历史
    evo_file = Path("state/knn_evolve_log.json")
    if evo_file.exists():
        try:
            evo_data = json.loads(evo_file.read_text("utf-8"))
            if evo_data:
                last = evo_data[-1]
                click.echo(f"  进化历史: {len(evo_data)}次 最近={last.get('timestamp','')[:10]} "
                           f"准确率={last.get('overall_accuracy',0):.1%}")
        except Exception:
            pass


@cmd_knn.command("accuracy")
@click.option("--plugin", "-p", default="", help="只显示指定外挂")
def knn_accuracy(plugin):
    """准确率详览 — per-plugin×symbol"""
    sys.path.insert(0, str(Path.cwd()))
    try:
        from modules.knn import load_knn_accuracy
    except ImportError as e:
        click.echo(f"  ❌ modules.knn 加载失败: {e}"); return

    acc_map = load_knn_accuracy()
    if not acc_map:
        click.echo("\n  准确率数据: ❌ 空 (plugin_knn_accuracy.json不存在或backfill未执行)")
        # fallback: 显示老的knn_accuracy_map.json
        old_map = Path("state/knn_accuracy_map.json")
        if old_map.exists():
            try:
                old_data = json.loads(old_map.read_text("utf-8"))
                click.echo(f"\n  [降级] 老准确率map (per-symbol, 非per-plugin×symbol):")
                click.echo(f"  {'品种':<12} {'准确率':>8}")
                click.echo(f"  {'─'*25}")
                for k, v in sorted(old_data.items(), key=lambda x: x[1] if isinstance(x[1], (int, float)) else 0):
                    if k.startswith("_"):
                        continue
                    if isinstance(v, (int, float)):
                        click.echo(f"  {k:<12} {v:>7.1%}")
                click.echo(f"  更新: {old_data.get('_updated', '?')[:19]}")
            except Exception:
                pass
        return

    updated = acc_map.get("_updated", "未知")
    entries = {k: v for k, v in acc_map.items() if not k.startswith("_") and isinstance(v, dict)}

    if plugin:
        entries = {k: v for k, v in entries.items() if k.startswith(plugin)}

    click.echo(f"\n  KNN准确率 — {len(entries)}组合 (更新:{updated[:19]})")
    click.echo(f"  {'─'*65}")
    click.echo(f"  {'外挂×品种':<25} {'准确率':>8} {'总数':>6} {'正确':>6} {'评级':>6}")
    click.echo(f"  {'─'*65}")

    for key in sorted(entries.keys(), key=lambda k: entries[k].get("accuracy", 0)):
        info = entries[key]
        acc = info.get("accuracy", 0)
        total = info.get("total", 0)
        wins = info.get("wins", 0)
        grade = "★★★" if acc >= 0.75 else ("★★" if acc >= 0.65 else ("★" if acc >= 0.55 else "—"))
        click.echo(f"  {key:<25} {acc:>7.1%} {total:>6} {wins:>6} {grade:>6}")

    click.echo(f"  {'─'*65}")
    if entries:
        import numpy as np
        all_acc = [v.get("accuracy", 0) for v in entries.values()]
        click.echo(f"  平均准确率: {np.mean(all_acc):.1%}  "
                   f"最高: {max(all_acc):.1%}  最低: {min(all_acc):.1%}")


@cmd_knn.command("bootstrap")
@click.option("--days", "-d", default=365, show_default=True, help="拉取天数")
@click.option("--force", is_flag=True, default=False, help="强制重建(覆盖已有数据)")
def knn_bootstrap(days, force):
    """构建KNN历史库 — 用yfinance 4H K线滑窗"""
    sys.path.insert(0, str(Path.cwd()))
    try:
        from modules.knn import bootstrap_from_yfinance
        click.echo(f"\n  开始构建KNN历史库 ({days}天4H K线{'，强制重建' if force else ''})...")
        result = bootstrap_from_yfinance(days=days)
        if isinstance(result, dict):
            for sym, info in result.items():
                if isinstance(info, dict):
                    click.echo(f"  {sym}: {info.get('samples', 0)}样本")
        click.echo("  ✓ 完成")
    except Exception as e:
        click.echo(f"  ❌ 失败: {e}")
        import traceback; traceback.print_exc()


@cmd_knn.command("backfill")
def knn_backfill():
    """手动触发回填 — 处理pending记录并更新准确率"""
    sys.path.insert(0, str(Path.cwd()))
    try:
        from modules.knn import get_plugin_knn_db, backfill_returns
    except ImportError as e:
        click.echo(f"  ❌ modules.knn 加载失败: {e}"); return

    db = get_plugin_knn_db()
    pending = db.get_pending()
    click.echo(f"\n  待回填: {len(pending)}条")

    if not pending:
        click.echo("  无需回填")
        return

    # 简单价格获取函数
    def _get_price(symbol, recorded_at):
        try:
            import yfinance as yf
            from datetime import datetime, timedelta
            from modules.knn.models import YF_MAP
            yf_sym = YF_MAP.get(symbol, symbol)
            rec_dt = datetime.fromisoformat(recorded_at.replace("Z", "+00:00"))
            end_dt = rec_dt + timedelta(hours=48)
            df = yf.Ticker(yf_sym).history(
                start=rec_dt.strftime("%Y-%m-%d"),
                end=end_dt.strftime("%Y-%m-%d"),
                interval="1h",
            )
            if df.empty:
                return None
            target_hours = 40  # ~10根4H
            if len(df) > target_hours:
                return float(df.iloc[target_hours]["Close"])
            return float(df.iloc[-1]["Close"])
        except Exception:
            return None

    filled = backfill_returns(db, get_price_func=_get_price)
    click.echo(f"  回填完成: {filled}条已处理")
    remaining = db.get_pending()
    click.echo(f"  剩余pending: {len(remaining)}条")


# ── KNN Evolve 辅助函数 ─────────────────────────────────
def _knn_compose_reflection(sym, acc, avg_conf, total_pred):
    """规则驱动反思(无需LLM): 分析KNN失败模式"""
    reasons = []
    if avg_conf < 0.15:
        reasons.append("置信度过低→特征区分度不足")
    if acc < 0.45:
        reasons.append("低于随机→特征可能不适用该组合")
    if acc >= 0.45 and acc < 0.55:
        reasons.append("接近随机→信号边际,需增强特征或增加样本")
    if total_pred < 50:
        reasons.append("预测次数<50→历史样本不足,结论不可靠")
    if avg_conf > 0.3 and acc < 0.50:
        reasons.append("高置信但低准确→模型过拟合历史模式")
    return "; ".join(reasons) if reasons else "需进一步分析"


def _knn_classify_failure(key, acc, avg_wr, n_samples, is_crypto):
    """根因分类: 为什么KNN在该组合上失败"""
    root_causes = []
    if n_samples < 50:
        root_causes.append(("INSUFFICIENT_DATA", "样本<50,历史不足"))
    if avg_wr < 0.40:
        root_causes.append(("LOW_FEATURE_DISCRIMINATION", "特征区分度极低"))
    if is_crypto and acc < 0.45:
        root_causes.append(("REGIME_SHIFT", "加密货币波动模式频繁切换"))
    if acc > 0.45 and acc < 0.55:
        root_causes.append(("MARGINAL_SIGNAL", "信号接近随机,需增强特征"))
    if avg_wr > 0.6 and acc < 0.50:
        root_causes.append(("OVERFIT", "模型过拟合,胜率高但准确率低"))
    return root_causes


def _knn_smart_prune_v2(db, key, target_keep_ratio=0.7):
    """TiM-inspired: Phase1 forget老旧无信息样本 + Phase2 merge相似特征向量"""
    import numpy as np
    data = db.get_history(key)
    if data is None:
        return 0
    rets = data.get("returns")
    feat = data.get("features")
    if rets is None or feat is None:
        return 0
    n = len(rets)
    if n < 100:
        return 0

    # Phase 1: forget old low-information samples
    keep_mask = np.ones(n, dtype=bool)
    oldest_third = n // 3
    for i in range(oldest_third):
        if abs(rets[i]) < 0.005:
            keep_mask[i] = False

    # Phase 2 (S09): merge near-duplicate feature vectors
    # Cosine distance < 0.15 ≈ similarity > 0.989 → 信息冗余
    remaining_idx = np.where(keep_mask)[0]
    if len(remaining_idx) >= 50 and feat.shape[1] > 0:
        sub_feat = feat[remaining_idx]
        norms = np.linalg.norm(sub_feat, axis=1, keepdims=True)
        norms = np.where(norms < 1e-8, 1.0, norms)
        normed = sub_feat / norms

        n_sub = len(remaining_idx)
        sub_merged = np.zeros(n_sub, dtype=bool)

        for i in range(n_sub):
            if sub_merged[i]:
                continue
            dists = np.linalg.norm(normed[i:i+1] - normed[i+1:], axis=1)
            near = np.where((dists < 0.15) & (~sub_merged[i+1:]))[0]
            if len(near) == 0:
                continue
            near_abs = near + i + 1
            group_orig = remaining_idx[np.concatenate([[i], near_abs])]
            # Average features and returns into the representative sample
            feat[remaining_idx[i]] = feat[group_orig].mean(axis=0)
            rets[remaining_idx[i]] = rets[group_orig].mean()
            for j in near_abs:
                sub_merged[j] = True
                keep_mask[remaining_idx[j]] = False

    # Phase 3: trim to target if still over
    kept = keep_mask.sum()
    target = int(n * target_keep_ratio)
    if kept > target:
        for i in range(n):
            if kept <= target:
                break
            if keep_mask[i]:
                keep_mask[i] = False
                kept -= 1

    removed = n - int(keep_mask.sum())
    if removed > 0:
        db._db[key]["features"] = feat[keep_mask]
        db._db[key]["returns"] = rets[keep_mask]
        if "regimes" in db._db[key]:
            regimes = db._db[key]["regimes"]
            db._db[key]["regimes"] = [r for r, m in zip(regimes, keep_mask) if m]
        if "timestamps" in db._db[key]:
            timestamps = db._db[key]["timestamps"]
            db._db[key]["timestamps"] = [t for t, m in zip(timestamps, keep_mask) if m]
    return removed


@cmd_knn.command("evolve")
@click.option("--days", "-d", default=365, show_default=True, help="回溯验证天数")
@click.option("--prune/--no-prune", default=False, help="淘汰低质量老特征")
def knn_evolve(days, prune):
    """进化闭环: 库统计→准确率分析→漂移检测→反思→淘汰

    基于 modules/knn 五层架构:
      L2 store统计 → L3 漂移检测 → L4 准确率 → L5 gcc-evo闭环
    """
    import numpy as np
    sys.path.insert(0, str(Path.cwd()))

    try:
        from modules.knn import (
            get_plugin_knn_db, load_knn_accuracy, detect_drift, compute_psi,
            feedback_to_retriever, create_knn_experience_cards,
            sync_evo_tuning, check_accuracy_drift,
        )
    except ImportError as e:
        click.echo(f"  ❌ modules.knn 加载失败: {e}"); return

    db = get_plugin_knn_db()
    all_stats = db.get_stats()
    pending = all_stats.pop("_pending", 0)

    if not all_stats:
        click.echo("  ❌ KNN库为空, 先运行 gcc-evo knn bootstrap"); return

    click.echo(f"\n  KNN进化闭环 — {len(all_stats)}组合")
    click.echo(f"  {'═'*70}")

    # ── Phase 0: 加载已有约束 + 经验卡 ──
    cstore = None
    try:
        from gcc_evolution.constraints import ConstraintStore
        cstore = ConstraintStore()
        knn_constraints = cstore.active_constraints(key="KEY-007")
        if knn_constraints:
            click.echo(f"  已有KNN约束: {len(knn_constraints)}条")
    except Exception:
        pass

    try:
        from gcc_evolution.experience_store import GlobalMemory
        gm = GlobalMemory()
        knn_cards = gm.get_by_key("KEY-007")
        if knn_cards:
            click.echo(f"  KEY-007经验卡: {len(knn_cards)}张")
        gm.close()
    except Exception:
        pass

    # ── Phase 1: 库统计 + 准确率分析 ──
    acc_map = load_knn_accuracy()
    click.echo(f"\n  Phase 1: 组合准确率分析")
    click.echo(f"  {'─'*70}")
    click.echo(f"  {'组合':<25} {'样本':>6} {'胜率':>6} {'准确率':>8} {'评级':>6}")
    click.echo(f"  {'─'*70}")

    good_keys = []
    bad_keys = []
    all_results = []

    for key in sorted(all_stats.keys()):
        s = all_stats[key]
        n = s["samples"]
        wr = s["win_rate"]
        # 从accuracy map获取backfill后的准确率
        acc_info = acc_map.get(key)
        if isinstance(acc_info, dict):
            acc = acc_info.get("accuracy", wr)
        elif isinstance(acc_info, (int, float)):
            acc = acc_info
        else:
            acc = wr  # fallback到胜率
        grade = "★★★" if acc >= 0.75 else ("★★" if acc >= 0.65 else ("★" if acc >= 0.55 else "—"))
        click.echo(f"  {key:<25} {n:>6} {wr:>5.0%} {acc:>7.1%} {grade:>6}")

        all_results.append((key, n, wr, acc))
        if acc >= 0.75:
            good_keys.append(key)
        elif acc < 0.55 and n >= 30:
            bad_keys.append(key)

    click.echo(f"  {'─'*70}")
    total_samples = sum(s["samples"] for s in all_stats.values())
    avg_acc = np.mean([r[3] for r in all_results]) if all_results else 0
    click.echo(f"  合计: {len(all_results)}组合  {total_samples:,}样本  平均准确率: {avg_acc:.1%}")

    overall_acc = avg_acc  # 用于后续记录

    # ── Phase 2: 进化建议 ──
    click.echo(f"\n  Phase 2: 进化建议")
    click.echo(f"  {'─'*70}")
    if good_keys:
        click.echo(f"  ✓ 高准确率 (≥75%): {', '.join(good_keys[:10])}")
    if bad_keys:
        click.echo(f"  ✗ 低准确率 (<55%, n≥30): {', '.join(bad_keys[:10])}")
    if avg_acc >= 0.55:
        click.echo(f"  ✓ 整体准确率 {avg_acc:.1%} — 进化方向正确")
    elif avg_acc >= 0.50:
        click.echo(f"  △ 整体准确率 {avg_acc:.1%} — 略优于随机")
    else:
        click.echo(f"  ✗ 整体准确率 {avg_acc:.1%} — 低于随机, 需审视算法")

    # ── Phase 2.5: 低准确率深度分析 ──
    reflections = {}
    root_causes = {}
    if bad_keys:
        click.echo(f"\n  Phase 2.5: 低准确率组合深度分析")
        click.echo(f"  {'─'*70}")

        for key in bad_keys[:15]:
            r = next((x for x in all_results if x[0] == key), None)
            if not r:
                continue
            _, n, wr, acc = r
            reflection = _knn_compose_reflection(key, acc, wr, n)
            reflections[key] = reflection
            click.echo(f"  🔍 {key}: {reflection}")

            is_crypto = any(c in key for c in ("BTCUSDC", "ETHUSDC", "SOLUSDC", "ZECUSDC"))
            causes = _knn_classify_failure(key, acc, wr, n, is_crypto)
            if causes:
                root_causes[key] = causes
                cause_strs = [f"{c[0]}({c[1]})" for c in causes]
                click.echo(f"     根因: {'; '.join(cause_strs)}")

        # 自动生成约束
        if cstore is not None:
            from gcc_evolution.constraints import Constraint
            for key in bad_keys:
                r = next((x for x in all_results if x[0] == key), None)
                if not r:
                    continue
                _, n, wr, acc = r
                cstore.add(Constraint(
                    source_card_id=f"KNN_EVOLVE_{key}",
                    rule=f"DO NOT trust KNN for {key} (accuracy {acc:.1%}, n={n})",
                    context=f"knn_evolve",
                    key="KEY-007",
                    confidence=round(1.0 - acc, 2),
                ))
            click.echo(f"  已为{len(bad_keys)}个低准确率组合生成约束")

    # ── Phase 3: L3 漂移检测 ──
    click.echo(f"\n  Phase 3: L3漂移检测")
    click.echo(f"  {'─'*70}")
    drift_count = 0
    for key in sorted(all_stats.keys()):
        data = db.get_history(key)
        if data is None:
            continue
        feat = data.get("features")
        if feat is None or len(feat) < 60:
            continue
        try:
            mid = len(feat) // 2
            old_feat = feat[:mid]
            new_feat = feat[mid:]
            # 用每列平均PSI
            psi_vals = []
            for col in range(min(feat.shape[1], 10)):
                psi = compute_psi(old_feat[:, col], new_feat[:, col])
                psi_vals.append(psi)
            avg_psi = np.mean(psi_vals)
            if avg_psi > 0.25:
                click.echo(f"  ⚠ {key}: PSI={avg_psi:.3f} — 显著漂移")
                drift_count += 1
            elif avg_psi > 0.10:
                click.echo(f"  △ {key}: PSI={avg_psi:.3f} — 轻微漂移")
        except Exception:
            continue
    if drift_count == 0:
        click.echo(f"  ✓ 未检测到显著漂移")

    # ── Phase 4: 淘汰低质量特征 ──
    if prune:
        click.echo(f"\n  Phase 4: 淘汰老旧特征")
        click.echo(f"  {'─'*70}")
        pruned_total = 0
        for key in bad_keys:
            pruned = _knn_smart_prune_v2(db, key)
            if pruned > 0:
                pruned_total += pruned
                remaining = len(db.get_history(key).get("returns", [])) if db.get_history(key) else 0
                click.echo(f"  {key}: 淘汰{pruned}条, 保留{remaining}条")
        if pruned_total > 0:
            db._save()
            click.echo(f"  ✓ 共淘汰 {pruned_total} 条, 已保存")
        else:
            click.echo(f"  无需淘汰")

    # ── Phase 5: L5 gcc-evo闭环 ──
    click.echo(f"\n  Phase 5: L5 gcc-evo闭环")
    click.echo(f"  {'─'*70}")
    try:
        if acc_map and any(isinstance(v, dict) for k, v in acc_map.items() if not k.startswith("_")):
            feedback_to_retriever(acc_map)
            click.echo(f"  ✓ 准确率→Retriever权重反哺")
            create_knn_experience_cards(acc_map)
            click.echo(f"  ✓ 高精度经验卡自动创建")
            check_accuracy_drift(acc_map)
            click.echo(f"  ✓ 准确率偏离检测完成")
        else:
            click.echo(f"  △ 跳过L5 (plugin_knn_accuracy.json无per-key数据)")
        sync_evo_tuning()
        click.echo(f"  ✓ gcc-evo→KNN反向调参")
    except Exception as e:
        click.echo(f"  ⚠ L5执行异常(非致命): {e}")

    # ── 保存进化记录 ──
    from datetime import datetime
    evo_log = Path("state/knn_evolve_log.json")
    record = {
        "timestamp": datetime.now().isoformat(),
        "days": days,
        "overall_accuracy": round(overall_acc, 4),
        "total_combinations": len(all_results),
        "total_samples": total_samples,
        "good_keys": good_keys[:20],
        "bad_keys": bad_keys[:20],
        "pruned": prune,
        "drift_count": drift_count,
        "per_key": {r[0]: {"samples": r[1], "win_rate": round(r[2], 4),
                           "accuracy": round(r[3], 4)} for r in all_results},
        "reflections": reflections,
        "root_causes": {k: [(c[0], c[1]) for c in cs] for k, cs in root_causes.items()},
    }
    try:
        history = json.loads(evo_log.read_text("utf-8")) if evo_log.exists() else []
    except Exception:
        history = []
    history.append(record)
    if len(history) > 20:
        history = history[-20:]
    evo_log.write_text(json.dumps(history, indent=2, ensure_ascii=False), "utf-8")
    click.echo(f"\n  进化记录已保存: {evo_log}")

    # Delta对比
    if len(history) >= 2:
        prev = history[-2]
        prev_acc = prev.get("overall_accuracy", 0)
        delta = overall_acc - prev_acc
        arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
        click.echo(f"  Delta vs上次: {prev_acc:.1%} → {overall_acc:.1%} ({arrow}{abs(delta):.1%})")


# ── card (知识卡活化) ─────────────────────────────────────

# ── retro (回溯分析) ──

@cli.group("retro", invoke_without_command=True)
@click.pass_context
def cmd_retro(ctx):
    """回溯分析 — trade_events→DecisionRecord→规则发现"""
    if ctx.invoked_subcommand is None:
        click.echo("\n  ✦ Retrospective Analysis Commands")
        click.echo("  ════════════════════════════════════════")
        click.echo("  gcc-evo retro summary          trade_events汇总统计")
        click.echo("  gcc-evo retro analyze SYMBOL   分析品种回溯(默认7天)")
        click.echo("  gcc-evo retro report SYMBOL    生成报告(--json输出JSON)")
        click.echo("  gcc-evo retro rules SYMBOL     导出结构化规则JSON")
        click.echo()


@cmd_retro.command("summary")
def retro_summary():
    """trade_events 按品种汇总统计"""
    gcc = _gcc_dir()
    db_path = gcc / "gcc.db"
    from log_to_decision_adapter import LogToDecisionAdapter
    adapter = LogToDecisionAdapter(db_path)
    summary = adapter.get_summary()
    if not summary:
        click.echo("  ⚠ 无trade_events数据。先运行: gcc-evo db parse-log")
        return
    click.echo(f"\n  ✦ Trade Events Summary ({len(summary)} symbols)")
    click.echo(f"  {'─' * 65}")
    click.echo(f"  {'Symbol':<12} {'KEY':<10} {'Total':>6} {'Exec':>6} {'Block':>6} {'Period'}")
    click.echo(f"  {'─' * 65}")
    for sym, s in summary.items():
        click.echo(
            f"  {sym:<12} {s['key']:<10} {s['total']:>6} {s['executed']:>6} "
            f"{s['intercepted']:>6} {s['first_date']}~{s['last_date']}"
        )
    click.echo()


@cmd_retro.command("analyze")
@click.argument("symbol")
@click.option("--since", default="7d", help="时间窗口: 7d/30d/2026-01-01")
@click.option("--key", default=None, help="指定KEY (默认从symbol推断)")
def retro_analyze(symbol, since, key):
    """分析品种回溯: 加载→分析→输出报告"""
    gcc = _gcc_dir()
    db_path = gcc / "gcc.db"
    from log_to_decision_adapter import LogToDecisionAdapter
    from gcc_evolution.retrospective import RetrospectiveAnalyzer
    adapter = LogToDecisionAdapter(db_path)
    records = adapter.load_records(symbol=symbol, key=key, since=since)
    if not records:
        click.echo(f"  ⚠ {symbol} 无记录 (since={since})")
        return
    resolved_key = key or records[0].key
    analyzer = RetrospectiveAnalyzer(key=resolved_key)
    analyzer.load_records(records)
    report = analyzer.generate_report(period_start=since, period_end="now")
    click.echo(report.to_markdown())


@cmd_retro.command("report")
@click.argument("symbol")
@click.option("--since", default="7d", help="时间窗口")
@click.option("--key", default=None, help="指定KEY")
@click.option("--json-out", "use_json", is_flag=True, help="输出JSON格式")
def retro_report(symbol, since, key, use_json):
    """生成回溯报告 (默认Markdown, --json-out输出JSON)"""
    gcc = _gcc_dir()
    db_path = gcc / "gcc.db"
    from log_to_decision_adapter import LogToDecisionAdapter
    from gcc_evolution.retrospective import RetrospectiveAnalyzer
    adapter = LogToDecisionAdapter(db_path)
    records = adapter.load_records(symbol=symbol, key=key, since=since)
    if not records:
        click.echo(f"  ⚠ {symbol} 无记录 (since={since})")
        return
    resolved_key = key or records[0].key
    analyzer = RetrospectiveAnalyzer(key=resolved_key)
    analyzer.load_records(records)
    report = analyzer.generate_report(period_start=since, period_end="now")
    if use_json:
        click.echo(json.dumps(report.to_json(), ensure_ascii=False, indent=2))
    else:
        click.echo(report.to_markdown())


@cmd_retro.command("rules")
@click.argument("symbol")
@click.option("--since", default="30d", help="时间窗口(规则发现建议30d+)")
@click.option("--key", default=None, help="指定KEY")
def retro_rules(symbol, since, key):
    """导出结构化规则JSON → .GCC/state/rules_export_{KEY}.json"""
    gcc = _gcc_dir()
    db_path = gcc / "gcc.db"
    from log_to_decision_adapter import LogToDecisionAdapter
    from gcc_evolution.retrospective import RetrospectiveAnalyzer
    adapter = LogToDecisionAdapter(db_path)
    records = adapter.load_records(symbol=symbol, key=key, since=since)
    if not records:
        click.echo(f"  ⚠ {symbol} 无记录 (since={since})")
        return
    resolved_key = key or records[0].key
    analyzer = RetrospectiveAnalyzer(key=resolved_key)
    analyzer.load_records(records)
    report = analyzer.generate_report(period_start=since, period_end="now")
    rules = report.extract_rules()
    out_path = analyzer.export_rules_json(report, output_dir=gcc / "state")
    click.echo(f"\n  ✦ Rules Export: {resolved_key}")
    click.echo(f"  {'─' * 50}")
    click.echo(f"  Records: {len(records)} ({report.executed_total} exec, {report.intercepted_total} block)")
    click.echo(f"  Rules discovered: {len(rules)}")
    for r in rules:
        click.echo(f"    {r['rule_id']}: {r['trigger_condition']} → {r['action']} (conf={r['confidence']:.2f}, n={r['sample_count']})")
    click.echo(f"  Output: {out_path}")
    click.echo()


@cli.group("card", invoke_without_command=True)
@click.pass_context
def cmd_card(ctx):
    """知识卡活化系统 — 索引/查询/蒸馏"""
    if ctx.invoked_subcommand is None:
        click.echo("\n  ✦ Card Bridge Commands")
        click.echo("  ════════════════════════════════════")
        click.echo("  gcc-evo card index       扫描JSON卡片,建立索引")
        click.echo("  gcc-evo card query -m X  按module查询规则")
        click.echo("  gcc-evo card report      有效性报告")
        click.echo("  gcc-evo card distill     执行蒸馏(更新confidence)")
        click.echo()


@cmd_card.command("index")
def card_index():
    """扫描 skill/cards/ JSON，建立索引，输出统计。"""
    from gcc_evolution.card_bridge import CardBridge
    bridge = CardBridge()
    count = bridge.load_index()
    stats = bridge.stats()
    click.echo(f"\n  ✦ Card Index: {count} cards indexed")
    click.echo(f"  {'─' * 45}")
    if stats["modules"]:
        click.echo("  Modules:")
        for m, n in sorted(stats["modules"].items()):
            click.echo(f"    {m}: {n} cards")
    if stats["types"]:
        click.echo("  Types:")
        for t, n in sorted(stats["types"].items()):
            click.echo(f"    {t}: {n} cards")
    click.echo()


@cmd_card.command("query")
@click.option("-m", "--module", default="", help="Filter by system_mapping.module")
@click.option("-t", "--card-type", default="", help="Filter by card type")
@click.option("-k", "--keyword", default="", help="Keyword filter (comma-separated)")
@click.option("--route", type=click.Choice(["keyword", "bm25", "rrf"]), default="keyword",
              help="Retrieval route")
@click.option("--graph-hop", type=int, default=0, help="Expand related_cards graph by N hops")
@click.option("--session-id", default="default", help="Session id for access logging/hotspots")
@click.option("--min-conf", default=0.3, help="Minimum confidence threshold")
def card_query(module, card_type, keyword, route, graph_hop, session_id, min_conf):
    """按module/type/keyword查询知识卡规则。"""
    from gcc_evolution.card_bridge import CardBridge
    bridge = CardBridge()
    bridge.load_index()
    keywords = [k.strip() for k in keyword.split(",") if k.strip()] if keyword else None
    results = bridge.query(
        module=module or None,
        card_type=card_type or None,
        keywords=keywords,
        route=route,
        graph_hops=max(0, graph_hop),
        session_id=session_id,
        min_confidence=min_conf,
    )
    if not results:
        click.echo("  No matching cards found."); return
    click.echo(f"\n  ✦ {len(results)} cards matched")
    click.echo(f"  {'─' * 55}")
    for r in results:
        click.echo(f"  {r['card_id']}: {r['title'][:40]}")
        line = f"    module={r['module']} conf={r['confidence']:.1f} quality={r['quality']} rules={len(r['rules'])}"
        if route == "bm25":
            line += f" bm25={r.get('bm25_score', 0.0):.3f}"
        if route == "rrf":
            line += f" rrf={r.get('rrf_score', 0.0):.4f} bm25={r.get('bm25_score', 0.0):.3f}"
        if r.get("rank_source") == "graph_1hop":
            line += f" graph_hops={r.get('graph_hops', 0)} from={r.get('graph_from', '')}"
        click.echo(line)
        for i, rule in enumerate(r["rules"][:3]):  # 最多显示3条规则
            click.echo(f"    [{i}] IF: {rule.get('if', '')[:60]}")
            click.echo(f"        THEN: {rule.get('then', '')[:60]}")
    click.echo()


@cmd_card.command("session-end")
@click.option("--session-id", default="default", help="Session id to aggregate hotspots")
@click.option("--top-k", default=10, type=int, help="Top-k cards/keywords in hotspot summary")
def card_session_end(session_id, top_k):
    """Run KNN session-end hook: access log aggregation + top-k hotspots."""
    from gcc_evolution.card_bridge import card_knn_session_end
    summary = card_knn_session_end(session_id=session_id, top_k=max(1, top_k))
    click.echo(f"\n  ✦ Session {summary.get('session_id')} events={summary.get('events', 0)}")
    click.echo("  Top cards:")
    for row in summary.get("top_cards", [])[:max(1, top_k)]:
        click.echo(f"    {row.get('card_id')}: {row.get('hits')}")
    click.echo("  Top keywords:")
    for row in summary.get("top_keywords", [])[:max(1, top_k)]:
        click.echo(f"    {row.get('keyword')}: {row.get('hits')}")
    click.echo()


@cmd_card.command("knn-precompute")
@click.option("--top-k", default=10, type=int, help="K used by NearestNeighbors index")
def card_knn_precompute(top_k):
    """Build and persist prefetch index (state/prefetch_index.pkl)."""
    from gcc_evolution.card_bridge import card_knn_precompute_index
    meta = card_knn_precompute_index(top_k=max(1, top_k))
    click.echo(
        f"\n  ✦ precompute done backend={meta.get('backend')} cards={meta.get('cards')} "
        f"top_k={meta.get('top_k')} path={meta.get('path')}\n"
    )


@cmd_card.command("knn-status")
def card_knn_status():
    """Show prefetch index preload status."""
    from gcc_evolution.card_bridge import CardBridge
    b = CardBridge()
    meta = (b._prefetch_index or {}).get("meta", {})
    click.echo(
        f"\n  ✦ prefetch backend={meta.get('backend')} loaded={meta.get('loaded', False)} "
        f"path=state/prefetch_index.pkl\n"
    )


@cmd_card.command("knn-drift-check")
@click.option("--window", default=120, type=int, help="Recent event window size for PSI")
@click.option("--psi-threshold", default=0.25, type=float, help="PSI threshold to trigger rebuild")
def card_knn_drift_check(window, psi_threshold):
    """Run incremental drift check and trigger full precompute rebuild on drift."""
    from gcc_evolution.card_bridge import card_knn_incremental_update_and_drift_check
    r = card_knn_incremental_update_and_drift_check(
        window=max(20, int(window)),
        psi_threshold=float(psi_threshold),
    )
    click.echo(
        f"\n  ✦ drift psi={r.get('psi')} threshold={r.get('psi_threshold')} "
        f"triggered={r.get('triggered_rebuild')} events={r.get('events')}\n"
    )


@cmd_card.command("blast-radius")
@click.option("--seeds", default="", help="Comma-separated seed card ids")
@click.option("--hops", default=2, type=int, help="BFS hops")
@click.option("--depth-decay", default=0.7, type=float, help="Risk decay per hop (0~1)")
@click.option("--threshold-n", default=5, type=int, help="Manual approval threshold on impacted count")
@click.option("--out", default="state/blast_radius_report.json", help="Output report path")
def card_blast_radius(seeds, hops, depth_decay, threshold_n, out):
    """Compute 2-hop blast radius report for EvolutionGate."""
    from gcc_evolution.card_bridge import card_evolution_blast_radius
    seed_ids = [s.strip() for s in seeds.split(",") if s.strip()]
    rep = card_evolution_blast_radius(
        seed_ids,
        hops=max(1, int(hops)),
        out_path=out,
        depth_decay=float(depth_decay),
        threshold_n=max(1, int(threshold_n)),
    )
    summary = rep.get("summary", {})
    click.echo(
        f"\n  ✦ blast-radius impacted={summary.get('impacted_total')} "
        f"severity={summary.get('severity')} hops={rep.get('hops')} "
        f"risk={summary.get('total_risk')} manual_required={summary.get('manual_approval_required')} "
        f"out={rep.get('output_path')}\n"
    )


@cmd_card.command("report")
def card_report():
    """有效性报告 (激活次数、正确率、蒸馏建议)。"""
    from gcc_evolution.card_bridge import CardBridge
    bridge = CardBridge()
    bridge.load_index()
    click.echo(bridge.get_effectiveness_report())


@cmd_card.command("distill")
def card_distill():
    """执行蒸馏: 更新confidence，标记flagged/validated。"""
    from gcc_evolution.card_bridge import CardBridge
    bridge = CardBridge()
    bridge.load_index()
    report = bridge.distill()
    validated = sum(1 for v in report.values() if v["status"] == "validated")
    flagged = sum(1 for v in report.values() if v["status"] == "flagged")
    active = sum(1 for v in report.values() if v["status"] == "active")
    click.echo(f"\n  ✦ Distill complete: {len(report)} cards processed")
    click.echo(f"    ✅ validated={validated}  🔵 active={active}  ⚠️ flagged={flagged}")
    if validated:
        click.echo("    Validated:")
        for cid, v in report.items():
            if v["status"] == "validated":
                click.echo(f"      {cid}: {v['title'][:35]} rate={v['correct_rate']:.0%}")
    if flagged:
        click.echo("    Flagged:")
        for cid, v in report.items():
            if v["status"] == "flagged":
                click.echo(f"      {cid}: {v['title'][:35]} rate={v['correct_rate']:.0%}")
    click.echo()


@cmd_card.command("sync")
@click.option("--direction", type=click.Choice(["both", "to-global", "from-global"]),
              default="both", help="同步方向")
def card_sync(direction):
    """GCC-0155/S76: CardBridge↔GlobalMemory双向同步。

    to-global:   validated卡片 → 经验库
    from-global: 经验库downstream数据 → 更新卡片confidence
    both:        先 to-global 再 from-global
    """
    from gcc_evolution.card_bridge import CardBridge
    from gcc_evolution.experience_store import GlobalMemory

    bridge = CardBridge()
    count = bridge.load_index()
    click.echo(f"\n  ✦ Card-Memory Sync — {count} cards loaded")

    gm = GlobalMemory()

    if direction in ("both", "to-global"):
        result = bridge.sync_to_global_memory(gm)
        click.echo(f"  → GlobalMemory: synced={result['synced']}, "
                    f"skipped={result['skipped']}, checked={result['total_checked']}")

    if direction in ("both", "from-global"):
        result = bridge.sync_from_global_memory(gm)
        click.echo(f"  ← GlobalMemory: updated={result['updated']}, "
                    f"unchanged={result['unchanged']}")

    gm.close()
    click.echo("  ✓ Sync complete\n")


# ── setup: L0 预先设置层 ──────────────────────────────────

@cli.command("setup")
@click.argument("key", required=False, default="")
@click.option("--edit", "-e", is_flag=True, default=False, help="编辑已有配置")
@click.option("--show", "-s", is_flag=True, default=False, help="只读查看配置")
@click.option("--reset", is_flag=True, default=False, help="重置配置")
@click.option("--goal", default="", help="目标 (非交互模式)")
@click.option("--criteria", default="", help="成功标准, 逗号分隔 (非交互模式)")
@click.option("--anchor/--no-anchor", default=True, help="是否需要人工确认 (默认=是)")
def cmd_setup(key, edit, show, reset, goal, criteria, anchor):
    """L0 预先设置层: 配置本次 gcc-evo loop 的目标和成功标准。

    \b
    每次 gcc-evo loop 前需要通过 L0 gate 校验。
    配置存储在 .GCC/state/session_config.json。

    \b
    示例:
      gcc-evo setup KEY-010              交互式向导
      gcc-evo setup KEY-010 --show       只读查看
      gcc-evo setup KEY-010 --edit       编辑字段
      gcc-evo setup KEY-010 --reset      重置配置
      gcc-evo setup KEY-010 --goal "改善模块评分" --criteria "评分>0.8,无P0告警"
    """
    import sys

    # 动态导入 gcc_evolution 子模块
    try:
        import sys as _sys
        _root = Path(__file__).parent.parent
        if str(_root) not in _sys.path:
            _sys.path.insert(0, str(_root))
        from gcc_evolution.session_config import SessionConfig
        from gcc_evolution.setup_wizard import run_setup_wizard, run_edit_menu
    except Exception as _ie:
        click.echo(f"  [ERROR] 无法加载 session_config: {_ie}")
        click.echo("  确保 gcc_evolution/ 目录存在且包含 session_config.py")
        return

    cfg = SessionConfig.load()

    # ── --show ──
    if show:
        if not SessionConfig.exists():
            click.echo("  [L0] 尚未配置，运行: gcc-evo setup <KEY>")
            return
        click.echo(cfg.summary())
        return

    # ── --reset ──
    if reset:
        confirm_key = click.prompt(f"  输入 KEY 确认重置", default="")
        if confirm_key == cfg.key or confirm_key == key:
            cfg.reset()
            click.echo("  [L0] 配置已重置")
        else:
            click.echo("  [L0] KEY 不匹配，取消")
        return

    # ── 非交互模式 (--goal + --criteria) ──
    if goal and criteria:
        if key:
            cfg.key = key
        cfg.goal = goal
        cfg.success_criteria = [c.strip() for c in criteria.split(",") if c.strip()]
        cfg.human_anchor_required = anchor
        ok, err = cfg.is_valid()
        if not ok:
            click.echo(f"  [L0] 配置无效: {err}")
            return
        path = cfg.save()
        click.echo(f"  [L0] 配置已保存: {path}")
        click.echo(cfg.summary())
        return

    # ── --edit ──
    if edit:
        if not SessionConfig.exists():
            click.echo("  [L0] 无已有配置，请先运行: gcc-evo setup <KEY>")
            return
        result = run_edit_menu(cfg)
        if result:
            click.echo("  [L0] 配置已更新")
        return

    # ── 交互式向导 ──
    if key:
        cfg.key = key
    result = run_setup_wizard(key=cfg.key, existing=cfg if SessionConfig.exists() else None)
    if result:
        ok, err = result.is_valid()
        if ok:
            click.echo(f"\n  [L0] 配置完成，现在可以运行:")
            click.echo(f"    gcc-evo loop --key {result.key}")
        else:
            click.echo(f"  [L0] 警告: {err}")


# ── loop: 完整闭环命令 ──

@cli.command("loop")
@click.argument("task_ids", nargs=-1)
@click.option("--key", "-k", default="KEY-009", help="改善项KEY(默认KEY-009)")
@click.option("--once", is_flag=True, default=False, help="只跑一轮(不循环)")
@click.option("--interval", "-i", default=300, type=int, help="循环间隔秒数(默认300=5min)")
@click.option("--dry-run", is_flag=True, default=False, help="预览模式,不写入")
def cmd_loop(task_ids, key, once, interval, dry_run):
    """绑定GCC任务的完整闭环: 任务进度→分析→经验卡→规则→提炼→Dashboard

    \b
    闭环6步:
      1. Tasks   — 读取绑定的GCC任务,显示steps进度
      2. Audit   — key009_audit --export (日志分析+问题发现)
      3. Cards   — 经验卡生成 → GlobalMemory (自动在audit内)
      4. Rules   — 结构化规则 → state/key009_rules.json (自动在audit内)
      5. Distill — 经验卡提炼 → SkillBank更新
      6. Report  — 闭环状态+任务完成度摘要

    \b
    示例:
      gcc-evo loop GCC-0172 GCC-0173 --once   绑定2个任务,单次闭环
      gcc-evo loop -k KEY-009 --once           KEY-009下所有活跃任务
      gcc-evo loop GCC-0172                    持续循环(每5分钟)
      gcc-evo loop --dry-run                   预览模式
    """
    import subprocess, sys, time
    from datetime import datetime
    from zoneinfo import ZoneInfo

    NY = ZoneInfo("America/New_York")
    project_root = Path(__file__).parent.parent
    tasks_json_path = _gcc_dir() / "pipeline" / "tasks.json"

    # ── L0 Gate: 校验 SessionConfig ──────────────────────
    try:
        _root_path = Path(__file__).parent.parent
        if str(_root_path) not in sys.path:
            sys.path.insert(0, str(_root_path))
        from gcc_evolution.session_config import SessionConfig as _SC
        _cfg = _SC.load()
        _ok, _err = _cfg.is_valid()
        if not _ok:
            click.echo(f"\n  ⛔ [L0 Gate] SessionConfig 未配置: {_err}")
            click.echo(f"  请先运行: gcc-evo setup {key}")
            click.echo(f"  (--skip-gate 可跳过此检查)\n")
            if not dry_run:
                return
            click.echo("  [dry-run] 跳过 L0 gate\n")
        else:
            click.echo(f"  ✅ [L0] {_cfg.key} — {_cfg.goal[:40]}")
            if _cfg.human_anchor_required:
                click.echo(f"  ⚓ 人工确认模式: 每轮结束后暂停")
    except ImportError:
        pass  # gcc_evolution 包未安装时跳过
    # ─────────────────────────────────────────────────────

    # ── 加载pipeline任务 ──
    def _load_tasks():
        """从pipeline/tasks.json加载任务列表"""
        if not tasks_json_path.exists():
            return []
        try:
            with open(str(tasks_json_path), "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("tasks", data) if isinstance(data, dict) else data
        except Exception:
            return []

    def _find_bound_tasks(all_tasks):
        """找到绑定的GCC任务(按task_ids或key筛选)"""
        bound = []
        for t in all_tasks:
            if not isinstance(t, dict):
                continue
            tid = t.get("task_id", "")
            tkey = t.get("key", "")
            stage = t.get("stage", "")
            # 指定了task_ids → 精确匹配
            if task_ids:
                if tid in task_ids:
                    bound.append(t)
            # 没指定task_ids → 按key筛选活跃任务(非done)
            elif tkey == key and stage != "done":
                bound.append(t)
        return bound

    def _show_task_progress(bound_tasks):
        """显示绑定任务的steps进度"""
        if not bound_tasks:
            click.echo(f"  ○ 无绑定任务")
            return 0, 0
        total_steps = 0
        done_steps = 0
        for t in bound_tasks:
            tid = t.get("task_id", "?")
            title = t.get("title", "?")
            stage = t.get("stage", "?")
            steps = t.get("steps", [])
            n_done = sum(1 for s in steps if s.get("status") == "done")
            n_total = len(steps)
            total_steps += n_total
            done_steps += n_done
            pct = f"{n_done}/{n_total}" if n_total else "no steps"
            stage_icon = {"done": "✅", "implement": "⚙️", "pending": "⏳", "analyze": "🔍"}.get(stage, "○")
            click.echo(f"  {stage_icon} {tid} ({pct}) {title[:50]}")
            # 显示未完成的steps
            for s in steps:
                if s.get("status") != "done":
                    sid = s.get("id", "?")
                    stitle = s.get("title", "?")
                    click.echo(f"       ○ {sid}: {stitle[:45]}")
        return done_steps, total_steps

    # ── loop_state.json 写入 ────────────────────────────────
    _loop_state_path = Path(__file__).parent / "loop_state.json"

    def _write_loop_state(running, round_num=0, last_start="", last_end="", steps=None):
        """写入 .GCC/loop_state.json 供 dashboard 读取"""
        state = {
            "running": running,
            "round": round_num,
            "last_start": last_start,
            "last_end": last_end,
            "steps": steps or {},
        }
        try:
            _loop_state_path.write_text(
                json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            pass
    # ─────────────────────────────────────────────────────

    _loop_round = [0]  # mutable counter

    def _run_step(name, cmd, timeout=120):
        """运行子步骤,返回(success, output)"""
        click.echo(f"  ⏳ {name}...", nl=False)
        try:
            proc = subprocess.run(
                cmd, cwd=str(project_root),
                capture_output=True, text=True,
                encoding="utf-8", timeout=timeout
            )
            if proc.returncode == 0:
                click.echo(f" ✓")
                return True, proc.stdout
            elif proc.returncode == 2:
                click.echo(f" — (skip)")
                return "skip", proc.stdout
            else:
                click.echo(f" ✗ (rc={proc.returncode})")
                err = (proc.stderr or "")[:200]
                if err:
                    click.echo(f"    {err}")
                return False, proc.stderr
        except subprocess.TimeoutExpired:
            click.echo(f" ✗ (timeout)")
            return False, "timeout"
        except Exception as e:
            click.echo(f" ✗ ({e})")
            return False, str(e)

    def _icon(ok):
        return "✓" if ok else "✗"

    def _run_once():
        now = datetime.now(NY)
        _loop_round[0] += 1
        ts_start = now.strftime("%Y-%m-%dT%H:%M:%S")
        all_tasks = _load_tasks()
        bound = _find_bound_tasks(all_tasks)
        task_label = ", ".join(task_ids) if task_ids else f"{key} (活跃)"
        click.echo(f"\n  ✦ 闭环 [{task_label}] — {now.strftime('%Y-%m-%d %H:%M:%S')} ET")
        click.echo(f"  {'═' * 55}")

        results = {}
        _step_status = {}  # 供 loop_state.json 使用

        # Step 1: 任务进度
        _write_loop_state(True, _loop_round[0], ts_start, "", {"tasks": {"status": "running"}, "audit": {"status": "pending"}, "distill": {"status": "pending"}, "rules": {"status": "pending"}, "dashboard": {"status": "pending"}})
        click.echo(f"\n  📋 Step 1/5: 任务进度 ({len(bound)} 个绑定任务)")
        done_s, total_s = _show_task_progress(bound)
        task_pct = f"{done_s}/{total_s}" if total_s else "N/A"
        results["tasks"] = len(bound) > 0
        _step_status["tasks"] = {"status": "ok" if results["tasks"] else "skip", "detail": task_pct}

        # Step 2: Audit (日志分析+经验卡+规则)
        _write_loop_state(True, _loop_round[0], ts_start, "", {**_step_status, "audit": {"status": "running"}, "distill": {"status": "pending"}, "rules": {"status": "pending"}, "dashboard": {"status": "pending"}})
        ok, out = _run_step(
            "Step 2/5: Audit (分析+经验卡+规则)",
            [sys.executable, "key009_audit.py", "--export"]
        )
        results["audit"] = ok
        _step_status["audit"] = {"status": "ok" if ok else "error"}

        # Step 3: Distill (经验提炼→SkillBank)
        _write_loop_state(True, _loop_round[0], ts_start, "", {**_step_status, "distill": {"status": "running"}, "rules": {"status": "pending"}, "dashboard": {"status": "pending"}})
        if dry_run:
            click.echo(f"  ⏳ Step 3/5: Distill (提炼)... [dry-run skip]")
            results["distill"] = True
        else:
            ok, out = _run_step(
                "Step 3/5: Distill (经验提炼→SkillBank)",
                [sys.executable, str(_gcc_dir() / "gcc_evo.py"), "distill"]
            )
            results["distill"] = ok
        _distill_st = "ok" if results["distill"] is True else ("skip" if results["distill"] == "skip" else "error")
        _step_status["distill"] = {"status": _distill_st}

        # Step 4: Rules check
        _write_loop_state(True, _loop_round[0], ts_start, "", {**_step_status, "rules": {"status": "running"}, "dashboard": {"status": "pending"}})
        rules_path = project_root / "state" / "key009_rules.json"
        if rules_path.exists():
            try:
                with open(str(rules_path), "r", encoding="utf-8") as _rf:
                    rules_data = json.loads(_rf.read())
                if isinstance(rules_data, dict):
                    n_rules = len(rules_data.get("rules", []))
                else:
                    n_rules = len(rules_data) if isinstance(rules_data, list) else 0
                click.echo(f"  ✓ Step 4/5: Rules — {n_rules} 条结构化规则")
                results["rules"] = True
                _step_status["rules"] = {"status": "ok", "detail": f"{n_rules}条规则"}
            except Exception as _re:
                click.echo(f"  ✗ Step 4/5: Rules — {_re}")
                results["rules"] = False
                _step_status["rules"] = {"status": "error"}
        else:
            click.echo(f"  ○ Step 4/5: Rules — 无规则文件")
            results["rules"] = False
            _step_status["rules"] = {"status": "skip"}

        # Step 5: Dashboard check
        _write_loop_state(True, _loop_round[0], ts_start, "", {**_step_status, "dashboard": {"status": "running"}})
        export_path = project_root / "state" / "key009_audit.json"
        if export_path.exists():
            try:
                with open(str(export_path), "r", encoding="utf-8") as _ef:
                    data = json.loads(_ef.read())
                ranges = list(data.keys())
                total_issues = 0
                total_fixed = 0
                for rng in ranges:
                    issues = data.get(rng, {}).get("issues", [])
                    total_issues += len([i for i in issues if i.get("type") != "POSITIVE" and not i.get("fixed") and not i.get("acked")])
                    total_fixed += len([i for i in issues if i.get("fixed")])
                click.echo(f"  ✓ Step 5/5: Dashboard — {ranges}, 问题{total_issues}, 已修复{total_fixed}")
                results["dashboard"] = True
                _step_status["dashboard"] = {"status": "ok", "detail": f"问题{total_issues}/修复{total_fixed}"}
            except Exception as _ee:
                click.echo(f"  ✗ Step 5/5: Dashboard — {_ee}")
                results["dashboard"] = False
                _step_status["dashboard"] = {"status": "error"}
        else:
            click.echo(f"  ✗ Step 5/5: Dashboard — 无export文件")
            results["dashboard"] = False

        # Summary
        ok_count = sum(1 for v in results.values() if v)
        total = len(results)
        health = "✓ HEALTHY" if ok_count == total else f"⚠ {ok_count}/{total}"
        # 写入完成状态
        ts_end = datetime.now(NY).strftime("%Y-%m-%dT%H:%M:%S")
        _write_loop_state(not once, _loop_round[0], ts_start, ts_end, _step_status)

        click.echo(f"\n  {'─' * 55}")
        click.echo(f"  闭环: {health}  |  任务Steps: {task_pct}")
        click.echo(f"  Tasks={_icon(results['tasks'])} Audit={_icon(results['audit'])} "
                    f"Distill={_icon(results['distill'])} Rules={_icon(results['rules'])} "
                    f"Dashboard={_icon(results['dashboard'])}")
        # 显示未完成steps的下一步建议
        if bound:
            next_steps = []
            for t in bound:
                for s in t.get("steps", []):
                    if s.get("status") != "done":
                        next_steps.append(f"{t['task_id']} {s.get('id','')}: {s.get('title','')[:40]}")
                        break
            if next_steps:
                click.echo(f"\n  📌 下一步:")
                for ns in next_steps[:3]:
                    click.echo(f"     → {ns}")
        click.echo()
        return ok_count == total

    # ── L6 Dashboard 启动 ───────────────────────────────────
    _dashboard_server = None
    try:
        from gcc_evolution.observer.event_bus import EventBus as _EB
        from gcc_evolution.dashboard_server import DashboardServer as _DS
        _bus = _EB.get()
        _dashboard_server = _DS(bus=_bus)
        if _dashboard_server.start():
            click.echo(f"  🖥  [L6] Dashboard: {_dashboard_server.url}")
        else:
            click.echo(f"  ⚠  [L6] Dashboard 端口占用，跳过")
            _dashboard_server = None
    except ImportError:
        pass  # 可选模块，不强制依赖
    # ─────────────────────────────────────────────────────

    if once:
        _run_once()
    else:
        task_label = ", ".join(task_ids) if task_ids else f"{key} (活跃)"
        click.echo(f"  ✦ 持续闭环 [{task_label}] — 间隔 {interval}s, Ctrl+C 退出")
        try:
            while True:
                _run_once()
                click.echo(f"  ⏳ 下次运行: {interval}s 后...")
                time.sleep(interval)
        except KeyboardInterrupt:
            click.echo("\n  ✋ 闭环已停止")
    if _dashboard_server:
        _dashboard_server.stop()


if __name__ == "__main__":
    main()
