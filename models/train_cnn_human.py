"""
CNN Human Model 训练程序 v2.950

使用标注数据训练1D-CNN模型，用于K线趋势预测。

使用方法:
    python train_cnn_human.py

训练流程:
    1. 加载 labels/training_labels.json
    2. 数据预处理和增强
    3. 划分训练集/验证集 (80%/20%)
    4. 训练1D-CNN模型
    5. 保存模型到 models/cnn_human_model.pt
    6. 保存统计到 state/cnn_human_stats.json

依赖:
    pip install torch numpy

作者: AI Trading System
版本: v2.950
日期: 2025-12-27
"""

import os
import sys
import json
import numpy as np
from datetime import datetime

# ============================================================
# PyTorch导入
# ============================================================

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
# 配置
# ============================================================

TRAIN_CONFIG = {
    # 数据
    "labels_file": "labels/training_labels.json",
    "input_length": 50,
    "input_features": 6,
    
    # 模型
    "conv1_filters": 64,
    "conv2_filters": 128,
    "kernel_size": 3,
    "dense_units": 64,
    "dropout_rate": 0.3,
    "num_classes": 3,
    
    # 训练
    "batch_size": 32,
    "epochs": 50,
    "learning_rate": 0.001,
    "weight_decay": 1e-4,
    "val_split": 0.2,
    "early_stopping_patience": 10,
    
    # 输出
    "model_dir": "models",
    "model_file": "cnn_human_model.pt",
    "stats_dir": "state",
    "stats_file": "cnn_human_stats.json",
}

# 类别
CLASS_NAMES = ["UP", "SIDE", "DOWN"]
CLASS_TO_IDX = {"UP": 0, "SIDE": 1, "DOWN": 2}


# ============================================================
# 数据集类
# ============================================================

class KlineDataset(Dataset):
    """
    K线数据集
    """
    
    def __init__(self, samples: list, augment: bool = False):
        """
        Args:
            samples: 标注样本列表
            augment: 是否数据增强
        """
        self.samples = samples
        self.augment = augment
    
    def __len__(self):
        return len(self.samples)
    
    def __getitem__(self, idx):
        sample = self.samples[idx]
        
        # 提取特征
        features = self._extract_features(sample["klines"])
        
        # 数据增强
        if self.augment:
            features = self._augment(features)
        
        # 标准化
        features = self._normalize(features)
        
        # 转换为tensor
        x = torch.tensor(features, dtype=torch.float32)
        y = torch.tensor(sample["label_idx"], dtype=torch.long)
        
        return x, y
    
    def _extract_features(self, klines: list) -> np.ndarray:
        """提取特征"""
        features = []
        
        for bar in klines:
            o = float(bar.get("open", bar.get("o", 0)))
            h = float(bar.get("high", bar.get("h", 0)))
            l = float(bar.get("low", bar.get("l", 0)))
            c = float(bar.get("close", bar.get("c", 0)))
            v = float(bar.get("volume", bar.get("v", 0)))
            
            change_pct = (c - o) / o * 100 if o > 0 else 0
            
            features.append([o, h, l, c, v, change_pct])
        
        features = np.array(features, dtype=np.float32)
        
        # 确保长度
        target_len = TRAIN_CONFIG["input_length"]
        if len(features) < target_len:
            pad = np.zeros((target_len - len(features), 6), dtype=np.float32)
            features = np.vstack([pad, features])
        elif len(features) > target_len:
            features = features[-target_len:]
        
        return features
    
    def _normalize(self, features: np.ndarray) -> np.ndarray:
        """标准化"""
        normalized = features.copy()
        
        # 找基准价
        base_price = 1.0
        for i in range(len(features)):
            if features[i, 0] > 0:
                base_price = features[i, 0]
                break
        
        # OHLC标准化
        for i in range(4):
            normalized[:, i] = (features[:, i] - base_price) / base_price * 100
        
        # Volume标准化
        vol = features[:, 4]
        vol_nonzero = vol[vol > 0]
        if len(vol_nonzero) > 0:
            vol_mean = np.log1p(vol_nonzero).mean()
            vol_std = np.log1p(vol_nonzero).std() + 1e-8
            normalized[:, 4] = (np.log1p(vol) - vol_mean) / vol_std
        
        # Change%缩放
        normalized[:, 5] = features[:, 5] / 10.0
        
        return normalized
    
    def _augment(self, features: np.ndarray) -> np.ndarray:
        """数据增强"""
        # 随机噪声
        if np.random.rand() < 0.3:
            noise = np.random.normal(0, 0.01, features.shape)
            features = features + noise.astype(np.float32)
        
        # 随机缩放
        if np.random.rand() < 0.3:
            scale = np.random.uniform(0.95, 1.05)
            features[:, :4] *= scale
        
        return features


# ============================================================
# CNN网络
# ============================================================

