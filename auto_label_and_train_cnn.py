"""
自动标注 + CNN训练脚本 v2.960

自动从历史K线数据生成标注样本并训练CNN模型。
无需人工标注，根据后续价格走势自动判断标签。

使用方法:
    python auto_label_and_train_cnn.py

原理:
    - 取50根K线作为输入
    - 看后续10根K线的涨跌幅作为标签
    - 涨 > 1.5% → UP
    - 跌 > 1.5% → DOWN
    - 其他 → SIDE

作者: AI Trading System
版本: v2.960
日期: 2025-12-27
"""

import os
import sys
import json
import random
import numpy as np
from datetime import datetime, timedelta

# ============================================================
# 配置 - 可以修改这里增加样本量
# ============================================================

CONFIG = {
    # 数据源 - 与实际交易品种一致
    "symbols": {
        # 加密货币 (Coinbase 4个)
        "crypto": [
            "BTC-USD", "ETH-USD", "SOL-USD", "ZEC-USD",
        ],
        # 美股 (实际交易品种)
        "stocks": [
            # 主力交易
            "TSLA", "COIN", "RDDT", "NBIS", "CRWV", "RKLB", "HIMS", "OPEN", "AMD", "ONDS",
            # ETF
            "SQQQ", "TQQQ", "ETHA",
            # 科技股
            "SOFI", "IONQ", "PLTR", "GOOGL", "NVDA", "AVGO",
            # 其他
            "BMNR", "NVDS", "AVAV",
        ],
    },
    
    # K线周期 (多周期采样增加样本)
    "intervals": ["15m", "30m", "1h"],
    
    # 采样配置
    "lookback_days": 59,          # yfinance分钟数据最多60天
    "klines_per_sample": 50,      # 输入K线数量
    "future_klines": 5,           # 用于判断标签的未来K线数 (10→5, 更短更准)
    "samples_per_symbol": 500,    # 每个品种每个周期的采样数 (100→500, 5倍样本)
    
    # 标签阈值 (降低阈值，生成更多UP/DOWN标签)
    "up_threshold": 0.01,         # 涨幅 > 1.0% → UP (1.5%→1.0%)
    "down_threshold": -0.01,      # 跌幅 > 1.0% → DOWN (-1.5%→-1.0%)
    
    # 训练配置
    "val_split": 0.2,
    "batch_size": 32,
    "epochs": 100,
    "learning_rate": 0.001,
    "early_stopping_patience": 15,
    
    # 输出
    "labels_dir": "labels",
    "labels_file": "auto_training_labels.json",
    "model_dir": "models",
    "model_file": "cnn_human_model.pt",
    "stats_dir": "state",
    "stats_file": "cnn_human_stats.json",
}

# ============================================================
# 依赖检查
# ============================================================

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    print("[错误] yfinance未安装")
    print("安装命令: pip install yfinance")
    sys.exit(1)

try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    from torch.utils.data import Dataset, DataLoader
    TORCH_AVAILABLE = True
except ImportError:
    print("[错误] PyTorch未安装")
    print("安装命令: pip install torch")
    sys.exit(1)

# ============================================================
# 数据获取
# ============================================================

def fetch_klines(symbol: str, interval: str, days: int = 59) -> list:
    """从yfinance获取历史K线"""
    try:
        print(f"  获取 {symbol} {interval}...", end=" ")
        
        ticker = yf.Ticker(symbol)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        df = ticker.history(start=start_date, end=end_date, interval=interval)
        
        if df.empty:
            print("无数据")
            return []
        
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
        
        print(f"{len(klines)} 根K线")
        return klines
        
    except Exception as e:
        print(f"错误: {e}")
        return []


# ============================================================
# 自动标注
# ============================================================

