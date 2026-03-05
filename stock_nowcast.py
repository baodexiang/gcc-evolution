"""
stock_nowcast.py — Agentic Nowcasting (arXiv:2601.11958)
=========================================================
LLM自主搜网给品种打分(-5~+5)，不需历史训练数据。
盘后4:30pm ET运行，T+1验价算准确率。

Phase 1: 仅日志+邮件，不影响交易决策。

GCC-0008 KEY-005-NC
"""

import json
import os
import time
import logging
import ssl
import smtplib
from datetime import datetime, date, timedelta
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger("nowcast")

# ============================================================
# 路径
# ============================================================
ROOT = Path(__file__).parent
STATE_DIR = ROOT / "state"
LOG_FILE = STATE_DIR / "nowcast_log.jsonl"
POOLS_FILE = STATE_DIR / "nowcast_pools.json"

# ============================================================
# 品种配置
# ============================================================
TRADING_POOL = [
    ("TSLA", "Tesla Inc"),
    ("COIN", "Coinbase Global"),
    ("RDDT", "Reddit Inc"),
    ("NBIS", "Nebius Group"),
    ("CRWV", "CrowdStrike Holdings"),
    ("RKLB", "Rocket Lab USA"),
    ("HIMS", "Hims & Hers Health"),
    ("OPEN", "Opendoor Technologies"),
    ("AMD", "Advanced Micro Devices"),
    ("ONDS", "Ondas Holdings"),
    ("PLTR", "Palantir Technologies"),
]

CRYPTO_POOL = [
    ("BTC-USD", "Bitcoin"),
    ("ETH-USD", "Ethereum"),
    ("SOL-USD", "Solana"),
    ("ZEC-USD", "Zcash"),
]

# ============================================================
# LLM配置
# ============================================================
NC_MODEL = os.environ.get("NC_MODEL", "gpt-4o-search-preview")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

# ============================================================
# 邮件配置 (复用主系统)
# ============================================================
EMAIL_ENABLED = True
EMAIL_SMTP_SERVER = "smtp.gmail.com"
EMAIL_SMTP_PORT = 587
EMAIL_SMTP_TIMEOUT = 30
EMAIL_FROM = "aistockllmpro@gmail.com"
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
EMAIL_TO = ["baodexiang@hotmail.com"]

NY_TZ = ZoneInfo("America/New_York")


def _log(msg: str):
    """输出到可用日志"""
    try:
        from llm_server_v3640 import log_to_server
        log_to_server(msg)
    except Exception:
        logger.info(msg)


# ============================================================
# 核心: 单品种评分
# ============================================================
PROMPT_TEMPLATE = """Today is {date}. Evaluate {symbol} ({company}) for a 1-3 day outlook.

Search the web for:
- Latest news, press releases, earnings updates
- Analyst ratings and price target changes
- Sector/industry trends affecting this stock
- Any upcoming catalysts (earnings dates, FDA decisions, product launches)
- Recent insider trading or institutional flow
- Reddit sentiment (r/wallstreetbets, r/stocks, r/investing) — retail trader buzz

Rate from -5 (very bearish) to +5 (very bullish).
0 means neutral/no clear direction.

Output ONLY a JSON object:
{{"score": <int -5 to 5>, "confidence": <float 0.0 to 1.0>, "reasoning": "<1-2 sentences>"}}
"""