class CNN1DNetwork(nn.Module):
    """
    1D-CNN网络
    """
    
    def __init__(self, config):
        super(CNN1DNetwork, self).__init__()
        
        self.conv1 = nn.Conv1d(
            in_channels=config["input_features"],
            out_channels=config["conv1_filters"],
            kernel_size=config["kernel_size"],
            padding=1
        )
        self.bn1 = nn.BatchNorm1d(config["conv1_filters"])
        self.pool1 = nn.MaxPool1d(kernel_size=2)
        
        self.conv2 = nn.Conv1d(
            in_channels=config["conv1_filters"],
            out_channels=config["conv2_filters"],
            kernel_size=config["kernel_size"],
            padding=1
        )
        self.bn2 = nn.BatchNorm1d(config["conv2_filters"])
        self.pool2 = nn.MaxPool1d(kernel_size=2)
        
        self.fc1 = nn.Linear(config["conv2_filters"], config["dense_units"])
        self.dropout = nn.Dropout(config["dropout_rate"])
        self.fc2 = nn.Linear(config["dense_units"], config["num_classes"])
    
    def forward(self, x):
        # x: (batch, seq_len, features) → (batch, features, seq_len)
        x = x.permute(0, 2, 1)
        
        x = F.relu(self.bn1(self.conv1(x)))
        x = self.pool1(x)
        
        x = F.relu(self.bn2(self.conv2(x)))
        x = self.pool2(x)
        
        x = x.mean(dim=2)  # Global Average Pooling
        
        x = F.relu(self.fc1(x))
        x = self.dropout(x)
        x = self.fc2(x)
        
        return x


# ============================================================
# 训练器
# ============================================================

