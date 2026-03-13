"""
schwab_data_provider.py
Schwab K线数据适配层 - 兼容 yfinance 接口，无缝接入 aipro 系统
版本: v1.1
用途: 替换 price_scan_engine_v21.py / 缠论BS / SuperTrend / N结构 中的 yfinance 数据源

依赖安装:
    uv add schwab-py httpx pandas

系统环境变量（Windows 用户变量，设置后重启终端生效）:
    SCHWAB_APP_KEY       = 你的 App Key
    SCHWAB_APP_SECRET    = 你的 Secret
    SCHWAB_CALLBACK_URL  = https://127.0.0.1
    SCHWAB_TOKEN_PATH    = C:\\Users\\baode\\aibot\\state\\schwab_token.json

首次运行说明:
    1. 运行 python schwab_data_provider.py
    2. 程序自动打印授权 URL
    3. 用浏览器打开，用 Schwab 交易账号（非开发者账号）登录授权
    4. 授权后浏览器跳转空白页，复制地址栏完整 URL 粘贴回终端按回车
    5. Token 自动保存到 SCHWAB_TOKEN_PATH
    6. Refresh Token 7天硬过期 — 每周一 8:00 AM ET 重新授权（运行本脚本即可）

使用方法:
    from schwab_data_provider import get_provider
    df = get_provider().get_kline("TSLA", interval="1d", bars=120)
"""

import os
import sys
import logging
import pathlib
import httpx
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional, Literal

# ─────────────────────────────────────────────
# 配置：全部从系统环境变量读取，无任何硬编码
# ─────────────────────────────────────────────
SCHWAB_APP_KEY    = os.environ.get("SCHWAB_APP_KEY", "")
SCHWAB_APP_SECRET = os.environ.get("SCHWAB_APP_SECRET", "")
SCHWAB_CALLBACK   = os.environ.get("SCHWAB_CALLBACK_URL", "https://127.0.0.1")
SCHWAB_TOKEN_PATH = os.environ.get("SCHWAB_TOKEN_PATH", "")

# ─────────────────────────────────────────────
# 时间粒度映射：yfinance interval -> schwab-py 方法名
# ─────────────────────────────────────────────
INTERVAL_MAP = {
    "1m":  "get_price_history_every_minute",
    "5m":  "get_price_history_every_five_minutes",
    "10m": "get_price_history_every_ten_minutes",
    "15m": "get_price_history_every_fifteen_minutes",
    "30m": "get_price_history_every_thirty_minutes",
    "1d":  "get_price_history_every_day",
    "1wk": "get_price_history_every_week",
}

# 4H 重映射：Schwab 无原生4H，缠论/SuperTrend 用日线替代（精度够用）
# 真正的4H数据继续从 TradingView webhook 拿，Schwab 专注日线和分钟线
INTERVAL_REMAP = {
    "4h": "1d",
}

logger = logging.getLogger("schwab_data_provider")
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [SCHWAB] %(levelname)s %(message)s"
    )


# ─────────────────────────────────────────────
# 启动自检
# ─────────────────────────────────────────────
def _check_env():
    """检查必要环境变量，缺失时给出明确提示后退出"""
    missing = [k for k, v in {
        "SCHWAB_APP_KEY": SCHWAB_APP_KEY,
        "SCHWAB_APP_SECRET": SCHWAB_APP_SECRET,
        "SCHWAB_TOKEN_PATH": SCHWAB_TOKEN_PATH,
    }.items() if not v]

    if missing:
        print("\n" + "=" * 60)
        print("❌ 缺少以下系统环境变量（Windows 用户变量）：")
        for m in missing:
            print(f"   {m}")
        print("\n设置方法：Win+S → 搜索「编辑系统环境变量」→ 用户变量 → 新建")
        print("设置完成后重启终端再运行。")
        print("=" * 60 + "\n")
        sys.exit(1)