def nowcast_single(symbol: str, company: str, target_date: str = None) -> dict:
    """
    单品种Nowcast评分。
    使用OpenAI web search模型，让LLM自主搜网评分。
    """
    if not OPENAI_API_KEY:
        return {"error": "OPENAI_API_KEY not set"}

    if target_date is None:
        target_date = datetime.now(NY_TZ).strftime("%Y-%m-%d")

    prompt = PROMPT_TEMPLATE.format(date=target_date, symbol=symbol, company=company)

    try:
        from openai import OpenAI
        import httpx
        client = OpenAI(
            api_key=OPENAI_API_KEY,
            timeout=httpx.Timeout(60.0, connect=10.0),
            max_retries=2,
        )

        response = client.chat.completions.create(
            model=NC_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_completion_tokens=200,
        )

        text = response.choices[0].message.content or ""
        # 提取JSON
        text = text.strip()
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        result = json.loads(text)
        # 校验
        score = int(result.get("score", 0))
        score = max(-5, min(5, score))
        confidence = float(result.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))
        reasoning = str(result.get("reasoning", ""))[:200]

        return {
            "symbol": symbol,
            "date": target_date,
            "score": score,
            "confidence": round(confidence, 3),
            "reasoning": reasoning,
            "model": NC_MODEL,
            "actual_return": None,
            "backfilled": False,
        }

    except json.JSONDecodeError as e:
        _log(f"[NC][ERROR] {symbol} JSON解析失败: {e} raw={text[:100]}")
        return {"symbol": symbol, "date": target_date, "error": f"JSON parse: {e}"}
    except Exception as e:
        _log(f"[NC][ERROR] {symbol} API异常: {e}")
        return {"symbol": symbol, "date": target_date, "error": str(e)}


def nowcast_all(pool: str = "all") -> list:
    """
    批量评分。
    pool: "trading" | "crypto" | "all"
    """
    symbols = []
    if pool in ("trading", "all"):
        symbols.extend(TRADING_POOL)
    if pool in ("crypto", "all"):
        symbols.extend(CRYPTO_POOL)

    results = []
    today = datetime.now(NY_TZ).strftime("%Y-%m-%d")

    for symbol, company in symbols:
        # 检查今日是否已评分(幂等)
        if _already_scored(symbol, today):
            _log(f"[NC] {symbol} 今日已评分, 跳过")
            continue

        result = nowcast_single(symbol, company, today)
        if "error" not in result:
            _append_log(result)
            results.append(result)
            _log(f"[NC] {symbol} score={result['score']:+d} conf={result['confidence']:.2f} "
                 f"reason={result['reasoning'][:60]}")
        else:
            _log(f"[NC] {symbol} 失败: {result.get('error', 'unknown')}")

        # 限速: 避免API rate limit
        time.sleep(1.0)

    _log(f"[NC] 批量评分完成: {len(results)}/{len(symbols)}个品种")
    return results


# ============================================================
# T+1 验价回填
# ============================================================
def backfill_returns(lookback_days: int = 7) -> int:
    """
    回填已到期记录的actual_return。
    对date <= 今天-1的记录(未回填), 用yfinance取收盘价算收益率。
    """
    if not LOG_FILE.exists():
        return 0

    import yfinance as yf

    today = datetime.now(NY_TZ).date()
    cutoff = today - timedelta(days=1)  # 至少T+1才回填

    entries = _load_all_logs()
    updated = 0

    # 按symbol分组待回填记录
    pending = {}
    for i, entry in enumerate(entries):
        if entry.get("backfilled") or entry.get("error"):
            continue
        entry_date = date.fromisoformat(entry["date"])
        if entry_date > cutoff:
            continue
        sym = entry["symbol"]
        if sym not in pending:
            pending[sym] = []
        pending[sym].append((i, entry))

    for sym, items in pending.items():
        try:
            # 拉取足够的历史数据
            start_date = min(date.fromisoformat(e["date"]) for _, e in items) - timedelta(days=1)
            end_date = today + timedelta(days=1)
            df = yf.download(sym, start=start_date.isoformat(),
                             end=end_date.isoformat(), progress=False)
            if df.empty:
                continue

            closes = df["Close"].squeeze()

            for idx, entry in items:
                entry_date = date.fromisoformat(entry["date"])
                # T日收盘 vs T+1收盘
                t0_candidates = closes[closes.index.date <= entry_date]
                t1_candidates = closes[closes.index.date > entry_date]

                if t0_candidates.empty or t1_candidates.empty:
                    continue

                t0_close = float(t0_candidates.iloc[-1])
                t1_close = float(t1_candidates.iloc[0])

                if t0_close > 0:
                    ret = (t1_close - t0_close) / t0_close
                    entries[idx]["actual_return"] = round(ret, 6)
                    entries[idx]["backfilled"] = True
                    updated += 1

        except Exception as e:
            _log(f"[NC][BACKFILL] {sym} 异常: {e}")

    if updated > 0:
        _save_all_logs(entries)
        _log(f"[NC][BACKFILL] 回填{updated}条记录")

    return updated


