"""
Coinbase 仓位监控 & State.json 同步工具 v6
功能：
  1. 查询实时价格和持仓 (含现金USDC/USD)
  2. 计算持仓总市值 (加密货币 + 现金)
  3. 对比 Coinbase 真实仓位 vs state.json 记录
  4. 通过API同步仓位到主程序 (v5新增)
  5. 每 5 分钟自动同步
  6. 每天纽约时间 6:00 AM 生成24小时盈亏报告 (txt文件)

v6更新 (2026-01-01):
  - 所有API请求添加 timeout=30，防止网络问题导致程序卡死
  - 添加请求重试机制 (最多3次)
  - 优化错误处理

v5更新 (2025-12-31):
  - 改用 /fix_position API 同步，确保主程序内存同步
  - 保留直接写文件作为备用方案
  - 同时更新主程序内存和磁盘state

v4更新 (2025-12-28):
  - 报告时间改为纽约时间 6:00 AM
  - 优化报告格式: 区分加密货币 vs 现金
  - 每日报告输出独立txt文件

安装依赖: pip install requests cryptography PyJWT pytz
"""

import time
import secrets
import requests
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

try:
    import jwt
    from cryptography.hazmat.primitives import serialization
except ImportError:
    print("请先安装依赖:")
    print("   pip install PyJWT cryptography")
    exit(1)

try:
    import pytz
except ImportError:
    print("请安装 pytz:")
    print("   pip install pytz")
    exit(1)

# ============================================================
# 配置区
# ============================================================

API_KEY_NAME = "organizations/84119b71-e971-4844-8f91-bcfe54504c66/apiKeys/7d69e6f2-88a1-45e7-b806-0821bf0f3848"

API_PRIVATE_KEY = """-----BEGIN EC PRIVATE KEY-----
MHcCAQEEICBNdsz8FxLsQV/OCaDkEjkpKgBHG6GYqapzBDmrmaCnoAoGCCqGSM49
AwEHoUQDQgAEYrjK0/oRfzzn+7LyIOrh+EX5eJ8Fzka04aENf18uVkAbqyzoGEuD
V4+auZ+gdWHPb5UXeVIWwMQhEe+a9xp34g==
-----END EC PRIVATE KEY-----"""

# v5新增: 主程序API地址
LLMSERVER_URL = "http://localhost:6001"

# state.json 路径
STATE_JSON_PATH = "logs/state.json"

# 历史快照文件 (用于计算24小时盈亏)
SNAPSHOT_FILE = "logs/portfolio_snapshots.json"

# 每日盈亏报告目录
DAILY_REPORT_DIR = "logs/daily_reports"

# 监控刷新间隔 (秒) - 5分钟
REFRESH_INTERVAL = 5 * 60

# 每日统计时间 (纽约时间 6:00 AM)
DAILY_REPORT_HOUR = 6
DAILY_REPORT_MINUTE = 0
NY_TIMEZONE = pytz.timezone('America/New_York')

# 稳定币列表
STABLECOINS = ["USDC", "USD", "USDT", "DAI"]

# 币种映射
SYMBOL_MAP = {
    "BTC": "BTCUSDC",
    "ETH": "ETHUSDC",
    "SOL": "SOLUSDC",
    "ZEC": "ZECUSDC",
}

# 每个单位的交易数量 (按币种)
UNIT_AMOUNTS = {
    "BTC": 0.02,
    "ETH": 1,
    "SOL": 15,
    "ZEC": 5,
}

# v6新增: API超时和重试配置
API_TIMEOUT = 30  # 秒
API_MAX_RETRIES = 3  # 最大重试次数

# ============================================================

BASE_URL = "https://api.coinbase.com"

def build_jwt(uri: str) -> str:
    """构建 JWT Token"""
    private_key = serialization.load_pem_private_key(
        API_PRIVATE_KEY.encode('utf-8'),
        password=None
    )

    payload = {
        "sub": API_KEY_NAME,
        "iss": "cdp",
        "nbf": int(time.time()),
        "exp": int(time.time()) + 120,
        "uri": uri,
    }

    token = jwt.encode(
        payload,
        private_key,
        algorithm="ES256",
        headers={"kid": API_KEY_NAME, "nonce": secrets.token_hex(16)}
    )

    return token

