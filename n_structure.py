"""
n_structure.py — N字结构门控模块
==================================
v2.1: 修复DEEP_PULLBACK quality=0死代码 (波浪验证扩展至所有非SIDE状态)

核心假设:
  当前K线永远是某个N字最后一笔上的一个点。
  每根新K线进来，重新往回看，找到它所属的N字结构，
  判断当前位置，决定能不能交易、给几次机会。

N字结构 = 三笔构成:
  第一笔(A→B): 启动段
  第二笔(B→C): 回调段
  第三笔(C→?): 延续段，当前K线所在

v2.0 波浪验证 (两条硬规则):
  规则1: 回调深度评分 — retrace_ratio = leg2/leg1
         浅回调(<38.2%) = 强势, 深回调(>78.6%) = 弱势
  规则2: 第三笔不能最短 — leg3不能同时<leg1且<leg2
         违反时降级N字质量，限制交易次数

quality字段 (0~1):
  >= 0.8 → 高质量N字，给更多交易机会
  0.5~0.8 → 正常N字
  < 0.5 → 低质量N字，限制机会

所有转折点用收盘价。分型来源: czsc_lite FX。

改善追踪: KEY-001 N字结构门控升级
"""

from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, field
from datetime import datetime


# ============================================================
# 常量
# ============================================================

# N字状态
STATE_SIDE = "SIDE"                  # 震荡 — 无完美N字
STATE_PERFECT_N = "PERFECT_N"        # 完美N字成立，未突破前N字高低点
STATE_UP_BREAK = "UP_BREAK"          # 上升突破 — 第三笔突破前N字高点
STATE_DOWN_BREAK = "DOWN_BREAK"      # 下降突破 — 第三笔突破前N字低点
STATE_PULLBACK = "PULLBACK"          # 回调中 — 不给机会，等新N字
STATE_DEEP_PULLBACK = "DEEP_PULLBACK"  # 深度回调 — 破B点，给防守机会

# 方向
DIR_UP = "UP"
DIR_DOWN = "DOWN"
DIR_NONE = "NONE"


# ============================================================
# 数据结构
# ============================================================

@dataclass
class Fractal:
    """分型数据 (从czsc_lite FX转换而来)"""
    type: str          # 'TOP' / 'BOTTOM'
    price: float       # 收盘价 (非high/low)
    bar_index: int     # K线索引
    dt: Optional[datetime] = None
    confirmed: bool = True


@dataclass
class NState:
    """N字结构状态"""
    # ABC三点
    A: float = 0.0
    B: float = 0.0
    C: float = 0.0
    A_index: int = -1
    B_index: int = -1
    C_index: int = -1

    # 状态
    state: str = STATE_SIDE
    direction: str = DIR_NONE

    # 前一个N字记录 (用于突破/结构破坏判断)
    prev_n_high: float = 0.0
    prev_n_low: float = 0.0
    prev_n_A: float = 0.0

    # 当前结构内交易次数
    trade_count_long: int = 0
    trade_count_short: int = 0

    # 移动止盈止损开关
    trailing_stop_active: bool = False

    # 最新价格
    last_high: float = 0.0
    last_low: float = 0.0

    # === v2.0: 波浪验证字段 ===
    quality: float = 0.0        # N字质量 0~1 (综合评分)
    leg1_range: float = 0.0     # 第一笔幅度 |A→B|
    leg2_range: float = 0.0     # 第二笔幅度 |B→C| (回调段)
    leg3_range: float = 0.0     # 第三笔幅度 |C→当前| (延续段)
    retrace_ratio: float = 0.0  # 回调比 = leg2/leg1 (波浪: 浪2不破起点)
    extension_ok: bool = True   # 第三笔不是最短 (波浪: 浪3不能最短)

    def to_dict(self) -> dict:
        return {
            'A': self.A, 'B': self.B, 'C': self.C,
            'state': self.state, 'direction': self.direction,
            'prev_n_high': self.prev_n_high,
            'prev_n_low': self.prev_n_low,
            'trade_count_long': self.trade_count_long,
            'trade_count_short': self.trade_count_short,
            'trailing_stop_active': self.trailing_stop_active,
            'quality': self.quality,
            'leg1_range': self.leg1_range,
            'leg2_range': self.leg2_range,
            'leg3_range': self.leg3_range,
            'retrace_ratio': self.retrace_ratio,
            'extension_ok': self.extension_ok,
        }



