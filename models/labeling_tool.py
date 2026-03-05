"""
K线趋势标注工具 v2.950

用于人工标注K线图趋势，生成训练数据供CNN Human模型使用。

使用方法:
    python labeling_tool.py

操作说明:
    1. 程序会显示50根K线图
    2. 根据你的判断按键标注:
       - 按 1 或 U: 标注为 UP (上涨趋势)
       - 按 2 或 S: 标注为 SIDE (横盘震荡)
       - 按 3 或 D: 标注为 DOWN (下跌趋势)
    3. 其他操作:
       - 按 B: 返回上一张重新标注
       - 按 Q: 保存并退出
       - 按 ESC: 不保存退出

数据来源:
    - 自动从yfinance拉取历史数据
    - 支持股票和加密货币
    - 随机采样不同时间段

输出文件:
    - labels/training_labels.json  # 标注结果

依赖:
    pip install matplotlib yfinance numpy pandas

作者: AI Trading System
版本: v2.950
日期: 2025-12-27
"""

import os
import sys
import json
import random
import numpy as np
from datetime import datetime, timedelta

# ============================================================
# 依赖检查
# ============================================================

try:
    import matplotlib
    matplotlib.use('TkAgg')  # 使用TkAgg后端以支持键盘事件
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    print("[错误] matplotlib未安装")
    print("安装命令: pip install matplotlib")
    MATPLOTLIB_AVAILABLE = False

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    print("[警告] yfinance未安装，将使用模拟数据")
    print("安装命令: pip install yfinance")
    YFINANCE_AVAILABLE = False

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    print("[错误] pandas未安装")
    print("安装命令: pip install pandas")
    PANDAS_AVAILABLE = False


# ============================================================
# 配置
# ============================================================

CONFIG = {
    # 标注目标
    "total_samples": 200,        # 总标注数量
    "klines_per_sample": 50,     # 每个样本的K线数量
    
    # 数据源
    "symbols": {
        "stocks": ["TSLA", "AMD", "NVDA", "AAPL", "MSFT"],
        "crypto": ["BTC-USD", "ETH-USD", "SOL-USD"],
    },
    "intervals": ["30m", "1h"],  # K线周期
    
    # 采样配置
    "samples_per_symbol": 25,    # 每个品种采样数量
    "lookback_days": 180,        # 历史数据回溯天数
    
    # 输出
    "output_dir": "labels",
    "output_file": "training_labels.json",
    
    # 显示
    "figure_size": (14, 8),
    "candle_width": 0.6,
}

# 标签定义
LABELS = {
    "UP": 0,
    "SIDE": 1,
    "DOWN": 2,
}

LABEL_NAMES = {0: "UP", 1: "SIDE", 2: "DOWN"}
LABEL_COLORS = {"UP": "green", "SIDE": "gray", "DOWN": "red"}


# ============================================================
# 数据获取
# ============================================================

def fetch_historical_data(symbol: str, interval: str, days: int = 180) -> list:
    """
    从yfinance获取历史K线数据
    
    Args:
        symbol: 股票或加密货币代码
        interval: K线周期 ("30m", "1h", "1d")
        days: 回溯天数
    
    Returns:
        K线数据列表
    """
    if not YFINANCE_AVAILABLE:
        return generate_mock_data(500)
    
    try:
        ticker = yf.Ticker(symbol)
        
        # yfinance对于分钟数据有限制，最多60天
        if interval in ["30m", "1h"]:
            actual_days = min(days, 59)
        else:
            actual_days = days
        
        end_date = datetime.now()
        start_date = end_date - timedelta(days=actual_days)
        
        df = ticker.history(start=start_date, end=end_date, interval=interval)
        
        if df.empty:
            print(f"[警告] {symbol} 无数据，使用模拟数据")
            return generate_mock_data(500)
        
        # 转换为列表格式
        klines = []
        for idx, row in df.iterrows():
            klines.append({
                "timestamp": idx.timestamp(),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": float(row["Volume"]),
            })
        
        return klines
        
    except Exception as e:
        print(f"[错误] 获取{symbol}数据失败: {e}")
        return generate_mock_data(500)


def generate_mock_data(length: int = 500) -> list:
    """
    生成模拟K线数据 (用于测试)
    """
    klines = []
    price = 100.0
    
    for i in range(length):
        # 随机波动
        change = random.gauss(0, 0.02)  # 2%标准差
        
        open_price = price
        close_price = price * (1 + change)
        high_price = max(open_price, close_price) * (1 + abs(random.gauss(0, 0.005)))
        low_price = min(open_price, close_price) * (1 - abs(random.gauss(0, 0.005)))
        volume = random.uniform(500000, 2000000)
        
        klines.append({
            "timestamp": i * 1800,  # 30分钟间隔
            "open": open_price,
            "high": high_price,
            "low": low_price,
            "close": close_price,
            "volume": volume,
        })
        
        price = close_price
    
    return klines


