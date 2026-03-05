"""
AIPRO 决策层监控 v3.610

v3.610更新:
  - L2 recommendation显示: 在L2列旁显示扫描引擎L2空间确认状态(SB/B/H/S/SS)
  - per-cycle GTS缓存: 避免N+1文件读取
  - 配合: 主程序v3.610 + 扫描引擎v21 + Vision v2.9

v3.600更新:
  - 动态周期自适应: 从timeframe_params读取品种周期参数
  - 配合: 主程序v3.600 + 扫描引擎v20 + Vision v2.8

v3.590更新:
  - Position Control状态显示:
    * 显示当前仓位 (0-5)
    * 显示Position Control模式 (EMA10过滤/共振要求)
    * 同步: 主程序v3.590 + 扫描引擎v17.3

v3.572更新:
  - 扫描引擎顺大逆小策略显示:
    * print_global_trend_status()改版: 显示当前趋势+x4大周期+顺大逆小策略
    * 新增列: x4大周期趋势、允许交易方向、数据状态
    * 策略逻辑: x4=UP→仅BUY | x4=DOWN→仅SELL | 反转检测→跟随当前
    * 数据状态: 正常(绿) / 待同步(红，需重启主程序)
  - 同步: 主程序v3.572 + 扫描引擎v16.9

v3.570更新:
  - Vision趋势分析器(观察模式):
    * 新增print_vision_daily_report()面板: 每日L1 vs Vision准确率对比(纽约8AM更新)
    * 新增print_vision_status()面板: Vision最近分析状态(verbose模式)
    * 扩展print_regime_accuracy(): 新增V当前/V-X4准确率列
    * 每日报告保存: logs/vision_report_YYYYMMDD.txt
  - 同步: 主程序v3.570 + 扫描引擎v16.1

v3.565更新:
  - MACD背离外挂从主程序移交扫描引擎:
    * 主程序不再实时处理MACD背离 (ENABLE_MACD_DIVERGENCE_PLUGIN=False)
    * 扫描引擎新增_scan_macd_divergence(), 15分钟周期
    * 仅在震荡市(RANGING)激活，与原逻辑一致
    * 新增get_15m_ohlcv()数据获取 (替代原10分钟)
  - 同步: 主程序v3.565 + 扫描引擎v16.1

v3.560更新:
  - 全系统修复升级 (P0×3 + P1×11 + P2×10):
    * P0: SELL状态更新 + 原子写 + 纽约时间修正
    * P1: open_buys/FIFO/内存读取/统一仓位/重试/日志轮转
    * P2: 冷却标识/异常处理/3commas重试/缓存TTL/优雅退出
  - 同步: 主程序v3.560 + 扫描引擎v16.0

v3.550更新:
  - 鲁本威科夫知识应用到L1/L2系统:
    * L1增强: VPOC迁移验证 + 价值区域重叠检测
    * L2增强: 假突破"无法重入"规则 + 累积/分配量能特征
    * 评分内部优化 (总分±22不变)
  - 同步: 主程序v3.550 + 扫描引擎v15.0

v3.545更新:
  - L1外挂移交扫描引擎 (配合主程序v3.545 + 扫描引擎v15):
    * Rob Hoffman: 移交扫描引擎，主程序移除调用
    * 双底双顶: 移交扫描引擎，主程序移除调用
    * 飞云双突破: 移交扫描引擎，主程序移除调用
  - v3.565: MACD背离也移交扫描引擎:
    * MACD背离: 移交扫描引擎，15分钟周期，仅震荡市激活
  - 同步: 主程序v3.545 + 扫描引擎v15.0

v3.540更新:
  - 新增全局趋势状态显示 (配合主程序v3.540 + 扫描引擎v14):
    * 新增print_global_trend_status(): 显示全局趋势同步状态
    * 读取global_trend_state.json显示各品种趋势+市况
    * 显示: 品种 + 趋势方向(UP/DOWN/SIDE) + 市况(TRENDING/RANGING)
    * 最后更新时间 + 趋势变化原因
  - 新增GLOBAL_TREND_STATE_FILE常量
  - 同步: 主程序v3.540 + 扫描引擎v14.0

v3.530更新:
  - 外挂触发时机规范化 (配合扫描引擎v13):
    * 剥头皮5分钟周期触发控制: 每根K线只触发一次单向操作
    * 新增scalping_cycle_state状态管理
    * 防止同一周期内重复触发信号
  - SuperTrend外挂集成到扫描引擎:
    * 新增SUPERTREND_SCAN_STATE_FILE常量
  - 统一外挂状态显示:
    * 新增print_all_plugin_status(): 统一显示所有外挂触发状态
    * 扫描引擎触发: P0-Tracking / 剥头皮 / SuperTrend
    * L1层触发: SuperTrend / RobHoffman / 双底双顶 / 飞云 / MACD背离
    * 显示: 外挂名称 + 触发信号 + 触发时间 + 冻结剩余时间
    * 新增L1_PLUGIN_STATE_FILE常量和get_l1_plugin_state()函数
  - 同步: 主程序v3.530 + 扫描引擎v13.0

v3.520更新:
  - L2评分体系重构:
    * 5大类评分: 形态±6 + 唐纳奇综合±8 + 量能±2 + Wyckoff±2 + 每日偏向±2 + Vegas±2 = ±22
    * 合并唐纳奇综合分: 位置±4 + 突破/震荡±3 + 趋势强化±1 = ±8
    * 新增Vegas隧道分: EMA 144/169位置确认 (±2)
  - 新阈值设计 (L2只做最强信号):
    * STRONG_BUY ≥ +10 (45%)
    * BUY ≥ +6 (27%)
    * HOLD -5 ~ +5 (45%范围)
    * SELL ≤ -6
    * STRONG_SELL ≤ -10
  - 预计算缓存扩展:
    * PrecomputedIndicators新增: ema_144, ema_169
  - 同步: 主程序v3.520

v3.510更新:
  - L1日志完善性增强:
    * Donchian突破/跌破日志已有
    * 新增DeepSeek仲裁触发日志[v3.510]
    * 新增五模块共识失败日志[v3.510]
    * 新增仓位门控生效日志[v3.510]
    * 新增执行结果反馈日志[v3.510]
  - 邮件格式统一:
    * format_email_subject_v3510(): 统一标题格式
    * send_trend_change_email_v3510(): 趋势转折提醒邮件
  - 双底双顶外挂:
    * double_pattern_plugin.py: 独立形态检测外挂
    * 双底仅在下跌/低位触发，双顶仅在上涨/高位触发
  - 外挂并行检查模式:
    * 所有外挂独立检查，激活结果收集到列表
    * 选择第一个激活的执行，无优先级
  - 预计算缓存优化:
    * PrecomputedIndicators: 缓存道氏x4/x8、120高低点、ADX等
    * TV webhook和后台更新时触发预计算
    * llm_decide使用缓存减少重复计算
  - 同步: 主程序v3.510

v3.501更新:
  - 唐纳奇突破/跌破验证机制:
    * BreakoutState类新增字段: fallback_count, already_handled, last_breakout_failed, trend_strengthened
    * check_small_cycle_breakout_validation(): 小周期验证(连续2根K线确认)
    * 突破模式: close > upper → +3分, 小周期监控站稳/跌回
    * 跌破模式: close < lower → -3分, 小周期监控站稳/反弹
    * 震荡模式: 低买高卖 (pos<25% → +2, pos>75% → -2)
    * 突破失败: 连续2根小周期跌回 → 触发反向信号(SELL/BUY)
    * 失败后下一大周期强制震荡模式
    * 验证成功后标记趋势强化(额外±1分)
    * 6大类总分范围: -20 ~ +20
  - 同步: 主程序v3.501

v3.499更新:
  - 唐纳奇通道策略强化 - L2位置确认反馈到L1:
    * DonchianState类: 跟踪位置稳定性(连续高位/低位计数)
    * update_donchian_state(): 更新位置状态
    * apply_donchian_strategy(): 生成策略评分(±3)
    * apply_donchian_feedback_to_l1(): L1趋势判断反馈修正
    * L2评分新增第5类: 唐纳奇通道分(±3)
    * 5大类总分范围: -17 ~ +17 (原-14~+14)
  - 同步: 主程序v3.499

v3.498更新:
  - HOLD时门卫开放让L1外挂决策:
    * 当L2大周期=HOLD时，门卫不关闭，开放双向
    * L1外挂(SuperTrend/飞云/Rob Hoffman)自己判断趋势
    * 震荡市场可能变成趋势，L1外挂有自己的趋势过滤逻辑
  - 同步: 主程序v3.498

v3.497更新:
  - 美股成本价格高抛低吸策略:
    * get_avg_cost_price(): 计算平均成本价格
    * get_cost_reduction_score_adj(): 成本拉低策略评分调整
    * 浮亏+低位: +1分加仓拉低成本
    * 浮亏+高位: -1分减仓止损
    * 浮盈+高位: -1分锁定利润
  - 同步: 主程序v3.497

v3.496更新:
  - 美股盈亏动态策略调整:
    * get_pnl_level(): 根据1月累计盈亏计算级别(normal/warning/severe)
    * get_max_position_units(): 严重亏损股票仓位上限降至1单位
    * Wyckoff阶段覆盖:
      - severe(亏损>35%): 只允许低位(<30%)买入，其他强制DISTRIBUTION
      - warning(亏损20-35%): 强制高抛低吸，忽略L1趋势
    * L2评分调整: 正常亏损股票高位(>70%)额外-1分促进卖出
  - 同步: 主程序v3.496

v3.495更新:
  - MACD背离外挂显示:
    * 监控面板新增MACD背离状态区域
    * 显示背离类型、强度、止损止盈
    * 告警面板新增背离触发告警
  - 同步: 主程序v3.496 + macd_divergence_plugin.py v0.1

v3.493更新:
  - L1趋势判断修复 (道氏理论专业标准):
    * x4 DOW-Swing参数: n_swing=3→2, min_swings=3→2 (2个波峰+2个波谷确认趋势)
    * x4整体趋势兜底: DOW-Swing返回side时，整体变化>=5%判定方向
    * Tech ADX强制判定: ADX>=40+价格方向 → 强制判定TREND_UP/DOWN
    * Tech ADX中等判定: ADX>=25+价格变化>=3% → 判定方向
  - 专业技术分析标准:
    * 道氏理论: 2个完整的波峰波谷序列即可确认趋势方向
    * ADX指标: >40极强趋势，>25中等趋势，<25震荡
  - 启动时自动刷新L1:
    * 服务器启动后自动对所有品种(4加密+10美股=14个)运行完整L1分析
    * 新版本上线后立即使用新算法，不需要等待大周期推送
  - 手动刷新API端点:
    * GET/POST /refresh_l1 - 刷新所有14个品种
    * GET/POST /refresh_l1?symbol=ZECUSDC - 只刷新指定品种
    * GET/POST /refresh_l1?symbol=TSLA - 美股也支持
  - 同步: 主程序v3.493

v3.492更新:
  - L2量价异常检测 (来源: 量价理论第20-29集、第43-44集):
    * 巨量十字星检测: 高位+十字星+巨量(>=2倍均量) → 危险信号
    * "头上三柱香"检测: 连续>=3根长上影线(>实体*2) → 强烈看跌
    * 脉冲量陷阱检测: 单根>=3倍均量+后续无量堆 → 诱多陷阱
    * 量堆式下跌风险: 连续下跌+放量趋势 → 暂停BUY
    * 平衡量过滤器: 量能CV>0.6 → 信号可靠性下降
    * 高位巨量阴线: 高位+巨量+跌>=3% → 强烈卖出信号
  - 形态量价背离增强 (配合v3.420形态外挂):
    * 双重顶量价背离: 右峰缩量<左峰70% → 增强SELL
    * 头肩顶量能衰竭: 量能依次递减 → 增强SELL
    * 巨量吞噬线验证: 量能>=1.5倍均量才有效
  - 评分调整机制:
    * buy_penalty: 量价异常时惩罚买入信号(0-6分)
    * sell_bonus: 量价异常时增强卖出信号(0-6分)
  - 同步: 主程序v3.492

v3.491更新:
  - ADX阈值优化:
    * 加密货币: 20→15 (24h交易波动大,ADX天然偏低)
    * 美股: 25→22 (高位时ADX衰减导致判SIDE)
  - 价格强制判断趋势:
    * 30根K线价格变化>=10%时,强制判断UP/DOWN方向
    * 不再依赖ADX值,解决明显趋势被判SIDE问题
  - 位置-阶段一致性检查:
    * 极低位(pos<0.15)+大跌>=10% → MARKDOWN(非ACCUMULATION)
    * 极高位(pos>0.85)+大涨>=10% → MARKUP(非DISTRIBUTION)
  - 同步: 主程序v3.491

v3.490更新:
  - 代码复查 (code-simplifier):
    * 验证v3.488 L2 Gate时序修复正确性
    * 验证v3.487 Wyckoff稳定性功能正确性
    * 检查代码简洁性和一致性
  - 同步: 主程序v3.490

v3.487更新:
  - P0-1: Wyckoff阶段确认机制 (防止ZEC等品种阶段跳变)
    * 连续2根K线确认才切换阶段
    * 阶段切换时输出confirm_count便于调试
  - P0-2: 短期回调企稳检测 (见底仍SELL问题)
    * 检测从近10根K线高点的回调幅度
    * 回调>5% + 企稳K线(锤子/十字星/长下影) → 暂停SELL
  - P1-3: MARKUP_PULLBACK子状态 (回调识别延迟)
    * MARKUP + 连续2根阴线 → sub_state="PULLBACK"
    * MARKDOWN + 连续2根阳线 → sub_state="RALLY"
    * 子状态时降低反向交易权重50%
  - P1-4: 底部反转保护 (RSI/K线保护)
    * RSI < 30 (超卖) → 阻止SELL
    * 看涨吞没K线 → 阻止SELL
    * 锤子线 → 阻止SELL
  - P2-5: UNCLEAR阶段Wyckoff分归零
    * UNCLEAR阶段直接返回wyckoff_score=0
  - P2-6: 双周期位置确认
    * 计算20根K线的短期位置
    * 长期UPPER_HALF + 短期LOWER_HALF = "PULLBACK_IN_UPTREND" → SELL权重-30%
    * 长期LOWER_HALF + 短期UPPER_HALF = "RALLY_IN_DOWNTREND" → BUY权重-30%
  - 同步: 主程序v3.487

v3.485更新:
  - L1纯x4定位Wyckoff阶段 (原始设计: L1大周期判断位置):
    * trend_x4=UP → MARKUP (上涨期)
    * trend_x4=DOWN → MARKDOWN (下跌期)
    * trend_x4=SIDE + pos<30% → ACCUMULATION (吸筹期)
    * trend_x4=SIDE + pos>70% → DISTRIBUTION (派发期)
    * trend_x4=SIDE + 中间位置 → RANGING (震荡期)
  - L2评分扩展为4大类:
    * 形态分(±6): PA + 2B + 123 + K线形态, Donchian位置乘数
    * 位置分(±4): TV pos_in_channel直接映射
    * 量能分(±2): 量价配合验证
    * Wyckoff策略分(±2): 形态与Wyckoff阶段匹配度
  - 总分范围: -14 ~ +14
  - 5档信号: STRONG_BUY≥7 | BUY≥4 | HOLD[-3,+3] | SELL≤-4 | STRONG_SELL≤-7
  - 同步: 主程序v3.485

v3.470更新:
  - TradingView信号数据增强 (Pine Script v3):
    * Donchian通道: donchian_upper/lower/basis, pos_in_channel
    * EMA20: ema20, ema_trend(up/down/flat), price_above_ema
    * MACD(12,26,9): macd_line/signal/hist/trend, macd_cross_over/under
    * 布林带(20,2σ): bb_upper/lower/basis, bb_width_pct, pos_in_bb, bb_squeeze
    * 其他: atr14, vol_ratio
  - 新字段传递到L1三方协商用于增强判断
  - 同步: 主程序v3.470

v3.465更新:
  - P1改善项 (来源: 知识卡片):
    * P1-1: 20 EMA趋势过滤器 (THE 20 EMA)
      - 价格>EMA+斜率向上→BULLISH, 价格<EMA+斜率向下→BEARISH
      - 回调信号: 价格接近EMA(±1%) + 趋势明确
    * P1-2: Power Candle力量K线检测 (THE POWER CANDLE)
      - Bullish: HIGH=CLOSE+上影线<5%+实体>=60%
      - Bearish: LOW=CLOSE+下影线<5%+实体>=60%
      - 强度等级: 1-3级 (基于实体比例)
    * P1-3: 量堆式拉升检测 (量价理论第29集)
      - 连续3根以上K线成交量>平均×1.2
      - 动能强度: MODERATE/STRONG/VERY_STRONG
      - 脉冲量警告: 单根>=3x均量
  - 云端函数: l2_analysis.py
  - 同步: 主程序v3.465

v3.460更新:
  - L2大小周期门卫机制:
    * 大周期STRONG_BUY时 → 允许小周期BUY/STRONG_BUY交易一次
    * 大周期STRONG_SELL时 → 允许小周期SELL/STRONG_SELL交易一次
    * 交易后冻结 → 直到下一个大周期信号
    * 小周期评分: K线形态(-1~+1) + RSI位置(-2~+2) + 动量(-2~+2)
    * 状态存储: l2_gate_state.json
  - 新增显示: L2 Gate状态面板
  - 同步: 主程序v3.460

v3.455更新:
  - L2打分重构 + K线形态分:
    * 总分范围压缩: -22~+22 → -12~+12
    * 新增K线形态分: -1~+1 (大阳/锤子+1, 大阴/射击星-1, 十字星0)
    * 形态分压缩: PA/2B/123总和 -5~+5 → -3~+3
    * 位置分压缩: -3~+3 → -2~+2
    * 趋势分压缩: -3~+3 → -2~+2
    * 辅助分项压缩: 量能/市场状态/背离/极端量 各压缩到±1
    * 行神分移除(合并到K线形态)
    * STRONG阈值不变(≥6/≤-6)，但占比从27%→50%
  - 同步: 主程序v3.455

v3.450更新:
  - P0-CycleSwitch (周期切换立即完整分析):
    * 触发: 任何周期切换都触发完整三方协商分析
    * 流程: 预加载OHLCV → Tech+Human信号 → DeepSeek仲裁 → BUY/HOLD/SELL
    * 交易: 正常执行 (无特殊阈值)
    * 邮件: 正常发送 (标识来源P0-CycleSwitch)
    * 目的: 切换周期后立即得到交易建议，不等待下次TradingView推送
  - 同步: 主程序v3.450

v3.445更新:
  - 品种独立周期配置 (解决混周期K线问题):
    * 问题: 所有品种使用相同MAIN_TIMEFRAME=30min预加载
    * 实际: ZEC=1h, BTC/ETH/SOL=2h, 美股=4h
    * 解决: SYMBOL_TIMEFRAMES字典配置品种独立周期
    * 预加载: Coinbase支持2h(7200s), yfinance支持2h/4h interval
  - 同步: 主程序v3.445

v3.441更新:
  - FORCE_DOWN恢复检测 (解决大跌后企稳误判问题):
    * 问题: NBIS/OPEN大跌后企稳/反弹，但仍被判DOWN
    * 解决: 检测恢复条件，满足则判RANGING而非DOWN
    * 恢复条件1: 从30bar低点反弹>=10%
    * 恢复条件2: 连续3根收盘价上涨
  - 显示增强: 当前趋势列显示RECOVERY标记
  - 同步: 主程序v3.441

v3.435更新:
  - trend_mid强制规则 (解决当前周期误判问题):
    * P0-1: FORCE_DOWN_MID - 跌幅>=30%强制trend_mid判DOWN (解决COIN-40%判SIDE)
    * P0-2: FORCE_UP_MID - 涨幅>=50%强制trend_mid判UP (解决RKLB+152%判SIDE)
    * P1: PRICE_OVERRIDE - 30bar价格变化>=5%覆盖道氏side (解决BTC+7%判SIDE)
  - 背景: v3.430修复只影响大周期x4，不影响当前周期mid
  - 同步: 主程序v3.435

v3.430更新:
  - 复盘驱动优化 (解决L1x4准确率50%问题):
    * P0: FORCE_DOWN规则 - 跌幅>=30%强制判DOWN (解决COIN-38%/OPEN-40%被判UP)
    * P1: 动态ADX阈值 - 价格变化>=5%时ADX阈值25→15 (解决BTC+6.6%被判SIDE)
    * P2: 强势股保护 - 高位>85%+小回调<3%时cur保持SIDE (避免小幅回调误判DOWN)
  - 同步: 主程序v3.430

v3.420更新:
  - 形态外挂检测 (双重底/顶 + 头肩底/顶):
    * 检测反转形态: W底、M头、头肩底、头肩顶
    * 质量评分1-3: 考虑量能配合、颈线突破、回踩确认
    * 买入形态(W底/头肩底)加分，卖出形态(M头/头肩顶)减分
  - 告警面板新增形态外挂告警
  - 同步: 主程序v3.420

v3.400更新:
  - L2大周期形态质量评分:
    * D1: PIN_BAR质量评分 (完美/标准/变形)
    * D2: 吞没力度评分 (吞没倍数+放量确认)
    * D3: 2B速度验证 (急速2B/普通2B/慢速2B)
    * D4: 假突破质量判断 (突破幅度+回落速度+量能)
  - L2小周期(10m)OHLCV完整分析:
    * M1: V型底用真实Low找极值点
    * M2: 微结构加量能验证+射击之星/锤子线检测
    * M3: 动量分析加影线分析 (长上影扣分)
    * M4: 路径分析加量能确认 (反弹放量加分)
  - 同步: 主程序v3.400

v3.390更新:
  - P0修复: L1预计算也调用DeepSeek趋势仲裁
    * 修复L2收到错误big_trend=SIDE导致顺大逆小失效
  - DeepSeek摆点优化: 使用Swing Point道氏理论判断x4趋势
    * 优先于ADX阈值，解决ADX<25误判为SIDE的问题
  - x4聚合修复: 先aggregate_ohlc聚合成x4周期再计算道氏理论
  - 冻结周期显示: P0追踪面板冻结状态显示剩余时间
    * 例如: 冻结(5h30m) 表示还剩5小时30分钟解冻
  - 同步: 主程序v3.390

v3.380更新:
  - 当前趋势显示: Human模块新增current_trend字段 (UP/DOWN/SIDE)
    * 与big_trend格式统一，方便顺大逆小判断
    * big_trend=x4大周期趋势, current_trend=当前周期趋势
  - 监控面板: Step1表格新增"当前趋势"列
    * UP=绿色, DOWN=红色, SIDE=黄色
  - 同步: 主程序v3.380

v3.370更新:
  - 顺大逆小修复: big_small_pattern从L1预计算结果正确计算
    * BIG_UP+PULLBACK → BIG_UP_SMALL_PULLBACK → WAIT_PULLBACK_EXHAUST策略
    * BIG_DOWN+BOUNCE → BIG_DOWN_SMALL_BOUNCE → WAIT_BOUNCE_EXHAUST策略
    * 符合顺大逆小时L2多头/空头形态额外+3分
  - L2阈值统一: >=5/>=2 改为 >=6/>=3 (与merge_to_exec_bias_ohlcv一致)
  - L2降级追踪: 新增l2_veto_applied/l2_original_exec_bias/l2_downgrade_desc字段
  - 监控显示: L2列降级时显示↓标记，告警面板显示降级详情
  - 废弃函数标注: compute_l2_exec_bias_advanced, compute_l2_exec_bias
  - P3规则解释改进: 添加趋势信息说明拒绝原因
  - 同步: 主程序v3.370

v3.360更新:
  - L1趋势条件激活扫描引擎
  - 扫描逻辑: UP趋势→只买入, DOWN趋势→只卖出, 震荡→暂停

v3.340更新:
  - P0修复: 三方协商reason提取改进 (extract_reason_with_rfr)
    * 依次检查顶层reason、嵌套decision.reason、reason_bullets
    * 确保REAL_FIRST_REACTION正确提取
  - P1修复: LLM请求添加30秒超时防止阻塞
  - P2修复: 调试日志统一使用log_to_server

v3.330更新:
  - DeepSeek趋势仲裁: AI+Tech分歧时调用DeepSeek判断趋势/震荡
  - 五模块框架完善:
    * AI+Tech一致 → 确认趋势 → Human主导(顺大逆小)
    * AI+Tech分歧 → DeepSeek仲裁 → 根据结果选择Human或Grid主导
  - 新增函数: call_deepseek_trend_arbiter_v3330()
  - 同步: 主程序v3.330

v3.320更新:
  - 修复ADX/Chop数据路径: tech_signals.raw.chop (不是choppiness)
  - 修复五模块数据保存: v3300_five_module现在正确保存到state.json
  - 修复monitor显示路径: tech_module.detail.xxx, grid_module.detail.relative_pos
  - AI+Tech双重验证: 两源一致才确认趋势，不一致默认震荡
  - 同步: 主程序v3.320

v3.310更新:
  - AI+Tech双重验证判断趋势/震荡
  - consensus: AGREE(一致)/DISAGREE(不一致)/TECH_ONLY(AI无效时兜底)

v3.300更新:
  - L1五模块重构: AI顺大/Human逆小/Tech强度/Grid位置/DeepSeek仲裁
    * AI模块(compute_ai_big_trend_v3300): 大周期趋势判断(x4/x8/trend120)
    * Human模块(compute_human_phase_v3300): 逆小阶段判断
    * Tech模块(compute_tech_strength_v3300): ADX/Choppiness强度验证
    * Grid模块(compute_grid_position_v3300): 箱体位置判断
    * 决策矩阵(compute_l1_decision_matrix_v3300): 五模块组合输出5信号
  - 同步: 主程序v3.300

v3.290更新:
  - 13买卖点L2增强: 对标云聪13买卖点体系
    * 增强2B检测(detect_2b_strict): 五浪验证+大阳线验证+立即性检查
    * 增强二次测试(detect_secondary_test): PA与支撑位联动
    * 增强SOS(detect_sos_strict): 形态中轴+放量大阳确认
    * 增强123(detect_123_with_volume): 突破放量确认
  - L2打分系统接入增强信号:
    * compute_13_buypoints_score(): 综合计算增强信号得分
    * 增强信号最多影响±3分
    * 新增score_breakdown字段: v3290_buypoints
  - 同步: 主程序v3.290

v3.280更新:
  - Swing Point道氏理论: 摆动点识别过滤盘整噪音
    * 问题: v3.260道氏理论要求连续3次HH+HL，波浪式趋势被误判为SIDE
    * 解决: 用Swing Point找出真正的波峰波谷再比较
    * 摆动高点: 左右各2根的High都比它低
    * 摆动低点: 左右各2根的Low都比它高
    * 效果: 自动过滤"阳线-盘整-阳线"中间的噪音
  - 新增函数:
    * find_swing_points(): 识别摆动高点和摆动低点
    * compute_trend_dow_swing(): 基于摆动点的道氏理论判断
  - 回退机制: 数据不足时自动回退到v3.260逐K线比较
  - 同步: 主程序v3.280

v3.270更新:
  - 威科夫4核心模块整合Grid门控
  - 同步: 主程序v3.270

v3.260更新:
  - 道氏理论趋势判断: 替代slope+weighted_dr
    * 核心: 连续3次HH+HL=UP, 连续3次LH+LL=DOWN, 其他=SIDE
    * 优势: 更快响应趋势转变，使用4根K线判断
  - Human模块改动:
    * 从ohlcv_window获取highs/lows数据
    * 多周期(mid/x4/x8)统一使用道氏理论
  - DeepSeek模块改动:
    * prompt添加道氏理论判断结果
    * 仲裁时道氏理论权重+40%
  - 同步: 主程序v3.260

v3.250更新:
  - P0-1a修复: chop字段名不匹配
  - P0-1b修复: rsi字段不存在于raw中
  - SuperTrend外挂v0.8.1: 快速趋势响应

v3.245更新:
  - P0-1修复: tech_indicators数据源修复
    * 问题: ACTION_LOG中tech_indicators永远是adx=0,chop=50,rsi=50
    * 根因: tech_signals变量作用域错误('tech_signals' in locals()永远False)
    * 修复: 从l1_unified["components"]["tech"]["raw"]获取正确数据
  - P0-2修复: trend_mid数据源修复
    * 问题: ACTION_LOG中trend_mid永远是"side"
    * 根因: 本地trend_mid被平滑逻辑改写，DeepSeek使用的是正确数据源
    * 修复: 从l1_unified["components"]["human"]["visual_slope"]获取
  - 同步: 主程序v3.245

v3.241更新:
  - P0改善实施: 5模块核心改进
  - T1: ACTION_LOG新增tech_indicators (adx/chop/rsi)
  - T2: ADX阈值 25→20，提高趋势识别灵敏度
  - H1: 动态slope阈值 - BTC 0.2%, 小币 0.5%, 股票 0.3%
  - G1: pa_edge=NONE时不再降级置信度
  - D1/D2: DeepSeek仲裁结果追踪和触发频率统计
  - 新增: DEEPSEEK_STATS全局统计 + compute_trend_v13()动态阈值版
  - 同步: 主程序v3.241

v3.240更新:
  - L1趋势判断核心修复: 加权方向比率(方案B)
  - 新增: _weighted_dir_ratio() - 按涨跌幅度加权
  - 新增: compute_trend_v12() - 双重条件趋势判断
  - 效果: BTC 94k→91k(-3%) 正确判断为DOWN（之前SIDE）
  - 同步: 主程序v3.240

v3.230更新:
  - Rule D修复: 移除l1_action条件检查，顺大逆小保护始终生效
  - 规则E新增: SIDE市场3小时冷却期(加密货币+美股)
  - 同步: 主程序v3.230

v3.220更新:
  - 同步: 主程序v3.220 (L1外挂模块修复)
  - 修复: v3.180+版本L1外挂从未触发问题
  - 根因: dir()检查变量错误导致l1_signals_for_plugin永远为空
  - 修复: 移除dir()检查，外挂正确接收L1三方协商结果
  - 效果: 外挂恢复正常工作(BUY1/SELL1信号生成)

v3.200更新:
  - 同步: 主程序v3.200
  - 重构: L2 10m小周期功能定位 - 仅作为辅助验证层
  - 新增: L2_10M_ACTIVE_TRADING开关 (默认False)
  - 屏蔽: 10m的所有主动交易触发逻辑 (P2激活/P3底激活/P4跌破激活/P5 V底/P6加速/P7增强/P8分数覆盖)
  - 保留: 10m的所有阻止逻辑 (假突破阻止/倒V顶阻止/放量下跌阻止/L1一致性/v3.165保护)
  - 核心: 10m现在只能阻止错误决策，不能主动触发买卖

v3.190更新:
  - 同步: 主程序v3.190
  - 修复: v3.180置信度传递断裂问题 (compute_l1_three_way_signal返回值缺少ai_confidence)
  - 新增: L2 10m小周期修正开关 USE_L2_10M_CORRECTION (默认False暂时屏蔽)
  - 效果: 外挂诊断正确显示动态置信度(0.40~0.95)，不再显示固定0.50

v3.180更新:
  - 同步: 主程序v3.180 (L1置信度传递修复)
  - 修复: 外挂诊断显示AI/Human/Tech conf=0.50问题
  - 修复: market_regime投票置信度现在正确传递给三方协商
  - 效果: L1模块诊断不再全是MISS(conf=0.50)，显示动态置信度0.40~0.95
  - 阈值更新: P0-Open美股6%, L2 10m统一2.5%

v3.160更新:
  - 同步: 主程序v3.160 (威科夫量价分析增强)
  - 新增: 威科夫分析面板显示 (量价背离/意图K线/震仓/停止行为)
  - 新增: DeepSeek仲裁增加威科夫规则
  - 新增: 威科夫信号列(WK)显示检测结果

v3.150更新:
  - 同步: 主程序v3.150 (SuperTrend趋势过滤)
  - 同步: supertrend_plugin_v08.py (趋势过滤功能)
  - 外挂仅在TRENDING市场触发，RANGING自动过滤
  - BUY1: position < 80% 才执行
  - SELL1: position > 20% 才执行

v3.120更新:
  - 同步: 主程序v3.120 (L2小周期验证增强)
  - tv_l2_10m_server新增短期趋势判断功能
  - 解决10m L2永远FORCE_HOLD的问题

v3.100更新:
  - 同步: 主程序v3.100 (门控优化 + 显示修复)
  - 取消P4.2 Grid PA Gate和UNCLEAR Gate
  - 修复P3显示与实际不一致Bug

v3.080更新:
  - 同步: 主程序v3.080 (P3外挂放行 + L1诊断系统)
  - 新增: L1模块准确率统计面板
  - 新增: 读取l1_diagnosis_summary.json显示诊断统计
  - 同步: supertrend_plugin_v08.py (趋势过滤)

v3.060更新:
  - 新增: SuperTrend外挂状态面板 (指标信号/模式/诊断)
  - 新增: L1模块诊断统计显示
  - 同步: 主程序v3.060 (SuperTrend趋势策略外挂)

v3.050更新:
  - 同步: 主程序v3.050 (大周期保护 + 知识规则阈值调整)
  - 同步: 扫描引擎冻结周期12h→6h
  - 新增: 大周期保护状态显示 (big_trend_protection)

v3.020更新:
  - 新增: P0追踪保护状态面板 (peak/trough价格和回撤显示)
  - 同步: price_scan_engine_v7.py追踪止损功能

v2.996更新:
  - 新增: WEAK_BUY/WEAK_SELL信号显示 (配合主程序AI信号修复)
  - 修复: 三方信号映射增加弱多/弱空显示

v2.992更新:
  - 修复: 仓位显示从state根级别读取，而非_last_final_decision快照
  - 修复: 确保显示实时仓位而非决策时快照

v2.990更新:
  - 新增: DeepSeek仲裁状态显示 (DS列)
  - 新增: DeepSeek仲裁详情面板
  - 新增: 共识类型增加 DEEPSEEK_ARBITER
  - 优化: 主表格增加DS列显示仲裁状态

v2.983更新:
  - 新增: 10m暴涨暴跌信号状态显示
  - 新增: L2 Score/exec_bias原始值显示
  - 同步: 主程序NY_TIMEZONE修复

v2.978更新:
  - 新增: 顺大逆小模式显示 (big_small_pattern)
  - 新增: COUNTER_TREND 共识类型显示
  - 修复: 方向显示增加顺大逆小标记

v2.970更新:
  - 新增: P0扫描引擎状态显示
  - 新增: 扫描引擎心跳检测
  - 修正: 美股三方信号N/A显示问题

v2.960更新:
  - 新增: Human双轨校准表 (规则/CNN准确率和权重)
  - 保留: v2.951所有功能

v2.951更新:
  - 新增: 市场状态 (TRENDING/RANGING) 显示
  - 新增: 策略模式 (L1/L2策略) 显示
  - 新增: 三方趋势投票显示
  - 新增: 市场状态判断准确率监控
  - 保留: CNN Human / XGBoost Tech 模型状态
"""

