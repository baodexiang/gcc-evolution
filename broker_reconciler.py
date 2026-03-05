"""
broker_reconciler.py — SYS-029 每日对账
Schwab 1099-B CSV 解析 + Coinbase fills API → state/broker_pnl.json

用法:
  python broker_reconciler.py          # 手动运行
  (llm_server 每日8AM NY 自动调度)
"""

import csv
import glob
import json
import os
import re
import time
import secrets
from datetime import datetime, timezone
from pathlib import Path

try:
    import pytz
    NY_TZ = pytz.timezone("America/New_York")
except ImportError:
    from zoneinfo import ZoneInfo
    NY_TZ = ZoneInfo("America/New_York")

# ============================================================
# Schwab 1099-B 品种名→ticker 映射
# ============================================================
NAME_TO_TICKER = {
    "TESLA INC": "TSLA",
    "ALPHABET INC": "GOOGL",
    "INTEL CORP": "INTC",
    "ASML HLDG N V": "ASML",
    "OKLO INC": "OKLO",
    "BROADCOM INC": "AVGO",
    "SOFI TECHNOLOGIES INC": "SOFI",
    "UPSTART HLDGS INC": "UPST",
    "PAYONEER GLOBAL INC": "PAYO",
    "STRATEGY INC": "MSTR",
    "RECURSION PHARMACEUTICAL": "RXRX",
    "INNODATA INC": "INOD",
    "REDDIT INC": "RDDT",
    "HIMS & HERS HEALTH INC": "HIMS",
    "TEMPUS AI INC": "TEM",
    "NEBIUS GROUP N V A": "NBIS",
    "APPLOVIN CORP": "APP",
    "UNITEDHEALTH GROUP INC": "UNH",
    "COINBASE GLOBAL INC": "COIN",
    "COREWEAVE INC": "CRWV",
    "ROCKET LAB CORP": "RKLB",
    "ADVANCED MICRO DEVIC": "AMD",
    "OPENDOOR TECHNOLOGIES IN": "OPEN",
    "PROSHARES ULTRAPRO SH": "TQQQ",
    "BITMINE IMMERSION TECNOL": "BIMI",
    "FIGURE TECHNOLOGY SOLUTI": "FIG",
    "SHARPLINK GAMING IN": "SBET",
    "SHARPLINK": "SBET",
    "ISHARES ETHEREUM TRUST": "ETHA",
    "OPENDOOR TECHNOLO": "OPEN-WT",
}

# 期权前缀 — 归类到 OPTIONS-XXX
OPTIONS_PREFIXES = ("PUT ", "CALL ")

OUTPUT_FILE = "state/broker_pnl.json"

# ============================================================
# Schwab CSV 解析
# ============================================================

def _parse_description(desc: str):
    """从1099-B描述提取 (数量, ticker)
    例: '50.00 ALPHABET INC            CLASS            CLASS A' → (50.0, 'GOOGL')
    """
    desc = desc.strip()
    # 提取前面的数量
    m = re.match(r"^([\d.]+)\s+(.+)$", desc)
    if not m:
        return None, None
    qty = float(m.group(1))
    name_raw = m.group(2)

    # 清理多余空格, 去掉CLASS/ADR等后缀信息
    name_clean = re.sub(r"\s+", " ", name_raw).strip()

    # 期权: PUT/CALL开头 → 归类为 OPTIONS
    for prefix in OPTIONS_PREFIXES:
        if name_clean.upper().startswith(prefix):
            return qty, "OPTIONS"

    # 尝试匹配: 从最长前缀开始匹配
    for known_name, ticker in NAME_TO_TICKER.items():
        if name_clean.upper().startswith(known_name.upper()):
            return qty, ticker

    # 未匹配 — 返回原始名称作为ticker
    # 取第一个有意义的词组(去掉CLASS/ADR等)
    fallback = re.sub(r"\s+(CLASS|FSPONSORED|ADR|REPS|ORD|SHS|INC).*", "", name_clean, flags=re.IGNORECASE).strip()
    return qty, fallback or name_clean


def _parse_dollar(val: str) -> float:
    """'$1,234.56' or '1234.56' → 1234.56"""
    if not val:
        return 0.0
    return float(val.replace("$", "").replace(",", "").strip() or "0")


def parse_schwab_csv(filepath: str) -> dict:
    """解析单个Schwab 1099-B CSV，返回按品种汇总的P&L"""
    result = {}
    in_1099b = False

    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue

            # 找到1099-B区域开始
            if row[0].strip() == "Form 1099 B":
                in_1099b = True
                continue

            if not in_1099b:
                continue

            # 跳过列头行
            if row[0].strip() in ("1a", "Description of property (Example 100 sh. XYZ Co.)"):
                continue

            # 数据行: 至少需要5列 (1a描述, 1b日期, 1c日期, 1d收入, 1e成本)
            if len(row) < 7:
                continue

            desc = row[0].strip()
            if not desc or not desc[0].isdigit():
                continue

            qty, ticker = _parse_description(desc)
            if not ticker:
                continue

            proceeds = _parse_dollar(row[3])
            cost_basis = _parse_dollar(row[4])
            wash_sale = _parse_dollar(row[6])

            if ticker not in result:
                result[ticker] = {
                    "lots": 0,
                    "proceeds": 0.0,
                    "cost_basis": 0.0,
                    "realized_pnl": 0.0,
                    "wash_sale": 0.0,
                }

            result[ticker]["lots"] += 1
            result[ticker]["proceeds"] += proceeds
            result[ticker]["cost_basis"] += cost_basis
            result[ticker]["realized_pnl"] += (proceeds - cost_basis)
            result[ticker]["wash_sale"] += wash_sale

    # 四舍五入
    for ticker in result:
        for k in ("proceeds", "cost_basis", "realized_pnl", "wash_sale"):
            result[ticker][k] = round(result[ticker][k], 2)

    return result