# ============================================================
# 核心算法: 从分型序列找ABC
# ============================================================

def find_abc_from_fractals(fractals: List[Fractal]) -> Optional[Tuple[Fractal, Fractal, Fractal]]:
    """
    从分型序列中找最近的ABC三点。

    规则:
    - 取最后3个交替分型 (顶底交替)
    - 上升N字: A(底) → B(顶) → C(底)
    - 下降N字: A(顶) → B(底) → C(顶)

    返回: (A, B, C) 或 None
    """
    if len(fractals) < 3:
        return None

    # 确保顶底交替，从后往前取最后3个有效分型
    alternating = []
    for fx in reversed(fractals):
        if not alternating:
            alternating.append(fx)
        elif fx.type != alternating[-1].type:
            alternating.append(fx)
        # 同类型: 保留更极端的
        elif fx.type == "TOP" and fx.price > alternating[-1].price:
            alternating[-1] = fx
        elif fx.type == "BOTTOM" and fx.price < alternating[-1].price:
            alternating[-1] = fx

        if len(alternating) >= 3:
            break

    if len(alternating) < 3:
        return None

    # 反转回时间顺序: A, B, C
    A, B, C = alternating[2], alternating[1], alternating[0]
    return (A, B, C)


# ============================================================
# 波浪验证: 两条硬规则
# ============================================================

def _wave_validate(ns: NState, current_price: float) -> NState:
    """
    用波浪理论两条硬规则评估N字质量。

    规则1 — 回调深度 (浪2不破浪1起点):
      上升N: retrace = |B-C| / |B-A|, 越小越好
        < 0.382 → 强势回调 (quality +0.4)
        < 0.618 → 正常回调 (quality +0.25)
        < 0.786 → 深回调    (quality +0.1)
        >= 0.786 → 勉强成立 (quality +0)
      已经有C>A的硬约束，这里是精细评分。

    规则2 — 第三笔不能最短 (浪3不能最短):
      leg3 = |current - C|
      如果 leg3 < leg1 且 leg3 < leg2 → 第三笔最短 → extension_ok=False
      反之 → extension_ok=True (quality +0.35)

    基础分 0.25 (构成了完美N字本身就有底分)

    Returns:
        NState (quality, retrace_ratio, extension_ok 已填充)
    """
    # 计算三笔幅度
    ns.leg1_range = abs(ns.B - ns.A)
    ns.leg2_range = abs(ns.B - ns.C)

    if ns.direction == DIR_UP:
        ns.leg3_range = max(0, current_price - ns.C)
    elif ns.direction == DIR_DOWN:
        ns.leg3_range = max(0, ns.C - current_price)
    else:
        ns.leg3_range = 0

    # --- 规则1: 回调深度 ---
    if ns.leg1_range > 0:
        ns.retrace_ratio = ns.leg2_range / ns.leg1_range
    else:
        ns.retrace_ratio = 1.0

    # KEY-006: retrace_ratio > 3.0 属结构失真 (leg2 超出leg1三倍以上)
    if ns.retrace_ratio > 3.0:
        ns.quality = 0.0
        return ns

    quality = 0.25  # 基础分

    if ns.retrace_ratio < 0.382:
        quality += 0.4   # 浅回调 = 强势
    elif ns.retrace_ratio < 0.618:
        quality += 0.25  # 正常回调
    elif ns.retrace_ratio < 0.786:
        quality += 0.1   # 深回调
    # else: 极深回调，不加分

    # --- 规则2: 第三笔不能最短 ---
    if ns.leg3_range > 0:
        ns.extension_ok = not (ns.leg3_range < ns.leg1_range
                               and ns.leg3_range < ns.leg2_range)
    else:
        # 第三笔还没开始，暂时ok
        ns.extension_ok = True

    if ns.extension_ok:
        quality += 0.35

    ns.quality = min(quality, 1.0)
    return ns


