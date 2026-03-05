"""
AI PRO Trading System v5.640 - Cloud Validation
================================================
Synced from v3.640 main program
DRY_RUN mode: Analysis only, no actual trading

v5.640 Update (缠论K线合并 + 三段判定):
- 缠论K线合并处理包含关系 (trend_8bar.py merge函数)
- 三段判定早期识别趋势变化 (trend_8bar.py judge函数)
- 子周期数据源自动选择 (_find_sub_timeframe函数)
- 用8根子K线提前判断当前周期趋势 (TrendDetector类)
- Synced from llm_server_v3640.py

v5.540 Update (趋势转折同步 + 智能选股):
- 趋势转折自动同步到扫描引擎 (sync_trend_to_scan_engine_v3540)
- global_trend_state.json 趋势持久化
- 启动时L1刷新后同步趋势到外挂
- 模拟盘智能选股: 搜索过滤 + 板块分类 + 快捷预设
- Synced from llm_server_v3540.py

v5.498 Update (HOLD门卫开放 + UNCLEAR位置策略):
- P0-1: HOLD时门卫开放 (让L1外挂自己判断趋势)
  - 大周期=HOLD时门卫不关闭
  - HOLD+BUY/STRONG_BUY → 放行买入 (L1外挂决策)
  - HOLD+SELL/STRONG_SELL → 放行卖出 (L1外挂决策)
  - HOLD+其他 → 等待
- P0-2: UNCLEAR阶段纯位置策略
  - Wyckoff阶段=UNCLEAR时，不再返回0分
  - pos<20% → +2分 (极低位倾向买入)
  - pos>80% → -2分 (极高位倾向卖出)
  - 中间位置 → 0分 (等待)
- P1-3: 满仓+极低位警告日志
  - 满仓+极低位(<5%)时记录警告日志
  - 提示"低位加仓机会但满仓"
- Synced from llm_server_v3498.py

v5.497 Update (美股成本价格高抛低吸):
- P0-1: 成本价格计算 (get_avg_cost_price)
  - 从open_buys计算平均成本
  - 或从cycle_cost_basis/position_units计算
- P0-2: 成本拉低评分调整 (get_cost_reduction_score_adj)
  - 浮亏+低位(<30%) → +1分 (加仓拉低成本)
  - 浮亏+高位(>70%) → -1分 (减仓止损)
  - 浮盈+高位(>70%) → -1分 (锁定利润)
- 注: 云端DRY_RUN模式无实际持仓，此功能仅在主程序生效
- Synced from llm_server_v3497.py

v5.494 Update (Wyckoff阶段位置修正):
- P2-1: Wyckoff阶段极端位置修正
  - EXTREME_LOW(pos<0.15) + down趋势 → ACCUMULATION (底部吸筹，非下跌趋势)
  - EXTREME_HIGH(pos>0.85) + up趋势 → DISTRIBUTION (顶部派发，非上涨趋势)
  - 位置比趋势更重要：极端位置覆盖趋势判断

v5.493 Update (L1趋势判断修复 + 启动时L1自动刷新 + 价格强制判断阈值优化 + 模拟盘周期自动配置):
- P0-1: L1趋势判断修复
  - x4 DOW-Swing参数: n_swing=3→2, min_swings=3→2 (道氏理论标准化)
  - 2个波峰+2个波谷即可确认趋势，无需等待3个
  - side→整体趋势兜底: DOW-Swing返回side但整体涨跌>=5%时用整体方向判定
  - Tech ADX>=40强制判定UP/DOWN方向，不再直接判RANGING
- P0-2: 启动时L1自动刷新
  - 服务器启动后自动对14个品种运行完整L1五模块分析
  - /refresh_l1 API支持手动刷新单个或全部品种
  - 解决新版本上线后L1判断滞后问题
- P1-3: 价格强制判断阈值优化
  - 加密货币: 5%触发强制趋势判断 (原10%)
  - 美股: 8%触发强制趋势判断 (原10%)
  - 动态ADX阈值降低: 加密3%/美股5%时降低ADX阈值
- P1-4: 模拟盘支持用户自选周期
  - 新增 stock_timeframe / crypto_timeframe 配置项
  - 默认: 美股=4h, 加密货币=2h
  - 用户可在模拟盘设置中修改周期
  - 分析API优先使用用户配置的周期
- P2-5: 云端新增AI产业链+资源类股票 (26只)
  - AI产业链: TSM, SMCI, ARM, ANET, VRT, VST, CEG, OKLO
  - 资源类: FCX, SCCO, TECK, MP, ALB, LAC, SQM, GOLD, NEM, AEM, CCJ, UEC, BHP, RIO, VALE, NUE, CLF, X
- Synced from llm_server_v3493.py

v5.487 Update (Wyckoff稳定性 + 回调检测 + 底部保护):
- P0-1: Wyckoff阶段确认机制 (防止ZEC等品种跳变)
  - 连续2根K线确认才切换阶段
  - 全局缓存: _wyckoff_phase_cache
- P0-2: 短期回调企稳检测 (见底仍SELL问题)
  - 回调>5% + 企稳K线(锤子/十字星/长下影) → 暂停SELL
- P1-3: MARKUP_PULLBACK子状态 (回调识别延迟)
  - MARKUP + 连续2阴线 → PULLBACK, 反向权重×0.5
  - MARKDOWN + 连续2阳线 → RALLY, 反向权重×0.5
- P1-4: 底部反转保护 (RSI<30/看涨吞没/锤子→暂停SELL)
- P2-5: UNCLEAR阶段Wyckoff分归零
- P2-6: 双周期位置确认 (长期120+短期20, 背离时权重×0.7)
- Synced from llm_server_v3487.py

v5.480 Update (L1 Wyckoff定位 + L2四大类评分):
- P0: L1纯x4定位Wyckoff阶段 (简洁可靠)
  - trend_x4=UP → MARKUP (上涨期)
  - trend_x4=DOWN → MARKDOWN (下跌期)
  - trend_x4=SIDE + pos<30% → ACCUMULATION (吸筹期)
  - trend_x4=SIDE + pos>70% → DISTRIBUTION (派发期)
  - trend_x4=SIDE + 中间位置 → RANGING (震荡期)
- P0: L2四大类评分 (-14 ~ +14)
  - 【形态分】(±6) - PA + 2B + 123 + K线形态, Donchian乘数
  - 【位置分】(±4) - TV pos_in_channel直接映射
  - 【量能分】(±2) - 量价配合验证
  - 【Wyckoff策略分】(±2) - 形态与阶段匹配度
    - 同一形态在不同阶段有不同价值
    - MARKUP期Hammer: +2 (回调企稳)
    - MARKDOWN期Hammer: -2 (逆势)
- NEW: Wyckoff策略类型
  - MARKUP/MARKDOWN → TREND_PULLBACK (顺大逆小)
  - ACCUMULATION/DISTRIBUTION/RANGING → RANGE_REVERSAL (高抛低吸)
- 阈值: STRONG_BUY≥7 | BUY≥4 | HOLD[-3,+3] | SELL≤-4 | STRONG_SELL≤-7
- Synced from llm_server_v3480.py

v5.455 Update (L2评分重构):
- P0: L2评分重构 - 解决分数膨胀问题
  - 问题: 原始设计最大22分，STRONG阈值6分=仅需27%即触发
  - 解决: 压缩评分范围至-12~+12，STRONG需50%
- NEW: 单根K线形态评分 (candle_shape_score)
  - +1.0: 大阳线/锤子线
  - +0.5: 普通阳线
  -  0.0: 十字星/纺锤
  - -0.5: 普通阴线
  - -1.0: 大阴线/射击之星
- 权重压缩: Pattern(-3~+3), Position(-2~+2), K线形态(-1~+1)
- Synced from llm_server_v3455.py

v5.450 Update (P0-CycleSwitch):
- P0: 周期切换立即完整分析
  - 触发: 任何周期切换都触发完整三方协商分析
  - 流程: 预加载OHLCV → Tech+Human信号 → DeepSeek仲裁 → BUY/HOLD/SELL
  - 交易: 正常执行 (无特殊阈值)
  - 邮件: 正常发送 (标识来源P0-CycleSwitch)
  - 目的: 切换周期后立即得到交易建议，不等待下次TradingView推送
- Synced from llm_server_v3450.py

v5.445 Update (品种独立周期配置):
- P0: 品种独立周期 (解决混周期K线问题)
  - 问题: 所有品种使用相同MAIN_TIMEFRAME=30min预加载
  - 实际: ZEC=1h, BTC/ETH/SOL=2h, 美股=4h
  - 解决: SYMBOL_TIMEFRAMES字典配置品种独立周期
- P1: CoinGecko支持2h granularity
- P2: TwelveData支持2h/4h interval
- Synced from llm_server_v3445.py

v5.440 Update (量价理论增强):
- P0: 形神分析法 (L2质量分增强)
  - 来源：量价理论第3集
  - 形不散(K线流畅度) + 神不散(成交量均衡)
  - 四种状态: 形神兼备/形散神聚/形不散神散/形神皆散
- P1: 双重底量价验证增强
  - 来源：量价理论第42集
  - 新增右底更圆润检测
- P3: MACD背驰检测 (L1趋势转折预警)
  - 来源：缠论第11集
  - 规则："无趋势无背驰" - 盘整中跳过
- NEW: OHLCV累积缓存 (解决CoinGecko数据不足问题)
- Synced from llm_server_v3440.py

v5.435 Update (trend_mid Force Rules):
- FORCE_DOWN_MID: Drop >= 30% forces dow_trend to DOWN
- FORCE_UP_MID: Rise >= 50% forces dow_trend to UP
- PRICE_OVERRIDE: 30-bar change >= 5% overrides SIDE judgment
- Background: v3.430 fixes only affected big-period(x4), not current period(mid)
- Synced from llm_server_v3435.py

v5.430 Update (Review-Driven Optimization):
- FORCE_DOWN rule: Drop >= 30% from 120-bar high forces DOWN trend
- Dynamic ADX threshold: Price change >= 5% lowers ADX threshold 25->15
- Strong stock protection: High position (>85%) + small pullback (<3%) protects as SIDE
- Synced from llm_server_v3430.py

v5.420 Update:
- Reversal pattern detection (Double Bottom/Top + Head-Shoulders)
- Pattern quality scoring (1-3)
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ============================================================================
# Core Configuration
# ============================================================================

DRY_RUN = True  # CRITICAL: Always True - No actual trading in cloud version

VERSION = "5.640"
SYSTEM_NAME = "AI PRO Trading System - Cloud Validation"

# ============================================================================
# Data Sources
# ============================================================================

DATA_SOURCES = {
    "stocks": "twelvedata",
    "crypto": "coingecko"
}

TWELVEDATA_CONFIG = {
    "api_key": os.getenv("TWELVEDATA_API_KEY", ""),
    "cache_ttl": 60,
    "timeout": 30,
}

COINGECKO_CONFIG = {
    "base_url": "https://api.coingecko.com/api/v3",
    "cache_ttl": 60,
    "timeout": 30,
}

# ============================================================================
# Supported Assets
# ============================================================================

DEFAULT_STOCKS = [
    "TSLA", "AAPL", "NVDA", "AMD", "COIN",
    "GOOGL", "AMZN", "META", "MSFT", "NFLX"
]

# Extended stock list (S&P 500 + NASDAQ 100 + Chinese ADRs)
AVAILABLE_STOCKS = [
    # ==================== Tech Giants ====================
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSLA",

    # ==================== Semiconductors ====================
    "AMD", "INTC", "AVGO", "QCOM", "MU", "AMAT", "LRCX", "KLAC", "MRVL", "ON",
    "TXN", "ADI", "NXPI", "MCHP", "SWKS", "QRVO", "MPWR", "ENTG", "TER", "ASML",
    "TSM",  # 台积电 - AI芯片代工龙头

    # ==================== AI Infrastructure (AI产业链) ====================
    # AI芯片/服务器
    "SMCI",  # Super Micro - AI服务器
    "ARM",   # ARM Holdings - AI芯片架构
    "ANET",  # Arista Networks - AI数据中心网络
    "VRT",   # Vertiv - AI数据中心电力/冷却
    # AI存储/内存
    "WDC", "STX",  # 已在Other板块，这里标记为AI相关
    # AI电力基础设施
    "VST",   # Vistra - AI数据中心电力
    "CEG",   # Constellation Energy - 核电/AI电力
    "OKLO",  # Oklo - 小型核反应堆/AI电力

    # ==================== Resources & Mining (资源类) ====================
    # 铜矿 (Copper) - AI/电力基础设施关键金属
    "FCX",   # Freeport-McMoRan - 全球最大铜矿
    "SCCO",  # Southern Copper - 南美铜矿龙头
    "TECK",  # Teck Resources - 加拿大矿业
    # 稀土/锂电 (Rare Earth/Lithium) - 电池/电动车
    "MP",    # MP Materials - 美国唯一稀土矿
    "ALB",   # Albemarle - 全球锂业龙头
    "LAC",   # Lithium Americas - 锂矿开发
    "SQM",   # Sociedad Química y Minera - 智利锂矿
    # 黄金 (Gold) - 避险资产
    "GOLD",  # Barrick Gold - 全球第二大金矿
    "NEM",   # Newmont - 全球最大金矿
    "AEM",   # Agnico Eagle - 加拿大金矿
    # 铀矿 (Uranium) - 核电/AI电力
    "CCJ",   # Cameco - 全球最大铀矿
    "UEC",   # Uranium Energy Corp - 美国铀矿
    # 综合矿业 (Diversified Mining)
    "BHP",   # BHP Group - 全球最大矿业
    "RIO",   # Rio Tinto - 全球第二大矿业
    "VALE",  # Vale - 巴西矿业/铁矿石
    # 钢铁 (Steel)
    "NUE",   # Nucor - 美国最大钢铁
    "CLF",   # Cleveland-Cliffs - 美国钢铁
    "X",     # United States Steel - 美国钢铁

    # ==================== Software & Cloud ====================
    "CRM", "ORCL", "ADBE", "NOW", "SNOW", "PLTR", "PANW", "CRWD", "ZS", "NET",
    "DDOG", "MDB", "TEAM", "WDAY", "SPLK", "VEEV", "ANSS", "CDNS", "SNPS", "INTU",
    "ZM", "DOCU", "OKTA", "TWLO", "HUBS", "TTD", "BILL", "PCTY", "PAYC", "SMAR",

    # ==================== Fintech & Payments ====================
    "V", "MA", "PYPL", "SQ", "COIN", "HOOD", "AFRM", "SOFI", "UPST", "LC",
    "FIS", "FISV", "GPN", "AXP", "COF", "DFS", "SYF",

    # ==================== E-commerce & Consumer ====================
    "NFLX", "DIS", "CMCSA", "ABNB", "BKNG", "UBER", "LYFT", "DASH", "SHOP",
    "EBAY", "ETSY", "W", "CHWY", "PTON", "ROKU", "SPOT", "PARA", "WBD", "FOX",

    # ==================== EV & Clean Energy ====================
    "RIVN", "LCID", "NIO", "XPEV", "LI", "ENPH", "SEDG", "FSLR", "RUN", "PLUG",
    "CHPT", "BLNK", "QS", "FFIE", "FSR", "GOEV", "WKHS", "NKLA",

    # ==================== Healthcare & Biotech ====================
    "JNJ", "UNH", "PFE", "ABBV", "MRK", "LLY", "BMY", "AMGN", "GILD", "MRNA", "BNTX",
    "REGN", "VRTX", "BIIB", "ILMN", "ISRG", "DXCM", "ALGN", "IDXX", "ZTS", "TMO",
    "DHR", "ABT", "MDT", "SYK", "BSX", "EW", "BDX", "CI", "CVS", "HUM", "CNC",

    # ==================== Banks & Finance ====================
    "JPM", "BAC", "WFC", "GS", "MS", "C", "BLK", "SCHW", "USB", "PNC", "TFC",
    "AIG", "MET", "PRU", "ALL", "TRV", "CB", "ICE", "CME", "SPGI", "MCO", "MSCI",

    # ==================== Industrial & Defense ====================
    "BA", "LMT", "RTX", "GE", "CAT", "DE", "HON", "UPS", "FDX", "UNP", "CSX",
    "NSC", "MMM", "ITW", "EMR", "ROK", "PH", "ETN", "IR", "AME", "GD", "NOC",

    # ==================== Retail ====================
    "WMT", "COST", "TGT", "HD", "LOW", "NKE", "SBUX", "MCD", "YUM", "DPZ", "CMG",
    "DLTR", "DG", "ROST", "TJX", "LULU", "GPS", "ANF", "AEO", "BBY", "KR", "SYY",

    # ==================== Oil & Gas ====================
    "XOM", "CVX", "COP", "SLB", "OXY", "EOG", "PXD", "DVN", "MPC", "VLO", "PSX",
    "HAL", "BKR", "FANG", "MRO", "APA", "HES",

    # ==================== Utilities & REITs ====================
    "NEE", "DUK", "SO", "D", "AEP", "EXC", "SRE", "XEL", "ED", "WEC",
    "AMT", "PLD", "CCI", "EQIX", "PSA", "DLR", "O", "WELL", "AVB", "SPG",

    # ==================== Consumer Staples ====================
    "PG", "KO", "PEP", "PM", "MO", "MDLZ", "CL", "KMB", "GIS", "K", "HSY",
    "KHC", "STZ", "TAP", "BF.B", "EL", "CHD",

    # ==================== Communication ====================
    "T", "VZ", "TMUS", "CHTR", "LBRDK",

    # ==================== Other S&P 500 ====================
    "BRK.B", "ACN", "IBM", "CSCO", "HPQ", "HPE", "DELL", "WDC", "STX",

    # ==================== 中概股 Chinese ADRs ====================
    "BABA", "JD", "PDD", "BIDU", "NTES", "BILI", "TME", "IQ", "VIPS", "TAL",
    "EDU", "GOTU", "DIDI", "LU", "FUTU", "TIGR", "YMM", "MNSO", "KC", "LEGN",
    "ZH", "DOYU", "HUYA", "WB", "QFIN", "FINV", "LX", "BZUN", "ATHM", "HTHT",
    "TCOM", "ZTO", "BGNE", "ZLAB", "IMAB", "BZ", "API", "DAO", "NIU", "XNET"
]

DEFAULT_CRYPTO = [
    {"id": "bitcoin", "symbol": "BTC"},
    {"id": "ethereum", "symbol": "ETH"},
    {"id": "solana", "symbol": "SOL"},
    {"id": "ripple", "symbol": "XRP"},
    {"id": "cardano", "symbol": "ADA"},
]

# Extended crypto list
AVAILABLE_CRYPTO = [
    {"id": "bitcoin", "symbol": "BTC", "name": "Bitcoin"},
    {"id": "ethereum", "symbol": "ETH", "name": "Ethereum"},
    {"id": "solana", "symbol": "SOL", "name": "Solana"},
    {"id": "ripple", "symbol": "XRP", "name": "XRP"},
    {"id": "cardano", "symbol": "ADA", "name": "Cardano"},
    {"id": "dogecoin", "symbol": "DOGE", "name": "Dogecoin"},
    {"id": "polkadot", "symbol": "DOT", "name": "Polkadot"},
    {"id": "avalanche-2", "symbol": "AVAX", "name": "Avalanche"},
    {"id": "chainlink", "symbol": "LINK", "name": "Chainlink"},
    {"id": "matic-network", "symbol": "MATIC", "name": "Polygon"},
    {"id": "litecoin", "symbol": "LTC", "name": "Litecoin"},
    {"id": "uniswap", "symbol": "UNI", "name": "Uniswap"},
    {"id": "stellar", "symbol": "XLM", "name": "Stellar"},
    {"id": "cosmos", "symbol": "ATOM", "name": "Cosmos"},
    {"id": "near", "symbol": "NEAR", "name": "NEAR"},
    {"id": "arbitrum", "symbol": "ARB", "name": "Arbitrum"},
    {"id": "optimism", "symbol": "OP", "name": "Optimism"},
    {"id": "aptos", "symbol": "APT", "name": "Aptos"},
    {"id": "sui", "symbol": "SUI", "name": "Sui"},
    {"id": "pepe", "symbol": "PEPE", "name": "Pepe"},
    {"id": "zcash", "symbol": "ZEC", "name": "Zcash"},
    {"id": "bitcoin-cash", "symbol": "BCH", "name": "Bitcoin Cash"},
    {"id": "tron", "symbol": "TRX", "name": "Tron"},
    {"id": "ethereum-classic", "symbol": "ETC", "name": "Ethereum Classic"},
    {"id": "filecoin", "symbol": "FIL", "name": "Filecoin"},
    {"id": "monero", "symbol": "XMR", "name": "Monero"},
    {"id": "hedera-hashgraph", "symbol": "HBAR", "name": "Hedera"},
    {"id": "internet-computer", "symbol": "ICP", "name": "Internet Computer"},
    {"id": "vechain", "symbol": "VET", "name": "VeChain"},
    {"id": "aave", "symbol": "AAVE", "name": "Aave"},
]

CRYPTO_ID_MAP = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "XRP": "ripple",
    "ADA": "cardano",
    "DOGE": "dogecoin",
    "DOT": "polkadot",
    "AVAX": "avalanche-2",
    "LINK": "chainlink",
    "MATIC": "matic-network",
    "LTC": "litecoin",
    "UNI": "uniswap",
    "XLM": "stellar",
    "ATOM": "cosmos",
    "NEAR": "near",
    "ARB": "arbitrum",
    "OP": "optimism",
    "APT": "aptos",
    "SUI": "sui",
    "PEPE": "pepe",
    "ZEC": "zcash",
    "BCH": "bitcoin-cash",
    "TRX": "tron",
    "ETC": "ethereum-classic",
    "FIL": "filecoin",
    "XMR": "monero",
    "HBAR": "hedera-hashgraph",
    "ICP": "internet-computer",
    "VET": "vechain",
    "AAVE": "aave",
}

# ============================================================================
# Timeframes
# ============================================================================

SUPPORTED_TIMEFRAMES = {
    "5m": {"minutes": 5, "display": "5 Min"},
    "10m": {"minutes": 10, "display": "10 Min"},
    "15m": {"minutes": 15, "display": "15 Min"},
    "30m": {"minutes": 30, "display": "30 Min"},
    "1h": {"minutes": 60, "display": "1 Hour"},
    "2h": {"minutes": 120, "display": "2 Hours"},  # v5.445: Added
    "4h": {"minutes": 240, "display": "4 Hours"},
    "1d": {"minutes": 1440, "display": "Daily"},
}

DEFAULT_TIMEFRAME = "30m"

# ============================================================================
# v5.445: Per-Symbol Timeframe Configuration (Trading Cycle Minutes)
# ============================================================================

SYMBOL_TIMEFRAMES = {
    # Crypto (trading in cloud uses symbol without USDC suffix)
    "ZEC": 60,      # 1 hour
    "BTC": 120,     # 2 hours
    "ETH": 120,     # 2 hours
    "SOL": 120,     # 2 hours
    # With USDC suffix (for compatibility)
    "ZECUSDC": 60,
    "BTCUSDC": 120,
    "ETHUSDC": 120,
    "SOLUSDC": 120,
    # US Stocks (4 hours)
    "TSLA": 240,
    "COIN": 240,
    "RDDT": 240,
    "NVDA": 240,
    "AMD": 240,
    "GOOGL": 240,
    "AMZN": 240,
    "META": 240,
    "AAPL": 240,
    "MSFT": 240,
    "NFLX": 240,
    "PLTR": 240,
    # Default for other stocks: 240 (4 hours)
}

def get_symbol_timeframe(symbol: str) -> int:
    """v5.445: Get trading cycle for symbol (minutes)"""
    return SYMBOL_TIMEFRAMES.get(symbol, 240 if symbol.isupper() and len(symbol) <= 5 else 60)

# ============================================================================
# Email Notifications
# ============================================================================

EMAIL_ENABLED = os.getenv("EMAIL_ENABLED", "true").lower() == "true"
EMAIL_SMTP_SERVER = os.getenv("EMAIL_SMTP_SERVER", "smtp.gmail.com")
EMAIL_SMTP_PORT = int(os.getenv("EMAIL_SMTP_PORT", "587"))
EMAIL_SENDER = os.getenv("EMAIL_SENDER", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
EMAIL_RECIPIENT = os.getenv("EMAIL_RECIPIENT", "")

# ============================================================================
# DeepSeek AI Configuration (Arbitration Module)
# ============================================================================

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_ENABLED = bool(DEEPSEEK_API_KEY)
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEEPSEEK_MODEL = "deepseek-chat"

# ============================================================================
# User System Configuration
# ============================================================================

USER_MAX_COUNT = 500  # v5.435: Increased from 100 to 500
USER_MAX_EXPANDABLE = 1000  # Maximum expandable
USER_DB_PATH = os.path.join(os.path.dirname(__file__), "users", "users.json")
SESSION_SECRET = os.getenv("SESSION_SECRET", "ai-pro-secret-key-change-in-production")
SESSION_LIFETIME_HOURS = 24

# ============================================================================
# Server Configuration
# ============================================================================

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

# ============================================================================
# Logging
# ============================================================================

LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# ============================================================================
# Analysis Parameters (Synced from v3.493)
# ============================================================================

ANALYSIS_CONFIG = {
    # L1 Trend Analysis
    "l1_lookback": 120,  # v3.430: Increased for FORCE_DOWN calculation
    "adx_period": 14,
    "adx_threshold": 22,  # v3.491: Base threshold for stocks (lowered from 25)
    "adx_strong_threshold": 30,

    # v3.491: Crypto-specific ADX threshold (lower than stocks due to 24h trading noise)
    "crypto_adx_threshold": 15,  # v3.491: Crypto uses 15 (lowered from 20)

    # v3.493: Price force threshold (trigger forced trend judgment)
    "crypto_price_force_threshold": 5.0,  # Crypto: 5% price change forces UP/DOWN
    "stock_price_force_threshold": 8.0,   # Stock: 8% price change forces UP/DOWN

    # v3.493: Dynamic ADX threshold trigger
    "crypto_dynamic_adx_trigger": 3.0,    # Crypto: 3% price change lowers ADX threshold
    "stock_dynamic_adx_trigger": 5.0,     # Stock: 5% price change lowers ADX threshold
    "dynamic_adx_low_threshold": 12,      # v3.493: Lowered ADX threshold when triggered

    # v3.493: DOW-Swing parameters (Dow Theory standard)
    "dow_n_swing": 2,       # Number of swing points to identify (2 peaks + 2 troughs)
    "dow_min_swings": 2,    # Minimum swings required to confirm trend

    # v3.493: Side fallback threshold
    "side_fallback_threshold": 5.0,  # Overall trend >= 5% overrides SIDE judgment

    # v3.430: FORCE_DOWN rule
    "force_down_lookback": 120,  # K-bars to check for highest price
    "force_down_threshold": 30.0,  # Drop % threshold to force DOWN

    # v3.430: Strong stock protection
    "strong_stock_high_position": 0.85,  # Position > 85% considered high
    "strong_stock_max_pullback": 3.0,  # Pullback < 3% considered small

    # Dow Theory
    "swing_point_window": 5,
    "dow_lookback": 20,

    # L2 Signal Analysis
    "l2_lookback": 50,
    "rsi_period": 14,
    "rsi_overbought": 70,
    "rsi_oversold": 30,

    # Volume Analysis (v3.160 Wyckoff)
    "volume_ma_period": 20,
    "volume_spike_threshold": 1.5,
    "volume_climax_threshold": 2.5,

    # Grid Module
    "grid_lookback": 20,
    "zhongshu_min_bars": 3,

    # DeepSeek Arbitration
    "deepseek_trigger_confidence_diff": 0.15,
    "deepseek_timeout": 30,
}

# ============================================================================
# i18n Configuration
# ============================================================================

DEFAULT_LANGUAGE = "en"
SUPPORTED_LANGUAGES = ["en", "zh"]
