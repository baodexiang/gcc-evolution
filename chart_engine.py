"""
ChartEngine v1.0 — 统一K线截图接口
=====================================
为 Vision 过滤模块提供高质量 TradingView 风格截图。

引擎优先级：
  A. lightweight-charts (TradingView风格，最佳AI识别率)
  B. mplfinance (降级备用，当前已有)

截图规格 (Vision识别优化)：
  - 尺寸: 1200×700px (16:9)
  - 背景: #1e1e1e 深色
  - 内容: K线 + 成交量 + 网格
  - 不加: 指标窗口/文字标注/买卖点（干扰形态识别）
  - EMA10: 可选（default=False，需要时传 show_ema=True）

用法：
    from chart_engine import ChartEngine
    engine = ChartEngine()
    img_b64 = engine.screenshot_b64(bars, symbol="AMD")
"""

import base64
import io
import os
import time
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ============================================================
# 截图参数 (Vision识别优化，见需求文档 7.1)
# ============================================================
VISION_CHART_CONFIG = {
    "bars":        90,       # 60~90根，覆盖所有形态
    "width":       1200,     # 够宽，蜡烛不挤在一起
    "height":      700,      # 16:9
    "show_volume": True,     # 必须成交量（Wyckoff需要）
    "background":  "#1e1e1e",# 深色背景（TradingView默认）
    "up_color":    "#26a69a",# 绿涨
    "down_color":  "#ef5350",# 红跌
    "grid":        True,     # 有网格帮助判断高低
    "crosshair":   False,    # 关十字线（干扰识别）
    "dpi":         150,      # 够清晰但文件不大
}


# ============================================================
# 引擎A: LightweightCharts (TradingView风格)
# ============================================================

def _generate_lightweight(
    bars: list,
    symbol: str,
    bars_count: int = 90,
    show_ema: bool = False,
) -> Optional[bytes]:
    """
    用 lightweight-charts-python 生成 TradingView 风格截图。
    返回 PNG bytes，失败返回 None。
    """
    try:
        import pandas as pd
        from lightweight_charts import Chart

        df = _bars_to_df(bars, bars_count)
        if df is None or df.empty:
            return None

        c = Chart(
            width=VISION_CHART_CONFIG["width"],
            height=VISION_CHART_CONFIG["height"],
            inner_width=1,
            inner_height=1,
            toolbox=False,
        )

        # TradingView深色主题
        c.layout(
            background_color=VISION_CHART_CONFIG["background"],
            text_color="#d1d4dc",
            font_size=12,
        )
        c.grid(
            vert_enabled=VISION_CHART_CONFIG["grid"],
            horz_enabled=VISION_CHART_CONFIG["grid"],
            color="#2B2B43",
        )

        # K线颜色
        c.candle_style(
            up_color=VISION_CHART_CONFIG["up_color"],
            down_color=VISION_CHART_CONFIG["down_color"],
            border_up_color=VISION_CHART_CONFIG["up_color"],
            border_down_color=VISION_CHART_CONFIG["down_color"],
            wick_up_color=VISION_CHART_CONFIG["up_color"],
            wick_down_color=VISION_CHART_CONFIG["down_color"],
        )

        # 成交量（半透明）
        if VISION_CHART_CONFIG["show_volume"]:
            c.volume_config(
                up_color="rgba(38,166,154,0.5)",
                down_color="rgba(239,83,80,0.5)",
            )

        c.set(df)

        # 可选 EMA10（用户决定是否启用）
        if show_ema:
            closes = df["close"].values
            ema10  = _calc_ema(closes, 10)
            # line.set() 需要 DataFrame 含 'time' + 'value' 列
            # line.set() 要求列名与 create_line 的 name 参数一致
            ema_df = pd.DataFrame({"time": df["time"].values, "EMA10": ema10})
            line = c.create_line("EMA10", color="#ffffff", width=1,
                                 price_line=False, price_label=False)
            line.set(ema_df)

        # 截图
        c.show(block=False)
        time.sleep(1.5)  # 等渲染完成
        img_bytes = c.screenshot()
        c.exit()
        return img_bytes

    except Exception as e:
        logger.warning(f"[ChartEngine] LightweightCharts失败: {e}")
        return None


# ============================================================
# 引擎B: mplfinance (降级备用)
# ============================================================

