"""
Paper Trading Account Manager
=============================
管理模拟盘账户、持仓、交易历史
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """持仓数据"""
    symbol: str
    quantity: float
    avg_cost: float
    current_price: float
    last_updated: str

    @property
    def market_value(self) -> float:
        return self.quantity * self.current_price

    @property
    def unrealized_pnl(self) -> float:
        return (self.current_price - self.avg_cost) * self.quantity

    @property
    def unrealized_pnl_pct(self) -> float:
        if self.avg_cost == 0:
            return 0
        return ((self.current_price - self.avg_cost) / self.avg_cost) * 100


@dataclass
class Trade:
    """交易记录"""
    id: int
    timestamp: str
    symbol: str
    action: str  # BUY / SELL
    quantity: float
    price: float
    fee: float
    total: float
    source: str  # 触发来源
    pnl: Optional[float] = None  # 实现盈亏 (SELL时)
    pnl_pct: Optional[float] = None  # 盈亏百分比


class PaperAccount:
    """模拟盘账户管理"""

    # 默认配置
    DEFAULT_CONFIG = {
        "stock": {
            "capital": 200000,  # 美股资金上限 $200,000
            "max_symbols": 5,   # 最多5个美股
            "symbols": [],      # 选中的美股
            "fee_rate": 0.0,    # 美股0%费率
            "position_ratio": 0.20,  # 每个品种占20%
            "timeframe": "4h"   # v5.493: 美股默认4h周期
        },
        "crypto": {
            "capital": 50000,   # 加密货币资金上限 $50,000
            "max_symbols": 2,   # 最多2个加密货币
            "symbols": [],      # 选中的加密货币
            "fee_rate": 0.001,  # 加密货币0.1%费率
            "position_ratio": 0.50,  # 每个品种占50%
            "timeframe": "2h"   # v5.493: 加密货币默认2h周期
        },
        "auto_trade": True,     # 自动跟随信号
        "created_at": None,
        "initialized": False
    }

    def __init__(self, data_dir: str):
        """
        初始化模拟盘账户

        Args:
            data_dir: 数据目录路径
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.config_path = self.data_dir / "paper_config.json"
        self.positions_path = self.data_dir / "paper_positions.json"
        self.trades_path = self.data_dir / "paper_trades.json"

        self.config: Dict = {}
        self.positions: Dict[str, Position] = {}
        self.trades: List[Trade] = []
        self.cash_stock: float = 0  # 美股可用现金
        self.cash_crypto: float = 0  # 加密货币可用现金

        self._load_all()

    def _load_all(self):
        """加载所有数据"""
        self._load_config()
        self._load_positions()
        self._load_trades()

    def _load_config(self):
        """加载配置"""
        try:
            if self.config_path.exists():
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
                    # 初始化现金
                    if self.config.get("initialized"):
                        self.cash_stock = self.config.get("cash_stock", self.config["stock"]["capital"])
                        self.cash_crypto = self.config.get("cash_crypto", self.config["crypto"]["capital"])
            else:
                self.config = self.DEFAULT_CONFIG.copy()
                self.config["created_at"] = datetime.now().isoformat()
                self._save_config()
        except Exception as e:
            logger.error(f"Failed to load paper config: {e}")
            self.config = self.DEFAULT_CONFIG.copy()

    def _save_config(self):
        """保存配置"""
        try:
            # 保存现金状态
            self.config["cash_stock"] = self.cash_stock
            self.config["cash_crypto"] = self.cash_crypto
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save paper config: {e}")

    def _load_positions(self):
        """加载持仓"""
        try:
            if self.positions_path.exists():
                with open(self.positions_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.positions = {
                        symbol: Position(**pos)
                        for symbol, pos in data.get("positions", {}).items()
                    }
        except Exception as e:
            logger.error(f"Failed to load paper positions: {e}")
            self.positions = {}

    def _save_positions(self):
        """保存持仓"""
        try:
            data = {
                "positions": {
                    symbol: asdict(pos)
                    for symbol, pos in self.positions.items()
                },
                "updated_at": datetime.now().isoformat()
            }
            with open(self.positions_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save paper positions: {e}")

    def _load_trades(self):
        """加载交易历史"""
        try:
            if self.trades_path.exists():
                with open(self.trades_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.trades = [Trade(**t) for t in data.get("trades", [])]
        except Exception as e:
            logger.error(f"Failed to load paper trades: {e}")
            self.trades = []

    def _save_trades(self):
        """保存交易历史"""
        try:
            data = {
                "trades": [asdict(t) for t in self.trades],
                "last_id": self.trades[-1].id if self.trades else 0,
                "updated_at": datetime.now().isoformat()
            }
            with open(self.trades_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save paper trades: {e}")

    def is_stock(self, symbol: str) -> bool:
        """判断是否为美股"""
        # 加密货币通常包含 -USD 或 USDC/USDT
        crypto_patterns = ['-USD', 'USDC', 'USDT', 'BTC', 'ETH', 'SOL', 'ZEC']
        return not any(p in symbol.upper() for p in crypto_patterns)

    def initialize(self, stock_symbols: List[str], crypto_symbols: List[str],
                   stock_capital: float = None, crypto_capital: float = None):
        """
        初始化模拟盘

        Args:
            stock_symbols: 选中的美股列表 (最多5个)
            crypto_symbols: 选中的加密货币列表 (最多2个)
            stock_capital: 美股资金 (可选，默认200000)
            crypto_capital: 加密货币资金 (可选，默认50000)
        """
        # 验证数量限制
        if len(stock_symbols) > 5:
            raise ValueError("美股最多选择5个")
        if len(crypto_symbols) > 2:
            raise ValueError("加密货币最多选择2个")

        # 验证资金上限
        stock_capital = stock_capital or self.config["stock"]["capital"]
        crypto_capital = crypto_capital or self.config["crypto"]["capital"]

        if stock_capital > 200000:
            raise ValueError("美股资金上限为 $200,000")
        if crypto_capital > 50000:
            raise ValueError("加密货币资金上限为 $50,000")

        # 更新配置
        self.config["stock"]["symbols"] = stock_symbols
        self.config["stock"]["capital"] = stock_capital
        self.config["crypto"]["symbols"] = crypto_symbols
        self.config["crypto"]["capital"] = crypto_capital
        self.config["initialized"] = True
        self.config["created_at"] = datetime.now().isoformat()

        # 初始化现金
        self.cash_stock = stock_capital
        self.cash_crypto = crypto_capital

        # 清空持仓和交易历史
        self.positions = {}
        self.trades = []

        self._save_config()
        self._save_positions()
        self._save_trades()

        logger.info(f"Paper account initialized: {len(stock_symbols)} stocks, {len(crypto_symbols)} crypto")

    def update_settings(self, stock_symbols: List[str] = None,
                        crypto_symbols: List[str] = None,
                        stock_capital: float = None,
                        crypto_capital: float = None,
                        stock_fee_rate: float = None,
                        crypto_fee_rate: float = None,
                        stock_timeframe: str = None,
                        crypto_timeframe: str = None,
                        auto_trade: bool = None):
        """更新设置（不重置账户）"""
        if stock_symbols is not None:
            if len(stock_symbols) > 5:
                raise ValueError("美股最多选择5个")
            self.config["stock"]["symbols"] = stock_symbols

        if crypto_symbols is not None:
            if len(crypto_symbols) > 2:
                raise ValueError("加密货币最多选择2个")
            self.config["crypto"]["symbols"] = crypto_symbols

        if stock_capital is not None:
            if stock_capital > 200000:
                raise ValueError("美股资金上限为 $200,000")
            self.config["stock"]["capital"] = stock_capital

        if crypto_capital is not None:
            if crypto_capital > 50000:
                raise ValueError("加密货币资金上限为 $50,000")
            self.config["crypto"]["capital"] = crypto_capital

        if stock_fee_rate is not None:
            self.config["stock"]["fee_rate"] = stock_fee_rate

        if crypto_fee_rate is not None:
            self.config["crypto"]["fee_rate"] = crypto_fee_rate

        # v5.493: 用户可选择周期
        if stock_timeframe is not None:
            self.config["stock"]["timeframe"] = stock_timeframe

        if crypto_timeframe is not None:
            self.config["crypto"]["timeframe"] = crypto_timeframe

        if auto_trade is not None:
            self.config["auto_trade"] = auto_trade

        self._save_config()

    def get_position_capital(self, symbol: str) -> float:
        """获取单个品种的可用资金"""
        if self.is_stock(symbol):
            num_stocks = len(self.config["stock"]["symbols"]) or 1
            return self.config["stock"]["capital"] / num_stocks
        else:
            num_crypto = len(self.config["crypto"]["symbols"]) or 1
            return self.config["crypto"]["capital"] / num_crypto

    def get_fee_rate(self, symbol: str) -> float:
        """获取费率"""
        if self.is_stock(symbol):
            return self.config["stock"]["fee_rate"]
        else:
            return self.config["crypto"]["fee_rate"]

    def get_timeframe(self, symbol: str) -> str:
        """v5.493: 获取用户配置的交易周期"""
        if self.is_stock(symbol):
            return self.config["stock"].get("timeframe", "4h")
        else:
            return self.config["crypto"].get("timeframe", "2h")

    def get_available_cash(self, symbol: str) -> float:
        """获取可用现金"""
        if self.is_stock(symbol):
            return self.cash_stock
        else:
            return self.cash_crypto

    def can_trade(self, symbol: str) -> bool:
        """检查是否可以交易该品种"""
        if not self.config.get("initialized"):
            return False

        if self.is_stock(symbol):
            return symbol in self.config["stock"]["symbols"]
        else:
            # 加密货币需要匹配 symbol (可能是 BTC-USD 或 bitcoin)
            crypto_symbols = self.config["crypto"]["symbols"]
            return symbol in crypto_symbols or any(
                symbol.upper().replace('-USD', '') in s.upper()
                for s in crypto_symbols
            )

    def update_price(self, symbol: str, price: float):
        """更新持仓的当前价格"""
        if symbol in self.positions:
            self.positions[symbol].current_price = price
            self.positions[symbol].last_updated = datetime.now().isoformat()
            self._save_positions()

    def get_summary(self) -> Dict:
        """获取账户摘要"""
        # 计算持仓市值
        stock_market_value = sum(
            pos.market_value for symbol, pos in self.positions.items()
            if self.is_stock(symbol)
        )
        crypto_market_value = sum(
            pos.market_value for symbol, pos in self.positions.items()
            if not self.is_stock(symbol)
        )

        # 总资产
        total_stock = self.cash_stock + stock_market_value
        total_crypto = self.cash_crypto + crypto_market_value
        total_assets = total_stock + total_crypto

        # 初始资金
        initial_stock = self.config["stock"]["capital"]
        initial_crypto = self.config["crypto"]["capital"]
        initial_total = initial_stock + initial_crypto

        # 总盈亏
        total_pnl = total_assets - initial_total
        total_pnl_pct = (total_pnl / initial_total * 100) if initial_total > 0 else 0

        # 今日盈亏 (简化: 用未实现盈亏)
        today_pnl = sum(pos.unrealized_pnl for pos in self.positions.values())

        return {
            "total_assets": total_assets,
            "total_pnl": total_pnl,
            "total_pnl_pct": total_pnl_pct,
            "today_pnl": today_pnl,
            "cash_stock": self.cash_stock,
            "cash_crypto": self.cash_crypto,
            "stock_market_value": stock_market_value,
            "crypto_market_value": crypto_market_value,
            "positions_count": len(self.positions),
            "trades_count": len(self.trades),
            "initialized": self.config.get("initialized", False),
            "auto_trade": self.config.get("auto_trade", True)
        }

    def get_positions_list(self) -> List[Dict]:
        """获取持仓列表"""
        return [
            {
                "symbol": pos.symbol,
                "quantity": pos.quantity,
                "avg_cost": pos.avg_cost,
                "current_price": pos.current_price,
                "market_value": pos.market_value,
                "pnl": pos.unrealized_pnl,
                "pnl_pct": pos.unrealized_pnl_pct,
                "is_stock": self.is_stock(pos.symbol),
                "last_updated": pos.last_updated
            }
            for pos in self.positions.values()
        ]

    def get_trades_list(self, limit: int = 20, offset: int = 0) -> Dict:
        """获取交易历史列表（分页）"""
        # 按时间倒序
        sorted_trades = sorted(self.trades, key=lambda t: t.timestamp, reverse=True)
        total = len(sorted_trades)
        trades = sorted_trades[offset:offset + limit]

        return {
            "trades": [asdict(t) for t in trades],
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": offset + limit < total
        }

    def reset_account(self):
        """重置账户"""
        self.cash_stock = self.config["stock"]["capital"]
        self.cash_crypto = self.config["crypto"]["capital"]
        self.positions = {}
        self.trades = []
        self.config["initialized"] = True
        self.config["created_at"] = datetime.now().isoformat()

        self._save_config()
        self._save_positions()
        self._save_trades()

        logger.info("Paper account reset")

    def export_trades_csv(self) -> str:
        """导出交易历史为CSV格式"""
        lines = ["ID,Time,Symbol,Action,Quantity,Price,Fee,Total,Source,P&L,P&L%"]
        for t in sorted(self.trades, key=lambda x: x.timestamp, reverse=True):
            pnl = f"{t.pnl:.2f}" if t.pnl is not None else ""
            pnl_pct = f"{t.pnl_pct:.2f}" if t.pnl_pct is not None else ""
            lines.append(f"{t.id},{t.timestamp},{t.symbol},{t.action},{t.quantity},{t.price:.2f},{t.fee:.2f},{t.total:.2f},{t.source},{pnl},{pnl_pct}")
        return "\n".join(lines)
