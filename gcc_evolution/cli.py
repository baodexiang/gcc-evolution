"""
gcc-evo CLI â€” Command-line interface for the self-evolution engine.

Usage:
    gcc-evo version
    gcc-evo setup KEY [--show] [--edit] [--reset]
    gcc-evo init [--project NAME]
    gcc-evo l0 show
    gcc-evo l0 check
    gcc-evo l0 scaffold [--overwrite]
    gcc-evo l0 set-prereq NAME --status pass|fail [--evidence TEXT]
    gcc-evo loop TASK_ID [--once] [--provider PROVIDER] [--dry-run]
    gcc-evo commit "MESSAGE" [--task-id GCC-0001] [--step-id S1]
    gcc-evo ho create [--task-id GCC-0001] [--step-id S1] [--message TEXT]
    gcc-evo pipe task TITLE -k KEY -m MODULE -p PRIORITY
    gcc-evo pipe list
    gcc-evo pipe status TASK_ID
    gcc-evo memory compact
    gcc-evo memory export [--output PATH]
    gcc-evo health
"""

import sys
import json
import argparse
import subprocess
import re
import shutil
from pathlib import Path
from datetime import datetime


def _safe_print(text: str) -> None:
    """Print with a safe fallback for legacy console encodings."""
    try:
        print(text)
    except UnicodeEncodeError:
        # Avoid command failure on cp1252/cp936 terminals.
        print(text.encode("ascii", errors="replace").decode("ascii"))