# ─────────────────────────────────────────────
# 主类
# ─────────────────────────────────────────────
class SchwabDataProvider:
    """
    Schwab K线数据提供器，接口兼容 yfinance。

    替换现有代码示例：
        # 原来
        df = yf.download("TSLA", period="6mo", interval="1d")
        # 替换（接口完全兼容）
        df = get_provider().download("TSLA", period="6mo", interval="1d")
    """

    def __init__(self, use_cache: bool = True, cache_ttl_minutes: int = 5):
        self._client = None
        self._use_cache = use_cache
        self._cache_ttl = timedelta(minutes=cache_ttl_minutes)
        self._cache: dict[str, tuple[datetime, pd.DataFrame]] = {}

    # ──────────────────────────────────────────
    # Token 年龄检查 — 每周一 8:00 AM ET 重新授权
    # Refresh Token 7天硬过期，提前提醒避免中断
    # ──────────────────────────────────────────
    def check_token_age(self) -> dict:
        """
        检查 Schwab Token 年龄，返回状态信息。
        返回: {"age_hours": float, "expired": bool, "warn": bool, "message": str}
        """
        token_file = pathlib.Path(SCHWAB_TOKEN_PATH) if SCHWAB_TOKEN_PATH else None
        if not token_file or not token_file.exists():
            return {"age_hours": -1, "expired": True, "warn": True,
                    "message": "Token文件不存在，需要首次授权"}
        try:
            import json
            token_data = json.loads(token_file.read_text(encoding="utf-8"))
            # schwab-py 在 token 文件中存 creation_timestamp
            created = token_data.get("creation_timestamp", 0)
            if not created:
                # fallback: 用文件修改时间
                created = token_file.stat().st_mtime
            age_seconds = datetime.now().timestamp() - created
            age_hours = age_seconds / 3600
            age_days = age_hours / 24
            expired = age_days >= 7
            warn = age_days >= 6  # 6天预警
            if expired:
                msg = f"⚠️ Token已过期({age_days:.1f}天)，需要重新授权: python schwab_data_provider.py"
            elif warn:
                msg = f"⚠️ Token即将过期({age_days:.1f}天)，建议周一8AM ET重新授权"
            else:
                msg = f"Token正常({age_days:.1f}天/{age_hours:.0f}h)"
            return {"age_hours": round(age_hours, 1), "expired": expired,
                    "warn": warn, "message": msg}
        except Exception as e:
            return {"age_hours": -1, "expired": False, "warn": True,
                    "message": f"Token检查失败: {e}"}

    # ──────────────────────────────────────────
    # Token 过期前2小时邮件提醒
    # ──────────────────────────────────────────
    _email_sent_flag = None  # 类级别：防止重复发送

    def check_and_notify_token_expiry(self) -> None:
        """
        检查 Token 年龄，过期前2小时发一次邮件提醒。
        由主程序定时调用（如每小时一次）。
        """
        status = self.check_token_age()
        age_hours = status["age_hours"]
        if age_hours < 0:
            return

        # 7天 = 168小时，过期前2小时 = 166小时
        hours_remaining = 168 - age_hours
        if hours_remaining <= 2 and not SchwabDataProvider._email_sent_flag:
            self._send_token_expiry_email(age_hours, hours_remaining)
            SchwabDataProvider._email_sent_flag = True
        elif hours_remaining > 24:
            # Token 刷新后重置标记
            SchwabDataProvider._email_sent_flag = False

    def _send_token_expiry_email(self, age_hours: float, hours_remaining: float) -> None:
        """发送 Token 即将过期的邮件提醒。"""
        try:
            import smtplib
            import ssl
            from email.message import EmailMessage

            subject = f"⚠️ Schwab Token 即将过期 — 剩余{hours_remaining:.1f}小时"
            body = (
                f"Schwab API Token 即将过期：\n\n"
                f"  Token 年龄: {age_hours:.1f} 小时 ({age_hours/24:.1f} 天)\n"
                f"  剩余时间: {hours_remaining:.1f} 小时\n"
                f"  过期时间: 约 {hours_remaining:.0f} 小时后\n\n"
                f"请立即重新授权：\n"
                f"  1. mv state/schwab_token.json state/schwab_token.json.bak\n"
                f"  2. python schwab_data_provider.py\n"
                f"  3. 在浏览器完成 Schwab 登录授权\n"
                f"  4. 复制回调 URL 粘贴回终端\n"
            )

            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = "aistockllmpro@gmail.com"
            msg["To"] = "baodexiang@hotmail.com"
            msg.set_content(body)

            context = ssl.create_default_context()
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
                server.starttls(context=context)
                server.login("aistockllmpro@gmail.com", "ficw ovws zvzb qmfs")
                server.send_message(msg)

            logger.info("[SCHWAB] Token过期提醒邮件已发送 (剩余%.1f小时)", hours_remaining)
        except Exception as e:
            logger.warning("[SCHWAB] Token过期提醒邮件发送失败: %s", e)

    # ──────────────────────────────────────────
    # 客户端初始化（懒加载，首次调用时触发）
    # ──────────────────────────────────────────
    def _get_client(self):
        if self._client is not None:
            return self._client

        # 重新初始化client时清除account_hash缓存，保证生命周期同步
        self._account_hash = None

        _check_env()

        token_file = pathlib.Path(SCHWAB_TOKEN_PATH)
        first_time = not token_file.exists()

        # Token 年龄检查
        if not first_time:
            status = self.check_token_age()
            if status["expired"]:
                logger.error(status["message"])
                first_time = True  # 强制重新授权流程
            elif status["warn"]:
                logger.warning(status["message"])

        if first_time:
            print("\n" + "=" * 60)
            print("📋 首次授权（只需做一次）：")
            print("  1. 程序会打印一个授权链接")
            print("  2. 复制到浏览器，用 Schwab 交易账号登录并授权")
            print("  3. 授权后浏览器跳转到空白页面")
            print("  4. 复制浏览器地址栏完整 URL，粘贴回终端按回车")
            print(f"  5. Token 将保存至：{SCHWAB_TOKEN_PATH}")
            print("=" * 60 + "\n")

        try:
            from schwab.auth import easy_client, client_from_manual_flow
            callback_url = (SCHWAB_CALLBACK or "").strip().replace("：", ":")
            if callback_url and "://" not in callback_url:
                callback_url = f"https://{callback_url}"

            try:
                self._client = easy_client(
                    api_key=SCHWAB_APP_KEY,
                    app_secret=SCHWAB_APP_SECRET,
                    callback_url=callback_url,
                    token_path=SCHWAB_TOKEN_PATH,
                )
            except PermissionError as e:
                logger.warning(f"easy_client失败，切换手动授权流: {e}")
                self._client = client_from_manual_flow(
                    api_key=SCHWAB_APP_KEY,
                    app_secret=SCHWAB_APP_SECRET,
                    callback_url=callback_url,
                    token_path=SCHWAB_TOKEN_PATH,
                )
            if first_time:
                print(f"\n✅ 授权成功！Token 已保存，后续运行无需重复授权。\n")
            logger.info("Schwab client 初始化成功")
        except Exception as e:
            logger.error(f"Schwab client 初始化失败: {e}")
            raise

        return self._client

    # ──────────────────────────────────────────
    # GCC-0256 S2: 直接交易接口
    # ──────────────────────────────────────────
    _account_hash: Optional[str] = None

    def _get_account_hash(self) -> str:
        """获取Schwab账户hash (首次调用缓存)"""
        if self._account_hash:
            return self._account_hash
        client = self._get_client()
        resp = client.get_account_numbers()
        if resp.status_code == 200:
            accounts = resp.json()
            if accounts:
                hash_value = accounts[0].get("hashValue", "")
                if not hash_value:
                    raise RuntimeError("[SCHWAB] hashValue字段为空，账户数据异常")
                self._account_hash = hash_value
                logger.info(f"[SCHWAB] 获取account_hash成功: {self._account_hash[:8]}...")
                return self._account_hash
        raise RuntimeError(f"[SCHWAB] 获取account_hash失败: HTTP {resp.status_code}")

    def get_account_balance(self) -> dict:
        """获取账户余额信息 (GCC-0256 S4: 期权下单前资金检查)

        Returns:
            {"available_funds": float, "buying_power": float, "cash": float}
        """
        try:
            client = self._get_client()
            account_hash = self._get_account_hash()
            resp = client.get_account(account_hash, fields=[client.Account.Fields.POSITIONS])
            if resp.status_code == 200:
                data = resp.json()
                bal = data.get("securitiesAccount", {}).get("currentBalances", {})
                return {
                    "available_funds": bal.get("availableFunds", 0),
                    "buying_power": bal.get("buyingPower", 0),
                    "cash": bal.get("cashBalance", 0),
                    "option_buying_power": bal.get("optionBuyingPower", bal.get("buyingPower", 0)),
                }
            logger.error(f"[SCHWAB] get_account_balance失败: HTTP {resp.status_code}")
            return {"available_funds": 0, "buying_power": 0, "cash": 0, "option_buying_power": 0}
        except Exception as e:
            logger.error(f"[SCHWAB] get_account_balance异常: {e}")
            return {"available_funds": 0, "buying_power": 0, "cash": 0, "option_buying_power": 0}

    def place_equity_order(self, symbol: str, action: str, quantity: int,
                           order_type: str = "MARKET", dry_run: bool = False) -> dict:
        """
        Schwab直连下单 (GCC-0256 S2)

        Args:
            symbol: 股票代码, 如 "TSLA"
            action: "BUY" 或 "SELL"
            quantity: 股数
            order_type: "MARKET" (默认) 或 "LIMIT"
            dry_run: True=preview_order干跑, False=真实下单

        Returns:
            {"success": True, "order_id": str, ...} 或 {"success": False, "error": str}
        """
        try:
            from schwab.orders.equities import equity_buy_market, equity_sell_market

            account_hash = self._get_account_hash()
            client = self._get_client()

            if action == "BUY":
                order_spec = equity_buy_market(symbol, quantity)
            elif action == "SELL":
                order_spec = equity_sell_market(symbol, quantity)
            else:
                return {"success": False, "error": f"无效action: {action}"}

            if dry_run:
                resp = client.preview_order(account_hash, order_spec)
                logger.info(f"[SCHWAB] preview_order {symbol} {action} qty={quantity} → HTTP {resp.status_code}")
                return {
                    "success": resp.status_code == 200,
                    "dry_run": True,
                    "status_code": resp.status_code,
                    "symbol": symbol,
                    "action": action,
                    "quantity": quantity,
                }

            resp = client.place_order(account_hash, order_spec)
            # place_order成功返回201, order_id在Location header中
            if resp.status_code == 201:
                location = resp.headers.get("Location", "")
                order_id = location.split("/")[-1] if location else ""
                logger.info(f"[SCHWAB] place_order成功 {symbol} {action} qty={quantity} order_id={order_id}")
                return {
                    "success": True,
                    "order_id": order_id,
                    "symbol": symbol,
                    "action": action,
                    "quantity": quantity,
                }
            else:
                error_body = ""
                try:
                    error_body = resp.json()
                except Exception:
                    error_body = resp.text[:300]
                logger.error(f"[SCHWAB] place_order失败 {symbol} {action} HTTP {resp.status_code}: {error_body}")
                return {
                    "success": False,
                    "error": f"HTTP {resp.status_code}: {error_body}",
                    "symbol": symbol,
                    "action": action,
                }
        except Exception as e:
            logger.error(f"[SCHWAB] place_equity_order异常 {symbol} {action}: {e}")
            return {"success": False, "error": str(e), "symbol": symbol, "action": action}

    def get_equity_order(self, order_id: str) -> dict:
        """查询订单状态"""
        try:
            account_hash = self._get_account_hash()
            client = self._get_client()
            # schwab-py: get_order(order_id, account_hash) — 注意参数顺序与place_order不同
            resp = client.get_order(int(order_id), account_hash)
            if resp.status_code == 200:
                return resp.json()
            return {"error": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"error": str(e)}

    def cancel_equity_order(self, order_id: str) -> dict:
        """取消订单"""
        try:
            account_hash = self._get_account_hash()
            client = self._get_client()
            # schwab-py: cancel_order(order_id, account_hash) — 注意参数顺序
            resp = client.cancel_order(int(order_id), account_hash)
            return {"success": resp.status_code in (200, 204), "status_code": resp.status_code}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ──────────────────────────────────────────
    # 交易历史 (券商对账用)
    # ──────────────────────────────────────────
    def get_transactions(self, days: int = 60) -> list:
        """拉取最近N天的TRADE类型交易记录。

        Returns:
            [{symbol, action, qty, price, amount, fees, date, time, order_id, asset_type}, ...]
        """
        from datetime import date as _date
        try:
            from schwab.client import Client as _C
            client = self._get_client()
            account_hash = self._get_account_hash()
            end = _date.today()
            start = end - timedelta(days=days)
            resp = client.get_transactions(
                account_hash,
                start_date=start,
                end_date=end,
                transaction_types=[_C.Transactions.TransactionType.TRADE],
            )
            if resp.status_code != 200:
                logger.error("[SCHWAB] get_transactions HTTP %d", resp.status_code)
                return []
            raw = resp.json()
            if not isinstance(raw, list):
                return []

            trades = []
            for tx in raw:
                trade_date = tx.get("tradeDate", "")[:10]  # "2026-03-12"
                trade_time = tx.get("time", "")
                order_id = str(tx.get("orderId", ""))
                net_amount = float(tx.get("netAmount", 0))
                # 提取EQUITY/OPTION条目
                for item in tx.get("transferItems", []):
                    inst = item.get("instrument", {})
                    asset_type = inst.get("assetType", "")
                    if asset_type in ("EQUITY", "OPTION"):
                        symbol = inst.get("symbol", "")
                        qty = abs(float(item.get("amount", 0)))
                        price = float(item.get("price", 0))
                        effect = item.get("positionEffect", "")
                        action = "BUY" if effect == "OPENING" else "SELL" if effect == "CLOSING" else effect
                        cost = float(item.get("cost", 0))
                        # 提取费用
                        fees = sum(
                            abs(float(fi.get("cost", 0)))
                            for fi in tx.get("transferItems", [])
                            if fi.get("instrument", {}).get("assetType") == "CURRENCY"
                            and fi.get("feeType") in ("COMMISSION", "SEC_FEE", "TAF_FEE", "OPT_REG_FEE")
                        )
                        trades.append({
                            "symbol": symbol,
                            "action": action,
                            "qty": qty,
                            "price": round(price, 4),
                            "amount": round(abs(cost), 2),
                            "fees": round(fees, 4),
                            "net_amount": round(net_amount, 2),
                            "date": trade_date,
                            "time": trade_time,
                            "order_id": order_id,
                            "asset_type": "option" if asset_type == "OPTION" else "stock",
                        })
            trades.sort(key=lambda t: t["time"])
            logger.info("[SCHWAB] get_transactions: %d trades in %d days", len(trades), days)
            return trades
        except Exception as e:
            logger.error("[SCHWAB] get_transactions error: %s", e)
            return []

    # ──────────────────────────────────────────
    # 核心接口
    # ──────────────────────────────────────────
    def get_kline(
        self,
        symbol: str,
        interval: Literal["1m", "5m", "10m", "15m", "30m", "4h", "1d", "1wk"] = "1d",
        bars: int = 120,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        extended_hours: bool = False,
    ) -> pd.DataFrame:
        """
        获取K线，返回标准 DataFrame：
            index:   DatetimeIndex (UTC)
            columns: open, high, low, close, volume

        参数:
            symbol         - 股票代码，如 "TSLA"
            interval       - 时间粒度（同 yfinance）
            bars           - 返回根数（不指定 start/end 时使用）
            start / end    - 精确时间范围（优先于 bars）
            extended_hours - 是否包含盘前盘后数据
        """
        cache_key = f"{symbol}_{interval}_{bars}"
        if self._use_cache and cache_key in self._cache:
            ts, cached_df = self._cache[cache_key]
            if datetime.now() - ts < self._cache_ttl:
                logger.debug(f"命中缓存: {cache_key}")
                return cached_df.copy()

        # 4H 重映射
        effective_interval = INTERVAL_REMAP.get(interval, interval)
        if effective_interval != interval:
            logger.info(f"[{symbol}] interval {interval} -> {effective_interval}（Schwab无原生4H）")

        df = self._fetch(symbol, effective_interval, bars, start, end, extended_hours)

        if df is not None and not df.empty and self._use_cache:
            self._cache[cache_key] = (datetime.now(), df)

        return df if df is not None else pd.DataFrame()

    # ──────────────────────────────────────────
    # 批量获取（多标的，用于外挂扫描循环）
    # ──────────────────────────────────────────
    def get_kline_batch(
        self,
        symbols: list,
        interval: str = "1d",
        bars: int = 120,
    ) -> dict:
        """
        批量获取多标的K线，返回 {symbol: DataFrame}
        对应 price_scan_engine_v21 的外挂扫描场景
        """
        result = {}
        for sym in symbols:
            try:
                df = self.get_kline(sym, interval, bars)
                if not df.empty:
                    result[sym] = df
                    logger.info(f"  {sym}: {len(df)}根 [{interval}] 最新={df.index[-1].date()}")
                else:
                    logger.warning(f"  {sym}: 返回空数据")
            except Exception as e:
                logger.error(f"  {sym} 获取失败: {e}")
        return result

    # ──────────────────────────────────────────
    # 实时报价 + VWAP 计算（docx P0）
    # ──────────────────────────────────────────
    def get_quote(self, symbol: str) -> dict:
        """
        获取实时报价扩展字段。
        返回: {last, bid, ask, open, high, low, close_prev, volume,
               week52_high, week52_low, pe_ratio, vwap, vwap_bias}
        vwap_bias: "ABOVE" (价格在VWAP上方) / "BELOW" / "AT"
        """
        client = self._get_client()
        try:
            resp = client.get_quote(symbol)
            assert resp.status_code == 200, f"HTTP {resp.status_code}"
            data = resp.json().get(symbol, {})
            quote = data.get("quote", {})
            fundamental = data.get("fundamental", {})

            last = float(quote.get("lastPrice", 0))
            high = float(quote.get("highPrice", 0))
            low = float(quote.get("lowPrice", 0))
            volume = int(quote.get("totalVolume", 0))

            # VWAP 计算: 用日内分钟线 typical_price × volume
            vwap = self._calc_intraday_vwap(symbol)
            if vwap <= 0 and high > 0 and low > 0:
                # fallback: 典型价格近似
                vwap = (high + low + last) / 3

            # vwap_bias: 当前价与VWAP的关系
            if vwap > 0 and last > 0:
                pct_diff = (last - vwap) / vwap
                if pct_diff > 0.002:
                    vwap_bias = "ABOVE"
                elif pct_diff < -0.002:
                    vwap_bias = "BELOW"
                else:
                    vwap_bias = "AT"
            else:
                vwap_bias = "UNKNOWN"

            result = {
                "symbol": symbol,
                "last": last,
                "bid": float(quote.get("bidPrice", 0)),
                "ask": float(quote.get("askPrice", 0)),
                "open": float(quote.get("openPrice", 0)),
                "high": high,
                "low": low,
                "close_prev": float(quote.get("closePrice", 0)),
                "volume": volume,
                "week52_high": float(quote.get("52WeekHigh", 0)),
                "week52_low": float(quote.get("52WeekLow", 0)),
                "pe_ratio": float(fundamental.get("peRatio", 0)),
                "vwap": round(vwap, 4),
                "vwap_bias": vwap_bias,
            }
            logger.info("[SCHWAB] quote %s: last=%.2f vwap=%.2f bias=%s",
                        symbol, last, vwap, vwap_bias)
            return result
        except Exception as e:
            logger.warning("[SCHWAB] get_quote %s failed: %s", symbol, e)
            return {"symbol": symbol, "last": 0, "vwap": 0, "vwap_bias": "UNKNOWN"}

    def _calc_intraday_vwap(self, symbol: str) -> float:
        """用日内5分钟K线计算精确VWAP。"""
        try:
            df = self.get_kline(symbol, interval="5m", bars=80)
            if df is None or df.empty:
                return 0.0
            # typical_price = (H + L + C) / 3
            tp = (df["high"] + df["low"] + df["close"]) / 3
            vol = df["volume"]
            total_tpv = (tp * vol).sum()
            total_vol = vol.sum()
            if total_vol <= 0:
                return 0.0
            return float(total_tpv / total_vol)
        except Exception:
            return 0.0

    def get_quote_batch(self, symbols: list) -> dict:
        """批量获取多标的报价+VWAP，返回 {symbol: quote_dict}。"""
        result = {}
        for sym in symbols:
            result[sym] = self.get_quote(sym)
        return result

    # ──────────────────────────────────────────
    # yfinance 兼容接口（直接替换 yf.download）
    # ──────────────────────────────────────────
    def download(
        self,
        symbol: str,
        period: str = "6mo",
        interval: str = "1d",
    ) -> pd.DataFrame:
        """
        兼容 yf.download(symbol, period=..., interval=...) 调用签名
        现有代码只需改一行导入即可完成替换
        """
        bars = _period_to_bars(period, interval)
        return self.get_kline(symbol, interval, bars)

    # ──────────────────────────────────────────
    # 内部：实际调用 schwab-py
    # ──────────────────────────────────────────
    def _fetch(
        self,
        symbol: str,
        interval: str,
        bars: int,
        start: Optional[datetime],
        end: Optional[datetime],
        extended_hours: bool,
    ) -> Optional[pd.DataFrame]:
        client = self._get_client()

        method_name = INTERVAL_MAP.get(interval)
        if not method_name:
            raise ValueError(
                f"不支持的粒度: '{interval}'，支持的值: {list(INTERVAL_MAP.keys())}"
            )

        method = getattr(client, method_name)

        if start is None and end is None:
            end = datetime.now()
            start = _bars_to_start(bars, interval, end)

        try:
            resp = method(
                symbol,
                start_datetime=start,
                end_datetime=end,
                need_extended_hours_data=extended_hours,
            )
            assert resp.status_code == httpx.codes.OK, \
                f"HTTP {resp.status_code}: {resp.text[:200]}"
            data = resp.json()
        except AssertionError as e:
            logger.error(f"[{symbol} {interval}] API 错误: {e}")
            return None
        except Exception as e:
            logger.error(f"[{symbol} {interval}] 请求异常: {e}")
            return None

        candles = data.get("candles", [])
        if not candles:
            logger.warning(f"[{symbol} {interval}] API 返回空 candles")
            return pd.DataFrame()

        df = pd.DataFrame(candles)
        df["datetime"] = pd.to_datetime(df["datetime"], unit="ms", utc=True)
        df = df.set_index("datetime").sort_index()
        df = df[["open", "high", "low", "close", "volume"]]

        # 截取最新 bars 根
        if len(df) > bars:
            df = df.iloc[-bars:]

        logger.info(
            f"[{symbol} {interval}] {len(df)}根  "
            f"{df.index[0].date()} -> {df.index[-1].date()}  "
            f"最新收盘={df['close'].iloc[-1]:.4f}"
        )
        return df


