"""
配额恢复补丁 v1.3
================
在不停止扫描引擎的情况下恢复配额

用法:
    python reset_quota_patch.py                    # 恢复配额并自动热重载(默认)
    python reset_quota_patch.py --no-reload        # 只恢复配额，不热重载
    python reset_quota_patch.py --plugin supertrend # 只恢复SuperTrend配额
    python reset_quota_patch.py --symbol BTCUSDC   # 只恢复BTCUSDC的配额
    python reset_quota_patch.py --plugin tracking --symbol SOLUSDC  # 组合过滤
    python reset_quota_patch.py --list             # 列出当前配额状态

v1.3更新:
- 默认自动热重载，无需 --reload 参数
- 新增 --no-reload 参数禁用热重载

v1.2更新:
- 新增 --reload 参数，重置后自动调用扫描引擎热重载API
- 需要扫描引擎 v17.1+ 支持 /reload_state 端点

v1.1更新:
- 修复P0-Tracking配额重置，增加triggered_action字段
"""

import json
import os
import sys
import argparse
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

# 修复Windows控制台编码
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# 扫描引擎API配置
SCAN_ENGINE_API = "http://127.0.0.1:6002"


def call_reload_api() -> bool:
    """调用扫描引擎热重载API"""
    url = f"{SCAN_ENGINE_API}/reload_state"
    try:
        req = urllib.request.Request(url, method='POST')
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            if data.get("status") == "ok":
                print(f"[热重载] 扫描引擎已重新加载配额状态")
                return True
            else:
                print(f"[热重载] 失败: {data.get('message', '未知错误')}")
                return False
    except urllib.error.URLError as e:
        print(f"[热重载] 无法连接扫描引擎: {e.reason}")
        print(f"         请确保扫描引擎正在运行且端口6002可用")
        return False
    except Exception as e:
        print(f"[热重载] 错误: {e}")
        return False

# 外挂配置: 名称 -> 状态文件
PLUGINS = {
    "tracking": {
        "file": "scan_tracking_state.json",
        "name": "P0-Tracking",
        "quota_fields": ["buy_used", "sell_used", "trailing_stop_used", "trailing_buy_used"],
        "extra_fields": ["buy_triggered", "sell_triggered", "triggered_action"],  # v1.1: 周期触发状态
    },
    "supertrend": {
        "file": "scan_supertrend_state.json",
        "name": "SuperTrend",
        "quota_fields": ["buy_used", "sell_used"],
    },
    "rob_hoffman": {
        "file": "scan_rob_hoffman_state.json",
        "name": "Rob Hoffman",
        "quota_fields": ["buy_used", "sell_used"],
    },
    "double_pattern": {
        "file": "scan_double_pattern_state.json",
        "name": "双底双顶",
        "quota_fields": ["buy_used", "sell_used"],
    },
    "feiyun": {
        "file": "scan_feiyun_state.json",
        "name": "飞云",
        "quota_fields": ["buy_used", "sell_used"],
    },
    "macd_divergence": {
        "file": "scan_macd_divergence_state.json",
        "name": "MACD背离",
        "quota_fields": ["buy_used", "sell_used"],
    },
    "supertrend_av2": {
        "file": "scan_supertrend_av2_state.json",
        "name": "SuperTrend+AV2",
        "quota_fields": ["buy_used", "sell_used"],
    },
    "scalping": {
        "file": "scan_scalping_state.json",
        "name": "剥头皮",
        "quota_fields": ["daily_buy_count", "daily_sell_count"],
        "is_count": True,  # 特殊处理: 计数器模式
    },
}


def safe_json_read(filepath: str) -> dict:
    """安全读取JSON文件"""
    try:
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"[错误] 读取 {filepath} 失败: {e}")
    return {}


def safe_json_write(filepath: str, data: dict):
    """安全写入JSON文件 (原子写入)"""
    temp_file = filepath + ".tmp"
    try:
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        # 原子替换
        if os.path.exists(filepath):
            os.replace(temp_file, filepath)
        else:
            os.rename(temp_file, filepath)
        return True
    except Exception as e:
        print(f"[错误] 写入 {filepath} 失败: {e}")
        if os.path.exists(temp_file):
            os.remove(temp_file)
        return False


def format_quota_status(symbol_state: dict, plugin_config: dict) -> str:
    """格式化配额状态显示"""
    if plugin_config.get("is_count"):
        buy = symbol_state.get("daily_buy_count", 0)
        sell = symbol_state.get("daily_sell_count", 0)
        return f"buy={buy} sell={sell}"
    else:
        parts = []
        for field in plugin_config["quota_fields"]:
            short_name = field.replace("_used", "").replace("trailing_", "T_")
            used = symbol_state.get(field, False)
            parts.append(f"{short_name}[{'X' if used else '-'}]")
        # v1.1: 显示额外字段 (triggered_action)
        triggered = symbol_state.get("triggered_action")
        if triggered:
            parts.append(f"triggered={triggered}")
        freeze = symbol_state.get("freeze_until")
        if freeze:
            parts.append(f"freeze={freeze[:16]}")
        return " ".join(parts)