# ============================================================
# 准确率统计
# ============================================================
def calc_accuracy(lookback_days: int = 30) -> dict:
    """
    计算Nowcast准确率:
    - hit_rate: score方向与actual_return方向一致的比率
    - top5_avg_return: score最高5个品种的平均实际收益
    - asymmetry: 做多命中率 vs 做空命中率
    """
    if not LOG_FILE.exists():
        return {"error": "no data"}

    cutoff = (datetime.now(NY_TZ).date() - timedelta(days=lookback_days)).isoformat()
    entries = [e for e in _load_all_logs()
               if e.get("backfilled") and not e.get("error")
               and e["date"] >= cutoff]

    if not entries:
        return {"total": 0, "hit_rate": 0.0}

    hits = 0
    long_hits = 0
    long_total = 0
    short_hits = 0
    short_total = 0

    for e in entries:
        score = e["score"]
        ret = e["actual_return"]
        if score == 0:
            continue  # neutral不算

        correct = (score > 0 and ret > 0) or (score < 0 and ret < 0)
        if correct:
            hits += 1

        if score > 0:
            long_total += 1
            if ret > 0:
                long_hits += 1
        elif score < 0:
            short_total += 1
            if ret < 0:
                short_hits += 1

    non_neutral = len([e for e in entries if e["score"] != 0])

    # Top 5得分最高的品种平均收益
    sorted_entries = sorted(entries, key=lambda e: e["score"], reverse=True)
    top5 = sorted_entries[:5]
    top5_avg = sum(e["actual_return"] for e in top5) / len(top5) if top5 else 0.0

    return {
        "total": len(entries),
        "non_neutral": non_neutral,
        "hit_rate": round(hits / non_neutral, 4) if non_neutral > 0 else 0.0,
        "long_hit_rate": round(long_hits / long_total, 4) if long_total > 0 else 0.0,
        "short_hit_rate": round(short_hits / short_total, 4) if short_total > 0 else 0.0,
        "top5_avg_return": round(top5_avg, 6),
        "lookback_days": lookback_days,
    }