def sample_klines(all_klines: list, num_klines: int = 50) -> tuple:
    """
    从历史数据中随机采样一段K线
    
    Returns:
        (klines_list, start_index)
    """
    if len(all_klines) < num_klines + 10:
        return all_klines[:num_klines], 0
    
    # 随机选择起始位置
    max_start = len(all_klines) - num_klines
    start_idx = random.randint(0, max_start)
    
    return all_klines[start_idx:start_idx + num_klines], start_idx


# ============================================================
# K线图绘制
# ============================================================

def draw_candlestick_chart(ax, klines: list, title: str = ""):
    """
    绘制K线图
    """
    ax.clear()
    
    n = len(klines)
    width = CONFIG["candle_width"]
    
    for i, bar in enumerate(klines):
        o = bar["open"]
        h = bar["high"]
        l = bar["low"]
        c = bar["close"]
        
        # 颜色
        if c >= o:
            color = "green"
            body_bottom = o
            body_height = c - o
        else:
            color = "red"
            body_bottom = c
            body_height = o - c
        
        # 绘制影线
        ax.plot([i, i], [l, h], color=color, linewidth=1)
        
        # 绘制实体
        if body_height > 0:
            rect = Rectangle(
                (i - width/2, body_bottom),
                width, body_height,
                facecolor=color, edgecolor=color
            )
            ax.add_patch(rect)
        else:
            # 十字星
            ax.plot([i - width/2, i + width/2], [o, o], color=color, linewidth=2)
    
    ax.set_xlim(-1, n)
    ax.set_title(title, fontsize=14, fontweight='bold')
    ax.set_xlabel("K线序号")
    ax.set_ylabel("价格")
    ax.grid(True, alpha=0.3)


# ============================================================
# 标注工具主类
# ============================================================

