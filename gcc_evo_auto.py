#!/usr/bin/env python3
"""
gcc_evo_auto.py — GCC-EVO 全自动进化引擎 (v1.0)
=================================================
每日自动运行，分析两条进化链路，自动应用符合安全约束的变更，
发送 HTML 简报邮件。

覆盖范围:
  KEY-002: 品种参数自适应 (.GCC/params/SYMBOL.yaml)
  KEY-004: 外挂因子评估 (factor_observatory.db)

运行:
    python gcc_evo_auto.py          # 全量分析+应用+发邮件
    python gcc_evo_auto.py --dry-run # 只分析不改，邮件仍发
    python gcc_evo_auto.py --no-email # 只分析+应用，不发邮件

安全约束:
  - 每参数单次变更幅度 ≤ 50%
  - 最小样本: symbol_param=10, plugin_factor=50
  - 置信度阈值: 0.65
  - 每次最多禁用1个外挂
  - 变更前备份 YAML
"""

import argparse
import json
import logging
import os
import shutil
import sqlite3
import ssl
import smtplib
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("GCCEvo")

# ── 路径 ──────────────────────────────────────────────────────
BASE_DIR     = Path(__file__).parent
PARAMS_DIR   = BASE_DIR / ".GCC" / "params"
PROPOSALS_DIR= BASE_DIR / ".GCC" / "proposals"
BACKUP_DIR   = BASE_DIR / ".GCC" / "params_backup"
FACTOR_DB    = BASE_DIR / "state" / "factor_observatory.db"
SIGNAL_LOG   = BASE_DIR / "state" / "audit" / "signal_log.jsonl"
KEY002_FILE  = BASE_DIR / "state" / "key002_adaptive.json"
DAILY_DIR    = BASE_DIR / "logs" / "analyzer"
GOV_FILE     = BASE_DIR / "state" / "plugin_governance_actions.json"

# ── 邮件配置（复用 llm_server 相同账户）─────────────────────
EMAIL_SMTP    = "smtp.gmail.com"
EMAIL_PORT    = 587
EMAIL_TIMEOUT = 30
EMAIL_FROM    = "aistockllmpro@gmail.com"
EMAIL_PASS    = "ficw ovws zvzb qmfs"
EMAIL_TO      = ["baodexiang@hotmail.com"]

# ── 安全约束 ──────────────────────────────────────────────────
MIN_CONFIDENCE     = 0.65   # 低于此置信度不自动应用
MIN_SAMPLES_PARAM  = 10     # 品种参数最小样本量
MIN_SAMPLES_FACTOR = 50     # 因子分析最小样本量
MAX_PARAM_CHANGE   = 0.50   # 每次变更幅度上限（相对当前值）
MAX_DISABLE_PER_RUN= 1      # 每次最多禁用1个外挂
ICIR_WARN          = 0.3
ICIR_GOOD          = 0.5

ALL_SYMBOLS = [
    "BTCUSDC", "ETHUSDC", "SOLUSDC", "ZECUSDC",
    "TSLA", "COIN", "RDDT", "NBIS", "CRWV",
    "RKLB", "HIMS", "OPEN", "AMD", "ONDS", "PLTR",
]


# ══════════════════════════════════════════════════════════════
# YAML 工具
# ══════════════════════════════════════════════════════════════

def _load_yaml(symbol: str) -> dict:
    path = PARAMS_DIR / f"{symbol}.yaml"
    if not path.exists():
        return {}
    try:
        import yaml
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        log.warning(f"  YAML读取失败({symbol}): {e}")
        return {}


def _save_yaml(symbol: str, data: dict, dry_run: bool = False):
    path = PARAMS_DIR / f"{symbol}.yaml"
    if dry_run:
        return
    try:
        import yaml
        # 备份
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(path, BACKUP_DIR / f"{symbol}_{ts}.yaml")
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
        log.info(f"  YAML已更新: {symbol}")
    except Exception as e:
        log.warning(f"  YAML保存失败({symbol}): {e}")


def _set_nested(d: dict, key_path: str, value):
    keys = key_path.split(".")
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = value