# ============================================================
# 邮件报告
# ============================================================
def send_nowcast_email(results: list, accuracy: dict = None):
    """每日Nowcast结果邮件。"""
    if not EMAIL_ENABLED or not EMAIL_PASSWORD or not results:
        return

    today = datetime.now(NY_TZ).strftime("%Y-%m-%d")
    subject = f"[NC] Nowcast评分 {today} ({len(results)}品种)"

    lines = [
        f"Agentic Nowcasting Report — {today}",
        "=" * 50,
        "",
        f"{'Symbol':<10} {'Score':>6} {'Conf':>6}  Reasoning",
        "-" * 70,
    ]

    # 按score排序(高到低)
    sorted_results = sorted(results, key=lambda r: r.get("score", 0), reverse=True)
    for r in sorted_results:
        score = r.get("score", 0)
        conf = r.get("confidence", 0)
        reason = r.get("reasoning", "")[:50]
        score_str = f"{score:+d}"
        lines.append(f"{r['symbol']:<10} {score_str:>6} {conf:>6.2f}  {reason}")

    # 强信号汇总
    strong_bull = [r for r in results if r.get("score", 0) >= 3]
    strong_bear = [r for r in results if r.get("score", 0) <= -3]
    lines.extend([
        "",
        f"Strong Bullish (>=+3): {', '.join(r['symbol'] for r in strong_bull) or 'None'}",
        f"Strong Bearish (<=-3): {', '.join(r['symbol'] for r in strong_bear) or 'None'}",
    ])

    # 准确率(如果有)
    if accuracy and accuracy.get("total", 0) > 0:
        lines.extend([
            "",
            f"--- 近{accuracy['lookback_days']}天准确率 ---",
            f"Hit Rate: {accuracy['hit_rate']:.1%} ({accuracy['non_neutral']}笔)",
            f"Long:  {accuracy['long_hit_rate']:.1%}",
            f"Short: {accuracy['short_hit_rate']:.1%}",
            f"Top5 Avg Return: {accuracy['top5_avg_return']:.4%}",
        ])

    lines.extend(["", f"Model: {NC_MODEL}", "Phase 1: 仅日志, 不影响交易决策"])

    body = "\n".join(lines)

    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = EMAIL_FROM
        msg["To"] = ", ".join(EMAIL_TO)
        msg.set_content(body)

        context = ssl.create_default_context()
        with smtplib.SMTP(EMAIL_SMTP_SERVER, EMAIL_SMTP_PORT, timeout=EMAIL_SMTP_TIMEOUT) as server:
            server.starttls(context=context)
            server.login(EMAIL_FROM, EMAIL_PASSWORD)
            server.send_message(msg)
        _log("[NC][EMAIL] 报告发送成功")
    except Exception as e:
        _log(f"[NC][EMAIL] 发送失败: {e}")


# ============================================================
# 主调度入口 (被_autosave_worker调用)
# ============================================================
def run_daily_nowcast():
    """
    每日盘后调度入口:
    1. 批量评分所有品种
    2. 回填历史记录
    3. 算准确率
    4. 发邮件
    """
    _log("[NC] === 每日Nowcast开始 ===")

    # 1. 评分
    results = nowcast_all("all")

    # 2. 回填
    filled = backfill_returns(lookback_days=7)
    if filled > 0:
        _log(f"[NC] 回填{filled}条历史记录")

    # 3. 准确率
    accuracy = calc_accuracy(lookback_days=30)

    # 4. 邮件
    if results:
        send_nowcast_email(results, accuracy)

    _log(f"[NC] === 每日Nowcast完成: {len(results)}品种评分, "
         f"hit_rate={accuracy.get('hit_rate', 'N/A')} ===")

    return {"scored": len(results), "backfilled": filled, "accuracy": accuracy}


# ============================================================
# 内部工具
# ============================================================
def _already_scored(symbol: str, date_str: str) -> bool:
    """检查今日是否已评分(幂等)。"""
    if not LOG_FILE.exists():
        return False
    try:
        with open(LOG_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                if entry.get("symbol") == symbol and entry.get("date") == date_str:
                    return True
    except Exception:
        pass
    return False


def _append_log(entry: dict):
    """追加一条记录到JSONL。"""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _load_all_logs() -> list:
    """加载全部记录。"""
    if not LOG_FILE.exists():
        return []
    entries = []
    with open(LOG_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return entries


def _save_all_logs(entries: list):
    """覆盖写入全部记录(回填后用)。"""
    with open(LOG_FILE, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ============================================================
# CLI测试入口
# ============================================================
if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "single":
        sym = sys.argv[2] if len(sys.argv) > 2 else "PLTR"
        company = dict(TRADING_POOL + CRYPTO_POOL).get(sym, sym)
        r = nowcast_single(sym, company)
        print(json.dumps(r, indent=2, ensure_ascii=False))
    elif len(sys.argv) > 1 and sys.argv[1] == "backfill":
        n = backfill_returns()
        print(f"Backfilled {n} entries")
    elif len(sys.argv) > 1 and sys.argv[1] == "accuracy":
        acc = calc_accuracy()
        print(json.dumps(acc, indent=2))
    else:
        result = run_daily_nowcast()
        print(json.dumps(result, indent=2))
