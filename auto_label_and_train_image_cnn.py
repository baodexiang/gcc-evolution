#!/usr/bin/env python3
"""
auto_label_and_train_image_cnn.py - GPT-4o自动标注 + ResNet18图像CNN训练 一体脚本

三方对比测试 C方案: 用GPT-4o标注蜡烛图 → 训练ResNet18图像分类模型

功能:
  Part A: 生成历史K线蜡烛图 + 调GPT-4o API标注UP/DOWN/SIDE + 保存标签和图片
  Part B: 使用标注数据训练ResNet18图像分类模型

用法:
  python auto_label_and_train_image_cnn.py              # 标注 + 训练
  python auto_label_and_train_image_cnn.py --label-only  # 只标注
  python auto_label_and_train_image_cnn.py --train-only  # 只训练(已有标注数据)

输出:
  labels/gpt4o_labels.json     - 标注数据
  labels/images/*.png          - 蜡烛图PNG (224×224)
  models/image_cnn_model.pt    - 训练好的ResNet18图像CNN模型
"""

import os
import sys
import json
import time
import argparse
import base64
import io
import random
from datetime import datetime
from typing import Optional, Dict, List

import numpy as np
import pandas as pd

# ============================================================================
# 配置
# ============================================================================

# 品种配置 (与vision_analyzer.py SYMBOLS_BASE_CONFIG一致)
SYMBOLS = {
    # 加密货币
    "BTCUSDC": {"yf_symbol": "BTC-USD", "type": "crypto"},
    "ETHUSDC": {"yf_symbol": "ETH-USD", "type": "crypto"},
    "SOLUSDC": {"yf_symbol": "SOL-USD", "type": "crypto"},
    "ZECUSDC": {"yf_symbol": "ZEC-USD", "type": "crypto"},
    # 美股
    "TSLA": {"yf_symbol": "TSLA", "type": "stock"},
    "AMD": {"yf_symbol": "AMD", "type": "stock"},
    "COIN": {"yf_symbol": "COIN", "type": "stock"},
}

# 周期配置 (30m, 1h, 4h)
TIMEFRAMES = {
    "30m": {"minutes": 30, "yf_interval": "30m", "yf_period": "60d", "bars_per_chart": 50},
    "1h":  {"minutes": 60, "yf_interval": "60m", "yf_period": "60d", "bars_per_chart": 50},
    "4h":  {"minutes": 240, "yf_interval": "60m", "yf_period": "60d", "bars_per_chart": 50},
}

# 滑动窗口配置
SLIDE_STEP = 10  # 窗口步长

# 图表配置
CHART_DPI = 56  # 224px / 4inch = 56 DPI

# GPT-4o标注配置
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
GPT_MODEL = "gpt-4o"
GPT_MAX_TOKENS = 150
GPT_TIMEOUT = 30

# 输出路径
LABELS_DIR = "labels"
IMAGES_DIR = os.path.join(LABELS_DIR, "images")
LABELS_FILE = os.path.join(LABELS_DIR, "gpt4o_labels.json")
MODEL_DIR = "models"
MODEL_FILE = os.path.join(MODEL_DIR, "image_cnn_model.pt")

# 训练配置
TRAIN_BATCH_SIZE = 32
TRAIN_EPOCHS = 30
TRAIN_LR = 0.001
TRAIN_VAL_SPLIT = 0.2

# GPT-4o标注提示词 (HH/HL结构化判断)
LABEL_PROMPT = """This chart shows 50 candlestick bars with green=bullish, red=bearish, plus EMA20 (yellow dashed).

Analyze the OVERALL trend direction using Higher Highs/Higher Lows (HH/HL) structure:

UP: Price forms Higher Highs and Higher Lows. Most candles close above EMA20. Clear upward slope.
DOWN: Price forms Lower Highs and Lower Lows. Most candles close below EMA20. Clear downward slope.
SIDE: No clear HH/HL or LH/LL pattern. Price oscillates around EMA20. Flat or choppy.

Respond ONLY with JSON:
{"direction": "UP", "confidence": 0.85, "reason": "clear HH/HL structure above EMA20"}"""


