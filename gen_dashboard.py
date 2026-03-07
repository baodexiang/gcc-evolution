"""
GCC Dashboard 生成器 v4.99
读取 .GCC/gcc.db (improvements/cards/tasks) + tasks.jsonl + handoffs + pipeline
python gen_dashboard.py          # 生成并打开浏览器
python gen_dashboard.py --quiet  # 生成但不打开浏览器 (供 hook/自动化调用)
"""
import json, pathlib, webbrowser, sys, sqlite3, hashlib

SCRIPT_DIR = pathlib.Path(__file__).parent
TEMPLATE = SCRIPT_DIR / ".GCC" / "gcc_dashboard.html"

# ── Dashboard 格式锁 (2026-03-07 确认为最佳格式) ──────────────────────────
# 修改模板前必须经用户明确同意，确认后更新此 hash
TEMPLATE_HASH_LOCK = "666ce27d74a7d0befc6436efefac5d8dd1836c19eecccf26d73559c467fc6674"

if not TEMPLATE.exists():
    print(f"错误：找不到 {TEMPLATE}")
    sys.exit(1)

_template_bytes = TEMPLATE.read_bytes()
_actual_hash = hashlib.sha256(_template_bytes).hexdigest()
if _actual_hash != TEMPLATE_HASH_LOCK:
    print(f"⚠️  [DASHBOARD FORMAT LOCK] 模板 hash 不匹配!")
    print(f"   期望: {TEMPLATE_HASH_LOCK}")
    print(f"   实际: {_actual_hash}")
    print(f"   模板已被修改。如已确认变更，请更新 gen_dashboard.py 中的 TEMPLATE_HASH_LOCK。")

print(f"模板: {TEMPLATE}")
html = _template_bytes.decode("utf-8")

GCC_DIR = pathlib.Path(".GCC")
HANDOFF_DIR = GCC_DIR / "handoffs"
DB_PATH = GCC_DIR / "gcc.db"

inject_lines = []
loaded = []

# ══ IMPROVEMENTS + CARDS from gcc.db ═══════════════════════
all_improvements = []
all_cards = []

if DB_PATH.exists() and DB_PATH.stat().st_size > 0:
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        # improvements
        for r in conn.execute("SELECT * FROM improvements ORDER BY id"):
            row = dict(r)
            obs = []
            try: obs = json.loads(row.get("observations_json") or "[]")
            except: pass
            all_improvements.append({
                "id": row["id"],
                "parent_key": row.get("parent_key") or "",
                "title": row.get("title") or row["id"],
                "status": row.get("status") or "FOUND",
                "phase_text": row.get("phase_text") or "",
                "observations": obs,
                "note": row.get("note") or "",
                "item_type": row.get("item_type") or "",
            })
        # cards
        for r in conn.execute("SELECT * FROM cards ORDER BY id"):
            row = dict(r)
            phases = []
            try: phases = json.loads(row.get("phases_json") or "[]")
            except: pass
            all_cards.append({
                "id": row["id"],
                "key_id": row.get("key_id") or "",
                "title": row.get("title") or row["id"],
                "card_type": row.get("card_type") or "knowledge",
                "layer_priority": row.get("layer_priority") or 2,
                "content": (row.get("content_md") or "")[:3000],
                "phases": phases,
                "why_text": (row.get("why_text") or "")[:500],
                "lessons": (row.get("lessons_text") or "")[:500],
            })
        conn.close()
        loaded.append(f"gcc.db ({len(all_improvements)} improvements, {len(all_cards)} cards)")
    except Exception as e:
        print(f"  gcc.db读取失败: {e}")

# Fallback: improvements.json
if not all_improvements:
    imp = GCC_DIR / "improvements.json"
    if imp.exists():
        try:
            d = json.loads(imp.read_text(encoding="utf-8", errors="ignore"))
            inject_lines.append(f"DATA.improvements = Array.isArray({json.dumps(d, ensure_ascii=False)}) ? {json.dumps(d, ensure_ascii=False)} : flattenImprovements({json.dumps(d, ensure_ascii=False)});")
            inject_lines.append("DATA.cards = extractCards(DATA.improvements);")
            loaded.append("improvements.json (fallback)")
        except Exception as e:
            print(f"  skip improvements.json: {e}")

## Scan .GCC/skill/cards/ for structured JSON knowledge cards
card_dir = GCC_DIR / "skill" / "cards"
if card_dir.exists():
    seen_ids = {c["id"] for c in all_cards}
    for jf in sorted(card_dir.rglob("*.json")):
        try:
            d = json.loads(jf.read_text(encoding="utf-8", errors="ignore"))
            cid = d.get("id") or jf.stem
            if cid in seen_ids:
                continue
            seen_ids.add(cid)
            # Extract category from parent directory name
            cat = jf.parent.name if jf.parent != card_dir else ""
            all_cards.append({
                "id": cid,
                "key_id": cat,
                "title": f"{cat} — {d.get('title', jf.stem)}" if cat else d.get("title", jf.stem),
                "card_type": "knowledge",
                "layer_priority": 2,
            })
        except Exception:
            pass