# ============================================================
# 核心算法: N字状态判定
# ============================================================

def classify_n_state(
    A: Fractal, B: Fractal, C: Fractal,
    current_price: float,
    prev_state: Optional[NState] = None,
) -> NState:
    """
    根据ABC三点和当前价格，判定N字状态。

    上升N字条件: A=底, B=顶, C=底, C.price > A.price
    下降N字条件: A=顶, B=底, C=顶, C.price < A.price

    Args:
        A, B, C: 三个分型转折点
        current_price: 当前K线收盘价
        prev_state: 上一次的NState (用于继承prev_n和交易计数)

    Returns:
        NState
    """
    ns = NState()
    ns.A = A.price
    ns.B = B.price
    ns.C = C.price
    ns.A_index = A.bar_index
    ns.B_index = B.bar_index
    ns.C_index = C.bar_index

    # 继承前一个N字记录
    if prev_state:
        ns.prev_n_high = prev_state.prev_n_high
        ns.prev_n_low = prev_state.prev_n_low
        ns.prev_n_A = prev_state.prev_n_A

    # --- 判断N字方向 ---
    if A.type == "BOTTOM" and B.type == "TOP" and C.type == "BOTTOM":
        # 上升N字候选: A(底)→B(顶)→C(底)
        if C.price > A.price:
            # 完美上升N字: C底高于A底
            ns.direction = DIR_UP
            ns = _classify_up_n(ns, current_price, prev_state)
            # v2.1: 所有非SIDE状态都做波浪验证 (含DEEP_PULLBACK/PULLBACK)
            # 修复: 原仅PERFECT_N/UP_BREAK做验证 → DEEP_PULLBACK quality=0 → 被质量门槛误杀
            if ns.state != STATE_SIDE:
                ns = _wave_validate(ns, current_price)
        else:
            # C没有高于A → 不构成完美N字 → 震荡
            ns.state = STATE_SIDE
            ns.direction = DIR_NONE

    elif A.type == "TOP" and B.type == "BOTTOM" and C.type == "TOP":
        # 下降N字候选: A(顶)→B(底)→C(顶)
        if C.price < A.price:
            # 完美下降N字: C顶低于A顶
            ns.direction = DIR_DOWN
            ns = _classify_down_n(ns, current_price, prev_state)
            # v2.1: 同上，下降N字也对所有非SIDE状态做波浪验证
            if ns.state != STATE_SIDE:
                ns = _wave_validate(ns, current_price)
        else:
            # C没有低于A → 不构成完美N字 → 震荡
            ns.state = STATE_SIDE
            ns.direction = DIR_NONE
    else:
        # 分型序列不构成标准N字 → 震荡
        ns.state = STATE_SIDE
        ns.direction = DIR_NONE

    return ns