def _generate_mplfinance(
    bars: list,
    symbol: str,
    bars_count: int = 90,
    show_ema: bool = False,
) -> Optional[bytes]:
    """
    用 mplfinance 生成降级截图（纯Python，零依赖）。
    模拟 TradingView 配色，但视觉质量低于 LightweightCharts。
    """
    try:
        import mplfinance as mpf
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import pandas as pd
        import numpy as np

        df = _bars_to_df(bars, bars_count)
        if df is None or df.empty:
            return None

        # 设置索引为日期
        df = df.copy()
        df.index = pd.DatetimeIndex(df["time"])
        df = df[["open", "high", "low", "close", "volume"]]
        df.columns = ["Open", "High", "Low", "Close", "Volume"]

        mc = mpf.make_marketcolors(
            up=VISION_CHART_CONFIG["up_color"],
            down=VISION_CHART_CONFIG["down_color"],
            edge="inherit",
            wick="inherit",
            volume={"up": "#26a69a80", "down": "#ef535080"},
        )
        style = mpf.make_mpf_style(
            marketcolors=mc,
            facecolor=VISION_CHART_CONFIG["background"],
            edgecolor="#333333",
            figcolor=VISION_CHART_CONFIG["background"],
            gridcolor="#2B2B43",
            gridstyle="-",
            y_on_right=True,
        )

        addplots = []
        if show_ema:
            ema10 = _calc_ema(df["Close"].values, 10)
            addplots.append(mpf.make_addplot(
                pd.Series(ema10, index=df.index),
                color="#ffffff", width=1.0
            ))

        buf = io.BytesIO()
        figsize = (
            VISION_CHART_CONFIG["width"] / VISION_CHART_CONFIG["dpi"],
            VISION_CHART_CONFIG["height"] / VISION_CHART_CONFIG["dpi"],
        )
        mpf.plot(
            df,
            type="candle",
            volume=VISION_CHART_CONFIG["show_volume"],
            style=style,
            title=f" {symbol}",
            figsize=figsize,
            addplot=addplots if addplots else None,
            savefig=dict(
                fname=buf,
                dpi=VISION_CHART_CONFIG["dpi"],
                bbox_inches="tight",
                facecolor=VISION_CHART_CONFIG["background"],
            ),
        )
        buf.seek(0)
        return buf.read()

    except Exception as e:
        logger.warning(f"[ChartEngine] mplfinance失败: {e}")
        return None


# ============================================================
# 统一接口 ChartEngine
# ============================================================

class ChartEngine:
    """
    统一K线截图接口，自动选择最佳引擎。

    优先 LightweightCharts（TradingView风格），
    失败自动降级 mplfinance。
    """

    def __init__(self):
        self.engine = self._detect_engine()
        logger.info(f"[ChartEngine] 使用引擎: {self.engine}")

    def _detect_engine(self) -> str:
        """检测可用引擎"""
        try:
            from lightweight_charts import Chart
            # 简单测试能否实例化
            c = Chart(width=100, height=100)
            c.exit()
            return "lightweight"
        except Exception:
            pass

        try:
            import mplfinance  # noqa
            return "mplfinance"
        except Exception:
            pass

        return "none"

    def screenshot(
        self,
        bars: list,
        symbol: str = "",
        bars_count: int = None,
        show_ema: bool = False,
    ) -> Optional[bytes]:
        """
        生成K线截图，返回 PNG bytes。

        Args:
            bars: OHLCV list，每项 {time, open, high, low, close, volume}
            symbol: 品种名（标题显示用）
            bars_count: 显示最近N根（默认 VISION_CHART_CONFIG['bars']）
            show_ema: 是否叠加 EMA10（默认False，纯形态识别）
        """
        n = bars_count or VISION_CHART_CONFIG["bars"]

        if self.engine == "lightweight":
            img = _generate_lightweight(bars, symbol, n, show_ema)
            if img:
                print(f"[ChartEngine] {symbol} LightweightCharts OK ({len(img)//1024}KB)")
                return img
            print(f"[ChartEngine] {symbol} LightweightCharts失败，降级mplfinance")

        img = _generate_mplfinance(bars, symbol, n, show_ema)
        if img:
            print(f"[ChartEngine] {symbol} mplfinance OK ({len(img)//1024}KB)")
            return img

        print(f"[ChartEngine] {symbol} 所有引擎失败")
        return None

    def screenshot_b64(
        self,
        bars: list,
        symbol: str = "",
        bars_count: int = None,
        show_ema: bool = False,
    ) -> Optional[str]:
        """返回 base64 字符串（直接传给 Vision API）"""
        img = self.screenshot(bars, symbol, bars_count, show_ema)
        if img:
            return base64.b64encode(img).decode("utf-8")
        return None


# ============================================================
# 工具函数
# ============================================================