def api_request(method: str, path: str) -> dict:
    """
    通用 API 请求
    v6更新: 添加 timeout 和重试机制，防止卡死
    """
    uri = f"{method} api.coinbase.com{path}"

    for attempt in range(API_MAX_RETRIES):
        try:
            token = build_jwt(uri)

            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }

            if method == "GET":
                response = requests.get(BASE_URL + path, headers=headers, timeout=API_TIMEOUT)
            else:
                response = requests.post(BASE_URL + path, headers=headers, timeout=API_TIMEOUT)

            if response.status_code == 200:
                return response.json()

            # 非200状态码，记录并返回None
            print(f"  [API] {method} {path} 返回 HTTP {response.status_code}")
            return None

        except requests.exceptions.Timeout:
            print(f"  [API] 请求超时 (尝试 {attempt + 1}/{API_MAX_RETRIES}): {method} {path}")
            if attempt < API_MAX_RETRIES - 1:
                time.sleep(2)  # 重试前等待2秒
                continue
            return None

        except requests.exceptions.ConnectionError as e:
            print(f"  [API] 连接错误 (尝试 {attempt + 1}/{API_MAX_RETRIES}): {e}")
            if attempt < API_MAX_RETRIES - 1:
                time.sleep(2)
                continue
            return None

        except Exception as e:
            print(f"  [API] 请求异常: {e}")
            return None

    return None

def get_accounts() -> list:
    """获取所有账户余额"""
    data = api_request("GET", "/api/v3/brokerage/accounts")
    if not data or "accounts" not in data:
        return []

    holdings = []
    for acc in data["accounts"]:
        available = float(acc.get("available_balance", {}).get("value", 0))
        hold = float(acc.get("hold", {}).get("value", 0))
        total = available + hold
        currency = acc.get("currency", "???")

        if total > 0.0001:
            holdings.append({
                "currency": currency,
                "available": available,
                "hold": hold,
                "total": total
            })

    return holdings

def get_price(symbol: str) -> float:
    """获取单个币种的 USDC 价格"""
    if symbol in STABLECOINS:
        return 1.0

    for quote in ["USDC", "USD"]:
        product_id = f"{symbol}-{quote}"
        data = api_request("GET", f"/api/v3/brokerage/products/{product_id}")
        if data and "price" in data:
            return float(data["price"])

    return 0.0

def get_all_prices(holdings: list) -> dict:
    """获取所有持仓币种的价格"""
    prices = {}
    for h in holdings:
        currency = h["currency"]
        if currency not in prices:
            prices[currency] = get_price(currency)
    return prices

def calculate_portfolio(holdings: list, prices: dict) -> dict:
    """计算投资组合"""
    total_value = 0.0
    portfolio = []

    for h in holdings:
        currency = h["currency"]
        amount = h["total"]
        price = prices.get(currency, 0)
        value = amount * price
        total_value += value

        portfolio.append({
            "currency": currency,
            "amount": amount,
            "price": price,
            "value": value
        })

    portfolio.sort(key=lambda x: -x["value"])

    return {
        "total_value": total_value,
        "holdings": portfolio
    }

# ============================================================
# 快照管理 (用于计算24小时盈亏)
# ============================================================

