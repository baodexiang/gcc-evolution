# ========================================================================
# ER Threshold Analyzer v1.0
# ========================================================================
#
# 版本: 1.0
# 日期: 2026-01-31
#
# KAMA效率比阈值自动分析与调整
#
# 触发时间: 纽约时间 8:00 AM (与Vision报告同步)
# 分析窗口: 过去24小时
#
# 核心功能:
#   - 收集观察日志中的ER值
#   - 计算ER分布 (均值、中位数、百分位)
#   - 统计过滤率
#   - 自动调整阈值
#
# 调整策略:
#   - 过滤率 > 35%: 降低阈值 (更宽松)
#   - 过滤率 < 15%: 提高阈值 (更严格)
#   - 过滤率 15-35%: 微调到P30
#
# ========================================================================

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
import numpy as np

# ========================================================================
# 配置
# ========================================================================

STATE_FILE = "state/er_threshold_state.json"
CHANDELIER_LOG = "logs/chandelier_zlsma_observation.log"
HOFFMAN_LOG = "logs/rob_hoffman_observation.log"

# 调整参数
MIN_SAMPLES = 20  # 最少样本数才进行分析
TARGET_FILTER_RATE = (0.15, 0.35)  # 目标过滤率范围 15%-35%
ER_ADJUST_STEP = 0.02  # 每次调整幅度
ER_MIN = 0.10  # 最小阈值
ER_MAX = 0.50  # 最大阈值

# 默认阈值
DEFAULT_CHANDELIER_THRESHOLD = 0.25
DEFAULT_HOFFMAN_THRESHOLD = 0.30


# ========================================================================
# ERThresholdAnalyzer 类
# ========================================================================

