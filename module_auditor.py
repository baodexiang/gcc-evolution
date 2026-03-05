"""
module_auditor.py — KEY-010 模块级五层GCC-EVO审计引擎
=======================================================
第1层：每个模块单独评分（过去N天独立表现）
第2层：瓶颈定位（具体参数/指标超阈值）
第3层：生成改善建议，写入 state/module_audit_{name}.json
第4层：由 evo_verifier.py 负责（7天验证，本文件不涉及）
第5层：由 gcc_memory_writer.py 负责（写入SkillBank，本文件不涉及）

运行方式:
    python module_auditor.py                   # 审计所有模块，写JSON
    python module_auditor.py --module l2_macd_small  # 只审计指定模块
    python module_auditor.py --report          # 输出可读报告
"""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pytz

ROOT = Path(__file__).parent
STATE = ROOT / "state"
NY_TZ = pytz.timezone("America/New_York")

ANALYSIS_WINDOW_DAYS = 14  # 默认评估窗口（天）

# ── 阈值定义（达到阈值以上 = 健康，低于 = 需改善） ───────────────────────────
THRESHOLDS = {
    "scan_engine": {
        "signal_quality_rate":   {"target": 0.15, "p0": 0.05,  "desc": "触发后最终成交比例"},
        "false_trigger_rate":    {"target": 0.70, "p0": 0.90,  "desc": "触发后被后续层过滤比例（越低越好）", "invert": True},
    },
    "l1_main": {
        "exec_eff":             {"target": 0.30, "p0": 0.10,  "desc": "信号到下单执行效率"},
        "gate_block_rate":      {"target": 0.60, "p0": 0.90,  "desc": "DATA-STALE拦截比例（越低越好）", "invert": True},
    },
    "l2_main": {
        "plugin_exec_rate":     {"target": 0.20, "p0": 0.05,  "desc": "外挂触发后实际执行比例"},
        "governance_observe":   {"target": 0.50, "p0": 0.90,  "desc": "治理OBSERVE比例（越低越好）", "invert": True},
    },
    "l2_macd_small": {
        "win_rate":             {"target": 0.55, "p0": 0.40,  "desc": "MACD背离信号胜率"},
        "consolidating_err":    {"target": 0.30, "p0": 0.50,  "desc": "震荡行情误触发率（越低越好）", "invert": True},
        "trending_capture":     {"target": 0.50, "p0": 0.20,  "desc": "趋势行情信号捕捉率"},
    },
    "brooks_vision": {
        "position_accuracy":    {"target": 0.65, "p0": 0.50,  "desc": "位置判断准确率"},
        "decisive_count":       {"target": 50,   "p0": 10,    "desc": "有效评估样本数"},
    },
    "vision_baseline": {
        "block_rate":           {"target": 0.30, "p0": 0.70,  "desc": "VF拦截率（越低越好，过高=误杀）", "invert": True},
        "symbol_coverage":      {"target": 3,    "p0": 1,     "desc": "有效品种覆盖数"},
    },
    "position_control": {
        "dc_pass_rate":         {"target": 0.60, "p0": 0.30,  "desc": "唐安琪周期通过率"},
        "stale_block_rate":     {"target": 0.30, "p0": 0.60,  "desc": "DATA-STALE拦截率（越低越好）", "invert": True},
    },
}


# ═══════════════════════════════════════════════════════════
# 基类
# ═══════════════════════════════════════════════════════════

