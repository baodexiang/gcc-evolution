"""
Core Analysis Modules
=====================
Synced from v3.640 main program

v5.640: Added trend_8bar module for Chan Theory K-line merging
        Module available at core.trend_8bar, use: from core.trend_8bar import ...
"""

from .l1_analysis import L1Analyzer
from .l2_analysis import L2Analyzer
from .signal_generator import SignalGenerator
from .deepseek_analyzer import DeepSeekAnalyzer

__all__ = ["L1Analyzer", "L2Analyzer", "SignalGenerator", "DeepSeekAnalyzer"]

# v5.640: trend_8bar 模块可按需导入
# from .trend_8bar import merge, judge, Trend, TrendDetector, decide