def load_snapshots() -> list:
    """加载历史快照"""
    if not os.path.exists(SNAPSHOT_FILE):
        return []
    try:
        with open(SNAPSHOT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []

def save_snapshots(snapshots: list):
    """保存历史快照"""
    # 只保留最近48小时的快照
    cutoff = datetime.now().timestamp() - 48 * 3600
    snapshots = [s for s in snapshots if s.get("timestamp", 0) > cutoff]

    try:
        os.makedirs(os.path.dirname(SNAPSHOT_FILE), exist_ok=True)
        with open(SNAPSHOT_FILE, "w", encoding="utf-8") as f:
            json.dump(snapshots, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"保存快照失败: {e}")

def add_snapshot(portfolio: dict):
    """添加新快照"""
    snapshots = load_snapshots()

    snapshot = {
        "timestamp": datetime.now().timestamp(),
        "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_value": portfolio["total_value"],
        "holdings": {h["currency"]: {"amount": h["amount"], "price": h["price"], "value": h["value"]}
                     for h in portfolio["holdings"]}
    }

    snapshots.append(snapshot)
    save_snapshots(snapshots)

def get_snapshot_24h_ago() -> dict:
    """获取24小时前的快照"""
    snapshots = load_snapshots()
    if not snapshots:
        return None

    target_time = datetime.now().timestamp() - 24 * 3600

    # 找最接近24小时前的快照
    closest = None
    min_diff = float('inf')

    for s in snapshots:
        diff = abs(s["timestamp"] - target_time)
        if diff < min_diff:
            min_diff = diff
            closest = s

    # 如果差距太大 (超过2小时)，返回None
    if min_diff > 2 * 3600:
        return None

    return closest

# ============================================================
# 每日盈亏报告
# ============================================================

def generate_daily_report(current_portfolio: dict) -> str:
    """
    v4重写: 生成每日盈亏报告

    区分:
    - 加密货币持仓 (BTC, ETH, SOL, ZEC等)
    - 现金 (USDC, USD等稳定币)
    """
    now_ny = datetime.now(NY_TIMEZONE)
    report_date = now_ny.strftime("%Y-%m-%d")

    # 获取24小时前快照
    snapshot_24h = get_snapshot_24h_ago()

    # 分离加密货币和现金
    crypto_holdings = []
    cash_holdings = []

    for h in current_portfolio["holdings"]:
        if h["currency"] in STABLECOINS:
            cash_holdings.append(h)
        else:
            crypto_holdings.append(h)

    crypto_total = sum(h["value"] for h in crypto_holdings)
    cash_total = sum(h["value"] for h in cash_holdings)
    total_value = current_portfolio["total_value"]

    lines = []
    lines.append("=" * 70)
    lines.append(f"加密货币每日盈亏报告")
    lines.append(f"日期: {report_date}")
    lines.append(f"纽约时间: {now_ny.strftime('%H:%M:%S')}")
    lines.append("=" * 70)

    # ========== 当前持仓: 加密货币 ==========
    lines.append("")
    lines.append("加密货币持仓")
    lines.append("-" * 70)
    lines.append(f"{'币种':<10} {'数量':<18} {'价格':<14} {'市值':<14}")
    lines.append("-" * 70)

    for h in crypto_holdings:
        lines.append(f"{h['currency']:<10} {h['amount']:<18.8f} ${h['price']:<13,.2f} ${h['value']:<13,.2f}")

    lines.append("-" * 70)
    lines.append(f"{'加密货币小计':<10} {'':<18} {'':<14} ${crypto_total:<13,.2f}")

    # ========== 当前持仓: 现金 ==========
    lines.append("")
    lines.append("现金 (稳定币)")
    lines.append("-" * 70)

    for h in cash_holdings:
        lines.append(f"{h['currency']:<10} {h['amount']:<18.2f} {'':<14} ${h['value']:<13,.2f}")

    lines.append("-" * 70)
    lines.append(f"{'现金小计':<10} {'':<18} {'':<14} ${cash_total:<13,.2f}")

    # ========== 总资产 ==========
    lines.append("")
    lines.append("=" * 70)
    lines.append(f"总资产: ${total_value:,.2f}")
    lines.append(f"   - 加密货币: ${crypto_total:,.2f} ({crypto_total/total_value*100:.1f}%)")
    lines.append(f"   - 现金:     ${cash_total:,.2f} ({cash_total/total_value*100:.1f}%)")
    lines.append("=" * 70)

    # ========== 24小时盈亏 ==========
    lines.append("")
    lines.append("=" * 70)
    lines.append("24小时盈亏统计")
    lines.append("=" * 70)

    if snapshot_24h:
        prev_value = snapshot_24h["total_value"]
        curr_value = total_value
        pnl = curr_value - prev_value
        pnl_pct = (pnl / prev_value * 100) if prev_value > 0 else 0

        # 计算24小时前的加密货币和现金
        prev_holdings = snapshot_24h.get("holdings", {})
        prev_crypto = sum(v.get("value", 0) for k, v in prev_holdings.items() if k not in STABLECOINS)
        prev_cash = sum(v.get("value", 0) for k, v in prev_holdings.items() if k in STABLECOINS)

        crypto_pnl = crypto_total - prev_crypto
        crypto_pnl_pct = (crypto_pnl / prev_crypto * 100) if prev_crypto > 0 else 0

        lines.append("")
        lines.append(f"总资产变化:")
        lines.append(f"   24小时前:  ${prev_value:>12,.2f}")
        lines.append(f"   当前:      ${curr_value:>12,.2f}")
        lines.append(f"   ─────────────────────────")

        pnl_sign = "+" if pnl >= 0 else ""
        lines.append(f"   盈亏:      ${pnl_sign}{pnl:>11,.2f} ({pnl_sign}{pnl_pct:.2f}%)")

        lines.append("")
        lines.append(f"加密货币盈亏 (不含现金):")
        lines.append(f"   24小时前:  ${prev_crypto:>12,.2f}")
        lines.append(f"   当前:      ${crypto_total:>12,.2f}")
        lines.append(f"   ─────────────────────────")

        crypto_sign = "+" if crypto_pnl >= 0 else ""
        lines.append(f"   盈亏:      ${crypto_sign}{crypto_pnl:>11,.2f} ({crypto_sign}{crypto_pnl_pct:.2f}%)")

        # 各币种盈亏明细
        lines.append("")
        lines.append("-" * 70)
        lines.append("各币种盈亏明细:")
        lines.append("-" * 70)
        lines.append(f"{'币种':<10} {'24h前市值':<14} {'当前市值':<14} {'盈亏':<14} {'盈亏%':<10}")
        lines.append("-" * 70)

        for h in crypto_holdings:
            currency = h["currency"]
            curr_val = h["value"]

            prev_h = prev_holdings.get(currency, {})
            prev_val = prev_h.get("value", 0)

            coin_pnl = curr_val - prev_val
            coin_pnl_pct = (coin_pnl / prev_val * 100) if prev_val > 0 else 0

            sign = "+" if coin_pnl >= 0 else ""
            lines.append(f"{currency:<10} ${prev_val:<13,.2f} ${curr_val:<13,.2f} ${sign}{coin_pnl:<12,.2f} {sign}{coin_pnl_pct:.2f}%")

        lines.append("-" * 70)

        # 现金变化
        cash_change = cash_total - prev_cash
        cash_sign = "+" if cash_change >= 0 else ""
        lines.append(f"{'现金变化':<10} ${prev_cash:<13,.2f} ${cash_total:<13,.2f} ${cash_sign}{cash_change:<12,.2f}")
        lines.append("-" * 70)

    else:
        lines.append("")
        lines.append("无法获取24小时前的快照数据")
        lines.append("   (需要运行至少24小时才能生成对比)")

    lines.append("")
    lines.append("=" * 70)
    lines.append("报告结束")
    lines.append("=" * 70)

    return "\n".join(lines)

def save_daily_report(report: str):
    """保存每日报告到文件"""
    now_ny = datetime.now(NY_TIMEZONE)
    report_date = now_ny.strftime("%Y%m%d")

    os.makedirs(DAILY_REPORT_DIR, exist_ok=True)

    filename = f"daily_report_{report_date}.txt"
    filepath = os.path.join(DAILY_REPORT_DIR, filename)

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"报告已保存: {filepath}")
        return filepath
    except Exception as e:
        print(f"保存报告失败: {e}")
        return None