class BaseModuleAuditor:
    module_id: str = ""
    module_name: str = ""

    def __init__(self, audit_data: dict, window_days: int = ANALYSIS_WINDOW_DAYS):
        self.audit_data = audit_data          # key009_audit.json["24h"]
        self.window_days = window_days
        self._metrics: dict = {}
        self._score: float = 0.0
        self._bottleneck: dict = {}
        self._suggestion: dict = {}

    # ── 第1层：提取指标并评分 ─────────────────────────────────────
    def extract_metrics(self) -> dict:
        """从 audit_data 中提取本模块的原始指标，子类实现"""
        raise NotImplementedError

    def compute_score(self, metrics: dict) -> float:
        """基于指标和阈值计算 0-1 分，通用加权平均"""
        thresh = THRESHOLDS.get(self.module_id, {})
        if not thresh:
            return 0.5

        scores = []
        for key, cfg in thresh.items():
            val = metrics.get(key)
            if val is None:
                continue
            target = cfg["target"]
            p0 = cfg["p0"]
            invert = cfg.get("invert", False)

            if invert:
                # 越低越好：val < p0 = 1.0, val > target = 0.0（逐渐劣化）
                if val <= p0:
                    s = 1.0
                elif val >= target:
                    # 超过 target 阈值开始扣分（target 是上限）
                    # 使用 target 作为中值
                    s = max(0.0, 1.0 - (val - p0) / max(target - p0, 0.01))
                else:
                    s = 1.0 - (val - p0) / max(target - p0, 0.01)
            else:
                # 越高越好：val >= target = 1.0, val < p0 = 0.0
                if val >= target:
                    s = 1.0
                elif val <= p0:
                    s = 0.0
                else:
                    s = (val - p0) / max(target - p0, 0.01)

            scores.append(max(0.0, min(1.0, s)))

        return round(sum(scores) / len(scores), 3) if scores else 0.5

    # ── 第2层：瓶颈定位 ───────────────────────────────────────────
    def find_bottleneck(self, metrics: dict, score: float) -> dict:
        thresh = THRESHOLDS.get(self.module_id, {})
        issues = []
        for key, cfg in thresh.items():
            val = metrics.get(key)
            if val is None:
                continue
            target = cfg["target"]
            p0 = cfg["p0"]
            invert = cfg.get("invert", False)

            # 判断是否触发预警
            # 越低越好（invert=True）: val > p0 = P0, target < val <= p0 = WARN
            # 越高越好（invert=False）: val < p0 = P0, p0 <= val < target = WARN
            if invert:
                is_p0 = val >= p0
                is_warn = (not is_p0) and val > target
            else:
                is_p0 = val <= p0
                is_warn = (not is_p0) and val < target

            if is_p0:
                issues.append({
                    "metric": key,
                    "value": val,
                    "target": target,
                    "severity": "P0",
                    "desc": cfg["desc"],
                })
            elif is_warn:
                issues.append({
                    "metric": key,
                    "value": val,
                    "target": target,
                    "severity": "WARN",
                    "desc": cfg["desc"],
                })

        return {"issues": issues, "issue_count": len(issues)}

    # ── 第3层：生成改善建议 ───────────────────────────────────────
    def generate_suggestion(self, metrics: dict, bottleneck: dict) -> dict:
        """子类可覆盖生成更具体的建议"""
        issues = bottleneck.get("issues", [])
        if not issues:
            return {"action": "无需改善", "expected_improvement": "维持现状", "priority": "—"}

        top = issues[0]
        return {
            "action": f"{top['desc']} ({top['metric']}) 当前值 {top['value']} 超阈值 {top['target']}，需优化",
            "expected_improvement": f"{top['metric']} 改善至目标 {top['target']}",
            "priority": top["severity"],
        }

    # ── 输出 ─────────────────────────────────────────────────────
    def run(self) -> dict:
        """执行第1-3层，返回 module_audit 结构"""
        metrics = self.extract_metrics()
        score = self.compute_score(metrics)
        bottleneck = self.find_bottleneck(metrics, score)
        suggestion = self.generate_suggestion(metrics, bottleneck)

        self._metrics = metrics
        self._score = score
        self._bottleneck = bottleneck
        self._suggestion = suggestion

        result = {
            "module": self.module_id,
            "module_name": self.module_name,
            "audit_date": datetime.now(NY_TZ).strftime("%Y-%m-%d"),
            "analysis_window_days": self.window_days,
            "score": score,
            "metrics": metrics,
            "bottleneck": bottleneck,
            "suggestion": suggestion,
            "verification_due": (datetime.now(NY_TZ) + timedelta(days=7)).strftime("%Y-%m-%d"),
            "gcc_memory_written": False,
        }
        return result

    def save(self, result: dict) -> Path:
        out = STATE / f"module_audit_{self.module_id}.json"
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return out


# ═══════════════════════════════════════════════════════════
# S02: 扫描引擎
# ═══════════════════════════════════════════════════════════