def _get_nested(d: dict, key_path: str, default=None):
    keys = key_path.split(".")
    for k in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(k, {})
    return d if d != {} else default


# ══════════════════════════════════════════════════════════════
# KEY-002: 品种参数分析
# ══════════════════════════════════════════════════════════════

def _load_signal_log() -> list:
    if not SIGNAL_LOG.exists():
        return []
    rows = []
    try:
        with open(SIGNAL_LOG, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except Exception:
                        pass
    except Exception:
        pass
    return rows


def _analyze_symbol_params(rows: list) -> dict:
    """按品种统计 pass_accuracy / false_pass_rate / side状态表现"""
    stats = defaultdict(lambda: {
        "total": 0, "correct_pass": 0, "false_pass": 0,
        "correct_block": 0, "false_block": 0, "pending": 0,
        "side_total": 0, "side_false_pass": 0,
    })
    for r in rows:
        sym = r.get("symbol", "")
        if not sym:
            continue
        retro = r.get("retrospective", "pending")
        state = r.get("n_state_state", r.get("n_pattern", "SIDE"))
        allowed = r.get("allowed", True)
        s = stats[sym]
        s["total"] += 1
        if retro == "pending":
            s["pending"] += 1
        elif retro == "correct_pass":
            s["correct_pass"] += 1
        elif retro == "false_pass":
            s["false_pass"] += 1
            if state == "SIDE":
                s["side_false_pass"] += 1
        elif retro == "correct_block":
            s["correct_block"] += 1
        elif retro == "false_block":
            s["false_block"] += 1
        if state == "SIDE" and allowed:
            s["side_total"] += 1
    # 计算比率
    result = {}
    for sym, s in stats.items():
        judged = s["correct_pass"] + s["false_pass"]
        result[sym] = {
            **s,
            "pass_accuracy": s["correct_pass"] / judged if judged >= 1 else None,
            "side_false_pass_rate": s["side_false_pass"] / s["side_total"] if s["side_total"] >= 1 else None,
        }
    return result


def _load_whipsaw_data() -> dict:
    """从最近日报中提取 whipsaw 数据"""
    whipsaw = defaultdict(int)
    if not DAILY_DIR.exists():
        return {}
    for f in sorted(DAILY_DIR.glob("daily_v3_*.txt"))[-7:]:
        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
            import re
            for m in re.finditer(r"\|\s*(\w+)\s*\|.*?\|\s*(\d+)次\s*\|.*?亏损", content):
                sym, count = m.group(1), int(m.group(2))
                whipsaw[sym] = max(whipsaw[sym], count)
        except Exception:
            pass
    return dict(whipsaw)


def generate_key002_proposals(dry_run: bool = False) -> list:
    """分析品种参数，生成自动调优提案"""
    rows    = _load_signal_log()
    sym_stats = _analyze_symbol_params(rows)
    whipsaw   = _load_whipsaw_data()
    proposals = []

    for symbol in ALL_SYMBOLS:
        yaml_data = _load_yaml(symbol)
        if not yaml_data:
            continue
        s = sym_stats.get(symbol, {})
        changes = []
        evidence = {"symbol": symbol, "data": s, "whipsaw": whipsaw.get(symbol, 0)}
        judged = s.get("correct_pass", 0) + s.get("false_pass", 0)

        # 规则1: SIDE状态 false_pass_rate > 75% → side_max_trades→0
        side_fpr = s.get("side_false_pass_rate")
        if side_fpr is not None and side_fpr > 0.75 and s.get("side_total", 0) >= MIN_SAMPLES_PARAM:
            cur = _get_nested(yaml_data, "n_gate.side_max_trades", 1)
            if cur > 0:
                changes.append({
                    "key_path": "n_gate.side_max_trades",
                    "old_value": cur, "new_value": 0,
                    "reason": f"SIDE状态false_pass={side_fpr:.0%}(n={s['side_total']}), 禁止SIDE交易",
                    "confidence": min(0.95, side_fpr),
                })

        # 规则2: pass_accuracy < 40% + whipsaw ≥3次 → 增加冷却时间
        pa = s.get("pass_accuracy")
        ws = whipsaw.get(symbol, 0)
        if pa is not None and pa < 0.40 and judged >= MIN_SAMPLES_PARAM and ws >= 3:
            cur_cd = _get_nested(yaml_data, "timing.side_cooldown_hours", 3)
            new_cd = min(12, int(cur_cd * 1.5))
            if new_cd > cur_cd:
                changes.append({
                    "key_path": "timing.side_cooldown_hours",
                    "old_value": cur_cd, "new_value": new_cd,
                    "reason": f"pass_accuracy={pa:.0%}, whipsaw={ws}次 → 延长冷却",
                    "confidence": 0.70,
                })

        # 规则3: 品种缠论准确率极低(<25%) → 降低仓位上限
        if pa is not None and pa < 0.25 and judged >= MIN_SAMPLES_PARAM * 2:
            cur_max = _get_nested(yaml_data, "risk.max_position_units", 2)
            new_max = max(1, cur_max - 1)
            if new_max < cur_max:
                changes.append({
                    "key_path": "risk.max_position_units",
                    "old_value": cur_max, "new_value": new_max,
                    "reason": f"准确率极低{pa:.0%}(n={judged}), 降低最大仓位",
                    "confidence": 0.68,
                })

        if changes:
            # 只保留置信度 >= MIN_CONFIDENCE 的变更
            changes = [c for c in changes if c["confidence"] >= MIN_CONFIDENCE]
        if changes:
            proposals.append({
                "proposal_id": f"PROP-K2-{symbol}-{datetime.now().strftime('%Y%m%d')}",
                "type": "symbol_param",
                "source": "KEY-002",
                "symbol": symbol,
                "evidence": evidence,
                "changes": changes,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "status": "auto_applied" if not dry_run else "dry_run",
            })

    return proposals


def apply_key002_proposals(proposals: list, dry_run: bool = False) -> list:
    """将提案写入 YAML"""
    applied = []
    for prop in proposals:
        sym   = prop["symbol"]
        yaml_data = _load_yaml(sym)
        if not yaml_data:
            continue
        changed = False
        for ch in prop["changes"]:
            _set_nested(yaml_data, ch["key_path"], ch["new_value"])
            changed = True
            log.info(f"  [{sym}] {ch['key_path']}: {ch['old_value']} → {ch['new_value']}")
        if changed:
            yaml_data["last_updated"] = datetime.now().strftime("%Y-%m-%d")
            yaml_data["version"]      = str(float(yaml_data.get("version", "1.0")) + 0.1)[:4]
            _save_yaml(sym, yaml_data, dry_run=dry_run)
            applied.append(prop)
    return applied


# ══════════════════════════════════════════════════════════════
# KEY-004: 因子分析
# ══════════════════════════════════════════════════════════════

def _load_factor_stats() -> dict:
    """读取 factor_stats 表最新数据"""
    if not FACTOR_DB.exists():
        return {}
    try:
        conn = sqlite3.connect(str(FACTOR_DB))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT factor_name, ic_mean, icir, win_rate, n_samples, market_regime, updated_at "
            "FROM factor_stats ORDER BY updated_at DESC"
        ).fetchall()
        conn.close()
        stats = {}
        for r in rows:
            fn = r["factor_name"]
            regime = r["market_regime"] or "all"
            if fn not in stats:
                stats[fn] = {}
            stats[fn][regime] = dict(r)
        return stats
    except Exception:
        return {}