def get_last_report_date() -> str:
    """获取最后一次报告的日期"""
    if not os.path.exists(DAILY_REPORT_DIR):
        return ""

    files = os.listdir(DAILY_REPORT_DIR)
    report_files = [f for f in files if f.startswith("daily_report_")]

    if not report_files:
        return ""

    dates = [f.replace("daily_report_", "").replace(".txt", "") for f in report_files]
    return max(dates) if dates else ""

# ============================================================
# State.json 同步功能
# ============================================================

def load_state_json() -> dict:
    """读取 state.json"""
    if not os.path.exists(STATE_JSON_PATH):
        print(f"未找到 {STATE_JSON_PATH}")
        return {}

    try:
        with open(STATE_JSON_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"读取 state.json 失败: {e}")
        return {}

def save_state_json(data: dict):
    """保存 state.json"""
    try:
        if os.path.exists(STATE_JSON_PATH):
            backup_path = STATE_JSON_PATH + f".backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            with open(STATE_JSON_PATH, "r", encoding="utf-8") as f:
                backup_data = f.read()
            with open(backup_path, "w", encoding="utf-8") as f:
                f.write(backup_data)
            print(f"已备份: {backup_path}")

        with open(STATE_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print(f"state.json 已保存")
        return True
    except Exception as e:
        print(f"保存 state.json 失败: {e}")
        return False

def compare_positions(portfolio: dict, state: dict) -> list:
    """对比仓位"""
    comparisons = []

    for h in portfolio["holdings"]:
        currency = h["currency"]

        if currency in STABLECOINS:
            continue

        symbol = SYMBOL_MAP.get(currency, f"{currency}USDC")

        coinbase_amount = h["amount"]
        coinbase_value = h["value"]
        coinbase_price = h["price"]

        state_data = state.get(symbol, {})
        state_position_units = state_data.get("position_units", 0)
        state_open_buys = state_data.get("open_buys", [])
        state_max_units = state_data.get("max_units", 5)

        # 按数量计算单位数
        unit_amount = UNIT_AMOUNTS.get(currency, 1)
        calculated_units = int(coinbase_amount / unit_amount) if unit_amount > 0 else 0
        calculated_units = min(calculated_units, state_max_units)  # 不超过最大单位

        is_match = state_position_units == calculated_units

        comparisons.append({
            "currency": currency,
            "symbol": symbol,
            "coinbase_amount": coinbase_amount,
            "coinbase_value": coinbase_value,
            "coinbase_price": coinbase_price,
            "unit_amount": unit_amount,
            "state_position_units": state_position_units,
            "state_open_buys_count": len(state_open_buys),
            "state_open_buys": state_open_buys,
            "calculated_units": calculated_units,
            "max_units": state_max_units,
            "is_match": is_match,
            "in_state": symbol in state
        })

    # 反向检查: state.json有仓位但Coinbase没持仓的品种 (防止虚假仓位)
    compared_symbols = {c["symbol"] for c in comparisons}
    for currency, symbol in SYMBOL_MAP.items():
        if symbol in compared_symbols:
            continue
        state_data = state.get(symbol, {})
        state_position_units = state_data.get("position_units", 0)
        if state_position_units > 0:
            comparisons.append({
                "currency": currency,
                "symbol": symbol,
                "coinbase_amount": 0.0,
                "coinbase_value": 0.0,
                "coinbase_price": 0.0,
                "unit_amount": UNIT_AMOUNTS.get(currency, 1),
                "state_position_units": state_position_units,
                "state_open_buys_count": len(state_data.get("open_buys", [])),
                "state_open_buys": state_data.get("open_buys", []),
                "calculated_units": 0,
                "max_units": state_data.get("max_units", 5),
                "is_match": False,
                "in_state": True,
            })

    return comparisons

def sync_via_api(positions: dict) -> bool:
    """
    v5新增: 通过API同步仓位到主程序
    v6更新: 添加超时保护
    """
    try:
        resp = requests.post(
            f"{LLMSERVER_URL}/fix_position",
            json={"positions": positions},
            timeout=API_TIMEOUT
        )

        if resp.status_code == 200:
            result = resp.json()
            print(f"  API同步成功")
            for item in result.get("results", []):
                print(f"     {item['symbol']}: {item['old_units']} -> {item['new_units']}")
            return True
        else:
            print(f"  API同步失败: HTTP {resp.status_code}")
            return False
    except requests.exceptions.Timeout:
        print(f"  API同步超时 ({API_TIMEOUT}s)，将直接写入state.json")
        return False
    except requests.exceptions.ConnectionError:
        print(f"  主程序未运行，将直接写入state.json")
        return False
    except Exception as e:
        print(f"  API同步异常: {e}")
        return False

def sync_to_state_json(comparisons: list, state: dict, auto_fix: bool = True) -> tuple:
    """同步仓位 (v5: 优先使用API，失败时写文件)"""
    changes = []
    api_positions = {}  # v5: 收集需要同步的仓位

    for comp in comparisons:
        symbol = comp["symbol"]

        if not comp["in_state"] or comp["is_match"]:
            continue

        old_units = comp["state_position_units"]
        new_units = comp["calculated_units"]

        if auto_fix:
            # v5: 收集需要同步的仓位
            api_positions[symbol] = new_units

            # 同时更新state字典 (作为备用)
            state[symbol]["position_units"] = new_units

            current_open_buys = state[symbol].get("open_buys", [])

            if len(current_open_buys) != new_units:
                if new_units > len(current_open_buys):
                    avg_price = comp["coinbase_price"]
                    while len(state[symbol]["open_buys"]) < new_units:
                        state[symbol]["open_buys"].append(avg_price)
                elif new_units < len(current_open_buys) and new_units > 0:
                    state[symbol]["open_buys"] = current_open_buys[:new_units]
                elif new_units == 0:
                    state[symbol]["open_buys"] = []

            state[symbol]["actual_buy_count"] = new_units
            state[symbol]["_coinbase_sync"] = {
                "last_sync": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "coinbase_amount": comp["coinbase_amount"],
                "coinbase_value": comp["coinbase_value"],
                "coinbase_price": comp["coinbase_price"]
            }

            changes.append({
                "symbol": symbol,
                "old_units": old_units,
                "new_units": new_units
            })

            print(f"  {symbol}: {old_units} -> {new_units} 单位")

    # v5: 优先通过API同步 (会同时更新内存和磁盘)
    if api_positions:
        api_success = sync_via_api(api_positions)
        if api_success:
            # API成功，主程序已保存state，返回空changes表示不需要再写文件
            return state, []  # 返回空changes，run_once不会再调用save

    # API失败或不可用，返回changes让run_once知道需要手动保存
    return state, changes

def display_comparison(comparisons: list, portfolio: dict) -> int:
    """显示对比结果"""
    print("\n" + "="*90)
    print("Coinbase vs State.json 仓位对比")
    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"总市值: ${portfolio['total_value']:,.2f} USDC")
    print("="*90)

    print(f"\n{'币种':<8} {'CB数量':<14} {'单位量':<10} {'State':<8} {'计算':<8} {'状态':<6}")
    print("-"*90)

    mismatch_count = 0

    for comp in comparisons:
        status = "[OK]" if comp["is_match"] else "[X]"
        if not comp["is_match"]:
            mismatch_count += 1

        unit_amt = comp.get("unit_amount", 1)
        print(f"{comp['currency']:<8} {comp['coinbase_amount']:<14.6f} {unit_amt:<10} {comp['state_position_units']:<8} {comp['calculated_units']:<8} {status}")

    print("-"*90)

    if mismatch_count > 0:
        print(f"\n发现 {mismatch_count} 个仓位不匹配!")
    else:
        print(f"\n所有仓位匹配正确!")

    return mismatch_count