class ScanEngineAuditor(BaseModuleAuditor):
    module_id = "scan_engine"
    module_name = "扫描引擎"

    def extract_metrics(self) -> dict:
        d = self.audit_data
        # 从 plugins 数据提取：plugin触发 vs 实际执行
        plugins = d.get("plugins", {})
        plugin_exec = plugins.get("plugin_exec", {})
        vf_total = plugins.get("vf_total", 0)           # VF过滤掉的外挂信号
        sent = plugin_exec.get("sent", 0)
        block = plugin_exec.get("block", 0)
        total_triggered = sent + block + vf_total

        # 信号质量率：触发后成交（sent）/ 总触发
        quality_rate = round(sent / total_triggered, 3) if total_triggered > 0 else 0.0
        # 误触发率：被后续过滤（block + vf）/ 总触发
        false_rate = round((block + vf_total) / total_triggered, 3) if total_triggered > 0 else 0.0

        # MACD背离信号触发情况
        macd_div = d.get("macd_divergence", {})
        macd_found = macd_div.get("found", 0)
        macd_filtered = macd_div.get("filtered", 0)

        return {
            "total_triggers": total_triggered,
            "sent": sent,
            "blocked": block + vf_total,
            "signal_quality_rate": quality_rate,
            "false_trigger_rate": false_rate,
            "macd_signals_found": macd_found,
            "macd_signals_filtered": macd_filtered,
        }

    def generate_suggestion(self, metrics, bottleneck) -> dict:
        issues = bottleneck.get("issues", [])
        if not issues:
            return {"action": "扫描引擎正常", "expected_improvement": "维持现状", "priority": "—"}

        ftr = metrics.get("false_trigger_rate", 0)
        sqr = metrics.get("signal_quality_rate", 0)
        if ftr > THRESHOLDS["scan_engine"]["false_trigger_rate"]["p0"]:
            return {
                "action": f"误触发率过高({ftr:.0%})，建议提高扫描门槛或增加前置过滤条件",
                "expected_improvement": f"误触发率从{ftr:.0%}降至{THRESHOLDS['scan_engine']['false_trigger_rate']['target']:.0%}以下",
                "priority": "P0",
            }
        return {
            "action": f"信号质量率偏低({sqr:.0%})，检查下单路径是否存在系统性拦截",
            "expected_improvement": f"质量率从{sqr:.0%}升至{THRESHOLDS['scan_engine']['signal_quality_rate']['target']:.0%}以上",
            "priority": "WARN",
        }


# ═══════════════════════════════════════════════════════════
# S03: 主程序 L1
# ═══════════════════════════════════════════════════════════

class L1MainAuditor(BaseModuleAuditor):
    module_id = "l1_main"
    module_name = "主程序 L1"

    def extract_metrics(self) -> dict:
        d = self.audit_data
        sys_evo = d.get("system_evo", {})
        exec_eff = sys_evo.get("exec_eff", 0)
        errors = sys_evo.get("errors", 0)
        stability = sys_evo.get("stability", 100)

        # DATA-STALE 拦截情况（L1控制总流量）
        gates = d.get("gates", {})
        totals = gates.get("totals", {})
        stale_count = totals.get("DATA-STALE", 0)
        total_events = d.get("total_events", 1)
        gate_block_rate = round(stale_count / max(total_events, 1), 3)

        return {
            "exec_eff": round(exec_eff / 100, 3) if exec_eff > 1 else exec_eff,
            "gate_block_rate": gate_block_rate,
            "error_count": errors,
            "stability": stability,
            "stale_blocks": stale_count,
        }

    def generate_suggestion(self, metrics, bottleneck) -> dict:
        issues = bottleneck.get("issues", [])
        if not issues:
            return {"action": "L1主程序正常", "expected_improvement": "维持现状", "priority": "—"}
        exec_eff = metrics.get("exec_eff", 0)
        gate_rate = metrics.get("gate_block_rate", 0)
        if exec_eff < THRESHOLDS["l1_main"]["exec_eff"]["p0"]:
            return {
                "action": f"L1执行效率极低({exec_eff:.1%})，检查L2路径是否被大量门控拦截",
                "expected_improvement": f"执行效率从{exec_eff:.1%}升至{THRESHOLDS['l1_main']['exec_eff']['target']:.0%}以上",
                "priority": "P0",
            }
        return {
            "action": f"DATA-STALE拦截率偏高({gate_rate:.0%})，检查数据源稳定性",
            "expected_improvement": f"拦截率降至{THRESHOLDS['l1_main']['gate_block_rate']['target']:.0%}以下",
            "priority": "WARN",
        }


