#!/usr/bin/env python3
"""
audit.py — KEY-001 T07 审计分析引擎 (v1.0)
==========================================
读取 state/audit/signal_log.jsonl，对已判定记录进行分层分析，
输出准确率指标 + 改善建议。

分析维度:
  - 总体指标: pass_accuracy / false_block_rate
  - 按 n_pattern 分层: PERFECT_N/UP_BREAK/DOWN_BREAK/DEEP_PULLBACK/SIDE
  - 按 n_quality 分位: Q1(0~0.25) / Q2(0.25~0.5) / Q3(0.5~0.75) / Q4(0.75~1.0)
  - 按 direction: BUY / SELL
  - 按 symbol

改善触发条件 (来自 KEY001_因子观测与审计需求.md):
  - false_block_rate > 35%  → 放宽拦截/提高配额
  - pass_accuracy   < 55%  → 收紧阈值/降级配额
  - DEEP_PULLBACK 错误率偏高 → 限次策略微调
  - Q1(低质量)准确率差      → 建议拦截低质量信号

运行方式:
    python audit.py                    # 分析 signal_log.jsonl
    python audit.py --filter           # 同时分析 filter_log.jsonl
    python audit.py --min-samples 10   # 最小样本数(default=5)
    python audit.py --save             # 保存报告到 state/audit/reports/
"""

import argparse
import json
import os
from collections import defaultdict
from datetime import datetime, timezone

# ── 路径 ────────────────────────────────────────────────────────
SIGNAL_LOG  = os.path.join("state", "audit", "signal_log.jsonl")
FILTER_LOG  = os.path.join("state", "audit", "filter_log.jsonl")
REPORTS_DIR = os.path.join("state", "audit", "reports")

# ── 改善阈值 (来自审计规格) ─────────────────────────────────────
THRESHOLD_FALSE_BLOCK   = 0.35   # false_block_rate 超过此值 → 放宽
THRESHOLD_PASS_ACCURACY = 0.55   # pass_accuracy 低于此值   → 收紧
MIN_SAMPLES_DEFAULT     = 5      # 样本不足时跳过分析


# ═══════════════════════════════════════════════════════════════
# 数据加载
# ═══════════════════════════════════════════════════════════════

def load_records(path: str) -> tuple[list, int, int]:
    """
    读取 JSONL，返回 (judged_records, judged_count, pending_count)
    只返回 retrospective 已判定（非 pending/None）的记录
    """
    if not os.path.exists(path):
        return [], 0, 0

    judged, pending = [], 0
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            r = rec.get("retrospective", "pending")
            if r in ("pending", None, ""):
                pending += 1
            else:
                judged.append(rec)

    return judged, len(judged), pending


# ═══════════════════════════════════════════════════════════════
# 指标计算
# ═══════════════════════════════════════════════════════════════

RETRO_TYPES = ("correct_pass", "false_pass", "correct_block", "false_block", "inconclusive")


def _counts(records: list) -> dict:
    """统计四种结果的数量"""
    c = {k: 0 for k in RETRO_TYPES}
    c["total"] = len(records)
    for rec in records:
        r = rec.get("retrospective", "inconclusive")
        if r in c:
            c[r] += 1
    return c


def _metrics(c: dict) -> dict:
    """从计数算出准确率指标"""
    cp, fp = c.get("correct_pass", 0), c.get("false_pass", 0)
    cb, fb = c.get("correct_block", 0), c.get("false_block", 0)
    pass_total  = cp + fp
    block_total = cb + fb

    return {
        "total":             c["total"],
        "pass_accuracy":     round(cp / pass_total, 3)  if pass_total  > 0 else None,
        "block_accuracy":    round(cb / block_total, 3) if block_total > 0 else None,
        "false_block_rate":  round(fb / block_total, 3) if block_total > 0 else None,
        "pass_total":        pass_total,
        "block_total":       block_total,
        "correct_pass":      cp,
        "false_pass":        fp,
        "correct_block":     cb,
        "false_block":       fb,
        "inconclusive":      c.get("inconclusive", 0),
    }