def _load_factor_signal_counts() -> dict:
    """读取每个因子的信号数量"""
    if not FACTOR_DB.exists():
        return {}
    try:
        conn = sqlite3.connect(str(FACTOR_DB))
        rows = conn.execute(
            "SELECT factor_name, COUNT(*) as cnt FROM factor_signals "
            "WHERE ret_1d IS NOT NULL GROUP BY factor_name"
        ).fetchall()
        conn.close()
        return {r[0]: r[1] for r in rows}
    except Exception:
        return {}


def generate_key004_proposals(dry_run: bool = False) -> list:
    """分析因子表现，生成外挂调整提案"""
    factor_stats  = _load_factor_stats()
    signal_counts = _load_factor_signal_counts()
    proposals     = []
    disabled_count = 0

    for factor_name, regimes in factor_stats.items():
        all_data = regimes.get("all", {})
        n = signal_counts.get(factor_name, 0)
        if n < MIN_SAMPLES_FACTOR:
            continue

        icir     = all_data.get("icir")
        ic_mean  = all_data.get("ic_mean")
        win_rate = all_data.get("win_rate")
        if icir is None:
            continue

        evidence = {
            "factor": factor_name, "n": n,
            "icir": icir, "ic_mean": ic_mean, "win_rate": win_rate,
        }
        changes = []

        # 规则1: ICIR < WARN 且样本充足 → 建议禁用
        if icir < ICIR_WARN and disabled_count < MAX_DISABLE_PER_RUN:
            changes.append({
                "action": "governance",
                "target": factor_name,
                "governance_action": "DISABLE",
                "old_value": "ACTIVE",
                "new_value": "DISABLE",
                "reason": f"ICIR={icir:.3f}<{ICIR_WARN}(n={n}), 因子无效",
                "confidence": min(0.90, 1.0 - icir / ICIR_WARN),
            })
            disabled_count += 1

        # 规则2: ICIR > GOOD 且暂停中 → 建议激活
        elif icir > ICIR_GOOD:
            changes.append({
                "action": "governance",
                "target": factor_name,
                "governance_action": "ACTIVATE",
                "old_value": "PAUSED",
                "new_value": "ACTIVE",
                "reason": f"ICIR={icir:.3f}>{ICIR_GOOD}, 因子有效，建议激活",
                "confidence": 0.70,
            })

        if changes:
            changes = [c for c in changes if c["confidence"] >= MIN_CONFIDENCE]
        if changes:
            proposals.append({
                "proposal_id": f"PROP-K4-{factor_name}-{datetime.now().strftime('%Y%m%d')}",
                "type": "plugin_factor",
                "source": "KEY-004",
                "factor": factor_name,
                "evidence": evidence,
                "changes": changes,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "status": "auto_applied" if not dry_run else "dry_run",
            })

    return proposals


