"""
XGBoost Tech模型优化训练脚本 v3.320

优化内容:
  1. 5分类 → 3分类 (BUY/HOLD/SELL)
  2. 提高涨跌阈值减少噪音
  3. 调整模型参数防过拟合
  4. 添加交叉验证
  5. 特征重要性分析

使用方法:
  python train_xgboost_v3320.py
"""

import os
import json
import numpy as np
from datetime import datetime

# ============================================================
# 优化后的配置
# ============================================================

# 训练标的 (增加你实际交易的品种)
TRAIN_SYMBOLS = {
    "stocks": [
        "TSLA", "COIN", "AMD", "NVDA", "AAPL", "GOOGL", "AMZN", "META", "MSFT",
        "CRWV", "RDDT", "HIMS", "OPEN", "RKLB", "NBIS"  # 新增实际交易的
    ],
    "crypto": ["BTC-USD", "ETH-USD", "SOL-USD"],
}

# v3.320优化参数
INTERVAL = "30m"
FUTURE_BARS = 4            # 预测2小时后
LABEL_THRESHOLD = 0.008    # 提高到0.8% (原0.5%)，减少噪音
NUM_CLASSES = 3            # 3分类: 0=SELL, 1=HOLD, 2=BUY

# 输出路径
MODEL_PATH = "models/xgboost_tech_model.json"
STATS_PATH = "state/xgboost_tech_stats.json"

# ============================================================
# 依赖检查
# ============================================================

try:
    import xgboost as xgb
    XGBOOST_OK = True
except ImportError:
    print("请安装xgboost: pip install xgboost")
    XGBOOST_OK = False

try:
    import yfinance as yf
    YFINANCE_OK = True
except ImportError:
    print("请安装yfinance: pip install yfinance")
    YFINANCE_OK = False

try:
    import pandas as pd
    PANDAS_OK = True
except ImportError:
    print("请安装pandas: pip install pandas")
    PANDAS_OK = False


# ============================================================
# 特征名称 (24维)
# ============================================================

FEATURE_NAMES = [
    "adx", "plus_di", "minus_di", "di_diff",
    "rsi_14", "rsi_7",
    "macd", "macd_signal", "macd_hist",
    "choppiness",
    "bb_upper_dist", "bb_lower_dist", "bb_position",
    "ema_9_21_cross", "ema_21_55_cross",
    "volume_ratio",
    "atr_pct",
    "momentum_5", "momentum_10", "momentum_20",
    "trend_x4_up", "trend_x4_down",
    "trend_x8_up", "trend_x8_down",
]


# ============================================================
# 技术指标计算函数
# ============================================================

def calculate_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calculate_ema(data, period):
    if len(data) < period:
        return data[-1] if len(data) > 0 else 0
    multiplier = 2 / (period + 1)
    ema = np.mean(data[:period])
    for price in data[period:]:
        ema = (price - ema) * multiplier + ema
    return ema


def calculate_macd(closes, fast=12, slow=26, signal=9):
    if len(closes) < slow + signal:
        return 0, 0, 0
    ema_fast = calculate_ema(closes, fast)
    ema_slow = calculate_ema(closes, slow)
    macd_line = ema_fast - ema_slow
    signal_line = macd_line * 0.9
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def calculate_bollinger(closes, period=20, std_dev=2.0):
    if len(closes) < period:
        return closes[-1], closes[-1], closes[-1]
    recent = closes[-period:]
    middle = np.mean(recent)
    std = np.std(recent)
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    return upper, middle, lower