# ─────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────

def _period_to_bars(period: str, interval: str) -> int:
    """yfinance period 字符串 -> 估算 bars 数"""
    period_days = {
        "1d": 1, "5d": 5, "1mo": 21, "3mo": 63,
        "6mo": 126, "1y": 252, "2y": 504, "5y": 1260,
    }
    bars_per_day = {
        "1m": 390, "5m": 78, "10m": 39, "15m": 26,
        "30m": 13, "4h": 2, "1d": 1, "1wk": 0.2,
    }
    days = period_days.get(period, 126)
    per_day = bars_per_day.get(interval, 1)
    return max(int(days * per_day), 10)


def _bars_to_start(bars: int, interval: str, end: datetime) -> datetime:
    """根据 bars 数和粒度反推 start 时间，加 40% buffer 应对节假日"""
    mins_per_bar = {
        "1m": 1, "5m": 5, "10m": 10, "15m": 15,
        "30m": 30, "4h": 240, "1d": 1440, "1wk": 10080,
    }
    mins = mins_per_bar.get(interval, 1440)
    return end - timedelta(minutes=int(bars * mins * 1.4))


# ─────────────────────────────────────────────
# 全局单例（推荐：整个进程共享一个 client）
# ─────────────────────────────────────────────
_instance: Optional[SchwabDataProvider] = None