class Trainer:
    """
    模型训练器
    """
    
    def __init__(self, config):
        self.config = config
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = None
        self.optimizer = None
        self.criterion = None
        self.train_loader = None
        self.val_loader = None
        self.history = {"train_loss": [], "val_loss": [], "val_acc": []}
        
        print(f"[训练器] 设备: {self.device}")
        if self.device == "cuda":
            print(f"[训练器] GPU: {torch.cuda.get_device_name(0)}")
    
    def load_data(self):
        """加载标注数据"""
        labels_path = self.config["labels_file"]
        
        if not os.path.exists(labels_path):
            print(f"[错误] 标注文件不存在: {labels_path}")
            print("[提示] 请先运行 labeling_tool.py 进行标注")
            return False
        
        with open(labels_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        samples = data.get("samples", [])
        
        if len(samples) < 20:
            print(f"[错误] 样本数量不足: {len(samples)} (最少需要20个)")
            return False
        
        print(f"[数据] 加载 {len(samples)} 个标注样本")
        print(f"[数据] 分布: UP={data['label_distribution']['UP']}, "
              f"SIDE={data['label_distribution']['SIDE']}, "
              f"DOWN={data['label_distribution']['DOWN']}")
        
        # 划分训练集/验证集
        np.random.shuffle(samples)
        split_idx = int(len(samples) * (1 - self.config["val_split"]))
        train_samples = samples[:split_idx]
        val_samples = samples[split_idx:]
        
        print(f"[数据] 训练集: {len(train_samples)}, 验证集: {len(val_samples)}")
        
        # 创建DataLoader
        train_dataset = KlineDataset(train_samples, augment=True)
        val_dataset = KlineDataset(val_samples, augment=False)
        
        self.train_loader = DataLoader(
            train_dataset,
            batch_size=self.config["batch_size"],
            shuffle=True,
            num_workers=0
        )
        self.val_loader = DataLoader(
            val_dataset,
            batch_size=self.config["batch_size"],
            shuffle=False,
            num_workers=0
        )
        
        self.train_samples = len(train_samples)
        self.val_samples = len(val_samples)
        
        return True
    
    def build_model(self):
        """构建模型"""
        self.model = CNN1DNetwork(self.config)
        self.model.to(self.device)
        
        self.optimizer = torch.optim.Adam(
            self.model.parameters(),
            lr=self.config["learning_rate"],
            weight_decay=self.config["weight_decay"]
        )
        
        self.criterion = nn.CrossEntropyLoss()
        
        # 计算参数量
        total_params = sum(p.numel() for p in self.model.parameters())
        print(f"[模型] 参数量: {total_params:,}")
    
    def train_epoch(self):
        """训练一个epoch"""
        self.model.train()
        total_loss = 0
        
        for batch_x, batch_y in self.train_loader:
            batch_x = batch_x.to(self.device)
            batch_y = batch_y.to(self.device)
            
            self.optimizer.zero_grad()
            outputs = self.model(batch_x)
            loss = self.criterion(outputs, batch_y)
            loss.backward()
            self.optimizer.step()
            
            total_loss += loss.item()
        
        return total_loss / len(self.train_loader)
    
    def validate(self):
        """验证"""
        self.model.eval()
        total_loss = 0
        correct = 0
        total = 0
        
        with torch.no_grad():
            for batch_x, batch_y in self.val_loader:
                batch_x = batch_x.to(self.device)
                batch_y = batch_y.to(self.device)
                
                outputs = self.model(batch_x)
                loss = self.criterion(outputs, batch_y)
                total_loss += loss.item()
                
                _, predicted = outputs.max(1)
                total += batch_y.size(0)
                correct += predicted.eq(batch_y).sum().item()
        
        val_loss = total_loss / len(self.val_loader)
        val_acc = correct / total
        
        return val_loss, val_acc
    
    def train(self):
        """完整训练流程"""
        print("\n" + "=" * 60)
        print("开始训练")
        print("=" * 60)
        
        best_val_acc = 0
        patience_counter = 0
        best_model_state = None
        
        for epoch in range(self.config["epochs"]):
            train_loss = self.train_epoch()
            val_loss, val_acc = self.validate()
            
            self.history["train_loss"].append(train_loss)
            self.history["val_loss"].append(val_loss)
            self.history["val_acc"].append(val_acc)
            
            print(f"Epoch {epoch+1:3d}/{self.config['epochs']} | "
                  f"Train Loss: {train_loss:.4f} | "
                  f"Val Loss: {val_loss:.4f} | "
                  f"Val Acc: {val_acc:.1%}")
            
            # 保存最佳模型
            if val_acc > best_val_acc:
                best_val_acc = val_acc
                best_model_state = self.model.state_dict().copy()
                patience_counter = 0
                print(f"  ↑ 新最佳模型 (Val Acc: {val_acc:.1%})")
            else:
                patience_counter += 1
            
            # 早停
            if patience_counter >= self.config["early_stopping_patience"]:
                print(f"\n[早停] {patience_counter} 轮未改善，停止训练")
                break
        
        # 恢复最佳模型
        if best_model_state:
            self.model.load_state_dict(best_model_state)
        
        print(f"\n训练完成，最佳验证准确率: {best_val_acc:.1%}")
        
        return best_val_acc
    
    def save_model(self):
        """保存模型"""
        os.makedirs(self.config["model_dir"], exist_ok=True)
        model_path = os.path.join(self.config["model_dir"], self.config["model_file"])
        
        checkpoint = {
            "model_state_dict": self.model.state_dict(),
            "config": self.config,
            "stats": {
                "train_samples": self.train_samples,
                "val_samples": self.val_samples,
                "val_accuracy": max(self.history["val_acc"]) if self.history["val_acc"] else 0,
                "epochs_trained": len(self.history["train_loss"]),
                "trained_at": datetime.now().isoformat(),
            },
            "history": self.history,
        }
        
        torch.save(checkpoint, model_path)
        print(f"[保存] 模型已保存: {model_path}")
        
        return model_path
    
    def save_stats(self):
        """保存统计信息"""
        os.makedirs(self.config["stats_dir"], exist_ok=True)
        stats_path = os.path.join(self.config["stats_dir"], self.config["stats_file"])
        
        stats = {
            "model_version": "v2.950",
            "train_samples": self.train_samples,
            "val_samples": self.val_samples,
            "val_accuracy": max(self.history["val_acc"]) if self.history["val_acc"] else 0,
            "epochs_trained": len(self.history["train_loss"]),
            "best_epoch": self.history["val_acc"].index(max(self.history["val_acc"])) + 1 if self.history["val_acc"] else 0,
            "final_train_loss": self.history["train_loss"][-1] if self.history["train_loss"] else 0,
            "final_val_loss": self.history["val_loss"][-1] if self.history["val_loss"] else 0,
            "trained_at": datetime.now().isoformat(),
            "device": self.device,
        }
        
        with open(stats_path, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
        
        print(f"[保存] 统计已保存: {stats_path}")
        
        return stats_path


# ============================================================
# 主函数
# ============================================================

def main():
    print("=" * 60)
    print("CNN Human Model 训练程序 v2.950")
    print("=" * 60)
    
    # 检查PyTorch
    print(f"\nPyTorch版本: {torch.__version__}")
    print(f"CUDA可用: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"GPU: {torch.cuda.get_device_name(0)}")
    
    # 创建训练器
    trainer = Trainer(TRAIN_CONFIG)
    
    # 加载数据
    if not trainer.load_data():
        print("\n[错误] 数据加载失败，退出")
        return
    
    # 构建模型
    trainer.build_model()
    
    # 训练
    best_acc = trainer.train()
    
    # 保存
    trainer.save_model()
    trainer.save_stats()
    
    print("\n" + "=" * 60)
    print("训练完成")
    print("=" * 60)
    print(f"\n最终验证准确率: {best_acc:.1%}")
    print(f"模型文件: {TRAIN_CONFIG['model_dir']}/{TRAIN_CONFIG['model_file']}")
    print(f"统计文件: {TRAIN_CONFIG['stats_dir']}/{TRAIN_CONFIG['stats_file']}")
    
    # 使用提示
    print("\n" + "-" * 60)
    print("下一步:")
    print("  1. 将模型文件复制到主程序目录")
    print("  2. 在 llm_server_v2950.py 中设置 USE_CNN_HUMAN = True")
    print("  3. 重启主程序")
    print("-" * 60)


if __name__ == "__main__":
    main()