# ============================================================
# 主函数
# ============================================================

def run_once(do_sync: bool = False) -> dict:
    """执行一次查询"""
    print("\n正在查询 Coinbase...")

    holdings = get_accounts()
    if not holdings:
        print("无法获取持仓数据")
        return None

    print("正在获取实时价格...")
    prices = get_all_prices(holdings)

    portfolio = calculate_portfolio(holdings, prices)

    # 保存快照 (用于24小时盈亏计算)
    add_snapshot(portfolio)

    state = load_state_json()
    if state:
        comparisons = compare_positions(portfolio, state)
        mismatch_count = display_comparison(comparisons, portfolio)

        if do_sync and mismatch_count > 0:
            print("\n正在同步仓位...")
            # v5: sync_to_state_json内部会优先尝试API同步
            # API同步成功后返回空changes，失败时返回changes列表
            state, changes = sync_to_state_json(comparisons, state)
            if changes:
                # API同步失败，需要手动保存文件
                print("  通过文件备份保存...")
                save_state_json(state)

    return portfolio

def run_monitor():
    """持续监控模式"""
    print("\n" + "="*80)
    print("启动持续监控模式 v6")
    print(f"   同步间隔: {REFRESH_INTERVAL // 60} 分钟")
    print(f"   每日报告: 纽约时间 {DAILY_REPORT_HOUR}:{DAILY_REPORT_MINUTE:02d} AM")
    print(f"   state.json: {STATE_JSON_PATH}")
    print(f"   API超时: {API_TIMEOUT}秒, 最大重试: {API_MAX_RETRIES}次")
    print("   按 Ctrl+C 退出")
    print("="*80)

    last_report_date = get_last_report_date()

    while True:
        try:
            portfolio = run_once(do_sync=True)

            # 检查是否需要生成每日报告
            now_ny = datetime.now(NY_TIMEZONE)
            today_date = now_ny.strftime("%Y%m%d")

            # 在报告时间窗口内 (6:00 - 6:15) 且今天还没生成
            if (now_ny.hour == DAILY_REPORT_HOUR and
                DAILY_REPORT_MINUTE <= now_ny.minute <= DAILY_REPORT_MINUTE + 15 and
                today_date != last_report_date and
                portfolio):

                print("\n" + "="*80)
                print("生成每日盈亏报告...")
                print("="*80)

                report = generate_daily_report(portfolio)
                print(report)
                save_daily_report(report)
                last_report_date = today_date

            next_run = datetime.now().timestamp() + REFRESH_INTERVAL
            next_run_str = datetime.fromtimestamp(next_run).strftime("%H:%M:%S")
            print(f"\n下次同步: {next_run_str}")

            time.sleep(REFRESH_INTERVAL)

        except KeyboardInterrupt:
            print("\n\n监控已停止")
            break
        except Exception as e:
            print(f"\n错误: {e}")
            time.sleep(REFRESH_INTERVAL)