class LabelingTool:
    """
    K线标注工具
    """
    
    def __init__(self):
        self.samples = []           # 待标注样本列表
        self.labels = []            # 已标注结果
        self.current_idx = 0        # 当前样本索引
        self.fig = None
        self.ax = None
        self.running = True
        self.saved = False
        
        # 加载已有标注
        self.load_existing_labels()
    
    def load_existing_labels(self):
        """加载已有的标注文件"""
        output_path = os.path.join(CONFIG["output_dir"], CONFIG["output_file"])
        if os.path.exists(output_path):
            try:
                with open(output_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.labels = data.get("samples", [])
                    print(f"[信息] 加载已有标注: {len(self.labels)} 个样本")
            except:
                self.labels = []
    
    def prepare_samples(self):
        """
        准备待标注的样本
        """
        print("\n" + "=" * 60)
        print("准备标注样本...")
        print("=" * 60)
        
        self.samples = []
        
        # 合并所有品种
        all_symbols = CONFIG["symbols"]["stocks"] + CONFIG["symbols"]["crypto"]
        
        for symbol in all_symbols:
            print(f"\n获取 {symbol} 数据...")
            
            for interval in CONFIG["intervals"]:
                # 获取历史数据
                all_klines = fetch_historical_data(
                    symbol, interval, CONFIG["lookback_days"]
                )
                
                if len(all_klines) < CONFIG["klines_per_sample"]:
                    print(f"  {interval}: 数据不足，跳过")
                    continue
                
                # 采样多个片段
                samples_needed = CONFIG["samples_per_symbol"] // len(CONFIG["intervals"])
                
                for _ in range(samples_needed):
                    klines, start_idx = sample_klines(
                        all_klines, CONFIG["klines_per_sample"]
                    )
                    
                    self.samples.append({
                        "symbol": symbol,
                        "interval": interval,
                        "start_idx": start_idx,
                        "klines": klines,
                    })
        
        # 打乱顺序
        random.shuffle(self.samples)
        
        # 限制总数
        if len(self.samples) > CONFIG["total_samples"]:
            self.samples = self.samples[:CONFIG["total_samples"]]
        
        print(f"\n准备完成: {len(self.samples)} 个样本待标注")
        print(f"已有标注: {len(self.labels)} 个")
        print(f"剩余需标注: {max(0, CONFIG['total_samples'] - len(self.labels))} 个")
    
    def on_key_press(self, event):
        """
        键盘事件处理
        """
        key = event.key.lower() if event.key else ""
        
        if key in ['1', 'u']:
            self.record_label("UP")
        elif key in ['2', 's']:
            self.record_label("SIDE")
        elif key in ['3', 'd']:
            self.record_label("DOWN")
        elif key == 'b':
            self.go_back()
        elif key == 'q':
            self.save_and_exit()
        elif key == 'escape':
            self.exit_without_save()
    
    def record_label(self, label: str):
        """记录标注"""
        if self.current_idx >= len(self.samples):
            return
        
        sample = self.samples[self.current_idx]
        
        # 创建标注记录
        record = {
            "id": len(self.labels),
            "symbol": sample["symbol"],
            "interval": sample["interval"],
            "label": label,
            "label_idx": LABELS[label],
            "klines": sample["klines"],
            "timestamp": datetime.now().isoformat(),
        }
        
        self.labels.append(record)
        
        print(f"  标注: {label} ({self.current_idx + 1}/{len(self.samples)})")
        
        # 下一个
        self.current_idx += 1
        self.show_next_sample()
    
    def go_back(self):
        """返回上一张"""
        if self.current_idx > 0 and len(self.labels) > 0:
            self.labels.pop()
            self.current_idx -= 1
            print(f"  返回上一张 ({self.current_idx + 1}/{len(self.samples)})")
            self.show_next_sample()
    
    def save_and_exit(self):
        """保存并退出"""
        self.save_labels()
        self.running = False
        plt.close(self.fig)
    
    def exit_without_save(self):
        """不保存退出"""
        print("\n[警告] 未保存退出")
        self.running = False
        plt.close(self.fig)
    
    def save_labels(self):
        """保存标注结果"""
        os.makedirs(CONFIG["output_dir"], exist_ok=True)
        output_path = os.path.join(CONFIG["output_dir"], CONFIG["output_file"])
        
        data = {
            "version": "v2.950",
            "created": datetime.now().isoformat(),
            "total_samples": len(self.labels),
            "label_distribution": {
                "UP": sum(1 for l in self.labels if l["label"] == "UP"),
                "SIDE": sum(1 for l in self.labels if l["label"] == "SIDE"),
                "DOWN": sum(1 for l in self.labels if l["label"] == "DOWN"),
            },
            "samples": self.labels,
        }
        
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print(f"\n[保存] 标注结果已保存: {output_path}")
        print(f"       总样本数: {len(self.labels)}")
        print(f"       UP: {data['label_distribution']['UP']}")
        print(f"       SIDE: {data['label_distribution']['SIDE']}")
        print(f"       DOWN: {data['label_distribution']['DOWN']}")
        self.saved = True
    
    def show_next_sample(self):
        """显示下一个样本"""
        if self.current_idx >= len(self.samples):
            print("\n" + "=" * 60)
            print("标注完成！")
            print("=" * 60)
            self.save_and_exit()
            return
        
        sample = self.samples[self.current_idx]
        
        # 更新标题
        title = (
            f"样本 {self.current_idx + 1}/{len(self.samples)} | "
            f"{sample['symbol']} {sample['interval']} | "
            f"已标注: {len(self.labels)}"
        )
        
        # 绘制K线图
        draw_candlestick_chart(self.ax, sample["klines"], title)
        
        # 添加操作提示
        hint = (
            "[1/U] UP上涨  [2/S] SIDE横盘  [3/D] DOWN下跌  "
            "[B] 返回  [Q] 保存退出"
        )
        self.ax.text(
            0.5, -0.12, hint,
            transform=self.ax.transAxes,
            ha='center', va='top',
            fontsize=11,
            bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5)
        )
        
        self.fig.canvas.draw()
    
    def run(self):
        """
        运行标注工具
        """
        if not MATPLOTLIB_AVAILABLE or not PANDAS_AVAILABLE:
            print("[错误] 缺少必要依赖，无法运行")
            return
        
        # 准备样本
        self.prepare_samples()
        
        if not self.samples:
            print("[错误] 无可用样本")
            return
        
        # 跳过已标注的
        self.current_idx = len(self.labels)
        if self.current_idx >= len(self.samples):
            print("\n[信息] 所有样本已标注完成！")
            return
        
        print("\n" + "=" * 60)
        print("开始标注")
        print("=" * 60)
        print("\n操作说明:")
        print("  [1] 或 [U]: 标注为 UP (上涨趋势)")
        print("  [2] 或 [S]: 标注为 SIDE (横盘震荡)")
        print("  [3] 或 [D]: 标注为 DOWN (下跌趋势)")
        print("  [B]: 返回上一张重新标注")
        print("  [Q]: 保存并退出")
        print("  [ESC]: 不保存退出")
        print("\n请根据K线图的整体趋势进行判断...")
        
        # 创建图形
        self.fig, self.ax = plt.subplots(figsize=CONFIG["figure_size"])
        self.fig.canvas.mpl_connect('key_press_event', self.on_key_press)
        
        # 显示第一个样本
        self.show_next_sample()
        
        # 显示窗口
        plt.tight_layout()
        plt.show()
        
        # 退出时自动保存
        if not self.saved and len(self.labels) > 0:
            self.save_labels()


# ============================================================
# 主函数
# ============================================================

def main():
    print("=" * 60)
    print("K线趋势标注工具 v2.950")
    print("=" * 60)
    print(f"\n目标: 标注 {CONFIG['total_samples']} 个样本")
    print(f"每个样本: {CONFIG['klines_per_sample']} 根K线")
    print(f"品种: {CONFIG['symbols']['stocks'] + CONFIG['symbols']['crypto']}")
    print(f"周期: {CONFIG['intervals']}")
    
    tool = LabelingTool()
    tool.run()
    
    print("\n" + "=" * 60)
    print("标注工具已退出")
    print("=" * 60)


if __name__ == "__main__":
    main()