class ERThresholdAnalyzer:
    """ER阈值自动分析器"""

    VERSION = "1.0"

    def __init__(self):
        self.state = self._load_state()

    def _load_state(self) -> Dict:
        """加载状态"""
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"[ER Analyzer] 加载状态失败: {e}")

        # 返回默认状态
        return {
            "last_analysis": None,
            "chandelier_threshold": DEFAULT_CHANDELIER_THRESHOLD,
            "hoffman_threshold": DEFAULT_HOFFMAN_THRESHOLD,
            "history": []
        }

    def _save_state(self):
        """保存状态"""
        try:
            os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
            with open(STATE_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.state, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[ER Analyzer] 保存状态失败: {e}")

    def analyze_24h(self) -> Dict:
        """分析过去24小时数据"""
        print(f"[ER Analyzer] 开始分析 (v{self.VERSION})")

        results = {
            "timestamp": datetime.now().isoformat(),
            "chandelier": self._analyze_plugin("chandelier"),
            "hoffman": self._analyze_plugin("hoffman"),
        }

        return results

    def _analyze_plugin(self, plugin: str) -> Dict:
        """分析单个外挂的ER数据"""
        log_file = CHANDELIER_LOG if plugin == "chandelier" else HOFFMAN_LOG
        current_threshold = (
            self.state["chandelier_threshold"]
            if plugin == "chandelier"
            else self.state["hoffman_threshold"]
        )

        print(f"[ER Analyzer] 分析 {plugin}, 日志: {log_file}")

        # 读取24小时内的日志
        er_values = self._parse_log_24h(log_file)

        if len(er_values) < MIN_SAMPLES:
            print(f"[ER Analyzer] {plugin}: 样本不足 ({len(er_values)}/{MIN_SAMPLES})")
            return {
                "status": "insufficient_data",
                "samples": len(er_values),
                "min_required": MIN_SAMPLES,
                "current_threshold": current_threshold,
                "suggested_threshold": current_threshold,
                "action": "HOLD"
            }

        # 计算统计
        er_array = np.array(er_values)
        stats = {
            "samples": len(er_values),
            "mean": float(np.mean(er_array)),
            "median": float(np.median(er_array)),
            "std": float(np.std(er_array)),
            "min": float(np.min(er_array)),
            "max": float(np.max(er_array)),
            "p25": float(np.percentile(er_array, 25)),
            "p30": float(np.percentile(er_array, 30)),
            "p50": float(np.percentile(er_array, 50)),
            "p75": float(np.percentile(er_array, 75)),
        }

        # 计算过滤率
        filtered = sum(1 for er in er_values if er < current_threshold)
        filter_rate = filtered / len(er_values)
        stats["filter_rate"] = filter_rate
        stats["filtered_count"] = filtered

        print(f"[ER Analyzer] {plugin}: 样本={len(er_values)}, "
              f"过滤率={filter_rate:.1%}, P30={stats['p30']:.3f}")

        # 决定调整
        suggested, action, reason = self._decide_adjustment(
            current_threshold, filter_rate, stats["p30"]
        )

        return {
            "status": "analyzed",
            "current_threshold": current_threshold,
            "suggested_threshold": suggested,
            "action": action,
            "reason": reason,
            "stats": stats
        }

    def _parse_log_24h(self, log_file: str) -> List[float]:
        """解析24小时内的ER值"""
        if not os.path.exists(log_file):
            print(f"[ER Analyzer] 日志文件不存在: {log_file}")
            return []

        cutoff = datetime.now() - timedelta(hours=24)
        er_values = []

        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        ts_str = entry.get("timestamp", "")
                        if ts_str:
                            ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                            if ts >= cutoff:
                                er = entry.get("efficiency_ratio", 0)
                                if er > 0:
                                    er_values.append(er)
                    except (json.JSONDecodeError, ValueError):
                        continue
        except Exception as e:
            print(f"[ER Analyzer] 读取日志失败: {e}")

        return er_values

    def _decide_adjustment(
        self, current: float, filter_rate: float, p30: float
    ) -> Tuple[float, str, str]:
        """决定阈值调整"""
        min_rate, max_rate = TARGET_FILTER_RATE

        if filter_rate > max_rate:
            # 过滤太多，降低阈值
            new_threshold = max(current - ER_ADJUST_STEP, ER_MIN)
            new_threshold = round(new_threshold, 2)
            return (
                new_threshold,
                "LOWER",
                f"过滤率{filter_rate:.1%}>{max_rate:.0%}, 降低阈值"
            )

        elif filter_rate < min_rate:
            # 过滤太少，提高阈值
            new_threshold = min(current + ER_ADJUST_STEP, ER_MAX)
            new_threshold = round(new_threshold, 2)
            return (
                new_threshold,
                "RAISE",
                f"过滤率{filter_rate:.1%}<{min_rate:.0%}, 提高阈值"
            )

        else:
            # 过滤率合适，微调到P30
            if abs(p30 - current) > ER_ADJUST_STEP:
                new_threshold = round(p30, 2)
                new_threshold = max(ER_MIN, min(ER_MAX, new_threshold))
                return (
                    new_threshold,
                    "FINE_TUNE",
                    f"过滤率适中，微调至P30={p30:.2f}"
                )

            return (
                current,
                "HOLD",
                f"过滤率{filter_rate:.1%}在目标范围内，保持不变"
            )

    def apply_adjustments(self, results: Dict) -> bool:
        """应用调整到外挂配置"""
        changed = False

        for plugin in ["chandelier", "hoffman"]:
            data = results.get(plugin, {})
            action = data.get("action", "HOLD")

            if action in ["LOWER", "RAISE", "FINE_TUNE"]:
                key = f"{plugin}_threshold"
                old = self.state[key]
                new = data["suggested_threshold"]

                if old != new:
                    self.state[key] = new
                    changed = True
                    print(f"[ER Analyzer] {plugin}: {old:.2f} → {new:.2f} ({action})")

        if changed:
            self.state["last_analysis"] = datetime.now().isoformat()
            self.state["history"].append({
                "timestamp": datetime.now().isoformat(),
                "results": results
            })
            # 保留最近30天历史
            self.state["history"] = self.state["history"][-30:]
            self._save_state()
            print("[ER Analyzer] 阈值已更新并保存")
        else:
            print("[ER Analyzer] 无需调整阈值")

        return changed

    def get_current_thresholds(self) -> Dict[str, float]:
        """获取当前阈值 (供外挂读取)"""
        return {
            "chandelier": self.state.get("chandelier_threshold", DEFAULT_CHANDELIER_THRESHOLD),
            "hoffman": self.state.get("hoffman_threshold", DEFAULT_HOFFMAN_THRESHOLD)
        }


# ========================================================================
# 辅助函数
# ========================================================================

def run_daily_analysis() -> str:
    """运行每日分析 (供monitor调用)"""
    print("=" * 60)
    print("[ER Analyzer] 每日分析开始")
    print("=" * 60)

    analyzer = ERThresholdAnalyzer()
    results = analyzer.analyze_24h()
    changed = analyzer.apply_adjustments(results)

    # 生成报告
    report = generate_report(results, changed)

    print(report)
    return report


def generate_report(results: Dict, changed: bool) -> str:
    """生成分析报告"""
    lines = [
        "",
        "=" * 50,
        "KAMA ER 阈值每日分析报告",
        f"时间: {results['timestamp']}",
        "=" * 50,
    ]

    for plugin in ["chandelier", "hoffman"]:
        data = results.get(plugin, {})
        plugin_name = "剥头皮(Chandelier)" if plugin == "chandelier" else "Rob Hoffman"

        lines.append(f"\n【{plugin_name}】")
        lines.append(f"  状态: {data.get('status', 'N/A')}")
        lines.append(f"  当前阈值: {data.get('current_threshold', 'N/A')}")
        lines.append(f"  建议阈值: {data.get('suggested_threshold', 'N/A')}")
        lines.append(f"  操作: {data.get('action', 'N/A')}")
        lines.append(f"  原因: {data.get('reason', 'N/A')}")

        stats = data.get("stats", {})
        if stats:
            lines.append(f"  ---")
            lines.append(f"  样本数: {stats.get('samples', 0)}")
            lines.append(f"  过滤数: {stats.get('filtered_count', 0)}")
            lines.append(f"  过滤率: {stats.get('filter_rate', 0):.1%}")
            lines.append(f"  ER均值: {stats.get('mean', 0):.3f}")
            lines.append(f"  ER标准差: {stats.get('std', 0):.3f}")
            lines.append(f"  ER范围: {stats.get('min', 0):.3f} - {stats.get('max', 0):.3f}")
            lines.append(f"  P25: {stats.get('p25', 0):.3f}")
            lines.append(f"  P30: {stats.get('p30', 0):.3f}")
            lines.append(f"  P50: {stats.get('p50', 0):.3f}")
            lines.append(f"  P75: {stats.get('p75', 0):.3f}")

    lines.append("")
    lines.append("=" * 50)
    lines.append(f"阈值已更新: {'是' if changed else '否'}")
    lines.append("=" * 50)
    lines.append("")

    return "\n".join(lines)


def get_dynamic_threshold(plugin: str) -> float:
    """
    获取动态阈值 (供外挂调用)

    Args:
        plugin: "chandelier" 或 "hoffman"

    Returns:
        当前阈值
    """
    try:
        analyzer = ERThresholdAnalyzer()
        thresholds = analyzer.get_current_thresholds()
        return thresholds.get(plugin, 0.25)
    except Exception:
        # fallback到默认值
        if plugin == "chandelier":
            return DEFAULT_CHANDELIER_THRESHOLD
        else:
            return DEFAULT_HOFFMAN_THRESHOLD


# ========================================================================
# 测试
# ========================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("ER Threshold Analyzer v1.0 - 测试")
    print("=" * 60)

    # 测试1: 加载分析器
    print("\n测试1: 初始化分析器")
    analyzer = ERThresholdAnalyzer()
    thresholds = analyzer.get_current_thresholds()
    print(f"  当前阈值: {thresholds}")

    # 测试2: 运行分析
    print("\n测试2: 运行24小时分析")
    results = analyzer.analyze_24h()
    print(f"  分析结果: {json.dumps(results, indent=2, ensure_ascii=False)}")

    # 测试3: 生成报告
    print("\n测试3: 生成报告")
    report = generate_report(results, False)
    print(report)

    # 测试4: 动态阈值获取
    print("\n测试4: 动态阈值获取")
    chandelier_th = get_dynamic_threshold("chandelier")
    hoffman_th = get_dynamic_threshold("hoffman")
    print(f"  Chandelier阈值: {chandelier_th}")
    print(f"  Hoffman阈值: {hoffman_th}")

    print("\n" + "=" * 60)
    print("测试完成!")
    print("=" * 60)
