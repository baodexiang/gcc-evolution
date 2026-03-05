"""
改善项管理工具 v1.0

用法:
  python manage_improvements.py list                              # 列出所有活跃项
  python manage_improvements.py list --layer AUDIT                # 按层过滤
  python manage_improvements.py list --priority P0                # 按优先级过滤
  python manage_improvements.py list --status FOUND               # 按状态过滤
  python manage_improvements.py list --all                        # 包含已关闭

  python manage_improvements.py add --layer SYSTEM --priority P1 \
    --title "Module A 股票预选" --description "股票预选"           # 新增

  python manage_improvements.py update AUD-001 --status TESTING   # 更新状态
  python manage_improvements.py update AUD-001 --coded true       # 更新checklist
  python manage_improvements.py update AUD-001 --phase "Phase 2"  # 更新Phase

  python manage_improvements.py close AUD-001 --effect "逆向从5次降到0次"  # 关闭

  python manage_improvements.py stats                             # 统计摘要

  # GCC-EVO 对齐流程
  python manage_improvements.py gcc-bootstrap --align-stage        # 建立/对齐pipeline任务
  python manage_improvements.py gcc-status                         # 查看对齐状态
  python manage_improvements.py gcc-gate KEY-002 --auto-advance    # 执行gate并推进

  # KEY-000 辅助
  python manage_improvements.py sync-key000-res-status              # 同步KEY-000里RES摘要状态前缀
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime

try:
    from gcc_evolution.pipeline import TaskPipeline, PipelineStage
    _HAS_GCC_PIPELINE = True
except Exception:
    TaskPipeline = None
    PipelineStage = None
    _HAS_GCC_PIPELINE = False

IMPROVEMENTS_FILE = os.path.join("state", "improvements.json")
GCC_DIRS = [".GCC", ".gcc"]

VALID_LAYERS = ["SYSTEM", "TOOL", "AUDIT", "RESEARCH"]
VALID_STATUSES = ["FOUND", "ANALYZED", "IN_PROGRESS", "TESTING", "VERIFIED", "DEFERRED", "CLOSED"]
VALID_PRIORITIES = ["P0", "P1", "P2", "P3"]

STATUS_ICONS = {
    "FOUND": "?",
    "ANALYZED": "#",
    "IN_PROGRESS": ">",
    "TESTING": "T",
    "VERIFIED": "V",
    "DEFERRED": "D",
    "CLOSED": "X",
}

LAYER_PREFIXES = {"SYSTEM": "SYS", "TOOL": "TOOL", "AUDIT": "AUD", "RESEARCH": "RES"}

# --- ANSI colors ---
C_R = "\033[91m"
C_Y = "\033[93m"
C_G = "\033[92m"
C_C = "\033[96m"
C_W = "\033[97m"
C_0 = "\033[0m"
C_DIM = "\033[2m"

PRIORITY_COLORS = {"P0": C_R, "P1": C_Y, "P2": C_W, "P3": C_DIM}

STATUS_TO_GCC_STAGE = {
    "FOUND": "analyze",
    "ANALYZED": "design",
    "IN_PROGRESS": "implement",
    "TESTING": "test",
    "VERIFIED": "integrate",
    "DEFERRED": "suspended",
    "CLOSED": "done",
}


def load_improvements():
    if not os.path.exists(IMPROVEMENTS_FILE):
        return {"version": 1, "last_updated": "", "items": []}
    with open(IMPROVEMENTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_improvements(data):
    data["last_updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    with open(IMPROVEMENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def next_id(data, layer):
    prefix = LAYER_PREFIXES[layer]
    existing = [
        int(i["id"].split("-")[1])
        for i in data["items"]
        if i["id"].startswith(prefix + "-")
    ]
    return max(existing, default=0) + 1


def today():
    return datetime.now().strftime("%Y-%m-%d")


def now_iso():
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _run_git(args):
    try:
        res = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
            errors="ignore",
        )
        if res.returncode == 0:
            return res.stdout.strip()
    except Exception:
        pass
    return ""


def _compute_improvement_snapshot(data):
    items = data.get("items", [])
    active = [i for i in items if i.get("status") != "CLOSED"]

    by_status = {}
    for i in active:
        s = i.get("status", "UNKNOWN")
        by_status[s] = by_status.get(s, 0) + 1

    by_layer = {}
    for layer in VALID_LAYERS:
        li = [i for i in items if i.get("layer") == layer]
        closed = len([x for x in li if x.get("status") == "CLOSED"])
        by_layer[layer] = {
            "total": len(li),
            "closed": closed,
            "active": len(li) - closed,
        }

    return {
        "total": len(items),
        "active": len(active),
        "by_status": by_status,
        "by_layer": by_layer,
    }


def _require_gcc_pipeline():
    if _HAS_GCC_PIPELINE:
        return True
    print("  错误: gcc_evolution.pipeline 不可用，无法执行gcc对齐流程")
    print("  提示: 确认 gcc_evolution/ 目录存在且当前Python环境可导入")
    return False


def _new_pipeline():
    if not _require_gcc_pipeline() or TaskPipeline is None:
        return None
    return TaskPipeline()


def _priority_of(item):
    p = str(item.get("priority", "P2")).upper()
    return p if p in VALID_PRIORITIES else "P2"


def _target_stage_of(item):
    st = str(item.get("status", "FOUND")).upper()
    return STATUS_TO_GCC_STAGE.get(st, "analyze")


def _task_stage_name(task):
    s = getattr(task, "stage", None)
    v = getattr(s, "value", None)
    if v is not None:
        return str(v)
    return str(s or "pending")


def _advance_to_stage(pipeline, task, target_stage):
    if target_stage == "suspended":
        task.suspend("mapped from DEFERRED")
        pipeline._save()
        return

    # 从pending开始逐步推进，保留stage_history
    safe_guard = 16
    while safe_guard > 0:
        safe_guard -= 1
        cur = _task_stage_name(task)
        if cur in (target_stage, "done", "failed", "suspended"):
            break
        nxt = pipeline.advance(task.task_id)
        if nxt is None:
            break
        task = pipeline.get_task(task.task_id) or task


def _sync_state_yaml(path, branch, commit_id):
    if not os.path.exists(path):
        return False

    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    found_branch = False
    found_commit = False
    new_lines = []

    for line in lines:
        if line.startswith("current_branch:"):
            new_lines.append(f"current_branch: {branch}\n")
            found_branch = True
        elif line.startswith("last_commit_id:"):
            new_lines.append(f"last_commit_id: {commit_id}\n")
            found_commit = True
        else:
            new_lines.append(line)

    if not found_branch:
        new_lines.append(f"current_branch: {branch}\n")
    if not found_commit:
        new_lines.append(f"last_commit_id: {commit_id}\n")

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    return True


def _sync_graph_json(path, branch, commit_id, summary, agent, snapshot):
    if not os.path.exists(path):
        return False

    with open(path, "r", encoding="utf-8") as f:
        graph = json.load(f)

    commits = graph.setdefault("commits", {})
    branches = graph.setdefault("branches", {})
    old_head = graph.get("head")

    if commit_id not in commits:
        commits[commit_id] = {
            "id": commit_id,
            "summary": summary,
            "timestamp": now_iso(),
            "branch": branch,
            "parent": old_head,
            "parent2": None,
            "is_merge": False,
            "files_changed": ["state/improvements.json"],
            "agent": agent,
            "meta": {
                "improvements": snapshot,
            },
        }

    if branch not in branches:
        branches[branch] = {
            "head": commit_id,
            "base_commit": old_head,
            "created": now_iso(),
            "status": "active",
        }
    else:
        branches[branch]["head"] = commit_id
        branches[branch]["status"] = "active"

    graph["current_branch"] = branch
    graph["head"] = commit_id

    with open(path, "w", encoding="utf-8") as f:
        json.dump(graph, f, indent=2, ensure_ascii=False)

    return True


def checklist_bar(cl):
    steps = ["analyzed", "coded", "tested", "verified"]
    filled = sum(1 for s in steps if cl.get(s, False))
    bar = "#" * filled + "." * (4 - filled)
    labels = [s for s in steps if cl.get(s, False)]
    label = labels[-1] if labels else "found"
    return f"[{bar}] {label}"


# ============================================================
# Commands
# ============================================================

def cmd_list(args):
    data = load_improvements()
    items = data["items"]

    # Filters
    if args.layer:
        items = [i for i in items if i["layer"] == args.layer.upper()]
    if args.priority:
        items = [i for i in items if i["priority"] == args.priority.upper()]
    if args.status:
        items = [i for i in items if i["status"] == args.status.upper()]
    if not args.all:
        items = [i for i in items if i["status"] != "CLOSED"]

    # Sort: P0 first, then by status flow
    status_order = {s: i for i, s in enumerate(VALID_STATUSES)}
    priority_order = {p: i for i, p in enumerate(VALID_PRIORITIES)}
    items.sort(key=lambda x: (priority_order.get(x["priority"], 9), status_order.get(x["status"], 9)))

    if not items:
        print("  (无匹配项)")
        return

    # Header
    print(f"\n {'ID':<9} {'P':>2}  {'层':<7} {'状态':<12} {'进度':<20} {'标题'}")
    print(" " + "-" * 90)

    for item in items:
        icon = STATUS_ICONS.get(item["status"], "?")
        pcol = PRIORITY_COLORS.get(item["priority"], "")
        bar = checklist_bar(item.get("checklist", {}))

        scol = C_G if item["status"] in ("VERIFIED", "CLOSED") else ""
        scol = C_C if item["status"] == "IN_PROGRESS" else scol
        scol = C_Y if item["status"] == "FOUND" else scol

        status_str = f"{scol}{icon} {item['status']:<10}{C_0}"
        title = item["title"]
        if item.get("phase"):
            title += f" [{item['phase']}]"

        print(f" {item['id']:<9} {pcol}{item['priority']:>2}{C_0}  {item['layer']:<7} {status_str} {bar:<20} {title}")

    total = len(items)
    by_status = {}
    for i in items:
        by_status[i["status"]] = by_status.get(i["status"], 0) + 1
    print(" " + "-" * 90)
    parts = [f"{k}:{v}" for k, v in by_status.items()]
    print(f" 共 {total} 项 | {' | '.join(parts)}")
    print()


def cmd_add(args):
    data = load_improvements()
    layer = args.layer.upper()
    if layer not in VALID_LAYERS:
        print(f"  错误: layer必须是 {VALID_LAYERS}")
        return

    priority = args.priority.upper()
    if priority not in VALID_PRIORITIES:
        print(f"  错误: priority必须是 {VALID_PRIORITIES}")
        return

    new_id = f"{LAYER_PREFIXES[layer]}-{next_id(data, layer):03d}"
    item = {
        "id": new_id,
        "layer": layer,
        "priority": priority,
        "title": args.title,
        "status": "FOUND",
        "phase": args.phase,
        "found_date": today(),
        "updated_date": today(),
        "closed_date": None,
        "source": args.source or "",
        "description": args.description or "",
        "files": args.files.split(",") if args.files else [],
        "checklist": {"analyzed": False, "coded": False, "tested": False, "verified": False},
        "effect": None,
    }
    data["items"].append(item)
    save_improvements(data)
    print(f"  {C_G}+{C_0} 已添加: {new_id} {args.title} ({layer}/{priority})")


def cmd_update(args):
    data = load_improvements()
    item = next((i for i in data["items"] if i["id"] == args.id.upper()), None)
    if not item:
        print(f"  错误: 找不到 {args.id}")
        return

    changes = []
    if args.status:
        s = args.status.upper()
        if s not in VALID_STATUSES:
            print(f"  错误: status必须是 {VALID_STATUSES}")
            return
        item["status"] = s
        changes.append(f"status→{s}")
    if args.phase is not None:
        item["phase"] = args.phase
        changes.append(f"phase→{args.phase}")

    # Checklist updates
    for key in ["analyzed", "coded", "tested", "verified"]:
        val = getattr(args, key, None)
        if val is not None:
            item["checklist"][key] = val.lower() in ("true", "1", "yes")
            changes.append(f"{key}→{item['checklist'][key]}")

    if args.effect is not None:
        item["effect"] = args.effect
        changes.append(f"effect→{args.effect}")

    item["updated_date"] = today()
    save_improvements(data)
    print(f"  {C_C}~{C_0} {args.id}: {', '.join(changes)}")


def cmd_close(args):
    data = load_improvements()
    item = next((i for i in data["items"] if i["id"] == args.id.upper()), None)
    if not item:
        print(f"  错误: 找不到 {args.id}")
        return

    item["status"] = "CLOSED"
    item["closed_date"] = today()
    item["updated_date"] = today()
    if "checklist" in item:
        for k in item["checklist"]:
            item["checklist"][k] = True
    if args.effect:
        item["effect"] = args.effect

    save_improvements(data)
    print(f"  {C_G}X{C_0} 已关闭: {args.id} {item['title']}")
    if args.effect:
        print(f"    效果: {args.effect}")


def cmd_stats(args):
    data = load_improvements()
    items = data["items"]

    print(f"\n 改善追踪统计 | 更新: {data.get('last_updated', 'N/A')}")
    print(" " + "=" * 70)

    # Per-layer stats
    for layer in VALID_LAYERS:
        li = [i for i in items if i["layer"] == layer]
        total = len(li)
        closed = len([i for i in li if i["status"] == "CLOSED"])
        active = total - closed
        pct = (closed / total * 100) if total > 0 else 0

        bar_len = 20
        filled = int(pct / 100 * bar_len)
        bar = "#" * filled + "." * (bar_len - filled)

        print(f"  {layer:<8} [{bar}] {pct:5.1f}%  ({closed}/{total}完成, {active}活跃)")

    print(" " + "-" * 70)

    # Priority distribution (active only)
    active = [i for i in items if i["status"] != "CLOSED"]
    for p in VALID_PRIORITIES:
        pi = [i for i in active if i["priority"] == p]
        if pi:
            pcol = PRIORITY_COLORS.get(p, "")
            statuses = {}
            for i in pi:
                statuses[i["status"]] = statuses.get(i["status"], 0) + 1
            parts = [f"{STATUS_ICONS[s]}{v}" for s, v in statuses.items()]
            print(f"  {pcol}{p}{C_0}: {len(pi)}项 ({' '.join(parts)})")

    # Stale check (>7 days since update)
    from datetime import datetime as dt
    now = dt.now()
    stale = []
    for i in active:
        try:
            _udate = i.get("updated_date") or i.get("found_date")
            if _udate:
                updated = dt.strptime(_udate, "%Y-%m-%d")
                if (now - updated).days > 7:
                    stale.append(i)
        except (ValueError, TypeError):
            pass

    if stale:
        print(f"\n  {C_R}! 超过7天未更新:{C_0}")
        for i in stale:
            print(f"    {i['id']} {i['title']} (最后更新: {i['updated_date']})")

    # Weekly closed
    week_closed = []
    for i in items:
        if i["status"] == "CLOSED" and i.get("closed_date"):
            try:
                cd = dt.strptime(i["closed_date"], "%Y-%m-%d")
                if (now - cd).days <= 7:
                    week_closed.append(i)
            except (ValueError, TypeError):
                pass

    print(f"\n  本周关闭: {len(week_closed)}项")
    for i in week_closed:
        eff = f" → {i['effect']}" if i.get("effect") else ""
        print(f"    {C_G}X{C_0} {i['id']} {i['title']}{eff}")

    print()


def cmd_sync_gcc(args):
    data = load_improvements()
    snapshot = _compute_improvement_snapshot(data)

    git_branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    git_head = _run_git(["rev-parse", "--short", "HEAD"])

    branch = args.branch or git_branch or "main"
    commit_id = args.commit or git_head or "unknown"
    summary = args.summary or f"improvement sync ({snapshot['active']} active)"
    agent = args.agent or "manage_improvements.py"

    touched = []
    for d in GCC_DIRS:
        if not os.path.isdir(d):
            continue

        state_path = os.path.join(d, ".gcc_state.yaml")
        graph_path = os.path.join(d, "graph.json")

        ok_state = _sync_state_yaml(state_path, branch, commit_id)
        ok_graph = _sync_graph_json(graph_path, branch, commit_id, summary, agent, snapshot)
        if ok_state or ok_graph:
            touched.append(d)

    if not touched:
        print("  ! 未找到可同步目录(.GCC/.gcc)")
        return

    status_str = ", ".join([f"{k}:{v}" for k, v in snapshot["by_status"].items()]) or "none"
    print(f"  {C_G}+{C_0} GCC同步完成: {', '.join(touched)}")
    print(f"    branch={branch} head={commit_id}")
    print(f"    active={snapshot['active']}/{snapshot['total']} | {status_str}")


def cmd_gcc_bootstrap(args):
    pipeline = _new_pipeline()
    if pipeline is None:
        return

    data = load_improvements()
    items = data.get("items", [])
    if not args.all:
        items = [i for i in items if i.get("status") != "CLOSED"]

    created = 0
    linked = 0

    for item in items:
        existing_id = item.get("gcc_task_id", "")
        task = pipeline.get_task(existing_id) if existing_id else None

        if task is None:
            task = pipeline.create_task(
                title=f"{item.get('id', 'UNK')} {item.get('title', '')}",
                description=item.get("description", ""),
                priority=_priority_of(item),
                requirements=item.get("description", ""),
                key=item.get("id", ""),
                dependencies=[],
            )
            created += 1

        item["gcc_task_id"] = task.task_id
        item["gcc_stage"] = _task_stage_name(task)

        if args.align_stage:
            target = _target_stage_of(item)
            _advance_to_stage(pipeline, task, target)
            latest = pipeline.get_task(task.task_id) or task
            item["gcc_stage"] = _task_stage_name(latest)

        linked += 1

    save_improvements(data)
    print(f"  {C_G}+{C_0} gcc bootstrap完成: linked={linked}, created={created}")
    if args.align_stage:
        print("    已按improvement status对齐到gcc stage")


def cmd_gcc_gate(args):
    pipeline = _new_pipeline()
    if pipeline is None:
        return

    data = load_improvements()
    item = next((i for i in data.get("items", []) if i.get("id") == args.id.upper()), None)
    if not item:
        print(f"  错误: 找不到 {args.id}")
        return

    task_id = item.get("gcc_task_id", "")
    if not task_id:
        print(f"  错误: {args.id} 尚未绑定 gcc_task_id，请先执行 gcc-bootstrap")
        return

    task = pipeline.get_task(task_id)
    if not task:
        print(f"  错误: pipeline中不存在任务 {task_id}")
        return

    check_results = None
    if args.checks_json:
        try:
            check_results = json.loads(args.checks_json)
            if not isinstance(check_results, list):
                raise ValueError("checks_json必须是JSON数组")
        except Exception as e:
            print(f"  错误: checks_json解析失败: {e}")
            return

    gate = pipeline.run_gate(task_id, check_results=check_results)
    item["gcc_stage"] = _task_stage_name(pipeline.get_task(task_id) or task)
    item["gcc_last_gate"] = gate.result.value
    item["gcc_last_gate_pass_rate"] = round(gate.pass_rate, 2)
    item["gcc_last_gate_iteration"] = gate.iteration

    if args.auto_advance and gate.result.value == "passed":
        pipeline.advance(task_id)
        latest = pipeline.get_task(task_id)
        item["gcc_stage"] = _task_stage_name(latest)

    save_improvements(data)
    print(
        f"  {C_C}~{C_0} {args.id} gate={gate.result.value} "
        f"pass_rate={gate.pass_rate:.2f} iter={gate.iteration} stage={item.get('gcc_stage','?')}"
    )


def cmd_gcc_status(args):
    pipeline = _new_pipeline()
    if pipeline is None:
        return

    data = load_improvements()
    items = data.get("items", [])
    if args.id:
        items = [i for i in items if i.get("id") == args.id.upper()]

    if not args.all:
        items = [i for i in items if i.get("status") != "CLOSED"]

    print("\n GCC对齐状态")
    print(" " + "-" * 92)
    print(f" {'ID':<9} {'Status':<12} {'Task':<10} {'Stage':<12} {'Gate':<10} {'Iter':<5} {'Title'}")
    print(" " + "-" * 92)

    count = 0
    for item in items:
        task_id = item.get("gcc_task_id", "-")
        stage = "-"
        if task_id != "-":
            task = pipeline.get_task(task_id)
            if task:
                stage = _task_stage_name(task)
        gate = item.get("gcc_last_gate", "-")
        iteration = item.get("gcc_last_gate_iteration", "-")
        print(
            f" {item.get('id','?'):<9} {item.get('status','?'):<12} {task_id:<10} "
            f"{stage:<12} {gate:<10} {str(iteration):<5} {item.get('title','')}"
        )
        count += 1

    if count == 0:
        print("  (无匹配项)")
    print(" " + "-" * 92)


def cmd_sync_key000_res_status(args):
    data = load_improvements()
    items = data.get("items", [])

    key000 = next((x for x in items if x.get("id") == "KEY-000"), None)
    if key000 is None:
        print("  错误: 未找到 KEY-000")
        return

    summary = key000.get("summary")
    if not isinstance(summary, dict):
        print("  错误: KEY-000.summary 不是对象")
        return

    res_items = [x for x in items if str(x.get("id", "")).startswith("RES-")]
    if not res_items:
        print("  提示: 未找到任何 RES-* 条目")
        return

    def _res_num(item):
        try:
            return int(str(item.get("id", "RES-999")).split("-")[1])
        except Exception:
            return 999

    changed = []
    for item in sorted(res_items, key=_res_num):
        rid = str(item.get("id", "")).upper()
        status = str(item.get("status", "UNKNOWN")).upper()
        existing = str(summary.get(rid, "")).strip()
        plain = existing
        if existing.startswith("[") and "]" in existing:
            plain = existing.split("]", 1)[1].strip()

        if plain:
            updated = f"[{status}] {plain}"
        else:
            title = str(item.get("title", "")).strip()
            updated = f"[{status}] {title}" if title else f"[{status}]"

        if summary.get(rid) != updated:
            summary[rid] = updated
            changed.append(rid)

    key000["summary"] = summary

    if args.dry_run:
        if changed:
            print(f"  dry-run: 将更新 {len(changed)} 项 -> {', '.join(changed)}")
        else:
            print("  dry-run: 无需更新")
        return

    if not changed:
        print("  KEY-000 RES状态摘要已是最新，无需更新")
        return

    save_improvements(data)
    print(f"  已同步 KEY-000 RES状态摘要: {len(changed)} 项")
    print(f"  更新项: {', '.join(changed)}")


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="改善项管理工具")
    sub = parser.add_subparsers(dest="command")

    # list
    p_list = sub.add_parser("list", help="列出改善项")
    p_list.add_argument("--layer", help="按层过滤: SYSTEM/TOOL/AUDIT/RESEARCH")
    p_list.add_argument("--priority", help="按优先级: P0/P1/P2/P3")
    p_list.add_argument("--status", help="按状态: FOUND/ANALYZED/IN_PROGRESS/TESTING/VERIFIED/CLOSED")
    p_list.add_argument("--all", action="store_true", help="包含已关闭项")

    # add
    p_add = sub.add_parser("add", help="新增改善项")
    p_add.add_argument("--layer", required=True, help="SYSTEM/TOOL/AUDIT/RESEARCH")
    p_add.add_argument("--priority", required=True, help="P0/P1/P2/P3")
    p_add.add_argument("--title", required=True, help="标题")
    p_add.add_argument("--description", help="描述")
    p_add.add_argument("--source", help="来源")
    p_add.add_argument("--phase", help="Phase(SYSTEM层)")
    p_add.add_argument("--files", help="相关文件(逗号分隔)")

    # update
    p_upd = sub.add_parser("update", help="更新改善项")
    p_upd.add_argument("id", help="改善项ID")
    p_upd.add_argument("--status", help="新状态")
    p_upd.add_argument("--phase", help="新Phase")
    p_upd.add_argument("--analyzed", help="true/false")
    p_upd.add_argument("--coded", help="true/false")
    p_upd.add_argument("--tested", help="true/false")
    p_upd.add_argument("--verified", help="true/false")
    p_upd.add_argument("--effect", help="效果描述")

    # close
    p_close = sub.add_parser("close", help="关闭改善项")
    p_close.add_argument("id", help="改善项ID")
    p_close.add_argument("--effect", help="效果描述")

    # stats
    sub.add_parser("stats", help="统计摘要")

    # sync-gcc
    p_sync = sub.add_parser("sync-gcc", help="同步improvements摘要到.GCC/.gcc元数据")
    p_sync.add_argument("--branch", help="覆盖分支名(默认取git当前分支)")
    p_sync.add_argument("--commit", help="覆盖commit id(默认取git HEAD短哈希)")
    p_sync.add_argument("--summary", help="graph提交摘要")
    p_sync.add_argument("--agent", default="manage_improvements.py", help="记录到graph的agent字段")

    # gcc-bootstrap
    p_boot = sub.add_parser("gcc-bootstrap", help="按gcc-evo要求为improvements建立/对齐pipeline任务")
    p_boot.add_argument("--all", action="store_true", help="包含已关闭项")
    p_boot.add_argument("--align-stage", action="store_true", help="按status自动推进stage")

    # gcc-gate
    p_gate = sub.add_parser("gcc-gate", help="对指定改善项执行gcc gate校验")
    p_gate.add_argument("id", help="改善项ID，例如 KEY-002 或 SYS-001")
    p_gate.add_argument("--checks-json", help="gate检查JSON数组，默认按模板全通过")
    p_gate.add_argument("--auto-advance", action="store_true", help="gate通过后自动推进到下一stage")

    # gcc-status
    p_gs = sub.add_parser("gcc-status", help="查看improvements与gcc pipeline对齐状态")
    p_gs.add_argument("--id", help="仅查看指定改善项")
    p_gs.add_argument("--all", action="store_true", help="包含已关闭项")

    # sync-key000-res-status
    p_sync_res = sub.add_parser("sync-key000-res-status", help="同步KEY-000中RES项的状态前缀")
    p_sync_res.add_argument("--dry-run", action="store_true", help="仅预览变更，不写文件")

    args = parser.parse_args()

    if args.command == "list":
        cmd_list(args)
    elif args.command == "add":
        cmd_add(args)
    elif args.command == "update":
        cmd_update(args)
    elif args.command == "close":
        cmd_close(args)
    elif args.command == "stats":
        cmd_stats(args)
    elif args.command == "sync-gcc":
        cmd_sync_gcc(args)
    elif args.command == "gcc-bootstrap":
        cmd_gcc_bootstrap(args)
    elif args.command == "gcc-gate":
        cmd_gcc_gate(args)
    elif args.command == "gcc-status":
        cmd_gcc_status(args)
    elif args.command == "sync-key000-res-status":
        cmd_sync_key000_res_status(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
