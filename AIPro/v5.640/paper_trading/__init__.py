"""
Paper Trading Module
====================
模拟盘交易系统 - 跟随系统信号自动买卖

功能:
- 美股5个 + 加密货币2个
- 美股资金上限 $200,000，加密货币 $50,000
- 美股0%费率，加密货币0.1%费率
- 自动跟随系统信号执行模拟交易
- 记录完整交易历史（时间精确到秒）
"""

from .account import PaperAccount
from .executor import PaperTradeExecutor
from .auto_trader import AutoTrader

__all__ = ['PaperAccount', 'PaperTradeExecutor', 'AutoTrader']