# ═══════════════════════════════════════════════════════════════
# 分层分析
# ═══════════════════════════════════════════════════════════════

def _quality_band(q: float) -> str:
    if   q >= 0.75: return "Q4(高)"
    elif q >= 0.50: return "Q3(中高)"
    elif q >= 0.25: return "Q2(中低)"
    else:           return "Q1(低)"


def analyze(records: list, min_samples: int) -> dict:
    """完整分层分析"""
    overall = _metrics(_counts(records))

    # 按 n_pattern
    by_pattern: dict = defaultdict(list)
    for rec in records:
        by_pattern[rec.get("n_pattern", "UNKNOWN")].append(rec)

    # 按 n_quality 分位
    by_quality: dict = defaultdict(list)
    for rec in records:
        q = rec.get("n_quality") or 0.0
        by_quality[_quality_band(float(q))].append(rec)

    # 按 direction
    by_dir: dict = defaultdict(list)
    for rec in records:
        by_dir[rec.get("direction", "?")].append(rec)

    # 按 symbol
    by_sym: dict = defaultdict(list)
    for rec in records:
        by_sym[rec.get("symbol", "?")].append(rec)

    def _calc_group(groups: dict) -> dict:
        return {
            k: _metrics(_counts(v))
            for k, v in sorted(groups.items())
            if len(v) >= min_samples
        }

    return {
        "overall":     overall,
        "by_pattern":  _calc_group(by_pattern),
        "by_quality":  _calc_group(by_quality),
        "by_direction":_calc_group(by_dir),
        "by_symbol":   _calc_group(by_sym),
    }


# ═══════════════════════════════════════════════════════════════
# 改善建议生成
# ═══════════════════════════════════════════════════════════════

def generate_proposals(analysis: dict) -> list[str]:
    """
    根据分析结果生成可执行改善建议。
    触发条件来自 KEY001_因子观测与审计需求.md Section 4.3
    """
    proposals = []
    overall = analysis["overall"]

    # ── P1: 总体 false_block_rate 过高 ──
    fbr = overall.get("false_block_rate")
    if fbr is not None and fbr > THRESHOLD_FALSE_BLOCK:
        proposals.append(
            f"[P1] 总体 false_block_rate={fbr:.1%} > {THRESHOLD_FALSE_BLOCK:.0%} — "
            f"建议提高 SIDE/PERFECT_N max_trades 配额 或 降低N字质量门槛"
        )

    # ── P1: 总体 pass_accuracy 过低 ──
    pa = overall.get("pass_accuracy")
    if pa is not None and pa < THRESHOLD_PASS_ACCURACY:
        proposals.append(
            f"[P1] 总体 pass_accuracy={pa:.1%} < {THRESHOLD_PASS_ACCURACY:.0%} — "
            f"建议收紧 PERFECT_N quality门槛(当前Q3/Q4才放行)或减少 break 配额"
        )

    # ── P2: 按 n_pattern 分层 ──
    for pat, m in analysis.get("by_pattern", {}).items():
        fbr_p = m.get("false_block_rate")
        pa_p  = m.get("pass_accuracy")
        if fbr_p is not None and fbr_p > THRESHOLD_FALSE_BLOCK:
            proposals.append(
                f"[P2] {pat}: false_block_rate={fbr_p:.1%} 过高 — "
                f"建议 {pat} 状态下提高 max_trades 配额 (block_total={m['block_total']}笔)"
            )
        if pa_p is not None and pa_p < THRESHOLD_PASS_ACCURACY:
            proposals.append(
                f"[P2] {pat}: pass_accuracy={pa_p:.1%} 偏低 — "
                f"建议 {pat} 状态下降低配额或要求更高 quality"
            )

    # ── P2: DEEP_PULLBACK 专项 ──
    dp = analysis.get("by_pattern", {}).get("DEEP_PULLBACK")
    if dp and dp["total"] >= 3:
        dp_fbr = dp.get("false_block_rate")
        dp_pa  = dp.get("pass_accuracy")
        if dp_fbr is not None and dp_fbr > 0.4:
            proposals.append(
                f"[P2] DEEP_PULLBACK false_block={dp_fbr:.1%} — "
                f"回调拦截过多错杀机会，建议 deep_pullback_max_trades 从1改为2"
            )
        if dp_pa is not None and dp_pa < 0.45:
            proposals.append(
                f"[P2] DEEP_PULLBACK pass_accuracy={dp_pa:.1%} — "
                f"深度回调放行信号质量差，建议要求 quality >= 0.6 才放行"
            )

    # ── P3: Q1低质量信号 ──
    q1 = analysis.get("by_quality", {}).get("Q1(低)")
    if q1 and q1["total"] >= 3:
        q1_pa = q1.get("pass_accuracy")
        if q1_pa is not None and q1_pa < 0.45:
            proposals.append(
                f"[P3] Q1(quality<0.25) pass_accuracy={q1_pa:.1%} — "
                f"低质量信号放行后成功率差，建议直接拦截 quality < 0.25 的信号"
            )

    # ── P3: 高频 false_block 品种 ──
    for sym, m in analysis.get("by_symbol", {}).items():
        sym_fbr = m.get("false_block_rate")
        if sym_fbr is not None and sym_fbr > 0.5 and m["block_total"] >= 5:
            proposals.append(
                f"[P3] {sym}: false_block_rate={sym_fbr:.1%} (n={m['block_total']}) — "
                f"该品种N字门控过于保守，建议 YAML 中调高 {sym} 的 max_trades"
            )

    if not proposals:
        proposals.append("[OK] 当前指标均在阈值范围内，无需调整。")

    return proposals