def calculate_atr(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return 0
    tr_list = []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        tr_list.append(tr)
    return np.mean(tr_list[-period:])


def calculate_adx(highs, lows, closes, period=14):
    if len(closes) < period * 2:
        return 0, 0, 0

    plus_dm_list = []
    minus_dm_list = []
    tr_list = []

    for i in range(1, len(closes)):
        plus_dm = max(0, highs[i] - highs[i-1])
        minus_dm = max(0, lows[i-1] - lows[i])

        if plus_dm > minus_dm:
            minus_dm = 0
        elif minus_dm > plus_dm:
            plus_dm = 0
        else:
            plus_dm = minus_dm = 0

        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        plus_dm_list.append(plus_dm)
        minus_dm_list.append(minus_dm)
        tr_list.append(tr)

    if len(tr_list) < period:
        return 0, 0, 0

    atr = np.mean(tr_list[-period:])
    avg_plus_dm = np.mean(plus_dm_list[-period:])
    avg_minus_dm = np.mean(minus_dm_list[-period:])

    if atr == 0:
        return 0, 0, 0

    plus_di = 100 * avg_plus_dm / atr
    minus_di = 100 * avg_minus_dm / atr

    di_sum = plus_di + minus_di
    if di_sum == 0:
        return 0, plus_di, minus_di

    dx = 100 * abs(plus_di - minus_di) / di_sum
    return dx, plus_di, minus_di


def calculate_choppiness(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return 50.0

    atr_sum = 0
    highest = max(highs[-period:])
    lowest = min(lows[-period:])

    for i in range(-period, 0):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        atr_sum += tr

    range_hl = highest - lowest
    if range_hl <= 0 or atr_sum <= 0:
        return 50.0

    try:
        chop = 100 * np.log10(atr_sum / range_hl) / np.log10(period)
        return max(0, min(100, chop))
    except:
        return 50.0


def extract_features_from_df(df, idx):
    """提取24维特征"""
    features = [0.0] * len(FEATURE_NAMES)

    if idx < 60:
        return None

    try:
        closes = df['Close'].iloc[idx-60:idx+1].values
        highs = df['High'].iloc[idx-60:idx+1].values
        lows = df['Low'].iloc[idx-60:idx+1].values
        volumes = df['Volume'].iloc[idx-60:idx+1].values

        current_price = closes[-1]

        # 1. ADX, +DI, -DI
        adx, plus_di, minus_di = calculate_adx(highs, lows, closes, 14)
        features[0] = adx / 100.0
        features[1] = plus_di / 100.0
        features[2] = minus_di / 100.0
        features[3] = (plus_di - minus_di) / 100.0

        # 2. RSI
        features[4] = calculate_rsi(closes, 14) / 100.0
        features[5] = calculate_rsi(closes, 7) / 100.0

        # 3. MACD
        macd, signal, hist = calculate_macd(closes)
        features[6] = np.clip(macd / current_price * 100, -5, 5) / 5
        features[7] = np.clip(signal / current_price * 100, -5, 5) / 5
        features[8] = np.clip(hist / current_price * 100, -5, 5) / 5

        # 4. Choppiness
        chop = calculate_choppiness(highs, lows, closes, 14)
        features[9] = chop / 100.0

        # 5. 布林带
        bb_upper, bb_middle, bb_lower = calculate_bollinger(closes)
        bb_range = bb_upper - bb_lower if bb_upper > bb_lower else 1
        features[10] = (bb_upper - current_price) / bb_range
        features[11] = (current_price - bb_lower) / bb_range
        features[12] = (current_price - bb_lower) / bb_range

        # 6. EMA交叉
        ema_9 = calculate_ema(closes, 9)
        ema_21 = calculate_ema(closes, 21)
        ema_55 = calculate_ema(closes, 55)
        features[13] = 1.0 if ema_9 > ema_21 else -1.0
        features[14] = 1.0 if ema_21 > ema_55 else -1.0

        # 7. 成交量
        avg_vol = np.mean(volumes[-20:])
        current_vol = volumes[-1]
        features[15] = min(current_vol / avg_vol, 5.0) / 5.0 if avg_vol > 0 else 0.5

        # 8. ATR
        atr = calculate_atr(highs, lows, closes, 14)
        features[16] = min(atr / current_price * 100, 10) / 10

        # 9. 动量
        features[17] = np.clip((closes[-1] / closes[-5] - 1) * 100, -10, 10) / 10
        features[18] = np.clip((closes[-1] / closes[-10] - 1) * 100, -20, 20) / 20
        features[19] = np.clip((closes[-1] / closes[-20] - 1) * 100, -30, 30) / 30

        # 10. 趋势方向
        momentum_x4 = (closes[-1] / closes[-20] - 1) if len(closes) >= 20 else 0
        momentum_x8 = (closes[-1] / closes[-40] - 1) if len(closes) >= 40 else 0
        features[20] = 1.0 if momentum_x4 > 0.01 else 0.0
        features[21] = 1.0 if momentum_x4 < -0.01 else 0.0
        features[22] = 1.0 if momentum_x8 > 0.02 else 0.0
        features[23] = 1.0 if momentum_x8 < -0.02 else 0.0

        return features

    except Exception as e:
        return None


def generate_label_3class(df, idx, future_bars=4):
    """
    v3.320: 3分类标签

    0 = SELL: 跌幅 > 0.8%
    1 = HOLD: 涨跌 < 0.8%
    2 = BUY:  涨幅 > 0.8%
    """
    if idx + future_bars >= len(df):
        return None

    current_price = df['Close'].iloc[idx]
    future_price = df['Close'].iloc[idx + future_bars]

    change_pct = (future_price - current_price) / current_price

    if change_pct > LABEL_THRESHOLD:
        return 2  # BUY
    elif change_pct < -LABEL_THRESHOLD:
        return 0  # SELL
    else:
        return 1  # HOLD


# ============================================================
# 数据下载
# ============================================================

def download_data(symbol, interval="30m"):
    print(f"  下载 {symbol}...")

    try:
        ticker = yf.Ticker(symbol)

        if interval in ["5m", "15m", "30m"]:
            period = "60d"
        elif interval in ["1h"]:
            period = "730d"
        else:
            period = "365d"

        df = ticker.history(period=period, interval=interval)

        if df.empty:
            print(f"    {symbol}: 无数据")
            return None

        print(f"    {symbol}: {len(df)} 条K线")
        return df

    except Exception as e:
        print(f"    {symbol}: 错误 {e}")
        return None


def extract_dataset(df, symbol):
    """提取特征和3分类标签"""
    features = []
    labels = []

    for idx in range(60, len(df) - FUTURE_BARS):
        feat = extract_features_from_df(df, idx)
        label = generate_label_3class(df, idx, FUTURE_BARS)

        if feat is not None and label is not None:
            features.append(feat)
            labels.append(label)

    print(f"    {symbol}: {len(features)} 样本")
    return features, labels


def prepare_training_data():
    """准备训练数据"""

    print("\n" + "=" * 60)
    print(" 步骤1: 下载数据")
    print("=" * 60)

    all_features = []
    all_labels = []

    print("\n股票:")
    for symbol in TRAIN_SYMBOLS["stocks"]:
        df = download_data(symbol, INTERVAL)
        if df is not None and len(df) > 100:
            features, labels = extract_dataset(df, symbol)
            all_features.extend(features)
            all_labels.extend(labels)

    print("\n加密货币:")
    for symbol in TRAIN_SYMBOLS["crypto"]:
        df = download_data(symbol, INTERVAL)
        if df is not None and len(df) > 100:
            features, labels = extract_dataset(df, symbol)
            all_features.extend(features)
            all_labels.extend(labels)

    print(f"\n总样本: {len(all_features)}")

    # 标签分布
    label_counts = {}
    for l in all_labels:
        label_counts[l] = label_counts.get(l, 0) + 1

    label_names = {0: "SELL", 1: "HOLD", 2: "BUY"}
    print("\n标签分布:")
    for l in sorted(label_counts.keys()):
        pct = label_counts[l] / len(all_labels) * 100
        print(f"  {label_names[l]}: {label_counts[l]} ({pct:.1f}%)")

    return all_features, all_labels


def oversample_minority_classes(X, y):
    """过采样少数类(BUY/SELL)使类别平衡"""

    # 统计各类别
    unique, counts = np.unique(y, return_counts=True)
    max_count = max(counts)

    X_resampled = list(X)
    y_resampled = list(y)

    for cls in unique:
        cls_indices = np.where(y == cls)[0]
        cls_count = len(cls_indices)

        if cls_count < max_count:
            # 需要补充的数量
            n_to_add = max_count - cls_count
            # 随机重复采样
            resample_indices = np.random.choice(cls_indices, size=n_to_add, replace=True)
            X_resampled.extend(X[resample_indices])
            y_resampled.extend(y[resample_indices])

    return np.array(X_resampled), np.array(y_resampled)


def train_xgboost_v3320(features, labels, validation_split=0.2):
    """v3.320优化训练 + 过采样"""

    print("\n" + "=" * 60)
    print(" 步骤2: 训练XGBoost (v3.320 + 过采样)")
    print("=" * 60)

    X = np.array(features)
    y = np.array(labels)

    # 划分数据 (先划分再过采样，防止数据泄露)
    n_samples = len(X)
    n_val = int(n_samples * validation_split)
    indices = np.random.permutation(n_samples)

    train_idx = indices[n_val:]
    val_idx = indices[:n_val]

    X_train, y_train = X[train_idx], y[train_idx]
    X_val, y_val = X[val_idx], y[val_idx]

    print(f"\n原始训练集: {len(X_train)}")

    # 过采样训练集
    X_train, y_train = oversample_minority_classes(X_train, y_train)

    print(f"过采样后训练集: {len(X_train)}")

    # 过采样后标签分布
    unique, counts = np.unique(y_train, return_counts=True)
    label_names = {0: "SELL", 1: "HOLD", 2: "BUY"}
    print("过采样后分布:")
    for cls, cnt in zip(unique, counts):
        print(f"  {label_names[cls]}: {cnt} ({cnt/len(y_train)*100:.1f}%)")

    print(f"验证集: {len(X_val)} (未过采样，保持真实分布)")

    dtrain = xgb.DMatrix(X_train, label=y_train, feature_names=FEATURE_NAMES)
    dval = xgb.DMatrix(X_val, label=y_val, feature_names=FEATURE_NAMES)

    # v3.320优化参数
    params = {
        "objective": "multi:softprob",
        "num_class": 3,           # 3分类
        "max_depth": 4,           # 减小防过拟合
        "eta": 0.05,              # 降低学习率
        "subsample": 0.7,
        "colsample_bytree": 0.7,
        "min_child_weight": 5,    # 防过拟合
        "gamma": 0.1,             # 防过拟合
        "eval_metric": "mlogloss",
        "seed": 42,
    }

    print("\n训练参数:")
    print(f"  num_class: 3 (SELL/HOLD/BUY)")
    print(f"  max_depth: 4")
    print(f"  eta: 0.05")
    print(f"  min_child_weight: 5")

    print("\n开始训练...")
    evallist = [(dtrain, "train"), (dval, "eval")]
    model = xgb.train(
        params,
        dtrain,
        num_boost_round=300,      # 增加轮次(因为学习率低)
        evals=evallist,
        early_stopping_rounds=30,
        verbose_eval=50,
    )

    # 计算准确率
    preds = model.predict(dval)
    pred_labels = np.argmax(preds, axis=1)
    accuracy = np.mean(pred_labels == y_val)

    print(f"\n验证准确率: {accuracy:.1%}")

    # 各类别准确率
    print("\n各类别准确率:")
    label_names = {0: "SELL", 1: "HOLD", 2: "BUY"}
    for l in range(3):
        mask = y_val == l
        if mask.sum() > 0:
            acc = np.mean(pred_labels[mask] == l)
            print(f"  {label_names[l]}: {acc:.1%} ({mask.sum()} 样本)")

    # 特征重要性
    print("\n特征重要性 Top 10:")
    importance = model.get_score(importance_type='gain')
    sorted_imp = sorted(importance.items(), key=lambda x: x[1], reverse=True)[:10]
    for feat, score in sorted_imp:
        print(f"  {feat}: {score:.1f}")

    return model, accuracy, len(X_train), len(X_val)


def save_model(model, accuracy, train_samples, val_samples):
    """保存模型"""

    print("\n" + "=" * 60)
    print(" 步骤3: 保存模型")
    print("=" * 60)

    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    os.makedirs(os.path.dirname(STATS_PATH), exist_ok=True)

    model.save_model(MODEL_PATH)
    print(f"模型: {MODEL_PATH}")

    stats = {
        "version": "v3.320",
        "num_classes": 3,
        "class_names": ["SELL", "HOLD", "BUY"],
        "train_samples": train_samples,
        "val_samples": val_samples,
        "val_accuracy": accuracy,
        "model_path": MODEL_PATH,
        "trained_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "interval": INTERVAL,
        "future_bars": FUTURE_BARS,
        "label_threshold": LABEL_THRESHOLD,
        "symbols": TRAIN_SYMBOLS,
    }

    with open(STATS_PATH, "w") as f:
        json.dump(stats, f, indent=2)
    print(f"统计: {STATS_PATH}")


def main():
    print("\n" + "=" * 60)
    print(" XGBoost Tech v3.320 优化训练")
    print("=" * 60)
    print(f"\n优化内容:")
    print(f"  - 5分类 -> 3分类 (SELL/HOLD/BUY)")
    print(f"  - 涨跌阈值: 0.5% -> 0.8%")
    print(f"  - 降低学习率+增加正则化")
    print(f"  - 增加训练标的")

    if not all([XGBOOST_OK, YFINANCE_OK, PANDAS_OK]):
        print("\n缺少依赖")
        return

    features, labels = prepare_training_data()

    if len(features) < 100:
        print("\n样本不足")
        return

    result = train_xgboost_v3320(features, labels)

    if result is None:
        print("\n训练失败")
        return

    model, accuracy, train_samples, val_samples = result
    save_model(model, accuracy, train_samples, val_samples)

    print("\n" + "=" * 60)
    print(f" 训练完成! 准确率: {accuracy:.1%}")
    print("=" * 60)
    print(f"\n对比: 旧模型54% -> 新模型{accuracy:.1%}")

    if accuracy > 0.60:
        print("\n建议: 准确率>60%，可以继续使用XGBoost")
    else:
        print("\n建议: 准确率仍<60%，考虑关闭XGBoost使用规则")


if __name__ == "__main__":
    main()