def _configure_console_output() -> None:
    """Best-effort stdout/stderr Unicode compatibility on Windows."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            # Older environments may not support reconfigure().
            pass


def _print_banner():
    from . import __version__
    print(f"gcc-evo v{__version__} â€” AI Self-Evolution Engine")


def cmd_version(args):
    """Show version and environment info."""
    from . import __version__
    from .layer_manifest import canonical_layers
    print(f"gcc-evo v{__version__}")
    print(f"Python {sys.version.split()[0]}")
    print(f"Platform: {sys.platform}")

    # Check available layers
    layers = []
    try:
        from .free import l1 as _free_l1
        layers.append("L1:Memory")
    except ImportError:
        pass
    try:
        from .free import l2 as _free_l2
        layers.append("L2:Retrieval")
    except ImportError:
        pass
    try:
        from .free import l3 as _free_l3
        layers.append("L3:Distillation")
    except ImportError:
        pass
    try:
        from .paid import l4 as _paid_l4
        layers.append("L4:Decision")
    except ImportError:
        pass
    try:
        from .free import l5 as _free_l5
        layers.append("L5:Orchestration")
    except ImportError:
        pass
    try:
        from .paid import da as _paid_da
        layers.append("Anchor")
    except ImportError:
        pass
    try:
        from .free import ui as _free_ui
        layers.append("UI")
    except ImportError:
        pass

    print(f"Canonical availability: {', '.join(layers)}")
    print(f"Canonical layers: {', '.join(canonical_layers())}")
    print("Canonical boundary:")
    print("  free  -> UI, L0 Phase 1, base L1/L2/L3/L5")
    print("  paid  -> L0 Phase 2-4, full L1/L2/L3, L4, advanced L5, DA")

    # Check enterprise
    try:
        from .enterprise import knn_evolution
        print("Enterprise: available (license required)")
    except Exception:
        print("Enterprise: not loaded")


def cmd_setup(args):
    """L0 session setup wizard."""
    from .free.l0.session_config import SessionConfig
    from .free.l0.setup_wizard import run_setup_wizard
    from .setup_wizard import run_edit_menu

    key = args.key or ""

    if args.reset:
        cfg = SessionConfig()
        cfg.reset()
        print("Session config reset.")
        return

    if args.show:
        cfg = SessionConfig.load()
        _safe_print(cfg.summary())
        return

    if args.edit:
        cfg = SessionConfig.load()
        if not cfg.key and key:
            cfg.key = key
        run_edit_menu(cfg)
        return

    # Full wizard
    run_setup_wizard(key=key)


def cmd_init(args):
    """Initialize project structure."""
    project_name = args.project or "gcc-evo-project"
    base = Path.cwd() / project_name if args.project else Path.cwd()

    dirs = [
        base / ".GCC",
        base / ".GCC" / "handoffs",
        base / ".GCC" / "pipeline",
        base / ".GCC" / "state",
        base / "state",
        base / "state" / "audit",
        base / "logs",
    ]

    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)

    # evolution.yaml template
    config_path = base / ".GCC" / "evolution.yaml"
    if not config_path.exists():
        config_path.write_text(
            "# gcc-evo configuration\n"
            "version: '5.325'\n"
            "project: '{}'\n"
            "loop_interval: 300  # seconds\n"
            "skeptic_threshold: 0.75\n"
            "memory_ttl: 7  # days\n"
            "providers:\n"
            "  # Uncomment and set your API keys\n"
            "  # anthropic: sk-ant-...\n"
            "  # openai: sk-...\n"
            "  # gemini: ...\n"
            "  # deepseek: ...\n".format(project_name),
            encoding="utf-8",
        )

    # pipeline tasks.json
    tasks_path = base / ".GCC" / "pipeline" / "tasks.json"
    if not tasks_path.exists():
        tasks_path.write_text(
            json.dumps({"version": "1.0", "counter": 0, "tasks": []}, indent=2),
            encoding="utf-8",
        )

    if args.project:
        print(f"Initialized project: {project_name}/")
    else:
        print("Initialized gcc-evo in current directory")
    print(f"  .GCC/evolution.yaml  â€” configuration")
    print(f"  .GCC/pipeline/       â€” task management")
    print(f"  state/               â€” runtime state")
    print(f"  logs/                â€” execution logs")
    print()
    print("Next steps:")
    print("  1. gcc-evo setup KEY-001       # L0 session config (required before loop)")
    print("  2. gcc-evo l0 scaffold         # create mandatory Phase1-4 artifacts")
    print("  3. gcc-evo pipe task 'My first task' -k KEY-001 -m core -p P1")


def cmd_loop(args):
    """Run the 6-step self-improvement loop."""
    task_id = args.task_id
    once = args.once
    provider = args.provider
    dry_run = getattr(args, "dry_run", False)

    # â”€â”€ L0 Gate â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if not dry_run:
        from .free.l0.session_config import SessionConfig
        from .free.l0.governance import evaluate_l0_governance, format_governance_summary
        cfg = SessionConfig.load()
        ok, err = cfg.is_valid()
        if not ok:
            print(f"[L0] Session config invalid: {err}")
            print("Run first: gcc-evo setup <KEY>")
            return
        print(f"[L0] Goal: {cfg.goal}")
        print(f"[L0] KEY: {cfg.key}")
        governance = evaluate_l0_governance()
        if not governance["ok"]:
            print("[L0] Governance gate blocked loop execution.")
            print(format_governance_summary(governance))
            print("Run: gcc-evo l0 show")
            print("Run: gcc-evo l0 scaffold")
            print("Run: gcc-evo l0 set-prereq <name> --status pass --evidence '...'\n")
            return

    print(f"Loop: {task_id} | provider={provider or 'default'} | once={once}")

    from .free.l1.memory_tiers import SensoryMemory, ShortTermMemory, LongTermMemory
    from .free.l1.storage import JSONStorage
    from .free.l2.retriever import HybridRetriever
    from .free.l3.distiller import ExperienceDistiller
    from .paid.l4.skeptic import SkepticValidator
    from .free.l5.loop_engine import SelfImprovementLoop

    # Ensure state directory exists
    state_dir = Path("state")
    state_dir.mkdir(exist_ok=True)

    # Initialize layers
    sensory = SensoryMemory()
    short_term = ShortTermMemory(window_size=50)
    storage = JSONStorage(str(state_dir / "long_term.json"))
    long_term = LongTermMemory(storage=storage)
    retriever = HybridRetriever()
    distiller = ExperienceDistiller(min_confidence=0.7)
    skeptic = SkepticValidator()

    iteration = 0
    while True:
        iteration += 1
        ts = datetime.utcnow().strftime("%H:%M:%S")
        print(f"\n{'='*50}")
        print(f"[{ts}] Iteration {iteration} â€” {task_id}")
        print(f"{'='*50}")

        # Step 1: Observe
        print("[1/6] Observe... collecting data")
        observation = {
            "task_id": task_id,
            "iteration": iteration,
            "timestamp": datetime.utcnow().isoformat(),
        }
        sensory.store("current_observation", observation)
        short_term.store("observations", observation)

        # Step 2: Analyze
        print("[2/6] Analyze... detecting patterns")
        docs = [
            {"id": f"obs-{iteration}", "text": json.dumps(observation),
             "created_at": datetime.utcnow().isoformat()}
        ]
        retriever.index(docs)
        analysis = retriever.retrieve(task_id, top_k=3)

        # Step 3: Hypothesize
        print("[3/6] Hypothesize... generating improvement ideas")
        hypothesis = {
            "signal": "IMPROVE",
            "action": "OPTIMIZE",
            "confidence": 0.8,
            "conditions": ["+pattern_detected"],
            "reasoning": f"Iteration {iteration}: system running, collecting baseline data",
        }

        # Step 4: Verify (Skeptic Gate)
        print("[4/6] Verify... skeptic validation")
        validation = skeptic.validate(hypothesis)
        status = "PASS" if validation.is_valid else "BLOCKED"
        print(f"       Skeptic: {status} (confidence={validation.confidence:.2f})")
        if validation.issues:
            for issue in validation.issues:
                print(f"       Issue: {issue}")

        # Step 5: Distill
        print("[5/6] Distill... extracting experience")
        distiller.add_experience({
            "conditions": {"task": task_id, "iteration": iteration},
            "outcome": {"success": validation.is_valid, "action": "baseline"},
        })
        cards = distiller.distill()
        if cards:
            for card in cards:
                print(f"       New card: {card.card_id} ({card.confidence:.1%})")
                long_term.store(card.card_id, {
                    "title": card.title,
                    "confidence": card.confidence,
                    "summary": card.summary,
                })

        # Step 6: Report
        print("[6/6] Report... generating summary")
        report = {
            "task_id": task_id,
            "iteration": iteration,
            "skeptic_pass": validation.is_valid,
            "cards_generated": len(cards),
            "timestamp": datetime.utcnow().isoformat(),
        }
        print(f"       Result: iteration={iteration}, skeptic={status}, cards={len(cards)}")

        # Save report
        report_path = state_dir / "audit"
        report_path.mkdir(exist_ok=True)
        with open(report_path / f"{task_id}_log.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(report) + "\n")

        if once:
            print(f"\n[Done] Single iteration complete for {task_id}")
            break
        else:
            import time
            print(f"\nNext iteration in 300s...")
            time.sleep(300)


def cmd_pipe_task(args):
    """Create a new pipeline task."""
    tasks_path = Path(".GCC/pipeline/tasks.json")
    if not tasks_path.exists():
        print("Error: .GCC/pipeline/tasks.json not found. Run 'gcc-evo init' first.")
        sys.exit(1)

    data = json.loads(tasks_path.read_text(encoding="utf-8"))
    counter = data.get("counter", 0) + 1
    task_id = f"GCC-{counter:04d}"

    task = {
        "task_id": task_id,
        "title": args.title,
        "key": args.key,
        "module": args.module,
        "priority": args.priority,
        "stage": "pending",
        "created_at": datetime.utcnow().isoformat(),
        "steps": [],
    }

    data["counter"] = counter
    data["tasks"].append(task)
    tasks_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Created: {task_id} â€” {args.title}")
    print(f"  Key: {args.key} | Module: {args.module} | Priority: {args.priority}")


def cmd_pipe_list(args):
    """List all pipeline tasks."""
    tasks_path = Path(".GCC/pipeline/tasks.json")
    if not tasks_path.exists():
        print("No tasks found. Run 'gcc-evo init' first.")
        return

    data = json.loads(tasks_path.read_text(encoding="utf-8"))
    tasks = data.get("tasks", [])

    if not tasks:
        print("No tasks yet. Create one: gcc-evo pipe task 'Title' -k KEY-001 -m module -p P1")
        return

    print(f"{'ID':<12} {'Stage':<12} {'Priority':<6} {'Title'}")
    print("-" * 60)
    for t in tasks[-20:]:  # Show last 20
        print(f"{t['task_id']:<12} {t.get('stage','?'):<12} {t.get('priority','?'):<6} {t['title'][:40]}")

    print(f"\nTotal: {len(tasks)} tasks")


def cmd_pipe_status(args):
    """Show task status details."""
    tasks_path = Path(".GCC/pipeline/tasks.json")
    if not tasks_path.exists():
        print("No tasks found.")
        return

    data = json.loads(tasks_path.read_text(encoding="utf-8"))
    for t in data.get("tasks", []):
        if t["task_id"] == args.task_id:
            print(json.dumps(t, indent=2, ensure_ascii=False))
            return

    print(f"Task {args.task_id} not found.")


def cmd_l0_show(args):
    """Show current L0 governance state and checks."""
    from .free.l0.governance import evaluate_l0_governance, format_governance_summary

    report = evaluate_l0_governance()
    print(format_governance_summary(report))


def cmd_l0_check(args):
    """Run L0 governance checks with status summary."""
    from .free.l0.governance import evaluate_l0_governance, format_governance_summary

    report = evaluate_l0_governance()
    print(format_governance_summary(report))
    print()
    print("L0_STATUS=" + ("PASS" if report["ok"] else "BLOCKED"))


def cmd_l0_scaffold(args):
    """Create the required L0 artifact structure."""
    from .free.l0.governance import scaffold_required_artifacts

    created = scaffold_required_artifacts(overwrite=args.overwrite)
    if not created:
        print("No new artifact files created.")
        return
    print("Created artifact templates:")
    for path in created:
        print(f"  - {path}")


def cmd_l0_set_prereq(args):
    """Mark one prerequisite as pass/fail with evidence."""
    from .free.l0.governance import set_prerequisite_status

    ok = set_prerequisite_status(
        key=args.name,
        satisfied=args.status == "pass",
        evidence=args.evidence or "",
    )
    if not ok:
        print(f"Unknown prerequisite: {args.name}")
        print("Valid names: data_quality, deterministic_rules, mathematical_filters")
        return
    print(f"Updated prerequisite: {args.name} -> {args.status}")


def _utc_now_iso() -> str:
    return datetime.utcnow().isoformat()


def _infer_task_ref(message: str) -> tuple[str | None, str | None]:
    """Infer GCC task / pipeline step references from commit message."""
    task_match = re.search(r"\bGCC-\d{4}\b", message, flags=re.IGNORECASE)
    step_match = re.search(r"\bS\d+[a-z]?\b", message, flags=re.IGNORECASE)
    task_id = task_match.group(0).upper() if task_match else None
    step_id = step_match.group(0).upper() if step_match else None
    return task_id, step_id


def _update_pipeline_after_commit(task_id: str, step_id: str | None, commit_sha: str) -> tuple[bool, str]:
    """Update .GCC/pipeline/tasks.json so dashboard reflects commit progress."""
    tasks_path = Path(".GCC/pipeline/tasks.json")
    if not tasks_path.exists():
        return False, "Pipeline file not found (.GCC/pipeline/tasks.json). Skipped status sync."

    data = json.loads(tasks_path.read_text(encoding="utf-8"))
    tasks = data.get("tasks", [])
    task = next((t for t in tasks if str(t.get("task_id", "")).upper() == task_id.upper()), None)
    if not task:
        return False, f"Task {task_id} not found in pipeline. Skipped status sync."

    now = _utc_now_iso()
    task["updated_at"] = now

    if step_id:
        steps = task.get("steps", [])
        step = next((s for s in steps if str(s.get("id", "")).upper() == step_id.upper()), None)
        if not step:
            return False, f"Step {step_id} not found under {task_id}. Skipped step sync."
        step["status"] = "done"
        note = str(step.get("note", "")).strip()
        tag = f"committed {commit_sha}"
        step["note"] = f"{note} | {tag}" if note else tag

        all_done = all(str(s.get("status", "")).lower() in {"done", "completed", "closed"} for s in steps)
        if all_done:
            task["stage"] = "done"
            task["status"] = "done"
            task["completed_at"] = now
        else:
            if str(task.get("stage", "")).lower() in {"pending", "planning"}:
                task["stage"] = "implement"
            task["status"] = "running"
    else:
        # Task-level commit means the GCC task is completed.
        task["stage"] = "done"
        task["status"] = "done"
        task["completed_at"] = now
        for step in task.get("steps", []):
            if str(step.get("status", "")).lower() not in {"done", "completed", "closed"}:
                step["status"] = "done"
                note = str(step.get("note", "")).strip()
                tag = f"committed {commit_sha}"
                step["note"] = f"{note} | {tag}" if note else tag

    tasks_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    if step_id:
        return True, f"Synced dashboard state: {task_id}/{step_id} -> done"
    return True, f"Synced dashboard state: {task_id} -> done"


def _write_handoff_fallback(task_id: str | None, step_id: str | None, commit_sha: str, message: str) -> tuple[bool, str]:
    """Fallback handoff writer for OSS CLI when `ho create` command is unavailable."""
    try:
        branch_res = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
        )
        branch = branch_res.stdout.strip() if branch_res.returncode == 0 else "main"
        now = _utc_now_iso()
        date_tag = now[:10].replace("-", "")
        branch_dir = Path(".GCC") / "branches" / branch
        handoff_dir = Path(".GCC") / "handoffs"
        branch_dir.mkdir(parents=True, exist_ok=True)
        handoff_dir.mkdir(parents=True, exist_ok=True)

        body = [
            f"# Handoff: HO_AUTO_{date_tag}",
            "",
            "## Current State",
            f"Branch: {branch} | Commit: {commit_sha}",
            "",
            "## Trigger",
            "Auto-created by `gcc-evo commit` fallback (ho create unavailable).",
            "",
            "## Scope",
            f"Task: {task_id or 'N/A'}",
            f"Step: {step_id or 'N/A'}",
            f"Message: {message}",
            "",
            "## Next Steps",
            "1. Run validation/tests for this task scope.",
            "2. Continue next pending pipeline step.",
            "3. Create formal handoff with full GCC CLI if available (`gcc-evo ho create`).",
            "",
            f"_Generated at {now}_",
        ]
        content = "\n".join(body) + "\n"
        branch_md = branch_dir / "handoff.md"
        flat_md = handoff_dir / f"HO_AUTO_{date_tag}.md"
        branch_md.write_text(content, encoding="utf-8")
        flat_md.write_text(content, encoding="utf-8")
        return True, f"Wrote fallback handoff: {branch_md}"
    except Exception as exc:
        return False, f"Fallback handoff write failed: {exc}"


def _run_ho_create(task_id: str | None, step_id: str | None, commit_sha: str, message: str) -> tuple[bool, str]:
    """
    Best-effort handoff generation.
    Preference: call `gcc-evo ho create` directly so existing full CLI handles it.
    """
    candidates = [
        ["gcc-evo", "ho", "create"],
        [sys.executable, "-m", "gcc_evolution.gcc_evo", "ho", "create"],
    ]
    for cmd in candidates:
        try:
            res = subprocess.run(cmd, capture_output=True, text=True)
        except Exception:
            continue
        if res.returncode == 0:
            output = (res.stdout or "").strip()
            return True, output or "Executed: gcc-evo ho create"

    # Fallback for OSS CLI without `ho` command support.
    return _write_handoff_fallback(task_id=task_id, step_id=step_id, commit_sha=commit_sha, message=message)


def cmd_ho_create(args):
    """Create a handoff note in OSS mode."""
    task_id = args.task_id
    step_id = args.step_id
    message = (args.message or "manual handoff").strip()

    if step_id and not task_id:
        print("Error: --step-id requires --task-id.")
        sys.exit(1)

    sha_res = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
    commit_sha = sha_res.stdout.strip() if sha_res.returncode == 0 else "HEAD"

    ok, msg = _write_handoff_fallback(
        task_id=task_id,
        step_id=step_id,
        commit_sha=commit_sha,
        message=message,
    )
    if not ok:
        print(f"ho create failed: {msg}")
        sys.exit(1)
    print(f"ho create success: {msg}")

    sync_ok, sync_msg = _sync_docs_after_ho_create()
    if sync_ok:
        print(f"doc sync: {sync_msg}")
    else:
        print(f"doc sync warning: {sync_msg}")


def _sync_docs_after_ho_create() -> tuple[bool, str]:
    """
    Best-effort doc sync hook after `gcc-evo ho create`.
    Source of truth: .GCC/skill/SKILL.md
    Mirror target:    AIPro/v5.640/SKILL.md
    """
    src = Path(".GCC") / "skill" / "SKILL.md"
    dst = Path("AIPro") / "v5.640" / "SKILL.md"
    if not src.exists():
        return False, f"source not found: {src}"

    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
    except Exception as exc:
        return False, f"sync failed ({src} -> {dst}): {exc}"

    checker_candidates = [
        Path(".GCC") / "improvement" / "key-010" / "03062026" / "doc_consistency_check.py",
        Path(".GCC") / "scripts" / "doc_consistency_check.py",
    ]
    checker = next((p for p in checker_candidates if p.exists()), None)
    if checker is None:
        return True, f"synced {src} -> {dst}; checker not found"

    try:
        res = subprocess.run(
            [sys.executable, str(checker)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except Exception as exc:
        return False, f"synced, but checker execution failed: {exc}"

    output = (res.stdout or "").strip()
    if res.returncode != 0:
        err = (res.stderr or "").strip()
        tail = output or err or "unknown checker error"
        return False, f"synced, checker failed: {tail}"
    return True, f"synced {src} -> {dst}; checker passed"


def cmd_commit(args):
    """Git commit and sync pipeline/dashboard status."""
    message = args.message.strip()
    if not message:
        print("Error: commit message cannot be empty.")
        sys.exit(1)

    task_id = args.task_id
    step_id = args.step_id
    inferred_task, inferred_step = _infer_task_ref(message)
    if not task_id:
        task_id = inferred_task
    if not step_id:
        step_id = inferred_step

    if step_id and not task_id:
        print("Error: --step-id requires --task-id (or a GCC-xxxx reference in message).")
        sys.exit(1)

    if not args.no_add:
        add_res = subprocess.run(["git", "add", "-A"], capture_output=True, text=True)
        if add_res.returncode != 0:
            print("git add failed:")
            print(add_res.stderr.strip() or add_res.stdout.strip())
            sys.exit(add_res.returncode)

    commit_cmd = ["git", "commit", "-m", message]
    if args.no_verify:
        commit_cmd.append("--no-verify")
    commit_res = subprocess.run(commit_cmd, capture_output=True, text=True)
    if commit_res.returncode != 0:
        print("git commit failed:")
        print(commit_res.stderr.strip() or commit_res.stdout.strip())
        sys.exit(commit_res.returncode)

    sha_res = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
    commit_sha = sha_res.stdout.strip() if sha_res.returncode == 0 else "HEAD"
    print(commit_res.stdout.strip() or f"Committed: {commit_sha}")

    if task_id:
        ok, msg = _update_pipeline_after_commit(task_id=task_id, step_id=step_id, commit_sha=commit_sha)
        if ok:
            print(msg)
        else:
            print(f"Status sync warning: {msg}")
        ho_ok, ho_msg = _run_ho_create(task_id=task_id, step_id=step_id, commit_sha=commit_sha, message=message)
        if ho_ok:
            print(f"Auto handoff: success ({ho_msg})")
        else:
            print(f"Auto handoff: warning ({ho_msg})")
    else:
        print("No GCC task reference found; skipped dashboard status sync and ho create.")


def cmd_memory_compact(args):
    """Compact memory tiers."""
    state_dir = Path("state")
    lt_path = state_dir / "long_term.json"

    if not lt_path.exists():
        print("No long-term memory to compact.")
        return

    data = json.loads(lt_path.read_text(encoding="utf-8"))
    count = len(data)
    print(f"Long-term memory: {count} entries")
    print("Compaction complete (no-op in community version).")


def cmd_memory_export(args):
    """Export memory state."""
    state_dir = Path("state")
    output = args.output or f"gcc_evo_export_{datetime.utcnow().strftime('%Y%m%d')}.json"

    export = {}
    for f in state_dir.glob("*.json"):
        try:
            export[f.name] = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            pass

    Path(output).write_text(json.dumps(export, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Exported {len(export)} files to {output}")


def cmd_health(args):
    """System health check."""
    print("gcc-evo Health Check")
    print("-" * 40)

    checks = []

    # Check .GCC directory
    gcc_dir = Path(".GCC")
    ok = gcc_dir.exists()
    checks.append(("Project initialized (.GCC/)", ok))

    # Check state directory
    state_dir = Path("state")
    ok = state_dir.exists()
    checks.append(("State directory (state/)", ok))

    # Check config
    config = gcc_dir / "evolution.yaml"
    ok = config.exists()
    checks.append(("Configuration (evolution.yaml)", ok))

    # Check pipeline
    pipeline = gcc_dir / "pipeline" / "tasks.json"
    ok = pipeline.exists()
    checks.append(("Pipeline tasks", ok))

    # Check L0 governance
    try:
        from .free.l0.governance import evaluate_l0_governance
        governance = evaluate_l0_governance()
        checks.append(("L0 governance gate", governance["ok"]))
    except Exception:
        checks.append(("L0 governance gate", False))

    # Check imports
    try:
        from . import __version__
        checks.append((f"Package v{__version__}", True))
    except Exception:
        checks.append(("Package import", False))

    for name, ok in checks:
        icon = "OK" if ok else "MISSING"
        print(f"  [{icon:>7}] {name}")

    passed = sum(1 for _, ok in checks if ok)
    print(f"\n{passed}/{len(checks)} checks passed")


def main():
    _configure_console_output()
    parser = argparse.ArgumentParser(
        prog="gcc-evo",
        description="gcc-evo â€” AI Self-Evolution Engine",
    )
    subparsers = parser.add_subparsers(dest="command")

    # version
    subparsers.add_parser("version", help="Show version info")

    # setup (L0)
    setup_parser = subparsers.add_parser("setup", help="L0 session setup wizard")
    setup_parser.add_argument("key", nargs="?", default="", help="KEY number (e.g. KEY-010)")
    setup_parser.add_argument("--show", action="store_true", help="Show current config")
    setup_parser.add_argument("--edit", action="store_true", help="Edit existing config")
    setup_parser.add_argument("--reset", action="store_true", help="Reset/delete config")

    # init
    init_parser = subparsers.add_parser("init", help="Initialize project")
    init_parser.add_argument("--project", type=str, default=None)
    init_parser.add_argument(
        "--force",
        action="store_true",
        help="Backward-compatible no-op flag (legacy scripts).",
    )

    # l0 governance
    l0_parser = subparsers.add_parser("l0", help="L0 governance checks and artifacts")
    l0_sub = l0_parser.add_subparsers(dest="l0_command")
    l0_sub.add_parser("show", help="Show prerequisite and artifact status")
    l0_sub.add_parser("check", help="Run prerequisite and artifact gate checks")
    l0_scaffold = l0_sub.add_parser("scaffold", help="Create required L0 artifact templates")
    l0_scaffold.add_argument("--overwrite", action="store_true", default=False)
    l0_set = l0_sub.add_parser("set-prereq", help="Mark a prerequisite gate pass/fail")
    l0_set.add_argument("name", type=str, help="data_quality | deterministic_rules | mathematical_filters")
    l0_set.add_argument("--status", choices=["pass", "fail"], required=True)
    l0_set.add_argument("--evidence", type=str, default="")

    # loop
    loop_parser = subparsers.add_parser("loop", help="Run improvement loop")
    loop_parser.add_argument("task_id", type=str)
    loop_parser.add_argument("--once", action="store_true", default=False)
    loop_parser.add_argument("--provider", type=str, default=None)
    loop_parser.add_argument("--dry-run", action="store_true", default=False,
                             help="Skip L0 gate check")

    # commit
    commit_parser = subparsers.add_parser("commit", help="Git commit + dashboard/pipeline sync")
    commit_parser.add_argument("message", type=str, help="Commit message")
    commit_parser.add_argument("--task-id", type=str, default=None,
                               help="GCC task id, e.g. GCC-0155")
    commit_parser.add_argument("--step-id", type=str, default=None,
                               help="Pipeline step id, e.g. S3")
    commit_parser.add_argument("--no-add", action="store_true", default=False,
                               help="Skip implicit 'git add -A'")
    commit_parser.add_argument("--no-verify", action="store_true", default=False,
                               help="Pass --no-verify to git commit")

    # ho
    ho_parser = subparsers.add_parser("ho", help="Handoff operations")
    ho_sub = ho_parser.add_subparsers(dest="ho_command")
    ho_create_parser = ho_sub.add_parser("create", help="Create handoff note")
    ho_create_parser.add_argument("--task-id", type=str, default=None,
                                  help="GCC task id, e.g. GCC-0155")
    ho_create_parser.add_argument("--step-id", type=str, default=None,
                                  help="Pipeline step id, e.g. S3")
    ho_create_parser.add_argument("--message", type=str, default="manual handoff",
                                  help="Optional handoff summary")

    # pipe
    pipe_parser = subparsers.add_parser("pipe", help="Pipeline management")
    pipe_sub = pipe_parser.add_subparsers(dest="pipe_command")

    task_parser = pipe_sub.add_parser("task", help="Create task")
    task_parser.add_argument("title", type=str)
    task_parser.add_argument("-k", "--key", required=True)
    task_parser.add_argument("-m", "--module", required=True)
    task_parser.add_argument("-p", "--priority", default="P1")

    pipe_sub.add_parser("list", help="List tasks")

    status_parser = pipe_sub.add_parser("status", help="Task status")
    status_parser.add_argument("task_id", type=str)

    # memory
    mem_parser = subparsers.add_parser("memory", help="Memory management")
    mem_sub = mem_parser.add_subparsers(dest="mem_command")
    mem_sub.add_parser("compact", help="Compact memory")
    export_parser = mem_sub.add_parser("export", help="Export state")
    export_parser.add_argument("--output", type=str, default=None)

    # health
    subparsers.add_parser("health", help="System health check")

    args = parser.parse_args()

    if args.command == "version":
        cmd_version(args)
    elif args.command == "setup":
        cmd_setup(args)
    elif args.command == "init":
        cmd_init(args)
    elif args.command == "l0":
        if args.l0_command == "show":
            cmd_l0_show(args)
        elif args.l0_command == "check":
            cmd_l0_check(args)
        elif args.l0_command == "scaffold":
            cmd_l0_scaffold(args)
        elif args.l0_command == "set-prereq":
            cmd_l0_set_prereq(args)
        else:
            l0_parser.print_help()
    elif args.command == "loop":
        cmd_loop(args)
    elif args.command == "commit":
        cmd_commit(args)
    elif args.command == "ho":
        if args.ho_command == "create":
            cmd_ho_create(args)
        else:
            ho_parser.print_help()
    elif args.command == "pipe":
        if args.pipe_command == "task":
            cmd_pipe_task(args)
        elif args.pipe_command == "list":
            cmd_pipe_list(args)
        elif args.pipe_command == "status":
            cmd_pipe_status(args)
        else:
            pipe_parser.print_help()
    elif args.command == "memory":
        if args.mem_command == "compact":
            cmd_memory_compact(args)
        elif args.mem_command == "export":
            cmd_memory_export(args)
        else:
            mem_parser.print_help()
    elif args.command == "health":
        cmd_health(args)
    else:
        _print_banner()
        parser.print_help()


if __name__ == "__main__":
    main()