if all_improvements:
    inject_lines.append(f"DATA.improvements = {json.dumps(all_improvements, ensure_ascii=False)};")
if all_cards:
    inject_lines.append(f"DATA.cards = {json.dumps(all_cards, ensure_ascii=False)};")

# ══ TASKS - collect from all sources ══════════════════════
all_tasks = []
seen = set()

def _norm_priority(p):
    return {'normal':'average','high':'high','low':'low'}.get((p or 'average').lower(), 'average')

def add_task(t):
    if not isinstance(t, dict): return
    k = t.get('task_id') or t.get('id') or t.get('title') or t.get('description') or str(id(t))
    has_steps = t.get('steps') and isinstance(t.get('steps'), list) and len(t['steps']) > 0
    if k in seen:
        if has_steps:
            # pipeline task with steps overrides earlier shallow entry
            all_tasks[:] = [x for x in all_tasks if x.get('task_id') != k]
        else:
            return
    seen.add(k)
    entry = {
        'task_id': t.get('task_id') or t.get('id', ''),
        'title': t.get('title') or t.get('description') or '未命名',
        'status': t.get('status', 'pending'),
        'priority': _norm_priority(t.get('priority')),
        'key_id': t.get('key_id') or t.get('key') or t.get('anchor_key', ''),
        'updated_at': (t.get('updated_at') or t.get('created_at') or '')[:10],
        'current_step': (t.get('current_step') or t.get('instructions') or t.get('context') or '')[:100],
        'source': t.get('source', ''),
        'handoff_id': t.get('handoff_id', ''),
        'progress': t.get('progress', ''),
        'module': t.get('module', ''),
        'stage': t.get('stage', ''),
        'description': (t.get('description') or '')[:200],
    }
    # pipeline tasks: preserve steps for dashboard sub-task rendering
    raw_steps = t.get('steps')
    if raw_steps and isinstance(raw_steps, list):
        entry['steps'] = [
            {'id': s.get('id',''), 'title': s.get('title') or s.get('step',''),
             'status': s.get('status','pending'), 'note': (s.get('note') or '')[:120]}
            for s in raw_steps if isinstance(s, dict)
        ]
    all_tasks.append(entry)

# tasks.jsonl
tj = GCC_DIR / "tasks.jsonl"
if tj.exists():
    for line in tj.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.strip():
            try: add_task(json.loads(line))
            except: pass
    loaded.append(f"tasks.jsonl")

# handoffs
ho_sessions = []
if HANDOFF_DIR.exists():
    ho_count = 0
    for hf in sorted(HANDOFF_DIR.glob("HO_*.json"), reverse=True)[:30]:
        try:
            d = json.loads(hf.read_text(encoding="utf-8", errors="ignore"))
            for t in d.get("tasks", []):
                if isinstance(t, dict):
                    t["handoff_id"] = d.get("handoff_id", hf.stem)
                    t["key_id"] = d.get("key", "")
                    t["updated_at"] = (d.get("created_at") or "")[:10]
                    t["source"] = "handoff"
                    add_task(t)
                    ho_count += 1
            ho_sessions.append({
                "handoff_id": d.get("handoff_id", hf.stem),
                "created_at": d.get("created_at", ""),
                "key": d.get("key", ""),
                "changes_summary": d.get("upstream", {}).get("changes_summary", ""),
                "task_count": len(d.get("tasks", [])),
                "done_count": sum(1 for t in d.get("tasks", []) if isinstance(t, dict) and t.get("status") in ("completed","done")),
            })
        except Exception as e:
            print(f"  skip {hf.name}: {e}")
    if ho_count: loaded.append(f"handoffs/ ({ho_count} tasks)")

# pipeline
pipe = GCC_DIR / "pipeline" / "tasks.json"
if pipe.exists():
    try:
        pd = json.loads(pipe.read_text(encoding="utf-8", errors="ignore"))
        if isinstance(pd, list):
            pt = pd
        elif isinstance(pd, dict) and "tasks" in pd:
            pt = pd["tasks"]
        elif isinstance(pd, dict):
            pt = list(pd.values())
        else:
            pt = []
        _stage_map = {'done':'completed','implement':'running','test':'running',
                      'integrate':'running','analyze':'running','design':'running',
                      'pending':'pending','suspended':'paused'}
        pipe_count = 0
        for t in pt:
            if isinstance(t, dict):
                t.setdefault("source", "pipeline")
                if "stage" in t and "status" not in t:
                    t["status"] = _stage_map.get(t["stage"], "pending")
                add_task(t)
                pipe_count += 1
        loaded.append(f"pipeline/tasks.json ({pipe_count})")
    except: pass

