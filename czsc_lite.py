"""
czsc_lite.py — 缠论核心算法轻量实现
=====================================
零外部依赖，替代 czsc 官方包 (27个重依赖)。

只实现 chan_bs_plugin.py 需要的4个核心类:
- RawBar: K线数据
- Freq: 周期枚举
- CZSC: 分笔引擎 (包含处理→分型→笔)
- ZS: 中枢验证

算法参考: 缠中说禅技术分析理论
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional


# ============================================================
# 周期枚举
# ============================================================

class Freq(Enum):
    F1 = "1分钟"
    F5 = "5分钟"
    F15 = "15分钟"
    F30 = "30分钟"
    F60 = "60分钟"
    F240 = "4小时"
    D = "日线"
    W = "周线"
    M = "月线"


# ============================================================
# K线数据
# ============================================================

@dataclass
class RawBar:
    """原始K线"""
    symbol: str
    dt: datetime
    freq: Freq
    open: float
    close: float
    high: float
    low: float
    vol: float = 0.0
    amount: float = 0.0


# ============================================================
# 内部数据结构
# ============================================================

class Direction(Enum):
    Up = "向上"
    Down = "向下"


@dataclass
class NewBar:
    """合并后的K线 (包含处理后)"""
    symbol: str
    dt: datetime
    freq: Freq
    open: float
    close: float
    high: float
    low: float
    vol: float = 0.0
    amount: float = 0.0
    raw_bars: list = field(default_factory=list)


@dataclass
class FX:
    """分型 (顶分型/底分型)"""
    symbol: str
    dt: datetime
    mark: str  # "g" = 顶分型, "d" = 底分型
    high: float
    low: float
    elements: list = field(default_factory=list)  # 3根合并K线


@dataclass
class BI:
    """笔"""
    symbol: str
    sdt: datetime       # 起始时间
    edt: datetime       # 结束时间
    direction: Direction
    high: float
    low: float
    fx_a: Optional[FX] = None  # 起始分型
    fx_b: Optional[FX] = None  # 结束分型
    raw_bars: list = field(default_factory=list)


# ============================================================
# 中枢 (ZS)
# ============================================================

class ZS:
    """中枢验证 — 从3根连续笔构造"""

    def __init__(self, bis: List[BI] = None):
        self.bis = bis or []
        self.is_valid = False
        self.zg = 0.0   # 中枢上沿 = min(高点们)
        self.zd = 0.0   # 中枢下沿 = max(低点们)
        self.gg = 0.0   # 最高点
        self.dd = 0.0   # 最低点
        self.sdt = None  # 起始时间
        self.edt = None  # 结束时间

        if len(self.bis) >= 3:
            self._validate()

    def _validate(self):
        """验证3笔是否构成有效中枢"""
        b1, b2, b3 = self.bis[0], self.bis[1], self.bis[2]

        # 中枢 = 3笔重叠区间
        highs = [b1.high, b2.high, b3.high]
        lows = [b1.low, b2.low, b3.low]

        self.zg = min(highs)   # 中枢上沿 = 3笔高点的最小值
        self.zd = max(lows)    # 中枢下沿 = 3笔低点的最大值

        # 有效条件: 上沿 > 下沿 (存在重叠区间)
        if self.zg > self.zd:
            self.is_valid = True
            self.gg = max(highs)
            self.dd = min(lows)
            self.sdt = b1.sdt
            self.edt = b3.edt


# ============================================================
# CZSC 分笔引擎
# ============================================================

class CZSC:
    """
    缠论分笔引擎

    输入: RawBar列表
    输出: bi_list (笔列表)

    算法流程:
    1. 包含处理 (K线合并)
    2. 分型检测 (顶/底分型)
    3. 笔构造 (连接分型)
    """

    def __init__(self, bars: List[RawBar]):
        self.bars_raw = bars
        self.bars_merged: List[NewBar] = []
        self.fx_list: List[FX] = []
        self.bi_list: List[BI] = []

        if len(bars) >= 3:
            self._process()

    def _process(self):
        """完整处理流程"""
        self._merge_bars()
        if len(self.bars_merged) >= 3:
            self._detect_fx()
        if len(self.fx_list) >= 2:
            self._build_bi()

    # ----------------------------------------------------------
    # Step 1: 包含处理 (K线合并)
    # ----------------------------------------------------------
    def _merge_bars(self):
        """
        包含关系处理:
        - 如果后一根K线被前一根包含 (前高>=后高 且 前低<=后低)
        - 或前一根被后一根包含 (后高>=前高 且 后低<=前低)
        - 则合并: 上升取高高低低, 下降取低低高高
        """
        if not self.bars_raw:
            return

        # 第一根直接放入
        first = self.bars_raw[0]
        merged = [NewBar(
            symbol=first.symbol, dt=first.dt, freq=first.freq,
            open=first.open, close=first.close,
            high=first.high, low=first.low,
            vol=first.vol, amount=first.amount,
            raw_bars=[first]
        )]

        for bar in self.bars_raw[1:]:
            last = merged[-1]

            # 判断包含关系
            if (last.high >= bar.high and last.low <= bar.low) or \
               (bar.high >= last.high and bar.low <= last.low):
                # 存在包含关系 → 合并
                # 判断方向: 看前两根合并K线的趋势
                if len(merged) >= 2:
                    going_up = merged[-2].high < last.high
                else:
                    going_up = bar.close > bar.open

                if going_up:
                    # 上升趋势: 取高高低低
                    last.high = max(last.high, bar.high)
                    last.low = max(last.low, bar.low)
                else:
                    # 下降趋势: 取低低高高
                    last.high = min(last.high, bar.high)
                    last.low = min(last.low, bar.low)

                last.dt = bar.dt
                last.close = bar.close
                last.vol += bar.vol
                last.raw_bars.append(bar)
            else:
                # 无包含关系 → 新增
                merged.append(NewBar(
                    symbol=bar.symbol, dt=bar.dt, freq=bar.freq,
                    open=bar.open, close=bar.close,
                    high=bar.high, low=bar.low,
                    vol=bar.vol, amount=bar.amount,
                    raw_bars=[bar]
                ))

        self.bars_merged = merged

    # ----------------------------------------------------------
    # Step 2: 分型检测
    # ----------------------------------------------------------
    def _detect_fx(self):
        """
        顶分型: 中间K线的高点 > 左右两根的高点
        底分型: 中间K线的低点 < 左右两根的低点
        """
        fxs = []
        bars = self.bars_merged

        for i in range(1, len(bars) - 1):
            prev, curr, nxt = bars[i - 1], bars[i], bars[i + 1]

            # 顶分型
            if curr.high > prev.high and curr.high > nxt.high:
                fxs.append(FX(
                    symbol=curr.symbol, dt=curr.dt,
                    mark="g", high=curr.high, low=curr.low,
                    elements=[prev, curr, nxt]
                ))
            # 底分型
            elif curr.low < prev.low and curr.low < nxt.low:
                fxs.append(FX(
                    symbol=curr.symbol, dt=curr.dt,
                    mark="d", high=curr.high, low=curr.low,
                    elements=[prev, curr, nxt]
                ))

        self.fx_list = fxs

    # ----------------------------------------------------------
    # Step 3: 笔构造
    # ----------------------------------------------------------
    def _build_bi(self):
        """
        笔的构造规则:
        1. 顶分型→底分型 = 向下笔
        2. 底分型→顶分型 = 向上笔
        3. 两个分型之间至少要有1根独立K线 (即分型之间>=5根合并K线)
           标准: 分型索引差 >= 4 (含分型自身共5根合并K线)
        4. 顶底交替
        """
        if len(self.fx_list) < 2:
            return

        bis = []
        # 从第一个分型开始
        fx_a = self.fx_list[0]

        for fx_b in self.fx_list[1:]:
            # 必须顶底交替
            if fx_a.mark == fx_b.mark:
                # 同类型分型: 保留更极端的那个
                if fx_a.mark == "g":
                    # 两个顶分型: 保留更高的
                    if fx_b.high > fx_a.high:
                        fx_a = fx_b
                else:
                    # 两个底分型: 保留更低的
                    if fx_b.low < fx_a.low:
                        fx_a = fx_b
                continue

            # 检查分型之间的K线数量 (简化: 用index差)
            idx_a = self._find_bar_index(fx_a.dt)
            idx_b = self._find_bar_index(fx_b.dt)
            if idx_b - idx_a < 4:
                # 分型间距不够，跳过fx_b
                continue

            # 构造笔
            if fx_a.mark == "d" and fx_b.mark == "g":
                # 底→顶 = 向上笔
                bi = BI(
                    symbol=fx_a.symbol,
                    sdt=fx_a.dt, edt=fx_b.dt,
                    direction=Direction.Up,
                    high=fx_b.high, low=fx_a.low,
                    fx_a=fx_a, fx_b=fx_b,
                    raw_bars=self.bars_merged[idx_a:idx_b + 1]
                )
                bis.append(bi)
            elif fx_a.mark == "g" and fx_b.mark == "d":
                # 顶→底 = 向下笔
                bi = BI(
                    symbol=fx_a.symbol,
                    sdt=fx_a.dt, edt=fx_b.dt,
                    direction=Direction.Down,
                    high=fx_a.high, low=fx_b.low,
                    fx_a=fx_a, fx_b=fx_b,
                    raw_bars=self.bars_merged[idx_a:idx_b + 1]
                )
                bis.append(bi)

            fx_a = fx_b

        self.bi_list = bis

    def _find_bar_index(self, dt: datetime) -> int:
        """找到合并K线中对应时间的索引"""
        for i, bar in enumerate(self.bars_merged):
            if bar.dt == dt:
                return i
        # 如果精确匹配失败，找最近的
        for i, bar in enumerate(self.bars_merged):
            if bar.dt >= dt:
                return i
        return len(self.bars_merged) - 1