def list_quotas(plugin_filter: str = None, symbol_filter: str = None):
    """列出当前配额状态"""
    print("\n" + "=" * 60)
    print("当前配额状态")
    print("=" * 60)

    for plugin_key, config in PLUGINS.items():
        if plugin_filter and plugin_key != plugin_filter:
            continue

        filepath = config["file"]
        if not os.path.exists(filepath):
            print(f"\n【{config['name']}】 - 状态文件不存在")
            continue

        data = safe_json_read(filepath)
        symbols = data.get("symbols", {})

        if not symbols:
            print(f"\n【{config['name']}】 - 无品种数据")
            continue

        print(f"\n【{config['name']}】 ({filepath})")
        print("-" * 50)

        for sym, state in sorted(symbols.items()):
            if symbol_filter and sym != symbol_filter:
                continue
            status = format_quota_status(state, config)
            print(f"  {sym:<12} {status}")

        # 剥头皮全局状态
        if plugin_key == "scalping":
            global_state = data.get("global", {})
            if global_state.get("global_frozen_until"):
                print(f"  [全局冻结] {global_state['global_frozen_until']}")

    print("\n" + "=" * 60)


def reset_quotas(plugin_filter: str = None, symbol_filter: str = None, dry_run: bool = False):
    """重置配额"""
    if dry_run:
        print("\n[模拟模式] 不会实际修改文件\n")

    reset_count = 0

    for plugin_key, config in PLUGINS.items():
        if plugin_filter and plugin_key != plugin_filter:
            continue

        filepath = config["file"]
        if not os.path.exists(filepath):
            continue

        data = safe_json_read(filepath)
        symbols = data.get("symbols", {})
        modified = False

        for sym, state in symbols.items():
            if symbol_filter and sym != symbol_filter:
                continue

            # 检查是否需要重置
            needs_reset = False
            if config.get("is_count"):
                # 计数器模式
                if state.get("daily_buy_count", 0) > 0 or state.get("daily_sell_count", 0) > 0:
                    needs_reset = True
            else:
                # 布尔模式
                for field in config["quota_fields"]:
                    if state.get(field):
                        needs_reset = True
                        break
                if state.get("freeze_until"):
                    needs_reset = True
                # v1.1: 检查额外字段
                for field in config.get("extra_fields", []):
                    if state.get(field):
                        needs_reset = True
                        break

            if needs_reset:
                old_status = format_quota_status(state, config)

                # 执行重置
                if config.get("is_count"):
                    state["daily_buy_count"] = 0
                    state["daily_sell_count"] = 0
                else:
                    for field in config["quota_fields"]:
                        state[field] = False
                    state["freeze_until"] = None
                    # v1.1: 重置额外字段 (P0-Tracking周期触发状态)
                    for field in config.get("extra_fields", []):
                        if field in state:
                            state[field] = None if field == "triggered_action" else False

                new_status = format_quota_status(state, config)
                print(f"[重置] {config['name']} | {sym}")
                print(f"       {old_status} → {new_status}")
                modified = True
                reset_count += 1

        # 剥头皮全局冻结
        if plugin_key == "scalping" and not symbol_filter:
            global_state = data.get("global", {})
            if global_state.get("global_frozen_until"):
                print(f"[重置] {config['name']} | 全局冻结")
                print(f"       {global_state['global_frozen_until']} → None")
                global_state["global_frozen_until"] = None
                modified = True
                reset_count += 1

        # 保存修改
        if modified and not dry_run:
            data["updated_at"] = datetime.now().isoformat()
            if safe_json_write(filepath, data):
                print(f"[保存] {filepath}")
            else:
                print(f"[失败] 保存 {filepath} 失败!")

    if reset_count == 0:
        print("\n没有需要重置的配额")
    else:
        print(f"\n共重置 {reset_count} 项配额")

    return reset_count


def main():
    parser = argparse.ArgumentParser(
        description="配额恢复补丁 - 在不停止扫描引擎的情况下恢复配额",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    python reset_quota_patch.py                          # 恢复所有配额+自动热重载
    python reset_quota_patch.py --list                   # 列出当前状态
    python reset_quota_patch.py --plugin supertrend      # 只恢复SuperTrend
    python reset_quota_patch.py --symbol BTCUSDC         # 只恢复BTC
    python reset_quota_patch.py --no-reload              # 只重置文件，不热重载
    python reset_quota_patch.py --dry-run                # 模拟运行

可用外挂:
    tracking, supertrend, rob_hoffman, double_pattern,
    feiyun, macd_divergence, supertrend_av2, scalping
        """
    )

    parser.add_argument("--list", "-l", action="store_true",
                        help="列出当前配额状态")
    parser.add_argument("--plugin", "-p", type=str, choices=list(PLUGINS.keys()),
                        help="只处理指定外挂")
    parser.add_argument("--symbol", "-s", type=str,
                        help="只处理指定品种 (如 BTCUSDC)")
    parser.add_argument("--dry-run", "-n", action="store_true",
                        help="模拟运行，不实际修改")
    parser.add_argument("--no-reload", action="store_true",
                        help="禁用热重载 (默认会自动调用扫描引擎热重载API)")

    args = parser.parse_args()

    # 标准化品种名称
    symbol = args.symbol.upper() if args.symbol else None

    print("\n" + "=" * 60)
    print("配额恢复补丁 v1.0")
    print("=" * 60)

    if args.list:
        list_quotas(args.plugin, symbol)
    else:
        # 显示过滤条件
        if args.plugin or symbol:
            filters = []
            if args.plugin:
                filters.append(f"外挂={PLUGINS[args.plugin]['name']}")
            if symbol:
                filters.append(f"品种={symbol}")
            print(f"过滤条件: {', '.join(filters)}")

        reset_count = reset_quotas(args.plugin, symbol, args.dry_run)

        # v1.3: 默认自动热重载
        if not args.no_reload and reset_count > 0 and not args.dry_run:
            print()
            call_reload_api()

    print()


if __name__ == "__main__":
    main()