def _classify_up_n(ns: NState, current_price: float, prev_state: Optional[NState]) -> NState:
    """
    上升N字内部状态判定。

    A(底) → B(顶) → C(底, C>A) → 当前价格走势

    状态转换:
    - current_price > B → 第三笔已超过B，还在延续
    - current_price > prev_n_high → 突破前N字高点 → UP_BREAK
    - current_price < C → 跌回C以下 → 回调
    - current_price < B方向回落幅度过大 → 深度回调
    """
    # 更新最新高低
    ns.last_high = max(current_price, ns.B)
    ns.last_low = min(current_price, ns.C)

    # --- 检查突破 ---
    if ns.prev_n_high > 0 and current_price > ns.prev_n_high:
        ns.state = STATE_UP_BREAK
        ns.trailing_stop_active = True
        # 继承交易计数 (突破是PERFECT_N的升级，不重置)
        if prev_state and prev_state.direction == DIR_UP:
            ns.trade_count_long = prev_state.trade_count_long
            ns.trade_count_short = prev_state.trade_count_short
        return ns

    # --- 检查深度回调: 跌破B点 (上升N字中B是顶，跌破说明回调超过了上升段) ---
    # 注: 上升N字中，深度回调指价格跌破C点(最近的底)
    if current_price < ns.C:
        # 进一步检查: 是否跌破前N字区域
        if ns.prev_n_low > 0 and current_price < ns.prev_n_low:
            # 结构彻底破坏 → 切回震荡
            ns.state = STATE_SIDE
            ns.direction = DIR_NONE
            ns.trailing_stop_active = False
            return ns

        ns.state = STATE_DEEP_PULLBACK
        ns.trailing_stop_active = True
        if prev_state and prev_state.direction == DIR_UP:
            ns.trade_count_long = prev_state.trade_count_long
            ns.trade_count_short = prev_state.trade_count_short
        return ns

    # --- 检查回调: 价格从高点回落但仍在C之上 ---
    # 如果价格在C和B之间，且从最近高点回落，视为回调中
    if current_price < ns.B and prev_state and prev_state.state in (STATE_PERFECT_N, STATE_UP_BREAK):
        # 价格从B以上回落到B以下 → 回调
        if prev_state.last_high > ns.B and current_price < ns.B:
            ns.state = STATE_PULLBACK
            ns.trailing_stop_active = False
            ns.trade_count_long = prev_state.trade_count_long
            ns.trade_count_short = prev_state.trade_count_short
            return ns

    # --- 默认: 完美N字成立，第三笔顺势延续 ---
    ns.state = STATE_PERFECT_N
    ns.trailing_stop_active = False
    # 新N字成立时重置交易计数
    if prev_state is None or prev_state.state == STATE_SIDE or prev_state.direction != DIR_UP:
        ns.trade_count_long = 0
        ns.trade_count_short = 0
    else:
        ns.trade_count_long = prev_state.trade_count_long
        ns.trade_count_short = prev_state.trade_count_short

    # 保存当前N字为prev (供下次判断突破)
    ns.prev_n_high = ns.B  # 上升N字的高点是B
    ns.prev_n_low = ns.A   # 上升N字的低点是A
    ns.prev_n_A = ns.A

    return ns


def _classify_down_n(ns: NState, current_price: float, prev_state: Optional[NState]) -> NState:
    """
    下降N字内部状态判定 — 上升N字的完全镜像。

    A(顶) → B(底) → C(顶, C<A) → 当前价格走势
    """
    ns.last_high = max(current_price, ns.A)
    ns.last_low = min(current_price, ns.B)

    # --- 突破: 价格跌破前N字低点 ---
    if ns.prev_n_low > 0 and current_price < ns.prev_n_low:
        ns.state = STATE_DOWN_BREAK
        ns.trailing_stop_active = True
        if prev_state and prev_state.direction == DIR_DOWN:
            ns.trade_count_long = prev_state.trade_count_long
            ns.trade_count_short = prev_state.trade_count_short
        return ns

    # --- 深度回调: 价格涨破C点(最近的顶) ---
    if current_price > ns.C:
        if ns.prev_n_high > 0 and current_price > ns.prev_n_high:
            # 结构破坏
            ns.state = STATE_SIDE
            ns.direction = DIR_NONE
            ns.trailing_stop_active = False
            return ns

        ns.state = STATE_DEEP_PULLBACK
        ns.trailing_stop_active = True
        if prev_state and prev_state.direction == DIR_DOWN:
            ns.trade_count_long = prev_state.trade_count_long
            ns.trade_count_short = prev_state.trade_count_short
        return ns

    # --- 回调: 价格从低点反弹但仍在C之下 ---
    if current_price > ns.B and prev_state and prev_state.state in (STATE_PERFECT_N, STATE_DOWN_BREAK):
        if prev_state.last_low < ns.B and current_price > ns.B:
            ns.state = STATE_PULLBACK
            ns.trailing_stop_active = False
            ns.trade_count_long = prev_state.trade_count_long
            ns.trade_count_short = prev_state.trade_count_short
            return ns

    # --- 默认: 完美下降N字 ---
    ns.state = STATE_PERFECT_N
    ns.trailing_stop_active = False
    if prev_state is None or prev_state.state == STATE_SIDE or prev_state.direction != DIR_DOWN:
        ns.trade_count_long = 0
        ns.trade_count_short = 0
    else:
        ns.trade_count_long = prev_state.trade_count_long
        ns.trade_count_short = prev_state.trade_count_short

    ns.prev_n_high = ns.A  # 下降N字的高点是A
    ns.prev_n_low = ns.B   # 下降N字的低点是B
    ns.prev_n_A = ns.A

    return ns


