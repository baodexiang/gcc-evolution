#!/usr/bin/env python3
"""
Human Knowledge Rule Validator v1.0
====================================
用于跟踪、验证和回滚 L1 Human 知识点规则

功能:
- 加载/保存规则配置
- Shadow模式验证（不影响实际决策）
- 效果统计与准确率计算
- 自动禁用低效规则
- 规则回滚支持

作者: AI Trading System
日期: 2026-01-01
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

# Fix Windows console encoding
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, Exception):
        pass


class HumanRuleValidator:
    """Human知识点规则验证器"""

    def __init__(self, config_path: str = None):
        """
        初始化验证器

        Args:
            config_path: 配置文件路径，默认为 config/human_knowledge_rules.json
        """
        if config_path is None:
            # 默认路径
            base_dir = Path(__file__).parent.parent
            config_path = base_dir / "config" / "human_knowledge_rules.json"

        self.config_path = Path(config_path)
        self.config = self._load_config()
        self.validation_log_path = base_dir / self.config.get("validation_results_file", "logs/human_rules_validation.jsonl")

        # 确保日志目录存在
        self.validation_log_path.parent.mkdir(parents=True, exist_ok=True)

    def _load_config(self) -> dict:
        """加载配置文件"""
        if self.config_path.exists():
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {"rules": {}, "global_settings": {}}

    def _save_config(self):
        """保存配置文件"""
        self.config["_meta"]["last_updated"] = datetime.now().strftime("%Y-%m-%d")
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=2, ensure_ascii=False)

    def is_rule_enabled(self, rule_id: str) -> bool:
        """检查规则是否启用"""
        rule = self.config.get("rules", {}).get(rule_id, {})
        return rule.get("enabled", False)

    def get_rule_params(self, rule_id: str) -> dict:
        """获取规则参数"""
        rule = self.config.get("rules", {}).get(rule_id, {})
        return rule.get("parameters", {})

    def enable_rule(self, rule_id: str, note: str = ""):
        """启用规则"""
        if rule_id in self.config.get("rules", {}):
            self.config["rules"][rule_id]["enabled"] = True
            self._add_changelog(rule_id, "enabled", note or "规则启用")
            self._save_config()
            print(f"[HumanRule] ✅ 启用规则: {rule_id}")

    def disable_rule(self, rule_id: str, note: str = ""):
        """禁用规则"""
        if rule_id in self.config.get("rules", {}):
            self.config["rules"][rule_id]["enabled"] = False
            self._add_changelog(rule_id, "disabled", note or "规则禁用")
            self._save_config()
            print(f"[HumanRule] ⛔ 禁用规则: {rule_id}")

    def _add_changelog(self, rule_id: str, action: str, note: str):
        """添加变更日志"""
        if rule_id in self.config.get("rules", {}):
            changelog_entry = {
                "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "action": action,
                "note": note
            }
            self.config["rules"][rule_id].setdefault("changelog", []).append(changelog_entry)

    def record_trigger(self, rule_id: str, symbol: str, signal: str,
                      context: dict, bar_index: int):
        """
        记录规则触发（Shadow模式）

        Args:
            rule_id: 规则ID
            symbol: 品种代码
            signal: 规则产生的信号 (BUY/SELL/HOLD/WARN等)
            context: 触发时的上下文信息
            bar_index: 当前K线索引（用于后续验证）
        """
        settings = self.config.get("global_settings", {})
        if not settings.get("log_all_triggers", True):
            return

        record = {
            "timestamp": datetime.now().isoformat(),
            "rule_id": rule_id,
            "symbol": symbol,
            "signal": signal,
            "context": context,
            "bar_index": bar_index,
            "verify_at_bar": bar_index + settings.get("validation_bars_ahead", 4),
            "verified": False,
            "outcome": None
        }

        # 追加到日志文件
        with open(self.validation_log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        # 更新触发计数
        if rule_id in self.config.get("rules", {}):
            self.config["rules"][rule_id]["metrics"]["total_triggers"] += 1
            self._save_config()

    def verify_pending_records(self, symbol: str, current_bar_index: int,
                               current_price: float, recent_high: float,
                               recent_low: float) -> List[dict]:
        """
        验证待验证的记录

        Args:
            symbol: 品种代码
            current_bar_index: 当前K线索引
            current_price: 当前价格
            recent_high: 验证周期内最高价
            recent_low: 验证周期内最低价

        Returns:
            验证完成的记录列表
        """
        if not self.validation_log_path.exists():
            return []

        verified_records = []
        updated_lines = []

        with open(self.validation_log_path, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.strip():
                    continue
                record = json.loads(line)

                # 检查是否需要验证
                if (record.get("symbol") == symbol and
                    not record.get("verified") and
                    current_bar_index >= record.get("verify_at_bar", 0)):

                    # 验证结果
                    outcome = self._evaluate_outcome(
                        record["signal"],
                        record["context"].get("entry_price", current_price),
                        current_price, recent_high, recent_low
                    )
                    record["verified"] = True
                    record["outcome"] = outcome
                    record["verify_price"] = current_price
                    record["verify_time"] = datetime.now().isoformat()

                    # 更新指标
                    self._update_metrics(record["rule_id"], outcome)
                    verified_records.append(record)

                updated_lines.append(json.dumps(record, ensure_ascii=False))

        # 写回更新后的日志
        with open(self.validation_log_path, 'w', encoding='utf-8') as f:
            f.write("\n".join(updated_lines) + "\n" if updated_lines else "")

        return verified_records

    def _evaluate_outcome(self, signal: str, entry_price: float,
                         current_price: float, recent_high: float,
                         recent_low: float) -> str:
        """评估信号结果"""
        if signal in ["BUY", "BULLISH"]:
            # 买入信号：价格上涨为正确
            if current_price > entry_price * 1.01:
                return "CORRECT"
            elif current_price < entry_price * 0.99:
                return "WRONG"
            else:
                return "NEUTRAL"
        elif signal in ["SELL", "BEARISH", "WARN_TOP"]:
            # 卖出/警告信号：价格下跌为正确
            if current_price < entry_price * 0.99:
                return "CORRECT"
            elif current_price > entry_price * 1.01:
                return "WRONG"
            else:
                return "NEUTRAL"
        return "NEUTRAL"

    def _update_metrics(self, rule_id: str, outcome: str):
        """更新规则指标"""
        if rule_id not in self.config.get("rules", {}):
            return

        metrics = self.config["rules"][rule_id]["metrics"]

        if outcome == "CORRECT":
            metrics["correct_predictions"] = metrics.get("correct_predictions", 0) + 1
        elif outcome == "WRONG":
            metrics["false_positives"] = metrics.get("false_positives", 0) + 1

        # 计算准确率
        total = metrics.get("correct_predictions", 0) + metrics.get("false_positives", 0)
        if total > 0:
            metrics["accuracy"] = round(metrics["correct_predictions"] / total, 4)

        metrics["last_evaluated"] = datetime.now().isoformat()

        # 检查是否需要自动禁用
        settings = self.config.get("global_settings", {})
        min_samples = settings.get("min_samples_for_evaluation", 20)
        auto_disable_threshold = settings.get("auto_disable_threshold", 0.35)

        if total >= min_samples and metrics["accuracy"] < auto_disable_threshold:
            self.disable_rule(rule_id, f"自动禁用：准确率{metrics['accuracy']:.1%} < {auto_disable_threshold:.1%}")
            print(f"[HumanRule] ⚠️ 规则 {rule_id} 准确率过低，已自动禁用")

        self._save_config()

    def get_rule_status(self, rule_id: str = None) -> dict:
        """获取规则状态报告"""
        if rule_id:
            rule = self.config.get("rules", {}).get(rule_id, {})
            return {
                "id": rule_id,
                "name": rule.get("name"),
                "enabled": rule.get("enabled", False),
                "metrics": rule.get("metrics", {}),
                "source": rule.get("source"),
                "description": rule.get("description")
            }

        # 返回所有规则状态
        report = {}
        for rid, rule in self.config.get("rules", {}).items():
            report[rid] = {
                "name": rule.get("name"),
                "enabled": rule.get("enabled", False),
                "accuracy": rule.get("metrics", {}).get("accuracy"),
                "triggers": rule.get("metrics", {}).get("total_triggers", 0)
            }
        return report

    def print_status_report(self):
        """打印状态报告"""
        print("\n" + "=" * 60)
        print("Human Knowledge Rules Status Report")
        print("=" * 60)

        for rule_id, rule in self.config.get("rules", {}).items():
            status = "✅ ON" if rule.get("enabled") else "⛔ OFF"
            metrics = rule.get("metrics", {})
            accuracy = metrics.get("accuracy")
            triggers = metrics.get("total_triggers", 0)

            acc_str = f"{accuracy:.1%}" if accuracy is not None else "N/A"

            print(f"\n{status} {rule.get('name', rule_id)}")
            print(f"   ID: {rule_id}")
            print(f"   来源: {rule.get('source', 'Unknown')}")
            print(f"   触发: {triggers} 次 | 准确率: {acc_str}")

            if rule.get("changelog"):
                last_change = rule["changelog"][-1]
                print(f"   最后变更: {last_change['date']} - {last_change['action']}")

        print("\n" + "=" * 60)

    def rollback_rule(self, rule_id: str, version: str = None):
        """
        回滚规则到之前的版本

        Args:
            rule_id: 规则ID
            version: 目标版本号（默认禁用并重置指标）
        """
        if rule_id not in self.config.get("rules", {}):
            print(f"[HumanRule] ❌ 规则不存在: {rule_id}")
            return

        # 禁用规则
        self.disable_rule(rule_id, f"回滚操作")

        # 重置指标
        self.config["rules"][rule_id]["metrics"] = {
            "total_triggers": 0,
            "correct_predictions": 0,
            "false_positives": 0,
            "false_negatives": 0,
            "accuracy": None,
            "last_evaluated": None
        }

        self._add_changelog(rule_id, "rollback", f"重置指标，回滚到初始状态")
        self._save_config()

        print(f"[HumanRule] 🔄 规则已回滚: {rule_id}")

    def add_new_rule(self, rule_id: str, name: str, source: str,
                     description: str, expected_benefit: str,
                     potential_risk: str, parameters: dict):
        """
        添加新规则

        Args:
            rule_id: 规则ID (如 RULE_006_xxx)
            name: 规则名称
            source: 来源 (如 "云聪13买点交易系统")
            description: 描述
            expected_benefit: 预期好处
            potential_risk: 潜在风险
            parameters: 参数字典
        """
        if rule_id in self.config.get("rules", {}):
            print(f"[HumanRule] ⚠️ 规则已存在: {rule_id}")
            return

        self.config.setdefault("rules", {})[rule_id] = {
            "name": name,
            "source": source,
            "enabled": False,  # 默认禁用，需手动启用
            "version": "1.0",
            "added_date": datetime.now().strftime("%Y-%m-%d"),
            "description": description,
            "expected_benefit": expected_benefit,
            "potential_risk": potential_risk,
            "parameters": parameters,
            "metrics": {
                "total_triggers": 0,
                "correct_predictions": 0,
                "false_positives": 0,
                "false_negatives": 0,
                "accuracy": None,
                "last_evaluated": None
            },
            "changelog": [
                {"date": datetime.now().strftime("%Y-%m-%d"), "action": "created", "note": "初始版本"}
            ]
        }

        self._save_config()
        print(f"[HumanRule] ➕ 新规则已添加: {rule_id} ({name})")
        print(f"   状态: 默认禁用，请使用 enable_rule() 启用")


# ============================================================
# 便捷函数 - 供主程序调用
# ============================================================

_validator_instance = None

def get_validator() -> HumanRuleValidator:
    """获取全局验证器实例"""
    global _validator_instance
    if _validator_instance is None:
        _validator_instance = HumanRuleValidator()
    return _validator_instance


def is_rule_enabled(rule_id: str) -> bool:
    """检查规则是否启用"""
    return get_validator().is_rule_enabled(rule_id)


def get_rule_params(rule_id: str) -> dict:
    """获取规则参数"""
    return get_validator().get_rule_params(rule_id)


def record_rule_trigger(rule_id: str, symbol: str, signal: str,
                        context: dict, bar_index: int):
    """记录规则触发"""
    get_validator().record_trigger(rule_id, symbol, signal, context, bar_index)


# ============================================================
# CLI 接口
# ============================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Human Knowledge Rule Validator")
    parser.add_argument("action", choices=["status", "enable", "disable", "rollback", "add"],
                       help="操作类型")
    parser.add_argument("--rule", "-r", help="规则ID")
    parser.add_argument("--note", "-n", help="备注")

    args = parser.parse_args()

    validator = HumanRuleValidator()

    if args.action == "status":
        validator.print_status_report()
    elif args.action == "enable":
        if args.rule:
            validator.enable_rule(args.rule, args.note or "")
        else:
            print("请指定规则ID: --rule RULE_ID")
    elif args.action == "disable":
        if args.rule:
            validator.disable_rule(args.rule, args.note or "")
        else:
            print("请指定规则ID: --rule RULE_ID")
    elif args.action == "rollback":
        if args.rule:
            validator.rollback_rule(args.rule)
        else:
            print("请指定规则ID: --rule RULE_ID")