def get_provider() -> SchwabDataProvider:
    """获取全局单例，避免重复初始化和重复授权"""
    global _instance
    if _instance is None:
        _instance = SchwabDataProvider()
    return _instance


# ─────────────────────────────────────────────
# 快速测试入口：python schwab_data_provider.py
# ─────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("Schwab Data Provider v1.1 - 快速测试")
    print("=" * 60)

    provider = SchwabDataProvider()

    # 你的股票组合
    PORTFOLIO = ["TSLA", "AMD", "COIN", "PLTR", "RDDT"]

    print("\n[1] 日线测试（120根）")
    for sym in PORTFOLIO[:3]:
        df = provider.get_kline(sym, interval="1d", bars=120)
        if not df.empty:
            print(f"  {sym}: {len(df)}根  最新收盘={df['close'].iloc[-1]:.2f}")
        else:
            print(f"  {sym}: 无数据")

    print("\n[2] 30分钟线批量测试（50根）")
    batch = provider.get_kline_batch(["TSLA", "AMD"], interval="30m", bars=50)
    for sym, df in batch.items():
        print(f"  {sym}: {len(df)}根  最新={df.index[-1]}")

    print("\n[3] yfinance 兼容接口测试")
    df = provider.download("PLTR", period="3mo", interval="1d")
    if not df.empty:
        print(f"  PLTR 3mo日线: {len(df)}根")
        print(df.tail(2).to_string())

    print("\n测试完成 ✅")
