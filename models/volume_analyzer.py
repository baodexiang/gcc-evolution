"""
Module D: 量价分析模块 — SQS信号质量门槛 + 统一量价过滤
v1.0: Phase 1 观察模式 (只记录, 不拦截)

数据来源: 现有OHLCV数据 (无需真实订单簿)
输出: SQS分数 / VF过滤结果 / CVD趋势 / 相对成交量

接口:
- get_signal_quality(ohlcv, direction) → float  # SQS 0~1
- volume_filter(direction, ohlcv) → str          # UPGRADE/PASS/DOWNGRADE/REJECT
- get_cvd(ohlcv) → list                          # 近似CVD序列
- get_relative_volume(ohlcv) → float              # 相对成交量
- get_close_position(ohlcv) → float               # 收盘位置 0~1
- get_trend_health(ohlcv, trend_dir) → float      # P1预留: 趋势健康度
- get_volume_profile(ohlcv, bins) → dict           # P1预留: VP分布
"""

import logging
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

NY_TZ = ZoneInfo("America/New_York")

ORDERFLOW_STATE_FILE = "state/orderflow_state.json"


def _safe_json_write(filepath, data):
    """安全写入JSON文件(原子操作)"""
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        temp_file = filepath + ".tmp"
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        os.replace(temp_file, filepath)
        return True
    except Exception as e:
        logger.error(f"[VolumeAnalyzer] 写入 {filepath} 失败: {e}")
        return False