import os
import json
import time
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
# from timeframe_params import get_timeframe_params  # v3.600: 暂未使用

# ============================================================
# 配置区
# ============================================================

STATE_FILE = "logs/state.json"
VALIDATION_FILE = "state/three_way_validation.json"
CALIBRATION_FILE = "state/three_way_calibration.json"
XGBOOST_STATS_FILE = "state/xgboost_tech_stats.json"
CNN_HUMAN_STATS_FILE = "state/cnn_human_stats.json"
REGIME_VALIDATION_FILE = "state/regime_validation.json"
HUMAN_DUAL_TRACK_FILE = "state/human_dual_track.json"
# v3.570: Vision视觉分析状态文件
VISION_STATUS_FILE = "state/vision_status.json"
VISION_DAILY_REPORT_FILE = "state/vision_daily_report.json"
PATTERN_LATEST_FILE = "state/vision/pattern_latest.json"  # v3.1: Vision形态检测结果
# v2.970新增: 扫描引擎文件
SCAN_SIGNAL_FILE = "scan_signals.json"
SCAN_HEARTBEAT_FILE = "scan_heartbeat.json"
SCAN_STATE_FILE = "scan_state.json"
# v3.020新增: 追踪保护状态文件 (与price_scan_engine_v8.py同步)
TRACKING_STATE_FILE = "scan_tracking_state.json"
# v3.496新增: Chandelier+ZLSMA剥头皮状态文件
SCALPING_STATE_FILE = "scan_scalping_state.json"
# v3.530新增: SuperTrend外挂状态文件 (扫描引擎)
SUPERTREND_SCAN_STATE_FILE = "scan_supertrend_state.json"
# v3.530新增: L1外挂触发状态文件 (主程序)
L1_PLUGIN_STATE_FILE = "l1_plugin_state.json"
# v3.540新增: 全局趋势状态文件
GLOBAL_TREND_STATE_FILE = "global_trend_state.json"
# v3.610: L2 recommendation per-cycle cache (避免N+1文件读取)
_gts_cycle_cache = None
_gts_cycle_time = 0
# v3.060新增: SuperTrend外挂诊断文件
PLUGIN_DIAGNOSIS_FILE = "logs/l1_diagnosis_summary.json"
# v3.550新增: 外挂利润追踪状态文件
PLUGIN_PROFIT_STATE_FILE = "plugin_profit_state.json"
# v3.550新增: 扫描引擎各外挂状态文件
ROB_HOFFMAN_STATE_FILE = "scan_rob_hoffman_state.json"
DOUBLE_PATTERN_STATE_FILE = "scan_double_pattern_state.json"
FEIYUN_STATE_FILE = "scan_feiyun_state.json"
MACD_DIVERGENCE_STATE_FILE = "scan_macd_divergence_state.json"  # v3.565: MACD背离外挂状态
SUPERTREND_AV2_STATE_FILE = "scan_supertrend_av2_state.json"

# v3.150新增: 决策层诊断配置
DIAGNOSIS_ENABLED = True
DEEPSEEK_HELPER = "deepseek_helper.py"
DIAGNOSIS_LOG_DIR = Path("logs/deepseeklogs")

REFRESH_INTERVAL = 15

# === 品种列表 ===
# 同步修改位置:
# 1. llm_server SYNC_SYMBOLS (~line 24922)
# 2. price_scan_engine CRYPTO_SYMBOL_MAP (~line 585)
# 3. monitor CRYPTO_SYMBOLS (此处)
CRYPTO_SYMBOLS = ["SOLUSDC", "ETHUSDC", "ZECUSDC", "BTCUSDC"]
STOCK_SYMBOLS = ["TSLA", "COIN", "RDDT", "AMD", "NBIS", "CRWV", "RKLB", "HIMS", "OPEN", "ONDS", "PLTR"]

# ANSI颜色
C_G, C_GB, C_R, C_RB = "\033[92m", "\033[92;1m", "\033[91m", "\033[91;1m"
C_Y, C_C, C_M, C_B, C_W, C_0 = "\033[93m", "\033[96m", "\033[95m", "\033[94m", "\033[97m", "\033[0m"

# ============================================================
# 工具函数
# ============================================================

def load_json_file(fp, max_retries=3):
    """v3.230: 添加重试机制解决Windows文件锁定问题"""
    import time
    if not os.path.exists(fp): return {}
    for attempt in range(max_retries):
        try:
            with open(fp, "r", encoding="utf-8") as f: return json.load(f)
        except PermissionError:
            if attempt < max_retries - 1:
                time.sleep(0.05 * (2 ** attempt))
            else:
                return {}
        except: return {}
    return {}

def get_file_mtime(fp):
    if not os.path.exists(fp): return "N/A"
    try: return datetime.fromtimestamp(os.path.getmtime(fp)).strftime("%Y-%m-%d %H:%M:%S")
    except: return "N/A"

def display_width(s):
    w = 0
    for c in str(s):
        if '\u4e00' <= c <= '\u9fff' or '\u3000' <= c <= '\u303f' or '\uff00' <= c <= '\uffef': w += 2
        else: w += 1
    return w

def pad_to_width(text, width):
    text = str(text)
    return text + ' ' * max(0, width - display_width(text))

def rpad_to_width(text, width):
    text = str(text)
    return ' ' * max(0, width - display_width(text)) + text

# ============================================================
# v2.970: 扫描引擎状态检查
# ============================================================

def check_scan_engine_status():
    """检查扫描引擎状态"""
    heartbeat = load_json_file(SCAN_HEARTBEAT_FILE)
    if not heartbeat:
        return {"alive": False, "reason": "无心跳文件"}

    try:
        last_beat = datetime.fromisoformat(heartbeat["timestamp"])
        elapsed = (datetime.now() - last_beat).total_seconds()
        if elapsed < 120:
            return {
                "alive": True,
                "elapsed": elapsed,
                "scan_count": heartbeat.get("scan_count", 0),
            }
        else:
            return {"alive": False, "reason": f"心跳超时({elapsed:.0f}秒)"}
    except:
        return {"alive": False, "reason": "心跳解析失败"}

def get_scan_signals():
    """获取扫描引擎信号"""
    data = load_json_file(SCAN_SIGNAL_FILE)
    return data.get("signals", {})

def get_scan_state():
    """获取扫描引擎状态"""
    return load_json_file(SCAN_STATE_FILE)

def get_tracking_state():
    """v2.997: 获取追踪保护状态"""
    return load_json_file(TRACKING_STATE_FILE)

def get_scalping_state():
    """v3.496: 获取Chandelier+ZLSMA剥头皮状态"""
    return load_json_file(SCALPING_STATE_FILE)

def get_supertrend_scan_state():
    """v3.530: 获取SuperTrend外挂状态 (扫描引擎)"""
    return load_json_file(SUPERTREND_SCAN_STATE_FILE)

def get_l1_plugin_state():
    """v3.530: 获取L1外挂触发状态 (主程序)"""
    return load_json_file(L1_PLUGIN_STATE_FILE)

def get_plugin_profit_state():
    """v3.550: 获取外挂利润追踪状态"""
    return load_json_file(PLUGIN_PROFIT_STATE_FILE)

def get_rob_hoffman_state():
    """v3.550: 获取Rob Hoffman外挂状态"""
    return load_json_file(ROB_HOFFMAN_STATE_FILE)

def get_double_pattern_state():
    """v3.550: 获取双底双顶外挂状态"""
    return load_json_file(DOUBLE_PATTERN_STATE_FILE)

def get_feiyun_state():
    """v3.550: 获取飞云外挂状态"""
    return load_json_file(FEIYUN_STATE_FILE)

def get_macd_divergence_state():
    """v3.565: 获取MACD背离外挂状态"""
    return load_json_file(MACD_DIVERGENCE_STATE_FILE)

def get_supertrend_av2_state():
    """v3.550: 获取SuperTrend+AV2外挂状态"""
    return load_json_file(SUPERTREND_AV2_STATE_FILE)

