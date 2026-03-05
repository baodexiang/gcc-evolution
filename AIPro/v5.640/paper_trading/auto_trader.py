"""
Paper Trading Auto Trader v5.540
================================
后台自动交易引擎 - 按配置周期运行分析并执行模拟交易

功能:
- 根据配置的stocks/crypto symbols自动运行分析
- 按配置的timeframe周期执行 (美股4h, 加密货币2h)
- BUY/SELL信号自动执行模拟交易
- HOLD信号跳过
"""

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, Optional, Callable

logger = logging.getLogger(__name__)


class AutoTrader:
    """模拟盘自动交易引擎"""

    # 周期对应的分钟数
    TIMEFRAME_MINUTES = {
        "5m": 5,
        "10m": 10,
        "15m": 15,
        "30m": 30,
        "1h": 60,
        "2h": 120,
        "4h": 240,
        "1d": 1440,
    }

    def __init__(
        self,
        paper_account,
        signal_generator,
        stock_provider,
        crypto_provider,
        execute_trade_func: Callable
    ):
        """
        初始化自动交易引擎

        Args:
            paper_account: PaperAccount实例
            signal_generator: SignalGenerator实例
            stock_provider: 美股数据提供者
            crypto_provider: 加密货币数据提供者
            execute_trade_func: 执行交易的函数
        """
        self.paper_account = paper_account
        self.signal_generator = signal_generator
        self.stock_provider = stock_provider
        self.crypto_provider = crypto_provider
        self.execute_trade = execute_trade_func

        self.running = False
        self.thread: Optional[threading.Thread] = None

        # 上次分析时间记录 (防止重复分析)
        self.last_analysis: Dict[str, datetime] = {}

        # 统计
        self.stats = {
            "total_analyses": 0,
            "buy_signals": 0,
            "sell_signals": 0,
            "hold_signals": 0,
            "errors": 0,
            "started_at": None,
        }

        logger.info("[AutoTrader] 初始化完成")

    def start(self):
        """启动自动交易"""
        if self.running:
            logger.warning("[AutoTrader] 已经在运行中")
            return

        self.running = True
        self.stats["started_at"] = datetime.now().isoformat()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        logger.info("[AutoTrader] 后台自动交易已启动")

    def stop(self):
        """停止自动交易"""
        self.running = False
        logger.info("[AutoTrader] 后台自动交易已停止")

    def _run_loop(self):
        """主循环 - 每分钟检查是否需要运行分析"""
        logger.info("[AutoTrader] 进入主循环")

        while self.running:
            try:
                self._check_and_run_analyses()
            except Exception as e:
                logger.error(f"[AutoTrader] 主循环错误: {e}")
                self.stats["errors"] += 1

            # 每60秒检查一次
            time.sleep(60)

    def _check_and_run_analyses(self):
        """检查并运行需要的分析"""
        # 检查模拟盘是否已初始化且启用自动交易
        config = self.paper_account.config
        if not config.get("initialized", False):
            return
        if not config.get("auto_trade", True):
            return

        now = datetime.now()

        # 处理美股
        stock_config = config.get("stock", {})
        stock_symbols = stock_config.get("symbols", [])
        stock_timeframe = stock_config.get("timeframe", "4h")
        stock_minutes = self.TIMEFRAME_MINUTES.get(stock_timeframe, 240)

        for symbol in stock_symbols:
            self._maybe_run_analysis(symbol, "stock", stock_timeframe, stock_minutes, now)

        # 处理加密货币
        crypto_config = config.get("crypto", {})
        crypto_symbols = crypto_config.get("symbols", [])
        crypto_timeframe = crypto_config.get("timeframe", "2h")
        crypto_minutes = self.TIMEFRAME_MINUTES.get(crypto_timeframe, 120)

        for symbol in crypto_symbols:
            self._maybe_run_analysis(symbol, "crypto", crypto_timeframe, crypto_minutes, now)

    def _maybe_run_analysis(
        self,
        symbol: str,
        asset_type: str,
        timeframe: str,
        interval_minutes: int,
        now: datetime
    ):
        """检查是否需要运行分析"""
        key = f"{symbol}_{asset_type}"

        # 检查是否需要运行 (超过周期间隔)
        last_time = self.last_analysis.get(key)
        if last_time:
            elapsed = (now - last_time).total_seconds() / 60
            if elapsed < interval_minutes:
                return  # 还没到下一个周期

        # 对于美股，检查市场是否开盘
        if asset_type == "stock":
            if not self._is_us_market_open(now):
                return  # 美股休市不分析

        # 运行分析
        try:
            self._run_single_analysis(symbol, asset_type, timeframe)
            self.last_analysis[key] = now
        except Exception as e:
            logger.error(f"[AutoTrader] {symbol} 分析失败: {e}")
            self.stats["errors"] += 1

    def _is_us_market_open(self, now: datetime) -> bool:
        """检查美股是否开盘 (简单判断)"""
        # 转换为美东时间 (简化处理，假设服务器时区)
        # 美股交易时间: 9:30 - 16:00 ET, 周一到周五
        weekday = now.weekday()
        if weekday >= 5:  # 周末
            return False

        hour = now.hour
        # 简化: 假设在美东时区附近
        # 实际应该用pytz转换
        if hour < 9 or hour >= 16:
            return False

        return True

    def _run_single_analysis(self, symbol: str, asset_type: str, timeframe: str):
        """运行单个品种的分析"""
        logger.info(f"[AutoTrader] 分析 {symbol} ({asset_type}, {timeframe})")

        # 获取数据
        provider = self.crypto_provider if asset_type == "crypto" else self.stock_provider

        try:
            # 获取K线数据
            bars = provider.get_ohlcv(symbol, timeframe, limit=150)
            if not bars or len(bars) < 50:
                logger.warning(f"[AutoTrader] {symbol} 数据不足")
                return

            # 运行信号分析
            result = self.signal_generator.analyze(
                symbol=symbol,
                bars=bars,
                timeframe=timeframe
            )

            if not result:
                logger.warning(f"[AutoTrader] {symbol} 分析无结果")
                return

            action = result.get("action", "HOLD")
            price = result.get("current_price", 0)
            confidence = result.get("confidence", 0)
            reason = result.get("reason", "")

            self.stats["total_analyses"] += 1

            # 执行交易
            if action == "BUY":
                self.stats["buy_signals"] += 1
                self._execute_signal(symbol, action, price, f"AutoTrader-{timeframe}")
                logger.info(f"[AutoTrader] {symbol} BUY @ {price:.2f} (置信度: {confidence}%)")

            elif action == "SELL":
                self.stats["sell_signals"] += 1
                self._execute_signal(symbol, action, price, f"AutoTrader-{timeframe}")
                logger.info(f"[AutoTrader] {symbol} SELL @ {price:.2f} (置信度: {confidence}%)")

            else:  # HOLD
                self.stats["hold_signals"] += 1
                logger.debug(f"[AutoTrader] {symbol} HOLD - {reason[:50]}")

        except Exception as e:
            logger.error(f"[AutoTrader] {symbol} 分析异常: {e}")
            raise

    def _execute_signal(self, symbol: str, action: str, price: float, source: str):
        """执行交易信号"""
        try:
            result = self.execute_trade(symbol, action, price, source)
            if result:
                logger.info(f"[AutoTrader] 交易执行成功: {result}")
        except Exception as e:
            logger.error(f"[AutoTrader] 交易执行失败: {e}")

    def get_status(self) -> dict:
        """获取自动交易状态"""
        return {
            "running": self.running,
            "stats": self.stats,
            "last_analysis": {k: v.isoformat() for k, v in self.last_analysis.items()}
        }