# ============================================================
# 门控函数
# ============================================================

def check_n_structure_gate(
    n_state: NState,
    direction: str,
    max_trades: Optional[Dict[str, int]] = None,
) -> Tuple[bool, str, bool]:
    """
    N字门控 — 替代HOLD带的全局第一层过滤。

    Args:
        n_state: 当前N字状态
        direction: 'BUY' 或 'SELL'
        max_trades: 可选的品种参数覆盖, keys:
            side_max_trades (default 1)
            perfect_n_max_trades (default 1)
            break_max_trades (default 2)
            deep_pullback_max_trades (default 1)

    Returns:
        (allowed, reason, trailing_stop_allowed)
    """
    st = n_state.state
    d = n_state.direction

    # v3.661: 品种参数化 — 从max_trades字典读取, 无则用默认
    mt = max_trades or {}
    _side_max = mt.get("side_max_trades", 1)
    _perfect_max = mt.get("perfect_n_max_trades", 1)
    _break_max = mt.get("break_max_trades", 2)
    _deep_max = mt.get("deep_pullback_max_trades", 1)

    # --- 状态一: 震荡 ---
    if st == STATE_SIDE:
        count = n_state.trade_count_long if direction == "BUY" else n_state.trade_count_short
        if count >= _side_max:
            return False, f"震荡,{direction}机会已用({count}/{_side_max})", False
        return True, f"震荡,给予{direction}1次机会", False

    # KEY-006: 非SIDE最低质量门槛 — 过滤底部低质量信号
    # v3.663: 0.65→0.55 — 分析显示quality=0.60(正常回调+ext_ok)被误杀74次
    # v3.678: 0.55→0.45 — dashboard显示门控拦截率过高(移动止盈65%,N字78%),quality=0.50被误杀
    # quality=0.00(无结构)和0.25(极深回调)仍被正确拦截
    _min_quality = 0.45
    if st != STATE_SIDE and n_state.quality < _min_quality:
        return False, f"质量不足({n_state.quality:.2f}<{_min_quality}),拦截{st}", False

    # --- 状态二: 完美N字,未突破 ---
    if st == STATE_PERFECT_N:
        # v2.0: 波浪验证 — 第三笔最短时降级
        if not n_state.extension_ok:
            # 浪3最短 = 动力不足，降级为只给1次机会且标记
            _perfect_max = min(_perfect_max, 1)

        # v2.0: 高质量N字加机会 (quality >= 0.8 额外+1)
        if n_state.quality >= 0.8:
            _perfect_max = max(_perfect_max, 2)

        if d == DIR_UP:
            if direction == "BUY":
                if n_state.trade_count_long >= _perfect_max:
                    return False, f"完美N字UP,BUY已用({n_state.trade_count_long}/{_perfect_max})Q={n_state.quality:.0%}", False
                return True, f"完美N字UP,允许BUY Q={n_state.quality:.0%}", False
            else:
                return False, f"完美N字UP,阻止SELL Q={n_state.quality:.0%}", False
        elif d == DIR_DOWN:
            if direction == "SELL":
                if n_state.trade_count_short >= _perfect_max:
                    return False, f"完美N字DOWN,SELL已用({n_state.trade_count_short}/{_perfect_max})Q={n_state.quality:.0%}", False
                return True, f"完美N字DOWN,允许SELL Q={n_state.quality:.0%}", False
            else:
                return False, f"完美N字DOWN,阻止BUY Q={n_state.quality:.0%}", False

    # --- 状态三: 突破 ---
    if st == STATE_UP_BREAK:
        # v2.0: 高质量突破给更多机会
        if n_state.quality >= 0.8:
            _break_max = max(_break_max, 3)
        if direction == "BUY":
            if n_state.trade_count_long >= _break_max:
                return False, f"上升突破,BUY已用({n_state.trade_count_long}/{_break_max})", True
            return True, f"上升突破,允许BUY({n_state.trade_count_long+1}/{_break_max})", True
        else:
            return False, "上升突破,阻止SELL", True

    if st == STATE_DOWN_BREAK:
        if n_state.quality >= 0.8:
            _break_max = max(_break_max, 3)
        if direction == "SELL":
            if n_state.trade_count_short >= _break_max:
                return False, f"下降突破,SELL已用({n_state.trade_count_short}/{_break_max})", True
            return True, f"下降突破,允许SELL({n_state.trade_count_short+1}/{_break_max})", True
        else:
            return False, "下降突破,阻止BUY", True

    # --- 状态四: 回调 ---
    if st == STATE_PULLBACK:
        return False, f"回调中({d}),等待新N字", False

    # --- 状态五: 深度回调 ---
    # v3.662: 深度回调不再一刀切阻止原方向, 改为限制次数
    # 原因: 回调可能是真反转(拦截对), 也可能是假弹(拦截错)
    # 两个方向都给有限机会, 用_deep_max控制
    if st == STATE_DEEP_PULLBACK:
        if d == DIR_UP:
            # 原方向UP，深度回调
            if direction == "SELL":
                # 反向防守SELL
                if n_state.trade_count_short >= _deep_max:
                    return False, f"深度回调UP,防守SELL已用({n_state.trade_count_short}/{_deep_max})", True
                return True, "深度回调UP,允许防守SELL", True
            else:
                # 原方向BUY: 给有限机会(回调可能失败,趋势恢复)
                if n_state.trade_count_long >= _deep_max:
                    return False, f"深度回调UP,顺势BUY已用({n_state.trade_count_long}/{_deep_max})", True
                return True, f"深度回调UP,给予BUY1次机会({n_state.trade_count_long+1}/{_deep_max})", True
        elif d == DIR_DOWN:
            # 原方向DOWN，深度回调
            if direction == "BUY":
                # 反向防守BUY
                if n_state.trade_count_long >= _deep_max:
                    return False, f"深度回调DOWN,防守BUY已用({n_state.trade_count_long}/{_deep_max})", True
                return True, "深度回调DOWN,允许防守BUY", True
            else:
                # 原方向SELL: 给有限机会(回调可能失败,趋势恢复)
                if n_state.trade_count_short >= _deep_max:
                    return False, f"深度回调DOWN,顺势SELL已用({n_state.trade_count_short}/{_deep_max})", True
                return True, f"深度回调DOWN,给予SELL1次机会({n_state.trade_count_short+1}/{_deep_max})", True

    # fallback
    return True, f"未知状态{st},放行", False