# ══ PIPELINE RAW (for tree view) ═══════════════════════════
pipeline_raw = []
if pipe.exists():
    try:
        pd2 = json.loads(pipe.read_text(encoding="utf-8", errors="ignore"))
        raw_tasks = pd2.get("tasks", []) if isinstance(pd2, dict) else pd2
        for t in raw_tasks:
            if not isinstance(t, dict): continue
            pipeline_raw.append({
                "task_id": t.get("task_id", ""),
                "title": t.get("title", ""),
                "description": (t.get("description") or "")[:200],
                "priority": t.get("priority", "P2"),
                "stage": t.get("stage", "pending"),
                "key": t.get("key", ""),
                "module": t.get("module", ""),
                "created_at": (t.get("created_at") or "")[:10],
                "updated_at": (t.get("updated_at") or "")[:10],
                "gate_results": [
                    {"stage": g.get("stage",""), "result": g.get("result",""), "pass_rate": g.get("pass_rate",0)}
                    for g in (t.get("gate_results") or [])
                ],
            })
    except: pass

if pipeline_raw:
    inject_lines.append(f"DATA.pipeline = {json.dumps(pipeline_raw, ensure_ascii=False)};")

if all_tasks:
    inject_lines.append(f"DATA.tasks = {json.dumps(all_tasks, ensure_ascii=False)};")

if ho_sessions:
    inject_lines.append(f"DATA.sessions = {json.dumps(ho_sessions, ensure_ascii=False)};")

# skillbank / suggestions
for key, fname in [("skills","skillbank.jsonl"),("suggestions","suggestions.jsonl")]:
    fp = GCC_DIR / fname
    if not fp.exists():
        fp = pathlib.Path("gcc") / fname
    if fp.exists():
        rows = []
        for line in fp.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip():
                try: rows.append(json.loads(line))
                except: pass
        if rows:
            inject_lines.append(f"DATA.{key} = {json.dumps(rows, ensure_ascii=False)};")
            loaded.append(fname)

# ══ STATE 准确率数据 (⑦-⑫) ═════════════════════════════
STATE_DIR = pathlib.Path("state")

def _load_state_json(filename, data_key, label):
    fp = STATE_DIR / filename
    if not fp.exists(): return
    try:
        raw = json.loads(fp.read_text(encoding="utf-8"))
        inject_lines.append(f"DATA.{data_key} = {json.dumps(raw, ensure_ascii=False)};")
        loaded.append(label)
    except Exception:
        pass

# ⑦ GCC-0171: Vision Filter 准确率
_vf_path = STATE_DIR / "vision_filter_accuracy.json"
if _vf_path.exists():
    try:
        _vf_raw = json.loads(_vf_path.read_text(encoding="utf-8"))
        _vf_dash = {
            "last_review": _vf_raw.get("last_3day_review", 0),
            "pending_count": sum(1 for e in _vf_raw.get("events", []) if e.get("result") == "pending"),
            "total_events": len(_vf_raw.get("events", [])),
            "symbols": _vf_raw.get("accuracy", {}),
        }
        inject_lines.append(f"DATA.vf_accuracy = {json.dumps(_vf_dash, ensure_ascii=False)};")
        loaded.append(f"vf_accuracy: {len(_vf_dash['symbols'])} symbols")
    except Exception:
        pass

# ⑧ GCC-0172: BrooksVision 形态回测准确率
_load_state_json("bv_signal_accuracy.json", "bv_accuracy", "bv_accuracy")

# ⑨ GCC-0173: MACD背离回测准确率
_load_state_json("macd_signal_accuracy.json", "macd_accuracy", "macd_accuracy")

# ⑩ GCC-0174: 知识卡准确率
_load_state_json("card_signal_accuracy.json", "card_accuracy", "card_accuracy")

# ⑪ GCC-0197: 外挂信号准确率
_pa_path = STATE_DIR / "plugin_signal_accuracy.json"
if _pa_path.exists():
    try:
        _pa_raw = json.loads(_pa_path.read_text(encoding="utf-8"))
        _pa_acc = _pa_raw.get("accuracy", {})
        inject_lines.append(f"DATA.plugin_accuracy = {json.dumps(_pa_acc, ensure_ascii=False)};")
        loaded.append(f"plugin_accuracy: {len(_pa_acc)} sources")
    except Exception:
        pass

# ⑫ GCC-0197: 外挂Phase状态
_load_state_json("plugin_phase_state.json", "plugin_phases", "plugin_phases")

# inject + render
if inject_lines:
    inject_js = "\n".join(inject_lines) + "\n"
    if "// INIT\n" in html:
        html = html.replace("// INIT\n", inject_js + "render();\n// INIT\n")
    else:
        html = html.replace("</script>\n</body>", inject_js + "render();\n</script>\n</body>")

out = GCC_DIR / "dashboard.html"
out.write_text(html, encoding="utf-8")
print(f"已内嵌: {', '.join(loaded)}")
print(f"improvements: {len(all_improvements)}, cards: {len(all_cards)}, tasks: {len(all_tasks)}, sessions: {len(ho_sessions)}")
print(f"生成: {out}")
if "--quiet" not in sys.argv:
    webbrowser.open(out.resolve().as_uri())