def auto_label_samples(all_symbols: list, intervals: list) -> list:
    """自动生成标注样本"""
    
    samples = []
    input_len = CONFIG["klines_per_sample"]
    future_len = CONFIG["future_klines"]
    samples_per = CONFIG["samples_per_symbol"]
    
    up_thresh = CONFIG["up_threshold"]
    down_thresh = CONFIG["down_threshold"]
    
    print("\n" + "=" * 60)
    print("Step 1: 自动标注样本")
    print("=" * 60)
    
    for symbol in all_symbols:
        for interval in intervals:
            klines = fetch_klines(symbol, interval, CONFIG["lookback_days"])
            
            if len(klines) < input_len + future_len + 10:
                continue
            
            # 随机采样
            max_start = len(klines) - input_len - future_len
            if max_start <= 0:
                continue
            
            sampled = 0
            attempts = 0
            max_attempts = samples_per * 3
            
            while sampled < samples_per and attempts < max_attempts:
                attempts += 1
                
                # 随机起点
                start_idx = random.randint(0, max_start)
                
                # 输入K线
                input_klines = klines[start_idx:start_idx + input_len]
                
                # 未来K线 (用于判断标签)
                future_klines = klines[start_idx + input_len:start_idx + input_len + future_len]
                
                if len(input_klines) < input_len or len(future_klines) < future_len:
                    continue
                
                # 计算未来涨跌幅
                current_close = input_klines[-1]["close"]
                future_close = future_klines[-1]["close"]
                
                if current_close <= 0:
                    continue
                
                change_pct = (future_close - current_close) / current_close
                
                # 自动标签
                if change_pct > up_thresh:
                    label = "UP"
                    label_idx = 0
                elif change_pct < down_thresh:
                    label = "DOWN"
                    label_idx = 2
                else:
                    label = "SIDE"
                    label_idx = 1
                
                samples.append({
                    "id": len(samples),
                    "symbol": symbol,
                    "interval": interval,
                    "label": label,
                    "label_idx": label_idx,
                    "change_pct": round(change_pct * 100, 2),
                    "klines": input_klines,
                })
                
                sampled += 1
    
    # 打乱
    random.shuffle(samples)
    
    # 统计
    up_count = sum(1 for s in samples if s["label"] == "UP")
    side_count = sum(1 for s in samples if s["label"] == "SIDE")
    down_count = sum(1 for s in samples if s["label"] == "DOWN")
    
    print(f"\n总样本数: {len(samples)}")
    print(f"  UP: {up_count} ({up_count/len(samples)*100:.1f}%)")
    print(f"  SIDE: {side_count} ({side_count/len(samples)*100:.1f}%)")
    print(f"  DOWN: {down_count} ({down_count/len(samples)*100:.1f}%)")
    
    return samples


def save_labels(samples: list):
    """保存标注文件"""
    os.makedirs(CONFIG["labels_dir"], exist_ok=True)
    output_path = os.path.join(CONFIG["labels_dir"], CONFIG["labels_file"])
    
    data = {
        "version": "v2.960_auto",
        "created": datetime.now().isoformat(),
        "total_samples": len(samples),
        "label_distribution": {
            "UP": sum(1 for s in samples if s["label"] == "UP"),
            "SIDE": sum(1 for s in samples if s["label"] == "SIDE"),
            "DOWN": sum(1 for s in samples if s["label"] == "DOWN"),
        },
        "config": {
            "up_threshold": CONFIG["up_threshold"],
            "down_threshold": CONFIG["down_threshold"],
            "future_klines": CONFIG["future_klines"],
        },
        "samples": samples,
    }
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    
    print(f"\n标注已保存: {output_path}")


# ============================================================
# CNN模型
# ============================================================

class KlineDataset(Dataset):
    def __init__(self, samples: list, augment: bool = False):
        self.samples = samples
        self.augment = augment
    
    def __len__(self):
        return len(self.samples)
    
    def __getitem__(self, idx):
        sample = self.samples[idx]
        features = self._extract_features(sample["klines"])
        
        if self.augment:
            features = self._augment(features)
        
        features = self._normalize(features)
        
        x = torch.tensor(features, dtype=torch.float32)
        y = torch.tensor(sample["label_idx"], dtype=torch.long)
        
        return x, y
    
    def _extract_features(self, klines: list) -> np.ndarray:
        features = []
        for bar in klines:
            o = float(bar.get("open", 0))
            h = float(bar.get("high", 0))
            l = float(bar.get("low", 0))
            c = float(bar.get("close", 0))
            v = float(bar.get("volume", 0))
            change_pct = (c - o) / o * 100 if o > 0 else 0
            features.append([o, h, l, c, v, change_pct])
        
        features = np.array(features, dtype=np.float32)
        
        # 确保长度
        target_len = CONFIG["klines_per_sample"]
        if len(features) < target_len:
            pad = np.zeros((target_len - len(features), 6), dtype=np.float32)
            features = np.vstack([pad, features])
        elif len(features) > target_len:
            features = features[-target_len:]
        
        return features
    
    def _normalize(self, features: np.ndarray) -> np.ndarray:
        normalized = features.copy()
        
        base_price = 1.0
        for i in range(len(features)):
            if features[i, 0] > 0:
                base_price = features[i, 0]
                break
        
        for i in range(4):
            normalized[:, i] = (features[:, i] - base_price) / base_price * 100
        
        vol = features[:, 4]
        vol_nonzero = vol[vol > 0]
        if len(vol_nonzero) > 0:
            vol_mean = np.log1p(vol_nonzero).mean()
            vol_std = np.log1p(vol_nonzero).std() + 1e-8
            normalized[:, 4] = (np.log1p(vol) - vol_mean) / vol_std
        
        normalized[:, 5] = features[:, 5] / 10.0
        
        return normalized
    
    def _augment(self, features: np.ndarray) -> np.ndarray:
        if np.random.rand() < 0.3:
            noise = np.random.normal(0, 0.01, features.shape)
            features = features + noise.astype(np.float32)
        
        if np.random.rand() < 0.3:
            scale = np.random.uniform(0.95, 1.05)
            features[:, :4] *= scale
        
        return features


