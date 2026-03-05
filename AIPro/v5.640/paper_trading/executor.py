"""
Paper Trade Executor
====================
执行模拟交易，与主程序信号集成
"""

import logging
from datetime import datetime
from typing import Optional, Dict
from .account import PaperAccount, Position, Trade

logger = logging.getLogger(__name__)


class PaperTradeExecutor:
    """模拟交易执行器"""

    def __init__(self, account: PaperAccount):
        """
        初始化执行器

        Args:
            account: PaperAccount 实例
        """
        self.account = account

    def execute_signal(self, symbol: str, action: str, price: float,
                       source: str, confidence: float = None) -> Optional[Dict]:
        """
        执行交易信号

        Args:
            symbol: 品种代码 (TSLA, BTC-USD, etc.)
            action: 信号动作 (BUY, SELL, HOLD)
            price: 当前价格
            source: 触发来源 (L2门卫, P0-Tracking, SuperTrend外挂, etc.)
            confidence: 信号置信度

        Returns:
            执行结果或None
        """
        # 检查是否启用自动交易
        if not self.account.config.get("auto_trade", True):
            logger.debug(f"Paper trading auto_trade disabled, skipping {symbol}")
            return None

        # 检查是否可以交易该品种
        if not self.account.can_trade(symbol):
            logger.debug(f"Symbol {symbol} not in paper trading list")
            return None

        # HOLD 不执行
        if action == "HOLD":
            # 只更新价格
            self.account.update_price(symbol, price)
            return None

        # 执行 BUY 或 SELL
        if action == "BUY":
            return self._execute_buy(symbol, price, source)
        elif action == "SELL":
            return self._execute_sell(symbol, price, source)
        else:
            logger.warning(f"Unknown action: {action}")
            return None

    def _execute_buy(self, symbol: str, price: float, source: str) -> Optional[Dict]:
        """执行买入"""
        # 检查是否已有持仓
        if symbol in self.account.positions:
            logger.info(f"Paper: {symbol} already has position, skip BUY")
            return None

        # 获取可用资金
        available = self.account.get_available_cash(symbol)
        position_capital = self.account.get_position_capital(symbol)

        # 计算买入数量
        use_capital = min(available, position_capital)
        if use_capital < 10:  # 最小交易金额
            logger.info(f"Paper: Insufficient cash for {symbol}")
            return None

        # 计算费用
        fee_rate = self.account.get_fee_rate(symbol)
        fee = use_capital * fee_rate

        # 实际可买金额
        buy_amount = use_capital - fee
        quantity = buy_amount / price

        # 对美股取整数
        if self.account.is_stock(symbol):
            quantity = int(quantity)
            if quantity < 1:
                logger.info(f"Paper: Cannot afford 1 share of {symbol}")
                return None
            buy_amount = quantity * price
            fee = buy_amount * fee_rate

        total = buy_amount + fee

        # 扣除现金
        if self.account.is_stock(symbol):
            self.account.cash_stock -= total
        else:
            self.account.cash_crypto -= total

        # 创建持仓
        now = datetime.now().isoformat()
        self.account.positions[symbol] = Position(
            symbol=symbol,
            quantity=quantity,
            avg_cost=price,
            current_price=price,
            last_updated=now
        )

        # 记录交易
        trade = Trade(
            id=len(self.account.trades) + 1,
            timestamp=now,
            symbol=symbol,
            action="BUY",
            quantity=quantity,
            price=price,
            fee=fee,
            total=total,
            source=source,
            pnl=None,
            pnl_pct=None
        )
        self.account.trades.append(trade)

        # 保存
        self.account._save_config()
        self.account._save_positions()
        self.account._save_trades()

        logger.info(f"Paper BUY: {symbol} {quantity} @ ${price:.2f}, fee=${fee:.2f}, source={source}")

        return {
            "action": "BUY",
            "symbol": symbol,
            "quantity": quantity,
            "price": price,
            "fee": fee,
            "total": total,
            "source": source,
            "timestamp": now
        }

    def _execute_sell(self, symbol: str, price: float, source: str) -> Optional[Dict]:
        """执行卖出"""
        # 检查是否有持仓
        if symbol not in self.account.positions:
            logger.info(f"Paper: {symbol} no position to sell")
            return None

        position = self.account.positions[symbol]
        quantity = position.quantity
        avg_cost = position.avg_cost

        # 计算卖出金额
        sell_amount = quantity * price
        fee_rate = self.account.get_fee_rate(symbol)
        fee = sell_amount * fee_rate
        total = sell_amount - fee

        # 计算盈亏
        cost_basis = quantity * avg_cost
        pnl = total - cost_basis
        pnl_pct = (pnl / cost_basis * 100) if cost_basis > 0 else 0

        # 增加现金
        if self.account.is_stock(symbol):
            self.account.cash_stock += total
        else:
            self.account.cash_crypto += total

        # 删除持仓
        del self.account.positions[symbol]

        # 记录交易
        now = datetime.now().isoformat()
        trade = Trade(
            id=len(self.account.trades) + 1,
            timestamp=now,
            symbol=symbol,
            action="SELL",
            quantity=quantity,
            price=price,
            fee=fee,
            total=total,
            source=source,
            pnl=pnl,
            pnl_pct=pnl_pct
        )
        self.account.trades.append(trade)

        # 保存
        self.account._save_config()
        self.account._save_positions()
        self.account._save_trades()

        logger.info(f"Paper SELL: {symbol} {quantity} @ ${price:.2f}, P&L=${pnl:.2f} ({pnl_pct:.2f}%), source={source}")

        return {
            "action": "SELL",
            "symbol": symbol,
            "quantity": quantity,
            "price": price,
            "fee": fee,
            "total": total,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "source": source,
            "timestamp": now
        }

    def update_prices(self, prices: Dict[str, float]):
        """
        批量更新持仓价格

        Args:
            prices: {symbol: price} 字典
        """
        for symbol, price in prices.items():
            if symbol in self.account.positions:
                self.account.update_price(symbol, price)