def parse_all_schwab() -> dict:
    """扫描AIPro/*.CSV，合并所有Schwab数据"""
    csv_files = glob.glob("AIPro/*.CSV") + glob.glob("AIPro/*.csv")
    csv_files = list(set(csv_files))  # 去重

    merged = {}
    for fpath in csv_files:
        try:
            data = parse_schwab_csv(fpath)
            for ticker, info in data.items():
                if ticker not in merged:
                    merged[ticker] = {"lots": 0, "proceeds": 0.0, "cost_basis": 0.0,
                                      "realized_pnl": 0.0, "wash_sale": 0.0}
                for k in ("lots", "proceeds", "cost_basis", "realized_pnl", "wash_sale"):
                    merged[ticker][k] += info[k]
        except Exception as e:
            print(f"[SYS-029] Schwab CSV解析失败 {fpath}: {e}")

    # 四舍五入
    for ticker in merged:
        for k in ("proceeds", "cost_basis", "realized_pnl", "wash_sale"):
            merged[ticker][k] = round(merged[ticker][k], 2)

    return merged


# ============================================================
# Coinbase fills (复用 coinbase_sync_v6.py 的 auth)
# ============================================================

def _coinbase_available() -> bool:
    """检查coinbase依赖是否可用"""
    try:
        import jwt
        from cryptography.hazmat.primitives import serialization
        import requests
        return True
    except ImportError:
        return False


def fetch_coinbase_fills() -> dict:
    """拉取Coinbase成交记录，FIFO匹配算realized P&L"""
    if not _coinbase_available():
        print("[SYS-029] Coinbase依赖缺失(jwt/cryptography/requests)，跳过")
        return {}

    try:
        # 动态导入coinbase_sync_v6的auth函数
        import importlib.util
        spec = importlib.util.spec_from_file_location("coinbase_sync_v6", "coinbase_sync_v6.py")
        cb = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cb)

        # 拉取fills: 最近90天
        all_fills = []
        cursor = None
        for _ in range(10):  # 最多10页
            path = "/api/v3/brokerage/orders/historical/fills?limit=100"
            if cursor:
                path += f"&cursor={cursor}"
            resp = cb.api_request("GET", path)
            if not resp:
                break
            fills = resp.get("fills", [])
            if not fills:
                break
            all_fills.extend(fills)
            cursor = resp.get("cursor")
            if not cursor:
                break

        if not all_fills:
            return {}

        # 按品种分组 FIFO 匹配
        by_product = {}
        for fill in all_fills:
            product = fill.get("product_id", "")
            if product not in by_product:
                by_product[product] = {"buys": [], "sells": []}

            side = fill.get("side", "").upper()
            size = float(fill.get("size", 0))
            price = float(fill.get("price", 0))
            fee = float(fill.get("commission", 0))

            entry = {"size": size, "price": price, "fee": fee}
            if side == "BUY":
                by_product[product]["buys"].append(entry)
            elif side == "SELL":
                by_product[product]["sells"].append(entry)

        # FIFO 匹配
        result = {}
        for product, sides in by_product.items():
            buys = list(sides["buys"])  # copy
            total_pnl = 0.0
            total_fees = 0.0
            matched_sells = 0
            total_buys = len(buys)

            for sell in sides["sells"]:
                sell_size = sell["size"]
                sell_revenue = sell_size * sell["price"]
                total_fees += sell["fee"]
                matched_sells += 1

                # FIFO match buys
                cost = 0.0
                remaining = sell_size
                while remaining > 0 and buys:
                    buy = buys[0]
                    matched = min(remaining, buy["size"])
                    cost += matched * buy["price"]
                    total_fees += buy["fee"] * (matched / buy["size"]) if buy["size"] > 0 else 0
                    buy["size"] -= matched
                    remaining -= matched
                    if buy["size"] <= 1e-10:
                        buys.pop(0)

                total_pnl += (sell_revenue - cost)

            if matched_sells > 0 or total_buys > 0:
                result[product] = {
                    "buys": total_buys,
                    "sells": matched_sells,
                    "realized_pnl": round(total_pnl, 2),
                    "fees": round(total_fees, 2),
                }

        return result

    except Exception as e:
        print(f"[SYS-029] Coinbase fills拉取异常: {e}")
        return {}


# ============================================================
# 主逻辑
# ============================================================

def run():
    """执行对账，输出 state/broker_pnl.json"""
    now = datetime.now(NY_TZ)
    ts = now.strftime("%Y-%m-%dT%H:%M:%S%z")
    # 格式化timezone offset: +0500 → +05:00
    ts = ts[:-2] + ":" + ts[-2:]

    # Schwab
    schwab_data = parse_all_schwab()
    schwab_total = sum(v["realized_pnl"] for v in schwab_data.values())

    # Coinbase
    cb_data = fetch_coinbase_fills()
    cb_total = sum(v["realized_pnl"] for v in cb_data.values())

    output = {
        "updated_at": ts,
        "schwab": {
            "symbols": schwab_data,
            "total_realized": round(schwab_total, 2),
        },
        "coinbase": {
            "symbols": cb_data,
            "total_realized": round(cb_total, 2),
        },
        "total_pnl": round(schwab_total + cb_total, 2),
    }

    os.makedirs("state", exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"[SYS-029] 对账完成 → {OUTPUT_FILE}")
    print(f"  Schwab: {len(schwab_data)}品种, P&L=${schwab_total:+,.2f}")
    print(f"  Coinbase: {len(cb_data)}品种, P&L=${cb_total:+,.2f}")
    print(f"  Total: ${schwab_total + cb_total:+,.2f}")

    return output


if __name__ == "__main__":
    run()