class CNN1DNetwork(nn.Module):
    def __init__(self):
        super(CNN1DNetwork, self).__init__()
        
        self.conv1 = nn.Conv1d(6, 64, kernel_size=3, padding=1)
        self.bn1 = nn.BatchNorm1d(64)
        self.pool1 = nn.MaxPool1d(2)
        
        self.conv2 = nn.Conv1d(64, 128, kernel_size=3, padding=1)
        self.bn2 = nn.BatchNorm1d(128)
        self.pool2 = nn.MaxPool1d(2)
        
        self.conv3 = nn.Conv1d(128, 256, kernel_size=3, padding=1)
        self.bn3 = nn.BatchNorm1d(256)
        
        self.fc1 = nn.Linear(256, 128)
        self.dropout = nn.Dropout(0.4)
        self.fc2 = nn.Linear(128, 3)
    
    def forward(self, x):
        x = x.permute(0, 2, 1)  # (batch, features, seq)
        
        x = F.relu(self.bn1(self.conv1(x)))
        x = self.pool1(x)
        
        x = F.relu(self.bn2(self.conv2(x)))
        x = self.pool2(x)
        
        x = F.relu(self.bn3(self.conv3(x)))
        
        x = x.mean(dim=2)  # Global Average Pooling
        
        x = F.relu(self.fc1(x))
        x = self.dropout(x)
        x = self.fc2(x)
        
        return x


# ============================================================
# 训练
# ============================================================

def train_model(samples: list):
    """训练CNN模型"""
    
    print("\n" + "=" * 60)
    print("Step 2: 训练CNN模型")
    print("=" * 60)
    
    # 强制使用CPU (避免CUDA版本不兼容问题)
    device = "cpu"
    print(f"设备: {device}")
    
    # 划分数据
    random.shuffle(samples)
    split_idx = int(len(samples) * (1 - CONFIG["val_split"]))
    train_samples = samples[:split_idx]
    val_samples = samples[split_idx:]
    
    print(f"训练集: {len(train_samples)}, 验证集: {len(val_samples)}")
    
    # DataLoader
    train_dataset = KlineDataset(train_samples, augment=True)
    val_dataset = KlineDataset(val_samples, augment=False)
    
    train_loader = DataLoader(train_dataset, batch_size=CONFIG["batch_size"], shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=CONFIG["batch_size"], shuffle=False)
    
    # 模型
    model = CNN1DNetwork().to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=CONFIG["learning_rate"], weight_decay=1e-4)
    criterion = nn.CrossEntropyLoss()
    
    # 学习率调度
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode='max', factor=0.5, patience=5)
    
    # 训练
    best_val_acc = 0
    patience_counter = 0
    best_model_state = None
    history = {"train_loss": [], "val_loss": [], "val_acc": []}
    
    print("\n开始训练...")
    for epoch in range(CONFIG["epochs"]):
        # 训练
        model.train()
        train_loss = 0
        for batch_x, batch_y in train_loader:
            batch_x, batch_y = batch_x.to(device), batch_y.to(device)
            optimizer.zero_grad()
            outputs = model(batch_x)
            loss = criterion(outputs, batch_y)
            loss.backward()
            optimizer.step()
            train_loss += loss.item()
        train_loss /= len(train_loader)
        
        # 验证
        model.eval()
        val_loss = 0
        correct = 0
        total = 0
        with torch.no_grad():
            for batch_x, batch_y in val_loader:
                batch_x, batch_y = batch_x.to(device), batch_y.to(device)
                outputs = model(batch_x)
                loss = criterion(outputs, batch_y)
                val_loss += loss.item()
                _, predicted = outputs.max(1)
                total += batch_y.size(0)
                correct += predicted.eq(batch_y).sum().item()
        val_loss /= len(val_loader)
        val_acc = correct / total
        
        history["train_loss"].append(train_loss)
        history["val_loss"].append(val_loss)
        history["val_acc"].append(val_acc)
        
        # 学习率调度
        scheduler.step(val_acc)
        
        print(f"Epoch {epoch+1:3d}/{CONFIG['epochs']} | "
              f"Train Loss: {train_loss:.4f} | Val Loss: {val_loss:.4f} | "
              f"Val Acc: {val_acc:.1%}")
        
        # 保存最佳
        if val_acc > best_val_acc:
            best_val_acc = val_acc
            best_model_state = model.state_dict().copy()
            patience_counter = 0
            print(f"  ↑ 新最佳模型!")
        else:
            patience_counter += 1
        
        # 早停
        if patience_counter >= CONFIG["early_stopping_patience"]:
            print(f"\n早停: {patience_counter} 轮未改善")
            break
    
    # 恢复最佳模型
    if best_model_state:
        model.load_state_dict(best_model_state)
    
    print(f"\n最佳验证准确率: {best_val_acc:.1%}")
    
    return model, best_val_acc, len(train_samples), len(val_samples), history