def _bars_to_df(bars: list, bars_count: int):
    """bars list → pandas DataFrame"""
    try:
        import pandas as pd
        from datetime import datetime

        rows = []
        for b in bars[-bars_count:]:
            ts = b.get("time", 0)
            dt = datetime.fromtimestamp(ts) if isinstance(ts, (int, float)) else ts
            rows.append({
                "time":   pd.Timestamp(dt).tz_localize(None),
                "open":   float(b["open"]),
                "high":   float(b["high"]),
                "low":    float(b["low"]),
                "close":  float(b["close"]),
                "volume": float(b.get("volume", 0)),
            })

        if not rows:
            return None
        return pd.DataFrame(rows)
    except Exception as e:
        logger.warning(f"[ChartEngine] bars转换失败: {e}")
        return None


def _calc_ema(values, period: int):
    """计算EMA"""
    import numpy as np
    alpha  = 2.0 / (period + 1)
    result = np.zeros(len(values))
    result[0] = values[0]
    for i in range(1, len(values)):
        result[i] = alpha * values[i] + (1 - alpha) * result[i - 1]
    return result


# ============================================================
# A/B 测试 (需求 6.1)
# ============================================================

def test_chart_quality(bars: list, symbol: str):
    """
    A/B测试：同一段K线分别用两种引擎生成，
    喂给Vision看形态识别结果是否一致。
    """
    import os, anthropic, re, json

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not anthropic_key:
        print("需要 ANTHROPIC_API_KEY")
        return {}

    client = anthropic.Anthropic(api_key=anthropic_key)
    prompt = """这张K线图里有什么技术形态？处于Wyckoff哪个阶段？
输出JSON: {"pattern": "形态", "wyckoff_phase": "阶段", "bias": "BUY|SELL|HOLD"}"""

    results = {}

    for engine_name, gen_func in [
        ("lightweight", lambda: _generate_lightweight(bars, symbol)),
        ("mplfinance",  lambda: _generate_mplfinance(bars, symbol)),
    ]:
        img = gen_func()
        if not img:
            results[engine_name] = {"error": "截图失败"}
            continue
        img_b64 = base64.b64encode(img).decode()
        try:
            resp = client.messages.create(
                model="claude-opus-4-6", max_tokens=200,
                messages=[{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64",
                     "media_type": "image/png", "data": img_b64}},
                    {"type": "text", "text": prompt},
                ]}],
            )
            text = resp.content[0].text
            text_clean = re.sub(r'```(?:json)?\s*', '', text).strip()
            m = re.search(r'\{.*?\}', text_clean, re.DOTALL)
            results[engine_name] = json.loads(m.group()) if m else {"raw": text[:100]}
        except Exception as e:
            results[engine_name] = {"error": str(e)}

    print(f"\n=== A/B 截图质量测试: {symbol} ===")
    for eng, r in results.items():
        print(f"  {eng:15s} → bias={r.get('bias','?'):6s} "
              f"形态={r.get('pattern','?'):15s} "
              f"wyckoff={r.get('wyckoff_phase','?')}")
    same = (results.get("lightweight", {}).get("bias") ==
            results.get("mplfinance", {}).get("bias"))
    print(f"  一致: {'✓' if same else '✗'}")
    return results


# ============================================================
# 快速测试
# ============================================================

if __name__ == "__main__":
    import yfinance as yf
    from datetime import datetime, timedelta

    engine = ChartEngine()
    print(f"引擎: {engine.engine}")

    # 拉数据
    df = yf.Ticker("AMD").history(
        start=(datetime.now() - timedelta(days=150)).strftime("%Y-%m-%d"),
        end=datetime.now().strftime("%Y-%m-%d"),
        interval="1d"
    )
    bars = [
        {"time": int(ts.timestamp()), "open": float(r["Open"]),
         "high": float(r["High"]), "low": float(r["Low"]),
         "close": float(r["Close"]), "volume": float(r["Volume"])}
        for ts, r in df.iterrows()
    ]

    # 不含 EMA10（默认，纯形态）
    img = engine.screenshot(bars, symbol="AMD", show_ema=False)
    if img:
        with open("/tmp/test_no_ema.png", "wb") as f:
            f.write(img)
        print(f"无EMA截图: /tmp/test_no_ema.png ({len(img)//1024}KB)")

    # 含 EMA10（用户可选）
    img_ema = engine.screenshot(bars, symbol="AMD", show_ema=True)
    if img_ema:
        with open("/tmp/test_with_ema.png", "wb") as f:
            f.write(img_ema)
        print(f"含EMA截图: /tmp/test_with_ema.png ({len(img_ema)//1024}KB)")