# ═══════════════════════════════════════════════════════════════
# 报告渲染
# ═══════════════════════════════════════════════════════════════

def _pct(v) -> str:
    return f"{v:.1%}" if v is not None else "—"


def _row(label: str, m: dict) -> str:
    return (
        f"| {label:<22} | {m['total']:>5} | "
        f"{_pct(m.get('pass_accuracy')):>10} | "
        f"{_pct(m.get('false_block_rate')):>14} | "
        f"{m.get('correct_pass',0):>3}cp {m.get('false_pass',0):>3}fp "
        f"{m.get('correct_block',0):>3}cb {m.get('false_block',0):>3}fb |"
    )


def render_report(
    analysis: dict,
    proposals: list[str],
    pending: int,
    source: str,
    min_samples: int,
) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    overall = analysis["overall"]
    lines = [
        f"# KEY-001 审计报告",
        f"",
        f"**生成时间**: {ts}  ",
        f"**数据来源**: {source}  ",
        f"**已判定**: {overall['total']} 条 | **待回填**: {pending} 条  ",
        f"**最小样本阈值**: {min_samples}",
        f"",
        f"---",
        f"",
        f"## 1. 总体指标",
        f"",
        f"| 指标 | 值 | 样本 |",
        f"|------|-----|------|",
        f"| pass_accuracy   | {_pct(overall.get('pass_accuracy'))} | {overall.get('pass_total',0)} 笔放行 |",
        f"| block_accuracy  | {_pct(overall.get('block_accuracy'))} | {overall.get('block_total',0)} 笔拦截 |",
        f"| false_block_rate| {_pct(overall.get('false_block_rate'))} | false={overall.get('false_block',0)} correct={overall.get('correct_block',0)} |",
        f"| false_pass      | {overall.get('false_pass',0)} 笔 | — |",
        f"| inconclusive    | {overall.get('inconclusive',0)} 笔 | 变动<0.5% |",
        f"",
    ]

    # ── 按 n_pattern ──
    by_pat = analysis.get("by_pattern", {})
    if by_pat:
        lines += [
            f"## 2. 按 N字状态 (n_pattern)",
            f"",
            f"| 状态                   | 总计  | pass_acc   | false_block_rate | 明细 |",
            f"|------------------------|-------|------------|------------------|------|",
        ]
        for pat, m in by_pat.items():
            lines.append(_row(pat, m))
        lines.append("")

    # ── 按 n_quality 分位 ──
    by_q = analysis.get("by_quality", {})
    if by_q:
        lines += [
            f"## 3. 按 N字质量分位 (n_quality)",
            f"",
            f"| 质量段                 | 总计  | pass_acc   | false_block_rate | 明细 |",
            f"|------------------------|-------|------------|------------------|------|",
        ]
        for qband in ["Q4(高)", "Q3(中高)", "Q2(中低)", "Q1(低)"]:
            if qband in by_q:
                lines.append(_row(qband, by_q[qband]))
        lines.append("")

    # ── 按 direction ──
    by_dir = analysis.get("by_direction", {})
    if by_dir:
        lines += [
            f"## 4. 按方向 (direction)",
            f"",
            f"| 方向                   | 总计  | pass_acc   | false_block_rate | 明细 |",
            f"|------------------------|-------|------------|------------------|------|",
        ]
        for d, m in by_dir.items():
            lines.append(_row(d, m))
        lines.append("")

    # ── 按 symbol ──
    by_sym = analysis.get("by_symbol", {})
    if by_sym:
        lines += [
            f"## 5. 按品种 (symbol)",
            f"",
            f"| 品种                   | 总计  | pass_acc   | false_block_rate | 明细 |",
            f"|------------------------|-------|------------|------------------|------|",
        ]
        for sym, m in by_sym.items():
            lines.append(_row(sym, m))
        lines.append("")

    # ── 改善建议 ──
    lines += [
        f"## 6. 改善建议",
        f"",
    ]
    for i, p in enumerate(proposals, 1):
        lines.append(f"{i}. {p}")
    lines.append("")

    # ── Phase 提示 ──
    test_status = "[DONE]" if overall['total'] >= 30 else f"[WAIT: {overall['total']}/30 条]"
    lines += [
        f"---",
        f"",
        f"**GCC-EVO Stage**: analyze[OK] -> design[OK] -> implement[OK] -> "
        f"test{test_status} -> integrate -> done",
        f"",
        f"**改善执行条件**: 积累 >=7天 且 >=30条已判定记录后，按建议调整 `.GCC/params/*.yaml`",
    ]

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════