# ═══════════════════════════════════════════════════════════
# S04: 主程序 L2
# ═══════════════════════════════════════════════════════════

class L2MainAuditor(BaseModuleAuditor):
    module_id = "l2_main"
    module_name = "主程序 L2"

    def extract_metrics(self) -> dict:
        d = self.audit_data
        plugins = d.get("plugins", {})
        plugin_exec = plugins.get("plugin_exec", {})
        sent = plugin_exec.get("sent", 0)
        block = plugin_exec.get("block", 0)
        total = sent + block
        exec_rate = round(sent / total, 3) if total > 0 else 0.0

        governance = plugins.get("governance", {})
        observe_count = governance.get("OBSERVE", 0)
        gov_total = sum(governance.values()) or 1
        observe_rate = round(observe_count / gov_total, 3)

        return {
            "plugin_exec_rate": exec_rate,
            "sent": sent,
            "blocked": block,
            "governance_observe": observe_rate,
            "observe_count": observe_count,
        }

    def generate_suggestion(self, metrics, bottleneck) -> dict:
        issues = bottleneck.get("issues", [])
        if not issues:
            return {"action": "L2主程序正常", "expected_improvement": "维持现状", "priority": "—"}
        er = metrics.get("plugin_exec_rate", 0)
        obs = metrics.get("governance_observe", 0)
        if obs > THRESHOLDS["l2_main"]["governance_observe"]["p0"]:
            return {
                "action": f"治理OBSERVE比例过高({obs:.0%})，外挂几乎全部处于观察状态，无实际执行",
                "expected_improvement": "检查KEY-004治理阈值，允许部分外挂进入ACTIVE状态",
                "priority": "P0",
            }
        return {
            "action": f"L2外挂执行率偏低({er:.1%})，检查门控条件是否过严",
            "expected_improvement": f"执行率从{er:.1%}升至{THRESHOLDS['l2_main']['plugin_exec_rate']['target']:.0%}",
            "priority": "WARN",
        }


# ═══════════════════════════════════════════════════════════
# S05: L2 小周期 MACD 外挂
# ═══════════════════════════════════════════════════════════