def save_model(model, val_acc, train_samples, val_samples, history):
    """保存模型和统计"""
    
    # 保存模型
    os.makedirs(CONFIG["model_dir"], exist_ok=True)
    model_path = os.path.join(CONFIG["model_dir"], CONFIG["model_file"])
    
    checkpoint = {
        "model_state_dict": model.state_dict(),
        "config": {
            "input_length": CONFIG["klines_per_sample"],
            "input_features": 6,
            "num_classes": 3,
        },
        "stats": {
            "train_samples": train_samples,
            "val_samples": val_samples,
            "val_accuracy": val_acc,
            "epochs_trained": len(history["train_loss"]),
            "trained_at": datetime.now().isoformat(),
        },
        "history": history,
    }
    
    torch.save(checkpoint, model_path)
    print(f"\n模型已保存: {model_path}")
    
    # 保存统计
    os.makedirs(CONFIG["stats_dir"], exist_ok=True)
    stats_path = os.path.join(CONFIG["stats_dir"], CONFIG["stats_file"])
    
    stats = {
        "model_version": "v2.960_auto",
        "train_samples": train_samples,
        "val_samples": val_samples,
        "val_accuracy": val_acc,
        "epochs_trained": len(history["train_loss"]),
        "trained_at": datetime.now().isoformat(),
    }
    
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    
    print(f"统计已保存: {stats_path}")


# ============================================================
# 主函数
# ============================================================

def main():
    print("=" * 60)
    print("自动标注 + CNN训练脚本 v2.960")
    print("=" * 60)
    
    print(f"\n配置:")
    print(f"  加密货币: {len(CONFIG['symbols']['crypto'])} 个")
    print(f"  美股: {len(CONFIG['symbols']['stocks'])} 个")
    print(f"  K线周期: {CONFIG['intervals']}")
    print(f"  每品种每周期采样: {CONFIG['samples_per_symbol']}")
    print(f"  标签阈值: UP > {CONFIG['up_threshold']*100}%, DOWN < {CONFIG['down_threshold']*100}%")
    
    # 计算预期样本数
    total_symbols = len(CONFIG['symbols']['crypto']) + len(CONFIG['symbols']['stocks'])
    expected_samples = total_symbols * len(CONFIG['intervals']) * CONFIG['samples_per_symbol']
    print(f"  预期最大样本数: ~{expected_samples}")
    
    # Step 1: 自动标注
    all_symbols = CONFIG['symbols']['crypto'] + CONFIG['symbols']['stocks']
    samples = auto_label_samples(all_symbols, CONFIG['intervals'])
    
    if len(samples) < 100:
        print(f"\n[错误] 样本太少 ({len(samples)}), 需要至少100个")
        return
    
    # 保存标注
    save_labels(samples)
    
    # Step 2: 训练
    model, val_acc, train_n, val_n, history = train_model(samples)
    
    # Step 3: 保存
    save_model(model, val_acc, train_n, val_n, history)
    
    print("\n" + "=" * 60)
    print("完成!")
    print("=" * 60)
    print(f"\n总样本数: {len(samples)}")
    print(f"训练样本: {train_n}")
    print(f"验证样本: {val_n}")
    print(f"验证准确率: {val_acc:.1%}")
    print(f"\n模型文件: {CONFIG['model_dir']}/{CONFIG['model_file']}")
    print(f"统计文件: {CONFIG['stats_dir']}/{CONFIG['stats_file']}")


if __name__ == "__main__":
    main()