def run(path: str, min_samples: int, save: bool) -> str:
    judged, judged_count, pending = load_records(path)

    if judged_count == 0:
        msg = (
            f"[audit] {os.path.basename(path)}: "
            f"无已判定记录 (pending={pending})。"
            f"\n  → 请先运行 python backfill.py 回填价格"
        )
        print(msg)
        return msg

    print(f"[audit] {os.path.basename(path)}: 已判定={judged_count} pending={pending}")

    analysis  = analyze(judged, min_samples)
    proposals = generate_proposals(analysis)
    report    = render_report(analysis, proposals, pending, path, min_samples)

    # Windows GBK 终端安全输出
    try:
        print(report)
    except UnicodeEncodeError:
        print(report.encode("utf-8", errors="replace").decode("ascii", errors="replace"))

    if save:
        os.makedirs(REPORTS_DIR, exist_ok=True)
        date_str = datetime.now().strftime("%Y%m%d_%H%M")
        name     = os.path.splitext(os.path.basename(path))[0]
        out_path = os.path.join(REPORTS_DIR, f"{name}_audit_{date_str}.md")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"[audit] 报告已保存: {out_path}")

    return report


def main():
    ap = argparse.ArgumentParser(description="audit.py v1.0 — KEY-001 T07 分析引擎")
    ap.add_argument("--filter",      action="store_true", help="同时分析 filter_log.jsonl")
    ap.add_argument("--min-samples", type=int, default=MIN_SAMPLES_DEFAULT,
                    help=f"分层最小样本数 (default={MIN_SAMPLES_DEFAULT})")
    ap.add_argument("--save",        action="store_true", help="保存报告到 state/audit/reports/")
    args = ap.parse_args()

    run(SIGNAL_LOG, args.min_samples, args.save)

    if args.filter:
        print("\n" + "=" * 60 + "\n")
        run(FILTER_LOG, args.min_samples, args.save)


if __name__ == "__main__":
    main()