# ============================================================================
# Part A: 数据获取 + 蜡烛图生成 + GPT-4o标注
# ============================================================================

def fetch_ohlcv(yf_symbol: str, interval: str, period: str) -> Optional[pd.DataFrame]:
    """从yfinance获取OHLCV数据"""
    try:
        import yfinance as yf
        ticker = yf.Ticker(yf_symbol)
        df = ticker.history(interval=interval, period=period)
        if df is None or len(df) < 10:
            print(f"  [WARN] {yf_symbol} 数据不足: {len(df) if df is not None else 0}行")
            return None
        return df
    except Exception as e:
        print(f"  [ERROR] {yf_symbol} 获取数据失败: {e}")
        return None


def resample_to_4h(df_1h: pd.DataFrame) -> pd.DataFrame:
    """将1H数据聚合为4H"""
    df_resampled = df_1h.resample("4h").agg({
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum",
    }).dropna()
    return df_resampled


def generate_candlestick_chart(bars_df: pd.DataFrame) -> Optional[bytes]:
    """
    生成蜡烛图PNG (224×224, 完整K线实体+影线, 绿涨红跌, 带EMA20)
    返回PNG bytes
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    opens = bars_df['Open'].values
    highs = bars_df['High'].values
    lows = bars_df['Low'].values
    closes = bars_df['Close'].values
    n = len(bars_df)
    x = np.arange(n)

    fig, ax = plt.subplots(figsize=(4, 4))  # 4x4 inch * 56 DPI ≈ 224x224

    bar_width = 0.6
    wick_width = 0.8

    for i in range(n):
        o, h, l, c = opens[i], highs[i], lows[i], closes[i]
        color = '#26a69a' if c >= o else '#ef5350'  # 绿涨红跌

        # 影线 (上下影线)
        ax.plot([x[i], x[i]], [l, h], color=color, linewidth=wick_width,
                solid_capstyle='round')

        # 实体
        body_bottom = min(o, c)
        body_height = abs(c - o)
        if body_height < (h - l) * 0.01:
            body_height = (h - l) * 0.01  # 十字星最小实体
        ax.bar(x[i], body_height, bottom=body_bottom, width=bar_width,
               color=color, edgecolor=color, linewidth=0.3)

    # EMA20 黄色虚线
    if n >= 20:
        ema20 = pd.Series(closes).ewm(span=20, adjust=False).mean().values
        ax.plot(x, ema20, color='#FFD700', linewidth=1.2, linestyle='--', alpha=0.8)

    # 极简样式 (用于CNN训练, 无坐标轴/标题)
    ax.set_xlim(-1, n)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    plt.tight_layout(pad=0.1)

    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=CHART_DPI, bbox_inches='tight',
                facecolor='white', edgecolor='none', pad_inches=0.05)
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def call_gpt4o_label(image_bytes: bytes, max_retries: int = 3) -> Optional[Dict]:
    """调用GPT-4o Vision API进行标注 (复用vision_analyzer.py的调用模式)"""
    try:
        from openai import OpenAI
    except ImportError:
        print("[ERROR] openai未安装: pip install openai")
        return None

    if not OPENAI_API_KEY:
        print("[ERROR] OPENAI_API_KEY未配置")
        return None

    client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
    image_base64 = base64.b64encode(image_bytes).decode("utf-8")

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=GPT_MODEL,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": LABEL_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{image_base64}",
                                "detail": "low",
                            },
                        },
                    ],
                }],
                max_tokens=GPT_MAX_TOKENS,
                timeout=GPT_TIMEOUT,
            )

            text = response.choices[0].message.content.strip()
            if "{" in text and "}" in text:
                json_str = text[text.index("{"):text.rindex("}") + 1]
                result = json.loads(json_str)
                direction = result.get("direction", "SIDE").upper()
                if direction not in ("UP", "DOWN", "SIDE"):
                    direction = "SIDE"
                confidence = float(result.get("confidence", 0.5))
                reason = result.get("reason", "")
                return {"direction": direction, "confidence": confidence, "reason": reason}

            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            print(f"  [WARN] GPT-4o返回非JSON: {text[:80]}")
            return None

        except Exception as e:
            print(f"  [WARN] GPT-4o调用失败 (尝试{attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(3)
                continue
            return None

    return None


def run_labeling():
    """Part A: 自动标注流程"""
    print("=" * 60)
    print(" Part A: GPT-4o 图像标注")
    print("=" * 60)

    os.makedirs(IMAGES_DIR, exist_ok=True)

    # 加载已有标签 (支持断点续标)
    labels = []
    labeled_keys = set()
    if os.path.exists(LABELS_FILE):
        try:
            with open(LABELS_FILE, "r", encoding="utf-8") as f:
                labels = json.load(f)
            labeled_keys = {f"{l['symbol']}_{l['timeframe']}_{l['start_idx']}" for l in labels}
            print(f"  已有标注: {len(labels)}条, 续标模式")
        except Exception:
            labels = []

    total_new = 0
    total_skipped = 0
    total_failed = 0
    cost_estimate = 0.0

    for symbol, cfg in SYMBOLS.items():
        yf_symbol = cfg["yf_symbol"]
        print(f"\n--- {symbol} ({yf_symbol}) ---")

        for tf_name, tf_cfg in TIMEFRAMES.items():
            interval = tf_cfg["yf_interval"]
            period = tf_cfg["yf_period"]
            bars_per_chart = tf_cfg["bars_per_chart"]

            print(f"  周期: {tf_name}")

            # 获取数据
            df = fetch_ohlcv(yf_symbol, interval, period)
            if df is None:
                continue

            # 4H需要从1H聚合
            if tf_name == "4h":
                df = resample_to_4h(df)
                print(f"  4H聚合后: {len(df)}根")

            total_bars = len(df)
            if total_bars < bars_per_chart:
                print(f"  [SKIP] 数据不足: {total_bars} < {bars_per_chart}")
                continue

            # 滑动窗口
            windows = list(range(0, total_bars - bars_per_chart + 1, SLIDE_STEP))
            print(f"  数据: {total_bars}根, 窗口: {len(windows)}个")

            for start_idx in windows:
                key = f"{symbol}_{tf_name}_{start_idx}"
                if key in labeled_keys:
                    total_skipped += 1
                    continue

                end_idx = start_idx + bars_per_chart
                window_df = df.iloc[start_idx:end_idx].copy()

                # 生成蜡烛图
                image_bytes = generate_candlestick_chart(window_df)
                if image_bytes is None:
                    total_failed += 1
                    continue

                # 保存图片
                img_filename = f"{symbol}_{tf_name}_{start_idx:04d}.png"
                img_path = os.path.join(IMAGES_DIR, img_filename)
                with open(img_path, "wb") as f:
                    f.write(image_bytes)

                # GPT-4o标注
                result = call_gpt4o_label(image_bytes)
                if result is None:
                    total_failed += 1
                    continue

                # 记录标签
                label_entry = {
                    "symbol": symbol,
                    "timeframe": tf_name,
                    "start_idx": start_idx,
                    "end_idx": end_idx,
                    "image_file": img_filename,
                    "direction": result["direction"],
                    "confidence": result["confidence"],
                    "reason": result["reason"],
                    "timestamp": datetime.now().isoformat(),
                }
                labels.append(label_entry)
                labeled_keys.add(key)
                total_new += 1
                cost_estimate += 0.004  # ~$0.004 per low-detail image call

                # 每10条保存一次 (断点保护)
                if total_new % 10 == 0:
                    with open(LABELS_FILE, "w", encoding="utf-8") as f:
                        json.dump(labels, f, indent=2, ensure_ascii=False)
                    print(f"  进度: +{total_new}条 (跳过{total_skipped}, 失败{total_failed}) 预估${cost_estimate:.2f}")

                # API限流: 每次调用间隔0.5秒
                time.sleep(0.5)

    # 最终保存
    with open(LABELS_FILE, "w", encoding="utf-8") as f:
        json.dump(labels, f, indent=2, ensure_ascii=False)

    print(f"\n{'=' * 60}")
    print(f" 标注完成!")
    print(f"  总条数: {len(labels)}")
    print(f"  新标注: {total_new}")
    print(f"  跳过:   {total_skipped}")
    print(f"  失败:   {total_failed}")
    print(f"  预估费用: ${cost_estimate:.2f}")

    # 统计各类别分布
    dist = {"UP": 0, "DOWN": 0, "SIDE": 0}
    for l in labels:
        d = l.get("direction", "SIDE")
        dist[d] = dist.get(d, 0) + 1
    print(f"  分布: UP={dist['UP']} DOWN={dist['DOWN']} SIDE={dist['SIDE']}")
    print(f"  标签文件: {LABELS_FILE}")
    print(f"  图片目录: {IMAGES_DIR}")
    print(f"{'=' * 60}")


# ============================================================================
# Part B: ResNet18 图像CNN 训练
# ============================================================================

def run_training():
    """Part B: 训练ResNet18图像CNN"""
    print("=" * 60)
    print(" Part B: ResNet18 图像CNN 训练")
    print("=" * 60)

    import torch
    import torch.nn as nn
    import torch.optim as optim
    from torch.utils.data import Dataset, DataLoader
    from torchvision import models, transforms
    from PIL import Image

    # 检查标签文件
    if not os.path.exists(LABELS_FILE):
        print(f"[ERROR] 标签文件不存在: {LABELS_FILE}")
        print("请先运行 --label-only 或不带参数运行")
        return

    with open(LABELS_FILE, "r", encoding="utf-8") as f:
        labels = json.load(f)

    print(f"  标签总数: {len(labels)}")

    # 过滤有效数据 (图片存在 + 置信度>=0.6)
    valid_labels = []
    for l in labels:
        img_path = os.path.join(IMAGES_DIR, l["image_file"])
        if os.path.exists(img_path) and l.get("confidence", 0) >= 0.6:
            valid_labels.append(l)

    print(f"  有效数据: {len(valid_labels)} (置信度>=0.6)")

    if len(valid_labels) < 100:
        print("[ERROR] 有效数据不足100条，无法训练")
        return

    # 类别映射
    CLASS_MAP = {"UP": 0, "SIDE": 1, "DOWN": 2}
    CLASS_NAMES = ["UP", "SIDE", "DOWN"]

    # 统计分布
    dist = {c: 0 for c in CLASS_NAMES}
    for l in valid_labels:
        dist[l["direction"]] = dist.get(l["direction"], 0) + 1
    print(f"  分布: {dist}")

    # 数据增强
    train_transform = transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.RandomHorizontalFlip(p=0.3),
        transforms.ColorJitter(brightness=0.1, contrast=0.1),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ])
    val_transform = transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ])

    # Dataset
    class CandlestickImageDataset(Dataset):
        def __init__(self, data_list, transform=None):
            self.data = data_list
            self.transform = transform

        def __len__(self):
            return len(self.data)

        def __getitem__(self, idx):
            entry = self.data[idx]
            img_path = os.path.join(IMAGES_DIR, entry["image_file"])
            image = Image.open(img_path).convert("RGB")
            if self.transform:
                image = self.transform(image)
            label = CLASS_MAP[entry["direction"]]
            return image, label

    # 划分训练/验证
    random.seed(42)
    shuffled = valid_labels.copy()
    random.shuffle(shuffled)

    n_val = int(len(shuffled) * TRAIN_VAL_SPLIT)
    train_data = shuffled[n_val:]
    val_data = shuffled[:n_val]

    train_dataset = CandlestickImageDataset(train_data, train_transform)
    val_dataset = CandlestickImageDataset(val_data, val_transform)

    train_loader = DataLoader(train_dataset, batch_size=TRAIN_BATCH_SIZE, shuffle=True, num_workers=0)
    val_loader = DataLoader(val_dataset, batch_size=TRAIN_BATCH_SIZE, shuffle=False, num_workers=0)

    print(f"  训练集: {len(train_dataset)}, 验证集: {len(val_dataset)}")

    # 构建模型: ResNet18预训练 + 冻结conv1-3 + 微调conv4-5 + 新FC
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"  设备: {device}")

    model = models.resnet18(weights=models.ResNet18_Weights.IMAGENET1K_V1)

    # 冻结前3层 (conv1, bn1, layer1, layer2)
    frozen_layers = ['conv1', 'bn1', 'layer1', 'layer2']
    for name, param in model.named_parameters():
        if any(name.startswith(fl) for fl in frozen_layers):
            param.requires_grad = False

    # 替换FC层: 512 → 128 → 3 (UP/SIDE/DOWN)
    model.fc = nn.Sequential(
        nn.Linear(512, 128),
        nn.ReLU(),
        nn.Dropout(0.3),
        nn.Linear(128, 3),
    )

    model = model.to(device)

    # 类别权重 (处理不平衡)
    total_samples = sum(dist.values())
    class_weights = torch.tensor([
        total_samples / (3 * max(dist[c], 1)) for c in CLASS_NAMES
    ], dtype=torch.float32).to(device)

    criterion = nn.CrossEntropyLoss(weight=class_weights)
    optimizer = optim.Adam(filter(lambda p: p.requires_grad, model.parameters()), lr=TRAIN_LR)
    scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode='max', patience=5, factor=0.5)

    # 训练循环
    best_val_acc = 0.0
    os.makedirs(MODEL_DIR, exist_ok=True)

    print(f"\n  开始训练 ({TRAIN_EPOCHS} epochs)...")
    for epoch in range(TRAIN_EPOCHS):
        # --- Train ---
        model.train()
        train_loss = 0.0
        train_correct = 0
        train_total = 0

        for images, targets in train_loader:
            images, targets = images.to(device), targets.to(device)
            optimizer.zero_grad()
            outputs = model(images)
            loss = criterion(outputs, targets)
            loss.backward()
            optimizer.step()

            train_loss += loss.item() * images.size(0)
            _, predicted = outputs.max(1)
            train_correct += predicted.eq(targets).sum().item()
            train_total += targets.size(0)

        train_acc = train_correct / train_total if train_total > 0 else 0

        # --- Validate ---
        model.eval()
        val_correct = 0
        val_total = 0

        with torch.no_grad():
            for images, targets in val_loader:
                images, targets = images.to(device), targets.to(device)
                outputs = model(images)
                _, predicted = outputs.max(1)
                val_correct += predicted.eq(targets).sum().item()
                val_total += targets.size(0)

        val_acc = val_correct / val_total if val_total > 0 else 0
        scheduler.step(val_acc)

        # 保存最佳模型
        if val_acc > best_val_acc:
            best_val_acc = val_acc
            torch.save({
                "model_state_dict": model.state_dict(),
                "model_type": "resnet18_image_cnn",
                "class_names": CLASS_NAMES,
                "val_accuracy": val_acc,
                "epoch": epoch,
                "frozen_layers": frozen_layers,
                "input_size": 224,
                "trained_at": datetime.now().isoformat(),
            }, MODEL_FILE)

        avg_loss = train_loss / train_total if train_total > 0 else 0
        lr = optimizer.param_groups[0]['lr']
        marker = " *BEST*" if val_acc >= best_val_acc else ""
        print(f"  Epoch {epoch+1:2d}/{TRAIN_EPOCHS}: "
              f"loss={avg_loss:.4f} train_acc={train_acc:.1%} val_acc={val_acc:.1%} "
              f"lr={lr:.6f}{marker}")

    print(f"\n{'=' * 60}")
    print(f" 训练完成!")
    print(f"  最佳验证准确率: {best_val_acc:.1%}")
    print(f"  模型文件: {MODEL_FILE}")
    print(f"{'=' * 60}")


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="GPT-4o图像标注 + ResNet18训练 (三方对比测试C方案)")
    parser.add_argument("--label-only", action="store_true", help="只标注，不训练")
    parser.add_argument("--train-only", action="store_true", help="只训练(已有标注数据)")
    args = parser.parse_args()

    print(f"\n{'=' * 60}")
    print(f" auto_label_and_train_image_cnn.py")
    print(f" 三方对比测试 C方案: GPT-4o标注 → ResNet18训练")
    print(f" 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'=' * 60}")

    if args.train_only:
        run_training()
    elif args.label_only:
        run_labeling()
    else:
        run_labeling()
        print("\n" + "=" * 60)
        print(" 标注完成，开始训练...")
        print("=" * 60 + "\n")
        run_training()


if __name__ == "__main__":
    main()