class VolumeAnalyzer:
    """
    量价分析模块 v1.0 — 基于OHLCV近似订单流

    Phase 1: 纯观察模式, 只计算+记录, 不拦截交易
    Phase 2: 启用SQS门槛拦截 + VF过滤拦截
    """

    # --- 基础计算 ---

    @staticmethod
    def get_close_position(bar: dict) -> float:
        """
        单根K线收盘位置: (close - low) / (high - low)
        返回 0~1, 收在高位=1, 收在低位=0
        """
        high = bar.get("high", 0)
        low = bar.get("low", 0)
        close = bar.get("close", 0)
        if high <= low or high <= 0:
            return 0.5
        return max(0.0, min(1.0, (close - low) / (high - low)))

    @staticmethod
    def get_delta(bar: dict) -> float:
        """
        单根K线近似delta: vol × (2 × close_pos - 1)
        close_pos=1 → delta=+vol (全买), close_pos=0 → delta=-vol (全卖)
        """
        vol = bar.get("volume", 0)
        if vol <= 0:
            return 0.0
        high = bar.get("high", 0)
        low = bar.get("low", 0)
        close = bar.get("close", 0)
        if high <= low or high <= 0:
            return 0.0
        close_pos = (close - low) / (high - low)
        return vol * (2.0 * close_pos - 1.0)

    @staticmethod
    def get_cvd(ohlcv: list) -> list:
        """
        累计量差 CVD (Cumulative Volume Delta)
        delta_i = vol_i × (2 × close_pos_i - 1), CVD = cumsum(delta)
        返回与ohlcv等长的CVD序列
        """
        cvd = []
        cumulative = 0.0
        for bar in ohlcv:
            vol = bar.get("volume", 0)
            high = bar.get("high", 0)
            low = bar.get("low", 0)
            close = bar.get("close", 0)
            if vol > 0 and high > low and high > 0:
                close_pos = (close - low) / (high - low)
                delta = vol * (2.0 * close_pos - 1.0)
            else:
                delta = 0.0
            cumulative += delta
            cvd.append(cumulative)
        return cvd

    @staticmethod
    def get_relative_volume(ohlcv: list, ma_period: int = 20) -> float:
        """
        相对成交量: 最新K线volume / MA(volume, ma_period)
        > 1.5 = 放量, 0.8~1.2 = 正常, < 0.5 = 缩量
        """
        if not ohlcv or len(ohlcv) < 2:
            return 1.0

        volumes = [bar.get("volume", 0) for bar in ohlcv]
        current_vol = volumes[-1]
        if current_vol <= 0:
            return 0.0

        # MA基线: 取最后ma_period根(不含最新)的均值
        lookback = volumes[-(ma_period + 1):-1] if len(volumes) > ma_period else volumes[:-1]
        if not lookback:
            return 1.0
        avg_vol = sum(lookback) / len(lookback)
        if avg_vol <= 0:
            return 0.0

        return current_vol / avg_vol

    def get_signal_quality(self, ohlcv: list, direction: str) -> float:
        """
        信号质量分 SQS (Signal Quality Score) 0~1

        BUY: rel_vol × close_pos × (1 + delta_ratio)
        SELL: rel_vol × (1 - close_pos) × (1 + abs(delta_ratio))

        delta_ratio = 最新delta / avg_abs_delta (衡量买卖力量)
        """
        if not ohlcv or len(ohlcv) < 5:
            return 0.5  # 数据不足返回中性

        rel_vol = self.get_relative_volume(ohlcv)
        last_bar = ohlcv[-1]
        close_pos = self.get_close_position(last_bar)
        last_delta = self.get_delta(last_bar)

        # 计算平均delta幅度作为基线
        recent_deltas = [abs(self.get_delta(bar)) for bar in ohlcv[-20:]]
        avg_abs_delta = sum(recent_deltas) / len(recent_deltas) if recent_deltas else 1.0
        if avg_abs_delta <= 0:
            avg_abs_delta = 1.0
        delta_ratio = last_delta / avg_abs_delta

        direction_upper = direction.upper()
        if direction_upper in ("BUY", "STRONG_BUY"):
            raw = rel_vol * close_pos * (1.0 + max(0, delta_ratio))
        elif direction_upper in ("SELL", "STRONG_SELL"):
            raw = rel_vol * (1.0 - close_pos) * (1.0 + abs(min(0, delta_ratio)))
        else:
            raw = 0.5

        # 归一化到 0~1
        return max(0.0, min(1.0, raw))

    def volume_filter(self, direction: str, ohlcv: list) -> str:
        """
        统一量价过滤 — 所有外挂信号的通用过滤层

        返回:
        - "REJECT": 极度缩量 (rel_vol < 0.5), 拒绝信号
        - "DOWNGRADE": CVD背离 + rel_vol < 1.0, 信号降级
        - "UPGRADE": 放量(>1.5) + CVD一致, 信号升级
        - "PASS": 正常通过
        """
        if not ohlcv or len(ohlcv) < 5:
            return "PASS"  # 数据不足不过滤

        rel_vol = self.get_relative_volume(ohlcv)

        # 1. 极度缩量 → REJECT
        if rel_vol < 0.5:
            return "REJECT"

        # 2. CVD一致性检查
        cvd = self.get_cvd(ohlcv)
        cvd_aligned = self._check_cvd_alignment(direction, cvd)

        # 3. CVD背离 + 缩量 → DOWNGRADE
        if not cvd_aligned and rel_vol < 1.0:
            return "DOWNGRADE"

        # 4. 放量 + CVD一致 → UPGRADE
        if rel_vol > 1.5 and cvd_aligned:
            return "UPGRADE"

        return "PASS"

    def _check_cvd_alignment(self, direction: str, cvd: list) -> bool:
        """
        检查CVD趋势是否与信号方向一致
        用最后5根CVD的斜率判断方向
        """
        if len(cvd) < 5:
            return True  # 数据不足, 默认一致

        recent = cvd[-5:]
        slope = recent[-1] - recent[0]

        direction_upper = direction.upper()
        if direction_upper in ("BUY", "STRONG_BUY"):
            return slope > 0  # BUY需要CVD上升
        elif direction_upper in ("SELL", "STRONG_SELL"):
            return slope < 0  # SELL需要CVD下降
        return True

    def get_cvd_trend_label(self, ohlcv: list, direction: str = "") -> str:
        """
        CVD趋势标签 (供监控面板显示)
        返回: "↑同向" / "↓背离" / "→中性"
        """
        if not ohlcv or len(ohlcv) < 5:
            return "→中性"

        cvd = self.get_cvd(ohlcv)
        recent = cvd[-5:]
        slope = recent[-1] - recent[0]

        if abs(slope) < 1e-10:
            return "→中性"

        if direction:
            aligned = self._check_cvd_alignment(direction, cvd)
            if slope > 0:
                return "↑同向" if aligned else "↑背离"
            else:
                return "↓同向" if aligned else "↓背离"

        # 无方向时只显示CVD方向
        return "↑" if slope > 0 else "↓"

    # --- P1: SYS-025~028 量价增强 ---

    def get_trend_health(self, ohlcv: list, trend_dir: str) -> float:
        """
        P1预留: 趋势健康度 = CVD一致性 × 相对成交量
        0~1, 越高越健康
        """
        if not ohlcv or len(ohlcv) < 5:
            return 0.5

        cvd = self.get_cvd(ohlcv)
        cvd_aligned = self._check_cvd_alignment(trend_dir, cvd)
        cvd_score = 1.0 if cvd_aligned else 0.3

        rel_vol = self.get_relative_volume(ohlcv)
        vol_score = min(1.5, rel_vol) / 1.5  # 归一化, 1.5+ = 1.0

        return cvd_score * vol_score

    def get_volume_profile(self, ohlcv: list, bins: int = 50) -> dict:
        """
        P1预留: 成交量分布 (Volume Profile)
        返回 {"poc": float, "hvn": [float, ...], "lvn": [float, ...]}
        """
        if not ohlcv or len(ohlcv) < 10:
            return {"poc": 0, "hvn": [], "lvn": []}

        all_highs = [bar.get("high", 0) for bar in ohlcv]
        all_lows = [bar.get("low", 0) for bar in ohlcv]
        price_max = max(all_highs)
        price_min = min(all_lows)
        if price_max <= price_min:
            return {"poc": 0, "hvn": [], "lvn": []}

        bin_size = (price_max - price_min) / bins
        profile = [0.0] * bins

        for bar in ohlcv:
            vol = bar.get("volume", 0)
            high = bar.get("high", 0)
            low = bar.get("low", 0)
            if vol <= 0 or high <= low:
                continue
            # 将成交量均匀分布到K线覆盖的价格区间
            low_bin = max(0, int((low - price_min) / bin_size))
            high_bin = min(bins - 1, int((high - price_min) / bin_size))
            n_bins = high_bin - low_bin + 1
            vol_per_bin = vol / n_bins if n_bins > 0 else 0
            for i in range(low_bin, high_bin + 1):
                profile[i] += vol_per_bin

        # POC = 成交量最大的档位
        poc_bin = profile.index(max(profile))
        poc_price = price_min + (poc_bin + 0.5) * bin_size

        # HVN/LVN: 高于/低于均值的区域
        avg_vol = sum(profile) / bins if bins > 0 else 0
        hvn = []
        lvn = []
        for i, v in enumerate(profile):
            price = price_min + (i + 0.5) * bin_size
            if v > avg_vol * 1.5:
                hvn.append(round(price, 4))
            elif v < avg_vol * 0.5 and v > 0:
                lvn.append(round(price, 4))

        return {"poc": round(poc_price, 4), "hvn": hvn, "lvn": lvn}

    def get_donchian_volume_score(self, ohlcv: list, pos_in_channel: float) -> dict:
        """
        SYS-026: Donchian量价增强 — 通道位置 × 成交量密度 × 动量质量
        Phase 1: 仅记录观察, 不参与实际过滤决策

        volume_density = 突破/跌破区域的成交量集中度 (VP分布)
        momentum_quality = 最后3根K线的方向一致性

        Returns:
            {"score": 0~1, "vol_density": float, "momentum": float,
             "suggestion": "CONFIRM"/"WEAK"/"DIVERGE"}
        """
        default = {"score": 0.5, "vol_density": 0.5, "momentum": 0.5, "suggestion": "WEAK"}
        if not ohlcv or len(ohlcv) < 10:
            return default

        # 1. 相对成交量 (最后1根 vs MA20)
        rel_vol = self.get_relative_volume(ohlcv)
        vol_score = min(2.0, rel_vol) / 2.0  # 归一化到 0~1

        # 2. 成交量密度: 最后5根的平均vol / 前15根平均vol
        recent_vols = [b.get("volume", 0) for b in ohlcv[-5:]]
        earlier_vols = [b.get("volume", 0) for b in ohlcv[-20:-5]] if len(ohlcv) >= 20 else [b.get("volume", 0) for b in ohlcv[:-5]]
        avg_recent = sum(recent_vols) / len(recent_vols) if recent_vols else 1
        avg_earlier = sum(earlier_vols) / len(earlier_vols) if earlier_vols else 1
        vol_density = avg_recent / avg_earlier if avg_earlier > 0 else 1.0
        vol_density_score = min(2.0, vol_density) / 2.0

        # 3. 动量质量: 最后3根K线收盘方向一致性
        last3 = ohlcv[-3:]
        up_count = sum(1 for b in last3 if b.get("close", 0) > b.get("open", 0))
        down_count = 3 - up_count
        momentum = max(up_count, down_count) / 3.0  # 一致性 0.33~1.0

        # 4. 综合分: pos × vol_density × momentum
        combined = pos_in_channel * vol_density_score * momentum
        combined = max(0.0, min(1.0, combined))

        # 5. 建议
        if combined > 0.6 and vol_density > 1.2:
            suggestion = "CONFIRM"  # 量价确认
        elif combined < 0.3 or vol_density < 0.7:
            suggestion = "DIVERGE"  # 量价背离
        else:
            suggestion = "WEAK"  # 信号一般

        return {
            "score": round(combined, 3),
            "vol_density": round(vol_density, 3),
            "momentum": round(momentum, 3),
            "suggestion": suggestion
        }

    def anchor_stop_to_hvn(self, ohlcv: list, current_price: float,
                           atr_stop_price: float, direction: str = "SELL") -> dict:
        """
        SYS-028: 止盈止损VP锚定 — 将止损位吸附到最近的HVN
        Phase 2: 实际替换ATR止损 (suggested_stop >= atr_stop, 更紧)

        逻辑:
        - SELL止损: 从ATR止损价向上找最近HVN, 如果距离<1个ATR则吸附
        - BUY止盈: 从ATR止盈价向下找最近HVN, 如果距离<1个ATR则吸附
        - HVN = 成交量密集区, 价格在此有支撑/阻力

        Returns:
            {"original_stop": float, "suggested_stop": float,
             "nearest_hvn": float, "distance_pct": float,
             "anchored": bool}
        """
        default = {
            "original_stop": atr_stop_price,
            "suggested_stop": atr_stop_price,
            "nearest_hvn": 0,
            "distance_pct": 0,
            "anchored": False
        }
        if not ohlcv or len(ohlcv) < 10 or current_price <= 0:
            return default

        vp = self.get_volume_profile(ohlcv, bins=50)
        hvn_list = vp.get("hvn", [])
        if not hvn_list:
            return default

        # ATR近似: 用止损距离估算
        atr_approx = abs(current_price - atr_stop_price)
        if atr_approx <= 0:
            return default

        if direction.upper() == "SELL":
            # SELL止损: 找比止损价高的最近HVN (支撑位)
            candidates = [h for h in hvn_list if h > atr_stop_price and h < current_price]
            if not candidates:
                return default
            nearest = min(candidates, key=lambda h: h - atr_stop_price)
        else:
            # BUY止盈: 找比止盈价低的最近HVN (阻力位)
            candidates = [h for h in hvn_list if h < atr_stop_price and h > current_price]
            if not candidates:
                return default
            nearest = max(candidates, key=lambda h: atr_stop_price - h)

        distance = abs(nearest - atr_stop_price)
        distance_pct = distance / current_price if current_price > 0 else 0

        # 只在距离小于1个ATR时吸附
        anchored = distance < atr_approx
        suggested = nearest if anchored else atr_stop_price

        return {
            "original_stop": round(atr_stop_price, 4),
            "suggested_stop": round(suggested, 4),
            "nearest_hvn": round(nearest, 4),
            "distance_pct": round(distance_pct, 4),
            "anchored": anchored
        }

    # --- 状态写入 ---

    @staticmethod
    def save_orderflow_state(symbol: str, rel_vol: float, cvd_trend: str,
                             sqs: float, vf: str, blocked_count: int = 0,
                             trend_health: float = None, vp_poc: float = None,
                             donchian_vol_score: float = None):
        """
        写入 state/orderflow_state.json 供monitor读取
        增量更新: 读取→合并→写入
        v1.1: 新增 trend_health / vp_poc / donchian_vol_score (SYS-025~028)
        """
        try:
            state = {}
            if os.path.exists(ORDERFLOW_STATE_FILE):
                with open(ORDERFLOW_STATE_FILE, 'r', encoding='utf-8') as f:
                    state = json.load(f)
        except Exception:
            state = {}

        entry = {
            "rel_vol": round(rel_vol, 2),
            "cvd_trend": cvd_trend,
            "sqs": round(sqs, 2),
            "vf": vf,
            "blocked_count": blocked_count,
            "updated": datetime.now(NY_TZ).strftime("%Y-%m-%d %H:%M:%S"),
        }
        if trend_health is not None:
            entry["trend_health"] = round(trend_health, 3)
        if vp_poc is not None:
            entry["vp_poc"] = round(vp_poc, 2)
        if donchian_vol_score is not None:
            entry["donchian_vol_score"] = round(donchian_vol_score, 3)

        state[symbol] = entry
        _safe_json_write(ORDERFLOW_STATE_FILE, state)
