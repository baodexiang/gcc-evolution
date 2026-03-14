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
TEMPLATE_HASH_LOCK = "ef8971213d40bed4fd1b7d0495da0b171cfaa99f94e0ddef20a62fef2c5dfa38"

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
# 只显示真正的知识卡(JSON), gcc.db的任务步骤卡不计入
all_cards = []
card_dir = GCC_DIR / "skill" / "cards"
if card_dir.exists():
    seen_ids = set()
    for jf in sorted(card_dir.rglob("*.json")):
        try:
            d = json.loads(jf.read_text(encoding="utf-8", errors="ignore"))
            cid = d.get("id") or jf.stem
            if cid in seen_ids:
                continue
            seen_ids.add(cid)
            # Extract category from parent directory name
            cat = jf.parent.name if jf.parent != card_dir else ""
            _conf = d.get("confidence", 0)
            try: _conf = float(_conf)
            except: _conf = 0
            all_cards.append({
                "id": cid,
                "key_id": cat,
                "title": f"{cat} — {d.get('title', jf.stem)}" if cat else d.get("title", jf.stem),
                "card_type": "knowledge",
                "layer_priority": 2,
                "confidence": _conf,
            })
        except Exception:
            pass

if all_improvements:
    inject_lines.append(f"DATA.improvements = {json.dumps(all_improvements, ensure_ascii=False)};")
if all_cards:
    inject_lines.append(f"DATA.cards = {json.dumps(all_cards, ensure_ascii=False)};")

# 经验卡计数 + 排名数据
_exp_file = pathlib.Path("state") / "gcc_knn_experience.jsonl"
_exp_count, _exp_backfilled = 0, 0
_exp_all = []
if _exp_file.exists():
    for _line in _exp_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        if _line.strip():
            try:
                _e = json.loads(_line)
                _exp_count += 1
                if _e.get("outcome") is not None:
                    _exp_backfilled += 1
                _exp_all.append(_e)
            except: pass
inject_lines.append(f"DATA.experience_cards = {{total: {_exp_count}, backfilled: {_exp_backfilled}}};")

# 知识卡 Top10 / Bottom10 (按 confidence 排序)
_kc_ranked = []
for _c in all_cards:
    _conf = 0
    try: _conf = float(_c.get("confidence", 0) or 0)
    except: pass
    _kc_ranked.append({"title": _c.get("title", "")[:60], "confidence": _conf, "key_id": _c.get("key_id", "")})
_kc_ranked.sort(key=lambda x: x["confidence"], reverse=True)
_kc_top10 = _kc_ranked[:10]
_kc_bot10 = _kc_ranked[-10:] if len(_kc_ranked) >= 10 else _kc_ranked
inject_lines.append(f"DATA.card_rank = {{top10: {json.dumps(_kc_top10, ensure_ascii=False)}, bottom10: {json.dumps(_kc_bot10, ensure_ascii=False)}}};")

# 经验卡按品种胜率排名
from collections import defaultdict
_exp_sym = defaultdict(lambda: {"win": 0, "lose": 0, "pending": 0})
for _e in _exp_all:
    _s = _e.get("symbol", "?")
    _o = _e.get("outcome")
    if _o is True: _exp_sym[_s]["win"] += 1
    elif _o is False: _exp_sym[_s]["lose"] += 1
    else: _exp_sym[_s]["pending"] += 1
_exp_rank = []
for _s, _v in _exp_sym.items():
    _total = _v["win"] + _v["lose"]
    _wr = round(_v["win"] / _total * 100, 1) if _total > 0 else 0
    _exp_rank.append({"symbol": _s, "win": _v["win"], "lose": _v["lose"], "pending": _v["pending"], "total": _total, "wr": _wr})
_exp_rank.sort(key=lambda x: x["wr"], reverse=True)
inject_lines.append(f"DATA.exp_rank = {json.dumps(_exp_rank, ensure_ascii=False)};")

loaded.append(f"cards: {len(all_cards)} knowledge, {_exp_count} experience")

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
            _pe = {
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
            }
            _raw_steps = t.get("steps")
            if _raw_steps and isinstance(_raw_steps, list):
                _pe["steps"] = [
                    {"id": s.get("id",""), "title": s.get("title") or s.get("step",""),
                     "status": s.get("status","pending"), "note": (s.get("note") or "")[:120]}
                    for s in _raw_steps if isinstance(s, dict)
                ]
            pipeline_raw.append(_pe)
    except: pass

if pipeline_raw:
    inject_lines.append(f"DATA.pipeline = {json.dumps(pipeline_raw, ensure_ascii=False)};")

if all_tasks:
    inject_lines.append(f"DATA.tasks = {json.dumps(all_tasks, ensure_ascii=False)};")

if ho_sessions:
    inject_lines.append(f"DATA.sessions = {json.dumps(ho_sessions, ensure_ascii=False)};")