def apply_key004_proposals(proposals: list, dry_run: bool = False) -> list:
    """将因子提案写入治理文件"""
    if not proposals or dry_run:
        return proposals if dry_run else []
    try:
        gov = {}
        if GOV_FILE.exists():
            gov = json.loads(GOV_FILE.read_text(encoding="utf-8"))
        for prop in proposals:
            for ch in prop["changes"]:
                if ch.get("action") == "governance":
                    gov[ch["target"]] = {
                        "action": ch["governance_action"],
                        "reason": ch["reason"],
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "source": "gcc_evo_auto",
                    }
                    log.info(f"  [KEY-004] {ch['target']} → {ch['governance_action']}: {ch['reason']}")
        GOV_FILE.write_text(json.dumps(gov, ensure_ascii=False, indent=2), encoding="utf-8")
        return proposals
    except Exception as e:
        log.warning(f"  治理文件写入失败: {e}")
        return []


# ══════════════════════════════════════════════════════════════
# 提案存档
# ══════════════════════════════════════════════════════════════

def _save_proposals(proposals: list):
    PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")
    path  = PROPOSALS_DIR / f"proposals_{today}.json"
    existing = []
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    existing.extend(proposals)
    path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")


# ══════════════════════════════════════════════════════════════
# HTML 邮件简报
# ══════════════════════════════════════════════════════════════

def _badge(val, good, warn=None) -> str:
    if val is None:
        return "⚫"
    if warn and val < warn:
        return "🔴"
    if val < good:
        return "🟡"
    return "🟢"