def generate_report_now():
    """立即生成报告"""
    print("\n正在查询 Coinbase...")

    holdings = get_accounts()
    if not holdings:
        print("无法获取持仓数据")
        return

    prices = get_all_prices(holdings)
    portfolio = calculate_portfolio(holdings, prices)

    report = generate_daily_report(portfolio)
    print(report)
    save_daily_report(report)

def main():
    print("\n" + "="*80)
    print("Coinbase 仓位监控 & 每日盈亏报告工具 v6")
    print("v6更新: API请求添加超时保护，防止卡死")
    print("="*80)
    print("\n使用方式:")
    print("  python coinbase_sync_v6.py          # 持续监控 (默认)")
    print("  python coinbase_sync_v6.py sync     # 查看 + 同步一次")
    print("  python coinbase_sync_v6.py monitor  # 持续监控 (每5分钟同步 + 每日6:00报告)")
    print("  python coinbase_sync_v6.py report   # 立即生成每日报告")
    print("  python coinbase_sync_v6.py once     # 只查看，不同步")

    if len(sys.argv) > 1:
        mode = sys.argv[1].lower()

        if mode == "monitor":
            run_monitor()
        elif mode == "sync":
            run_once(do_sync=True)
        elif mode == "report":
            generate_report_now()
        elif mode == "once":
            run_once(do_sync=False)
        else:
            run_once(do_sync=False)
    else:
        # 默认持续监控模式
        run_monitor()

if __name__ == "__main__":
    main()