class L2MacdAuditor(BaseModuleAuditor):
    module_id = "l2_macd_small"
    module_name = "L2小周期MACD"

    def extract_metrics(self) -> dict:
        d = self.audit_data

        # 从 macd_signal_accuracy.json 读取胜率
        win_rate = 0.0
        decisive = 0
        macd_acc_path = STATE / "macd_signal_accuracy.json"
        if macd_acc_path.exists():
            try:
                macd_data = json.loads(macd_acc_path.read_text(encoding="utf-8"))
                overall = macd_data.get("overall", {})
                win_rate = overall.get("accuracy", 0.0)
                decisive = overall.get("decisive", 0)
            except Exception:
                pass

        # 从 macd_divergence 计算震荡误触发率（被「背离强度不足」过滤）
        macd_div = d.get("macd_divergence", {})
        found = macd_div.get("found", 0)
        filtered = macd_div.get("filtered", 0)
        filter_reasons = macd_div.get("filter_reasons", {})

        total_signals = found + filtered
        # 趋势行情捕捉率 = 实际找到 / 总候选
        trending_capture = round(found / total_signals, 3) if total_signals > 0 else 0.0

        # 震荡误触发估算：被日限制拦截 = 生成了但不该生成的信号
        consolidating_blocks = (
            filter_reasons.get("每日限制: 今日买入额度已用", 0)
            + filter_reasons.get("每日限制: 今日卖出额度已用", 0)
        )
        # 误触发率 = 被日限制拦截 / (found + 被日限制)
        daily_limit_total = found + consolidating_blocks
        consolidating_err = round(consolidating_blocks / daily_limit_total, 3) if daily_limit_total > 0 else 0.0

        return {
            "win_rate": win_rate,
            "decisive_count": decisive,
            "trending_capture": trending_capture,
            "consolidating_err": consolidating_err,
            "signals_found": found,
            "signals_filtered": filtered,
            "avg_strength": macd_div.get("avg_strength", 0),
        }

    def generate_suggestion(self, metrics, bottleneck) -> dict:
        issues = bottleneck.get("issues", [])
        if not issues:
            return {"action": "MACD外挂正常", "expected_improvement": "维持现状", "priority": "—"}
        wr = metrics.get("win_rate", 0)
        ce = metrics.get("consolidating_err", 0)
        tc = metrics.get("trending_capture", 0)
        if ce > THRESHOLDS["l2_macd_small"]["consolidating_err"]["p0"]:
            return {
                "action": f"震荡行情误触发率过高({ce:.0%})，建议震荡行情下要求连续2根K线确认",
                "expected_improvement": f"误触发率从{ce:.0%}降至{THRESHOLDS['l2_macd_small']['consolidating_err']['target']:.0%}以下",
                "priority": "P0",
            }
        if wr < THRESHOLDS["l2_macd_small"]["win_rate"]["p0"]:
            return {
                "action": f"MACD信号胜率过低({wr:.0%})，检查背离强度阈值设置",
                "expected_improvement": f"胜率从{wr:.0%}提升至{THRESHOLDS['l2_macd_small']['win_rate']['target']:.0%}",
                "priority": "P0",
            }
        return {
            "action": f"趋势行情捕捉率偏低({tc:.0%})，调整背离检测窗口",
            "expected_improvement": f"捕捉率从{tc:.0%}升至{THRESHOLDS['l2_macd_small']['trending_capture']['target']:.0%}",
            "priority": "WARN",
        }


# ═══════════════════════════════════════════════════════════
# S06: Brooks Vision 外挂
# ═══════════════════════════════════════════════════════════

class BrooksVisionAuditor(BaseModuleAuditor):
    module_id = "brooks_vision"
    module_name = "BrooksVision"

    def extract_metrics(self) -> dict:
        # 从 bv_signal_accuracy.json 读取
        position_accuracy = 0.0
        decisive = 0
        bv_path = STATE / "bv_signal_accuracy.json"
        if bv_path.exists():
            try:
                bv_data = json.loads(bv_path.read_text(encoding="utf-8"))
                overall = bv_data.get("overall", {})
                position_accuracy = overall.get("accuracy", 0.0)
                decisive = overall.get("decisive", 0)
            except Exception:
                pass

        # 协同胜率：从 plugin_signal_accuracy 中读取 BrooksVision
        collab_win_rate = 0.0
        pa_path = STATE / "plugin_signal_accuracy.json"
        if pa_path.exists():
            try:
                pa_data = json.loads(pa_path.read_text(encoding="utf-8"))
                bv_acc = pa_data.get("accuracy", {}).get("BrooksVision", {})
                bv_overall = bv_acc.get("_overall", {})
                collab_total = bv_overall.get("total", 0)
                if collab_total > 0:
                    collab_win_rate = round(bv_overall.get("correct", 0) / collab_total, 3)
            except Exception:
                pass

        return {
            "position_accuracy": position_accuracy,
            "decisive_count": decisive,
            "collab_win_rate": collab_win_rate,
        }

    def generate_suggestion(self, metrics, bottleneck) -> dict:
        issues = bottleneck.get("issues", [])
        if not issues:
            return {"action": "BrooksVision正常", "expected_improvement": "维持现状", "priority": "—"}
        acc = metrics.get("position_accuracy", 0)
        dec = metrics.get("decisive_count", 0)
        if dec < THRESHOLDS["brooks_vision"]["decisive_count"]["p0"]:
            return {
                "action": f"BV有效评估样本不足({dec}笔)，无法可靠评估准确率，需积累更多历史数据",
                "expected_improvement": f"样本增至{THRESHOLDS['brooks_vision']['decisive_count']['target']}笔以上",
                "priority": "WARN",
            }
        return {
            "action": f"BV位置判断准确率偏低({acc:.0%})，检查低成交量时段的信号质量",
            "expected_improvement": f"准确率从{acc:.0%}升至{THRESHOLDS['brooks_vision']['position_accuracy']['target']:.0%}",
            "priority": "WARN",
        }