# human_anchors.json → DATA.human_guidance
# Format: flat array of anchor objects with fields: anchor_id, direction(NEUTRAL/LONG/SHORT),
#   main_concern, key(symbol), created_at, expires_after, tracking_status
_ha_path = GCC_DIR / "human_anchors.json"
if _ha_path.exists():
    try:
        _ha_raw = json.loads(_ha_path.read_text(encoding="utf-8"))
        # Normalize: flat array → list of display-ready anchor dicts
        raw_list = _ha_raw if isinstance(_ha_raw, list) else _ha_raw.get("anchors", [])
        # Sort by created_at desc, take last 8
        raw_list = sorted(raw_list, key=lambda x: x.get("created_at",""), reverse=True)[:8]
        # Map LONG→bullish, SHORT→bearish, NEUTRAL→neutral
        _dir_map = {"LONG":"bullish","SHORT":"bearish","NEUTRAL":"neutral","BULLISH":"bullish","BEARISH":"bearish"}
        anchors = []
        for a in raw_list:
            d = a.get("direction","NEUTRAL")
            anchors.append({
                "symbol":    a.get("key","") or "全局",
                "direction": _dir_map.get(d.upper(), "neutral"),
                "concern":   a.get("main_concern", a.get("concern","")),
                "priority":  a.get("priority","normal"),
                "expires_at": a.get("expires_at",""),
                "expires_after": a.get("expires_after",""),
                "created_at": (a.get("created_at","") or "")[:10],
                "tracking_status": a.get("tracking_status",""),
            })
        _hg = {
            "loop_running":   _ha_raw.get("loop_running", False) if isinstance(_ha_raw, dict) else False,
            "loop_last":      _ha_raw.get("loop_last", "")       if isinstance(_ha_raw, dict) else "",
            "anchors":        anchors,
            "prerequisites":  _ha_raw.get("prerequisites", [])   if isinstance(_ha_raw, dict) else [],
            "approval_queue": _ha_raw.get("approval_queue", [])  if isinstance(_ha_raw, dict) else [],
        }
        inject_lines.append(f"DATA.human_guidance = {json.dumps(_hg, ensure_ascii=False)};")
        loaded.append(f"human_anchors: {len(anchors)} anchors")
    except Exception:
        pass

# loop_state.json → merge into DATA.human_guidance (override loop_running/loop_last, add loop_steps/loop_round)
_ls_path = GCC_DIR / "loop_state.json"
if _ls_path.exists():
    try:
        _ls = json.loads(_ls_path.read_text(encoding="utf-8"))
        _ls_patch = {
            "loop_running": bool(_ls.get("running", False)),
            "loop_last":    _ls.get("last_end", "") or _ls.get("last_start", ""),
            "loop_round":   _ls.get("round", 0),
            "loop_steps":   _ls.get("steps", {}),
        }
        inject_lines.append(f"Object.assign(DATA.human_guidance, {json.dumps(_ls_patch, ensure_ascii=False)});")
        loaded.append(f"loop_state: round={_ls_patch['loop_round']}")
    except Exception:
        pass

# 8-layer architecture status → DATA.layers
_gcc_evo_dir = GCC_DIR / "gcc_evolution"
_layer_spec = [
    ('L0', 'Foundation Governance', 'L0_setup',        'free'),
    ('L1', 'Memory',                'L1_memory',        'free'),
    ('L2', 'Retrieval',             'L2_retrieval',     'free'),
    ('L3', 'Distillation',          'L3_distillation',  'free'),
    ('L4', 'Decision',              'L4_decision',      'paid'),
    ('L5', 'Orchestration',         'L5_orchestration', 'paid'),
    ('DA', 'Direction Anchor',      'direction_anchor', 'paid'),
]
_layers = []
for _lid, _lname, _ldir, _ltier in _layer_spec:
    _lpath = _gcc_evo_dir / _ldir
    _py_files = [f for f in _lpath.glob('*.py') if f.name != '__init__.py'] if _lpath.exists() else []
    _layers.append({'id': _lid, 'name': _lname, 'tier': _ltier, 'active': len(_py_files) > 0, 'files': len(_py_files)})
inject_lines.append(f"DATA.layers = {json.dumps(_layers, ensure_ascii=False)};")

# skillbank: 优先读蒸馏skill(实战验证), 回退老skillbank
_skills_path = pathlib.Path("state") / "gcc_skills.json"
if not _skills_path.exists():
    _skills_path = GCC_DIR / "skillbank.jsonl"
if not _skills_path.exists():
    _skills_path = pathlib.Path("gcc") / "skillbank.jsonl"
if _skills_path.exists():
    _skill_rows = []
    if _skills_path.suffix == ".json":
        try:
            _skill_rows = json.loads(_skills_path.read_text(encoding="utf-8"))
            # 转换为dashboard兼容格式
            _skill_rows = [{
                "skill_id": s.get("skill_id", ""),
                "name": s.get("name", ""),
                "skill_type": s.get("type", "general"),
                "success_rate": s.get("correct_rate", 0),
                "use_count": s.get("samples", 0),
                "confidence": s.get("correct_rate", 0.5),
                "version": 1,
                "source": "distilled",
            } for s in _skill_rows]
        except: pass
    else:
        for line in _skills_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip():
                try: _skill_rows.append(json.loads(line))
                except: pass
    if _skill_rows:
        inject_lines.append(f"DATA.skills = {json.dumps(_skill_rows, ensure_ascii=False)};")
        loaded.append(f"skillbank: {len(_skill_rows)} skills")

# suggestions
for key, fname in [("suggestions","suggestions.jsonl")]:
    fp = GCC_DIR / fname
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

# ⑬ GCC-0252: 方向锁 Leader
_load_state_json("plugin_direction_leader.json", "direction_leaders", "direction_leaders")

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