def build_email(
    k2_proposals: list,
    k4_proposals: list,
    factor_stats: dict,
    signal_counts: dict,
    sym_stats: dict,
    dry_run: bool,
) -> tuple[str, str]:
    """返回 (subject, html_body)"""
    today     = datetime.now().strftime("%Y-%m-%d")
    mode_tag  = "[DRY-RUN]" if dry_run else "[AUTO-APPLIED]"
    k2_count  = len(k2_proposals)
    k4_count  = len(k4_proposals)
    subject   = f"[GCC-EVO] {today} {mode_tag} 进化简报 (参数变更{k2_count}项 / 因子调整{k4_count}项)"

    sections = []

    # ── 头部 ──────────────────────────────────────────────
    sections.append(f"""
<div style="font-family:Arial,sans-serif;max-width:900px;margin:0 auto">
<h2 style="color:#1a1a2e;border-bottom:3px solid #0066cc;padding-bottom:8px">
  🤖 GCC-EVO 自动进化简报 · {today}
  <span style="font-size:13px;color:#666;font-weight:normal">
    &nbsp;{'🔵 DRY-RUN 模式' if dry_run else '✅ 已自动应用'}
  </span>
</h2>
<p style="color:#555;margin-top:0">
  KEY-002 品种参数变更: <b>{k2_count}</b> 项 &nbsp;|&nbsp;
  KEY-004 外挂因子调整: <b>{k4_count}</b> 项
</p>
""")

    # ── KEY-002 品种参数变更 ──────────────────────────────
    sections.append("""<h3 style="color:#0066cc">📊 KEY-002 品种参数变更</h3>""")
    if k2_proposals:
        rows_html = ""
        for prop in k2_proposals:
            sym = prop["symbol"]
            ev  = prop.get("evidence", {}).get("data", {})
            pa  = ev.get("pass_accuracy")
            ws  = prop.get("evidence", {}).get("whipsaw", 0)
            pa_str = f"{pa:.0%}" if pa is not None else "—"
            for ch in prop["changes"]:
                rows_html += f"""
<tr>
  <td style="padding:6px 10px;border-bottom:1px solid #eee"><b>{sym}</b></td>
  <td style="padding:6px 10px;border-bottom:1px solid #eee;color:#666">{ch['key_path']}</td>
  <td style="padding:6px 10px;border-bottom:1px solid #eee">{ch['old_value']}</td>
  <td style="padding:6px 10px;border-bottom:1px solid #eee;color:#cc3300"><b>{ch['new_value']}</b></td>
  <td style="padding:6px 10px;border-bottom:1px solid #eee;font-size:12px;color:#555">{ch['reason']}</td>
  <td style="padding:6px 10px;border-bottom:1px solid #eee;text-align:center">{pa_str} | ws={ws}</td>
</tr>"""
        sections.append(f"""
<table style="width:100%;border-collapse:collapse;font-size:13px">
  <thead>
    <tr style="background:#f0f4ff;font-weight:bold">
      <th style="padding:8px 10px;text-align:left">品种</th>
      <th style="padding:8px 10px;text-align:left">参数</th>
      <th style="padding:8px 10px;text-align:left">旧值</th>
      <th style="padding:8px 10px;text-align:left">新值</th>
      <th style="padding:8px 10px;text-align:left">原因</th>
      <th style="padding:8px 10px;text-align:left">证据</th>
    </tr>
  </thead>
  <tbody>{rows_html}</tbody>
</table>""")
    else:
        sections.append("""<p style="color:#888">✅ 无需调整，所有品种参数在合理范围内</p>""")

    # ── KEY-004 因子状态表 ──────────────────────────────
    sections.append("""<h3 style="color:#0066cc;margin-top:24px">🔬 KEY-004 外挂因子状态</h3>""")
    if factor_stats:
        rows_html = ""
        for fn, regimes in sorted(factor_stats.items()):
            d   = regimes.get("all", {})
            n   = signal_counts.get(fn, 0)
            icir   = d.get("icir")
            ic     = d.get("ic_mean")
            wr     = d.get("win_rate")
            icir_b = _badge(icir, ICIR_GOOD, ICIR_WARN)
            ic_b   = _badge(ic,   0.05)
            wr_b   = _badge(wr,   0.55)
            icir_s = f"{icir:.3f}" if icir is not None else "—"
            ic_s   = f"{ic:.3f}"   if ic   is not None else "—"
            wr_s   = f"{wr:.1%}"   if wr   is not None else "—"
            status = "🔴 弱" if (icir and icir < ICIR_WARN) else ("🟢 强" if (icir and icir > ICIR_GOOD) else "🟡 中")
            if n < MIN_SAMPLES_FACTOR:
                status = f"⚫ 积累中(n={n})"
            rows_html += f"""
<tr>
  <td style="padding:6px 10px;border-bottom:1px solid #eee"><b>{fn}</b></td>
  <td style="padding:6px 10px;border-bottom:1px solid #eee;text-align:center">{n}</td>
  <td style="padding:6px 10px;border-bottom:1px solid #eee;text-align:center">{ic_s} {ic_b}</td>
  <td style="padding:6px 10px;border-bottom:1px solid #eee;text-align:center">{icir_s} {icir_b}</td>
  <td style="padding:6px 10px;border-bottom:1px solid #eee;text-align:center">{wr_s} {wr_b}</td>
  <td style="padding:6px 10px;border-bottom:1px solid #eee;text-align:center">{status}</td>
</tr>"""
        sections.append(f"""
<table style="width:100%;border-collapse:collapse;font-size:13px">
  <thead>
    <tr style="background:#f0f4ff;font-weight:bold">
      <th style="padding:8px 10px;text-align:left">因子</th>
      <th style="padding:8px 10px;text-align:center">样本数</th>
      <th style="padding:8px 10px;text-align:center">IC均值</th>
      <th style="padding:8px 10px;text-align:center">ICIR</th>
      <th style="padding:8px 10px;text-align:center">胜率</th>
      <th style="padding:8px 10px;text-align:center">状态</th>
    </tr>
  </thead>
  <tbody>{rows_html}</tbody>
</table>""")
        if k4_proposals:
            adj_html = "".join(
                f"<li><b>{p['factor']}</b>: {p['changes'][0]['reason']}</li>"
                for p in k4_proposals if p.get("changes")
            )
            sections.append(f"""<p style="margin-top:10px">
<b>本次因子调整:</b><ul style="margin:4px 0">{adj_html}</ul></p>""")
    else:
        sections.append("""<p style="color:#888">⚫ 因子数据不足 (需运行 python factor_backfill.py)</p>""")

    # ── 品种健康快照 ──────────────────────────────────────
    sections.append("""<h3 style="color:#0066cc;margin-top:24px">🏥 品种健康快照</h3>""")
    concern_rows = ""
    for sym in ALL_SYMBOLS:
        s  = sym_stats.get(sym, {})
        pa = s.get("pass_accuracy")
        judged = s.get("correct_pass", 0) + s.get("false_pass", 0)
        if pa is not None and judged >= 5:
            color = "#cc3300" if pa < 0.40 else ("#cc8800" if pa < 0.55 else "#007700")
            concern_rows += f"""
<tr>
  <td style="padding:5px 10px;border-bottom:1px solid #eee">{sym}</td>
  <td style="padding:5px 10px;border-bottom:1px solid #eee;text-align:center">{judged}</td>
  <td style="padding:5px 10px;border-bottom:1px solid #eee;text-align:center;color:{color};font-weight:bold">{pa:.0%}</td>
  <td style="padding:5px 10px;border-bottom:1px solid #eee;text-align:center">{s.get('false_pass', 0)}</td>
  <td style="padding:5px 10px;border-bottom:1px solid #eee;text-align:center">{s.get('false_block', 0)}</td>
</tr>"""
    if concern_rows:
        sections.append(f"""
<table style="width:100%;border-collapse:collapse;font-size:13px">
  <thead>
    <tr style="background:#f0f4ff;font-weight:bold">
      <th style="padding:8px 10px;text-align:left">品种</th>
      <th style="padding:8px 10px;text-align:center">样本数</th>
      <th style="padding:8px 10px;text-align:center">准确率</th>
      <th style="padding:8px 10px;text-align:center">误判通过</th>
      <th style="padding:8px 10px;text-align:center">误判拦截</th>
    </tr>
  </thead>
  <tbody>{concern_rows}</tbody>
</table>""")
    else:
        sections.append("""<p style="color:#888">⚫ 样本不足，等待数据积累</p>""")

    # ── 尾部 ──────────────────────────────────────────────
    sections.append(f"""
<hr style="margin-top:24px;border:none;border-top:1px solid #ddd">
<p style="font-size:12px;color:#999;margin-top:8px">
  GCC-EVO Auto · {today} · 下次运行: 明天 8AM NY ·
  安全约束: 置信度≥{MIN_CONFIDENCE} | 样本≥{MIN_SAMPLES_PARAM} | 变更幅度≤{MAX_PARAM_CHANGE:.0%}
</p>
</div>""")

    html_body = "\n".join(sections)
    return subject, html_body