# ============================================================
# 交易计数更新
# ============================================================

def record_trade(n_state: NState, direction: str) -> NState:
    """
    交易执行后更新计数。
    在实际发单成功后调用。
    """
    if direction == "BUY":
        n_state.trade_count_long += 1
    elif direction == "SELL":
        n_state.trade_count_short += 1
    return n_state



# ============================================================
# 全局状态管理
# ============================================================

# 各品种的N字状态缓存
_n_states: Dict[str, NState] = {}


def update_n_state(symbol: str, fractals_4h: List[Fractal], current_price: float) -> NState:
    """
    更新品种的N字状态 — 每次扫描时调用。

    Args:
        symbol: 品种
        fractals_4h: 当前周期(4H)的分型序列
        current_price: 当前价格

    Returns:
        更新后的NState
    """
    prev = _n_states.get(symbol)

    abc = find_abc_from_fractals(fractals_4h)
    if abc is None:
        # 没找到有效ABC → 震荡
        ns = NState()
        ns.state = STATE_SIDE
        ns.direction = DIR_NONE
        # 保留交易计数
        if prev:
            ns.trade_count_long = prev.trade_count_long
            ns.trade_count_short = prev.trade_count_short
            ns.prev_n_high = prev.prev_n_high
            ns.prev_n_low = prev.prev_n_low
        _n_states[symbol] = ns
        return ns

    A, B, C = abc
    ns = classify_n_state(A, B, C, current_price, prev)
    _n_states[symbol] = ns
    return ns