# ═══════════════════════════════════════════════════════════
# S07: Vision 过滤（基准K线）
# ═══════════════════════════════════════════════════════════

class VisionBaselineAuditor(BaseModuleAuditor):
    module_id = "vision_baseline"
    module_name = "Vision过滤(基准K线)"

    def extract_metrics(self) -> dict:
        d = self.audit_data
        vf_data = d.get("vision_filter", {})
        total_blocked = vf_data.get("total", 0)
        by_symbol = vf_data.get("by_symbol", {})
        symbol_coverage = len(by_symbol)

        # 拦截率：被VF拦截 / 所有外挂信号候选（用 plugins.vf_total 近似）
        plugins = d.get("plugins", {})
        vf_total = plugins.get("vf_total", 0)
        # vf_total 是 VF 拦截掉的信号数
        block_rate = min(1.0, round(vf_total / max(total_blocked + vf_total, 1), 3))

        # 从 vision_filter_accuracy.json 读取各品种准确率
        vf_acc_path = STATE / "vision_filter_accuracy.json"
        avg_accuracy = 0.0
        if vf_acc_path.exists():
            try:
                vfa = json.loads(vf_acc_path.read_text(encoding="utf-8"))
                accs = [v.get("accuracy", 0) for v in vfa.get("accuracy", {}).values() if v.get("samples", 0) >= 3]
                avg_accuracy = round(sum(accs) / len(accs), 3) if accs else 0.0
            except Exception:
                pass

        return {
            "block_rate": block_rate,
            "symbol_coverage": symbol_coverage,
            "avg_filter_accuracy": avg_accuracy,
            "total_blocked": total_blocked,
            "vf_triggered": vf_total,
        }

    def generate_suggestion(self, metrics, bottleneck) -> dict:
        issues = bottleneck.get("issues", [])
        if not issues:
            return {"action": "Vision过滤正常", "expected_improvement": "维持现状", "priority": "—"}
        br = metrics.get("block_rate", 0)
        cov = metrics.get("symbol_coverage", 0)
        if cov < THRESHOLDS["vision_baseline"]["symbol_coverage"]["p0"]:
            return {
                "action": f"Vision过滤品种覆盖不足({cov}个品种)，数据稀疏，评估不可靠",
                "expected_improvement": "增加VF评估样本，覆盖至少3个活跃品种",
                "priority": "WARN",
            }
        return {
            "action": f"VF拦截率({br:.0%})可能存在误杀，检查bars_ago分布和基准K线识别准确率",
            "expected_improvement": "降低误杀率，保留更多有效信号",
            "priority": "WARN",
        }


# ═══════════════════════════════════════════════════════════
# S08: 仓位控制
# ═══════════════════════════════════════════════════════════

class PositionControlAuditor(BaseModuleAuditor):
    module_id = "position_control"
    module_name = "仓位控制"

    def extract_metrics(self) -> dict:
        d = self.audit_data
        # 唐安琪周期通过率
        baseline = d.get("baseline", {})
        dc_stats = baseline.get("dc_stats", {})
        dc_total = dc_stats.get("total", 0)
        dc_pass = dc_stats.get("pass", 0)
        dc_block = dc_stats.get("block", 0)
        dc_pass_rate = round(dc_pass / dc_total, 3) if dc_total > 0 else 0.0

        # DATA-STALE 拦截（影响仓位数据读取）
        gates = d.get("gates", {})
        stale_count = gates.get("totals", {}).get("DATA-STALE", 0)
        total_events = d.get("total_events", 1)
        stale_block_rate = round(stale_count / max(total_events, 1), 3)

        # 过度限制率估算（来自 vision_filter 品种数量）
        vf_data = d.get("vision_filter", {})
        vf_total_blocked = vf_data.get("total", 0)

        return {
            "dc_pass_rate": dc_pass_rate,
            "dc_total": dc_total,
            "dc_blocked": dc_block,
            "stale_block_rate": stale_block_rate,
            "stale_count": stale_count,
            "vf_excess_blocks": vf_total_blocked,
        }

    def generate_suggestion(self, metrics, bottleneck) -> dict:
        issues = bottleneck.get("issues", [])
        if not issues:
            return {"action": "仓位控制正常", "expected_improvement": "维持现状", "priority": "—"}
        dcp = metrics.get("dc_pass_rate", 0)
        sbr = metrics.get("stale_block_rate", 0)
        if dcp < THRESHOLDS["position_control"]["dc_pass_rate"]["p0"]:
            return {
                "action": f"唐安琪周期通过率过低({dcp:.0%})，大量仓位被周期规则拦截",
                "expected_improvement": f"通过率从{dcp:.0%}升至{THRESHOLDS['position_control']['dc_pass_rate']['target']:.0%}，检查周期宽度参数",
                "priority": "P0",
            }
        return {
            "action": f"DATA-STALE拦截率过高({sbr:.0%})，仓位控制数据源不稳定",
            "expected_improvement": "改善数据源稳定性，降低STALE拦截",
            "priority": "WARN",
        }