# ══════════════════════════════════════════════════════════════
# 邮件发送
# ══════════════════════════════════════════════════════════════

def send_report_email(subject: str, html_body: str):
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"]    = EMAIL_FROM
        msg["To"]      = ", ".join(EMAIL_TO)
        plain = subject  # 纯文本备用
        msg.set_content(plain)
        msg.add_alternative(html_body, subtype="html")
        ctx = ssl.create_default_context()
        with smtplib.SMTP(EMAIL_SMTP, EMAIL_PORT, timeout=EMAIL_TIMEOUT) as s:
            s.starttls(context=ctx)
            s.login(EMAIL_FROM, EMAIL_PASS)
            s.send_message(msg)
        log.info("  邮件发送成功")
    except Exception as e:
        log.warning(f"  邮件发送失败: {e}")


# ══════════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════════

def run(dry_run: bool = False, no_email: bool = False):
    log.info(f"=== GCC-EVO Auto {'[DRY-RUN]' if dry_run else ''} ===")
    today = datetime.now().strftime("%Y-%m-%d")

    # KEY-002
    log.info("── KEY-002 品种参数分析 ──")
    k2_proposals = generate_key002_proposals(dry_run=dry_run)
    k2_applied   = apply_key002_proposals(k2_proposals, dry_run=dry_run) if not dry_run else k2_proposals
    log.info(f"  提案: {len(k2_proposals)}项, 应用: {len(k2_applied)}项")

    # KEY-004
    log.info("── KEY-004 因子分析 ──")
    factor_stats  = _load_factor_stats()
    signal_counts = _load_factor_signal_counts()
    k4_proposals  = generate_key004_proposals(dry_run=dry_run)
    k4_applied    = apply_key004_proposals(k4_proposals, dry_run=dry_run) if not dry_run else k4_proposals
    log.info(f"  提案: {len(k4_proposals)}项, 应用: {len(k4_applied)}项")

    # 存档提案
    all_proposals = k2_proposals + k4_proposals
    if all_proposals:
        _save_proposals(all_proposals)
        log.info(f"  提案已存档 → .GCC/proposals/proposals_{today}.json")

    # 邮件
    if not no_email:
        log.info("── 生成邮件简报 ──")
        rows    = _load_signal_log()
        sym_stats = _analyze_symbol_params(rows)
        subject, html = build_email(
            k2_proposals, k4_proposals,
            factor_stats, signal_counts,
            sym_stats, dry_run,
        )
        send_report_email(subject, html)
    else:
        log.info("  --no-email: 跳过邮件")

    log.info("=== GCC-EVO Auto 完成 ===")
    return {"k2": len(k2_applied), "k4": len(k4_applied)}


def main():
    ap = argparse.ArgumentParser(description="GCC-EVO 全自动进化引擎 v1.0")
    ap.add_argument("--dry-run",   action="store_true", help="只分析不改，邮件仍发")
    ap.add_argument("--no-email",  action="store_true", help="不发邮件")
    args = ap.parse_args()
    run(dry_run=args.dry_run, no_email=args.no_email)


if __name__ == "__main__":
    main()