def get_n_state(symbol: str) -> NState:
    """获取品种的N字状态"""
    return _n_states.get(symbol, NState())


# ============================================================
# 测试验证
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("N字结构门控 v2.0 — 波浪验证 算法测试")
    print("=" * 60)

    # 测试1: 上升N字 — 浅回调高质量
    print("\n--- 测试1: 上升N字(浅回调=高质量) ---")
    fractals = [
        Fractal(type="BOTTOM", price=100.0, bar_index=0),
        Fractal(type="TOP",    price=120.0, bar_index=5),
        Fractal(type="BOTTOM", price=114.0, bar_index=10),  # 回调30%，浅回调
    ]
    abc = find_abc_from_fractals(fractals)
    A, B, C = abc
    print(f"  A={A.price}(底) B={B.price}(顶) C={C.price}(底)")
    print(f"  回调: {(120-114)/(120-100):.1%}")

    ns = classify_n_state(A, B, C, current_price=125.0)
    print(f"  当前价125 → state={ns.state} quality={ns.quality:.0%}")
    print(f"  retrace={ns.retrace_ratio:.3f} leg1={ns.leg1_range:.1f} "
          f"leg2={ns.leg2_range:.1f} leg3={ns.leg3_range:.1f} ext_ok={ns.extension_ok}")
    assert ns.quality >= 0.8, f"浅回调+长延续应高质量, got {ns.quality}"
    assert ns.extension_ok is True

    # 高质量N字应该给2次BUY机会
    ok, reason, _ = check_n_structure_gate(ns, "BUY")
    print(f"  BUY → {ok}, {reason}")
    assert ok is True
    ns = record_trade(ns, "BUY")
    ok, reason, _ = check_n_structure_gate(ns, "BUY")
    print(f"  BUY(第2次) → {ok}, {reason}")
    assert ok is True, "高质量N字应给2次机会"

    # 测试2: 上升N字 — 深回调低质量
    print("\n--- 测试2: 上升N字(深回调=低质量) ---")
    fractals = [
        Fractal(type="BOTTOM", price=100.0, bar_index=0),
        Fractal(type="TOP",    price=120.0, bar_index=5),
        Fractal(type="BOTTOM", price=101.0, bar_index=10),  # 回调95%，极深
    ]
    abc = find_abc_from_fractals(fractals)
    A, B, C = abc
    ns = classify_n_state(A, B, C, current_price=108.0)
    print(f"  回调: {(120-101)/(120-100):.1%} → quality={ns.quality:.0%}")
    print(f"  retrace={ns.retrace_ratio:.3f} ext_ok={ns.extension_ok}")
    assert ns.quality < 0.7, f"深回调应低质量, got {ns.quality}"

    # 测试3: 第三笔最短 → extension_ok=False
    print("\n--- 测试3: 第三笔最短(浪3最短规则) ---")
    fractals = [
        Fractal(type="BOTTOM", price=100.0, bar_index=0),
        Fractal(type="TOP",    price=130.0, bar_index=5),   # leg1=30
        Fractal(type="BOTTOM", price=110.0, bar_index=10),  # leg2=20
    ]
    abc = find_abc_from_fractals(fractals)
    A, B, C = abc
    ns = classify_n_state(A, B, C, current_price=115.0)  # leg3=5, 最短
    print(f"  leg1={ns.leg1_range:.0f} leg2={ns.leg2_range:.0f} leg3={ns.leg3_range:.0f}")
    print(f"  extension_ok={ns.extension_ok} quality={ns.quality:.0%}")
    assert ns.extension_ok is False, "leg3(5)<leg1(30)且<leg2(20), 应为False"

    # v2.1: extension_ok=False + 深回调 → quality=0.35 < 0.65 → 质量门槛拦截
    ok, reason, _ = check_n_structure_gate(ns, "BUY")
    print(f"  BUY → {ok}, {reason}")
    assert ok is False, "leg3最短+深回调=低质量(0.35<0.65)应拦截"

    # 测试4: 下降N字
    print("\n--- 测试4: 下降N字 ---")
    fractals = [
        Fractal(type="TOP",    price=120.0, bar_index=0),
        Fractal(type="BOTTOM", price=95.0,  bar_index=5),
        Fractal(type="TOP",    price=110.0, bar_index=10),
    ]
    abc = find_abc_from_fractals(fractals)
    A, B, C = abc
    ns = classify_n_state(A, B, C, current_price=85.0)
    print(f"  quality={ns.quality:.0%} retrace={ns.retrace_ratio:.3f} ext_ok={ns.extension_ok}")
    assert ns.direction == DIR_DOWN
    assert ns.quality > 0

    ok, reason, _ = check_n_structure_gate(ns, "SELL")
    print(f"  SELL → {ok}, {reason}")
    assert ok is True

    # 测试5: 震荡
    print("\n--- 测试5: 震荡(C<A) ---")
    fractals = [
        Fractal(type="BOTTOM", price=100.0, bar_index=0),
        Fractal(type="TOP",    price=115.0, bar_index=5),
        Fractal(type="BOTTOM", price=98.0,  bar_index=10),
    ]
    abc = find_abc_from_fractals(fractals)
    A, B, C = abc
    ns = classify_n_state(A, B, C, current_price=105.0)
    print(f"  state={ns.state} quality={ns.quality:.0%}")
    assert ns.state == STATE_SIDE
    assert ns.quality == 0.0  # 震荡无质量分

    # 测试6: 深度回调
    print("\n--- 测试6: 深度回调 ---")
    fractals = [
        Fractal(type="BOTTOM", price=100.0, bar_index=0),
        Fractal(type="TOP",    price=120.0, bar_index=5),
        Fractal(type="BOTTOM", price=105.0, bar_index=10),
    ]
    abc = find_abc_from_fractals(fractals)
    A, B, C = abc
    ns_prev = NState(prev_n_high=118.0, prev_n_low=95.0, direction=DIR_UP)
    ns = classify_n_state(A, B, C, current_price=103.0, prev_state=ns_prev)
    print(f"  state={ns.state} (跌破C=105) quality={ns.quality:.0%}")
    assert ns.state == STATE_DEEP_PULLBACK
    # v2.1: DEEP_PULLBACK现在有quality评分 (原始N字: retrace=15/20=75%, 基础0.25+深回调0.1+ext_ok0.35=0.70)
    assert ns.quality > 0, f"v2.1修复: DEEP_PULLBACK应有quality, got {ns.quality}"
    print(f"  retrace={ns.retrace_ratio:.3f} ext_ok={ns.extension_ok}")

    # v2.1验证: DEEP_PULLBACK quality>=0.65时门控应放行
    ok, reason, _ = check_n_structure_gate(ns, "SELL")
    print(f"  防守SELL → {ok}, {reason}")
    assert ok is True, f"DEEP_PULLBACK quality≥0.65应允许防守SELL"

    print("\n" + "=" * 60)
    print("全部测试通过 ✅")
    print("=" * 60)