def format_freeze_remaining(freeze_until_str):
    """v3.390: 格式化冻结剩余时间"""
    if not freeze_until_str:
        return ""
    try:
        freeze_until = datetime.fromisoformat(freeze_until_str.replace('Z', '+00:00'))
        # 处理时区：如果freeze_until有时区而now没有，统一处理
        now = datetime.now()
        if freeze_until.tzinfo is not None:
            # freeze_until有时区，转换为本地时间比较
            from datetime import timezone
            freeze_until = freeze_until.replace(tzinfo=None) if freeze_until.utcoffset() is None else freeze_until.astimezone().replace(tzinfo=None)

        remaining = freeze_until - now
        if remaining.total_seconds() <= 0:
            return ""

        hours = int(remaining.total_seconds() // 3600)
        minutes = int((remaining.total_seconds() % 3600) // 60)

        if hours > 0:
            return f"({hours}h{minutes:02d}m)"
        else:
            return f"({minutes}m)"
    except Exception:
        return ""

def is_symbol_frozen(freeze_until_str):
    """v3.490: 检查品种是否处于冻结状态 (提取重复逻辑)"""
    if not freeze_until_str:
        return False
    try:
        freeze_dt = datetime.fromisoformat(freeze_until_str.replace('Z', '+00:00'))
        now = datetime.now()
        if freeze_dt.tzinfo is not None:
            freeze_dt = freeze_dt.astimezone().replace(tzinfo=None)
        return freeze_dt > now
    except Exception:
        return False


def print_global_trend_status():
    """
    v3.620: 显示全局趋势同步 + 三方对比 (Vision/CNN/融合)

    读取多个状态文件，合并显示:
    - CURRENT/X4: 最终L1趋势
    - VIS: Vision(GPT-4o)方向
    - CNN: CNN数据判断方向
    - 采用: 当前覆盖来源
    - STRATEGY: 顺大逆小策略
    """
    total_width = 100

    # 读取全局趋势状态
    try:
        state = load_json_file(GLOBAL_TREND_STATE_FILE)
    except:
        state = None

    # 读取Vision latest.json
    vision_latest = {}
    try:
        vision_latest = load_json_file("state/vision/latest.json") or {}
    except:
        pass

    # 读取dual_track准确率 (判断覆盖来源)
    dual_track = {}
    try:
        dual_track = load_json_file(HUMAN_DUAL_TRACK_FILE) or {}
    except:
        pass

    # 读取主状态获取CNN信号
    main_state = {}
    try:
        main_state = load_json_file(STATE_FILE) or {}
    except:
        pass

    print("\n" + "=" * total_width)
    title = "Scan Engine: Trend + L1 Source (v3.620)"
    print(f"{title:^{total_width}}")
    print("=" * total_width)

    if not state or "symbols" not in state:
        print(f"  {C_Y}[No Data] Waiting for main program L1 refresh...{C_0}")
        print("-" * total_width)
        return

    last_updated = state.get("last_updated", "N/A")
    print(f"  Last Update: {last_updated}")
    print("-" * total_width)

    trend_colors = {"UP": C_G, "DOWN": C_R, "SIDE": C_Y}

    # 列宽定义
    WS = 10   # SYMBOL
    WC = 6    # CUR/X4/VIS/CNN (UP/DOWN/SIDE都<=4字符)
    WO = 8    # 采用 (Vision=6, CNN=3, 融合=4cjk, 规则=4cjk)
    WT = 12   # STRATEGY
    WL = 7    # L2

    # 表头 (用pad_to_width处理中文)
    header = (f"  {pad_to_width('SYMBOL', WS)}"
              f" {pad_to_width('CUR', WC)}"
              f" {pad_to_width('X4', WC)}"
              f" {pad_to_width('VIS', WC)}"
              f" {pad_to_width('CNN', WC)}"
              f" {pad_to_width('采用', WO)}"
              f" {pad_to_width('STRATEGY', WT)}"
              f" {pad_to_width('L2', WL)}")
    print(header)
    sep = f"  {'-'*WS} {'-'*WC} {'-'*WC} {'-'*WC} {'-'*WC} {'-'*WO} {'-'*WT} {'-'*WL}"
    print(sep)

    # symbol映射: global_trend用yfinance格式, Vision/主状态用主程序格式
    vis_symbol_map = {"BTC-USD": "BTCUSDC", "ETH-USD": "ETHUSDC", "SOL-USD": "SOLUSDC", "ZEC-USD": "ZECUSDC"}
    cnn_dir_map = {"BUY": "UP", "STRONG_BUY": "UP", "SELL": "DOWN", "STRONG_SELL": "DOWN", "HOLD": "SIDE"}

    for symbol, info in state.get("symbols", {}).items():
        current_trend = info.get("current_trend", "?")
        trend_x4 = info.get("trend_x4", "?")

        x4_upper = (trend_x4 or "SIDE").upper()
        cur_upper = (current_trend or "SIDE").upper()

        # Vision方向
        vis_key = vis_symbol_map.get(symbol, symbol)
        vis_data = vision_latest.get(vis_key, {})
        vis_dir = vis_data.get("current", {}).get("direction", "-").upper() if vis_data else "-"
        if vis_dir not in ("UP", "DOWN", "SIDE"):
            vis_dir = "-"

        # CNN信号 (从主状态)
        sym_state = main_state.get(vis_key, {})
        human_data = sym_state.get("_last_final_decision", {}).get("three_way_signals", {}).get("components", {}).get("human", {})
        cnn_sig = human_data.get("cnn_signal", "-")
        cnn_dir = cnn_dir_map.get(cnn_sig, "-")

        # v3.630: 判断L1覆盖来源 (准确率最高者)
        mr = sym_state.get("_last_final_decision", {}).get("three_way_signals", {}).get("market_regime", {})
        if isinstance(mr, str):
            mr = {}
        acc_override = mr.get("accuracy_override", False)
        acc_override_method = mr.get("accuracy_override_method", "")
        acc_override_accuracy = mr.get("accuracy_override_accuracy", 0)

        if acc_override and acc_override_method:
            source = f"{acc_override_method}({acc_override_accuracy:.0%})"
            source_color = C_C if "CNN" in acc_override_method else C_M if "Vision" in acc_override_method else C_Y
        elif human_data.get("model_used", False):
            source = "Dow基线"
            source_color = C_0
        else:
            source = "Dow基线"
            source_color = C_0

        # 策略
        if x4_upper == "UP" and cur_upper == "DOWN":
            strat_text = "SELL(REV)"
            strat_color = C_R
        elif x4_upper == "DOWN" and cur_upper == "UP":
            strat_text = "BUY(REV)"
            strat_color = C_G
        elif x4_upper == "UP":
            strat_text = "BUY ONLY"
            strat_color = C_G
        elif x4_upper == "DOWN":
            strat_text = "SELL ONLY"
            strat_color = C_R
        else:
            strat_text = "BUY+SELL"
            strat_color = C_Y

        # L2 recommendation
        l2_rec = info.get("l2_recommendation", "N/A")
        l2_colors = {"STRONG_BUY": C_GB, "BUY": C_G, "HOLD": C_Y, "SELL": C_R, "STRONG_SELL": C_R}
        l2_short = {"STRONG_BUY": "S_BUY", "BUY": "BUY", "HOLD": "HOLD", "SELL": "SELL", "STRONG_SELL": "S_SELL"}.get(l2_rec, l2_rec)

        # 用pad_to_width统一对齐 (颜色码不占宽度)
        def _c(text, width, color):
            return color + pad_to_width(text, width) + C_0

        cur_c = trend_colors.get(cur_upper, C_0)
        x4_c = trend_colors.get(x4_upper, C_0)
        vis_c = trend_colors.get(vis_dir, C_0) if vis_dir != "-" else C_0
        cnn_c = trend_colors.get(cnn_dir, C_0) if cnn_dir != "-" else C_0

        row = (f"  {pad_to_width(symbol, WS)}"
               f" {_c(cur_upper, WC, cur_c)}"
               f" {_c(x4_upper, WC, x4_c)}"
               f" {_c(vis_dir, WC, vis_c)}"
               f" {_c(cnn_dir, WC, cnn_c)}"
               f" {_c(source, WO, source_color)}"
               f" {_c(strat_text, WT, strat_color)}"
               f" {_c(l2_short, WL, l2_colors.get(l2_rec, C_0))}")
        print(row)

    print(sep)
    print(f"  CUR=最终当前 | VIS=GPT-4o | CNN=数据CNN | 采用=覆盖来源")
    print(f"  {C_M}Vision{C_0}=GPT覆盖  {C_C}CNN{C_0}=CNN覆盖融合  {C_Y}融合{C_0}=规则+CNN  规则=纯规则")
    print(sep)


def print_position_control_status(state):
    """
    v3.590: 显示Position Control立体仓位控制状态

    显示各品种:
    - 当前仓位 (0-5)
    - Position Control模式 (EMA10过滤/共振要求)
    - 允许的买卖操作
    """
    total_width = 90

    # 读取全局趋势状态
    try:
        trend_state = load_json_file(GLOBAL_TREND_STATE_FILE)
    except:
        trend_state = None

    print("\n" + "=" * total_width)
    title = "Position Control v20 - 立体仓位控制"
    print(f"{title:^{total_width}}")
    print("=" * total_width)

    if not trend_state or "symbols" not in trend_state:
        print(f"  {C_Y}[No Data] Waiting for trend data...{C_0}")
        print("-" * total_width)
        return

    # 表头
    header = f"  {'SYMBOL':<10} {'POS':^5} {'MODE':^20} {'BUY':^12} {'SELL':^12}"
    print(header)
    print(f"  {'-'*10} {'-'*5} {'-'*20} {'-'*12} {'-'*12}")

    # 符号映射
    symbol_map = {
        "BTCUSDC": "BTC-USD", "ETHUSDC": "ETH-USD",
        "SOLUSDC": "SOL-USD", "ZECUSDC": "ZEC-USD"
    }

    for symbol, sym_data in state.items():
        if isinstance(sym_data, dict) and "position_units" in sym_data:
            position = sym_data.get("position_units", 0)
            max_units = sym_data.get("max_units", 5)

            # 获取趋势
            yf_symbol = symbol_map.get(symbol, symbol)
            trend_info = trend_state.get("symbols", {}).get(yf_symbol, {})
            if not trend_info:
                trend_info = trend_state.get("symbols", {}).get(symbol, {})

            big_trend = (trend_info.get("trend_x4") or "?").upper()
            current_trend = (trend_info.get("current_trend") or "?").upper()

            # 判断Position Control模式和允许的操作
            if position <= 0:
                mode = "空仓"
                buy_status = f"{C_G}自由{C_0}"
                sell_status = f"{C_R}禁止{C_0}"
            elif position == 1:
                mode = "仓位1(单向卖)"
                buy_status = f"{C_G}自由{C_0}"
                # v20: big或cur=DOWN即可清仓
                if big_trend == "DOWN" or current_trend == "DOWN":
                    sell_status = f"{C_G}可清仓✓{C_0}"
                else:
                    sell_status = f"{C_Y}需D{C_0}"
            elif position == 2:
                mode = "仓位2"
                buy_status = f"{C_G}自由{C_0}"
                sell_status = f"{C_C}EMA10{C_0}"
            elif position == 3:
                mode = "仓位3(EMA10)"
                buy_status = f"{C_C}EMA10{C_0}"
                sell_status = f"{C_C}EMA10{C_0}"
            elif position == 4:
                mode = "仓位4(共振买)"
                # 检查共振
                if big_trend == "UP" and current_trend == "UP":
                    buy_status = f"{C_G}共振✓{C_0}"
                else:
                    buy_status = f"{C_Y}需U+U{C_0}"
                sell_status = f"{C_G}自由{C_0}"
            else:  # position >= 5
                mode = "满仓"
                buy_status = f"{C_R}禁止{C_0}"
                sell_status = f"{C_G}自由{C_0}"

            pos_display = f"{position}/{max_units}"
            if position >= max_units:
                pos_display = f"{C_M}{pos_display}{C_0}"
            elif position > 0:
                pos_display = f"{C_G}{pos_display}{C_0}"

            print(f"  {symbol:<10} {pos_display:^5} {mode:<20} {buy_status:^12} {sell_status:^12}")

    print("-" * total_width)
    print(f"  模式说明: EMA10=价格过滤(BUY>=EMA,SELL<=EMA) | 共振=big+current趋势一致")
    print(f"  共振条件: 买满仓(4→5)需U+U | 卖清仓(1→0)需big或cur=DOWN | 一卖(5→4)逐级")
    print("-" * total_width)


# ============================================================
# v3.150: 决策层诊断模块
# ============================================================

def call_deepseek(task: str, content: str) -> str:
    """调用 deepseek_helper.py 执行分析任务"""
    try:
        if task in ["cycle_analyze", "l1_diagnose", "p3_veto_analyze", "daily_report"]:
            result = subprocess.run(
                ["python", DEEPSEEK_HELPER, "--task", task, "--content", content],
                capture_output=True, text=True, timeout=60, encoding='utf-8'
            )
        else:
            result = subprocess.run(
                ["python", DEEPSEEK_HELPER, content],
                capture_output=True, text=True, timeout=60, encoding='utf-8'
            )
        return result.stdout.strip() if result.returncode == 0 else f"错误: {result.stderr}"
    except Exception as e:
        return f"DeepSeek调用失败: {e}"


class CycleDiagnostics:
    """v3.150: 周期诊断数据收集器"""

    def __init__(self):
        self.current_cycle_start = None
        self.p0_triggers = []
        self.plugin_triggers = []
        self.l2_10m_triggers = []
        self.p3_vetoes = []
        self.l1_diagnoses = []
        self.problems = []

        # 确保日志目录存在
        DIAGNOSIS_LOG_DIR.mkdir(parents=True, exist_ok=True)

        # 累计统计
        self.daily_stats = {
            "cycles": 0,
            "p0_count": 0,
            "plugin_count": 0,
            "l2_10m_count": 0,
            "l1_accuracy": {"ai": [], "human": [], "tech": []},
            "problems": []
        }

    def reset_cycle(self):
        """重置当前周期数据"""
        self.current_cycle_start = datetime.now()
        self.p0_triggers = []
        self.plugin_triggers = []
        self.l2_10m_triggers = []
        self.p3_vetoes = []
        self.problems = []

    def record_p0_trigger(self, symbol, signal, price):
        """记录P0触发"""
        self.p0_triggers.append({
            "time": datetime.now().isoformat(),
            "symbol": symbol,
            "signal": signal,
            "price": price
        })
        self.daily_stats["p0_count"] += 1

    def record_plugin_trigger(self, symbol, signal, st, qqe, macd, l1_signals):
        """记录外挂触发并分析L1"""
        trigger_data = {
            "time": datetime.now().isoformat(),
            "symbol": symbol,
            "signal": signal,
            "st": st, "qqe": qqe, "macd": macd,
            "l1": l1_signals
        }
        self.plugin_triggers.append(trigger_data)
        self.daily_stats["plugin_count"] += 1

        # 调用 DeepSeek 分析 L1
        if DIAGNOSIS_ENABLED:
            analysis = call_deepseek("l1_diagnose", json.dumps(trigger_data, ensure_ascii=False))
            self.l1_diagnoses.append({"trigger": trigger_data, "analysis": analysis})
            self._save_diagnosis_log(symbol, signal, l1_signals, analysis)
            return analysis
        return ""

    def record_p3_veto(self, symbol, l1_signal, l1_consensus, l2_signal, l2_score, reason):
        """记录P3否决"""
        veto_data = {
            "time": datetime.now().isoformat(),
            "symbol": symbol,
            "l1_signal": l1_signal,
            "l1_consensus": l1_consensus,
            "l2_signal": l2_signal,
            "l2_score": l2_score,
            "reason": reason
        }
        self.p3_vetoes.append(veto_data)

        if abs(l2_score) >= 7:
            self.problems.append(f"P3否决高分信号: {symbol} L2={l2_signal}(得分{l2_score})")

    def _save_diagnosis_log(self, symbol, signal, l1_signals, analysis):
        """保存诊断日志"""
        log_file = DIAGNOSIS_LOG_DIR / "plugin_diagnosis.log"
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"\n{'='*60}\n")
                f.write(f"时间: {datetime.now().isoformat()}\n")
                f.write(f"品种: {symbol}\n")
                f.write(f"外挂信号: {signal}\n")
                f.write(f"L1信号: AI={l1_signals.get('ai','?')} Human={l1_signals.get('human','?')} Tech={l1_signals.get('tech','?')}\n")
                f.write(f"诊断结果:\n{analysis}\n")
                f.write(f"{'='*60}\n")
        except Exception:
            pass

    def analyze_cycle_end(self):
        """周期结束时分析"""
        if not any([self.p0_triggers, self.plugin_triggers, self.l2_10m_triggers, self.p3_vetoes]):
            return None

        cycle_data = {
            "cycle": f"{self.current_cycle_start} - {datetime.now()}",
            "p0": self.p0_triggers,
            "plugin": self.plugin_triggers,
            "l2_10m": self.l2_10m_triggers,
            "p3_vetoes": self.p3_vetoes
        }

        if DIAGNOSIS_ENABLED:
            analysis = call_deepseek("cycle_analyze", json.dumps(cycle_data, ensure_ascii=False))
            self._save_cycle_analysis(cycle_data, analysis)
            self.daily_stats["cycles"] += 1
            return analysis
        return None

    def _save_cycle_analysis(self, cycle_data, analysis):
        """保存周期分析"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        log_file = DIAGNOSIS_LOG_DIR / f"cycle_diagnosis_{timestamp}.json"
        try:
            with open(log_file, "w", encoding="utf-8") as f:
                json.dump({"data": cycle_data, "analysis": analysis}, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def generate_daily_report(self):
        """生成每日报告"""
        if not DIAGNOSIS_ENABLED:
            return None
        report_data = json.dumps(self.daily_stats, ensure_ascii=False, indent=2)
        report = call_deepseek("daily_report", report_data)

        date_str = datetime.now().strftime("%Y%m%d")
        report_file = DIAGNOSIS_LOG_DIR / f"diagnosis_report_{date_str}.md"
        try:
            with open(report_file, "w", encoding="utf-8") as f:
                f.write(report)
        except Exception:
            pass

        return report_file


# 全局诊断实例
diagnostics = CycleDiagnostics()


def print_diagnosis_panel(all_data):
    """v3.150: 打印决策层诊断面板"""
    if not DIAGNOSIS_ENABLED:
        return

    total_width = 90
    now = datetime.now()
    cycle_start = now.replace(minute=(now.minute // 30) * 30, second=0, microsecond=0)
    cycle_end = cycle_start + timedelta(minutes=30)

    print("\n" + "=" * total_width)
    print(f" 决策层诊断 (v3.150) | 周期 {cycle_start.strftime('%H:%M')}-{cycle_end.strftime('%H:%M')}")
    print("-" * total_width)

    # 本周期事件统计
    p0_count = len(diagnostics.p0_triggers)
    plugin_count = len(diagnostics.plugin_triggers)
    l2_10m_count = len(diagnostics.l2_10m_triggers)
    p3_veto_count = len(diagnostics.p3_vetoes)

    print(f" 本周期事件 | P0触发: {p0_count} | 外挂触发: {plugin_count} | L2_10m: {l2_10m_count} | P3否决: {p3_veto_count}")
    print("-" * total_width)

    # 最近外挂触发
    if diagnostics.plugin_triggers:
        latest = diagnostics.plugin_triggers[-1]
        l1 = latest.get("l1", {})
        qqe_val = latest.get('qqe', 0) or 0
        macd_val = latest.get('macd', 0) or 0
        print(f" 最近外挂 | {latest['symbol']} {latest['signal']} | ST={latest.get('st', '?')} QQE={qqe_val:+.1f} MACD={macd_val:+.2f}")
        print(f"          | L1: AI={l1.get('ai','?')} Human={l1.get('human','?')} Tech={l1.get('tech','?')}")

        if diagnostics.l1_diagnoses:
            latest_diag = diagnostics.l1_diagnoses[-1]["analysis"]
            diag_short = latest_diag[:60].replace('\n', ' ') if latest_diag else ""
            print(f"          | 诊断: {diag_short}...")
    else:
        print(" 最近外挂 | 本周期无触发")

    print("-" * total_width)

    # 问题检测
    if diagnostics.problems:
        print(f" 问题检测 | {C_Y}⚠️ {len(diagnostics.problems)}个问题{C_0}")
        for i, problem in enumerate(diagnostics.problems[:3], 1):
            print(f"          | {i}. {problem}")
    else:
        print(f" 问题检测 | {C_G}✅ 本周期无异常{C_0}")

    print("-" * total_width)

    # 今日统计
    stats = diagnostics.daily_stats
    print(f" 今日统计 | 周期: {stats['cycles']} | P0: {stats['p0_count']} | 外挂: {stats['plugin_count']} | L2_10m: {stats.get('l2_10m_count', 0)}")

    print("=" * total_width)


# ============================================================
# 数据提取
# ============================================================

def get_symbol_data(state, symbol):
    data = state.get(symbol, {})
    ld = data.get("_last_final_decision", {})
    swing_sr = ld.get("swing_sr", {})
    supreme = ld.get("supreme_protection", {})
    three_way = ld.get("three_way_signals", {})
    position_gate = ld.get("position_gate", {})
    surge_data = data.get("_last_10m_surge", {})
    l2_gate = data.get("_l2_gate", {})  # v3.460: L2门卫状态
    l2_p1_features = data.get("_l2_p1_features", {})  # v3.465: P1改善项

    # v2.992: 从state根级别读取实时仓位，而非_last_final_decision的快照
    position_units = data.get("position_units", ld.get("position_units", 0))
    max_units = data.get("max_units", ld.get("max_units", 5))

    # v2.970: P0扫描引擎信号
    p0_scan = ld.get("p0_scan_engine", {})

    # v2.951: 市场状态 (兼容新旧格式)
    market_regime = three_way.get("market_regime", {})
    # 如果market_regime是字符串（旧格式），转换为字典
    if isinstance(market_regime, str):
        market_regime = {"regime": market_regime, "direction": "N/A", "l1_strategy": "N/A"}

    components = three_way.get("components", {})

    return {
        "symbol": symbol,
        "swing_triggered": swing_sr.get("triggered", False),
        "swing_action": swing_sr.get("action", "HOLD"),
        "supreme_protected": supreme.get("protected", False),
        "supreme_type": supreme.get("protection_type", "NONE"),
        "ai_sig": three_way.get("ai", "N/A"),
        "human_sig": three_way.get("human", "N/A"),
        "tech_sig": three_way.get("tech", "N/A"),
        "consensus": three_way.get("consensus", "N/A"),
        "tech_model_used": three_way.get("tech_model_used", False),
        "human_model_used": three_way.get("human_model_used", False),
        "l1_action": ld.get("l1_action", "N/A"),
        "exec_bias": ld.get("l2_exec_bias", "N/A"),
        "p3_action": ld.get("engine_action", "N/A"),
        "gate_applied": position_gate.get("gate_applied", False),
        "gate_reason": position_gate.get("gate_reason", ""),  # v3.391新增
        "position_status": position_gate.get("position_status", "NORMAL"),  # v3.391新增
        "final_action": ld.get("final_action", "N/A"),
        "position_units": position_units,  # v2.992: 使用实时仓位
        "max_units": max_units,  # v2.992: 使用实时max_units
        "pos_ratio": data.get("pos_ratio", 0.5),
        "override_by": ld.get("override_by", "NONE"),
        "surge_detected": surge_data.get("detected", False),
        "surge_type": surge_data.get("type", "NONE"),
        "surge_pct": surge_data.get("pct", 0) * 100 if surge_data.get("pct") else 0,
        # v2.951新增 (兼容旧格式)
        "market_regime": market_regime.get("regime", "N/A") if isinstance(market_regime, dict) else market_regime,
        "regime_direction": market_regime.get("direction", "N/A") if isinstance(market_regime, dict) else "N/A",
        "l1_strategy": market_regime.get("l1_strategy", "N/A") if isinstance(market_regime, dict) else "N/A",
        "ai_vote": components.get("ai", {}).get("regime_vote", "N/A") if isinstance(components, dict) else "N/A",
        "human_vote": components.get("human", {}).get("regime_vote", "N/A") if isinstance(components, dict) else "N/A",
        "tech_vote": components.get("tech", {}).get("regime_vote", "N/A") if isinstance(components, dict) else "N/A",
        # v2.970新增: P0扫描引擎触发
        "p0_scan_triggered": p0_scan.get("triggered", False),
        "p0_scan_action": p0_scan.get("action", ""),
        # v2.978新增: 顺大逆小模式
        "big_small_pattern": market_regime.get("big_small_pattern", "NONE") if isinstance(market_regime, dict) else "NONE",
        "l2_strategy": market_regime.get("l2_strategy", "N/A") if isinstance(market_regime, dict) else "N/A",
        # v3.630: 准确率覆盖状态 (替代v3.586 Vision覆盖)
        "accuracy_override": market_regime.get("accuracy_override", False) if isinstance(market_regime, dict) else False,
        "accuracy_override_method": market_regime.get("accuracy_override_method", "") if isinstance(market_regime, dict) else "",
        "accuracy_override_from": market_regime.get("accuracy_override_from", "") if isinstance(market_regime, dict) else "",
        "accuracy_override_to": market_regime.get("accuracy_override_to", "") if isinstance(market_regime, dict) else "",
        "accuracy_override_accuracy": market_regime.get("accuracy_override_accuracy", 0) if isinstance(market_regime, dict) else 0,
        # v2.983新增: 10m暴涨暴跌信号
        "surge_10m_detected": surge_data.get("detected", False),
        "surge_10m_type": surge_data.get("type", "NONE"),
        "surge_10m_pct": surge_data.get("change_pct", 0),
        # v2.983新增: L2 Score详情
        "l2_score": ld.get("l2_score", 0),
        "l2_score_breakdown": ld.get("l2_score_breakdown", {}),
        # v3.420新增: 形态外挂 (双重底/顶 + 头肩底/顶)
        "reversal_pattern": ld.get("reversal_pattern", {}),
        "reversal_pattern_name": ld.get("reversal_pattern", {}).get("pattern", "NONE"),
        "reversal_pattern_stage": ld.get("reversal_pattern", {}).get("stage", ""),
        "reversal_pattern_quality": ld.get("reversal_pattern", {}).get("quality_score", 0),
        "reversal_pattern_score": ld.get("l2_score_breakdown", {}).get("reversal", 0),
        # v3.370新增: L2降级追踪
        "l2_veto_applied": ld.get("l2_veto_applied", False),
        "l2_original_exec_bias": ld.get("l2_original_exec_bias", ld.get("l2_exec_bias", "N/A")),
        "l2_downgrade_desc": ld.get("l2_downgrade_desc", None),
        "l2_veto_reason": ld.get("l2_veto_reason", None),
        # v2.990新增: DeepSeek仲裁 (旧三方冲突仲裁)
        "deepseek_arbiter": three_way.get("deepseek_arbiter", None),
        # v3.330更新: DeepSeek趋势仲裁 (AI+Tech分歧时触发)
        # 同时检查旧三方仲裁 和 新趋势仲裁(consensus==DEEPSEEK_ARBITER)
        "deepseek_used": (
            (three_way.get("deepseek_arbiter", {}).get("success", False) if three_way.get("deepseek_arbiter") else False) or
            (three_way.get("v3300_five_module", {}).get("ai_module", {}).get("consensus") == "DEEPSEEK_ARBITER")
        ),
        "deepseek_signal": (
            three_way.get("v3300_five_module", {}).get("ai_module", {}).get("big_trend", "N/A")
            if three_way.get("v3300_five_module", {}).get("ai_module", {}).get("consensus") == "DEEPSEEK_ARBITER"
            else (three_way.get("deepseek_arbiter", {}).get("signal", "N/A") if three_way.get("deepseek_arbiter") else "N/A")
        ),
        "deepseek_conf": (
            three_way.get("v3300_five_module", {}).get("ai_module", {}).get("confidence", 0.7)
            if three_way.get("v3300_five_module", {}).get("ai_module", {}).get("consensus") == "DEEPSEEK_ARBITER"
            else (three_way.get("deepseek_arbiter", {}).get("confidence", 0) if three_way.get("deepseek_arbiter") else 0)
        ),
        "deepseek_reason": (
            three_way.get("v3300_five_module", {}).get("ai_module", {}).get("deepseek_reason", "AI+Tech分歧,趋势仲裁")
            if three_way.get("v3300_five_module", {}).get("ai_module", {}).get("consensus") == "DEEPSEEK_ARBITER"
            else (three_way.get("deepseek_arbiter", {}).get("reason", "") if three_way.get("deepseek_arbiter") else "")
        ),
        # v3.330新增: 标记是否为趋势仲裁(区分于旧三方仲裁)
        "deepseek_trend_arbiter": three_way.get("v3300_five_module", {}).get("ai_module", {}).get("consensus") == "DEEPSEEK_ARBITER",
        # v3.050新增: 大周期保护
        "big_trend_protection": ld.get("big_trend_protection", "NONE"),
        # v3.320: L1五模块框架 (AI+Tech双重验证)
        "v3300_five_module": three_way.get("v3300_five_module", {}),
        "v3300_ai_big_trend": three_way.get("v3300_five_module", {}).get("ai_module", {}).get("big_trend", "N/A"),
        "v3300_ai_consensus": three_way.get("v3300_five_module", {}).get("ai_module", {}).get("consensus", "N/A"),
        "v3300_ai_x4_regime": three_way.get("v3300_five_module", {}).get("ai_module", {}).get("detail", {}).get("ai_x4_regime", "N/A"),
        "v3300_tech_regime": three_way.get("v3300_five_module", {}).get("ai_module", {}).get("detail", {}).get("tech_regime", "N/A"),
        "v3300_adx": three_way.get("v3300_five_module", {}).get("tech_module", {}).get("detail", {}).get("adx", 0),
        "v3300_chop": three_way.get("v3300_five_module", {}).get("tech_module", {}).get("detail", {}).get("choppiness", 0),
        "v3300_human_phase": three_way.get("v3300_five_module", {}).get("human_module", {}).get("phase", "N/A"),
        "v3300_dow_trend": three_way.get("v3300_five_module", {}).get("human_module", {}).get("dow_trend", "side"),  # v3.370: 道氏理论
        "v3300_current_trend": three_way.get("v3300_five_module", {}).get("human_module", {}).get("current_trend", "SIDE"),  # v3.380: 当前周期趋势
        "v3300_recovery_detected": three_way.get("v3300_five_module", {}).get("human_module", {}).get("dow_details", {}).get("recovery_detected", False),  # v3.441: 恢复检测
        "v3300_recovery_reason": three_way.get("v3300_five_module", {}).get("human_module", {}).get("dow_details", {}).get("recovery_reason", ""),  # v3.441: 恢复原因
        "v3300_tech_strength": three_way.get("v3300_five_module", {}).get("tech_module", {}).get("strength", "N/A"),
        "v3300_grid_position": three_way.get("v3300_five_module", {}).get("grid_module", {}).get("position", "N/A"),
        "v3300_grid_relative": three_way.get("v3300_five_module", {}).get("grid_module", {}).get("detail", {}).get("relative_pos", 0),
        "v3300_signal": three_way.get("v3300_five_module", {}).get("signal", "N/A"),
        "v3300_decision_reason": three_way.get("v3300_five_module", {}).get("reason", "N/A"),
        # v3.060新增: SuperTrend外挂
        "plugin": ld.get("plugin", {}),
        "plugin_active": ld.get("plugin", {}).get("active", False),
        "plugin_mode": ld.get("plugin", {}).get("mode", "DISABLED"),
        "plugin_signal": ld.get("plugin", {}).get("indicator_signal", "NONE"),
        "plugin_st_trend": ld.get("plugin", {}).get("supertrend_trend", "N/A"),
        "plugin_qqe": ld.get("plugin", {}).get("qqe_hist", 0),
        "plugin_macd": ld.get("plugin", {}).get("macd_hist", 0),
        # v0.6.1: 缓存信号
        "plugin_cached": ld.get("plugin", {}).get("cached_signal", "NONE"),
        # v3.496新增: MACD背离外挂
        "macd_divergence": ld.get("macd_divergence", {}),
        # v3.160新增: 威科夫分析
        "wyckoff": ld.get("wyckoff", {}),
        "wyckoff_signal": ld.get("wyckoff", {}).get("wyckoff_signal", None),
        "wyckoff_warning": ld.get("wyckoff", {}).get("wyckoff_warning", None),
        "wyckoff_divergence": ld.get("wyckoff", {}).get("divergence", {}).get("divergence_type", "NONE"),
        "wyckoff_intention": ld.get("wyckoff", {}).get("intention", {}).get("bar_type", "NEUTRAL"),
        "wyckoff_spring": ld.get("wyckoff", {}).get("spring", {}).get("spring_detected", False),
        "wyckoff_stopping": ld.get("wyckoff", {}).get("stopping", {}).get("stopping_action", "NONE"),
        # v3.460新增: L2门卫状态
        "l2_gate_big_decision": l2_gate.get("big_decision", "N/A"),
        "l2_gate_small_decision": l2_gate.get("small_decision", "N/A"),
        "l2_gate_small_score": l2_gate.get("small_score", 0),
        "l2_gate_allow_trade": l2_gate.get("allow_trade", False),
        "l2_gate_trade_action": l2_gate.get("trade_action", None),
        "l2_gate_frozen": l2_gate.get("frozen", False),
        "l2_gate_reason": l2_gate.get("reason", ""),
        "l2_gate_timestamp": l2_gate.get("timestamp", 0),
        # v3.465新增: P1改善项
        "p1_ema20_bias": l2_p1_features.get("ema20", {}).get("bias", "N/A"),
        "p1_ema20_pullback": l2_p1_features.get("ema20", {}).get("pullback_signal", False),
        "p1_ema20_score": l2_p1_features.get("ema20", {}).get("score", 0),
        "p1_power_candle_type": l2_p1_features.get("power_candle", {}).get("type", "NONE"),
        "p1_power_candle_strength": l2_p1_features.get("power_candle", {}).get("strength", 0),
        "p1_power_candle_score": l2_p1_features.get("power_candle", {}).get("score", 0),
        "p1_volume_heap": l2_p1_features.get("volume_heap", {}).get("has_volume_heap", False),
        "p1_volume_heap_strength": l2_p1_features.get("volume_heap", {}).get("momentum_strength", "NONE"),
        "p1_volume_pulse_warning": l2_p1_features.get("volume_heap", {}).get("pulse_volume_warning", False),
        "p1_volume_heap_score": l2_p1_features.get("volume_heap", {}).get("score", 0),
        # v3.610: L2 recommendation (供扫描引擎空间确认)
        "l2_recommendation": _get_l2_recommendation_cached(symbol),
        # v3.1: Vision形态检测
        "vision_pattern": _get_vision_pattern_cached(symbol),
    }

# ============================================================
# 格式化
# ============================================================

# v3.370: 调整列宽 (中文占2字符宽度)
# v3.391: 移除XG/CN/DS列(始终显示-)
W_SYM, W_REG, W_DIR, W_3WAY, W_VOTE = 8, 6, 4, 9, 8  # 三方列缩短到9
W_CON, W_P1, W_L2, W_FIN, W_POS = 12, 4, 4, 4, 6  # v3.411: 共识列12字符容纳DOW_OVERRIDE
W_PAT = 7  # v3.1: Vision形态列

def sig_to_short(sig):
    # v3.370: 统一5档格式 + 兼容旧格式 (每个信号唯一字符)
    mapping = {
        "STRONG_BUY": "多", "BUY": "买",    # 多=强买
        "HOLD": "平",
        "SELL": "卖", "STRONG_SELL": "空",  # 空=强卖
        # 兼容旧格式
        "WEAK_BUY": "买", "WEAK_SELL": "卖", "NEUTRAL": "平",
        "BUY_OK": "买", "SELL_OK": "卖", "FORCE_HOLD": "平",
    }
    return mapping.get(sig, "平" if sig in ("H", "F", "N") else (sig[:1] if sig and sig != "N/A" else "-"))

def color_action(action, width):
    # v3.370: 统一5档格式 + 兼容旧格式
    text = sig_to_short(action)
    if action in ("STRONG_BUY", "BUY", "WEAK_BUY", "BUY_OK"):
        return C_GB + pad_to_width(text, width) + C_0
    elif action in ("STRONG_SELL", "SELL", "WEAK_SELL", "SELL_OK"):
        return C_RB + pad_to_width(text, width) + C_0
    elif action in ("HOLD", "NEUTRAL", "FORCE_HOLD"):
        return C_Y + pad_to_width(text, width) + C_0
    return pad_to_width(text, width)

def fmt_sym(d): return pad_to_width(d["symbol"][:W_SYM], W_SYM)

def fmt_regime(d):
    regime = d.get("market_regime", "N/A")
    if regime == "TRENDING":
        return C_GB + pad_to_width("趋势", W_REG) + C_0
    elif regime == "RANGING":
        return C_Y + pad_to_width("震荡", W_REG) + C_0
    return pad_to_width("  -", W_REG)

def fmt_direction(d):
    direction = d.get("regime_direction", "N/A")
    pattern = d.get("big_small_pattern", "NONE")

    # v2.978: 顺大逆小标记
    if pattern == "BIG_DOWN_SMALL_BOUNCE":
        # 大跌+小反弹: 方向DOWN，黄色警告
        return C_Y + pad_to_width("↓反", W_DIR) + C_0
    elif pattern == "BIG_UP_SMALL_PULLBACK":
        # 大涨+小回调: 方向UP，黄色警告
        return C_Y + pad_to_width("↑回", W_DIR) + C_0

    if direction == "UP": return C_GB + pad_to_width(" ↑", W_DIR) + C_0
    elif direction == "DOWN": return C_RB + pad_to_width(" ↓", W_DIR) + C_0
    elif direction == "SIDE": return C_Y + pad_to_width(" →", W_DIR) + C_0  # v3.391: 震荡方向
    return pad_to_width(" -", W_DIR)

def fmt_three_way(d):
    # v3.370: 固定格式 X/X/X (每个1中文字符)
    ai = sig_to_short(d['ai_sig'])
    human = sig_to_short(d['human_sig'])
    tech = sig_to_short(d['tech_sig'])
    return pad_to_width(f"{ai}/{human}/{tech}", W_3WAY)

def fmt_votes(d):
    ai = "T" if d.get("ai_vote") == "TRENDING" else ("R" if d.get("ai_vote") == "RANGING" else "?")
    human = "T" if d.get("human_vote") == "TRENDING" else ("R" if d.get("human_vote") == "RANGING" else "?")
    tech = "T" if d.get("tech_vote") == "TRENDING" else ("R" if d.get("tech_vote") == "RANGING" else "?")
    return pad_to_width(f"{ai}/{human}/{tech}", W_VOTE)

# v3.391: 移除fmt_xgb/fmt_cnn/fmt_ds(始终显示-无意义)

def fmt_consensus(d):
    # v3.330: 优先使用五模块的consensus (DEEPSEEK_ARBITER)
    c = d.get("v3300_ai_consensus", d.get("consensus", "N/A"))
    m = {
        "THREE_AGREE": ("三方一致", C_GB),
        "TWO_AGREE": ("两方一致", C_G),
        "THREE_SPLIT": ("分裂", C_Y),
        "CONFLICT": ("冲突", C_R),
        "COUNTER_TREND": ("顺大逆小", C_Y),
        "DEEPSEEK_ARBITER": ("DS仲裁", C_M),  # v3.330: DeepSeek趋势仲裁
        "AGREE": ("AI+T一致", C_GB),  # v3.310: AI+Tech一致
        "DISAGREE": ("AI+T分歧", C_Y),  # v3.310: AI+Tech分歧
        "TECH_ONLY": ("Tech兜底", C_C),  # v3.310: AI无效时Tech兜底
        "DOW_OVERRIDE": ("DOW_OVERRIDE", C_GB),  # v3.411: 道氏覆盖
    }
    if c in m: return m[c][1] + pad_to_width(m[c][0], W_CON) + C_0
    return pad_to_width(str(c)[:W_CON] if c else "N/A", W_CON)

def fmt_l1(d): return color_action(d["l1_action"], W_P1)

def _get_l2_recommendation_cached(symbol):
    """v3.610: 从global_trend_state.json读取L2 recommendation (per-cycle缓存)"""
    global _gts_cycle_cache, _gts_cycle_time
    import time as _time_mod
    now = _time_mod.time()
    # 每15秒刷新缓存（与REFRESH_INTERVAL一致）
    if _gts_cycle_cache is None or (now - _gts_cycle_time) > 15:
        try:
            _gts_cycle_cache = load_json_file(GLOBAL_TREND_STATE_FILE)
        except Exception:
            _gts_cycle_cache = {}
        _gts_cycle_time = now
    return (_gts_cycle_cache or {}).get("symbols", {}).get(symbol, {}).get("l2_recommendation", "N/A")


# v3.1: Vision形态检测结果缓存
_pattern_cache = None
_pattern_cache_time = 0

def _get_vision_pattern_cached(symbol):
    """v3.1: 从pattern_latest.json读取Vision形态 (per-cycle缓存)"""
    global _pattern_cache, _pattern_cache_time
    import time as _time_mod
    now = _time_mod.time()
    if _pattern_cache is None or (now - _pattern_cache_time) > 15:
        try:
            _pattern_cache = load_json_file(PATTERN_LATEST_FILE)
        except Exception:
            _pattern_cache = {}
        _pattern_cache_time = now
    data = (_pattern_cache or {}).get(symbol, {})
    pattern = data.get("pattern", "NONE")
    if pattern == "NONE":
        return "-"
    # 短名映射
    short_map = {
        "DOUBLE_BOTTOM": "DB", "DOUBLE_TOP": "DT",
        "HEAD_SHOULDERS_BOTTOM": "HsB", "HEAD_SHOULDERS_TOP": "HsT",
        "REVERSAL_123_BUY": "123B", "REVERSAL_123_SELL": "123S",
        "FALSE_BREAK_BUY": "2BB", "FALSE_BREAK_SELL": "2BS",
    }
    short = short_map.get(pattern, pattern[:4])
    stage = data.get("stage", "")
    conf = data.get("confidence", 0)
    prefix = "B" if stage == "BREAKOUT" else "F" if stage == "FORMING" else "?"
    return f"{prefix}:{short}"


def fmt_l2(d):
    """v3.610: 显示L2 exec_bias + L2 recommendation，降级时添加↓标记"""
    bias = d.get("exec_bias", "N/A")
    result = color_action(bias, W_L2)
    # v3.370: 如果发生降级，在颜色后添加↓标记
    if d.get("l2_veto_applied", False):
        # 替换末尾空格为↓标记
        result = result.rstrip() + C_Y + "↓" + C_0
    # v3.610: 在L2后显示recommendation (紧凑格式)
    l2_rec = d.get("l2_recommendation", "N/A")
    if l2_rec and l2_rec != "N/A":
        rec_short = {"STRONG_BUY": "SB", "BUY": "B", "HOLD": "H", "SELL": "S", "STRONG_SELL": "SS"}.get(l2_rec, "?")
        if "STRONG" in l2_rec:
            if "BUY" in l2_rec:
                result += C_GB + rec_short + C_0
            else:
                result += C_R + rec_short + C_0
        elif l2_rec == "BUY":
            result += C_G + rec_short + C_0
        elif l2_rec == "SELL":
            result += C_R + rec_short + C_0
        else:
            result += rec_short
    return result

def fmt_fin(d):
    """v3.411: 简化最终决策显示"""
    return color_action(d["final_action"], W_FIN)

def fmt_pos(d):
    text = str(d["position_units"]) + "/" + str(d["max_units"])
    if d["position_units"] >= d["max_units"]: return C_M + rpad_to_width(text, W_POS) + C_0
    elif d["position_units"] > 0: return C_G + rpad_to_width(text, W_POS) + C_0
    elif d["position_units"] < 0: return C_R + rpad_to_width(text, W_POS) + C_0
    return rpad_to_width(text, W_POS)

def color_acc(acc, width):
    text = "%.0f%%" % (acc * 100)
    if acc >= 0.60: return C_GB + rpad_to_width(text, width) + C_0
    elif acc >= 0.50: return C_G + rpad_to_width(text, width) + C_0
    elif acc >= 0.40: return C_Y + rpad_to_width(text, width) + C_0
    return C_R + rpad_to_width(text, width) + C_0

# ============================================================
# 表格打印
# ============================================================

def fmt_pattern(d):
    """v3.1: Vision形态列"""
    pat = d.get("vision_pattern", "-")
    if pat == "-":
        return rpad_to_width(pat, W_PAT)
    # B:DB = Breakout双底(绿), B:DT = Breakout双顶(红), F:xx = Forming(黄)
    if pat.startswith("B:"):
        # Breakout: BUY类绿色, SELL类红色
        buy_patterns = ("DB", "HsB", "123B", "2BB")
        if any(pat.endswith(p) for p in buy_patterns):
            return C_G + rpad_to_width(pat, W_PAT) + C_0
        return C_R + rpad_to_width(pat, W_PAT) + C_0
    if pat.startswith("F:"):
        return C_Y + rpad_to_width(pat, W_PAT) + C_0
    return rpad_to_width(pat, W_PAT)


def print_main_table(all_data):
    """v3.630: 主面板 — 品种|当前|x4|VIS|CNN|R%|C%|V%|采用|信号|L2|形态|最终|仓位"""
    # 读取dual_track/main_state额外数据
    dual_track = {}
    try:
        dual_track = load_json_file(HUMAN_DUAL_TRACK_FILE) or {}
    except:
        pass

    main_state = {}
    try:
        main_state = load_json_file(STATE_FILE) or {}
    except:
        pass

    trend_colors = {"UP": C_G, "DOWN": C_R, "SIDE": C_Y}

    # 列宽
    WT = 6    # trend columns (当前/x4)
    WV = 4    # VIS/CNN direction
    WA = 3    # accuracy columns (R%/C%/V%)
    WR = 10   # 采用
    WS = 4    # 信号
    WL = 4    # L2 (compact)

    cols = [("品种", W_SYM), ("当前", WT), ("x4", WT),
            ("VIS", WV), ("CNN", WV),
            ("R%", WA), ("C%", WA), ("V%", WA),
            ("采用", WR), ("信号", WS), ("L2", WL), ("形态", W_PAT), ("最终", W_FIN), ("仓位", W_POS)]

    total_w = sum(c[1] for c in cols) + 3 * len(cols) + 1
    header = "| " + " | ".join(pad_to_width(c[0], c[1]) for c in cols) + " |"
    print(header)
    print("-" * total_w)

    def _c(text, width, color):
        return color + pad_to_width(text, width) + C_0

    for d in all_data:
        symbol = d["symbol"]

        # 当前趋势 (最终结果)
        cur = (d.get("v3300_current_trend", "SIDE") or "SIDE").upper()
        # x4大周期
        x4 = (d.get("v3300_ai_big_trend", "N/A") or "SIDE").upper()
        if x4 == "N/A":
            x4 = "-"

        # Vision/CNN方向 (from market_regime)
        sym_state = main_state.get(symbol, {})
        mr = sym_state.get("_last_final_decision", {}).get("three_way_signals", {}).get("market_regime", {})
        if isinstance(mr, str):
            mr = {}
        vis_dir = mr.get("vision_current_direction", "").upper()
        if not vis_dir:
            vis_dir = "-"

        human_data = sym_state.get("_last_final_decision", {}).get("three_way_signals", {}).get("components", {}).get("human", {})
        cnn_dir = ""
        if human_data and human_data.get("cnn_override"):
            cnn_dir = human_data.get("cnn_trend", "").upper()
        if not cnn_dir:
            cnn_dir = "-"

        # 3方准确率: Rule vs CNN vs Vision
        dt_stats = dual_track.get("stats", {}).get(symbol, {})
        r_total = dt_stats.get("rule_total", 0)
        c_total = dt_stats.get("cnn_total", 0)
        v_total = dt_stats.get("vision_total", 0)
        r_pct = dt_stats.get("rule_correct", 0) / r_total * 100 if r_total > 0 else -1
        c_pct = dt_stats.get("cnn_correct", 0) / c_total * 100 if c_total > 0 else -1
        v_pct = dt_stats.get("vision_correct", 0) / v_total * 100 if v_total > 0 else -1
        _best_pct = max(r_pct, c_pct, v_pct)
        def _acc(val, is_best):
            if val < 0:
                return pad_to_width("---", WA)
            t = f"{val:.0f}"
            return (C_GB + pad_to_width(t, WA) + C_0) if is_best else pad_to_width(t, WA)
        r_str_acc = _acc(r_pct, r_pct == _best_pct and r_pct > 0)
        c_str_acc = _acc(c_pct, c_pct == _best_pct and c_pct > 0)
        v_str_acc = _acc(v_pct, v_pct == _best_pct and v_pct > 0)

        # v3.630: 采用来源 (最高准确率覆盖)
        acc_ov = mr.get("accuracy_override", False)
        acc_ov_method = mr.get("accuracy_override_method", "")
        acc_ov_accuracy = mr.get("accuracy_override_accuracy", 0)

        if acc_ov and "Vision" in acc_ov_method:
            source = f"Vision★({acc_ov_accuracy:.0%})"
            source_color = C_M
        elif acc_ov and "CNN" in acc_ov_method:
            source = f"CNN★({acc_ov_accuracy:.0%})"
            source_color = C_C
        elif human_data and human_data.get("model_used", False):
            if human_data.get("cnn_override"):
                source = "CNN覆盖"
                source_color = C_C
            else:
                source = "融合"
                source_color = C_Y
        else:
            source = "规则"
            source_color = C_0

        cur_c = trend_colors.get(cur, C_0)
        x4_c = trend_colors.get(x4, C_0)
        vis_c = trend_colors.get(vis_dir, C_0) if vis_dir != "-" else C_0
        cnn_c = trend_colors.get(cnn_dir, C_0) if cnn_dir != "-" else C_0

        # L1信号 (compact)
        signal = d.get("v3300_signal", "N/A")
        sig_text = sig_to_short(signal)
        if signal in ("STRONG_BUY", "BUY"):
            sig_str = C_GB + pad_to_width(sig_text, WS) + C_0
        elif signal in ("STRONG_SELL", "SELL"):
            sig_str = C_RB + pad_to_width(sig_text, WS) + C_0
        else:
            sig_str = pad_to_width(sig_text, WS)

        # L2 (compact — 只显示exec_bias)
        l2_str = color_action(d.get("exec_bias", "N/A"), WL)

        row = ("| " + pad_to_width(symbol[:W_SYM], W_SYM)
               + " | " + _c(cur, WT, cur_c)
               + " | " + _c(x4, WT, x4_c)
               + " | " + _c(vis_dir, WV, vis_c)
               + " | " + _c(cnn_dir, WV, cnn_c)
               + " | " + r_str_acc
               + " | " + c_str_acc
               + " | " + v_str_acc
               + " | " + _c(source, WR, source_color)
               + " | " + sig_str
               + " | " + l2_str
               + " | " + fmt_pattern(d)
               + " | " + fmt_fin(d)
               + " | " + fmt_pos(d) + " |")
        print(row)

    print("-" * total_w)
    print(f"  Vision★=GPT覆盖 CNN★=CNN覆盖 融合=规则+CNN 规则=默认  R%/C%/V%=规则/CNN/Vision准确率  {C_GB}绿{C_0}=最高准确率")


def print_scan_engine_status():
    """v2.970: 打印扫描引擎状态"""
    total_width = 90

    print("\n" + "=" * total_width)
    print(" P0 扫描引擎状态 (v3.050 - 6小时冻结)")
    print("-" * total_width)

    status = check_scan_engine_status()

    if status["alive"]:
        print(f" 状态: {C_GB}✅ 运行中{C_0} | 心跳: {status['elapsed']:.0f}秒前 | 扫描次数: {status['scan_count']}")
    else:
        print(f" 状态: {C_R}❌ 离线{C_0} | 原因: {status.get('reason', '未知')}")
        print("-" * total_width)
        return

    # 显示当前信号
    signals = get_scan_signals()
    scan_state = get_scan_state()

    if signals:
        print(f"\n 当前P0信号:")
        for symbol, sig in signals.items():
            print(f"   {C_M}⚡{C_0} {symbol}: {sig['signal']} ({sig['change_pct']:+.2f}%)")

    # 显示监控状态
    crypto_state = scan_state.get("crypto", {})
    stock_state = scan_state.get("stock", {})

    print(f"\n 监控状态:")

    # 加密货币
    crypto_triggered = sum(1 for s in crypto_state.values() if s.get("triggered"))
    crypto_total = len(crypto_state)
    print(f"   加密货币: {crypto_total}个品种, {crypto_triggered}个已触发")

    # 美股
    stock_triggered = sum(1 for s in stock_state.values() if s.get("triggered"))
    stock_total = len(stock_state)
    print(f"   美股: {stock_total}个品种, {stock_triggered}个已触发")

    print("-" * total_width)


def print_tracking_protection_status(state):
    """v3.020: 打印P0追踪保护状态"""
    total_width = 90

    tracking_state = get_tracking_state()

    if not tracking_state:
        return  # 无追踪状态时不显示

    print("\n" + "=" * total_width)
    print(" P0 追踪保护状态 (v3.050 - 6小时冻结)")
    print("-" * total_width)

    # 按资产类型分组显示
    crypto_symbols = ["BTC-USD", "ETH-USD", "SOL-USD", "ZEC-USD"]
    stock_symbols = ["TSLA", "COIN", "RDDT", "AMD", "NBIS", "CRWV", "RKLB", "HIMS", "OPEN", "ONDS", "PLTR"]

    # 阈值配置
    crypto_threshold = 2.5
    stock_threshold = 3.5

    # 映射: yfinance格式 -> 主程序格式
    yf_to_main = {
        "BTC-USD": "BTCUSDC", "ETH-USD": "ETHUSDC",
        "SOL-USD": "SOLUSDC", "ZEC-USD": "ZECUSDC"
    }

    has_data = False

    # 加密货币
    crypto_rows = []
    for yf_symbol in crypto_symbols:
        if yf_symbol in tracking_state:
            has_data = True
            ts = tracking_state[yf_symbol]
            main_symbol = yf_to_main.get(yf_symbol, yf_symbol)

            # 从state获取当前价格
            symbol_state = state.get(main_symbol, {})
            current_price = symbol_state.get("_last_final_decision", {}).get("current_price", 0)

            peak_price = ts.get("peak_price", 0)
            trough_price = ts.get("trough_price", 0)
            sell_triggered = ts.get("sell_triggered", False)
            buy_triggered = ts.get("buy_triggered", False)
            position = ts.get("last_position", 0)

            # v3.050: 检查冻结状态 (v3.490: 使用is_symbol_frozen简化)
            freeze_until = ts.get("freeze_until")
            is_frozen = is_symbol_frozen(freeze_until)

            if position > 0 and peak_price > 0 and current_price > 0:
                # 持仓状态: 显示peak和回撤
                drawdown = (current_price - peak_price) / peak_price * 100
                # v3.390: 冻结状态显示剩余时间
                freeze_remaining = format_freeze_remaining(freeze_until) if is_frozen else ""
                status = f"冻结{freeze_remaining}" if is_frozen else ("触发" if sell_triggered else "监控")
                status_color = C_M if is_frozen else (C_Y if sell_triggered else C_G)

                if drawdown >= 0:
                    dd_str = f"{C_GB}+{drawdown:.2f}%{C_0}"
                elif abs(drawdown) >= crypto_threshold:
                    dd_str = f"{C_RB}{drawdown:.2f}%{C_0}"
                else:
                    dd_str = f"{C_Y}{drawdown:.2f}%{C_0}"

                crypto_rows.append(
                    f"   {C_G}📈{C_0} {main_symbol:<8} | peak={peak_price:.2f} | 当前={current_price:.2f} | "
                    f"回撤={dd_str} | 阈值={crypto_threshold}% | {status_color}{status}{C_0}"
                )
            elif position == 0 and trough_price > 0 and current_price > 0:
                # 空仓状态: 显示trough和涨幅
                rise = (current_price - trough_price) / trough_price * 100
                # v3.390: 冻结状态显示剩余时间
                freeze_remaining = format_freeze_remaining(freeze_until) if is_frozen else ""
                status = f"冻结{freeze_remaining}" if is_frozen else ("触发" if buy_triggered else "监控")
                status_color = C_M if is_frozen else (C_Y if buy_triggered else C_G)

                if rise <= 0:
                    rise_str = f"{C_RB}{rise:.2f}%{C_0}"
                elif rise >= crypto_threshold:
                    rise_str = f"{C_GB}+{rise:.2f}%{C_0}"
                else:
                    rise_str = f"{C_Y}+{rise:.2f}%{C_0}"

                crypto_rows.append(
                    f"   {C_B}📉{C_0} {main_symbol:<8} | trough={trough_price:.2f} | 当前={current_price:.2f} | "
                    f"涨幅={rise_str} | 阈值={crypto_threshold}% | {status_color}{status}{C_0}"
                )

    # 美股
    stock_rows = []
    for symbol in stock_symbols:
        if symbol in tracking_state:
            has_data = True
            ts = tracking_state[symbol]

            symbol_state = state.get(symbol, {})
            current_price = symbol_state.get("_last_final_decision", {}).get("current_price", 0)

            peak_price = ts.get("peak_price", 0)
            trough_price = ts.get("trough_price", 0)
            sell_triggered = ts.get("sell_triggered", False)
            buy_triggered = ts.get("buy_triggered", False)
            position = ts.get("last_position", 0)

            # v3.050: 检查冻结状态 (v3.490: 使用is_symbol_frozen简化)
            freeze_until = ts.get("freeze_until")
            is_frozen = is_symbol_frozen(freeze_until)

            if position > 0 and peak_price > 0 and current_price > 0:
                drawdown = (current_price - peak_price) / peak_price * 100
                # v3.390: 冻结状态显示剩余时间
                freeze_remaining = format_freeze_remaining(freeze_until) if is_frozen else ""
                status = f"冻结{freeze_remaining}" if is_frozen else ("触发" if sell_triggered else "监控")
                status_color = C_M if is_frozen else (C_Y if sell_triggered else C_G)

                if drawdown >= 0:
                    dd_str = f"{C_GB}+{drawdown:.2f}%{C_0}"
                elif abs(drawdown) >= stock_threshold:
                    dd_str = f"{C_RB}{drawdown:.2f}%{C_0}"
                else:
                    dd_str = f"{C_Y}{drawdown:.2f}%{C_0}"

                stock_rows.append(
                    f"   {C_G}📈{C_0} {symbol:<8} | peak={peak_price:.2f} | 当前={current_price:.2f} | "
                    f"回撤={dd_str} | 阈值={stock_threshold}% | {status_color}{status}{C_0}"
                )
            elif position == 0 and trough_price > 0 and current_price > 0:
                rise = (current_price - trough_price) / trough_price * 100
                # v3.390: 冻结状态显示剩余时间
                freeze_remaining = format_freeze_remaining(freeze_until) if is_frozen else ""
                status = f"冻结{freeze_remaining}" if is_frozen else ("触发" if buy_triggered else "监控")
                status_color = C_M if is_frozen else (C_Y if buy_triggered else C_G)

                if rise <= 0:
                    rise_str = f"{C_RB}{rise:.2f}%{C_0}"
                elif rise >= stock_threshold:
                    rise_str = f"{C_GB}+{rise:.2f}%{C_0}"
                else:
                    rise_str = f"{C_Y}+{rise:.2f}%{C_0}"

                stock_rows.append(
                    f"   {C_B}📉{C_0} {symbol:<8} | trough={trough_price:.2f} | 当前={current_price:.2f} | "
                    f"涨幅={rise_str} | 阈值={stock_threshold}% | {status_color}{status}{C_0}"
                )

    if not has_data:
        print(f" {C_Y}⚠️ 暂无追踪数据{C_0}")
    else:
        if crypto_rows:
            print(f" {C_C}加密货币:{C_0}")
            for row in crypto_rows:
                print(row)
        if stock_rows:
            print(f" {C_C}美股:{C_0}")
            for row in stock_rows:
                print(row)

    print(f"\n   {C_G}📈{C_0}=持仓追踪peak | {C_B}📉{C_0}=空仓追踪trough | {C_M}冻结{C_0}=6h内1买+1卖")
    print("-" * total_width)


def print_scalping_status():
    """v3.496: 打印Chandelier+ZLSMA剥头皮状态"""
    total_width = 90

    scalping_state = get_scalping_state()
    if not scalping_state or "symbols" not in scalping_state:
        return  # 无剥头皮状态时不显示

    symbols_data = scalping_state.get("symbols", {})
    if not symbols_data:
        return

    print("\n" + "=" * total_width)
    print(" 🎯 Chandelier+ZLSMA 剥头皮状态 (v12.0 - 5分钟周期)")
    print("-" * total_width)

    # 映射: yfinance格式 -> 主程序格式
    yf_to_main = {
        "BTC-USD": "BTCUSDC", "ETH-USD": "ETHUSDC",
        "SOL-USD": "SOLUSDC", "ZEC-USD": "ZECUSDC"
    }

    rows = []
    for yf_symbol, state in symbols_data.items():
        main_symbol = yf_to_main.get(yf_symbol, yf_symbol)
        freeze_until = state.get("freeze_until")
        last_signal = state.get("last_signal", "-")
        last_trigger_time = state.get("last_trigger_time", "")
        last_trigger_price = state.get("last_trigger_price", 0)

        # 检查冻结状态
        is_frozen = is_symbol_frozen(freeze_until)
        freeze_remaining = format_freeze_remaining(freeze_until) if is_frozen else ""

        # 格式化上次触发时间
        if last_trigger_time:
            try:
                dt = datetime.fromisoformat(last_trigger_time)
                time_str = dt.strftime("%H:%M:%S")
            except:
                time_str = "N/A"
        else:
            time_str = "-"

        # 信号颜色
        if last_signal == "BUY":
            sig_color = C_GB
            sig_icon = "📈"
        elif last_signal == "SELL":
            sig_color = C_RB
            sig_icon = "📉"
        else:
            sig_color = C_Y
            sig_icon = "⏸"

        # 状态
        if is_frozen:
            status = f"{C_M}冻结{freeze_remaining}{C_0}"
        else:
            status = f"{C_G}监控中{C_0}"

        # 价格
        price_str = f"{last_trigger_price:.4f}" if last_trigger_price else "-"

        rows.append(
            f"   {sig_icon} {main_symbol:<8} | 上次: {sig_color}{last_signal:<4}{C_0} @ {time_str} | "
            f"价格: {price_str} | {status}"
        )

    for row in rows:
        print(row)

    print(f"\n   {C_G}监控中{C_0}=等待信号 | {C_M}冻结{C_0}=按币种(BTC/ETH/SOL=8h, ZEC=2h) | SIDE=依赖Chandelier方向")
    print("-" * total_width)


def print_all_plugin_status():
    """
    v3.530: 统一打印所有外挂触发状态
    - 扫描引擎触发: P0-Tracking, 剥头皮, SuperTrend, RobHoffman, 飞云, MACD背离
    - v3.565: MACD背离从L2层移交扫描引擎
    """
    total_width = 90

    # 收集所有外挂状态
    # 1. 扫描引擎外挂
    tracking_state = get_tracking_state()
    scalping_state = get_scalping_state()
    supertrend_scan_state = get_supertrend_scan_state()

    # 2. L1外挂状态
    l1_plugin_state = get_l1_plugin_state()

    # 映射: yfinance格式 -> 主程序格式
    yf_to_main = {
        "BTC-USD": "BTCUSDC", "ETH-USD": "ETHUSDC",
        "SOL-USD": "SOLUSDC", "ZEC-USD": "ZECUSDC"
    }

    # ================== 扫描引擎外挂 ==================
    scan_plugins = []

    # P0-Tracking
    if tracking_state and "symbols" in tracking_state:
        for yf_sym, state in tracking_state.get("symbols", {}).items():
            main_sym = yf_to_main.get(yf_sym, yf_sym)
            last_signal = state.get("triggered_action", "-")
            trigger_time = state.get("trigger_time", "")
            freeze_until = state.get("freeze_until", "")
            if last_signal and last_signal != "-":
                scan_plugins.append({
                    "symbol": main_sym,
                    "plugin": "P0-Tracking",
                    "signal": last_signal,
                    "trigger_time": trigger_time,
                    "freeze_until": freeze_until,
                })

    # 剥头皮
    if scalping_state and "symbols" in scalping_state:
        for yf_sym, state in scalping_state.get("symbols", {}).items():
            main_sym = yf_to_main.get(yf_sym, yf_sym)
            last_signal = state.get("last_signal", "-")
            trigger_time = state.get("last_trigger_time", "")
            freeze_until = state.get("freeze_until", "")
            if last_signal and last_signal != "-":
                scan_plugins.append({
                    "symbol": main_sym,
                    "plugin": "剥头皮",
                    "signal": last_signal,
                    "trigger_time": trigger_time,
                    "freeze_until": freeze_until,
                })

    # SuperTrend (扫描引擎)
    if supertrend_scan_state and "symbols" in supertrend_scan_state:
        for yf_sym, state in supertrend_scan_state.get("symbols", {}).items():
            main_sym = yf_to_main.get(yf_sym, yf_sym)
            last_signal = state.get("last_signal", "-")
            trigger_time = state.get("last_trigger_time", "")
            freeze_until = state.get("freeze_until", "")
            if last_signal and last_signal != "-":
                scan_plugins.append({
                    "symbol": main_sym,
                    "plugin": "SuperTrend(扫描)",
                    "signal": last_signal,
                    "trigger_time": trigger_time,
                    "freeze_until": freeze_until,
                })

    # v3.565: MACD背离 (扫描引擎)
    macd_div_scan_state = get_macd_divergence_state()
    if macd_div_scan_state and "symbols" in macd_div_scan_state:
        for yf_sym, state in macd_div_scan_state.get("symbols", {}).items():
            main_sym = yf_to_main.get(yf_sym, yf_sym)
            last_signal = state.get("last_signal", "-")
            trigger_time = state.get("last_trigger_time", "")
            freeze_until = state.get("freeze_until", "")
            if last_signal and last_signal != "-":
                scan_plugins.append({
                    "symbol": main_sym,
                    "plugin": "MACD背离(扫描)",
                    "signal": last_signal,
                    "trigger_time": trigger_time,
                    "freeze_until": freeze_until,
                })

    # ================== L1外挂 ==================
    l1_plugins = []
    if l1_plugin_state and "symbols" in l1_plugin_state:
        for sym, plugins in l1_plugin_state.get("symbols", {}).items():
            for plugin_name, state in plugins.items():
                last_signal = state.get("last_signal", "-")
                trigger_time = state.get("trigger_time", "")
                freeze_until = state.get("freeze_until", "")
                if last_signal and last_signal != "-":
                    l1_plugins.append({
                        "symbol": sym,
                        "plugin": plugin_name,
                        "signal": last_signal,
                        "trigger_time": trigger_time,
                        "freeze_until": freeze_until,
                    })

    # v3.530: 即使没有触发记录也显示面板框架（让用户知道功能存在）

    # 打印标题
    print("\n" + "=" * total_width)
    print(" 🔌 外挂触发状态 (v3.530)")
    print("=" * total_width)

    def format_trigger_time(trigger_time_str):
        """格式化触发时间"""
        if not trigger_time_str:
            return "-"
        try:
            dt = datetime.fromisoformat(trigger_time_str.replace('Z', '+00:00'))
            if dt.tzinfo is not None:
                dt = dt.astimezone().replace(tzinfo=None)
            return dt.strftime("%m-%d %H:%M")
        except:
            return "-"

    def get_signal_display(signal):
        """获取信号显示样式"""
        if "BUY" in str(signal).upper():
            return C_GB, "📈"
        elif "SELL" in str(signal).upper():
            return C_RB, "📉"
        else:
            return C_Y, "⏸"

    def get_status_display(freeze_until_str):
        """获取状态显示"""
        if is_symbol_frozen(freeze_until_str):
            remaining = format_freeze_remaining(freeze_until_str)
            return f"{C_M}冻结{remaining}{C_0}"
        else:
            return f"{C_G}就绪{C_0}"

    # 打印扫描引擎外挂
    print(f"\n {C_C}▸ 扫描引擎触发{C_0} (P0-Tracking / 剥头皮 / SuperTrend)")
    print("-" * total_width)
    if scan_plugins:
        for p in scan_plugins:
            sig_color, sig_icon = get_signal_display(p["signal"])
            time_str = format_trigger_time(p["trigger_time"])
            status = get_status_display(p["freeze_until"])
            print(f"   {sig_icon} {p['symbol']:<8} | {p['plugin']:<15} | {sig_color}{p['signal']:<12}{C_0} | {time_str} | {status}")
    else:
        print(f"   {C_Y}暂无触发记录{C_0}")

    # 打印L1外挂
    print(f"\n {C_C}▸ L1层触发{C_0} (SuperTrend / RobHoffman / 双底双顶 / 飞云)")
    print("-" * total_width)
    if l1_plugins:
        for p in l1_plugins:
            sig_color, sig_icon = get_signal_display(p["signal"])
            time_str = format_trigger_time(p["trigger_time"])
            status = get_status_display(p["freeze_until"])
            print(f"   {sig_icon} {p['symbol']:<8} | {p['plugin']:<15} | {sig_color}{p['signal']:<12}{C_0} | {time_str} | {status}")
    else:
        print(f"   {C_Y}暂无触发记录{C_0}")

    # 图例
    print(f"\n   {C_G}就绪{C_0}=可再次触发 | {C_M}冻结{C_0}=等待解冻 | 📈=买入信号 | 📉=卖出信号")
    print("-" * total_width)


def print_plugin_profit_report():
    """v3.620: 外挂利润分析 — 24小时窗口 (8AM~次日8AM), 解冻后重新计算"""
    total_width = 80
    state = get_plugin_profit_state()
    if not state:
        state = {}

    daily_stats = state.get("daily_stats", {})
    completed_trades = state.get("completed_trades", [])
    open_entries = state.get("open_entries", {})

    # 计算交易日 (纽约时间 8AM~次日8AM)
    try:
        import pytz
        ny_tz = pytz.timezone("America/New_York")
        ny_now = datetime.now(ny_tz)
        if ny_now.hour < 8:
            trade_date = (ny_now - timedelta(days=1)).strftime("%Y-%m-%d")
        else:
            trade_date = ny_now.strftime("%Y-%m-%d")
        today = trade_date
        trade_start = datetime.strptime(trade_date, "%Y-%m-%d").replace(hour=8)
        trade_end = trade_start + timedelta(days=1)
        date_range_str = f"{trade_start.strftime('%m/%d')} 8AM ~ {trade_end.strftime('%m/%d')} 8AM"
    except Exception:
        today = datetime.now().strftime("%Y-%m-%d")
        date_range_str = today

    today_all = daily_stats.get(today, {})

    # 统计当日已平仓交易 (从completed_trades筛选sell_ts匹配today)
    day_trades_by_asset_plugin = {}  # {asset_type: {plugin: {"wins": n, "losses": n}}}
    for t in completed_trades:
        sell_ts = t.get("sell_ts", "")
        if not sell_ts:
            continue
        # 判断sell_ts是否在当日窗口内
        sell_date_str = sell_ts[:10]  # "YYYY-MM-DD"
        if sell_date_str != today:
            continue
        buy_plugin = t.get("buy_plugin", "?")
        asset_type = t.get("asset_type", "crypto")
        pnl = t.get("pnl", 0)
        bucket = day_trades_by_asset_plugin.setdefault(asset_type, {}).setdefault(buy_plugin, {"wins": 0, "losses": 0})
        if pnl > 0:
            bucket["wins"] += 1
        else:
            bucket["losses"] += 1

    print("\n" + "=" * total_width)
    print(f" 外挂利润 (24h)  {date_range_str}")
    print("=" * total_width)

    # 列宽 (对齐优化)
    W_NAME = 16
    W_SIG = 6
    W_EXE = 6
    W_CLOSED = 6
    W_WR = 6
    W_PNL = 12

    header = (
        f" {pad_to_width('外挂', W_NAME)}"
        f"| {rpad_to_width('信号', W_SIG)}"
        f"| {rpad_to_width('执行', W_EXE)}"
        f"| {rpad_to_width('平仓', W_CLOSED)}"
        f"| {rpad_to_width('胜率', W_WR)}"
        f"| {rpad_to_width('盈亏', W_PNL)}"
    )

    CRYPTO_PLUGINS = [
        "P0-Tracking", "P0-Open", "Chandelier+ZLSMA",
        "SuperTrend", "SuperTrend+AV2", "RobHoffman",
        "DoublePattern", "Feiyun", "MACD背离",
        "移动止损", "移动止盈",
    ]
    STOCK_PLUGINS = [
        "P0-Tracking", "SuperTrend", "SuperTrend+AV2",
        "RobHoffman", "DoublePattern", "Feiyun", "MACD背离",
        "移动止损", "移动止盈",
    ]

    def _format_pnl(pnl_val, bold=False):
        if pnl_val > 0:
            g = C_GB if bold else C_G
            return f"{g}+${pnl_val:,.2f}{C_0}"
        elif pnl_val < 0:
            r = C_RB if bold else C_R
            return f"{r}-${abs(pnl_val):,.2f}{C_0}"
        return "$0.00"

    def _build_plugin_list(fixed_list, daily_dict):
        result = list(fixed_list)
        seen = set(result)
        for name in daily_dict.keys():
            if name not in seen:
                result.append(name)
                seen.add(name)
        return result

    def _print_section(section_label, daily_section, fixed_plugins, asset_type):
        """打印分区 — 只显示24h数据"""
        plugins = _build_plugin_list(fixed_plugins, daily_section)
        trade_data = day_trades_by_asset_plugin.get(asset_type, {})

        print(f" {C_C}{section_label}{C_0}")
        print(header)
        print("-" * total_width)

        sub_sig = sub_exec = sub_closed = sub_wins = 0
        sub_pnl = 0.0

        for pname in plugins:
            d = daily_section.get(pname, {})
            td = trade_data.get(pname, {})

            t_sig = d.get("signals", 0)
            t_exec = d.get("executed", 0)
            wins = td.get("wins", 0)
            losses = td.get("losses", 0)
            closed = wins + losses
            wr = f"{wins/closed*100:.0f}%" if closed > 0 else "-"
            pnl = d.get("pnl", 0.0)

            # 跳过全零行
            if t_sig == 0 and t_exec == 0 and closed == 0 and pnl == 0:
                continue

            pnl_str = _format_pnl(pnl)
            row = (
                f" {pad_to_width(pname, W_NAME)}"
                f"| {rpad_to_width(str(t_sig), W_SIG)}"
                f"| {rpad_to_width(str(t_exec), W_EXE)}"
                f"| {rpad_to_width(str(closed), W_CLOSED)}"
                f"| {rpad_to_width(wr, W_WR)}"
                f"| {rpad_to_width(pnl_str, W_PNL)}"
            )
            print(row)

            sub_sig += t_sig
            sub_exec += t_exec
            sub_closed += closed
            sub_wins += wins
            sub_pnl += pnl

        # 小计行
        print("-" * total_width)
        sub_wr = f"{sub_wins/sub_closed*100:.0f}%" if sub_closed > 0 else "-"
        sub_row = (
            f" {pad_to_width(section_label + '小计', W_NAME)}"
            f"| {rpad_to_width(str(sub_sig), W_SIG)}"
            f"| {rpad_to_width(str(sub_exec), W_EXE)}"
            f"| {rpad_to_width(str(sub_closed), W_CLOSED)}"
            f"| {rpad_to_width(sub_wr, W_WR)}"
            f"| {rpad_to_width(_format_pnl(sub_pnl), W_PNL)}"
        )
        print(sub_row)
        return sub_sig, sub_exec, sub_closed, sub_wins, sub_pnl

    # --- 加密货币分区 ---
    crypto_daily = today_all.get("crypto", {})
    c_sig, c_exec, c_closed, c_wins, c_pnl = _print_section(
        "加密货币", crypto_daily, CRYPTO_PLUGINS, "crypto"
    )

    print("")

    # --- 美股分区 ---
    stock_daily = today_all.get("stock", {})
    s_sig, s_exec, s_closed, s_wins, s_pnl = _print_section(
        "美股", stock_daily, STOCK_PLUGINS, "stock"
    )

    # --- 合计行 ---
    grand_sig = c_sig + s_sig
    grand_exec = c_exec + s_exec
    grand_closed = c_closed + s_closed
    grand_wins = c_wins + s_wins
    grand_pnl = c_pnl + s_pnl

    print("=" * total_width)
    grand_wr = f"{grand_wins/grand_closed*100:.0f}%" if grand_closed > 0 else "-"
    grand_row = (
        f" {pad_to_width('合计', W_NAME)}"
        f"| {rpad_to_width(str(grand_sig), W_SIG)}"
        f"| {rpad_to_width(str(grand_exec), W_EXE)}"
        f"| {rpad_to_width(str(grand_closed), W_CLOSED)}"
        f"| {rpad_to_width(grand_wr, W_WR)}"
        f"| {rpad_to_width(_format_pnl(grand_pnl, bold=True), W_PNL)}"
    )
    print(grand_row)
    print("=" * total_width)

    # 持仓中 (未平仓)
    crypto_open = []
    stock_open = []
    for sym, entries in open_entries.items():
        if not entries:
            continue
        plugin_counts = {}
        for e in entries:
            p = e.get("plugin", "?")
            plugin_counts[p] = plugin_counts.get(p, 0) + 1
        asset = entries[0].get("asset_type", "crypto")
        parts_list = crypto_open if asset == "crypto" else stock_open
        for p, cnt in plugin_counts.items():
            parts_list.append(f"{p}({sym})x{cnt}")

    open_text_parts = []
    if crypto_open:
        open_text_parts.append(f"加密: {', '.join(crypto_open)}")
    if stock_open:
        open_text_parts.append(f"美股: {', '.join(stock_open)}")
    if open_text_parts:
        print(f" 持仓中: {' | '.join(open_text_parts)}")
    print("=" * total_width)


def print_supertrend_scan_status():
    """v3.530: 已合并到print_all_plugin_status()，保留兼容性"""
    pass  # 改用 print_all_plugin_status()


def print_deepseek_status(all_data):
    """v3.330: 打印DeepSeek仲裁状态 (含趋势仲裁)"""
    total_width = 90

    # 筛选使用了DeepSeek仲裁的品种
    ds_symbols = [d for d in all_data if d.get("deepseek_used")]

    if not ds_symbols:
        return  # 无仲裁时不显示

    print("\n" + "=" * total_width)
    print(" DeepSeek 仲裁状态 (v3.370 趋势仲裁)")
    print("-" * total_width)

    for d in ds_symbols:
        symbol = d["symbol"]
        ds_signal = d.get("deepseek_signal", "N/A")
        ds_conf = d.get("deepseek_conf", 0)
        ds_reason = d.get("deepseek_reason", "")[:50]  # 截断原因
        ds_type = "趋势仲裁" if d.get("deepseek_trend_arbiter") else "三方仲裁"

        # 信号颜色 (v3.330: 趋势仲裁时显示UP/DOWN/SIDE)
        if ds_signal in ("BUY", "STRONG_BUY", "UP"):
            sig_color = C_GB
        elif ds_signal in ("SELL", "STRONG_SELL", "DOWN"):
            sig_color = C_RB
        else:
            sig_color = C_Y

        print(f"   {C_M}🤖{C_0} {symbol}: [{ds_type}] {sig_color}{ds_signal}{C_0} ({ds_conf*100:.0f}%) - {ds_reason}")

    print("-" * total_width)


def print_wyckoff_status(all_data):
    """v3.160: 打印威科夫量价分析状态"""
    total_width = 90

    # 筛选有威科夫信号或警告的品种
    wk_symbols = [d for d in all_data if (
        d.get("wyckoff_signal") or
        d.get("wyckoff_warning") or
        d.get("wyckoff_spring") or
        d.get("wyckoff_stopping") not in (None, "NONE") or
        d.get("wyckoff_divergence") not in (None, "NONE")
    )]

    if not wk_symbols:
        return  # 无信号时不显示

    print("\n" + "=" * total_width)
    print(" 威科夫量价分析 (v3.160)")
    print("-" * total_width)

    for d in wk_symbols:
        symbol = d["symbol"]
        wk_signal = d.get("wyckoff_signal")
        wk_warning = d.get("wyckoff_warning")
        wk_divergence = d.get("wyckoff_divergence", "NONE")
        wk_intention = d.get("wyckoff_intention", "NEUTRAL")
        wk_spring = d.get("wyckoff_spring", False)
        wk_stopping = d.get("wyckoff_stopping", "NONE")

        # 构建状态行
        status_parts = []

        # Spring (最重要)
        if wk_spring:
            status_parts.append(f"{C_GB}🔄Spring弹簧{C_0}")

        # 停止行为
        if wk_stopping == "BUYING_CLIMAX":
            status_parts.append(f"{C_GB}📈买入高潮(底部){C_0}")
        elif wk_stopping == "SELLING_CLIMAX":
            status_parts.append(f"{C_RB}📉卖出高潮(顶部){C_0}")

        # 量价背离
        if wk_divergence == "BEARISH":
            status_parts.append(f"{C_Y}⚠️看跌背离{C_0}")
        elif wk_divergence == "BULLISH":
            status_parts.append(f"{C_C}💡看涨背离{C_0}")

        # 意图K线
        if wk_intention == "INTENTION_BULL":
            status_parts.append(f"{C_G}意图阳{C_0}")
        elif wk_intention == "INTENTION_BEAR":
            status_parts.append(f"{C_R}意图阴{C_0}")
        elif wk_intention == "HESITATION":
            status_parts.append(f"{C_Y}犹豫{C_0}")

        # 威科夫信号
        sig_str = ""
        if wk_signal:
            if "BUY" in wk_signal:
                sig_str = f" → {C_GB}{wk_signal}{C_0}"
            elif "SELL" in wk_signal:
                sig_str = f" → {C_RB}{wk_signal}{C_0}"

        status_line = " | ".join(status_parts) if status_parts else "分析中"
        print(f"   📊 {symbol}: {status_line}{sig_str}")

        # 警告信息
        if wk_warning:
            print(f"      └─ {C_Y}警告: {wk_warning}{C_0}")

    print("-" * total_width)


def print_10m_surge_status(all_data):
    """v2.983: 打印10m暴涨暴跌信号状态"""
    total_width = 90

    # 筛选有10m信号的品种
    surge_symbols = [d for d in all_data if d.get("surge_10m_detected")]

    if not surge_symbols:
        return  # 无信号时不显示

    print("\n" + "=" * total_width)
    print(" 10m 暴涨暴跌信号 (v2.983)")
    print("-" * total_width)

    for d in surge_symbols:
        symbol = d["symbol"]
        surge_type = d.get("surge_10m_type", "NONE")
        surge_pct = d.get("surge_10m_pct", 0)

        if surge_type == "SURGE_UP":
            print(f"   {C_GB}🚀{C_0} {symbol}: 暴涨 {surge_pct:+.2f}%")
        elif surge_type == "SURGE_DOWN":
            print(f"   {C_RB}💥{C_0} {symbol}: 暴跌 {surge_pct:+.2f}%")

    print("-" * total_width)


def print_big_trend_protection_status(all_data):
    """v3.050: 打印大周期保护状态"""
    total_width = 90

    # 筛选触发了大周期保护的品种
    protected_symbols = [d for d in all_data if d.get("big_trend_protection") and d.get("big_trend_protection") != "NONE"]

    if not protected_symbols:
        return  # 无保护时不显示

    print("\n" + "=" * total_width)
    print(" 大周期保护状态 (v3.050)")
    print("-" * total_width)

    for d in protected_symbols:
        symbol = d["symbol"]
        protection = d.get("big_trend_protection", "NONE")

        if protection == "UP_HIGH_NO_SELL":
            print(f"   {C_C}🛡️{C_0} {symbol}: {C_GB}上涨趋势{C_0} + 高位 → 阻止SELL信号")
        elif protection == "DOWN_LOW_NO_BUY":
            print(f"   {C_C}🛡️{C_0} {symbol}: {C_RB}下跌趋势{C_0} + 低位 → 阻止BUY信号")

    print("-" * total_width)


def print_plugin_realtime_status(all_data):
    """v3.060: 打印SuperTrend外挂实时状态 (v0.6.1: 添加缓存信号显示)"""
    total_width = 100

    print("\n" + "=" * total_width)
    print(" SuperTrend 外挂实时状态 (v0.6.1 缓存机制)")
    print("-" * total_width)

    # 表头 - 使用固定宽度
    W_SYM = 10    # 品种
    W_MODE = 10   # 状态
    W_SIG = 6     # 使用信号
    W_CACHE = 6   # 缓存信号
    W_ST = 6      # ST趋势
    W_QQE = 8     # QQE
    W_MACD = 10   # MACD

    header = f" {pad_to_width('品种', W_SYM)} | {pad_to_width('状态', W_MODE)} | {pad_to_width('使用', W_SIG)} | {pad_to_width('缓存', W_CACHE)} | {pad_to_width('ST', W_ST)} | {rpad_to_width('QQE', W_QQE)} | {rpad_to_width('MACD', W_MACD)}"
    print(header)
    print("-" * total_width)

    for d in all_data:
        symbol = d["symbol"]
        plugin_active = d.get("plugin_active", False)
        plugin_mode = d.get("plugin_mode", "DISABLED")
        plugin_signal = d.get("plugin_signal", "NONE")
        plugin_cached = d.get("plugin_cached", "NONE")  # v0.6.1: 缓存信号
        st_trend = d.get("plugin_st_trend", "N/A")
        qqe = d.get("plugin_qqe", 0)
        macd = d.get("plugin_macd", 0)

        # 品种
        sym_str = pad_to_width(symbol, W_SYM)

        # 状态着色
        if plugin_active:
            if plugin_mode == "PLUGIN_AGREE":
                mode_str = C_GB + pad_to_width("AGREE", W_MODE) + C_0
                status_icon = "⚡"
            elif plugin_mode == "PLUGIN_CONFLICT":
                mode_str = C_M + pad_to_width("CONFLICT", W_MODE) + C_0
                status_icon = "⚡"
            else:
                mode_str = C_Y + pad_to_width(plugin_mode[:W_MODE], W_MODE) + C_0
                status_icon = "⚡"
        else:
            mode_str = pad_to_width("INACTIVE", W_MODE)
            status_icon = " "

        # 使用信号着色 (W_SIG=6)
        sig_text = plugin_signal[:W_SIG] if plugin_signal else "NONE"
        if "Buy" in plugin_signal or "BUY" in plugin_signal:
            sig_str = C_GB + pad_to_width(sig_text, W_SIG) + C_0
        elif "Sell" in plugin_signal or "SELL" in plugin_signal:
            sig_str = C_RB + pad_to_width(sig_text, W_SIG) + C_0
        else:
            sig_str = pad_to_width(sig_text, W_SIG)

        # v0.6.1: 缓存信号着色 (W_CACHE=6)
        cache_text = plugin_cached[:W_CACHE] if plugin_cached else "NONE"
        if "Buy" in plugin_cached or "BUY" in plugin_cached:
            cache_str = C_GB + pad_to_width(cache_text, W_CACHE) + C_0
        elif "Sell" in plugin_cached or "SELL" in plugin_cached:
            cache_str = C_RB + pad_to_width(cache_text, W_CACHE) + C_0
        else:
            cache_str = pad_to_width(cache_text, W_CACHE)

        # ST趋势着色
        if st_trend == "UP" or st_trend == 1:
            st_str = C_GB + pad_to_width("UP", W_ST) + C_0
        elif st_trend == "DOWN" or st_trend == -1:
            st_str = C_RB + pad_to_width("DOWN", W_ST) + C_0
        else:
            st_str = pad_to_width("N/A", W_ST)

        # QQE着色
        if isinstance(qqe, (int, float)):
            qqe_text = f"{qqe:+.2f}"
            if qqe > 0:
                qqe_str = C_GB + rpad_to_width(qqe_text, W_QQE) + C_0
            elif qqe < 0:
                qqe_str = C_RB + rpad_to_width(qqe_text, W_QQE) + C_0
            else:
                qqe_str = rpad_to_width(qqe_text, W_QQE)
        else:
            qqe_str = rpad_to_width("N/A", W_QQE)

        # MACD着色
        if isinstance(macd, (int, float)):
            macd_text = f"{macd:+.4f}"
            if macd > 0:
                macd_str = C_GB + rpad_to_width(macd_text, W_MACD) + C_0
            elif macd < 0:
                macd_str = C_RB + rpad_to_width(macd_text, W_MACD) + C_0
            else:
                macd_str = rpad_to_width(macd_text, W_MACD)
        else:
            macd_str = rpad_to_width("N/A", W_MACD)

        print(f" {status_icon}{sym_str} | {mode_str} | {sig_str} | {cache_str} | {st_str} | {qqe_str} | {macd_str}")

    print("-" * total_width)
    print(" 使用=本周期用的信号(来自上周期缓存) | 缓存=下周期将用的信号(本周期计算)")
    print(" 模式: AGREE=L1一致增强 | CONFLICT=L1冲突听外挂 | INACTIVE=L2正常工作")


def print_macd_divergence_status(all_data):
    """v3.496: 打印MACD背离外挂实时状态"""
    total_width = 100

    print("\n" + "=" * total_width)
    print(" MACD背离外挂实时状态 (v3.565: 已移交扫描引擎)")
    print("-" * total_width)

    # 表头 - 使用固定宽度
    W_SYM = 10    # 品种
    W_MODE = 12   # 状态
    W_TYPE = 8    # 背离类型
    W_STR = 6     # 强度
    W_L1 = 6      # L1趋势
    W_SL = 10     # 止损
    W_TP = 10     # 止盈

    header = f" {pad_to_width('品种', W_SYM)} | {pad_to_width('状态', W_MODE)} | {pad_to_width('背离', W_TYPE)} | {rpad_to_width('强度', W_STR)} | {pad_to_width('L1', W_L1)} | {rpad_to_width('止损', W_SL)} | {rpad_to_width('止盈', W_TP)}"
    print(header)
    print("-" * total_width)

    has_active = False

    for d in all_data:
        symbol = d["symbol"]
        div_data = d.get("macd_divergence", {})

        if not div_data:
            continue

        div_active = div_data.get("active", False)
        div_mode = div_data.get("mode", "DISABLED")
        div_type = div_data.get("div_type", "NONE")
        strength = div_data.get("strength_pct", 0)
        l1_trend = div_data.get("l1_trend", "")
        stop_loss = div_data.get("stop_loss", 0)
        take_profit = div_data.get("take_profit", 0)
        filter_reason = div_data.get("filter_reason", "")

        # 只显示有背离信号的品种
        if div_type == "NONE" and not div_active:
            continue

        has_active = True

        # 品种
        sym_str = pad_to_width(symbol, W_SYM)

        # 状态着色
        if div_active:
            mode_str = C_GB + pad_to_width("ACTIVE", W_MODE) + C_0
            status_icon = "⚡"
        elif div_mode == "FILTERED":
            mode_str = C_Y + pad_to_width("FILTERED", W_MODE) + C_0
            status_icon = "⚠"
        elif div_mode == "SIGNAL_FOUND":
            mode_str = C_M + pad_to_width("SIGNAL", W_MODE) + C_0
            status_icon = "📊"
        else:
            mode_str = pad_to_width(div_mode[:W_MODE], W_MODE)
            status_icon = " "

        # 背离类型着色
        if div_type == "BULLISH":
            type_str = C_GB + pad_to_width("底背离", W_TYPE) + C_0
        elif div_type == "BEARISH":
            type_str = C_RB + pad_to_width("顶背离", W_TYPE) + C_0
        else:
            type_str = pad_to_width("---", W_TYPE)

        # 强度着色
        if strength >= 50:
            str_str = C_GB + rpad_to_width(f"{strength:.0f}%", W_STR) + C_0
        elif strength >= 30:
            str_str = C_G + rpad_to_width(f"{strength:.0f}%", W_STR) + C_0
        else:
            str_str = rpad_to_width(f"{strength:.0f}%", W_STR)

        # L1趋势着色
        if l1_trend == "UP":
            l1_str = C_GB + pad_to_width("UP", W_L1) + C_0
        elif l1_trend == "DOWN":
            l1_str = C_RB + pad_to_width("DOWN", W_L1) + C_0
        else:
            l1_str = pad_to_width(l1_trend if l1_trend else "N/A", W_L1)

        # 止损止盈
        if stop_loss > 0:
            sl_str = rpad_to_width(f"{stop_loss:.2f}", W_SL)
        else:
            sl_str = rpad_to_width("---", W_SL)

        if take_profit > 0:
            tp_str = rpad_to_width(f"{take_profit:.2f}", W_TP)
        else:
            tp_str = rpad_to_width("---", W_TP)

        print(f" {status_icon}{sym_str} | {mode_str} | {type_str} | {str_str} | {l1_str} | {sl_str} | {tp_str}")

        # 如果被过滤，显示原因
        if filter_reason:
            print(f"   └─ 过滤原因: {filter_reason}")

    if not has_active:
        print(" (v3.565: MACD背离已移交扫描引擎，15分钟周期，仅震荡市激活)")

    print("-" * total_width)
    print(" 底背离=价格新低+MACD抬高→买入 | 顶背离=价格新高+MACD降低→卖出")
    print(" v3.565: 信号由扫描引擎产生，通过/p0_signal发送到主程序执行")


def print_supertrend_plugin_status():
    """v3.100: 打印L1模块准确率统计表格 (符合CLAUDE_CODE_PROMPT_V4要求)"""
    total_width = 90

    # 读取诊断文件
    diag_data = load_json_file(PLUGIN_DIAGNOSIS_FILE)

    if not diag_data:
        return  # 无数据时不显示

    print("\n" + "=" * total_width)
    print(" L1 模块准确率统计 (v3.100)")
    print("-" * total_width)

    # 显示统计信息
    stats = diag_data.get("stats", {})
    if stats:
        total_samples = stats.get("total", 0)

        # L1模块准确率
        ai_stats = stats.get("AI", {})
        human_stats = stats.get("HUMAN", {})
        tech_stats = stats.get("TECH", {})

        def calc_accuracy(s):
            total = s.get("total", 0)
            if total == 0:
                return 0.0
            match = s.get("MATCH", 0)
            return match / total * 100

        def get_total(s):
            return s.get("total", s.get("MATCH", 0) + s.get("OPPOSITE", 0) + s.get("MISS", 0) + s.get("FALSE_ALARM", 0))

        ai_acc = calc_accuracy(ai_stats)
        human_acc = calc_accuracy(human_stats)
        tech_acc = calc_accuracy(tech_stats)

        # 找出最差模块
        worst_module = ""
        min_acc = min(ai_acc, human_acc, tech_acc)
        if human_acc == min_acc and human_acc < 50:
            worst_module = "Human"
        elif ai_acc == min_acc and ai_acc < 50:
            worst_module = "AI"
        elif tech_acc == min_acc and tech_acc < 50:
            worst_module = "Tech"

        # 颜色编码
        def acc_color(acc):
            if acc >= 60:
                return C_GB
            elif acc >= 50:
                return C_G
            elif acc >= 40:
                return C_Y
            else:
                return C_R

        # 表格标题
        print(f" {'模块':<8} | {'样本数':>6} | {'准确率':>6} | {'MATCH':>5} | {'OPPOSITE':>8} | {'MISS':>4} | 状态")
        print("-" * total_width)

        # AI行
        ai_status = "← 最差" if worst_module == "AI" else ""
        print(f" {'AI':<8} | {get_total(ai_stats):>6} | {acc_color(ai_acc)}{ai_acc:5.1f}%{C_0} | {ai_stats.get('MATCH',0):>5} | {ai_stats.get('OPPOSITE',0):>8} | {ai_stats.get('MISS',0):>4} | {C_R}{ai_status}{C_0}")

        # Human行
        human_status = "← 最差，需优化" if worst_module == "Human" else ""
        print(f" {'Human':<8} | {get_total(human_stats):>6} | {acc_color(human_acc)}{human_acc:5.1f}%{C_0} | {human_stats.get('MATCH',0):>5} | {human_stats.get('OPPOSITE',0):>8} | {human_stats.get('MISS',0):>4} | {C_R}{human_status}{C_0}")

        # Tech行
        tech_status = "← 最差" if worst_module == "Tech" else ""
        print(f" {'Tech':<8} | {get_total(tech_stats):>6} | {acc_color(tech_acc)}{tech_acc:5.1f}%{C_0} | {tech_stats.get('MATCH',0):>5} | {tech_stats.get('OPPOSITE',0):>8} | {tech_stats.get('MISS',0):>4} | {C_R}{tech_status}{C_0}")

        print("-" * total_width)
        print(" 说明: MATCH=正确 | OPPOSITE=方向反了 | MISS=错过信号")

    # 最近的外挂信号
    recent = diag_data.get("recent_signals", [])
    if recent:
        print("-" * total_width)
        print("   🔌 最近外挂信号 (最新5条):")
        for sig in recent[-5:]:
            symbol = sig.get("symbol", "?")
            plugin_signal = sig.get("plugin_signal", "?")
            mode = sig.get("mode", "?")
            ts = sig.get("timestamp", "?")

            # 信号颜色
            sig_color = C_GB if "BUY" in plugin_signal else C_RB if "SELL" in plugin_signal else C_Y
            # 模式颜色
            mode_color = C_C if mode == "PLUGIN_AGREE" else C_M if mode == "PLUGIN_CONFLICT" else C_0

            print(f"      [{ts[-8:]}] {symbol:8s} → {sig_color}{plugin_signal:10s}{C_0} ({mode_color}{mode}{C_0})")

    print("-" * total_width)


def print_v3300_module_status(all_data):
    """v3.320: 打印L1五模块状态 (增强版 - 按L1流程展示)"""
    total_width = 120

    print("\n" + "=" * total_width)
    print(" v3.380 L1五模块决策流程 (AI+Tech双重验证 → DeepSeek趋势仲裁 → Human/Grid → 信号)")
    print("-" * total_width)

    # 第一行表头: AI+Tech双重验证 (v3.380: 添加当前趋势列)
    print(" " + C_C + "【Step 1: AI+Tech双重验证 → 大周期/当前周期趋势】" + C_0)
    # v3.380: 使用pad_to_width对齐中文，添加当前趋势列
    header1 = f" {pad_to_width('品种', 10)} | {pad_to_width('AI判断', 10)} | {pad_to_width('Tech判断', 10)} | {'ADX':>6s} | {'Chop':>6s} | {pad_to_width('一致性', 10)} | {pad_to_width('x4趋势', 8)} | {pad_to_width('当前趋势', 8)}"
    print(header1)
    print("-" * total_width)

    for d in all_data:
        symbol = d["symbol"]
        ai_x4 = str(d.get("v3300_ai_x4_regime", "N/A"))[:10]
        tech_regime = str(d.get("v3300_tech_regime", "N/A"))[:10]
        adx = d.get("v3300_adx", 0)
        chop = d.get("v3300_chop", 0)
        consensus = d.get("v3300_ai_consensus", "N/A")
        big_trend = d.get("v3300_ai_big_trend", "N/A")
        current_trend = d.get("v3300_current_trend", "SIDE")  # v3.380: 当前周期趋势

        # v3.320: 使用pad_to_width对齐
        sym_str = pad_to_width(symbol, 10)
        ai_str = pad_to_width(ai_x4, 10)
        tech_str = pad_to_width(tech_regime, 10)

        # 一致性着色 (v3.330: 支持DEEPSEEK_ARBITER)
        if consensus == "AGREE":
            cons_str = C_GB + pad_to_width("AI+T一致", 10) + C_0
        elif consensus == "DEEPSEEK_ARBITER":
            cons_str = C_M + pad_to_width("DS仲裁", 10) + C_0
        elif consensus == "DISAGREE":
            cons_str = C_Y + pad_to_width("AI+T分歧", 10) + C_0
        elif consensus == "TECH_ONLY":
            cons_str = C_C + pad_to_width("Tech兜底", 10) + C_0
        else:
            cons_str = pad_to_width(str(consensus)[:10], 10)

        # 大趋势着色 (x4周期)
        if big_trend == "UP":
            trend_str = C_GB + pad_to_width(big_trend, 8) + C_0
        elif big_trend == "DOWN":
            trend_str = C_RB + pad_to_width(big_trend, 8) + C_0
        else:
            trend_str = C_Y + pad_to_width(str(big_trend)[:8], 8) + C_0

        # v3.380: 当前趋势着色 (当前周期)
        # v3.441: 恢复检测显示RCVR标记
        # v3.630: 准确率覆盖显示方法名前缀
        recovery_detected = d.get("v3300_recovery_detected", False)
        acc_override = d.get("accuracy_override", False)
        acc_method = d.get("accuracy_override_method", "")

        # v3.630: 覆盖时显示方法缩写前缀 (C:=CNN, V:=Vision, R:=Rule, F:=Fused)
        method_prefix_map = {"CNN": "C:", "Vision": "V:", "Rule": "R:", "Fused": "F:"}
        override_prefix = method_prefix_map.get(acc_method, "") if acc_override else ""

        if current_trend == "UP":
            curr_trend_str = C_GB + pad_to_width(override_prefix + current_trend, 8) + C_0
        elif current_trend == "DOWN":
            curr_trend_str = C_RB + pad_to_width(override_prefix + current_trend, 8) + C_0
        elif recovery_detected:
            # v3.441: 恢复检测 -> 显示RCVR标记
            curr_trend_str = C_C + pad_to_width("RCVR", 8) + C_0
        else:
            curr_trend_str = C_Y + pad_to_width(override_prefix + str(current_trend)[:8], 8) + C_0

        # ADX着色 (>=25为强趋势)
        adx_val = float(adx) if adx else 0
        if adx_val >= 25:
            adx_str = C_GB + f"{adx_val:6.1f}" + C_0
        elif adx_val >= 20:
            adx_str = C_Y + f"{adx_val:6.1f}" + C_0
        else:
            adx_str = f"{adx_val:6.1f}"

        # Chop着色 (<50为趋势)
        chop_val = float(chop) if chop else 50
        if chop_val < 50:
            chop_str = C_GB + f"{chop_val:6.1f}" + C_0
        elif chop_val > 60:
            chop_str = C_R + f"{chop_val:6.1f}" + C_0
        else:
            chop_str = f"{chop_val:6.1f}"

        # v3.380: 添加当前趋势列
        row = f" {sym_str} | {ai_str} | {tech_str} | {adx_str} | {chop_str} | {cons_str} | {trend_str} | {curr_trend_str}"
        print(row)

    # 第二行: Human + Tech + Grid + 信号
    print("-" * total_width)
    print(" " + C_C + "【Step 2-4: Human逆小(道氏理论) → Tech强度 → Grid位置 → 最终信号】" + C_0)
    # v3.370: 添加道氏理论和L2策略列
    header2 = f" {pad_to_width('品种', 10)} | {pad_to_width('Human阶段', 14)} | {pad_to_width('道氏', 6)} | {pad_to_width('L2策略', 14)} | {pad_to_width('Tech', 6)} | {pad_to_width('Grid', 10)} | {pad_to_width('L1信号', 10)}"
    print(header2)
    print("-" * total_width)

    for d in all_data:
        symbol = d["symbol"]
        human_phase = str(d.get("v3300_human_phase", "N/A"))[:14]
        dow_trend = d.get("v3300_dow_trend", "side")  # v3.370: 道氏理论
        l2_strategy = d.get("l2_strategy", "NEUTRAL")  # v3.370: L2策略
        tech_strength = d.get("v3300_tech_strength", "N/A")
        grid_position = str(d.get("v3300_grid_position", "N/A"))[:10]
        grid_rel = d.get("v3300_grid_relative", 0)
        signal = d.get("v3300_signal", "N/A")

        # v3.320: 使用pad_to_width对齐
        sym_str = pad_to_width(symbol, 10)

        # Human阶段着色
        if "STABILIZING" in human_phase or "EXHAUSTING" in human_phase:
            human_str = C_GB + pad_to_width(human_phase, 14) + C_0
        elif "IN_PROGRESS" in human_phase:
            human_str = C_Y + pad_to_width(human_phase, 14) + C_0
        elif "MAIN_TREND" in human_phase:
            human_str = C_C + pad_to_width(human_phase, 14) + C_0
        else:
            human_str = pad_to_width(human_phase, 14)

        # v3.370: 道氏理论着色
        if dow_trend == "up":
            dow_str = C_GB + pad_to_width("UP", 6) + C_0
        elif dow_trend == "down":
            dow_str = C_RB + pad_to_width("DOWN", 6) + C_0
        else:
            dow_str = C_Y + pad_to_width("SIDE", 6) + C_0

        # v3.370: L2策略着色
        if l2_strategy == "TREND_PULLBACK":
            l2s_str = C_C + pad_to_width("顺势回调", 14) + C_0
        elif l2_strategy == "RANGE_REVERSAL":
            l2s_str = C_Y + pad_to_width("高抛低吸", 14) + C_0
        else:
            l2s_str = pad_to_width(str(l2_strategy)[:14], 14)

        # Tech强度着色
        if tech_strength == "STRONG":
            tech_str2 = C_GB + pad_to_width("强", 6) + C_0
        else:
            tech_str2 = C_Y + pad_to_width("弱", 6) + C_0

        # Grid位置着色
        if "BREAKOUT_UP" in grid_position:
            grid_str = C_GB + pad_to_width(grid_position, 10) + C_0
        elif "BREAKOUT_DOWN" in grid_position:
            grid_str = C_RB + pad_to_width(grid_position, 10) + C_0
        elif "BOX_LOW" in grid_position:
            grid_str = C_G + pad_to_width(grid_position, 10) + C_0
        elif "BOX_HIGH" in grid_position:
            grid_str = C_R + pad_to_width(grid_position, 10) + C_0
        else:
            grid_str = pad_to_width(grid_position, 10)

        # L1信号着色
        if signal in ["STRONG_BUY", "BUY"]:
            sig_str = C_GB + pad_to_width(str(signal)[:10], 10) + C_0
        elif signal in ["STRONG_SELL", "SELL"]:
            sig_str = C_RB + pad_to_width(str(signal)[:10], 10) + C_0
        else:
            sig_str = pad_to_width(str(signal)[:10], 10)

        row = f" {sym_str} | {human_str} | {dow_str} | {l2s_str} | {tech_str2} | {grid_str} | {sig_str}"
        print(row)

    print("-" * total_width)
    print(" 道氏理论: " + C_GB + "UP" + C_0 + "=HH+HL | " + C_RB + "DOWN" + C_0 + "=LH+LL | " + C_Y + "SIDE" + C_0 + "=无明确趋势")
    print(" L2策略: " + C_C + "顺势回调" + C_0 + "=道氏UP/DOWN时 | " + C_Y + "高抛低吸" + C_0 + "=道氏SIDE时")


def print_plugin_trade_freeze_status():
    """v3.575: 外挂交易统计 & 冻结状态面板 (当日24小时版)
    显示每个外挂当日的执行买/卖次数、持仓数、已平仓次数和冻结品种。
    v3.575: 改为只显示当前24小时(纽约日期)的交易数据
    """
    total_width = 100

    # --- 读取所有状态文件 ---
    profit_state = get_plugin_profit_state() or {}
    plugin_stats = profit_state.get("plugin_stats", {})

    # v3.575: 获取当日(纽约时区)的daily_stats
    try:
        import pytz
        ny_tz = pytz.timezone('America/New_York')
        today_ny = datetime.now(ny_tz).strftime("%Y-%m-%d")
    except:
        today_ny = datetime.now().strftime("%Y-%m-%d")
    daily_stats = profit_state.get("daily_stats", {}).get(today_ny, {})
    open_entries = profit_state.get("open_entries", {})

    # 各外挂的冻结状态文件
    tracking_st = get_tracking_state() or {}
    scalping_st = get_scalping_state() or {}
    supertrend_st = get_supertrend_scan_state() or {}
    rob_hoffman_st = get_rob_hoffman_state() or {}
    double_pattern_st = get_double_pattern_state() or {}
    feiyun_st = get_feiyun_state() or {}
    macd_divergence_st = get_macd_divergence_state() or {}  # v3.565
    supertrend_av2_st = get_supertrend_av2_state() or {}

    # 外挂名 → 状态数据 (symbols dict)
    PLUGIN_FREEZE_MAP = {
        "P0-Tracking": tracking_st.get("symbols", {}),
        "Chandelier+ZLSMA": scalping_st.get("symbols", {}),
        "SuperTrend": supertrend_st.get("symbols", {}),
        "SuperTrend+AV2": supertrend_av2_st.get("symbols", {}),
        "RobHoffman": rob_hoffman_st.get("symbols", {}),
        "DoublePattern": double_pattern_st.get("symbols", {}),
        "Feiyun": feiyun_st.get("symbols", {}),
        "MACD背离": macd_divergence_st.get("symbols", {}),  # v3.565
    }

    # 统计open_entries中各外挂的持仓数 → {asset_type: {plugin: count}}
    open_by_plugin = {}
    for sym, entries in open_entries.items():
        for entry in entries:
            atype = entry.get("asset_type", "crypto")
            pname = entry.get("plugin", "")
            open_by_plugin.setdefault(atype, {}).setdefault(pname, 0)
            open_by_plugin[atype][pname] += 1

    # yfinance符号 → 短名称
    YF_SHORT = {
        "BTC-USD": "BTC", "ETH-USD": "ETH",
        "SOL-USD": "SOL", "ZEC-USD": "ZEC",
    }
    # 加密货币yfinance符号集合
    CRYPTO_YF = {"BTC-USD", "ETH-USD", "SOL-USD", "ZEC-USD"}

    def _shorten(sym):
        return YF_SHORT.get(sym, sym)

    def _is_crypto_sym(sym):
        return sym in CRYPTO_YF

    def _get_frozen_symbols(symbols_dict, is_crypto):
        """从状态dict中提取冻结品种列表 → [(短名称, 剩余时间)]"""
        frozen = []
        for sym, st in symbols_dict.items():
            if _is_crypto_sym(sym) != is_crypto:
                continue
            freeze_str = st.get("freeze_until", "")
            if is_symbol_frozen(freeze_str):
                remaining = format_freeze_remaining(freeze_str)
                frozen.append(f"{_shorten(sym)}{remaining}")
        return frozen

    # 固定外挂顺序 (按资产类型)
    CRYPTO_PLUGINS = [
        "P0-Tracking", "P0-Open", "Chandelier+ZLSMA",
        "SuperTrend", "SuperTrend+AV2", "RobHoffman",
        "DoublePattern", "Feiyun", "MACD背离",
    ]
    STOCK_PLUGINS = [
        "P0-Tracking", "SuperTrend", "SuperTrend+AV2",
        "RobHoffman", "DoublePattern", "Feiyun", "MACD背离",
    ]

    # 列宽
    W_NAME = 18
    W_BS = 7     # 执行B/S
    W_OPEN = 5   # 持仓
    W_DONE = 6   # 已平仓

    print("\n" + "=" * total_width)
    print(f" 外挂交易 & 冻结状态 (当日: {today_ny})")
    print("=" * total_width)

    def _print_section(label, plugins, asset_type, is_crypto):
        print(f" {C_C}{label}{C_0}")
        print(
            f" {pad_to_width('外挂名', W_NAME)}"
            f"| {rpad_to_width('今日B/S', W_BS)}"
            f"| {rpad_to_width('持仓', W_OPEN)}"
            f"| {rpad_to_width('今日平', W_DONE)}"
            f"| 冻结品种"
        )
        print("-" * total_width)

        # v3.575: 使用当日daily_stats而非累计plugin_stats
        day_stats = daily_stats.get(asset_type, {})
        open_map = open_by_plugin.get(asset_type, {})

        for pname in plugins:
            # v3.575: 从当日统计获取B/S
            d = day_stats.get(pname, {})
            buys = d.get("buy", 0)
            sells = d.get("sell", 0)
            # 当日已平仓 (需要从completed_trades筛选，这里用wins计数)
            closed = d.get("wins", 0) + d.get("losses", 0)
            open_cnt = open_map.get(pname, 0)

            bs_str = f"{buys}/{sells}"

            # 冻结品种
            syms_dict = PLUGIN_FREEZE_MAP.get(pname, {})
            if syms_dict:
                frozen_list = _get_frozen_symbols(syms_dict, is_crypto)
                if frozen_list:
                    freeze_str = f"{C_M}{' '.join(frozen_list)}{C_0}"
                else:
                    freeze_str = f"{C_G}-{C_0}"
            else:
                # 无冻结状态文件 (P0-Open, MACD背离)
                freeze_str = f"{C_G}-{C_0}"

            row = (
                f" {pad_to_width(pname, W_NAME)}"
                f"| {rpad_to_width(bs_str, W_BS)}"
                f"| {rpad_to_width(str(open_cnt), W_OPEN)}"
                f"| {rpad_to_width(str(closed), W_DONE)}"
                f"| {freeze_str}"
            )
            print(row)

        print("-" * total_width)

    # 加密货币
    _print_section("加密货币", CRYPTO_PLUGINS, "crypto", True)
    print("")
    # 美股
    _print_section("美股", STOCK_PLUGINS, "stock", False)
    print("=" * total_width)


def print_accuracy_table(validation_data, calibration_data):
    total_width = 70

    print("\n" + "=" * total_width)
    print(" L1 三方准确率")
    print("-" * total_width)

    if not validation_data:
        print(" " + C_Y + "⚠️ 暂无验证数据" + C_0)
        print("-" * total_width)
        return

    stats = validation_data.get("stats", {})
    if not stats:
        print(" " + C_Y + "⚠️ 暂无验证数据" + C_0)
        print("-" * total_width)
        return

    W = {"品种": 8, "样本": 6, "AI准确": 6, "H准确": 6, "T准确": 6, "总准确": 6}
    cols = list(W.keys())

    header = "|" + "".join(" " + pad_to_width(col, W[col]) + " |" for col in cols)
    print(header)
    print("-" * total_width)

    for symbol in CRYPTO_SYMBOLS + STOCK_SYMBOLS:
        s = stats.get(symbol, {})
        total = s.get("total", 0)

        row = "| " + pad_to_width(symbol[:8], W["品种"]) + " |"
        if total > 0:
            row += " " + rpad_to_width(str(total), W["样本"]) + " |"
            row += " " + color_acc(s.get("ai_accuracy", 0.5), W["AI准确"]) + " |"
            row += " " + color_acc(s.get("human_accuracy", 0.5), W["H准确"]) + " |"
            row += " " + color_acc(s.get("tech_accuracy", 0.5), W["T准确"]) + " |"
            row += " " + color_acc(s.get("overall_accuracy", 0.5), W["总准确"]) + " |"
        else:
            row += " " + rpad_to_width("-", W["样本"]) + " |"
            row += " " + rpad_to_width("-", W["AI准确"]) + " |"
            row += " " + rpad_to_width("-", W["H准确"]) + " |"
            row += " " + rpad_to_width("-", W["T准确"]) + " |"
            row += " " + rpad_to_width("-", W["总准确"]) + " |"
        print(row)

    print("-" * total_width)


def print_model_status(xgboost_stats, cnn_stats):
    total_width = 70

    # XGBoost
    print("\n" + "=" * total_width + "\n XGBoost Tech 模型\n" + "-" * total_width)
    if not xgboost_stats:
        print(" " + C_Y + "⚠️ 未训练" + C_0)
    else:
        val_acc = xgboost_stats.get("val_accuracy", 0)
        acc_color = C_GB if val_acc >= 0.60 else C_G if val_acc >= 0.50 else C_Y if val_acc >= 0.40 else C_R
        print(" 样本: %d训练/%d验证 | 准确率: %s%.1f%%%s" % (
            xgboost_stats.get("train_samples", 0), xgboost_stats.get("val_samples", 0), acc_color, val_acc * 100, C_0))
    print("-" * total_width)

    # CNN Human
    print("\n" + "=" * total_width + "\n CNN Human 模型\n" + "-" * total_width)
    if not cnn_stats:
        print(" " + C_Y + "⚠️ 未训练" + C_0)
        print("    步骤1: python labeling_tool.py  (标注K线图)")
        print("    步骤2: python train_cnn_human.py (训练模型)")
    else:
        val_acc = cnn_stats.get("val_accuracy", 0)
        acc_color = C_GB if val_acc >= 0.60 else C_G if val_acc >= 0.50 else C_Y if val_acc >= 0.40 else C_R
        print(" 样本: %d训练/%d验证 | 准确率: %s%.1f%%%s" % (
            cnn_stats.get("train_samples", 0), cnn_stats.get("val_samples", 0), acc_color, val_acc * 100, C_0))
    print("-" * total_width)


def print_regime_accuracy(regime_data):
    """v3.570: 打印市场状态判断准确率(含Vision对比)"""
    total_width = 108

    print("\n" + "=" * total_width)
    print(" 市场状态判断准确率 (v3.570)")
    print("-" * total_width)

    if not regime_data:
        print(" " + C_Y + "⚠️ 暂无数据" + C_0)
        print("-" * total_width)
        return

    stats = regime_data.get("stats", {})
    if not stats:
        print(" " + C_Y + "⚠️ 暂无验证数据" + C_0)
        print("-" * total_width)
        return

    W = {"品种": 8, "样本": 5, "总准确": 7, "AI": 6, "Human": 6, "Tech": 6, "V当前": 6, "V-X4": 6, "趋势": 5, "震荡": 5}
    cols = list(W.keys())

    header = "|" + "".join(" " + pad_to_width(col, W[col]) + " |" for col in cols)
    print(header)
    print("-" * total_width)

    for symbol in CRYPTO_SYMBOLS + STOCK_SYMBOLS:
        s = stats.get(symbol, {})
        total = s.get("total", 0)

        row = "| " + pad_to_width(symbol[:8], W["品种"]) + " |"
        if total > 0:
            row += " " + rpad_to_width(str(total), W["样本"]) + " |"
            row += " " + color_acc(s.get("regime_accuracy", 0.5), W["总准确"]) + " |"
            row += " " + color_acc(s.get("ai_accuracy", 0.5), W["AI"]) + " |"
            row += " " + color_acc(s.get("human_accuracy", 0.5), W["Human"]) + " |"
            row += " " + color_acc(s.get("tech_accuracy", 0.5), W["Tech"]) + " |"
            # v3.570: Vision准确率
            v_cur_acc = s.get("vision_current_accuracy")
            v_x4_acc = s.get("vision_x4_accuracy")
            v_cur_total = s.get("vision_current_total", 0)
            v_x4_total = s.get("vision_x4_total", 0)
            if v_cur_total > 0 and v_cur_acc is not None:
                row += " " + color_acc(v_cur_acc, W["V当前"]) + " |"
            else:
                row += " " + rpad_to_width("-", W["V当前"]) + " |"
            if v_x4_total > 0 and v_x4_acc is not None:
                row += " " + color_acc(v_x4_acc, W["V-X4"]) + " |"
            else:
                row += " " + rpad_to_width("-", W["V-X4"]) + " |"
            row += " " + rpad_to_width(str(s.get("trending_count", 0)), W["趋势"]) + " |"
            row += " " + rpad_to_width(str(s.get("ranging_count", 0)), W["震荡"]) + " |"
        else:
            row += " " + rpad_to_width("-", W["样本"]) + " |"
            row += " " + rpad_to_width("-", W["总准确"]) + " |"
            row += " " + rpad_to_width("-", W["AI"]) + " |"
            row += " " + rpad_to_width("-", W["Human"]) + " |"
            row += " " + rpad_to_width("-", W["Tech"]) + " |"
            row += " " + rpad_to_width("-", W["V当前"]) + " |"
            row += " " + rpad_to_width("-", W["V-X4"]) + " |"
            row += " " + rpad_to_width("-", W["趋势"]) + " |"
            row += " " + rpad_to_width("-", W["震荡"]) + " |"
        print(row)

    print("-" * total_width)
    print(" 说明: 总准确=L1综合 | AI/Human/Tech=各方投票 | V当前=Vision当前周期 | V-X4=Vision X4周期")


def print_human_dual_track_table(dual_track_data):
    """v2.960: 打印Human双轨校准表"""
    total_width = 85

    print("\n" + "=" * total_width)
    print(" Human 双轨校准 (v2.960)")
    print("-" * total_width)

    if not dual_track_data:
        print(" " + C_Y + "⚠️ 暂无数据 (需要CNN模型和校准数据)" + C_0)
        print("-" * total_width)
        return

    stats = dual_track_data.get("stats", {})
    if not stats:
        print(" " + C_Y + "⚠️ 暂无校准数据" + C_0)
        print("-" * total_width)
        return

    W = {"品种": 8, "样本": 5, "规则准确": 7, "CNN准确": 7, "规则权重": 7, "CNN权重": 7, "融合准确": 7}
    cols = list(W.keys())

    header = "|" + "".join(" " + pad_to_width(col, W[col]) + " |" for col in cols)
    print(header)
    print("-" * total_width)

    for symbol in CRYPTO_SYMBOLS + STOCK_SYMBOLS:
        s = stats.get(symbol, {})
        rule_total = s.get("rule_total", 0)

        row = "| " + pad_to_width(symbol[:8], W["品种"]) + " |"
        if rule_total > 0:
            rule_acc = s.get("rule_correct", 0) / rule_total if rule_total > 0 else 0
            cnn_acc = s.get("cnn_correct", 0) / s.get("cnn_total", 1) if s.get("cnn_total", 0) > 0 else 0
            fused_acc = s.get("fused_correct", 0) / s.get("fused_total", 1) if s.get("fused_total", 0) > 0 else 0

            # 计算权重
            total_acc = rule_acc + cnn_acc
            if total_acc > 0 and rule_total >= 10:
                rule_weight = max(0.3, min(0.8, rule_acc / total_acc))
                cnn_weight = 1.0 - rule_weight
            else:
                rule_weight, cnn_weight = 0.7, 0.3

            row += " " + rpad_to_width(str(rule_total), W["样本"]) + " |"
            row += " " + color_acc(rule_acc, W["规则准确"]) + " |"
            row += " " + color_acc(cnn_acc, W["CNN准确"]) + " |"
            row += " " + rpad_to_width(f"{rule_weight:.0%}", W["规则权重"]) + " |"
            row += " " + rpad_to_width(f"{cnn_weight:.0%}", W["CNN权重"]) + " |"
            row += " " + color_acc(fused_acc, W["融合准确"]) + " |"
        else:
            row += " " + rpad_to_width("-", W["样本"]) + " |"
            row += " " + rpad_to_width("-", W["规则准确"]) + " |"
            row += " " + rpad_to_width("-", W["CNN准确"]) + " |"
            row += " " + rpad_to_width("70%", W["规则权重"]) + " |"
            row += " " + rpad_to_width("30%", W["CNN权重"]) + " |"
            row += " " + rpad_to_width("-", W["融合准确"]) + " |"
        print(row)

    print("-" * total_width)
    print(" 说明: 规则=现有v2.920算法 | CNN=1D-CNN模型 | 权重按准确率自动调整(30%-80%)")


def print_vision_status():
    """v3.570: Vision视觉分析最近状态面板(verbose模式)"""
    total_width = 60
    vision_status = load_json_file(VISION_STATUS_FILE)
    if not vision_status:
        return

    print("\n" + "=" * total_width)
    print(" Vision视觉分析状态 (v3.570)")
    print("-" * total_width)

    for symbol, info in vision_status.items():
        ts = info.get("timestamp", "")
        if ts:
            try:
                ts_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
            except Exception:
                ts_str = str(ts)
        else:
            ts_str = "N/A"

        tf = info.get("timeframe", "?")
        print(f" 品种: {symbol} ({tf}m) | 分析时间: {ts_str}")

        cur = info.get("current")
        x4 = info.get("x4")

        if cur:
            cur_regime = cur.get("regime", "?")
            cur_dir = cur.get("direction", "?")
            cur_conf = cur.get("confidence", 0)
            print(f"  Vision当前: {cur_regime} {cur_dir} (conf={cur_conf:.2f})")
        else:
            print("  Vision当前: N/A")

        if x4:
            x4_regime = x4.get("regime", "?")
            x4_dir = x4.get("direction", "?")
            x4_conf = x4.get("confidence", 0)
            print(f"  Vision X4:  {x4_regime} {x4_dir} (conf={x4_conf:.2f})")
        else:
            print("  Vision X4:  N/A")

        # API状态
        cg_ok = info.get("chatgpt_success", False)
        ds_ok = info.get("deepseek_success", False)
        latency = info.get("latency_ms", 0)
        cg_str = C_G + "Y" + C_0 if cg_ok else C_R + "N" + C_0
        ds_str = C_G + "Y" + C_0 if ds_ok else C_R + "N" + C_0
        print(f"  API: ChatGPT {cg_str} | DeepSeek {ds_str} | 总延迟: {latency}ms")

        print("-" * total_width)


def print_vision_daily_report():
    """v3.620: L1准确率5方对比报告面板(始终显示, 数据来自state/vision_daily_report.json)"""
    report_data = load_json_file(VISION_DAILY_REPORT_FILE)
    if not report_data:
        return

    total_width = 100
    report_date = report_data.get("date", "N/A")

    print("\n" + "=" * total_width)
    print(f" L1准确率对比报告 (v3.620) | {report_date}")
    print("-" * total_width)

    # v3.620: 5方准确率对比表 (dual_track数据)
    accuracy_comparison = report_data.get("accuracy_comparison", {})
    if accuracy_comparison:
        print(f" {'品种':<10} {'规则':>7} {'CNN':>7} {'融合':>7} {'Vision':>8} {'图像CNN':>8} {'当前用':>8}")
        print(" " + "-" * 65)
        for sym, acc in accuracy_comparison.items():
            rule = f"{acc['rule']*100:.1f}%" if acc.get('rule') is not None else "---"
            cnn = f"{acc['cnn']*100:.1f}%" if acc.get('cnn') is not None else "---"
            fused = f"{acc['fused']*100:.1f}%" if acc.get('fused') is not None else "---"
            vision = f"{acc['vision']*100:.1f}%" if acc.get('vision') is not None else "---"
            image_cnn = f"{acc['image_cnn']*100:.1f}%" if acc.get('image_cnn') is not None else "---"
            using = acc.get("l1_using", "融合")
            # 高亮当前使用的方法
            if using == "cnn":
                using_str = f"{C_G}CNN✓{C_0}"
            elif using == "vision":
                using_str = f"{C_G}Vision✓{C_0}"
            else:
                using_str = f"融合"
            print(f" {sym:<10} {rule:>7} {cnn:>7} {fused:>7} {vision:>8} {image_cnn:>8}  {using_str}")

    # 总体对比 (旧格式兼容)
    summary = report_data.get("summary", {})
    if summary and not accuracy_comparison:
        l1_acc = summary.get("l1_accuracy", 0)
        v_cur_acc = summary.get("vision_current_accuracy", 0)
        v_x4_acc = summary.get("vision_x4_accuracy", 0)
        print(" 总体对比:")
        print(f"   {'方法':<20} | {'准确率':>8}")
        print(f"   {'L1五模块(综合)':<20} | {l1_acc*100:>6.1f}%")
        print(f"   {'Vision当前周期':<20} | {v_cur_acc*100:>6.1f}%")
        print(f"   {'Vision X4周期':<20} | {v_x4_acc*100:>6.1f}%")

    # 各品种详情 (旧格式兼容)
    details = report_data.get("details", {})
    if details and not accuracy_comparison:
        print()
        print(f"   {'品种':<10} {'样本':>5} {'L1准确':>8} {'V当前':>8} {'V-X4':>8}")
        for sym, d in details.items():
            t = d.get("total", 0)
            if t > 0:
                l1a = d.get("l1_accuracy", 0)
                vca = d.get("vision_current_accuracy", 0)
                vxa = d.get("vision_x4_accuracy", 0)
                print(f"   {sym:<10} {t:>5} {l1a*100:>7.1f}% {vca*100:>7.1f}% {vxa*100:>7.1f}%")

    # 分歧样本
    disagreements = report_data.get("disagreements", [])
    if disagreements:
        print()
        print(" 分歧样本(Vision与L1不一致时谁对):")
        for item in disagreements[-10:]:
            ts = item.get("time", "")
            sym = item.get("symbol", "?")
            period = item.get("period", "?")
            l1_val = item.get("l1", "?")
            v_val = item.get("vision", "?")
            actual = item.get("actual", "?")
            winner = item.get("winner", "?")
            color = C_G if winner == "Vision" else (C_R if winner == "L1" else C_Y)
            print(f"   [{ts}] {sym} {period}: L1={l1_val} Vision={v_val} -> 实际{actual} -> {color}{winner}对{C_0}")

    # API统计
    api_stats = report_data.get("api_stats", {})
    if api_stats:
        print()
        print(" API统计:")
        agree_rate = api_stats.get("agree_rate", 0)
        cg_success = api_stats.get("chatgpt_success_rate", 0)
        ds_success = api_stats.get("deepseek_success_rate", 0)
        cg_latency = api_stats.get("chatgpt_avg_latency", 0)
        ds_latency = api_stats.get("deepseek_avg_latency", 0)
        print(f"   一致率: ChatGPT vs DeepSeek {agree_rate*100:.0f}%")
        print(f"   成功率: ChatGPT {cg_success*100:.0f}% | DeepSeek {ds_success*100:.0f}%")
        print(f"   延迟: ChatGPT {cg_latency:.1f}s | DeepSeek {ds_latency:.1f}s")

    print("-" * total_width)


def _generate_vision_daily_report_data(regime_data):
    """v3.620: 生成5方对比每日报告数据 (含dual_track准确率)"""
    if not regime_data:
        return None

    stats = regime_data.get("stats", {})
    records = regime_data.get("records", {})
    if not stats:
        return None

    report = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "summary": {},
        "details": {},
        "disagreements": [],
        "api_stats": {},
        "accuracy_comparison": {},  # v3.620: 5方对比
    }

    # v3.620: 读取dual_track数据，生成5方准确率对比
    dual_track = load_json_file(HUMAN_DUAL_TRACK_FILE)
    if dual_track and dual_track.get("stats"):
        dt_stats = dual_track["stats"]
        for sym, s in dt_stats.items():
            rule_total = s.get("rule_total", 0)
            if rule_total < 5:
                continue
            rule_acc = s.get("rule_correct", 0) / rule_total if rule_total > 0 else None
            cnn_acc = s.get("cnn_correct", 0) / s.get("cnn_total", 1) if s.get("cnn_total", 0) > 0 else None
            fused_acc = s.get("fused_correct", 0) / s.get("fused_total", 1) if s.get("fused_total", 0) > 0 else None
            vision_total = s.get("vision_total", 0)
            vision_acc = s.get("vision_correct", 0) / vision_total if vision_total >= 5 else None
            img_cnn_total = s.get("image_cnn_total", 0)
            img_cnn_acc = s.get("image_cnn_correct", 0) / img_cnn_total if img_cnn_total >= 5 else None

            # 判断当前L1用的是哪个
            l1_using = "融合"
            if cnn_acc is not None and fused_acc is not None and cnn_acc > fused_acc:
                l1_using = "cnn"
            if vision_acc is not None:
                l1_winner = max(cnn_acc or 0, fused_acc or 0)
                if vision_acc > l1_winner:
                    l1_using = "vision"

            report["accuracy_comparison"][sym] = {
                "rule": round(rule_acc, 3) if rule_acc is not None else None,
                "cnn": round(cnn_acc, 3) if cnn_acc is not None else None,
                "fused": round(fused_acc, 3) if fused_acc is not None else None,
                "vision": round(vision_acc, 3) if vision_acc is not None else None,
                "image_cnn": round(img_cnn_acc, 3) if img_cnn_acc is not None else None,
                "l1_using": l1_using,
                "samples": rule_total,
            }

    # 汇总准确率
    total_l1_correct = 0
    total_l1_count = 0
    total_v_cur_correct = 0
    total_v_cur_count = 0
    total_v_x4_correct = 0
    total_v_x4_count = 0

    for symbol in list(stats.keys()):
        s = stats[symbol]
        t = s.get("total", 0)
        if t == 0:
            continue

        l1_acc = s.get("regime_accuracy", 0)
        v_cur_acc = s.get("vision_current_accuracy", 0)
        v_x4_acc = s.get("vision_x4_accuracy", 0)
        v_cur_total = s.get("vision_current_total", 0)
        v_x4_total = s.get("vision_x4_total", 0)

        report["details"][symbol] = {
            "total": t,
            "l1_accuracy": l1_acc,
            "vision_current_accuracy": v_cur_acc if v_cur_total > 0 else 0,
            "vision_x4_accuracy": v_x4_acc if v_x4_total > 0 else 0,
        }

        total_l1_correct += s.get("regime_correct", 0)
        total_l1_count += t
        total_v_cur_correct += s.get("vision_current_correct", 0)
        total_v_cur_count += v_cur_total
        total_v_x4_correct += s.get("vision_x4_correct", 0)
        total_v_x4_count += v_x4_total

    report["summary"] = {
        "l1_accuracy": total_l1_correct / total_l1_count if total_l1_count > 0 else 0,
        "vision_current_accuracy": total_v_cur_correct / total_v_cur_count if total_v_cur_count > 0 else 0,
        "vision_x4_accuracy": total_v_x4_correct / total_v_x4_count if total_v_x4_count > 0 else 0,
    }

    # 收集分歧样本
    for symbol, recs in records.items():
        for rec in recs:
            if not rec.get("verified"):
                continue
            actual = rec.get("actual_regime")
            l1_regime = rec.get("regime")
            v_cur = rec.get("vision_current_regime")
            v_x4 = rec.get("vision_x4_regime")

            # 当前周期分歧
            if v_cur and l1_regime and v_cur != l1_regime and actual:
                ts_str = ""
                try:
                    ts_str = datetime.fromtimestamp(rec["timestamp"]).strftime("%H:%M")
                except Exception:
                    pass
                l1_right = (l1_regime == actual)
                v_right = (v_cur == actual)
                winner = "L1" if l1_right and not v_right else ("Vision" if v_right and not l1_right else "Both" if l1_right and v_right else "Neither")
                report["disagreements"].append({
                    "time": ts_str, "symbol": symbol, "period": "当前",
                    "l1": l1_regime, "vision": v_cur, "actual": actual, "winner": winner,
                })

            # X4周期分歧
            if v_x4 and l1_regime and v_x4 != l1_regime and actual:
                ts_str = ""
                try:
                    ts_str = datetime.fromtimestamp(rec["timestamp"]).strftime("%H:%M")
                except Exception:
                    pass
                l1_right = (l1_regime == actual)
                v_right = (v_x4 == actual)
                winner = "L1" if l1_right and not v_right else ("Vision" if v_right and not l1_right else "Both" if l1_right and v_right else "Neither")
                report["disagreements"].append({
                    "time": ts_str, "symbol": symbol, "period": "X4",
                    "l1": l1_regime, "vision": v_x4, "actual": actual, "winner": winner,
                })

    return report


def display(state, validation_data, calibration_data, xgboost_stats, cnn_stats, regime_data, dual_track_data):
    """v3.320: 精简版监控 - 按L1流程展示核心信息"""
    os.system('cls' if os.name == 'nt' else 'clear')

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("\n " + "=" * 120)
    print(" AIPRO 决策层监控 v3.570 | " + now + " | 趋势同步 + L1 Wyckoff + L2五大类评分 + Vision视觉分析")
    print(" " + "=" * 120)
    print(" 状态文件: " + STATE_FILE + " (更新: " + get_file_mtime(STATE_FILE) + ")")

    all_data = [get_symbol_data(state, s) for s in CRYPTO_SYMBOLS + STOCK_SYMBOLS]

    # ============================================================
    # 核心面板 1: 合并主面板+Scan Engine三方对比 (v3.620)
    # ============================================================
    print("\n" + "=" * 120 + "\n 主监控面板 + L1来源对比 (v3.630)\n" + "-" * 120)
    print_main_table(all_data)

    # ============================================================
    # 核心面板 3: 外挂交易 & 冻结状态 (v3.550 替代告警面板)
    # ============================================================
    print_plugin_trade_freeze_status()

    # ============================================================
    # 核心面板 4.1: Position Control状态 (v3.590)
    # ============================================================
    print_position_control_status(state)

    # ============================================================
    # 核心面板 5: 外挂利润分析 (v3.550)
    # ============================================================
    print_plugin_profit_report()

    # ============================================================
    # 核心面板 6: 准确率对比表 (v3.570, 含Vision对比，始终显示)
    # ============================================================
    print_regime_accuracy(regime_data)

    # ============================================================
    # 核心面板 7: Vision每日对比报告 (v3.570, 始终显示)
    # ============================================================
    print_vision_daily_report()

    # ============================================================
    # 可选面板 (仅在需要时显示)
    # ============================================================
    # 以下面板默认隐藏，可通过环境变量MONITOR_VERBOSE=1启用
    verbose = os.environ.get("MONITOR_VERBOSE", "0") == "1"

    if verbose:
        print_scan_engine_status()
        print_tracking_protection_status(state)
        print_scalping_status()  # v3.496: Chandelier+ZLSMA剥头皮
        print_all_plugin_status()  # v3.530: 统一外挂触发状态显示
        print_big_trend_protection_status(all_data)
        print_plugin_realtime_status(all_data)
        print_macd_divergence_status(all_data)  # v3.496: MACD背离外挂
        print_supertrend_plugin_status()
        print_diagnosis_panel(all_data)
        print_deepseek_status(all_data)
        print_wyckoff_status(all_data)
        print_10m_surge_status(all_data)
        print_accuracy_table(validation_data, calibration_data)
        print_human_dual_track_table(dual_track_data)
        print_model_status(xgboost_stats, cnn_stats)
        print_vision_status()  # v3.570: Vision视觉分析状态

    # ============================================================
    # 简化图例
    # ============================================================
    print("\n 图例:")
    print("   L1流程: AI+Tech双重验证(AGREE/DISAGREE) → Human逆小 → Tech强度 → Grid位置 → 信号")
    print("   " + C_GB + "AGREE" + C_0 + "=AI与Tech一致(高置信) | " + C_M + "DEEPSEEK_ARBITER" + C_0 + "=分歧时趋势仲裁")
    print("   ADX≥25=趋势 | Chop<50=趋势 | " + C_GB + "STRONG" + C_0 + "=强势 | " + C_G + "BOX_LOW" + C_0 + "=低位买点")
    print()
    print(" v3.570 | 刷新: %d秒 | MONITOR_VERBOSE=1 显示详细面板 | Ctrl+C退出" % REFRESH_INTERVAL)


def main():
    print(" 启动 AIPRO 决策监控 v3.570 (趋势同步 + L1 Wyckoff定位 + L2五大类评分 + Vision视觉分析)...")
    print(" 监控: " + STATE_FILE + " | 刷新: %d秒\n" % REFRESH_INTERVAL)

    last_cycle_minute = -1
    last_day = -1
    seen_plugin_triggers = set()  # 记录已处理的外挂触发
    vision_report_generated = False  # v3.570: Vision报告生成标记
    er_analysis_done_today = False  # v3.575: ER阈值分析标记
    retrospective_done_today = False  # v20: 回溯分析标记
    retrospective_weekly_done = False  # v20: 周报标记

    try:
        while True:
            now = datetime.now()
            current_cycle_minute = (now.minute // 30) * 30

            # v3.150: 检测周期切换
            if current_cycle_minute != last_cycle_minute:
                if last_cycle_minute != -1:
                    # 分析上一周期
                    analysis = diagnostics.analyze_cycle_end()
                    if analysis:
                        print(f"\n[诊断] 周期分析完成")

                # 重置新周期
                diagnostics.reset_cycle()
                seen_plugin_triggers.clear()
                last_cycle_minute = current_cycle_minute

            # v3.150: 检测日期切换，生成每日报告
            if now.day != last_day and now.hour >= 0:
                if last_day != -1:
                    report_file = diagnostics.generate_daily_report()
                    if report_file:
                        print(f"\n[诊断] 每日报告已生成: {report_file}")
                last_day = now.day

            # v3.570: 纽约8AM生成Vision每日对比报告
            try:
                import pytz
                ny_tz = pytz.timezone('America/New_York')
                ny_now = datetime.now(ny_tz)
                if ny_now.hour == 8 and ny_now.minute < 1 and not vision_report_generated:
                    regime_data_for_report = load_json_file(REGIME_VALIDATION_FILE)
                    report_data = _generate_vision_daily_report_data(regime_data_for_report)
                    if report_data:
                        # 保存到state文件供面板持续显示
                        os.makedirs("state", exist_ok=True)
                        with open(VISION_DAILY_REPORT_FILE, "w") as f:
                            json.dump(report_data, f, indent=2, default=str, ensure_ascii=False)
                        # 保存到logs目录
                        os.makedirs("logs", exist_ok=True)
                        date_str = ny_now.strftime("%Y%m%d")
                        log_file = f"logs/vision_report_{date_str}.txt"
                        with open(log_file, "w", encoding="utf-8") as f:
                            f.write(f"Vision 每日对比报告 - {report_data.get('date', '')}\n")
                            f.write(f"生成时间: {report_data.get('generated_at', '')}\n")
                            f.write("=" * 60 + "\n\n")
                            summary = report_data.get("summary", {})
                            f.write("总体对比:\n")
                            f.write(f"  L1五模块准确率: {summary.get('l1_accuracy', 0)*100:.1f}%\n")
                            f.write(f"  Vision当前周期: {summary.get('vision_current_accuracy', 0)*100:.1f}%\n")
                            f.write(f"  Vision X4周期:  {summary.get('vision_x4_accuracy', 0)*100:.1f}%\n\n")
                            details = report_data.get("details", {})
                            if details:
                                f.write("各品种详情:\n")
                                f.write(f"  {'品种':<10} {'样本':>5} {'L1':>8} {'V当前':>8} {'V-X4':>8}\n")
                                for sym, d in details.items():
                                    t = d.get("total", 0)
                                    if t > 0:
                                        f.write(f"  {sym:<10} {t:>5} {d.get('l1_accuracy',0)*100:>7.1f}% {d.get('vision_current_accuracy',0)*100:>7.1f}% {d.get('vision_x4_accuracy',0)*100:>7.1f}%\n")
                            disagreements = report_data.get("disagreements", [])
                            if disagreements:
                                f.write("\n分歧样本:\n")
                                for item in disagreements:
                                    f.write(f"  [{item.get('time','')}] {item.get('symbol','')} {item.get('period','')}: L1={item.get('l1','')} Vision={item.get('vision','')} -> 实际{item.get('actual','')} -> {item.get('winner','')}对\n")
                        print(f"\n[v3.570] Vision每日报告已生成: {log_file}")

                        # v3.620: 发送5方对比报告邮件
                        try:
                            acc_comp = report_data.get("accuracy_comparison", {})
                            if acc_comp:
                                email_lines = [
                                    f"L1准确率对比报告 | {report_data.get('date', '')}",
                                    "=" * 55,
                                    f"{'品种':<10} {'规则':>6} {'CNN':>6} {'融合':>6} {'Vision':>7} {'图CNN':>7} {'当前':>6}",
                                    "-" * 55,
                                ]
                                for sym, acc in acc_comp.items():
                                    r = f"{acc['rule']*100:.1f}%" if acc.get('rule') is not None else "---"
                                    c = f"{acc['cnn']*100:.1f}%" if acc.get('cnn') is not None else "---"
                                    fu = f"{acc['fused']*100:.1f}%" if acc.get('fused') is not None else "---"
                                    v = f"{acc['vision']*100:.1f}%" if acc.get('vision') is not None else "---"
                                    ic = f"{acc['image_cnn']*100:.1f}%" if acc.get('image_cnn') is not None else "---"
                                    u = acc.get("l1_using", "融合")
                                    email_lines.append(f"{sym:<10} {r:>6} {c:>6} {fu:>6} {v:>7} {ic:>7} {u:>6}")
                                email_body = "\n".join(email_lines)
                                import requests
                                try:
                                    requests.post(
                                        "http://localhost:5000/api/send_email",
                                        json={"subject": f"L1准确率报告 {report_data.get('date','')}",
                                              "body": email_body},
                                        timeout=10
                                    )
                                    print("[v3.620] 5方对比报告邮件已发送")
                                except Exception:
                                    print("[v3.620] 邮件API不可达，跳过")
                        except Exception as email_e:
                            print(f"[v3.620] 邮件发送异常: {email_e}")

                    vision_report_generated = True
                if ny_now.hour == 9:
                    vision_report_generated = False

                # v3.575: 纽约8AM运行ER阈值分析
                if ny_now.hour == 8 and ny_now.minute < 1 and not er_analysis_done_today:
                    try:
                        from er_threshold_analyzer import run_daily_analysis
                        report = run_daily_analysis()
                        # 保存报告到logs目录
                        date_str = ny_now.strftime("%Y%m%d")
                        log_file = f"logs/er_analysis_{date_str}.txt"
                        with open(log_file, "w", encoding="utf-8") as f:
                            f.write(report)
                        print(f"\n[v3.575] ER阈值分析报告已生成: {log_file}")
                        er_analysis_done_today = True
                    except Exception as er_e:
                        print(f"[v3.575] ER阈值分析失败: {er_e}")
                        er_analysis_done_today = True  # 失败也标记，避免重复尝试
                if ny_now.hour == 9:
                    er_analysis_done_today = False

                # v20: 纽约8AM运行交易回溯分析 (每日)
                if ny_now.hour == 8 and ny_now.minute < 1 and not retrospective_done_today:
                    try:
                        from trade_retrospective import run_retrospective, cleanup_old_decisions
                        terminal_report, md_report = run_retrospective("1d")
                        print(terminal_report)
                        # 保存Markdown报告
                        date_str = ny_now.strftime("%Y%m%d")
                        os.makedirs("logs/retrospective", exist_ok=True)
                        rpt_file = f"logs/retrospective/daily_{date_str}.md"
                        with open(rpt_file, "w", encoding="utf-8") as f:
                            f.write(md_report)
                        print(f"\n[v20] 每日回溯报告已生成: {rpt_file}")
                        # 清理7天前的决策记录
                        cleanup_old_decisions(7)
                        retrospective_done_today = True
                    except Exception as retro_e:
                        print(f"[v20] 回溯分析失败: {retro_e}")
                        retrospective_done_today = True

                # v20: 每周日8AM额外生成周报
                if ny_now.weekday() == 6 and ny_now.hour == 8 and ny_now.minute < 1 and not retrospective_weekly_done:
                    try:
                        from trade_retrospective import run_retrospective
                        terminal_report, md_report = run_retrospective("1w")
                        print(terminal_report)
                        date_str = ny_now.strftime("%Y%m%d")
                        os.makedirs("logs/retrospective", exist_ok=True)
                        rpt_file = f"logs/retrospective/weekly_{date_str}.md"
                        with open(rpt_file, "w", encoding="utf-8") as f:
                            f.write(md_report)
                        print(f"\n[v20] 每周回溯报告已生成: {rpt_file}")
                        retrospective_weekly_done = True
                    except Exception as retro_w_e:
                        print(f"[v20] 周报生成失败: {retro_w_e}")
                        retrospective_weekly_done = True
                if ny_now.hour == 9:
                    retrospective_done_today = False
                    retrospective_weekly_done = False
            except Exception as e:
                pass  # pytz未安装或时区错误，静默跳过

            state = load_json_file(STATE_FILE)
            validation_data = load_json_file(VALIDATION_FILE)
            calibration_data = load_json_file(CALIBRATION_FILE)
            xgboost_stats = load_json_file(XGBOOST_STATS_FILE)
            cnn_stats = load_json_file(CNN_HUMAN_STATS_FILE)
            regime_data = load_json_file(REGIME_VALIDATION_FILE)
            dual_track_data = load_json_file(HUMAN_DUAL_TRACK_FILE)

            # v3.150: 检测并记录外挂触发事件
            for symbol in CRYPTO_SYMBOLS + STOCK_SYMBOLS:
                data = state.get(symbol, {})
                ld = data.get("_last_final_decision", {})
                plugin_info = ld.get("plugin", {})

                if plugin_info.get("active") and plugin_info.get("mode") in ("PLUGIN_AGREE", "PLUGIN_CONFLICT"):
                    signal = plugin_info.get("indicator_signal", "")
                    trigger_key = f"{symbol}_{signal}_{now.strftime('%H%M')}"

                    if signal and trigger_key not in seen_plugin_triggers:
                        seen_plugin_triggers.add(trigger_key)
                        three_way = ld.get("three_way_signals", {})
                        diagnostics.record_plugin_trigger(
                            symbol=symbol,
                            signal=signal,
                            st=plugin_info.get("supertrend_trend", 0),
                            qqe=plugin_info.get("qqe_hist", 0),
                            macd=plugin_info.get("macd_hist", 0),
                            l1_signals={
                                "ai": three_way.get("ai_signal", "?"),
                                "human": three_way.get("human_signal", "?"),
                                "tech": three_way.get("tech_signal", "?")
                            }
                        )

            display(state, validation_data, calibration_data, xgboost_stats, cnn_stats, regime_data, dual_track_data)
            time.sleep(REFRESH_INTERVAL)
    except KeyboardInterrupt:
        # 退出前生成报告
        print("\n[诊断] 正在生成报告...")
        diagnostics.generate_daily_report()
        print(" 监控已停止")

if __name__ == "__main__":
    main()
