"""
modules/knn/models.py — L1 数据模型
====================================
KNN模块的数据结构、配置常量、日志工具。
gcc-evo五层架构: L1 数据模型层
"""

import logging
from pathlib import Path
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger("plugin_knn")

# ============================================================
# 路径
# ============================================================
ROOT = Path(__file__).parent.parent.parent  # ai-trading-bot/
STATE_DIR = ROOT / "state"

_HISTORY_FILE = STATE_DIR / "plugin_knn_history.npz"
_ACCURACY_FILE = STATE_DIR / "plugin_knn_accuracy.json"
_PENDING_FILE = STATE_DIR / "plugin_knn_pending.json"
_AUG_FILE = STATE_DIR / "plugin_knn_aug_stats.json"
_EVO_TUNE_FILE = STATE_DIR / "knn_evolution_tune.json"
_MAB_STATE_FILE = STATE_DIR / "knn_mab_state.json"

# ============================================================
# 配置常量
# ============================================================
PRICE_SHAPE_WINDOW = 20       # 价格形状特征: 最近20根4H K线
KNN_FUTURE_BARS = 10          # 回填: 10根4H bar后的收益率
KNN_K = 30                    # 默认K值(自适应时作为fallback)
KNN_MIN_SAMPLES = 15          # 最少样本数才出bias
KNN_BYPASS_THRESHOLD = 0.55   # 准确率低于此值 → bypass KNN查询
INDICATOR_WEIGHT = 3.0        # 指标维度权重(入场点质量)
SHAPE_WEIGHT = 1.0            # 价格形状维度权重(市场背景)
USE_STL_RESIDUAL = True       # GCC-0136: STL残差匹配(去趋势/季节性)
STL_PERIOD = 5                # STL分解周期(4H K线, 5根≈1天)
VOL_SHAPE_WINDOW = 20         # 成交量形状特征: 最近20根K线
ATR_WINDOW = 20               # ATR特征: 最近20根K线
PSI_THRESHOLD = 0.2           # GCC-0138: PSI > 0.2 → 显著漂移
DRIFT_K_MULTIPLIER = 2        # 漂移时K翻倍(更多邻居降噪)
DRIFT_CONFIDENCE_DECAY = 0.7  # 漂移时置信度乘以0.7
AUG_TAU = 20.0                # GCC-0139: 增强调度τ参数
AUG_JITTER_STD = 0.02         # GCC-0139: jitter噪声标准差
MIXUP_PROB = 0.3              # GCC-0140: Mix-up触发概率

# Phase控制
PLUGIN_KNN_PHASE2 = False     # Phase2: KNN反向+高置信 → 抑制信号
PHASE2_MIN_SAMPLES = 30       # 真实回填样本≥30才启用Phase2

# 品种列表
CRYPTO_SYMBOLS = ["BTCUSDC", "ETHUSDC", "SOLUSDC", "ZECUSDC"]
STOCK_SYMBOLS = ["TSLA", "COIN", "RDDT", "NBIS", "CRWV", "RKLB", "HIMS", "OPEN", "AMD", "ONDS", "PLTR"]
YF_MAP = {
    "BTCUSDC": "BTC-USD", "ETHUSDC": "ETH-USD",
    "SOLUSDC": "SOL-USD", "ZECUSDC": "ZEC-USD",
}

# WFO参数
WFO_TRAIN_BARS = 180           # 训练窗口: 180根4H bar (~30天)
WFO_VALID_BARS = 45            # 验证窗口: 45根4H bar (~7.5天)


# ============================================================
# 数据结构
# ============================================================
@dataclass
class PluginKNNResult:
    win_rate: float        # 历史相似情况胜率
    avg_return: float      # 历史相似情况平均收益
    sample_count: int      # 匹配样本数
    best_match_dist: float # 最近距离
    bias: str              # BUY / SELL / NEUTRAL
    confidence: float      # 置信度 (0~1)
    reason: str            # 可读原因


# ============================================================
# 日志工具
# ============================================================
def plugin_log(msg: str):
    """输出到可用日志: llm_server进程用log_to_server→server.log, scan_engine进程用logger→scan log"""
    try:
        from llm_server_v3640 import log_to_server
        log_to_server(msg)
    except Exception:
        logger.info(msg)