# ═══════════════════════════════════════════════════════════
# 注册表 + 主入口
# ═══════════════════════════════════════════════════════════

ALL_AUDITORS = [
    ScanEngineAuditor,
    L1MainAuditor,
    L2MainAuditor,
    L2MacdAuditor,
    BrooksVisionAuditor,
    VisionBaselineAuditor,
    PositionControlAuditor,
]

MODULE_MAP = {a.module_id: a for a in ALL_AUDITORS}


def run_all(window_days: int = ANALYSIS_WINDOW_DAYS, module_filter: Optional[str] = None) -> dict:
    """
    加载 key009_audit.json，对所有（或指定）模块运行第1-3层审计。
    返回 {module_id: result_dict}
    """
    audit_path = STATE / "key009_audit.json"
    if not audit_path.exists():
        raise FileNotFoundError(f"找不到 {audit_path}，请先运行 key009_audit.py --export")

    audit_data = json.loads(audit_path.read_text(encoding="utf-8"))
    d24 = audit_data.get("24h", {})

    # 把 system_evo 注入到 d24 方便各 auditor 读取
    # 已经在 d24["system_evo"] 中

    results = {}
    for cls in ALL_AUDITORS:
        if module_filter and cls.module_id != module_filter:
            continue
        auditor = cls(d24, window_days=window_days)
        result = auditor.run()
        auditor.save(result)
        results[cls.module_id] = result

    return results


def print_report(results: dict):
    print(f"\n{'='*60}")
    print(f"  KEY-010 模块级审计报告  {datetime.now(NY_TZ).strftime('%Y-%m-%d %H:%M ET')}")
    print(f"{'='*60}")
    for mod_id, r in results.items():
        score = r["score"]
        color = "✅" if score >= 0.75 else ("⚠️" if score >= 0.50 else "❌")
        print(f"\n{color} [{r['module_name']}]  评分: {score:.2f}")
        issues = r["bottleneck"].get("issues", [])
        if issues:
            for iss in issues:
                print(f"   [{iss['severity']}] {iss['desc']}: {iss['value']} (目标 {iss['target']})")
        sug = r["suggestion"]
        if sug.get("priority") not in ("—", None):
            print(f"   → 建议: {sug['action']}")
            print(f"   → 预期: {sug['expected_improvement']}")
    print(f"\n{'='*60}")
    scores = [r["score"] for r in results.values()]
    print(f"  系统平均评分: {sum(scores)/len(scores):.3f}  ({len(scores)} 个模块)")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="KEY-010 模块级审计")
    parser.add_argument("--module", default=None, help=f"只审计指定模块: {list(MODULE_MAP.keys())}")
    parser.add_argument("--report", action="store_true", help="输出可读报告")
    parser.add_argument("--window", type=int, default=ANALYSIS_WINDOW_DAYS, help="评估窗口天数")
    args = parser.parse_args()

    results = run_all(window_days=args.window, module_filter=args.module)

    if args.report:
        print_report(results)
    else:
        for mod_id, r in results.items():
            out = STATE / f"module_audit_{mod_id}.json"
            print(f"[KEY-010] {r['module_name']:20s}  评分={r['score']:.3f}  → {out.name}")
