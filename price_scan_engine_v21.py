#!/usr/bin/env python3
"""
Price Scan Engine v21.27 (配合主程序 v3.677)
实时价格扫描引擎 - P0级别触发系统 + Chandelier+ZLSMA剥头皮 + L1外挂集成

v21.27更新 (2026-03-02) - 恢复移动止盈止损状态持久化:
- _load_tracking_state()选择性加载: 只恢复trailing相关字段, P0-Tracking不加载
- 恢复字段: trailing_high/low/count/reset_date + atr_cache + bar_freeze + position
- 根因: P0-Tracking禁用时误连带禁用了移动止盈止损的状态加载
- 后果: 每次重启trailing_high从当前(已跌)价格重算, drawdown永远不够触发止损

v21.26更新 (2026-02-27) - max_units=None防护:
- _get_position_and_max(): st.get("max_units",5)返回None时加if mx is None: mx=5
- 修复: state.json中max_units=null导致position_units>=None TypeError
- 4个加密货币(BTC/ETH/SOL/ZEC)全部受影响

v21.25更新 (2026-02-27) - Coinbase 4H请求cap 300根:
- _cb_limit = min(lookback_bars * 4 + 4, 300)，防止chan_bs 484>300 HTTP 400
- 300/4=75根，满足缠论BS最低30根要求

v21.24更新 (2026-02-27) - 移动止损/止盈 FilterChain豁免 (P1修复):
- 移动止损/移动止盈不再被FilterChain Vision gate拦截(保命优先)
- 与主程序_fcss_exempt口径一致: BrooksVision + 移动止损 + 移动止盈均豁免
- 修复: ETH/SOL仓位5/5整夜止损失效问题

v21.20更新 (2026-02-27) - 分型过滤器 (三外挂共用):
- check_fractal_filter(): BUY时无顶分型放行，SELL时无底分型放行
- 作用于 SuperTrend / N字 / 缠论BS 三道外挂，position control后最终拦截
- 日志标签: [v21.20]

v21.17更新 (2026-02-17) - 移动止盈/止损N字门控过滤:

【N字门控过滤】移动止盈BUY+移动止损SELL在信号生成前检查N字结构:
- 新增_load_n_gate_state(): 读取主程序持久化的state/n_gate_active.json(5min缓存)
- SELL路径: crash-sell豁免, 非crash时逆结构方向→跳过
- BUY路径: 无豁免, 逆结构方向→跳过
- 预期消除60-70%同品种日内BUY+SELL打脸

v21.16更新 (2026-02-16) - MACD扫描删除+剥头皮观察模式:

【MACD背离扫描删除】L2小周期MACD保留,扫描引擎MACD完全移除:
- 删除_scan_macd_divergence()函数(228行)
- 删除配置(crypto+stock)、状态管理(load/save)、调用(2处)、保存(3处)、热重载(1处)

【剥头皮观察模式】enabled=False时检测但不执行:
- enabled=False不再直接return,设_scalp_observe=True继续检测
- 信号处记录[OBSERVE][剥头皮]日志后return,不发送信号

v21.15更新 (2026-02-15) - 移除外挂per-bar周期限制:

【外挂周期限制移除】N字门控替代per-bar评估/触发限制:
- 移除7个外挂的"同根K线只触发一次"检查(SuperTrend, ST+AV2, RobHoffman, 双底双顶, 缠论BS, 飞云, MACD背离)
- N字门控(KEY-001)已提供结构性交易过滤，per-bar限制冗余
- 保留每日配额(1买+1卖/品种)不变
- 保留P0-Tracking(止盈止损)的周期限制不变
- 保留同K线冻结(0→1禁卖, 5→4禁买)不变

v21.14更新 (2026-02-15) - SYS-020/022/032数据流修复:

【SYS-020 regime始终sideways修复】:
- calc_consensus_score()改读trend_info["regime"]+["trend"]而非不存在的market_regime
- TRENDING+UP→bull, TRENDING+DOWN→bear, RANGING→sideways
- 移动止损/止盈共识传参改为self._get_trend_for_plugin(symbol)

【SYS-022 BOUNDED_TILT信号不足修复】:
- confidence为None时默认0.5(不再跳过), ema10添加None保护

【SYS-032 vol_ratio始终1.0修复】:
- tracking_state初始化添加last_volume/avg_volume字段
- _get_atr_threshold()重算ATR时顺带填充volume数据(复用OHLCV)

v21.13更新 (2026-02-15) - 论文集成三项改善(Phase 1观察):

【SYS-020 自适应共识阈值】(SSRN:6044974 Dynamic Bounded Multi-Factor Tilts):
- calc_consensus_score()根据market_regime动态调整BLOCK_THRESHOLD
- bull/bear→阈值降至0.20(趋势市放行更多信号), sideways→阈值升至0.35(震荡市从严)
- 校准器相关性检测: 5源投票全同向(全+1或全-1)→过度一致→相关性惩罚0.9
- Phase 1: would_block_adaptive字段记录,不影响现有would_block判断

【SYS-022 动态仓位边界】(SSRN:6044974 Bounded Tilts):
- check_position_control()新增bounded_tilt_score: 信号强度→平滑连续值
- 边界约束: 调仓幅度必须>5%才执行,防止频繁微调
- Phase 1: 记录bounded_tilt日志,不影响现有0-5档逻辑

【SYS-032 分批退出调度器】(SSRN:6101126 Optimal Liquidation):
- _check_trailing_stop()新增流动性评分: 唐纳奇通道宽度×成交量
- 高ATR时建议放慢退出(记录日志),低流动性时警告
- Phase 1: 记录exit_scheduler建议,不改变实际退出行为

v21更新 (2026-02-06) - L2空间位置确认:

【L2空间位置确认】扫描引擎外挂信号触发时，对比L2的纯决定:
- BUY vs L2=STRONG_SELL → HOLD (L2强烈看空，等下一周期)
- SELL vs L2=STRONG_BUY → HOLD (L2强烈看多，等下一周期)
- 其他情况(L2=BUY/SELL/HOLD/同方向) → 放行
- 急跌SELL(跌≥5%) → 绕过L2确认(保命优先)
- 适用: SuperTrend/SuperTrend+AV2/RobHoffman/双底双顶/飞云
- 豁免: P0-Tracking/移动止盈止损/MACD背离

v21.8更新 (2026-02-12) - 跨周期共识度评分:

【共识度评分(Phase1: 仅记录)】5源加权投票:
- x4_trend(0.30) + current_trend(0.25) + vision(0.20) + supertrend(0.15) + l2_rec(0.10)
- score ∈ [-1.0, +1.0], |score|<0.30=低共识, |score|>=0.60=高共识
- Phase1: 所有外挂+P0信号 log 共识度,不阻止任何交易
- 配置: timeframe_params.py CONSENSUS_WEIGHTS/BLOCK_THRESHOLD/BOOST_THRESHOLD

v20.6更新 (2026-02-06) - 双阈值+PC放宽:

【移动止盈/止损双阈值】一次ATR + 一次固定阈值:
- 第1次触发: min(ATR动态, 固定阈值) - 哪个小用哪个
- 第2次触发: max(ATR动态, 固定阈值) - 另一个
- 固定阈值: 美股3.5%, 加密货币4.0%, 不走ATR倍数
- 每天配额: 2买+2卖 不变

【移动止盈/止损直通PC】到了就激活，不限仓位条件:
- check_position_control()中"移动"信号直通所有仓位
- 只受满仓禁买/空仓禁卖/每天2次配额限制
- 逐级±1档

【其他外挂PC中间档位放宽】EMA+合并K线即可:
- AND必须: EMA条件 + 合并K线(阳/阴)
- OR加分项: 创新高/创新低/跌破实体(不阻止交易)
- 首尾不变: 0→1(阳线/P0直通), 4→5(共振), 5→4(阴线), 1→0(趋势+跌破)

v20.4更新 (2026-02-05) - 实体突破确认避免震荡:

【仓位2+买入突破确认】避免震荡市频繁加仓:
- 仓位2→3 BUY: 当前价格 > 前K线实体高点 (max(open,close)，不含上影线)
- 仓位3→4 BUY: 当前价格 > 前K线实体高点 (max(open,close)，不含上影线)
- 新增函数: check_new_high_breakout()
- 效果: 震荡市价格不破实体 → 阻止加仓; 趋势市价格突破实体 → 允许加仓

【仓位3-卖出跌破确认】避免震荡市频繁减仓:
- 仓位3→2 SELL: 当前价格 < 前K线实体低点 (min(open,close)，不含下影线)
- 仓位2→1 SELL: 当前价格 < 前K线实体低点 (min(open,close)，不含下影线)
- 新增函数: check_new_low_breakdown()
- 效果: 震荡市价格不破实体 → 阻止减仓; 下跌趋势跌破实体 → 允许减仓

【实体价格说明】只看K线实体，忽略上下影线:
- 实体高点 = max(open, close) - 阳线是close，阴线是open
- 实体低点 = min(open, close) - 阳线是open，阴线是close
- 好处: 影线常是假突破，实体更能反映真实供需

v20.5更新 (2026-02-05) - ATR(14)动态阈值:

【移动止盈/止损ATR动态阈值】替代固定2.5%:
- ATR(14)×倍数/当前价 = 动态阈值百分比
- 按资产类型(科技股/BTC/ETH/中型币/山寨币)和市场状态(TRENDING/DEFAULT/RANGING)选择倍数
- 第1次和第2次触发都用同一ATR阈值(移除×1.4递增)
- ATR缓存24h(纽约8AM刷新)，重启首轮强制重算
- 安全边界: clamp到[1%, 10%]，ATR失败时fallback到CONFIG固定阈值

v20.4更新 (2026-02-05) - 精简外挂:

【禁用P0-Tracking】震荡市来回打脸，只保留移动止盈/止损:
- _scan_tracking()中_check_trailing_stop()后直接return
- 移动止盈(trailing buy) + 移动止损(trailing stop) 正常运行

【禁用剥头皮】信号噪音大，收益不明确:
- config.crypto.scalping.enabled = False

v20.3更新 (2026-02-05) - 局部极值点 + 统一阈值:

【P0-Tracking局部极值点】更精准的高低点识别:
- 改进: P0-Tracking优先使用最近的局部极值点(价格拐点)，而非30根K线的绝对极值
- 局部高点: K线高点 > 前后K线高点 (第一个拐点)
- 局部低点: K线低点 < 前后K线低点 (第一个拐点)
- 兜底: 如果找不到局部极值，则使用30根K线的绝对极值
- 新增函数: get_first_local_extremes()
- 好处: 更贴近当前价格走势，避免远古极值误触发

【移除P0仓位限制】局部极值点已降低误触发风险:
- 移除: 仓位1禁止P0 SELL
- 移除: 仓位4禁止P0 BUY
- 原因: 局部极值点更精准，不再需要仓位限制

【统一阈值】加密货币和美股使用相同阈值:
- P0-Tracking: 加密/美股统一 2.5%
- 移动止盈/止损: 加密/美股统一 2.5%

v20.2更新 (2026-02-04) - 统一冻结周期:

【统一冻结周期】加密货币+美股统一24小时+8AM NY解冻:
- 移除单次交易冻结 (剥头皮原有1小时冻结)
- 所有外挂配额用完后冻结到次日8AM NY
- 保留v20.1 K线内冻结 (同K线买了不许卖/卖了不许买)
- 冻结类型:
  * K线冻结: 首档买卖后同K线内禁止反向 (v20.1)
  * 配额冻结: 每日配额用完后冻结到次日8AM (v20.2统一)

v20.1更新 (2026-02-04) - 首档K线内冻结:

【首档K线内冻结】防止顶底打脸:
- 0→1买入后 → 同K线内禁止1→0卖出
- 5→4卖出后 → 同K线内禁止4→5买入
- 新增函数: check_first_position_bar_freeze()

【首档K线内冻结】防止顶底打脸:
- 问题: 顶部/底部区域外挂产生来回买卖打脸
  * 仓位1时产生卖信号 → 0→1买完马上又要1→0卖
  * 仓位5→4刚卖完又产生买信号 → 5→4卖完马上又要4→5买
- 方案: K线内冻结 - 买入的这根K线结束前不能卖，卖出的这根K线结束前不能买
- 新增状态字段: first_buy_bar_start, first_sell_bar_start
- 新增检查函数: check_first_position_bar_freeze()
- 触发条件 (仅针对首档):
  * 0→1买入后 → 同K线内禁止1→0卖出
  * 5→4卖出后 → 同K线内禁止4→5买入
- 中间档位不受影响: 1→2, 2→3, 3→4买入正常; 4→3, 3→2, 2→1卖出正常
- 日志: [v20.1] XXX 首买/首卖K线内禁止清仓/满仓(等K线结束)

v19更新 (2026-02-03) - Body交集合并过滤震荡:
- 新增: body交集合并函数
  - merge_body_intersection_bars(bars): 按body交集合并已完成K线，返回合并段列表
  - check_body_merged_bullish(bars): 合并后最后一段是阳线
  - check_body_merged_bearish(bars): 合并后最后一段是阴线
- 买入条件变更 (EMA10档位):
  - 2→3: >EMA10 + body交集合并阳 (原前2根合并阳)
  - 3→4: >EMA10 + body交集合并阳 (原前3根合并阳)
- 卖出条件变更 (EMA10档位):
  - 三卖: <EMA10 + body交集合并阴 (原前2根合并阴)
  - 四卖: <EMA10 + body交集合并阴 (原前3根合并阴)
- 算法: 连续bars的body有重叠则合并，用body并集范围做交集判断(避免收缩效应)，最后一段方向决定BUY/SELL
- 效果: 震荡市body频繁重叠→大段合并→方向不明→阻止买卖; 趋势市body间gap大→少合并→方向清晰→允许交易
- body并集: 交集判断用段内所有bar body的最高/最低点(union_top/union_bot)，解决大阳+回调后body范围收缩问题

v18更新 (2026-02-02) - v17.6仓位控制升级:
- 新增: K线合并判断函数
  - check_merged_bars_bullish(bars, count): 前N根K线合并后是否为阳线
  - check_merged_bars_bearish(bars, count): 前N根K线合并后是否为阴线
- 买入条件加强:
  - 1→2: >EMA5 + 前2根合并阳 (原只需>=EMA5)
  - 2→3: >EMA10 + 前2根合并阳 (原自由买入)
  - 3→4: >EMA10 + 前3根合并阳 (原只需>=EMA10)
- 卖出激进化:
  - 一卖(5→?): 前1根阴 → 直接减到1档 (原5→4)
  - 二卖: <EMA5 + 前2根合并阴 → 直接清到0档 (原4→3)
  - 三卖: <EMA10 + 前2根合并阴 → 直接清到0档 (原3→2)
  - 四卖: <EMA10 + 前3根合并阴 → 直接清到0档 (原2→1)
  - 清仓(1→0): 共振确认 (不变)
- 函数签名变化: check_position_control() 返回 (allowed, reason, target_position)

v17.5更新 (2026-02-02):
- 统一: 美股/加密货币策略完全一致
  - check_plugin_daily_limit(): 移除美股方向限制，只检查配额
  - update_plugin_daily_state(): 移除美股趋势冻结，统一1买+1卖后冻结
  - P0-Open: 移除加密货币X小时冻结，统一冻结到次日8AM
- 逻辑分层: 外层管方向(顺大逆小)，内层管次数(配额)
- 配额总结:
  - P0-Tracking: 1买+1卖/天 (使用buy_used/sell_used布尔标记)
    * 策略1(原P0): buy_used + sell_used (布尔)
    * 策略2(移动止损/止盈): trailing_stop_count + trailing_buy_count (各最多2次, 第1次ATR/第2次固定阈值)
  - 其他外挂: 1循环 = 1买+1卖/天 (剥头皮/SuperTrend/RobHoffman/双底双顶/飞云/MACD背离)
- 重置: 纽约时间8AM

v17.4更新 (2026-02-01):
- 改进: Position Control 立体仓位控制系统
  - 核心原则: 先查仓位数 → 再定买卖条件 (避免来回打脸)
  - BUY转换 (5次):
    * 0→1: 需前一根完整K线是阳线 (首次买入需多头确认)
    * 1→2: 需价格 >= EMA5 (加仓需站上短期均线)
    * 2→3: 自由买入 (安全区域)
    * 3→4: 需价格 >= EMA10 (中仓位需站上中期均线)
    * 4→5: 需共振 (big=UP + cur=UP)
  - SELL转换 (5次):
    * 5→4: 需前一根完整K线是阴线 (首次卖出需空头确认)
    * 4→3: 需价格 <= EMA5 (减仓需跌破短期均线)
    * 3→2: 需价格 <= EMA10
    * 2→1: 需价格 <= EMA10
    * 1→0: 需共振 (big=DOWN + cur=DOWN)
- 新增函数: calculate_ema5(), check_prev_bar_bullish(), check_prev_bar_bearish()
- 修改函数: check_position_control() 增加bars参数

v17.3更新 (2026-01-31):
- 新增: Position Control 立体仓位控制系统
  - 解决外挂各自为战的混乱局面，统一仓位门控
  - position 0-2: 自由激活 (P0为主，外挂也可)
  - position 3-4: EMA过滤 (BUY需价格>=EMA10, SELL需价格<=EMA10)
  - position 4→5 (BUY): 需共振 (big=UP + current=UP)
  - position 1→0 (SELL): 需共振 (big=DOWN + current=DOWN)
  - 边界: 空仓不能卖，满仓不能买
- 新增函数: check_position_control(position, action, big_trend, current_trend, signal_source, current_price, ema10)
- 所有外挂触发前先检查Position Control
- 日志: [v17.4] Position Control / Resonance

v17.2更新 (2026-01-31):
- 新增: P0信号保护机制 (动态保护模式)
  - 问题: P0-Tracking/移动止盈抄底后，其他外挂顺大逆小SELL立即平仓
  - 保护逻辑:
    * P0 BUY后 → 阻止其他外挂SELL (抄底保护)
    * P0 SELL后 → 阻止其他外挂BUY (抓顶保护)
  - 最大保护期: 4小时 (P0_PROTECTION_MAX_HOURS)
  - 动态解除:
    * 抄底保护: L1 current_trend=UP 确认向上时解除
    * 抓顶保护: L1 current_trend=DOWN 确认向下时解除
  - 8AM重置: 纽约时间早上8点重置所有保护状态
  - 范围: P0-Open/剥头皮/SuperTrend/RobHoffman/双底双顶/飞云/MACD背离
  - 豁免: P0-Tracking/移动止损/移动止盈自身不受限制
  - 新字段: p0_buy_protection_until, p0_sell_protection_until
  - 日志: [v17.2] P0抄底保护/P0抓顶保护: 阻止XXX BUY/SELL

v17.1更新 (2026-01-31):
- 新增: /reload_state 热重载API (端口6002)
- 功能: 不重启扫描引擎即可重新加载配额状态
- 调用: curl -X POST http://127.0.0.1:6002/reload_state
- 配合: reset_quota_patch.py 配额恢复补丁

v17.0更新 (2026-01-30):
- 版本号升级配合主程序v3.580
- 主程序新增Vision覆盖当前周期功能
- 扫描引擎无逻辑变化，接收主程序同步的current_trend (可能已被Vision覆盖)

v16.9更新 (2026-01-28):
- 修复: 移动止损/止盈日期重置不独立的问题
  - 问题: 移动止损有独立配额但日期重置依赖原P0-Tracking触发
  - 场景: 原P0-Tracking未触发时，移动止损配额不会在新一天重置
  - 修复: _check_trailing_stop()添加独立的trailing_reset_date检查
  - 新字段: trailing_reset_date (移动止损专用重置日期)
- 改进: 移动止损日志显示更清晰

v16.0更新 (2026-01-26):
- P0-5修复: get_current_period_start()改用纽约时间(get_ny_now)
- P1-6修复: 剥头皮状态重写保留profit跟踪字段
- P1-7修复: scan_once()补齐4个外挂save调用
- P1-8修复: _check_and_freeze()冻结优先于日期重置
- P1-9b修复: _get_trend_for_plugin fallback优先取current_trend
- P1-11b修复: 日志使用RotatingFileHandler
- P2-6修复: 趋势缓存30分钟TTL
- P2-8修复: SIGTERM/SIGINT优雅退出
- P2-9修复: bare open()替换为safe_json_read()
- P2-7: 品种列表同步位置注释

v15.2更新 (2026-01-25):
- 修复: check_plugin_daily_limit() 冻结优先级bug
  - 问题: 引擎在凌晨12AM-8AM重启时，日期变化导致冻结被误清除
  - 场景: 1月25日10PM触发→冻结到1月26日8AM→1月26日2AM重启→冻结被清除
  - 修复: 先检查freeze_until是否仍有效，再检查日期重置
  - 影响: Rob Hoffman/双底双顶/飞云 等所有使用此函数的外挂

v15.1更新 (2026-01-25):
- 修复: Rob Hoffman/双底双顶/飞云 外挂状态持久化
  - 问题: 重启后冻结状态丢失，可能导致重复触发
  - 修复: 新增 _load/_save_rob_hoffman_state() 等持久化函数
  - 新增文件: scan_rob_hoffman_state.json, scan_double_pattern_state.json, scan_feiyun_state.json
- 改进: 启动时自动加载外挂状态
- 改进: 触发时自动保存外挂状态

v15.0更新 (2026-01-25):
- 新增: L1外挂集成到扫描引擎
  - Rob Hoffman外挂: EMA排列趋势检测 (1小时周期)
  - 双底双顶外挂: 形态反转检测 (1小时周期)
  - 飞云双突破外挂: 趋势线+形态双突破 (1小时周期)
- 新增: _scan_rob_hoffman() 方法
- 新增: _scan_double_pattern() 方法
- 新增: _scan_feiyun() 方法
- 新增: rob_hoffman_state, double_pattern_state, feiyun_state 状态管理
- 改进: 所有L1外挂使用统一的 current_trend (当前周期趋势)
- 改进日志输出: [v3.545]标记

v14.2更新 (2026-01-24):
- 修复: get_5m_ohlcv()缺少timestamp字段
  - 问题: 5分钟K线没有timestamp，导致周期检查失效
  - 现象: 剥头皮每分钟触发而非每5分钟
  - 修复: 添加 "timestamp": str(idx) 字段
- 调整: 剥头皮每日限制改为3次闭环循环
  - UP趋势: 买3卖1 (原买4卖1)
  - DOWN趋势: 买1卖3 (原买1卖4)
- 新增: 第3次卖出特殊规则 - 有利润就清仓
  - 第1-2次: 达到目标利润率(0.3%-0.4%)才清仓
  - 第3次有利润: 立即清仓锁利润
  - 第3次亏损: 标记7:55AM纽约时间强制清盘
- 新增: _check_755am_force_liquidate() 7:55AM强制清盘检查
  - 在scan_once()开始时检查
  - 7:55-7:59 AM纽约时间窗口执行
  - 发送清盘通知邮件，冻结到次日8AM

v14.1更新 (2026-01-24):
- 新增: 剥头皮每日统计报告 (_generate_scalping_daily_report)
  - 纽约时间早上8点重置前自动生成
  - 保存到 剥头皮/ 目录
  - 同时生成 .txt 和 .json 格式
  - 包含: 总盈亏、收益率、各币种明细

v14.0更新 (2026-01-24):
- 新增: 趋势转折自动同步机制 (配合主程序 v3.540)
  - /update_trend HTTP端点接收主程序趋势更新通知
  - _global_trend_cache: 内存缓存趋势状态 (最快响应)
  - _get_trend_for_plugin(): 优先内存缓存 > global_trend_state.json > state.json
  - 外挂策略立即响应: TRENDING顺势交易 / RANGING震荡禁用
- 新增: Flask HTTP服务器 (端口6002，后台线程运行)
  - 接收主程序POST /update_trend趋势更新
  - 立即刷新内存中的趋势状态
- 改进: 剥头皮趋势过滤使用_get_trend_for_plugin()
  - RANGING(震荡市)禁用剥头皮
  - UP趋势只允许BUY，DOWN趋势只允许SELL
- 改进日志输出: [v3.540]标记

v13.0更新 (2026-01-24):
- 新增: SuperTrend外挂集成到扫描引擎 (L1层)
  - 1小时K线周期检测
  - SuperTrend+QQE+MACD三指标共振
  - 周期触发控制 (每根1小时K线只触发一次)
  - 新增supertrend_state和supertrend_cycle_state状态管理
  - 新增get_1h_ohlcv()获取1小时K线数据
  - 新增_get_l1_signals_for_supertrend()读取L1三方信号
  - 新增_get_market_data_for_supertrend()读取市场数据
- 新增: 剥头皮5分钟周期触发控制
  - 每根5分钟K线只允许触发一次单向操作
  - 新增scalping_cycle_state状态管理
  - 防止同一K线周期内重复触发信号
- 改进日志输出: [v3.530]标记

v12.3更新 (2026-01-23):
- 修复: 邮件"已执行"状态与实际交易不一致的严重bug
  - 问题: 邮件在通知服务器之前发送，导致即使服务器拒绝执行，邮件仍显示"已执行"
  - 修复: 先通知服务器获取响应，再根据executed状态发送邮件
  - _notify_main_server()现在返回服务器响应dict
- 邮件状态增强:
  - ✅ 已执行: server_executed=True
  - 🚫 被拒绝: server_executed=False (显示拒绝原因)
  - ⏳ 已发送: 有外挂但未收到服务器响应
  - ⚠️ 仅提醒: 无外挂激活
- 影响范围: Chandelier+ZLSMA剥头皮、P0-Tracking、P0-Open

v12.2更新 (2026-01-23):
- 修复: P0-Tracking无外挂激活时仍执行交易的问题
  - 问题: 即使L1外挂未激活，信号仍被发送到主程序执行
  - 修复: 只在有外挂激活时才调用_notify_main_server()
  - 邮件仍然发送作为观察提醒
- 修复: 邮件模板区分"已执行"和"仅提醒"状态
  - 有外挂激活: ✅ 已执行
  - 无外挂激活: ⚠️ 仅提醒 (不执行交易)

v12.1更新 (2026-01-22):
- 暂停P0-Open (加密货币+美股都禁用)
- 剥头皮冻结时间统一为2小时
- 剥头皮每日交易次数限制

v12.0更新 (2026-01-21):
- 新增Chandelier Exit + ZLSMA剥头皮策略 (仅加密货币)
  - 5分钟K线周期检测
  - Chandelier Exit(ATR=1, mult=2)触发信号
  - ZLSMA(50)趋势确认 + Heikin-Ashi大阳/大阴线
  - L1趋势过滤 (UP只买, DOWN只卖, SIDE依赖Chandelier方向)
  - 独立冻结机制 (BTC/ETH/SOL=8h, ZEC=2h)
- 新增get_5m_ohlcv()获取5分钟K线
- 新增_scan_chandelier_zlsma()剥头皮扫描

v11.6更新 (2026-01-21):
- 移除P0-Tracking趋势对齐检查 (美股+加密货币)
  - 问题: v11.4趋势对齐导致暴跌时SELL被跳过(L1滞后确认DOWN)
  - 修复: P0-Tracking允许任何趋势下触发BUY/SELL
  - 保留: P0-Open仍需趋势对齐 (UP→BUY, DOWN→SELL, SIDE→跳过)
- 影响范围:
  - _scan_tracking() SELL检查: 移除current_trend!=DOWN限制
  - _scan_tracking() BUY检查: 移除current_trend!=UP限制

v11.5更新 (2026-01-18):
- 按币种设置不同冻结时间:
  - BTC/ETH/SOL: 8小时
  - ZEC: 2小时 (波动性更大)
  - 美股: 24小时 (不变)
- 更新 get_next_unfreeze_time() 支持按币种冻结
- 更新 _check_and_freeze() 支持按币种冻结
- 更新 P0-Open freeze逻辑支持按币种冻结

v11.3.1更新 (2026-01-11):
- 修复: _get_current_trend()函数读取错误字段
  - 问题: l1_trend_for_scan中没有current_trend字段，导致始终返回SIDE
  - 修复: 优先从_last_final_decision.market_regime.current_trend读取
  - 备选: 使用l1_trend_for_scan.direction(大周期趋势)

v11.3更新 (2026-01-11):
- P0-Open重新启用 (只对加密货币开放):
  - 趋势对齐: current_trend=UP时只能BUY，current_trend=DOWN时只能SELL
  - 屏蔽条件: current_trend=SIDE时不触发 (震荡市)
  - 按币种阈值: BTC/ETH/SOL ±2%, ZEC ±2.5%
  - 冻结周期: 6小时
  - 美股保持禁用P0-Open (只用P0-Tracking)
- 新增函数: _get_current_trend() - 从state.json读取当前周期趋势
- 新增函数: _scan_open_crypto() - P0-Open加密货币扫描
- 新增配置: p0_open.thresholds (按币种阈值) / trend_aligned (趋势对齐)

v11.2更新 (2026-01-11):
- 核心修复: 美股周一开盘基准价重置
  - 问题: 周五收盘后基准价停留在周五的值，周一开盘可能因gap触发错误信号
  - 解决: 检测美股新交易日开盘(9:30-9:35 NY)，重置基准价为当前价
- 开盘缓冲期: 9:30-9:40 NY期间不触发信号，让价格稳定
- 新增字段: last_trading_date - 追踪上次交易日期
- 新增字段: market_open_cooldown_until - 开盘缓冲期结束时间
- 日志增强: 显示开盘日重置和缓冲期状态

v11.0更新 (2026-01-10):
- 核心原则: P0-Tracking一直运行，外挂是额外增强
  - P0-Tracking: 基础价格扫描，持续运行不受外挂状态影响
  - L1外挂: 趋势跟随增强(道氏理论确认趋势后激活)
  - 飞云外挂: 趋势捕捉增强(双突破共振确认趋势开启)
  - 两个外挂独立检查，哪个激活运行哪个，可同时激活
- L1外挂激活条件:
  - consensus=AGREE/DEEPSEEK_ARBITER + direction=UP/DOWN
  - UP趋势 + BUY触发 → 激活L1外挂
  - DOWN趋势 + SELL触发 → 激活L1外挂
- 飞云外挂激活条件:
  - 必须是双突破(is_double=True)
  - L1趋势方向一致(均需趋势行情)
  - UP趋势 + DOUBLE_BREAK_BUY + BUY触发 → 激活飞云外挂
  - DOWN趋势 + DOUBLE_BREAK_SELL + SELL触发 → 激活飞云外挂
- 震荡/无趋势 → P0-Tracking正常执行，外挂不激活
- 函数重命名: _should_scan_symbol → _should_activate_plugins
- v3.360增强: Human模块道氏理论判断当前周期趋势/震荡

v9.0更新 (2026-01-07):
- 重大变更: 屏蔽P0-Open功能，只保留P0-Tracking
- P0-Open相关代码保留但不执行，便于未来恢复
- 简化扫描逻辑，减少不必要的基准价计算

v8.3更新 (2026-01-06):
- 新增: is_us_stock() - 判断是否是美股品种
- 新增: is_us_market_open() - 检查美股是否在开盘时间 (09:30-16:00 NY)
- 新增: get_us_market_open_time_today() - 获取今天美股开盘时间
- 新增: get_today_market_open_price() - 获取美股当天开盘价
- 修改: P0-Open美股基准价逻辑 - 只在开盘时间设置，使用当天开盘价
- 修改: _check_period_reset_open() - 美股与加密货币分离处理
- 新增: last_update_date字段 - 追踪美股基准价设置的交易日

v8.2.2更新 (2026-01-05):
- 修改: 美股P0-Open阈值 3%
- 修改: 美股P0-Tracking阈值 3.5%
- 修改: P0-Tracking冻结规则从"1买+1卖"改为"单次交易后立即冻结6小时"
- 新增: P0-Open也支持冻结6小时（单次交易后）
- 修复: 周期重置时保留freeze_until字段（之前会被清除导致冻结失效）

v8.2更新 (2026-01-05):
- 新增: P0-Open仓位检查 (满仓不买，空仓不卖)
- 新增: P0-Tracking BUY条件从position==0改为position<5
- 新增: 仓位日志输出
- 修改: 冻结时间从"次日10:00"改为"当前整点+6小时"

v8.1更新 (2026-01-03):
- 修复: yfinance "possibly delisted" 错误
- 新增: 重试机制 (最多3次，指数退避)
- 新增: 多period备选 (1d → 5d → 7d)
- 新增: 抑制yfinance警告输出
- 新增: 价格缓存层 (30秒TTL，减少请求频率)

v8.0更新:
- P0-Open: 每周期限制1次，买卖互斥
- P0-Open: 新周期基准价使用前一次触发时的价格
- P0-Tracking: 每周期买卖互斥
- P0-Tracking: 6小时内1买+1卖后冻结（当前整点+6小时）
- P0-Tracking: 解冻后重新回溯30根K线初始化基准价

v7.0更新:
- 新增追踪止损/追涨买入功能 (P0-Tracking)
- 持仓时跟踪peak_price，从最高点回撤超阈值触发卖出
- 空仓时跟踪trough_price，从最低点上涨超阈值触发买入

功能：
1. P0-Open: 与前一个大周期开盘价比较
   - 加密货币: ±2%, 每周期1次(买或卖互斥), 基准价=前一周期开盘价
   - 美股: ±3%, 每周期1次(买或卖互斥), 基准价=当天开盘价(09:30)
   - v8.3: 美股只在开盘时间(09:30-16:00 NY)设置/更新基准价

2. P0-Tracking: 追踪止损/追涨买入
   - 加密货币: 2.5%, 每周期1次(买或卖互斥)
   - 美股: 3.5%, 每周期1次(买或卖互斥)
   - 6小时1买+1卖后冻结（当前整点+6小时）

数据源：
- 加密货币: yfinance (BTC-USD, ETH-USD等)
- 美股: yfinance (1分钟K线收盘价)

作者: AI Trading System
日期: 2025-01-02
"""

import os
import sys
import math
import warnings
warnings.filterwarnings("ignore", message=".*Timestamp.utcnow.*", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning, module="yfinance")

import json
import time
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from typing import Dict, Optional, Any, List
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from timeframe_params import get_timeframe_params, read_symbol_timeframe, is_crypto_symbol, SCAN_INTERVAL_BY_TF  # v20/v21.7
from models.volume_analyzer import VolumeAnalyzer  # v21.11: 量价增强(SYS-025~028)

# 第三方库
try:
    import requests
except ImportError:
    print("请安装 requests: pip install requests")
    sys.exit(1)

try:
    import yfinance as yf
    # v8.1: 抑制 yfinance 警告
    import warnings
    warnings.filterwarnings('ignore', message='.*possibly delisted.*')
    warnings.filterwarnings('ignore', message='.*Timestamp.utcnow.*', category=FutureWarning)
    logging.getLogger('yfinance').setLevel(logging.ERROR)
except ImportError:
    print("请安装 yfinance: pip install yfinance")
    sys.exit(1)

try:
    import pytz
except ImportError:
    print("请安装 pytz: pip install pytz")
    sys.exit(1)

# GCC-0205: 股票数据源双源fallback（yfinance -> Schwab）
try:
    from schwab_data_provider import get_provider as get_schwab_provider
    _schwab_provider_available = True
except Exception:
    get_schwab_provider = None
    _schwab_provider_available = False

# v12.0: Chandelier+ZLSMA剥头皮外挂
try:
    from chandelier_zlsma_plugin import get_chandelier_zlsma_plugin
    _chandelier_zlsma_available = True
except ImportError:
    get_chandelier_zlsma_plugin = None
    _chandelier_zlsma_available = False
    print("警告: chandelier_zlsma_plugin.py 未找到，剥头皮功能禁用")

# v3.530: SuperTrend外挂 (L1层扫描引擎集成)
try:
    from supertrend_plugin_v08 import get_supertrend_plugin, PluginMode
    _supertrend_available = True
except ImportError:
    get_supertrend_plugin = None
    PluginMode = None
    _supertrend_available = False
    print("警告: supertrend_plugin_v08.py 未找到，SuperTrend外挂禁用")

# v3.545: Rob Hoffman外挂 (L1层扫描引擎集成)
try:
    from rob_hoffman_plugin import get_rob_hoffman_plugin, HoffmanSignal, PluginMode as HoffmanPluginMode
    _rob_hoffman_available = True
except ImportError:
    get_rob_hoffman_plugin = None
    HoffmanSignal = None
    HoffmanPluginMode = None
    _rob_hoffman_available = False
    print("警告: rob_hoffman_plugin.py 未找到，Rob Hoffman外挂禁用")

# v3.545: 双底双顶外挂 (L1层扫描引擎集成)
try:
    from double_pattern_plugin import get_double_pattern_plugin, PluginSignal as DPPluginSignal
    _double_pattern_available = True
except ImportError:
    get_double_pattern_plugin = None
    DPPluginSignal = None
    _double_pattern_available = False
    print("警告: double_pattern_plugin.py 未找到，双底双顶外挂禁用")

# GCC-0046: Vision形态识别直接调用 (脱离TV依赖)
try:
    from vision_analyzer import analyze_patterns as _vision_analyze_patterns
    from vision_analyzer import get_symbols_config as _vision_get_symbols_config
    _vision_pattern_available = True
except ImportError:
    _vision_analyze_patterns = None
    _vision_get_symbols_config = None
    _vision_pattern_available = False
    print("警告: vision_analyzer.py 未找到，Vision形态独立扫描禁用")

# v21.1: 缠论买卖点外挂 (4H, 一/二/三买卖点)
try:
    from chan_bs_plugin import get_chan_bs_plugin, ChanBSResult, BSPoint as ChanBSPoint
    _chan_bs_available = True
except ImportError:
    get_chan_bs_plugin = None
    ChanBSResult = None
    ChanBSPoint = None
    _chan_bs_available = False
    print("警告: chan_bs_plugin.py 未找到，缠论买卖点外挂禁用")

# v2.1: Brooks PA外挂已合并到 Brooks Vision (brooks_vision.py)
# 原 brooks_pa_plugin.py 和 key004_brooks_pa.py 已删除

# v3.545: 飞云双突破外挂 (L1层扫描引擎集成)
try:
    from feiyun_plugin import get_feiyun_plugin, FeiyunSignal, PluginMode as FeiyunPluginMode
    _feiyun_available = True
except ImportError:
    get_feiyun_plugin = None
    FeiyunSignal = None
    FeiyunPluginMode = None
    _feiyun_available = False
    print("警告: feiyun_plugin.py 未找到，飞云外挂禁用")

# v3.565: MACD背离外挂 (从主程序移交扫描引擎，仅震荡市激活)
try:
    from macd_divergence_plugin import (
        get_macd_divergence_plugin,
        DivergenceResult,
        PluginMode as DivPluginMode,
    )
    _macd_divergence_available = True
except ImportError:
    get_macd_divergence_plugin = None
    DivergenceResult = None
    DivPluginMode = None
    _macd_divergence_available = False
    # v21.16: MACD背离外挂已从扫描引擎删除, import保留供L2使用

# v3.550: SuperTrend+QQE MOD+A-V2外挂 (知识卡片"超级趋势过滤器交易系统")
try:
    from supertrend_av2_plugin import get_supertrend_av2_plugin, PluginMode as AV2PluginMode
    _supertrend_av2_available = True
except ImportError:
    get_supertrend_av2_plugin = None
    AV2PluginMode = None
    _supertrend_av2_available = False
    print("警告: supertrend_av2_plugin.py 未找到，SuperTrend+AV2外挂禁用")

# v3.550: 外挂利润追踪
try:
    from plugin_profit_tracker import PluginProfitTracker, save_daily_report
    _profit_tracker_available = True
except ImportError:
    PluginProfitTracker = None
    save_daily_report = None
    _profit_tracker_available = False
    print("警告: plugin_profit_tracker.py 未找到，外挂利润追踪禁用")

# v3.540: Flask HTTP服务器 + 趋势同步
import threading
try:
    from flask import Flask, request, jsonify
    _flask_available = True
except ImportError:
    Flask = None
    _flask_available = False
    print("警告: Flask未安装，趋势同步HTTP端点禁用 (pip install flask)")

# v3.540: 全局趋势状态缓存 (内存)
_global_trend_cache: Dict[str, dict] = {}
_global_trend_lock = threading.Lock()
GLOBAL_TREND_STATE_FILE = "global_trend_state.json"

# v3.540: Flask app实例 (在main中启动)
_trend_sync_app = None

# v17.1: 扫描引擎实例 (用于热重载API)
_scan_engine_instance = None

# v21.11: 量价分析实例 (SYS-025~028 Phase 1 观察)
_vol_analyzer = VolumeAnalyzer()

# v21.3: 结构性改进模块 (Module A/B/C)
try:
    from modules.stock_selector import StockSelector
    from modules.trade_frequency import TradeFrequencyController
    _modules_available = True
except ImportError:
    _modules_available = False
    print("提示: modules/ 未就绪，预选/频率控制模块未加载")

# ============================================================
# 配置
# ============================================================

# 纽约时区
NY_TZ = pytz.timezone("America/New_York")

CONFIG = {
    # 扫描间隔（秒）
    "scan_interval": 300,  # v20.5: 5分钟扫描(剥头皮已禁用，降低API频率)

    # 加密货币配置
    "crypto": {
        "symbols": ["BTC-USD", "ETH-USD", "SOL-USD", "ZEC-USD"],
        "threshold": 0.02,   # 2% (P0-Open) [已屏蔽]
        "p0_tracking_threshold": 0.025,  # v20.3: 2.5% (局部极值点基准，加密/美股统一)
        "tracking_threshold": 0.025,  # v20.3: 2.5% (移动止盈/止损，加密/美股统一)
        "timeframe": "4h",   # v3.546: 改为4小时周期 - P0-Tracking用
        # v12.0: Chandelier+ZLSMA剥头皮配置
        "scalping": {
            "enabled": False,  # v20.4: 禁用剥头皮，观察整体交易质量
            "timeframe": "5m",  # 5分钟K线
            "lookback_bars": 100,  # 回溯100根5分钟K线
            # v20.2: 移除单次交易冻结，统一24小时周期+8AM解冻
            # v12.1: 每日交易次数限制
            # v17.2: 改为每日1次买卖，配合P0保护减少冲突
            "daily_limit": {
                "max_buy": 1,       # v17.2: 每日最多买1次
                "max_sell": 1,      # v17.2: 每日最多卖1次
                "reset_hour_ny": 8,  # 纽约时间早上8点重置
            },
        },
        # v3.546: SuperTrend外挂配置 (L1层扫描引擎集成)
        # 改为4小时周期，触发后冻结到次日纽约时间8AM
        "supertrend": {
            "enabled": True,
            "timeframe": "4h",          # v3.546: 改为4小时K线
            "ohlcv_lookback": 30,       # OHLCV回溯30根 (SuperTrend计算)
            "close_lookback": 120,      # 收盘价回溯120根 (QQE/MACD计算)
            "freeze_until_8am": True,   # v3.546: 触发后冻结到次日纽约时间8AM
        },
        # v3.546: Rob Hoffman外挂配置 (L1层扫描引擎集成)
        # 改为4小时周期，触发后冻结到次日纽约时间8AM
        "rob_hoffman": {
            "enabled": True,            # v2.0 IRB标准修正后重新启用
            "timeframe": "4h",          # v3.546: 改为4小时K线
            "ohlcv_lookback": 60,       # OHLCV回溯60根 (EMA55需要)
            "freeze_until_8am": True,   # v3.546: 触发后冻结到次日纽约时间8AM
        },
        # v3.546: 双底双顶外挂配置 (L1层扫描引擎集成)
        # 改为4小时周期，触发后冻结到次日纽约时间8AM
        "double_pattern": {
            "enabled": False,           # v21.15: Brooks Vision已覆盖形态识别，禁用
            "timeframe": "4h",          # v3.546: 改为4小时K线
            "ohlcv_lookback": 50,       # OHLCV回溯50根
            "freeze_until_8am": True,   # v3.546: 触发后冻结到次日纽约时间8AM
        },
        # v3.546: 飞云双突破外挂配置 (L1层扫描引擎集成)
        # 改为4小时周期，触发后冻结到次日纽约时间8AM
        "feiyun": {
            "enabled": True,            # v21.28: 恢复启用
            "timeframe": "4h",          # v3.546: 改为4小时K线
            "ohlcv_lookback": 40,       # OHLCV回溯40根
            "freeze_until_8am": True,   # v3.546: 触发后冻结到次日纽约时间8AM
        },
        # v21.16: macd_divergence配置已删除(扫描引擎), 仅保留L2小周期版本
        # v3.550: SuperTrend+QQE MOD+A-V2外挂配置 (知识卡片"超级趋势过滤器交易系统")
        # 三指标共振: SuperTrend(ATR=9,mult=3.9) + QQE MOD(灰色=震荡) + A-V2(52/10)
        "supertrend_av2": {
            "enabled": False,           # 安全期暂停
            "timeframe": "4h",          # 4小时K线周期
            "ohlcv_lookback": 100,      # OHLCV回溯100根 (A-V2需要52+10=62根)
            "close_lookback": 120,      # 收盘价回溯120根 (QQE计算)
            "freeze_until_8am": True,   # 触发后冻结到次日纽约时间8AM
        },
    },

    # 美股配置
    "stock": {
        "symbols": ["TSLA", "COIN", "RDDT", "NBIS", "CRWV", "RKLB", "HIMS", "OPEN", "AMD", "ONDS", "PLTR"],
        "threshold": 0.06,   # 6% (P0-Open) [已屏蔽]
        "p0_tracking_threshold": 0.025,  # v20.3: 2.5% 与加密货币统一
        "tracking_threshold": 0.025,  # v20.3: 2.5% 与加密货币统一
        "timeframe": "4h",   # v3.546: 改为4小时周期
        # v3.546: 美股外挂配置 (与加密货币一致)
        # 4小时周期，触发后冻结到次日纽约时间8AM
        "supertrend": {
            "enabled": True,
            "timeframe": "4h",          # v3.546: 4小时K线
            "ohlcv_lookback": 30,
            "close_lookback": 120,
            "freeze_until_8am": True,
        },
        "rob_hoffman": {
            "enabled": False,           # 安全期暂停
            "timeframe": "4h",          # v3.546: 4小时K线
            "ohlcv_lookback": 60,
            "freeze_until_8am": True,
        },
        "double_pattern": {
            "enabled": False,           # v21.15: Brooks Vision已覆盖形态识别，禁用
            "timeframe": "4h",          # v3.546: 4小时K线
            "ohlcv_lookback": 50,
            "freeze_until_8am": True,
        },
        "feiyun": {
            "enabled": True,            # v21.28: 恢复启用
            "timeframe": "4h",          # v3.546: 4小时K线
            "ohlcv_lookback": 40,
            "freeze_until_8am": True,
        },
        # v21.16: macd_divergence配置已删除(扫描引擎), 仅保留L2小周期版本
        # v3.550: SuperTrend+QQE MOD+A-V2外挂配置 (美股)
        "supertrend_av2": {
            "enabled": False,           # 安全期暂停
            "timeframe": "4h",
            "ohlcv_lookback": 100,
            "close_lookback": 120,
            "freeze_until_8am": True,
        },
    },

    # v8.0: 追踪保护配置
    # v3.230: P0-Tracking冷却期提高到24小时，大幅减少交易频率
    # v11.5: 按币种设置不同冻结时间 (ZEC=1h, BTC/ETH/SOL=4h)
    # v20.2: P0-Tracking配置 - 统一24小时周期+8AM NY解冻
    "tracking": {
        "lookback_bars": 30,  # 回溯30根K线初始化基准价格
        "state_file": "logs/state.json",  # 主程序状态文件路径
        "freeze_window_hours": 24,  # v20.2: 历史记录保留24小时 (仅用于清理，不影响冻结)
        # v20.2: 冻结统一使用get_next_8am_ny()，不再区分品种
        "unfreeze_hour_ny": 8,  # v20.2: 纽约时间8AM解冻 (原10AM)
    },

    # v11.3: P0-Open配置 (只对加密货币开放)
    # v12.1: 暂停P0-Open (加密货币+美股都禁用)
    # v20.2: 统一24小时周期+8AM NY解冻
    "p0_open": {
        "enabled_crypto": False,  # v12.1: 暂停 (原True)
        "enabled_stock": False,   # v11.3: 美股P0-Open禁用
        # v20.2: 冻结统一使用get_next_8am_ny()
        "require_trend": True,     # v11.3: 必须在趋势市(UP/DOWN)才触发，震荡(SIDE)不触发
        "trend_aligned": True,     # v11.3: 信号必须与趋势方向一致 (UP只买，DOWN只卖)
        # v11.3: 按币种设置不同阈值
        "thresholds": {
            "BTC-USD": 0.02,   # 2%
            "ETH-USD": 0.02,   # 2%
            "SOL-USD": 0.02,   # 2%
            "ZEC-USD": 0.025,  # 2.5%
        },
        "default_threshold": 0.02,  # 默认2%
    },

    # 邮件配置
    "email": {
        "enabled": True,
        "smtp_server": "smtp.gmail.com",
        "smtp_port": 587,
        "sender_email": "aistockllmpro@gmail.com",
        "sender_password": "ficw ovws zvzb qmfs",
        "receiver_email": "baodexiang@hotmail.com",
    },

    # 信号文件路径
    "signal_file": "scan_signals.json",
    "state_file": "scan_state.json",
    "tracking_state_file": "scan_tracking_state.json",
    "scalping_state_file": "scan_scalping_state.json",  # v12.0: 剥头皮状态
    "supertrend_state_file": "scan_supertrend_state.json",  # v3.530: SuperTrend状态
    "rob_hoffman_state_file": "scan_rob_hoffman_state.json",  # v15.1: Rob Hoffman状态
    "double_pattern_state_file": "scan_double_pattern_state.json",  # v15.1: 双底双顶状态
    "feiyun_state_file": "scan_feiyun_state.json",  # v15.1: 飞云状态
    "macd_divergence_state_file": "scan_macd_divergence_state.json",  # v3.565: MACD背离状态
    "supertrend_av2_state_file": "scan_supertrend_av2_state.json",  # v3.550: SuperTrend+AV2状态
    "chan_bs_state_file": "scan_chan_bs_state.json",  # v21.1: 缠论买卖点状态
    # brooks_pa_state_file: 已删除 (合并到 Brooks Vision)
    "heartbeat_file": "scan_heartbeat.json",

    # 主程序URL
    "main_server_url": "http://localhost:6001",

    # 日志
    "log_file": "logs/price_scan_engine.log",
}

# === 品种列表 ===
# 同步修改位置:
# 1. llm_server SYNC_SYMBOLS (~line 24922)
# 2. price_scan_engine CRYPTO_SYMBOL_MAP (此处)
# 3. monitor CRYPTO_SYMBOLS
# 加密货币符号映射
CRYPTO_SYMBOL_MAP = {
    "BTC-USD": "BTC-USD",
    "ETH-USD": "ETH-USD",
    "SOL-USD": "SOL-USD",
    "ZEC-USD": "ZEC-USD",
    "BTCUSDC": "BTC-USD",
    "ETHUSDC": "ETH-USD",
    "SOLUSDC": "SOL-USD",
    "ZECUSDC": "ZEC-USD",
}

# 反向映射
REVERSE_SYMBOL_MAP = {
    "BTC-USD": "BTCUSDC",
    "ETH-USD": "ETHUSDC",
    "SOL-USD": "SOLUSDC",
    "ZEC-USD": "ZECUSDC",
}

# ============================================================
# v21: Vision形态外挂 — 观察/执行模式配置
# ============================================================
VISION_PATTERN_OBSERVE_STOCK = False    # v21.5: 美股改为执行模式 (仓位0/1/4/5边界激活)
VISION_PATTERN_OBSERVE_CRYPTO = False   # 加密货币: 执行模式 (直接交易)
P0_TRACKING_ENABLED = True              # v21.28: 恢复启用 P0-Tracking 极值追踪
TRAILING_STOP_ENABLED = True            # 移动止损/止盈独立开关
MAX_UNITS_PER_SYMBOL = 5                # 每品种最大仓位单位 (与主程序一致)

# ============================================================
# v20.5: ATR动态阈值 - 资产分类 / 倍数表 / ATR计算
# ============================================================

def _classify_asset_type(symbol: str) -> str:
    """v20.5: 通用资产分类，新品种自动适配"""
    if not is_crypto_symbol(symbol):
        return "科技股"

    upper = symbol.upper()
    if upper.startswith("BTC"):
        return "BTC"
    if upper.startswith("ETH"):
        return "ETH"
    if upper.startswith(("SOL", "ZEC")):
        return "中型币"
    return "山寨币"


# v20.5: ATR倍数表 - 统一倍数(ATR已区分波动性，无需按品种再加码)
ATR_MULTIPLIER_TABLE = {
    "科技股": {"TRENDING": 1.5, "DEFAULT": 2.0, "RANGING": 2.5},
    "BTC":   {"TRENDING": 1.5, "DEFAULT": 2.0, "RANGING": 2.5},
    "ETH":   {"TRENDING": 1.5, "DEFAULT": 2.0, "RANGING": 2.5},
    "中型币": {"TRENDING": 1.5, "DEFAULT": 2.0, "RANGING": 2.5},
    "山寨币": {"TRENDING": 1.5, "DEFAULT": 2.0, "RANGING": 2.5},
}

# v20.5: ATR阈值安全边界上限 (按资产类型，下限统一1%)
ATR_CLAMP_UPPER = {
    "科技股": 0.10,   # 10%
    "BTC":   0.10,   # 10%
    "ETH":   0.15,   # 15%
    "中型币": 0.18,   # 18%
    "山寨币": 0.20,   # 20%
}


def estimate_trend_phase(bars: list, trend_x4: str = "SIDE") -> dict:
    """
    v21.12: 趋势阶段估计 (RES-007 + arXiv论文增强)
    利用x4方向 + 近20根K线位置 + EMA动量 判断初升/主升/末升阶段
    输出市场制度标签 bull/bear/sideways (arXiv:2505.07078 FINSABER)

    Phase 1: 仅记录, 不拦截

    增强 (v21.12):
    - EMA(10)动量确认趋势方向 (arXiv:2602.12030 Time-Inhomogeneous VA)
    - market_regime 标签: x4方向+EMA斜率→bull/bear/sideways
    - risk_budget增加 atr_regime_mult: 初期放宽止损/末期收紧 (时变波动厌恶)
    - rhythm_adjust 幅度增大: 初期-10%降门槛/末期+15%升门槛 (FINSABER)

    Returns:
        {"phase": "INITIAL"/"MAIN"/"FINAL"/"NEUTRAL",
         "progress": 0.0~1.0,
         "market_regime": "bull"/"bear"/"sideways",
         "ema_momentum": float,
         "risk_budget": {"rhythm_adjust": float, "atr_decay": float,
                         "position_max_adjust": int, "atr_regime_mult": float}}
    """
    PHASE_RISK = {
        # v21.12: 参数来源 — arXiv:2602.12030(时变风险) + arXiv:2505.07078(FINSABER regime)
        "INITIAL": {"rhythm_adjust": -0.10, "atr_decay": 0.0, "position_max_adjust": 0, "atr_regime_mult": 1.15},
        "MAIN":    {"rhythm_adjust": 0.0,   "atr_decay": 0.0, "position_max_adjust": 0, "atr_regime_mult": 1.0},
        "FINAL":   {"rhythm_adjust": 0.15,  "atr_decay": 0.20, "position_max_adjust": -1, "atr_regime_mult": 0.85},
        "NEUTRAL": {"rhythm_adjust": 0.0,   "atr_decay": 0.0, "position_max_adjust": 0, "atr_regime_mult": 1.0},
    }
    default = {"phase": "NEUTRAL", "progress": 0.5, "market_regime": "sideways",
               "ema_momentum": 0.0, "risk_budget": PHASE_RISK["NEUTRAL"]}

    x4 = (trend_x4 or "SIDE").upper()
    if x4 not in ("UP", "DOWN"):
        return default

    if not bars or len(bars) < 20:
        return default

    recent = bars[-20:]
    highs = [b["high"] for b in recent]
    lows = [b["low"] for b in recent]
    closes = [b["close"] for b in recent]
    range_high = max(highs)
    range_low = min(lows)
    range_span = range_high - range_low
    if range_span <= 0:
        return default

    current_close = recent[-1].get("close", 0)
    if current_close <= 0:
        return default

    # 归一化位置 [0, 1]
    pos_in_range = (current_close - range_low) / range_span
    pos_in_range = max(0.0, min(1.0, pos_in_range))

    # v21.12: EMA动量 — 近5根 vs 前5根均价, 确认趋势强度
    ema_momentum = 0.0
    if len(closes) >= 10:
        recent_avg = sum(closes[-5:]) / 5
        older_avg = sum(closes[-10:-5]) / 5
        if older_avg > 0:
            ema_momentum = (recent_avg - older_avg) / older_avg

    # v21.12: 市场制度判定 (FINSABER arXiv:2505.07078)
    # x4方向 + EMA动量 → bull/bear/sideways
    if x4 == "UP" and ema_momentum > 0.002:
        market_regime = "bull"
    elif x4 == "DOWN" and ema_momentum < -0.002:
        market_regime = "bear"
    else:
        market_regime = "sideways"

    if x4 == "UP":
        progress = pos_in_range
        if pos_in_range < 0.33:
            phase = "INITIAL"
        elif pos_in_range < 0.67:
            phase = "MAIN"
        else:
            phase = "FINAL"
    else:  # DOWN
        progress = 1.0 - pos_in_range
        if pos_in_range > 0.67:
            phase = "INITIAL"
        elif pos_in_range > 0.33:
            phase = "MAIN"
        else:
            phase = "FINAL"

    return {"phase": phase, "progress": round(progress, 3),
            "market_regime": market_regime, "ema_momentum": round(ema_momentum, 6),
            "risk_budget": PHASE_RISK[phase]}


# v21.10: 趋势阶段风险预算 Phase 1 开关
ENABLE_TREND_PHASE_RISK = True   # v21.22 RES-007 Phase2: 初期降BUY门槛/末期升门槛启用


def get_regime_adaptive_lookback(trend_info: dict, base_lookback: int = 30) -> int:
    """
    v21.10 SYS-023: Regime自适应数据窗口
    Phase 1: 仅记录对比, 不改变实际lookback

    TRENDING: base * 0.67 (20根) — 趋势中近期数据更重要
    RANGING:  base * 1.67 (50根) — 震荡中需要更大窗口看全局
    DEFAULT:  base (30根)
    """
    REGIME_LOOKBACK_ENABLED = False  # Phase 1
    regime = _get_market_regime_for_atr(trend_info)
    scale = {"TRENDING": 0.67, "RANGING": 1.67}.get(regime, 1.0)
    adaptive = max(15, int(base_lookback * scale))
    if not REGIME_LOOKBACK_ENABLED and adaptive != base_lookback:
        print(f"[v21.10] Regime窗口[观察]: {regime} lookback 原{base_lookback}→建议{adaptive} (未启用)")
    return adaptive if REGIME_LOOKBACK_ENABLED else base_lookback


def _get_market_regime_for_atr(trend_info: dict) -> str:
    """v20.5: 从趋势信息推断市场状态(用于ATR倍数选择)"""
    if not trend_info:
        return "DEFAULT"
    trend_x4 = trend_info.get("trend_x4", "SIDE")
    if trend_x4 in ("UP", "DOWN"):
        return "TRENDING"
    # trend_x4 == SIDE 时看 current_regime
    current_regime = trend_info.get("current_regime", "UNKNOWN")
    if current_regime == "RANGING":
        return "RANGING"
    return "DEFAULT"


def _calculate_atr_14(bars: list, period: int = 14) -> float:
    """v20.5: 计算ATR(14) - 简单平均法 (复用rob_hoffman_plugin逻辑)"""
    if not bars or len(bars) < period + 1:
        return 0.0

    trs = []
    for i in range(1, len(bars)):
        high = float(bars[i]["high"])
        low = float(bars[i]["low"])
        prev_close = float(bars[i-1]["close"])
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)

    if len(trs) < period:
        return sum(trs) / len(trs) if trs else 0.0

    return sum(trs[-period:]) / period


# ============================================================
# 日志配置
# ============================================================

def setup_logging():
    """配置日志"""
    log_dir = Path(CONFIG["log_file"]).parent
    log_dir.mkdir(parents=True, exist_ok=True)

    # Safe console handler that ignores encoding errors
    class SafeConsoleHandler(logging.StreamHandler):
        def emit(self, record):
            try:
                msg = self.format(record)
                # Try to write, replace bad chars if needed
                try:
                    self.stream.write(msg + self.terminator)
                except UnicodeEncodeError:
                    self.stream.write(msg.encode('ascii', 'replace').decode('ascii') + self.terminator)
                self.flush()
            except Exception:
                pass  # Silently ignore all console errors

    # v20.2: Safe rotating file handler for Python 3.14 + Windows compatibility
    from logging.handlers import RotatingFileHandler

    class SafeRotatingFileHandler(RotatingFileHandler):
        """RotatingFileHandler that handles OSError on Windows/Python 3.14
        v21.15: emit失败时自动重建文件句柄(OneDrive锁恢复)"""
        def shouldRollover(self, record):
            try:
                return super().shouldRollover(record)
            except OSError:
                # tell() fails on Windows with certain file states
                return False

        def emit(self, record):
            try:
                super().emit(record)
            except OSError:
                # v21.15: 句柄丢失时尝试重新打开文件
                try:
                    if self.stream:
                        self.stream.close()
                    self.stream = self._open()
                    super().emit(record)
                except Exception:
                    pass

        def flush(self):
            try:
                super().flush()
            except OSError:
                pass

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            SafeRotatingFileHandler(CONFIG["log_file"], maxBytes=50*1024*1024, backupCount=5, encoding='utf-8'),
            SafeConsoleHandler(),
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()

# ============================================================
# 工具函数
# ============================================================

def get_ny_now() -> datetime:
    """获取当前纽约时间"""
    return datetime.now(NY_TZ)


def get_current_period_start(timeframe: str) -> datetime:
    """获取当前大周期的开始时间"""
    now = get_ny_now()  # v16 P0-5: 使用纽约时间而非本地时间

    if timeframe == "1h":
        return now.replace(minute=0, second=0, microsecond=0)
    elif timeframe == "30m":
        minute = 0 if now.minute < 30 else 30
        return now.replace(minute=minute, second=0, microsecond=0)
    elif timeframe == "15m":
        minute = (now.minute // 15) * 15
        return now.replace(minute=minute, second=0, microsecond=0)
    elif timeframe == "2h":
        hour = (now.hour // 2) * 2
        return now.replace(hour=hour, minute=0, second=0, microsecond=0)
    elif timeframe == "4h":
        hour = (now.hour // 4) * 4
        return now.replace(hour=hour, minute=0, second=0, microsecond=0)
    else:
        return now.replace(minute=0, second=0, microsecond=0)


def get_next_unfreeze_time(symbol: str = None) -> datetime:
    """
    v8.2: 获取下一个解冻时间
    v16.3: 美股和加密货币统一冻结到次日纽约时间8AM
           (取消币种差异化冻结时间)

    Args:
        symbol: 品种符号（保留参数兼容性，不再使用）

    Returns:
        解冻时间（纽约时区 8AM）
    """

    # v16.3: 美股和加密货币统一冻结到次日8AM纽约时间
    # P0-Tracking 不再区分市场类型，统一使用8AM解冻
    return get_next_8am_ny()


def get_next_8am_ny() -> datetime:
    """
    v12.4: 获取下一个纽约时间8AM
    - 当前时间 < 8AM: 返回今天8AM
    - 当前时间 >= 8AM: 返回明天8AM
    """
    ny_now = get_ny_now()
    today_8am = ny_now.replace(hour=8, minute=0, second=0, microsecond=0)

    if ny_now < today_8am:
        return today_8am
    else:
        return today_8am + timedelta(days=1)


def get_today_date_ny() -> str:
    """v3.546: 获取纽约时间今天的日期字符串 YYYY-MM-DD"""
    return get_ny_now().strftime("%Y-%m-%d")


# ── Signal Gate 状态读取 (v21.21) ────────────────────────────────
_sg_scan_cache = {"data": None, "ts": 0}
_SG_SCAN_CACHE_SEC = 300    # 5分钟内存缓存
_SG_SCAN_FILE_TTL  = 4 * 3600  # 4小时文件TTL → fail-open

def _scan_read_signal_gate(symbol: str, direction: str):
    """读取 state/signal_gate_state.json (5分钟缓存).
    返回 dict(go, regime, vr, reason) 或 None (文件不存在/过期 → fail-open)."""
    import time as _sgt, json as _sgj, os as _sgo
    now = _sgt.time()
    if (_sg_scan_cache["data"] is not None
            and now - _sg_scan_cache["ts"] < _SG_SCAN_CACHE_SEC):
        data = _sg_scan_cache["data"]
    else:
        _path = _sgo.path.join("state", "signal_gate_state.json")
        if not _sgo.path.exists(_path):
            return None
        try:
            with open(_path, "r", encoding="utf-8") as _f:
                data = _sgj.load(_f)
            _sg_scan_cache["data"] = data
            _sg_scan_cache["ts"] = now
        except Exception:
            return None
    _meta = data.get("_meta", {})
    _updated = _meta.get("updated_at", "")
    if _updated:
        try:
            from datetime import datetime, timezone as _tz
            _dt = datetime.fromisoformat(_updated.replace("Z", "+00:00"))
            if now - _dt.timestamp() > _SG_SCAN_FILE_TTL:
                return None
        except Exception:
            pass
    sym_data = data.get(symbol, {})
    dir_data = sym_data.get(direction.upper())
    if not dir_data or dir_data.get("go") is None:
        return None
    return dir_data


# ── FilterChain 三道闸门状态读取 (v21.22) ───────────────────────────
_fc_scan_cache = {"data": None, "ts": 0}
_FC_SCAN_CACHE_SEC = 300       # 5分钟内存缓存
_FC_SCAN_FILE_TTL  = 4 * 3600  # 4小时文件TTL → fail-open

def _scan_read_filter_chain(symbol: str, direction: str):
    """读取 state/filter_chain_state.json (5分钟缓存).
    返回 dict(passed, vision, volume_score, micro_go, blocked_by, reason) 或 None (fail-open)."""
    import time as _fct, json as _fcj, os as _fco
    now = _fct.time()
    if (_fc_scan_cache["data"] is not None
            and now - _fc_scan_cache["ts"] < _FC_SCAN_CACHE_SEC):
        data = _fc_scan_cache["data"]
    else:
        _path = _fco.path.join("state", "filter_chain_state.json")
        if not _fco.path.exists(_path):
            return None
        try:
            with open(_path, "r", encoding="utf-8") as _f:
                data = _fcj.load(_f)
            _fc_scan_cache["data"] = data
            _fc_scan_cache["ts"] = now
        except Exception:
            return None
    _meta = data.get("_meta", {})
    _updated = _meta.get("updated_at", "")
    if _updated:
        try:
            from datetime import datetime, timezone as _tz
            _dt = datetime.fromisoformat(_updated.replace("Z", "+00:00"))
            if now - _dt.timestamp() > _FC_SCAN_FILE_TTL:
                return None
        except Exception:
            pass
    sym_data = data.get(symbol, {})
    dir_data = sym_data.get(direction.upper())
    if not dir_data or dir_data.get("passed") is None:
        return None
    return dir_data


def check_plugin_daily_limit(state: dict, action: str, trend_x4: str = None, current_trend: str = None, market_type: str = "crypto",
                             bars: list = None, current_price: float = None) -> tuple:
    """
    v3.546: 检查外挂每日买卖限制
    v15.2: 修复冻结优先级bug
    v17.5: 简化为只检查配额，方向过滤由外层check_x4_trend_filter()处理
           - 每天 BUY 1次 + SELL 1次 (美股/加密货币统一)
           - 配额用完后冻结至次日NY 8AM
    v20.5: 急跌保护 - 当前K线跌≥5%时绕过SELL配额限制

    Args:
        state: 外挂状态字典
        action: "BUY" 或 "SELL"
        trend_x4: (已废弃，保留兼容) x4大周期趋势
        current_trend: (已废弃，保留兼容) 当前周期趋势
        market_type: (已废弃，保留兼容) "crypto" 或 "stock"
        bars: (可选) K线数据，用于急跌检测
        current_price: (可选) 当前价格，用于急跌检测

    Returns:
        (can_trade: bool, reason: str)
    """
    today = get_today_date_ny()
    ny_now = get_ny_now()

    # v15.2: 先检查冻结时间是否仍有效（优先级最高）
    freeze_until_str = state.get("freeze_until")
    if freeze_until_str:
        try:
            freeze_dt = datetime.fromisoformat(freeze_until_str)
            if freeze_dt.tzinfo is None:
                freeze_dt = freeze_dt.replace(tzinfo=ZoneInfo("America/New_York"))

            if ny_now < freeze_dt:
                # 冻结仍有效，不管日期是否变化
                return (False, f"冻结至 {freeze_dt.strftime('%m-%d %H:%M')} NY")
            else:
                # 冻结已过期，重置状态
                state["buy_used"] = False
                state["sell_used"] = False
                state["freeze_until"] = None
                state["reset_date"] = today
                return (True, "冻结已解除")
        except Exception as e:
            logger.warning(f"解析冻结时间失败: {freeze_until_str}, {e}")

    # v15.2: 冻结无效或不存在时，才检查日期重置
    if state.get("reset_date") != today:
        # 新的一天，重置状态
        state["buy_used"] = False
        state["sell_used"] = False
        state["freeze_until"] = None
        state["reset_date"] = today
        return (True, "新一天开始")

    # v17.5: 统一配额检查 (方向过滤由外层check_x4_trend_filter处理)
    if action == "BUY" and state.get("buy_used"):
        return (False, "今日买入已用(1/1)")
    if action == "SELL" and state.get("sell_used"):
        # v20.5: 急跌保护 - 当前K线跌≥5%时绕过卖出配额限制
        crash, drop_pct = is_crash_bar(bars, current_price)
        if crash:
            return (True, f"急跌保护绕过配额(跌{drop_pct:.1f}%≥{CRASH_SELL_THRESHOLD_PCT}%)")
        return (False, "今日卖出已用(1/1)")

    return (True, "可交易")


def detect_n_pattern_break(bars: list, x4_direction: str) -> tuple:
    """
    v21.9: N字判断 — 检测趋势是否止跌/止涨

    下跌N字: 高→低→高→低(更低) = 趋势延续
             高→低→高→低(更高) = 止跌 → 允许BUY
    上涨N字: 低→高→低→高(更高) = 趋势延续
             低→高→低→高(更低) = 止涨 → 允许SELL

    使用5-bar摆点: bar[i]为局部极值 if min/max in [i-2, i+2]
    只看最近20根K线的摆点(约5个交易日/1天加密)
    """
    if not bars or len(bars) < 12:
        return False, "K线不足"

    # 只看最近20根
    recent = bars[-20:] if len(bars) > 20 else bars
    window = 2  # 5-bar pivot

    if x4_direction == "DOWN":
        # 找swing lows (局部最低点)
        swing_lows = []
        for i in range(window, len(recent) - window):
            low_i = recent[i]["low"]
            is_swing = all(low_i <= recent[i + j]["low"] for j in range(-window, window + 1) if j != 0)
            if is_swing:
                swing_lows.append((i, low_i))
        if len(swing_lows) >= 2:
            prev_low = swing_lows[-2][1]
            latest_low = swing_lows[-1][1]
            if latest_low > prev_low:
                return True, f"N字止跌: 低点{latest_low:.2f}>{prev_low:.2f}(更高的低)"
        return False, ""

    elif x4_direction == "UP":
        # 找swing highs (局部最高点)
        swing_highs = []
        for i in range(window, len(recent) - window):
            high_i = recent[i]["high"]
            is_swing = all(high_i >= recent[i + j]["high"] for j in range(-window, window + 1) if j != 0)
            if is_swing:
                swing_highs.append((i, high_i))
        if len(swing_highs) >= 2:
            prev_high = swing_highs[-2][1]
            latest_high = swing_highs[-1][1]
            if latest_high < prev_high:
                return True, f"N字止涨: 高点{latest_high:.2f}<{prev_high:.2f}(更低的高)"
        return False, ""

    return False, ""


def check_x4_trend_filter(action: str, trend_x4: str, current_trend: str = None,
                          bars: list = None) -> tuple:
    """
    v21.9: 第一层 — 顺大(x4定方向) + N字止跌/止涨豁免

    三层架构 (trend_filter_enhancement.docx):
      第一层: x4定方向 → 本函数 (顺大) + N字判断
      第二层: EMA5+K线 → check_ema5_momentum_filter() (逆小)
      第三层: 各外挂自身逻辑 → 下单

    规则:
      x4=DOWN → 禁止BUY，除非N字止跌(最近低点>前一低点)
      x4=UP   → 禁止SELL，除非N字止涨(最近高点<前一高点)
      x4=SIDE → 双向允许

    适用: 所有外挂 (传bars参数启用N字检测)
    不适用: P0-Tracking (保命用，不受限制), 移动止盈(仓位管理)
    """
    # GCC-0049: x4顺大逆小完全取消, 所有方向允许, 靠FilterChain+门禁过滤
    x4 = (trend_x4 or "SIDE").upper()
    return (True, f"GCC-0049: x4={x4}顺大逆小已取消，允许{action}")



# v17.2: P0信号保护配置
P0_PROTECTION_MAX_HOURS = 4  # P0信号后最大保护期(小时)


def check_p0_signal_protection(tracking_state: dict, symbol: str, action: str,
                               plugin_name: str, current_trend: str = None) -> tuple:
    """
    v17.2: P0信号保护检查 (动态保护模式)

    保护逻辑:
    - P0-Tracking/移动止盈 BUY后 → 阻止其他外挂SELL (防止抄底被平)
    - P0-Tracking/移动止损 SELL后 → 阻止其他外挂BUY (防止抓顶被补)

    动态保护结束条件 (满足任一):
    1. BUY保护: current_trend变为UP (L1确认反转向上)
    2. SELL保护: current_trend变为DOWN (L1确认反转向下)
    3. 超过4小时最大保护期
    4. P0自身的反向信号 (plugin_name含"P0"或"移动")

    Args:
        tracking_state: P0-Tracking状态字典 (整个字典，包含所有品种)
        symbol: 品种代码
        action: "BUY" 或 "SELL" - 当前外挂想要执行的动作
        plugin_name: 外挂名称 (用于日志和豁免判断)
        current_trend: 当前周期L1趋势 (用于动态解除保护)

    Returns:
        (allowed: bool, reason: str)
    """
    # P0系列外挂豁免 - 允许P0自己操作
    if "P0" in plugin_name or "移动" in plugin_name:
        return (True, "P0自身信号豁免")

    # 获取该品种的保护状态
    state = tracking_state.get(symbol, {})
    current_upper = (current_trend or "SIDE").upper()

    # ===== 检查BUY保护 (P0 BUY后阻止其他SELL) =====
    if action == "SELL":
        buy_protection = state.get("p0_buy_protection_until")
        if buy_protection:
            # 动态解除: current_trend=UP 确认反转向上
            if current_upper == "UP":
                state["p0_buy_protection_until"] = None
                logger.info(f"[v17.2] {symbol} P0抄底保护解除: current_trend=UP")
                return (True, "L1确认向上，抄底保护解除")

            # 检查最大保护期
            try:
                protection_dt = datetime.fromisoformat(buy_protection)
                now = datetime.now()
                if now < protection_dt:
                    remaining = (protection_dt - now).total_seconds() / 3600
                    reason = f"P0抄底保护: 阻止{plugin_name} SELL (剩余{remaining:.1f}h, 等待L1=UP)"
                    return (False, reason)
                else:
                    state["p0_buy_protection_until"] = None
                    logger.info(f"[v17.2] {symbol} P0抄底保护过期")
            except Exception:
                pass

    # ===== 检查SELL保护 (P0 SELL后阻止其他BUY) =====
    if action == "BUY":
        sell_protection = state.get("p0_sell_protection_until")
        if sell_protection:
            # 动态解除: current_trend=DOWN 确认反转向下
            if current_upper == "DOWN":
                state["p0_sell_protection_until"] = None
                logger.info(f"[v17.2] {symbol} P0抓顶保护解除: current_trend=DOWN")
                return (True, "L1确认向下，抓顶保护解除")

            # 检查最大保护期
            try:
                protection_dt = datetime.fromisoformat(sell_protection)
                now = datetime.now()
                if now < protection_dt:
                    remaining = (protection_dt - now).total_seconds() / 3600
                    reason = f"P0抓顶保护: 阻止{plugin_name} BUY (剩余{remaining:.1f}h, 等待L1=DOWN)"
                    return (False, reason)
                else:
                    state["p0_sell_protection_until"] = None
                    logger.info(f"[v17.2] {symbol} P0抓顶保护过期")
            except Exception:
                pass

    return (True, "")


def detect_dc_regime(bars: list, current_price: float, lookback: int = 20) -> str:
    """
    v21.6: 检测唐纳奇通道状态 — 震荡/突破/跌破

    用前lookback根K线(不含当前K线)构建参考通道,
    判断当前价格是否突破上轨或跌破下轨。

    Returns:
        "breakout_up"   — 当前价格 > 前N根最高价 (上涨突破)
        "breakout_down" — 当前价格 < 前N根最低价 (下跌破位)
        "oscillating"   — 通道内震荡
    """
    if not bars or len(bars) < lookback + 1 or not current_price:
        return "oscillating"
    prev_bars = bars[-(lookback + 1):-1]
    dc_upper = max(b["high"] for b in prev_bars)
    dc_lower = min(b["low"] for b in prev_bars)
    if current_price > dc_upper:
        return "breakout_up"
    elif current_price < dc_lower:
        return "breakout_down"
    return "oscillating"


def check_rhythm_quality(action: str, pos_in_channel: float, source: str = "",
                         dc_regime: str = "oscillating",
                         symbol: str = "", **kwargs) -> tuple:
    """
    v21.8: 买卖节奏质量过滤 (品种分化+波动自适应)

    SELL阈值根据唐纳奇通道状态动态调整:
    - 震荡(通道内): 45% — 高抛低吸,保护低位割肉
    - 突破上轨:     30% — 通道上移,适度放松
    - 跌破下轨:     55% — 通道下移,更严格保护
    高波动regime(跌破下轨)额外上浮5%保护

    BUY阈值: 加密货币75%(执行延迟风险大) / 美股65%。
    豁免: 双底双顶/MACD背离的BUY/SELL (反转信号免检)
    不适用: 移动止损 (有独立的唐纳奇保护)

    Returns:
        (allowed: bool, reason: str)
    """
    _REVERSAL_SOURCES = ("双底双顶", "MACD背离")

    # v21.8: BUY上限按品种分化 — 加密75%(延迟风险大)/美股65%
    _is_crypto = is_crypto_symbol(symbol) if symbol else True
    buy_threshold = 0.75 if _is_crypto else 0.65

    # v21.12 RES-007: 趋势阶段风险预算 — 初期降低BUY门槛, 末期提高
    # v21.12 增强: market_regime标签 + FINSABER论文参数 (arXiv:2505.07078)
    # Phase 1: 仅记录对比, 不调整实际阈值
    _phase_info = kwargs.get("trend_phase") if kwargs else None
    if _phase_info and _phase_info.get("phase") != "NEUTRAL":
        _adj = _phase_info["risk_budget"]["rhythm_adjust"]
        _regime = _phase_info.get("market_regime", "sideways")
        _phase_threshold = max(0.30, min(0.85, buy_threshold + _adj))
        if ENABLE_TREND_PHASE_RISK:
            buy_threshold = _phase_threshold
        elif action == "BUY":
            print(f"[v21.12] 阶段风险[观察]: phase={_phase_info['phase']} "
                  f"regime={_regime} BUY阈值 原{buy_threshold:.0%}→建议{_phase_threshold:.0%} "
                  f"(adjust={_adj:+.0%}, 未启用)")

    # v21.21: 固定10%压力/支撑区间 — 只看绝对边界，不再区分regime
    # 顶部10%不买(压力保护)，底部10%不卖(支撑保护)
    DC_BOUNDARY = 0.10

    # v21.22 SYS-034: Regime自适应阈值 (Phase1: 仅观察, ENABLED=False)
    # bull: BUY_boundary=0.05(顺势放宽) SELL_boundary=0.05(止损易出)
    # sideways: 均0.10(当前默认)
    # bear: BUY_boundary=0.15(逆势严控) SELL_boundary=0.05(快速止损)
    ENABLE_REGIME_ADAPTIVE_THRESHOLD = False  # Phase2改True
    _phase_info_r = kwargs.get("trend_phase") if kwargs else None
    _market_regime = (_phase_info_r.get("market_regime", "sideways") if _phase_info_r else "sideways")
    _regime_buy_boundary  = {"bull": 0.05, "sideways": 0.10, "bear": 0.15}.get(_market_regime, 0.10)
    _regime_sell_boundary = {"bull": 0.05, "sideways": 0.10, "bear": 0.05}.get(_market_regime, 0.10)
    if ENABLE_REGIME_ADAPTIVE_THRESHOLD:
        _buy_boundary  = _regime_buy_boundary
        _sell_boundary = _regime_sell_boundary
    else:
        _buy_boundary  = DC_BOUNDARY
        _sell_boundary = DC_BOUNDARY
        if _market_regime != "sideways" and (_regime_buy_boundary != DC_BOUNDARY or _regime_sell_boundary != DC_BOUNDARY):
            logger.debug(f"[SYS-034][观察] {symbol} {action} regime={_market_regime} "
                         f"建议BUY_boundary={_regime_buy_boundary:.0%} SELL_boundary={_regime_sell_boundary:.0%} "
                         f"(当前固定{DC_BOUNDARY:.0%}, 未启用)")

    if action == "BUY" and pos_in_channel > (1.0 - _buy_boundary):
        if any(r in source for r in _REVERSAL_SOURCES):
            return (True, f"反转信号免检(pos={pos_in_channel:.0%})")
        return (False, f"压力拦截: 通道位置{pos_in_channel:.0%}>{ (1-_buy_boundary):.0%}(顶部{_buy_boundary:.0%}区间)")

    if action == "SELL" and pos_in_channel < _sell_boundary:
        if any(r in source for r in _REVERSAL_SOURCES):
            return (True, f"反转信号免检(pos={pos_in_channel:.0%})")
        return (False, f"支撑拦截: 通道位置{pos_in_channel:.0%}<{_sell_boundary:.0%}(底部{_sell_boundary:.0%}区间)")

    # v21.11 SYS-026: Donchian量价增强观察
    # Phase 1: 仅记录vol_density, 不影响节奏过滤决策
    _rhythm_bars = kwargs.get("bars") if kwargs else None
    if _rhythm_bars and len(_rhythm_bars) >= 10:
        try:
            _dvs = _vol_analyzer.get_donchian_volume_score(_rhythm_bars, pos_in_channel)
            print(f"[v21.11] Donchian量价[观察]: {symbol} pos={pos_in_channel:.0%} "
                  f"vol_density={_dvs['vol_density']:.2f} score={_dvs['score']:.3f} "
                  f"→{_dvs['suggestion']}")
        except Exception:
            pass

    return (True, "")


def set_p0_buy_protection(state: dict, hours: int = P0_PROTECTION_MAX_HOURS) -> str:
    """
    v17.2: 设置P0抄底保护期 (BUY后阻止其他SELL)

    Args:
        state: 单个品种的tracking状态
        hours: 最大保护时长(小时)

    Returns:
        保护截止时间字符串
    """
    protection_until = datetime.now() + timedelta(hours=hours)
    state["p0_buy_protection_until"] = protection_until.isoformat()
    # 清除反向保护
    state["p0_sell_protection_until"] = None
    return protection_until.strftime("%H:%M:%S")


def set_p0_sell_protection(state: dict, hours: int = P0_PROTECTION_MAX_HOURS) -> str:
    """
    v17.2: 设置P0抓顶保护期 (SELL后阻止其他BUY)

    Args:
        state: 单个品种的tracking状态
        hours: 最大保护时长(小时)

    Returns:
        保护截止时间字符串
    """
    protection_until = datetime.now() + timedelta(hours=hours)
    state["p0_sell_protection_until"] = protection_until.isoformat()
    # 清除反向保护
    state["p0_buy_protection_until"] = None
    return protection_until.strftime("%H:%M:%S")


def check_first_position_bar_freeze(state: dict, action: str,
                                     position: int,
                                     current_bar_start: str,
                                     bars: list = None,
                                     current_price: float = None) -> tuple:
    """
    v21.17: 同K线单方向冻结 (替换v20.1首末档限制)

    统一规则: 同一根K线内只允许单方向交易, 最多2次
    - 已有BUY记录 → 阻止SELL (crash-sell豁免)
    - 已有SELL记录 → 阻止BUY
    - 同方向已达2次 → 阻止 (crash-sell豁免)
    - K线切换 → 自动重置

    Args:
        state: 单个品种的tracking状态
        action: "BUY" 或 "SELL"
        position: 当前仓位 (0-5)
        current_bar_start: 当前K线周期开始时间
        bars: (可选) K线数据，用于急跌检测
        current_price: (可选) 当前价格，用于急跌检测

    Returns:
        (allowed: bool, reason: str)
    """
    # crash-sell豁免
    if action == "SELL" and bars and current_price is not None:
        crash, drop_pct = is_crash_bar(bars, current_price)
        if crash:
            return (True, f"急跌保护绕过K线冻结(跌{drop_pct:.1f}%)")

    # K线切换 → 无冻结
    freeze_bar = state.get("bar_freeze_bar_start")
    if not freeze_bar or freeze_bar != current_bar_start:
        return (True, "")

    freeze_dir = state.get("bar_freeze_dir")
    freeze_count = state.get("bar_freeze_count", 0)

    # 反方向 → 阻止
    if freeze_dir and freeze_dir != action:
        return (False, f"同K线已有{freeze_dir}x{freeze_count}, 禁止反向{action}(等K线结束)")

    # 同方向已达2次 → 阻止
    if freeze_dir == action and freeze_count >= 2:
        return (False, f"同K线{action}已达{freeze_count}次上限(等K线结束)")

    return (True, "")


# =============================================================================
# v17.3: Position Control - 立体仓位控制系统
# 目标: 让外挂互相协调，有序管理仓位
# 原则: 只依赖当前仓位，重启无影响，异常允许但记录
# =============================================================================

def calculate_ema10(ohlcv_bars: list) -> float:
    """
    v17.3: 计算EMA10用于Position Control仓位3-4的过滤

    从K线close价格序列计算10日EMA。

    Args:
        ohlcv_bars: K线数据列表，每项含 {close: float, ...}

    Returns:
        EMA10值，如果数据不足返回0.0
    """
    if not ohlcv_bars or len(ohlcv_bars) < 10:
        return 0.0

    # 提取close价格序列
    closes = [bar.get("close", 0) for bar in ohlcv_bars if bar.get("close")]
    if len(closes) < 10:
        return 0.0

    # EMA计算: 取最近的数据
    period = 10
    multiplier = 2 / (period + 1)

    # 初始SMA作为起点
    ema = sum(closes[:period]) / period

    # 迭代计算EMA
    for price in closes[period:]:
        ema = (price - ema) * multiplier + ema

    return ema


def calculate_ema5(ohlcv_bars: list) -> float:
    """
    v17.4: 计算EMA5用于Position Control仓位1/2买入和4/5卖出的过滤

    从K线close价格序列计算5日EMA。

    Args:
        ohlcv_bars: K线数据列表，每项含 {close: float, ...}

    Returns:
        EMA5值，如果数据不足返回0.0
    """
    if not ohlcv_bars or len(ohlcv_bars) < 5:
        return 0.0

    # 提取close价格序列
    closes = [bar.get("close", 0) for bar in ohlcv_bars if bar.get("close")]
    if len(closes) < 5:
        return 0.0

    # EMA计算: 取最近的数据
    period = 5
    multiplier = 2 / (period + 1)

    # 初始SMA作为起点
    ema = sum(closes[:period]) / period

    # 迭代计算EMA
    for price in closes[period:]:
        ema = (price - ema) * multiplier + ema

    return ema


# v21.7: EMA顺势过滤开关 (Phase3: False=只记录不拦截, Phase4: True=拦截)
ENABLE_EMA5_BLOCK = True  # v21.23 Phase4: 缠论BS有效率73%，升级真拦截

# v3.653: EMA窗口品种分化 — 论文Walk-Forward启发
# 加密货币波动大，用EMA8(更平滑减少噪声)；美股用EMA5(更灵敏)
EMA_PERIOD_CRYPTO = 8
EMA_PERIOD_STOCK = 5


def calculate_ema(ohlcv_bars: list, period: int = 5) -> float:
    """v3.653: 通用EMA计算，支持可配周期"""
    if not ohlcv_bars or len(ohlcv_bars) < period:
        return 0.0
    closes = [bar.get("close", 0) for bar in ohlcv_bars if bar.get("close")]
    if len(closes) < period:
        return 0.0
    multiplier = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for price in closes[period:]:
        ema = (price - ema) * multiplier + ema
    return ema


def check_ema5_momentum_filter(action: str, bars: list, current_price: float,
                                plugin_source: str, symbol: str = None) -> tuple:
    """
    v21.7: EMA顺势过滤 — "逆小"时不入场
    v3.653: EMA窗口品种分化 — 加密EMA8/美股EMA5

    BUY:  price < EMA 且 前1根阴线 → BLOCK (回调中不买)
    SELL: price > EMA 且 前1根阳线 → BLOCK (反弹中不卖)
    其他情况 → ALLOW

    Phase 3: ENABLE_EMA5_BLOCK=False → 只记录不拦截
    Phase 4: ENABLE_EMA5_BLOCK=True  → 实际拦截

    Args:
        action: "BUY" 或 "SELL"
        bars: OHLCV K线数据列表
        current_price: 当前价格
        plugin_source: 外挂名称 (用于日志)
        symbol: 品种代码 (用于EMA窗口分化)

    Returns:
        (allowed: bool, reason: str)
    """
    # v3.653: 按品种选EMA周期
    _period = EMA_PERIOD_CRYPTO if (symbol and is_crypto_symbol(symbol)) else EMA_PERIOD_STOCK

    if not bars or len(bars) < _period + 1 or not current_price or current_price <= 0:
        return (True, "")

    ema_val = calculate_ema(bars, _period)
    if ema_val <= 0:
        return (True, "")

    # 前1根K线方向 (bars[-1]是当前未完成K线, bars[-2]是前1根完整K线)
    prev_bar = bars[-2] if len(bars) >= 2 else bars[-1]
    prev_open = prev_bar.get("open", 0)
    prev_close = prev_bar.get("close", 0)
    is_bearish = prev_close < prev_open
    is_bullish = prev_close > prev_open

    _ema_label = f"EMA{_period}"
    if action == "BUY" and current_price < ema_val and is_bearish:
        reason = f"{_ema_label}逆势: price({current_price:.2f})<{_ema_label}({ema_val:.2f})+阴线 → 回调中不买({plugin_source})"
        if ENABLE_EMA5_BLOCK:
            return (False, reason)
        return (True, f"[观察] {reason}")

    if action == "SELL" and current_price > ema_val and is_bullish:
        reason = f"{_ema_label}逆势: price({current_price:.2f})>{_ema_label}({ema_val:.2f})+阳线 → 反弹中不卖({plugin_source})"
        if ENABLE_EMA5_BLOCK:
            return (False, reason)
        return (True, f"[观察] {reason}")

    return (True, "")


def check_prev_bar_bullish(ohlcv_bars: list) -> bool:
    """
    v17.4: 检查前一根完整K线是否为阳线
    阳线定义: close > open

    用于仓位0→1首次买入的多头确认。

    Args:
        ohlcv_bars: K线数据列表，最后一根是当前未完成K线

    Returns:
        True = 前一根是阳线, False = 前一根是阴线或数据不足
    """
    if not ohlcv_bars or len(ohlcv_bars) < 2:
        return False

    # 倒数第二根 = 前一根完整K线
    prev_bar = ohlcv_bars[-2]
    prev_open = prev_bar.get("open", 0)
    prev_close = prev_bar.get("close", 0)

    return prev_close > prev_open


# ============================================================
# v21.8: 跨周期共识度评分 (P0改善: 5源加权投票)
# ============================================================

# 模块级方向缓存 — 每个品种最新的各信号源方向
# 格式: {symbol: {"x4_trend": "UP", "supertrend": "DOWN", ...}}
_consensus_direction_cache = {}


def _direction_to_vote(direction: str, action: str) -> int:
    """
    将方向字符串转为投票值 (+1 同向 / -1 反向 / 0 中性)

    direction: "UP"/"DOWN"/"SIDE"/"STRONG_BUY"/"BUY"/"HOLD"/"SELL"/"STRONG_SELL"
    action: "BUY" or "SELL"
    """
    d = (direction or "").upper()
    if action == "BUY":
        if d in ("UP", "BUY", "STRONG_BUY"):
            return +1
        elif d in ("DOWN", "SELL", "STRONG_SELL"):
            return -1
        else:
            return 0
    else:  # SELL
        if d in ("DOWN", "SELL", "STRONG_SELL"):
            return +1
        elif d in ("UP", "BUY", "STRONG_BUY"):
            return -1
        else:
            return 0


def update_consensus_direction(symbol: str, source: str, direction: str):
    """更新品种的信号源方向缓存"""
    if symbol not in _consensus_direction_cache:
        _consensus_direction_cache[symbol] = {}
    _consensus_direction_cache[symbol][source] = (direction or "SIDE").upper()


def calc_consensus_score(symbol: str, action: str, trend_info: dict = None) -> dict:
    """
    v21.8: 计算跨周期共识度评分

    从趋势缓存 + 方向缓存读取5个信号源方向,加权投票。
    Phase 1: 只计算+日志, 不拦截。

    Args:
        symbol: 品种 (yfinance格式或主程序格式都可)
        action: "BUY" or "SELL"
        trend_info: _get_trend_for_plugin()的返回值 (可选, 直传避免重复读)

    Returns:
        {
            "score": float,       # 共识度 [-1.0, +1.0]
            "abs_score": float,   # |score|
            "votes": dict,        # 各源投票详情 {"x4_trend": +1, ...}
            "weights": dict,      # 各源权重
            "would_block": bool,  # Phase2时是否会拦截
            "label": str,         # "高共识"/"中共识"/"低共识"
        }
    """
    from timeframe_params import CONSENSUS_WEIGHTS, CONSENSUS_BLOCK_THRESHOLD, CONSENSUS_BOOST_THRESHOLD

    # 收集各源方向
    cached = _consensus_direction_cache.get(symbol, {})

    # 1. x4_trend: 从trend_info (最新)
    x4_dir = "SIDE"
    if trend_info:
        x4_dir = trend_info.get("trend_x4", "SIDE")
    elif cached.get("x4_trend"):
        x4_dir = cached["x4_trend"]

    # 2. current_trend: 从trend_info (缠论当前周期)
    cur_dir = "SIDE"
    if trend_info:
        cur_dir = trend_info.get("trend", "SIDE")
    elif cached.get("current_trend"):
        cur_dir = cached["current_trend"]

    # 3. vision: 从方向缓存 (主程序通过HTTP更新)
    vision_dir = cached.get("vision", "SIDE")

    # 4. supertrend: 从方向缓存 (最近一次ST扫描结果)
    st_dir = cached.get("supertrend", "SIDE")

    # v3.676: 去掉l2_rec(几乎全HOLD=死权重), 4源投票

    # 计算投票
    votes = {
        "x4_trend":      _direction_to_vote(x4_dir, action),
        "current_trend": _direction_to_vote(cur_dir, action),
        "vision":        _direction_to_vote(vision_dir, action),
        "supertrend":    _direction_to_vote(st_dir, action),
    }

    # 加权汇总
    score = sum(votes[src] * CONSENSUS_WEIGHTS[src] for src in votes)
    abs_score = abs(score)

    # v21.13 SYS-020: 自适应共识阈值 (Phase 1 观察)
    # 趋势市降低阈值(放行更多), 震荡市提高阈值(从严)
    # v21.14修复: trend_info返回regime="TRENDING"/"RANGING" + trend="UP"/"DOWN"/"SIDE"
    #   而非market_regime="bull"/"bear"/"sideways", 需映射
    _regime = "sideways"
    if trend_info:
        _raw_regime = trend_info.get("regime", trend_info.get("current_regime", ""))
        _trend_dir = trend_info.get("trend", "SIDE")
        if _raw_regime == "TRENDING":
            _regime = "bull" if _trend_dir == "UP" else ("bear" if _trend_dir == "DOWN" else "sideways")
        else:
            _regime = "sideways"
    _adaptive_threshold = {"bull": 0.20, "bear": 0.20, "sideways": 0.35}.get(_regime, CONSENSUS_BLOCK_THRESHOLD)

    # v21.13 SYS-020: 校准器相关性检测 — 全同向=过度一致→惩罚
    _vote_vals = [v for v in votes.values() if v != 0]
    _all_agree = len(_vote_vals) >= 4 and len(set(_vote_vals)) == 1
    _corr_penalty = 0.90 if _all_agree else 1.0
    _adaptive_score = abs_score * _corr_penalty

    # 分级 (使用原阈值,保持现有行为不变)
    if abs_score >= CONSENSUS_BOOST_THRESHOLD:
        label = "高共识"
    elif abs_score >= CONSENSUS_BLOCK_THRESHOLD:
        label = "中共识"
    else:
        label = "低共识"

    # v21.13: 自适应判断 (Phase 1仅记录)
    _would_block_adaptive = _adaptive_score < _adaptive_threshold
    _adaptive_label = "高" if _adaptive_score >= CONSENSUS_BOOST_THRESHOLD else ("中" if _adaptive_score >= _adaptive_threshold else "低")

    return {
        "score": round(score, 3),
        "abs_score": round(abs_score, 3),
        "votes": votes,
        "weights": dict(CONSENSUS_WEIGHTS),
        "would_block": False,   # v21.29: 取消共识度拦截(权重已归零,不再显示[将拦截])
        "label": label,
        # v21.13 SYS-020 Phase 1 观察字段
        "adaptive_threshold": round(_adaptive_threshold, 2),
        "adaptive_score": round(_adaptive_score, 3),
        "would_block_adaptive": _would_block_adaptive,
        "adaptive_label": _adaptive_label,
        "regime": _regime,
        "corr_penalty": _corr_penalty,
        "sources": {
            "x4_trend": x4_dir,
            "current_trend": cur_dir,
            "vision": vision_dir,
            "supertrend": st_dir,
        },
    }


def log_consensus_score(symbol: str, action: str, source: str, consensus: dict):
    """格式化输出共识度日志"""
    score = consensus["score"]
    label = consensus["label"]
    votes = consensus["votes"]
    sources = consensus["sources"]
    would_block = consensus["would_block"]

    vote_strs = []
    for src in ["x4_trend", "current_trend", "vision", "supertrend"]:
        v = votes[src]
        d = sources[src]
        mark = "+" if v > 0 else ("-" if v < 0 else "0")
        vote_strs.append(f"{src}={d}({mark})")

    block_tag = " [将拦截]" if would_block else ""
    # v21.13 SYS-020: 追加自适应共识度对比
    _adap_thr = consensus.get("adaptive_threshold", 0.30)
    _adap_score = consensus.get("adaptive_score", abs(score))
    _adap_label = consensus.get("adaptive_label", label)
    _regime = consensus.get("regime", "?")
    _corr = consensus.get("corr_penalty", 1.0)
    _adap_block = consensus.get("would_block_adaptive", would_block)
    _diff_tag = ""
    if _adap_block != would_block:
        _diff_tag = f" [自适应→{'拦截' if _adap_block else '放行'}≠原判]"
    _corr_tag = f" corr×{_corr}" if _corr < 1.0 else ""
    logger.info(f"[v21.8] {symbol} {source} {action} 共识度={score:+.3f}({label}){block_tag} | {' '.join(vote_strs)}")
    logger.info(f"[CONSENSUS_ADAPTIVE] {symbol} {action} regime={_regime} 原阈值=0.30→自适应={_adap_thr} "
                  f"score={_adap_score:.3f}({_adap_label}){_corr_tag}{_diff_tag}")


def check_prev_bar_bearish(ohlcv_bars: list) -> bool:
    """
    v17.4: 检查前一根完整K线是否为阴线
    阴线定义: close < open

    用于仓位5→4首次卖出的空头确认。

    Args:
        ohlcv_bars: K线数据列表，最后一根是当前未完成K线

    Returns:
        True = 前一根是阴线, False = 前一根是阳线或数据不足
    """
    if not ohlcv_bars or len(ohlcv_bars) < 2:
        return False

    prev_bar = ohlcv_bars[-2]
    prev_open = prev_bar.get("open", 0)
    prev_close = prev_bar.get("close", 0)

    return prev_close < prev_open


def check_new_high_breakout(ohlcv_bars: list, current_price: float, lookback: int = 5) -> tuple:
    """
    v20.4: 检查是否创新高 (突破确认) - 基于实体价格

    用于仓位2+买入的突破确认：当前价格必须高于最近N根完整K线中最高的实体高点
    避免在震荡市场中频繁加仓

    实体高点 = max(open, close)，不含上影线
    v20.4: 看最近5根而非仅前1根，避免十字星导致门槛过低

    Args:
        ohlcv_bars: K线数据列表，最后一根是当前未完成K线
        current_price: 当前价格
        lookback: 回看K线数量，默认5

    Returns:
        (is_breakout: bool, max_body_high: float, reason: str)
    """
    if not ohlcv_bars or len(ohlcv_bars) < 2:
        return (True, 0, "无K线数据,默认通过")

    if current_price is None:
        return (True, 0, "无当前价格,默认通过")

    # v20.4: 取最近lookback根已完成K线的实体最高点
    completed = ohlcv_bars[:-1][-lookback:]
    max_body_high = 0
    for bar in completed:
        body_high = max(bar.get("open", 0), bar.get("close", 0))
        if body_high > max_body_high:
            max_body_high = body_high

    if max_body_high <= 0:
        return (True, 0, "K线实体无效,默认通过")

    if current_price > max_body_high:
        return (True, max_body_high, f"突破{lookback}根实体高✓({current_price:.2f}>{max_body_high:.2f})")
    else:
        return (False, max_body_high, f"未破{lookback}根实体高({current_price:.2f}<={max_body_high:.2f})")


def check_new_low_breakdown(ohlcv_bars: list, current_price: float, lookback: int = 5) -> tuple:
    """
    v20.4: 检查是否创新低 (跌破确认) - 基于实体价格

    用于仓位3-卖出的跌破确认：当前价格必须低于最近N根完整K线中最低的实体低点
    避免在震荡市场中频繁减仓

    实体低点 = min(open, close)，不含下影线
    v20.4: 看最近5根而非仅前1根，避免十字星导致门槛过低

    Args:
        ohlcv_bars: K线数据列表，最后一根是当前未完成K线
        current_price: 当前价格
        lookback: 回看K线数量，默认5

    Returns:
        (is_breakdown: bool, min_body_low: float, reason: str)
    """
    if not ohlcv_bars or len(ohlcv_bars) < 2:
        return (True, 0, "无K线数据,默认通过")

    if current_price is None:
        return (True, 0, "无当前价格,默认通过")

    # v20.4: 取最近lookback根已完成K线的实体最低点
    completed = ohlcv_bars[:-1][-lookback:]
    min_body_low = float('inf')
    for bar in completed:
        body_low = min(bar.get("open", 0), bar.get("close", 0))
        if body_low > 0 and body_low < min_body_low:
            min_body_low = body_low

    if min_body_low == float('inf') or min_body_low <= 0:
        return (True, 0, "K线实体无效,默认通过")

    if current_price < min_body_low:
        return (True, min_body_low, f"跌破{lookback}根实体低✓({current_price:.2f}<{min_body_low:.2f})")
    else:
        return (False, min_body_low, f"未破{lookback}根实体低({current_price:.2f}>={min_body_low:.2f})")


def check_merged_bars_bullish(ohlcv_bars: list, count: int) -> bool:
    """
    v18: 检查前N根K线合并后是否为阳线
    只看开始和结束，不看最高最低

    合并逻辑:
    - 合并开盘价 = 第-(count+1)根的open (倒数第count+1根，即合并区间的第一根)
    - 合并收盘价 = 第-2根的close (倒数第2根，即合并区间的最后一根完整K线)
    - 阳线: 合并收盘价 > 合并开盘价

    Args:
        ohlcv_bars: K线数据列表，最后一根是当前未完成K线
        count: 要合并的K线数量 (2 或 3)

    Returns:
        True = 合并后是阳线, False = 合并后是阴线或数据不足
    """
    # 需要 count+1 根K线: count根要合并的 + 1根当前未完成的
    if not ohlcv_bars or len(ohlcv_bars) < count + 1:
        return False

    # 合并区间: bars[-(count+1)] 到 bars[-2]
    # 例如 count=2: bars[-3].open 到 bars[-2].close
    # 例如 count=3: bars[-4].open 到 bars[-2].close
    merged_open = ohlcv_bars[-(count + 1)].get("open", 0)
    merged_close = ohlcv_bars[-2].get("close", 0)

    return merged_close > merged_open


def check_merged_bars_bearish(ohlcv_bars: list, count: int) -> bool:
    """
    v18: 检查前N根K线合并后是否为阴线
    只看开始和结束，不看最高最低

    合并逻辑:
    - 合并开盘价 = 第-(count+1)根的open
    - 合并收盘价 = 第-2根的close
    - 阴线: 合并收盘价 < 合并开盘价

    Args:
        ohlcv_bars: K线数据列表，最后一根是当前未完成K线
        count: 要合并的K线数量 (2 或 3)

    Returns:
        True = 合并后是阴线, False = 合并后是阳线或数据不足
    """
    if not ohlcv_bars or len(ohlcv_bars) < count + 1:
        return False

    merged_open = ohlcv_bars[-(count + 1)].get("open", 0)
    merged_close = ohlcv_bars[-2].get("close", 0)

    return merged_close < merged_open


def merge_body_intersection_bars(ohlcv_bars: list) -> list:
    """
    v19: 按body交集合并K线段 (body并集范围版)

    算法:
    - 从第1根bar开始，维护合并段的body并集范围 [union_bot, union_top]
    - union_top/union_bot 记录段内所有bar body的最高点和最低点
    - 每根新bar计算body范围 [b_bot, b_top]
    - 如果与并集范围有交集 (max(union_bot, b_bot) < min(union_top, b_top)):
      合并: 更新close为新bar的close, 扩展并集范围
    - 如果无交集: 切段，开始新的合并段
    - 方向判定: 段首open vs 段末close

    Args:
        ohlcv_bars: 已完成K线列表 (不含当前未完成K线)

    Returns:
        合并后的段列表 [{"open": float, "close": float}, ...]
        每段的open=段首bar的open, close=段末bar的close
    """
    if not ohlcv_bars:
        return []

    segments = []
    first = ohlcv_bars[0]
    curr_open = first.get("open", 0)
    curr_close = first.get("close", 0)
    # body并集范围: 记录段内所有bar body的最高/最低点
    union_top = max(curr_open, curr_close)
    union_bot = min(curr_open, curr_close)

    for i in range(1, len(ohlcv_bars)):
        bar = ohlcv_bars[i]
        bar_open = bar.get("open", 0)
        bar_close = bar.get("close", 0)

        # 新bar的body范围
        b_top = max(bar_open, bar_close)
        b_bot = min(bar_open, bar_close)

        # 交集判断: 用并集范围检查 (严格小于，相切=无交集)
        if max(union_bot, b_bot) < min(union_top, b_top):
            # 有交集 → 合并: 更新close，扩展并集范围
            curr_close = bar_close
            union_top = max(union_top, b_top)
            union_bot = min(union_bot, b_bot)
        else:
            # 无交集 → 切段
            segments.append({"open": curr_open, "close": curr_close})
            curr_open = bar_open
            curr_close = bar_close
            union_top = b_top
            union_bot = b_bot

    # 最后一段
    segments.append({"open": curr_open, "close": curr_close})
    return segments


def check_body_merged_bullish(ohlcv_bars: list, max_bars: int = 5) -> bool:
    """
    v19+v20.4: body交集合并后最后一段是否为阳线

    只使用最近max_bars根已完成K线进行body交集合并(只看open/close,不看影线)，
    检查合并后最后一段的方向。

    v20.4: 限制最多5根K线，避免看太远历史

    Args:
        ohlcv_bars: K线数据列表，最后一根是当前未完成K线
        max_bars: 最多合并的K线数量，默认5

    Returns:
        True = 合并后最后一段是阳线 (close > open)
    """
    if not ohlcv_bars or len(ohlcv_bars) < 3:
        return False

    # v20.4: 只取最近max_bars根已完成K线
    completed = ohlcv_bars[:-1][-max_bars:]
    segments = merge_body_intersection_bars(completed)

    if not segments:
        return False

    last = segments[-1]
    return last["close"] > last["open"]


def check_body_merged_bearish(ohlcv_bars: list, max_bars: int = 5) -> bool:
    """
    v19+v20.4: body交集合并后最后一段是否为阴线

    只使用最近max_bars根已完成K线进行body交集合并(只看open/close,不看影线)，
    检查合并后最后一段的方向。

    v20.4: 限制最多5根K线，避免看太远历史

    Args:
        ohlcv_bars: K线数据列表，最后一根是当前未完成K线
        max_bars: 最多合并的K线数量，默认5

    Returns:
        True = 合并后最后一段是阴线 (close < open)
    """
    if not ohlcv_bars or len(ohlcv_bars) < 3:
        return False

    # v20.4: 只取最近max_bars根已完成K线
    completed = ohlcv_bars[:-1][-max_bars:]
    segments = merge_body_intersection_bars(completed)

    if not segments:
        return False

    last = segments[-1]
    return last["close"] < last["open"]


# v20.5: 急跌保护阈值 - 当前K线跌幅超过此值时绕过配额/冻结限制允许多次卖出
CRASH_SELL_THRESHOLD_PCT = 5.0

# v21.28: BIAS25超卖过滤(逆势BUY门禁)
ENABLE_BIAS25_FILTER = False   # v21.29: 用户确认不需要BIAS25拦截，关闭
BIAS25_THRESHOLD_STOCK = -10.0


def is_crash_bar(bars: list, current_price: float) -> tuple:
    """
    v20.5: 检测当前K线是否为急跌K线 (跌幅≥5%)

    Args:
        bars: K线数据列表，最后一根是当前未完成K线
        current_price: 当前价格

    Returns:
        (is_crash: bool, drop_pct: float)
    """
    if not bars or len(bars) < 1 or current_price is None:
        return (False, 0.0)
    bar_open = bars[-1].get("open", 0)
    if bar_open <= 0 or current_price >= bar_open:
        return (False, 0.0)
    drop_pct = (bar_open - current_price) / bar_open * 100
    if drop_pct >= CRASH_SELL_THRESHOLD_PCT:
        return (True, drop_pct)
    return (False, drop_pct)


def _compute_bias25_pct(bars: list) -> float | None:
    """计算25日乖离率(%)，数据不足返回None。"""
    if not bars or len(bars) < 25:
        return None
    closes = [b.get("close") for b in bars[-25:] if b.get("close") is not None]
    if len(closes) < 25:
        return None
    sma25 = sum(closes) / 25.0
    if sma25 <= 0:
        return None
    return (closes[-1] - sma25) / sma25 * 100.0


def check_bias25_filter(action: str, bars: list, signal_source: str,
                        big_trend: str, current_trend: str) -> tuple:
    """
    v21.28: BIAS25超卖过滤。

    目标: 避免在x4下行中普通BUY信号过早抄底。
    规则:
    - 仅对BUY生效
    - P0/移动止盈止损豁免
    - 仅在x4=DOWN时启用硬拦截
    - 要求BIAS25 <= 阈值(-10%)
    """
    if not ENABLE_BIAS25_FILTER:
        return (True, "")

    act = (action or "").upper()
    if act != "BUY":
        return (True, "")

    src = signal_source or ""
    if "P0" in src or "移动" in src:
        return (True, "P0/移动信号豁免BIAS过滤")

    big = (big_trend or "SIDE").upper()
    cur = (current_trend or "SIDE").upper()
    if big != "DOWN":
        return (True, f"x4={big} 非下行，不启用BIAS硬拦截")

    bias25 = _compute_bias25_pct(bars)
    if bias25 is None:
        return (True, "BIAS25数据不足，默认放行")

    th = BIAS25_THRESHOLD_STOCK
    if bias25 <= th:
        return (True, f"BIAS25={bias25:.2f}%<=阈值{th:.1f}% 允许逆势BUY (x4={big}, cur={cur})")

    return (False, f"BIAS25过滤: {bias25:.2f}%>阈值{th:.1f}%，x4={big}下行中禁止抄底BUY")


def check_position_control(position: int, action: str,
                           big_trend: str, current_trend: str,
                           signal_source: str = "plugin",
                           current_price: float = None,
                           ema10: float = None,
                           bars: list = None,
                           confidence: float = None) -> tuple:
    """
    v21.31: Position Control - 立体仓位控制 (v21.21起取消K线合并要求)

    核心原则: 先查仓位数 → 再定买卖条件 (避免来回打脸)

    BUY转换 (5次):
    - 0→1: 需前一根阳线 (P0信号直通)
    - 1→2: 需价格>EMA5 (突破实体高为加分项)
    - 2→3: 需价格>EMA10 (创新高为加分项)
    - 3→4: 需价格>EMA10 (创新高为加分项)
    - 4→5: 需cur=UP + 价格>EMA10

    SELL转换 - 严格逐级减仓(每次只减1档):
    - 急跌保护: 当前K线跌>5% → 减1档(跳过条件)
    - 仓位5 一卖: 前1根阴 → 4档
    - 仓位4 二卖: <EMA5 (跌破实体低为加分项) → 3档
    - 仓位3 三卖: <EMA10 (创新低为加分项) → 2档
    - 仓位2 四卖: <EMA10 (创新低为加分项) → 1档
    - 仓位1 清仓: 价格<EMA10 → 0档 (v21.32取消cur=DOWN限制)

    Args:
        position: 当前实际仓位 (0-5), 每次调用获取最新值
        action: "BUY" 或 "SELL"
        big_trend: x4大周期趋势 "UP"/"DOWN"/"SIDE"
        current_trend: 当前周期趋势 "UP"/"DOWN"/"SIDE"
        signal_source: 信号来源，含"P0"或"移动"视为P0系列
        current_price: 当前价格 (EMA检查用)
        ema10: 10日EMA值 (EMA检查用)
        bars: K线数据列表 (用于K线检查和EMA计算)

    Returns:
        (allowed: bool, reason: str, target_position: int)
        - allowed: 是否允许交易
        - reason: 原因说明
        - target_position: 目标仓位 (严格逐级,每次±1档)
    """
    action_upper = action.upper() if action else "BUY"
    big = (big_trend or "SIDE").upper()
    current = (current_trend or "SIDE").upper()

    # v20.4: 构建Position Control状态摘要
    def get_restriction_info():
        """获取当前仓位的限制信息 (v21.31规则-严格逐级+EMA过滤)"""
        if position <= 0:
            return "空仓: BUY需阳线(P0直通) | SELL禁止"
        elif position == 1:
            return "仓位1: BUY需>EMA5 | SELL需<EMA10→0档"
        elif position == 2:
            return "仓位2: BUY需>EMA10 | SELL需<EMA10→1档"
        elif position == 3:
            return "仓位3: BUY需>EMA10 | SELL需<EMA10→2档"
        elif position == 4:
            return "仓位4: BUY需>EMA10 | SELL需<EMA5→3档"
        elif position >= 5:
            return "满仓: BUY禁止 | SELL需前1根阴线→4档"
        return f"仓位{position}: 未知状态"

    restriction_info = get_restriction_info()

    # v21.10 SYS-022: 置信度门控 (Phase 1 仅记录)
    # 高档位需要高置信度: 1-2档>=0.6, 3-4档>=0.75, 4-5档>=0.85
    CONFIDENCE_GATE_ENABLED = False  # Phase 1
    if confidence is not None and action_upper == "BUY":
        _target = position + 1
        _conf_required = 0.60 if _target <= 2 else (0.75 if _target <= 4 else 0.85)
        _conf_pass = confidence >= _conf_required
        if CONFIDENCE_GATE_ENABLED and not _conf_pass:
            return (False, f"[v21.10] 置信度门控: conf={confidence:.2f}<{_conf_required} (仓位{position}→{_target})", position)
        elif not _conf_pass:
            logger.info(f"[CONFIDENCE_GATE] {position}→{_target} conf={confidence:.2f}<{_conf_required} (未启用)")

    # v21.13 SYS-022: 动态仓位边界 Bounded Tilts (Phase 1 观察)
    # 计算信号强度→连续值,记录是否满足最小调仓幅度(5%)
    BOUNDED_TILT_ENABLED = False  # Phase 1
    try:
        _bt_signals = []
        # v21.14修复: confidence为None时默认0.5(不再跳过,保证至少1个信号源)
        _bt_signals.append(confidence if confidence is not None else 0.5)
        # EMA距离: 价格偏离EMA10的百分比→信号强度
        # v21.14修复: ema10添加None保护
        if current_price and current_price > 0 and ema10 and ema10 > 0:
            _ema_dist = (current_price - ema10) / ema10
            _bt_signals.append(max(-1.0, min(1.0, _ema_dist * 10)))  # 归一化到[-1,1]
        # 趋势方向: UP=+0.5, DOWN=-0.5, SIDE=0
        _trend_score = {"UP": 0.5, "DOWN": -0.5}.get(current, 0.0)
        _bt_signals.append(_trend_score)

        if _bt_signals:
            _bt_raw = sum(_bt_signals) / len(_bt_signals)  # 平均信号强度 [-1, 1]
            # 映射到仓位建议: 0=空仓, 5=满仓
            _bt_target_raw = 2.5 + _bt_raw * 2.5  # [0, 5]
            _bt_target_raw = max(0.0, min(5.0, _bt_target_raw))
            _bt_delta = _bt_target_raw - position  # 建议调仓幅度
            _bt_min_delta = 0.5  # 最小调仓阈值(相当于10%变动)
            _bt_action = "HOLD" if abs(_bt_delta) < _bt_min_delta else ("BUY" if _bt_delta > 0 else "SELL")
            logger.info(f"[BOUNDED_TILT] pos={position} target_raw={_bt_target_raw:.2f} delta={_bt_delta:+.2f} "
                          f"→{_bt_action} | signals={[round(s,2) for s in _bt_signals]} "
                          f"regime={big} src={signal_source}")
    except Exception:
        pass

    # === BUY 逻辑 (5次转换: 0→1→2→3→4→5) ===
    if action_upper == "BUY":
        # 满仓(5)禁止买入
        if position >= 5:
            return (False, f"[v20] 仓位5/5 BUY ✗ | 满仓禁买 | {restriction_info}", position)

        # v20.6: 移动止盈直通所有仓位 (已有独立阈值+配额机制，不需PC条件限制)
        if signal_source and "移动" in signal_source:
            target = position + 1
            return (True, f"[v20.6] 仓位{position}/5 BUY ✓ | {signal_source}直通({position}→{target}) | {restriction_info}", target)

        # v21.28: BIAS25逆势过滤（仅x4下行时硬拦截）
        bias_ok, bias_reason = check_bias25_filter(
            action_upper, bars, signal_source or "",
            big_trend=big, current_trend=current,
        )
        if not bias_ok:
            return (False, f"[v21.28] 仓位{position}/5 BUY ✗ | {bias_reason} | {restriction_info}", position)

        # 0→1: 需要前一根阳线 (v20: P0系列信号绕过K线检查)
        if position == 0:
            is_p0_signal = signal_source and ("P0" in signal_source or "移动" in signal_source)
            if is_p0_signal:
                return (True, f"[v20] 仓位0/5 BUY ✓ | 0→1 P0信号直通({signal_source}) | {restriction_info}", 1)
            if bars and check_prev_bar_bullish(bars):
                return (True, f"[v20] 仓位0/5 BUY ✓ | 0→1阳线确认 | {restriction_info}", 1)
            elif not bars:
                return (False, f"[v20.4] 仓位0/5 BUY ✗ | 0→1无K线数据,拒绝 | {restriction_info}", position)
            else:
                return (False, f"[v20] 仓位0/5 BUY ✗ | 0→1需前一根阳线 | {restriction_info}", position)

        # 1→2: 需要价格>EMA5 (突破实体高为加分项)
        if position == 1:
            if bars:
                ema5 = calculate_ema5(bars)
                price_ok = current_price > ema5 if (ema5 > 0 and current_price is not None) else True
                breakout_ok, prev_high, breakout_reason = check_new_high_breakout(bars, current_price)

                if price_ok:
                    _bk = f"+{breakout_reason}" if breakout_ok else "(未突破实体高)"
                    return (True, f"[v21.31] 仓位1/5 BUY ✓ | 1→2价格{current_price:.2f}>EMA5({ema5:.2f}){_bk} | {restriction_info}", 2)
                else:
                    return (False, f"[v21.31] 仓位1/5 BUY ✗ | 1→2价格{current_price:.2f}<=EMA5({ema5:.2f}) | {restriction_info}", position)
            return (False, f"[v20.4] 仓位1/5 BUY ✗ | 1→2无K线数据,拒绝 | {restriction_info}", position)

        # 2→3: 需要价格>EMA10 (创新高为加分项)
        if position == 2:
            if bars and current_price is not None and ema10 is not None and ema10 > 0:
                price_ok = current_price > ema10
                breakout_ok, prev_high, breakout_reason = check_new_high_breakout(bars, current_price)

                if price_ok:
                    _bk = f"+{breakout_reason}" if breakout_ok else "(未创新高)"
                    return (True, f"[v21.31] 仓位2/5 BUY ✓ | 2→3价格{current_price:.2f}>EMA10({ema10:.2f}){_bk} | {restriction_info}", 3)
                else:
                    return (False, f"[v21.31] 仓位2/5 BUY ✗ | 2→3价格{current_price:.2f}<=EMA10({ema10:.2f}) | {restriction_info}", position)
            return (False, f"[v20.4] 仓位2/5 BUY ✗ | 2→3无EMA/K线数据,拒绝 | {restriction_info}", position)

        # 3→4: 价格>EMA10 (v21.31: 创新高为OR加分项)
        if position == 3:
            if bars and current_price is not None and ema10 is not None and ema10 > 0:
                price_ok = current_price > ema10
                breakout_ok, prev_high, breakout_reason = check_new_high_breakout(bars, current_price)

                if price_ok:
                    _bk = f"+{breakout_reason}" if breakout_ok else "(未创新高)"
                    return (True, f"[v21.31] 仓位3/5 BUY ✓ | 3→4价格{current_price:.2f}>EMA10({ema10:.2f}){_bk} | {restriction_info}", 4)
                else:
                    return (False, f"[v21.31] 仓位3/5 BUY ✗ | 3→4价格{current_price:.2f}<=EMA10({ema10:.2f}) | {restriction_info}", position)
            return (False, f"[v20.4] 仓位3/5 BUY ✗ | 3→4无EMA/K线数据,拒绝 | {restriction_info}", position)

        # 4→5: v21.32 仅需价格>EMA10 (取消cur=UP趋势限制)
        if position == 4:
            if current_price is not None and ema10 is not None and ema10 > 0:
                if current_price > ema10:
                    return (True, f"[v21.32] 仓位4/5 BUY ✓ | 4→5 价格{current_price:.2f}>EMA10({ema10:.2f}) | {restriction_info}", 5)
                else:
                    return (False, f"[v21.32] 仓位4/5 BUY ✗ | 4→5价格{current_price:.2f}<=EMA10({ema10:.2f}) | {restriction_info}", position)
            return (False, f"[v21.32] 仓位4/5 BUY ✗ | EMA10不可用 | {restriction_info}", position)

    # === SELL 逻辑 - v21.32 严格逐级减仓(取消所有趋势限制,仅保留EMA过滤) ===
    # 规则表:
    # 仓位5 → 一卖: 前1根阴 → 4档(逐级)
    # 仓位4 → 二卖: <EMA5 + 跌破实体低(OR加分) → 3档(逐级)
    # 仓位3 → 三卖: <EMA10 + 创新低(OR加分) → 2档(逐级)
    # 仓位2 → 四卖: <EMA10 + 创新低(OR加分) → 1档(逐级)
    # 仓位1 → 清仓: <EMA10 → 0档
    if action_upper == "SELL":
        # 空仓(0)禁止卖出
        if position <= 0:
            return (False, f"[v20] 仓位0/5 SELL ✗ | 空仓禁卖 | {restriction_info}", position)

        # v20.5: 急跌保护 - 当前K线跌幅>5%时放宽条件(仅需阴线即可卖)
        crash_mode = False
        if bars and len(bars) >= 1 and current_price is not None:
            bar_open = bars[-1].get("open", 0)
            if bar_open > 0 and current_price < bar_open:
                drop_pct = (bar_open - current_price) / bar_open * 100
                if drop_pct >= CRASH_SELL_THRESHOLD_PCT:
                    crash_mode = True

        if crash_mode:
            target = max(position - 1, 0)
            return (True, f"[v20.5] 仓位{position}/5 SELL ✓ | 急跌保护(当前K线跌{drop_pct:.1f}%≥{CRASH_SELL_THRESHOLD_PCT}%)→{target}档 | {restriction_info}", target)

        # v20.6: 移动止损直通所有仓位 (已有独立阈值+配额机制，不需PC条件限制)
        if signal_source and "移动" in signal_source:
            target = max(position - 1, 0)
            return (True, f"[v20.6] 仓位{position}/5 SELL ✓ | {signal_source}直通({position}→{target}) | {restriction_info}", target)

        # 计算EMA5用于判断
        ema5 = calculate_ema5(bars) if bars else 0.0

        # 仓位5: 一卖 - 前1根阴 → 减1档(5→4)，逐级对称
        if position >= 5:
            if bars and check_prev_bar_bearish(bars):
                return (True, f"[v20] 仓位5/5 SELL ✓ | 一卖(前1根阴)→4档(逐级) | {restriction_info}", 4)
            return (False, f"[v20] 仓位5/5 SELL ✗ | 一卖需前1根阴线 | {restriction_info}", position)

        # 仓位4: 二卖 - <EMA5 (v21.31: 跌破实体低为OR加分项) → 3档(逐级)
        if position == 4:
            if ema5 > 0 and current_price is not None and current_price < ema5:
                breakdown_ok, prev_low, breakdown_reason = check_new_low_breakdown(bars, current_price)
                _bd = f"+{breakdown_reason}" if breakdown_ok else "(未跌破实体低)"
                resonance = "共振" if (big == "DOWN" and current == "DOWN") else "无共振"
                return (True, f"[v21.31] 仓位4/5 SELL ✓ | 二卖(<EMA5{_bd}+{resonance})→3档(逐级) | {restriction_info}", 3)
            return (False, f"[v21.31] 仓位4/5 SELL ✗ | 二卖需<EMA5({ema5:.2f}) | {restriction_info}", position)

        # 仓位3: 三卖 - <EMA10 (v21.31: 创新低为OR加分项) → 2档(逐级)
        if position == 3:
            if ema10 is not None and ema10 > 0 and current_price is not None and current_price < ema10:
                breakdown_ok, prev_low, breakdown_reason = check_new_low_breakdown(bars, current_price)
                _bd = f"+{breakdown_reason}" if breakdown_ok else "(未创新低)"
                resonance = "共振" if (big == "DOWN" and current == "DOWN") else "无共振"
                return (True, f"[v21.31] 仓位3/5 SELL ✓ | 三卖(<EMA10{_bd}+{resonance})→2档(逐级) | {restriction_info}", 2)
            _ema_s = f"{ema10:.2f}" if ema10 is not None else "N/A"
            return (False, f"[v21.31] 仓位3/5 SELL ✗ | 三卖需<EMA10({_ema_s}) | {restriction_info}", position)

        # 仓位2: 四卖 - <EMA10 (v21.31: 创新低为OR加分项) → 1档(逐级)
        if position == 2:
            if ema10 is not None and ema10 > 0 and current_price is not None and current_price < ema10:
                breakdown_ok, prev_low, breakdown_reason = check_new_low_breakdown(bars, current_price)
                _bd = f"+{breakdown_reason}" if breakdown_ok else "(未创新低)"
                resonance = "共振" if (big == "DOWN" and current == "DOWN") else "无共振"
                return (True, f"[v21.31] 仓位2/5 SELL ✓ | 四卖(<EMA10{_bd}+{resonance})→1档(逐级) | {restriction_info}", 1)
            _ema_s = f"{ema10:.2f}" if ema10 is not None else "N/A"
            return (False, f"[v21.31] 仓位2/5 SELL ✗ | 四卖需<EMA10({_ema_s}) | {restriction_info}", position)

        # 仓位1: 清仓 - v21.32 仅需价格<EMA10 (取消cur=DOWN趋势限制)
        if position == 1:
            if current_price is not None and ema10 is not None and ema10 > 0:
                if current_price < ema10:
                    return (True, f"[v21.32] 仓位1/5 SELL ✓ | 清仓 价格{current_price:.2f}<EMA10({ema10:.2f})→0档 | {restriction_info}", 0)
                else:
                    return (False, f"[v21.32] 仓位1/5 SELL ✗ | 价格{current_price:.2f}>=EMA10({ema10:.2f}) | {restriction_info}", position)
            return (False, f"[v21.32] 仓位1/5 SELL ✗ | EMA10不可用 | {restriction_info}", position)

        # 没有触发任何卖出条件
        return (False, f"[v20] 仓位{position}/5 SELL ✗ | 未触发卖出条件 | {restriction_info}", position)

    # 其他情况（理论上不会到达）
    return (True, f"[v20] 仓位{position}/5 {action_upper} ✓ | {restriction_info}", position + 1 if action_upper == "BUY" else position - 1)


def log_signal_decision(symbol: str, action: str, position: int,
                        allowed: bool, reason: str, target_pos: int,
                        signal_source: str, price: float,
                        big_trend: str, current_trend: str):
    """
    v20: 结构化记录Position Control决策到JSONL文件
    用于trade_retrospective.py回溯分析
    """
    try:
        entry = {
            "ts": datetime.now().isoformat(),
            "symbol": symbol,
            "action": action,
            "position": position,
            "allowed": allowed,
            "target_pos": target_pos,
            "reason": reason,
            "signal_source": signal_source,
            "price": price,
            "big_trend": big_trend,
            "current_trend": current_trend,
        }
        os.makedirs("logs", exist_ok=True)
        with open("logs/signal_decisions.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass  # 记录失败不影响交易逻辑


def optimal_exit_scheduler(current_pos: int, target_pos: int,
                           bars: list = None, current_price: float = None,
                           atr: float = None, symbol: str = "") -> dict:
    """
    v21.22 SYS-032: 分批退出调度器 (Phase1: 仅观察)

    根据流动性评分和ATR，计算最优退出步长。
    避免高波动低流动性时一次性清仓造成滑点。

    流动性评分 = (1 / DC宽度%) × 相对成交量
    - 高流动性 + 低ATR → 可多档同时退出
    - 低流动性 + 高ATR → 每次只退1档(当前行为)

    Args:
        current_pos: 当前仓位 (0-5)
        target_pos:  期望目标仓位 (通常0或1)
        bars:        K线数据 (用于计算DC宽度和成交量)
        current_price: 当前价格
        atr:         ATR值
        symbol:      品种名

    Returns:
        {"recommended_target": int, "step": int,
         "liquidity": float, "atr_pct": float, "reason": str}
    """
    need_to_exit = current_pos - target_pos
    if need_to_exit <= 0:
        return {"recommended_target": target_pos, "step": 0,
                "liquidity": 0.0, "atr_pct": 0.0, "reason": "无需退出"}

    # 默认: 每次退1档 (当前行为)
    recommended_step = 1
    liquidity_score = 1.0
    atr_pct = 0.0
    reason = "默认逐级(1档)"

    if bars and len(bars) >= 20 and current_price and current_price > 0:
        try:
            _highs = [b["high"] for b in bars[-20:]]
            _lows  = [b["low"]  for b in bars[-20:]]
            dc_upper, dc_lower = max(_highs), min(_lows)
            dc_width_pct = (dc_upper - dc_lower) / current_price if current_price > 0 else 0.10

            # 相对成交量 (最近1根 / 近20根均量)
            _vols = [b.get("volume", 0) for b in bars[-20:]]
            _avg_vol = sum(_vols[:-1]) / max(len(_vols) - 1, 1) if len(_vols) > 1 else 1
            _last_vol = _vols[-1] if _vols else _avg_vol
            rel_vol = _last_vol / _avg_vol if _avg_vol > 0 else 1.0

            liquidity_score = (1.0 / max(dc_width_pct, 0.005)) * rel_vol

            if atr and current_price > 0:
                atr_pct = atr / current_price

            # 退出步长决策
            # 高流动性(>15) + 低ATR(<1.5%) → 可2档
            # 超高流动性(>25) + 超低ATR(<0.8%) → 可3档
            if liquidity_score > 25 and atr_pct < 0.008 and need_to_exit >= 3:
                recommended_step = 3
                reason = f"高流动性({liquidity_score:.1f}) + 低ATR({atr_pct:.1%}) → 3档"
            elif liquidity_score > 15 and atr_pct < 0.015 and need_to_exit >= 2:
                recommended_step = 2
                reason = f"较高流动性({liquidity_score:.1f}) + 低ATR({atr_pct:.1%}) → 2档"
            else:
                reason = f"流动性({liquidity_score:.1f}) ATR({atr_pct:.1%}) → 逐级1档"
        except Exception:
            pass

    recommended_target = max(target_pos, current_pos - recommended_step)

    return {
        "recommended_target": recommended_target,
        "step": recommended_step,
        "liquidity": round(liquidity_score, 2),
        "atr_pct": round(atr_pct, 4),
        "reason": reason,
    }


def update_plugin_daily_state(state: dict, action: str, trend: str = None, market_type: str = "crypto") -> str:
    """
    v3.546: 更新外挂每日状态
    v17.5: 简化为统一逻辑（美股/加密货币一致）
           - 1买+1卖完成后冻结至次日NY 8AM
           - 方向过滤由外层check_x4_trend_filter()处理

    Args:
        state: 外挂状态字典
        action: "BUY" 或 "SELL"
        trend: (已废弃，保留兼容)
        market_type: (已废弃，保留兼容)

    Returns:
        状态描述字符串
    """
    today = get_today_date_ny()
    state["reset_date"] = today

    if action == "BUY":
        state["buy_used"] = True
        state["last_buy_time"] = datetime.now().isoformat()
    elif action == "SELL":
        state["sell_used"] = True
        state["last_sell_time"] = datetime.now().isoformat()

    # v17.5: 统一冻结逻辑 - 1买+1卖完成后冻结
    if state.get("buy_used") and state.get("sell_used"):
        freeze_until = get_next_8am_ny()
        state["freeze_until"] = freeze_until.isoformat()
        return f"1买+1卖完成，冻结至 {freeze_until.strftime('%m-%d %H:%M')} NY"
    else:
        buy_status = "✓" if state.get("buy_used") else "○"
        sell_status = "✓" if state.get("sell_used") else "○"
        return f"买[{buy_status}] 卖[{sell_status}]"


def is_us_stock(symbol: str) -> bool:
    """
    v8.3: 判断是否是美股品种
    """
    crypto_symbols = ["BTC-USD", "ETH-USD", "SOL-USD", "ZEC-USD",
                      "BTCUSDC", "ETHUSDC", "SOLUSDC", "ZECUSDC"]
    return symbol not in crypto_symbols


def get_us_market_open_time_today() -> Optional[datetime]:
    """
    v8.3: 获取今天美股开盘时间 (纽约时间 09:30)
    如果今天不是交易日，返回None
    """
    ny_now = get_ny_now()

    # 周末不是交易日
    if ny_now.weekday() >= 5:
        return None

    return ny_now.replace(hour=9, minute=30, second=0, microsecond=0)


def is_frozen_until(freeze_until: str) -> bool:
    """
    v8.0: 检查是否仍在冻结期
    """
    if not freeze_until:
        return False

    try:
        freeze_dt = datetime.fromisoformat(freeze_until)
        # 确保时区一致
        if freeze_dt.tzinfo is None:
            freeze_dt = NY_TZ.localize(freeze_dt)

        ny_now = get_ny_now()
        return ny_now < freeze_dt
    except Exception as e:
        logger.warning(f"解析冻结时间失败: {e}")
        return False


def is_us_market_open() -> bool:
    """检查美股市场是否开盘"""
    ny_now = get_ny_now()
    weekday = ny_now.weekday()

    if weekday >= 5:  # 周六日
        return False

    hour = ny_now.hour
    minute = ny_now.minute

    # 9:30 - 16:00 纽约时间
    if hour < 9 or (hour == 9 and minute < 30):
        return False
    if hour >= 16:
        return False

    return True


def is_us_market_open_window() -> bool:
    """
    v11.2: 检查是否在美股开盘窗口内 (9:30-9:35 NY)
    用于检测新交易日开盘时刻
    """
    ny_now = get_ny_now()
    weekday = ny_now.weekday()

    if weekday >= 5:  # 周六日
        return False

    hour = ny_now.hour
    minute = ny_now.minute

    # 9:30-9:35 纽约时间 = 开盘窗口
    if hour == 9 and 30 <= minute <= 35:
        return True

    return False


def get_us_market_open_cooldown_end() -> datetime:
    """
    v11.2: 获取开盘缓冲期结束时间 (9:40 NY)
    在开盘后10分钟内不触发信号，让价格稳定
    """
    ny_now = get_ny_now()
    return ny_now.replace(hour=9, minute=40, second=0, microsecond=0)


def get_today_trading_date() -> str:
    """
    v11.2: 获取今天的交易日期字符串 (YYYY-MM-DD)
    用于检测是否是新交易日
    """
    ny_now = get_ny_now()
    return ny_now.strftime("%Y-%m-%d")


def safe_json_read(filepath: str, max_retries: int = 3) -> Optional[Dict]:
    """
    安全读取JSON文件（带重试机制）

    v3.230修复: 解决Windows文件锁定问题(WinError 32)
    """
    import time

    if not os.path.exists(filepath):
        return None

    for attempt in range(max_retries):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except PermissionError as e:
            # WinError 32: 文件被其他进程占用
            if attempt < max_retries - 1:
                wait_time = 0.05 * (2 ** attempt)  # 指数退避: 0.05s, 0.1s, 0.2s
                time.sleep(wait_time)
            else:
                logger.warning(f"读取 {filepath} 失败(重试{max_retries}次): {e}")
                return None
        except Exception as e:
            logger.warning(f"读取 {filepath} 失败: {e}")
            return None

    return None


def safe_json_write(filepath: str, data: Dict, max_retries: int = 3) -> bool:
    """
    安全写入JSON文件（原子操作 + 重试机制）

    v3.230修复: 解决Windows文件锁定问题(WinError 32)
    - 使用os.replace()替代os.remove()+os.rename()
    - 添加指数退避重试机制
    - 使用唯一临时文件名避免冲突
    """
    import uuid
    import time

    # 使用唯一临时文件名避免多进程冲突
    temp_file = f"{filepath}.{uuid.uuid4().hex[:8]}.tmp"

    for attempt in range(max_retries):
        try:
            # 写入临时文件
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)

            # 原子替换 (os.replace在Windows上也是原子操作)
            os.replace(temp_file, filepath)
            return True

        except PermissionError as e:
            # WinError 32: 文件被其他进程占用
            if attempt < max_retries - 1:
                wait_time = 0.1 * (2 ** attempt)  # 指数退避: 0.1s, 0.2s, 0.4s
                logger.warning(f"写入 {filepath} 被锁定，{wait_time:.1f}秒后重试 ({attempt+1}/{max_retries})")
                time.sleep(wait_time)
            else:
                logger.error(f"写入 {filepath} 失败(重试{max_retries}次): {e}")
                # 清理临时文件
                try:
                    if os.path.exists(temp_file):
                        os.remove(temp_file)
                except Exception:  # v16 P2-2
                    pass
                return False

        except Exception as e:
            logger.error(f"写入 {filepath} 失败: {e}")
            # 清理临时文件
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            except Exception:  # v16 P2-2
                pass
            return False

    return False


# ============================================================
# 邮件通知
# ============================================================

class EmailNotifier:
    """邮件通知器"""

    def __init__(self, config: Dict):
        self.enabled = config.get("enabled", False)
        self.smtp_server = config.get("smtp_server", "smtp.gmail.com")
        self.smtp_port = config.get("smtp_port", 587)
        self.sender_email = config.get("sender_email", "")
        self.sender_password = config.get("sender_password", "")
        self.receiver_email = config.get("receiver_email", "")

    def send_signal_notification(self, symbol: str, signal_data: Dict) -> bool:
        """发送交易信号通知邮件 - v11.0: 支持L1/飞云外挂状态显示"""
        if not self.enabled:
            return False

        if not all([self.sender_email, self.sender_password, self.receiver_email]):
            logger.warning("邮件配置不完整，跳过发送")
            return False

        try:
            signal = signal_data.get("signal", "UNKNOWN")
            price = signal_data.get("price", 0)
            base_price = signal_data.get("base_price", 0)
            change_pct = signal_data.get("change_pct", 0)
            asset_type = signal_data.get("type", "unknown")
            timeframe = signal_data.get("timeframe", "1h")
            timestamp = signal_data.get("timestamp", datetime.now().isoformat())
            signal_type = signal_data.get("signal_type", "P0-Open")

            # v11.0: 外挂激活状态
            activate_l1 = signal_data.get("activate_l1_plugin", False)
            activate_feiyun = signal_data.get("activate_feiyun_plugin", False)
            activate_scalping = signal_data.get("activate_scalping_plugin", False)  # v12.0
            activate_supertrend = signal_data.get("activate_supertrend_plugin", False)  # v3.530
            l1_direction = signal_data.get("l1_trend_direction", "")
            feiyun_signal = signal_data.get("feiyun_signal", "")

            # v21: 构造外挂标签
            activate_double_pattern = signal_data.get("activate_double_pattern_plugin", False)
            activate_chan_bs = signal_data.get("activate_chan_bs_plugin", False)
            activate_macd = signal_data.get("activate_macd_divergence_plugin", False)

            plugin_tags = []
            if activate_supertrend:
                plugin_tags.append("SuperTrend")
            if activate_double_pattern:
                plugin_tags.append("Vision形态")
            if activate_chan_bs:
                plugin_tags.append("缠论BS")
            if activate_macd:
                plugin_tags.append("MACD背离")
            if activate_l1:
                plugin_tags.append("L1外挂")
            if activate_feiyun:
                plugin_tags.append("飞云外挂")
            if activate_scalping:
                plugin_tags.append("剥头皮")
            plugin_status = "+".join(plugin_tags) if plugin_tags else "仅P0"

            # 构造邮件主题 - v12.2修复: 根据服务器实际执行结果判断
            emoji = "🟢" if signal == "BUY" else "🔴"
            # v12.2: 优先使用服务器响应的执行状态
            server_executed = signal_data.get("server_executed")
            server_reason = signal_data.get("server_reason", "")

            # v17.4: 仓位控制信息
            position_units = signal_data.get("position_units", -1)  # -1表示未提供
            position_control_rule = signal_data.get("position_control_rule", "")

            if server_executed is True:
                # 服务器确认已执行
                plugin_emoji = "✅"
                exec_status = "已执行"
            elif server_executed is False:
                # 服务器拒绝执行
                plugin_emoji = "🚫"
                exec_status = "被拒绝"
            elif plugin_tags:
                # 兼容旧逻辑: 有外挂激活但未收到服务器响应
                plugin_emoji = "⏳"
                exec_status = "已发送"
            else:
                # 无外挂 = 仅提醒
                plugin_emoji = "⚠️"
                exec_status = "仅提醒"
            subject = f"{emoji}{plugin_emoji} {signal_type} {exec_status} | {symbol} {signal} | {change_pct:+.2f}%"

            # 根据信号类型构造不同的邮件内容
            if signal_type == "移动止损":
                base_label = "追踪最高价"
                type_desc = "移动止损(ATR动态)"
            elif signal_type == "移动止盈":
                base_label = "追踪最低价"
                type_desc = "移动止盈(ATR动态)"
            elif signal_type == "P0-Tracking":
                base_label = "基准价(peak/trough)"
                type_desc = "追踪止损" if signal == "SELL" else "追涨买入"
            elif signal_type == "Chandelier+ZLSMA":
                base_label = "ZLSMA基准价"
                type_desc = "5分钟剥头皮"
            elif signal_type == "SuperTrend":
                base_label = "当前价格"
                type_desc = "SuperTrend+QQE+MACD三共振"
            else:
                base_label = "周期开盘价"
                type_desc = "价差触发"

            # v12.2修复: 外挂状态行HTML - 根据服务器实际执行结果显示
            plugin_row_html = ""

            # v21: 构建外挂详情
            plugin_details = []
            if activate_supertrend:
                st_trend = signal_data.get("supertrend_trend", 0)
                st_zone = "红区" if st_trend == -1 else "绿区"
                plugin_mode = signal_data.get("plugin_mode", "")
                indicator_signal = signal_data.get("indicator_signal", "")
                plugin_details.append(f"SuperTrend({indicator_signal},ST={st_zone},{plugin_mode})")
            if activate_double_pattern:
                pattern = signal_data.get("pattern", "NONE")
                plugin_details.append(f"Vision形态({pattern})")
            if activate_chan_bs:
                bs_type = signal_data.get("bs_type", "NONE")
                plugin_details.append(f"缠论BS({bs_type})")
            if activate_macd:
                div_type = signal_data.get("div_type", "NONE")
                plugin_details.append(f"MACD背离({div_type})")
            if activate_l1:
                direction_text = "UP趋势" if l1_direction == "BUY_ONLY" else "DOWN趋势"
                plugin_details.append(f"L1外挂({direction_text})")
            if activate_feiyun:
                plugin_details.append(f"飞云外挂({feiyun_signal})")
            if activate_scalping:
                ce_direction = signal_data.get("ce_direction", "")
                current_trend = signal_data.get("current_trend", "")
                plugin_details.append(f"剥头皮(CE={ce_direction},L1={current_trend})")

            if server_executed is True:
                # 服务器确认已执行
                plugin_row_html = f"""
                    <tr style="background-color: #d4edda;">
                        <td style="padding: 10px; border: 1px solid #dee2e6;"><strong>✅ 执行状态</strong></td>
                        <td style="padding: 10px; border: 1px solid #dee2e6; color: #155724; font-weight: bold;">
                            已执行
                        </td>
                    </tr>
                    <tr style="background-color: #fff3cd;">
                        <td style="padding: 10px; border: 1px solid #dee2e6;"><strong>⚡外挂激活</strong></td>
                        <td style="padding: 10px; border: 1px solid #dee2e6; color: #856404; font-weight: bold;">
                            {' + '.join(plugin_details) if plugin_details else '无'}
                        </td>
                    </tr>"""
            elif server_executed is False:
                # 服务器拒绝执行
                plugin_row_html = f"""
                    <tr style="background-color: #f8d7da;">
                        <td style="padding: 10px; border: 1px solid #dee2e6;"><strong>🚫 执行状态</strong></td>
                        <td style="padding: 10px; border: 1px solid #dee2e6; color: #721c24; font-weight: bold;">
                            被服务器拒绝
                        </td>
                    </tr>
                    <tr style="background-color: #f8f9fa;">
                        <td style="padding: 10px; border: 1px solid #dee2e6;"><strong>拒绝原因</strong></td>
                        <td style="padding: 10px; border: 1px solid #dee2e6; color: #6c757d;">
                            {server_reason}
                        </td>
                    </tr>
                    <tr style="background-color: #fff3cd;">
                        <td style="padding: 10px; border: 1px solid #dee2e6;"><strong>⚡外挂激活</strong></td>
                        <td style="padding: 10px; border: 1px solid #dee2e6; color: #856404;">
                            {' + '.join(plugin_details) if plugin_details else '无'}
                        </td>
                    </tr>"""
            elif plugin_details:
                # 有外挂但未收到服务器响应
                plugin_row_html = f"""
                    <tr style="background-color: #fff3cd;">
                        <td style="padding: 10px; border: 1px solid #dee2e6;"><strong>⚡外挂激活</strong></td>
                        <td style="padding: 10px; border: 1px solid #dee2e6; color: #856404; font-weight: bold;">
                            {' + '.join(plugin_details)}
                        </td>
                    </tr>"""
            else:
                # 无外挂激活 = 仅提醒
                plugin_row_html = f"""
                    <tr style="background-color: #fff3cd;">
                        <td style="padding: 10px; border: 1px solid #dee2e6;"><strong>⚠️ 执行状态</strong></td>
                        <td style="padding: 10px; border: 1px solid #dee2e6; color: #856404; font-weight: bold;">
                            未执行 - 仅作为观察提醒
                        </td>
                    </tr>
                    <tr style="background-color: #f8f9fa;">
                        <td style="padding: 10px; border: 1px solid #dee2e6;"><strong>未执行原因</strong></td>
                        <td style="padding: 10px; border: 1px solid #dee2e6; color: #6c757d;">
                            当前为震荡/无趋势状态，L1外挂未激活
                        </td>
                    </tr>
                    <tr style="background-color: #e7f3ff;">
                        <td style="padding: 10px; border: 1px solid #dee2e6;"><strong>💡 建议</strong></td>
                        <td style="padding: 10px; border: 1px solid #dee2e6; color: #0056b3;">
                            可手动设置偏向后执行: python set_bias.py {symbol}=DOWN
                        </td>
                    </tr>"""

            # v3.530: SuperTrend指标详情行
            supertrend_row_html = ""
            if activate_supertrend:
                st_trend = signal_data.get("supertrend_trend", 0)
                st_zone = "红区" if st_trend == -1 else "绿区"
                st_zone_color = "#dc3545" if st_trend == -1 else "#28a745"
                qqe_hist = signal_data.get("qqe_hist", 0)
                qqe_color = "#28a745" if qqe_hist > 0 else "#dc3545"
                qqe_label = "蓝(看多)" if qqe_hist > 0 else "红(看空)"
                macd_hist = signal_data.get("macd_hist", 0)
                macd_color = "#28a745" if macd_hist > 0 else "#dc3545"
                macd_label = "蓝(看多)" if macd_hist > 0 else "红(看空)"
                indicator_signal = signal_data.get("indicator_signal", "NONE")

                supertrend_row_html = f"""
                    <tr style="background-color: #e7f3ff;">
                        <td style="padding: 10px; border: 1px solid #dee2e6;"><strong>📊 SuperTrend</strong></td>
                        <td style="padding: 10px; border: 1px solid #dee2e6; color: {st_zone_color}; font-weight: bold;">
                            {st_zone} (trend={st_trend})
                        </td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border: 1px solid #dee2e6;"><strong>📈 QQE</strong></td>
                        <td style="padding: 10px; border: 1px solid #dee2e6; color: {qqe_color};">
                            {qqe_hist:+.2f} {qqe_label}
                        </td>
                    </tr>
                    <tr style="background-color: #f8f9fa;">
                        <td style="padding: 10px; border: 1px solid #dee2e6;"><strong>📉 MACD</strong></td>
                        <td style="padding: 10px; border: 1px solid #dee2e6; color: {macd_color};">
                            {macd_hist:+.4f} {macd_label}
                        </td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border: 1px solid #dee2e6;"><strong>🎯 指标信号</strong></td>
                        <td style="padding: 10px; border: 1px solid #dee2e6; font-weight: bold;">
                            {indicator_signal}
                        </td>
                    </tr>"""

            # v17.4: 仓位控制信息行
            position_row_html = ""
            position_valid_range = signal_data.get("position_valid_range", "")
            if position_units >= 0:
                position_color = "#17a2b8"  # 蓝色
                # v20.2: 仓位区间限制显示
                range_row = ""
                if position_valid_range:
                    range_row = f"""
                    <tr style="background-color: #f0fff4;">
                        <td style="padding: 10px; border: 1px solid #dee2e6;"><strong>🎯 激活区间</strong></td>
                        <td style="padding: 10px; border: 1px solid #dee2e6; color: #28a745; font-weight: bold;">
                            {position_valid_range}
                        </td>
                    </tr>"""
                position_row_html = f"""
                    <tr style="background-color: #e7f3ff;">
                        <td style="padding: 10px; border: 1px solid #dee2e6;"><strong>📊 当前仓位</strong></td>
                        <td style="padding: 10px; border: 1px solid #dee2e6; color: {position_color}; font-weight: bold;">
                            {position_units}/5
                        </td>
                    </tr>{range_row}
                    <tr>
                        <td style="padding: 10px; border: 1px solid #dee2e6;"><strong>📋 仓位规则</strong></td>
                        <td style="padding: 10px; border: 1px solid #dee2e6; color: #6c757d;">
                            {position_control_rule}
                        </td>
                    </tr>"""

            # v20.1: K线冻结状态行
            bar_freeze_row_html = ""
            bar_freeze_info = signal_data.get("bar_freeze_info", "")
            if bar_freeze_info:
                bar_freeze_row_html = f"""
                    <tr style="background-color: #fff3cd;">
                        <td style="padding: 10px; border: 1px solid #dee2e6;"><strong>🔒 K线冻结</strong></td>
                        <td style="padding: 10px; border: 1px solid #dee2e6; color: #856404;">
                            {bar_freeze_info}
                        </td>
                    </tr>"""

            # v20.4: 突破/跌破确认状态行
            breakout_row_html = ""
            breakout_info = signal_data.get("breakout_info", "")
            if breakout_info:
                # 根据是否通过显示不同颜色
                if "✓" in breakout_info or "突破" in breakout_info or "跌破" in breakout_info:
                    bg_color = "#d4edda"  # 绿色背景
                    text_color = "#155724"
                    icon = "✅"
                else:
                    bg_color = "#f8d7da"  # 红色背景
                    text_color = "#721c24"
                    icon = "⏳"
                breakout_row_html = f"""
                    <tr style="background-color: {bg_color};">
                        <td style="padding: 10px; border: 1px solid #dee2e6;"><strong>{icon} 突破确认</strong></td>
                        <td style="padding: 10px; border: 1px solid #dee2e6; color: {text_color};">
                            {breakout_info}
                        </td>
                    </tr>"""

            # v20.6: 阈值信息行 (仅移动止盈/止损信号显示)
            atr_row_html = ""
            if signal_type in ("移动止损", "移动止盈"):
                _atr_val = signal_data.get("atr_value", 0)
                _atr_mult = signal_data.get("atr_multiplier", 0)
                _atr_asset = signal_data.get("atr_asset_type", "")
                _atr_regime = signal_data.get("atr_regime", "")
                _atr_pct = signal_data.get("atr_threshold_pct", 0)
                _th_type = signal_data.get("threshold_type", "ATR")
                if _th_type == "ATR" and _atr_val > 0:
                    atr_row_html = f"""
                    <tr style="background-color: #e7f3ff;">
                        <td style="padding: 10px; border: 1px solid #dee2e6;"><strong>ATR阈值</strong></td>
                        <td style="padding: 10px; border: 1px solid #dee2e6;">
                            ${_atr_val:,.2f} x {_atr_mult} = 阈值 {_atr_pct:.2f}% ({_atr_asset}/{_atr_regime})
                        </td>
                    </tr>"""
                elif _th_type == "固定":
                    _ref_atr = f" (参考ATR=${_atr_val:,.2f})" if _atr_val > 0 else ""
                    atr_row_html = f"""
                    <tr style="background-color: #fff3cd;">
                        <td style="padding: 10px; border: 1px solid #dee2e6;"><strong>固定阈值</strong></td>
                        <td style="padding: 10px; border: 1px solid #dee2e6;">
                            {_atr_pct:.1f}%{_ref_atr}
                        </td>
                    </tr>"""

            html_body = f"""
            <html>
            <body style="font-family: Arial, sans-serif; padding: 20px;">
                <h2 style="color: {'#28a745' if signal == 'BUY' else '#dc3545'};">
                    {emoji} {signal_type} 交易信号触发
                </h2>
                <p style="font-size: 14px; color: #666;">
                    触发类型: <strong>{type_desc}</strong>
                </p>
                <table style="border-collapse: collapse; width: 100%; max-width: 500px;">
                    <tr style="background-color: #f8f9fa;">
                        <td style="padding: 10px; border: 1px solid #dee2e6;"><strong>品种</strong></td>
                        <td style="padding: 10px; border: 1px solid #dee2e6;">{symbol}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border: 1px solid #dee2e6;"><strong>信号</strong></td>
                        <td style="padding: 10px; border: 1px solid #dee2e6; color: {'#28a745' if signal == 'BUY' else '#dc3545'}; font-weight: bold;">
                            {signal}
                        </td>
                    </tr>{plugin_row_html}{position_row_html}{bar_freeze_row_html}{breakout_row_html}{atr_row_html}
                    <tr style="background-color: #f8f9fa;">
                        <td style="padding: 10px; border: 1px solid #dee2e6;"><strong>类型</strong></td>
                        <td style="padding: 10px; border: 1px solid #dee2e6;">
                            {'加密货币' if asset_type == 'crypto' else '美股'}
                        </td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border: 1px solid #dee2e6;"><strong>{base_label}</strong></td>
                        <td style="padding: 10px; border: 1px solid #dee2e6;">${base_price:,.2f}</td>
                    </tr>
                    <tr style="background-color: #f8f9fa;">
                        <td style="padding: 10px; border: 1px solid #dee2e6;"><strong>当前价</strong></td>
                        <td style="padding: 10px; border: 1px solid #dee2e6;">${price:,.2f}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border: 1px solid #dee2e6;"><strong>涨跌幅</strong></td>
                        <td style="padding: 10px; border: 1px solid #dee2e6; color: {'#28a745' if change_pct > 0 else '#dc3545'};">
                            {change_pct:+.2f}%
                        </td>
                    </tr>{supertrend_row_html}
                    <tr style="background-color: #f8f9fa;">
                        <td style="padding: 10px; border: 1px solid #dee2e6;"><strong>触发时间</strong></td>
                        <td style="padding: 10px; border: 1px solid #dee2e6;">{timestamp}</td>
                    </tr>
                </table>
                <p style="margin-top: 20px; color: #6c757d; font-size: 12px;">
                    此邮件由 AI Trading System Price Scan Engine v20.6 自动发送
                </p>
            </body>
            </html>
            """

            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self.sender_email
            msg["To"] = self.receiver_email
            msg.attach(MIMEText(html_body, "html"))

            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.sender_email, self.sender_password)
                server.sendmail(self.sender_email, self.receiver_email, msg.as_string())

            logger.info(f"[邮件] 发送成功: {symbol} {signal} ({signal_type})")
            return True

        except smtplib.SMTPAuthenticationError:
            logger.error("[邮件] 认证失败")
            return False
        except Exception as e:
            logger.error(f"[邮件] 发送失败: {e}")
            return False


# ============================================================
# 数据获取
# ============================================================

# ── v21.20: 分型过滤器 (三道闸门前置) ────────────────────────────
def check_fractal_filter(bars: list, action: str) -> tuple:
    """v21.20: 分型过滤 — BUY时最近3根完成K线无顶分型，SELL时无底分型

    顶分型: bars[-2].high > bars[-3].high AND bars[-2].high > bars[-1].high
    底分型: bars[-2].low  < bars[-3].low  AND bars[-2].low  < bars[-1].low

    逻辑:
      BUY  + 顶分型存在 → 价格刚创局部高点，可能回落 → 拦截
      SELL + 底分型存在 → 价格刚创局部低点，可能反弹 → 拦截
    """
    if not bars or len(bars) < 3:
        return True, "数据不足→放行"
    b1, b2, b3 = bars[-3], bars[-2], bars[-1]
    if action == "BUY":
        top_fractal = b2["high"] > b1["high"] and b2["high"] > b3["high"]
        if top_fractal:
            return False, f"顶分型拦截BUY: h[-2]={b2['high']:.4g} > [{b1['high']:.4g}, {b3['high']:.4g}]"
    elif action == "SELL":
        bottom_fractal = b2["low"] < b1["low"] and b2["low"] < b3["low"]
        if bottom_fractal:
            return False, f"底分型拦截SELL: l[-2]={b2['low']:.4g} < [{b1['low']:.4g}, {b3['low']:.4g}]"
    return True, "无冲突分型→放行"


# ── Coinbase Candles (加密货币第一数据源) ──────────────────────
def _coinbase_fetch_candles(symbol: str, granularity: int = 3600, limit: int = 30,
                            end_timestamp: int = 0):
    """
    从 Coinbase Advanced API 获取K线数据（加密货币第一渠道）
    失败时调用方应 fall through 到 yfinance。

    Args:
        symbol: 品种代码 (BTC-USD / BTCUSDC 均可)
        granularity: 秒数 (3600=1H, 7200=2H, 21600=6H)
        limit: K线数量 (max 300)
        end_timestamp: 自定义结束时间戳(0=当前时间), 用于分页获取
    Returns:
        list[dict] | None  —  [{open,high,low,close,volume,timestamp}, ...]  时间正序
    """
    import requests, time as _time, secrets as _secrets
    try:
        import jwt
        from cryptography.hazmat.primitives import serialization
    except ImportError:
        return None

    # Coinbase API 配置 (与 llm_server / coinbase_sync_v6 相同)
    _API_KEY = "organizations/84119b71-e971-4844-8f91-bcfe54504c66/apiKeys/7d69e6f2-88a1-45e7-b806-0821bf0f3848"
    _API_PK = "-----BEGIN EC PRIVATE KEY-----\nMHcCAQEEICBNdsz8FxLsQV/OCaDkEjkpKgBHG6GYqapzBDmrmaCnoAoGCCqGSM49\nAwEHoUQDQgAEYrjK0/oRfzzn+7LyIOrh+EX5eJ8Fzka04aENf18uVkAbqyzoGEuD\nV4+auZ+gdWHPb5UXeVIWwMQhEe+a9xp34g==\n-----END EC PRIVATE KEY-----"

    # 符号映射 → Coinbase product_id (BTC-USDC)
    _SYM_MAP = {
        "BTCUSDC": "BTC-USDC", "ETHUSDC": "ETH-USDC",
        "SOLUSDC": "SOL-USDC", "ZECUSDC": "ZEC-USDC",
        "BTC-USD": "BTC-USDC", "ETH-USD": "ETH-USDC",
        "SOL-USD": "SOL-USDC", "ZEC-USD": "ZEC-USDC",
    }
    product_id = _SYM_MAP.get(symbol, symbol.replace("USDC", "-USDC").replace("-USD", "-USDC"))

    _GRAN_MAP = {
        60: "ONE_MINUTE", 300: "FIVE_MINUTE", 900: "FIFTEEN_MINUTE",
        1800: "THIRTY_MINUTE", 3600: "ONE_HOUR", 7200: "TWO_HOUR",
        21600: "SIX_HOUR", 86400: "ONE_DAY",
    }
    gran_str = _GRAN_MAP.get(granularity, "ONE_HOUR")

    end_ts = end_timestamp if end_timestamp > 0 else int(_time.time())
    start_ts = end_ts - granularity * limit

    path = f"/api/v3/brokerage/products/{product_id}/candles"
    uri = f"GET api.coinbase.com{path}"

    try:
        pk = serialization.load_pem_private_key(_API_PK.encode(), password=None)
        token = jwt.encode(
            {"sub": _API_KEY, "iss": "cdp", "nbf": int(_time.time()),
             "exp": int(_time.time()) + 120, "uri": uri},
            pk, algorithm="ES256",
            headers={"kid": _API_KEY, "nonce": _secrets.token_hex(16)},
        )
        resp = requests.get(
            f"https://api.coinbase.com{path}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            params={"start": str(start_ts), "end": str(end_ts), "granularity": gran_str},
            timeout=15,
        )
        if resp.status_code != 200:
            logger.warning(f"[COINBASE] {symbol} HTTP {resp.status_code}")
            return None

        candles = resp.json().get("candles", [])
        bars = []
        for c in candles:
            o, h, l, cl, v = float(c.get("open", 0)), float(c.get("high", 0)), float(c.get("low", 0)), float(c.get("close", 0)), float(c.get("volume", 0))
            if cl > 0 and h > 0 and l > 0 and h >= l and not (math.isinf(cl) or math.isinf(h) or math.isinf(l)):
                bars.append({"open": o, "high": h, "low": l, "close": cl,
                             "volume": v, "timestamp": str(c.get("start", ""))})
        bars.reverse()  # Coinbase返回倒序
        if bars:
            logger.info(f"[COINBASE] {symbol} 获取 {len(bars)} 根K线 (gran={gran_str})")
        return bars if bars else None
    except Exception as e:
        logger.warning(f"[COINBASE] {symbol} 失败: {e}")
        return None


def _coinbase_fetch_paginated(symbol: str, granularity: int = 3600, total_bars: int = 720) -> list:
    """GCC-0261: Coinbase分页获取(突破300根限制), 用于Wyckoff长周期数据。

    Args:
        symbol: 品种代码
        granularity: 秒数 (3600=1H)
        total_bars: 总需求根数 (>300时自动分页)
    Returns:
        list[dict] 时间正序, 或空列表
    """
    import time as _time
    all_bars = []
    end_ts = int(_time.time())
    max_pages = (total_bars // 300) + 1

    for _ in range(max_pages):
        if len(all_bars) >= total_bars:
            break
        batch_limit = min(300, total_bars - len(all_bars))
        batch = _coinbase_fetch_candles(symbol, granularity=granularity, limit=batch_limit,
                                        end_timestamp=end_ts)
        if not batch:
            break
        all_bars = batch + all_bars  # prepend older bars (batch is time-ascending)
        # 下一页: end_ts = 最旧bar的timestamp之前
        try:
            oldest_ts_str = batch[0].get("timestamp", "")
            if oldest_ts_str:
                oldest_ts = int(float(oldest_ts_str))
                end_ts = oldest_ts - 1
            else:
                break
        except (ValueError, TypeError):
            break

    if all_bars:
        logger.info("[COINBASE] %s 分页获取 %d 根K线 (gran=%ds, pages=%d)",
                    symbol, len(all_bars), granularity, min(max_pages, (len(all_bars) // 300) + 1))
    return all_bars[-total_bars:] if len(all_bars) > total_bars else all_bars


def _schwab_verify_4h(symbol: str, lookback_bars: int) -> list:
    """GCC-0261: Schwab 30m数据 → resample 4H, 用于美股Wyckoff数据验证。

    Returns:
        list[dict] 4H bars 时间正序, 或空列表
    """
    try:
        from schwab_data_provider import get_provider
        provider = get_provider()
        # 4H = 8根30m, 加40%余量
        bars_30m = int(lookback_bars * 8 * 1.4)
        df = provider.get_kline(symbol, interval="30m", bars=bars_30m)
        if df is None or df.empty or len(df) < 16:
            return []
        # 每8根30m合并为1根4H
        bars_4h = []
        df_vals = df.reset_index()
        n = len(df_vals)
        for i in range(0, n - 7, 8):
            chunk = df_vals.iloc[i:i+8]
            bars_4h.append({
                "open": float(chunk["open"].iloc[0]),
                "high": float(chunk["high"].max()),
                "low": float(chunk["low"].min()),
                "close": float(chunk["close"].iloc[-1]),
                "volume": float(chunk["volume"].sum()),
                "timestamp": str(chunk.iloc[0].get("datetime", "")),
            })
        if bars_4h:
            logger.info("[SCHWAB] %s 4H验证: %d根 (从%d根30m重采样)", symbol, len(bars_4h), n)
        return bars_4h[-lookback_bars:] if len(bars_4h) > lookback_bars else bars_4h
    except ImportError:
        return []
    except Exception as e:
        logger.debug("[SCHWAB] %s 4H验证失败: %s", symbol, e)
        return []


def _verify_and_get_4h(symbol: str, yf_bars: list, lookback_bars: int) -> list:
    """GCC-0261: 用Schwab(美股)/Coinbase(加密)复查yfinance 4H数据完整性。

    策略: 优质源数据更完整时替换yfinance, 否则用yfinance。
    """
    yf_count = len(yf_bars) if yf_bars else 0

    if is_crypto_symbol(symbol):
        # Coinbase分页获取 1H → resample 4H
        needed_1h = lookback_bars * 4 + 4
        cb_1h = _coinbase_fetch_paginated(symbol, granularity=3600, total_bars=needed_1h)
        if cb_1h and len(cb_1h) >= 8:
            vf_bars = []
            for i in range(0, len(cb_1h) - 3, 4):
                chunk = cb_1h[i:i+4]
                vf_bars.append({
                    "open": chunk[0]["open"],
                    "high": max(c["high"] for c in chunk),
                    "low": min(c["low"] for c in chunk),
                    "close": chunk[-1]["close"],
                    "volume": sum(c["volume"] for c in chunk),
                    "timestamp": chunk[0]["timestamp"],
                })
            vf_count = len(vf_bars)
        else:
            vf_bars, vf_count = [], 0
    else:
        # Schwab 30m → 4H
        vf_bars = _schwab_verify_4h(symbol, lookback_bars)
        vf_count = len(vf_bars)

    # 比较: 更完整的数据源胜出
    if vf_count > yf_count * 1.1:  # 验证源多10%以上才替换
        logger.info("[VERIFY] %s 4H: yfinance=%d < verified=%d, 使用验证源", symbol, yf_count, vf_count)
        return vf_bars[-lookback_bars:] if vf_count > lookback_bars else vf_bars
    elif vf_count > 0 and yf_count > 0:
        # 数量相当, 检查最新价格一致性
        yf_last = yf_bars[-1].get("close", 0) if yf_bars else 0
        vf_last = vf_bars[-1].get("close", 0) if vf_bars else 0
        if vf_last > 0 and yf_last > 0:
            pct_diff = abs(yf_last - vf_last) / vf_last
            if pct_diff > 0.02:  # >2%偏差
                logger.warning("[VERIFY] %s 4H价格偏差: yf=%.2f vs vf=%.2f (%.1f%%)",
                              symbol, yf_last, vf_last, pct_diff * 100)
        logger.info("[VERIFY] %s 4H: yfinance=%d, verified=%d, 数据一致", symbol, yf_count, vf_count)

    return yf_bars if yf_bars else vf_bars


def _safe_ohlcv_row(row, idx=None):
    """v21.28: 统一OHLCV行验证 — 过滤NaN/Inf/high<low/close<=0"""
    _o, _h, _l, _c = float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"])
    if any(math.isnan(x) or math.isinf(x) for x in (_o, _h, _l, _c)):
        return None
    if _c <= 0 or (_h > 0 and _l > 0 and _h < _l):
        return None
    return {
        "open": _o, "high": _h, "low": _l, "close": _c,
        "volume": float(row["Volume"]) if (row["Volume"] > 0 and not math.isinf(float(row["Volume"]))) else 0.0,
        "timestamp": str(idx) if idx is not None else "",
    }


class YFinanceDataFetcher:
    """
    yfinance数据获取器 - v8.1 增强版
    
    改进:
    - 重试机制 (3次，指数退避)
    - 多period备选
    - 警告抑制
    - 缓存层
    """
    
    # 重试配置
    MAX_RETRIES = 3
    RETRY_DELAY = 2  # 秒
    FETCH_TIMEOUT = 30  # v16.2: 单次yfinance调用超时(秒)

    # 价格缓存 (symbol -> (price, timestamp))
    _price_cache: Dict[str, tuple] = {}
    _cache_ttl = 30  # 缓存30秒

    # v16.2: 扫描周期内OHLCV缓存 (避免同品种重复下载)
    # key = f"{symbol}_{interval}_{lookback}", value = bars list
    _scan_cycle_cache: Dict[str, Any] = {}
    _scan_cycle_id: int = 0  # 每次scan_once递增，缓存自动失效
    # GCC-0205: SCHWAB_FALLBACK_MODE=off|observe|active(默认active)
    _schwab_fallback_mode: str = (os.getenv("SCHWAB_FALLBACK_MODE", "active") or "active").strip().lower()
    _schwab_status_logged: bool = False
    _schwab_unavailable_warned: bool = False
    
    @staticmethod
    def _get_cached_price(symbol: str) -> Optional[float]:
        """从缓存获取价格"""
        if symbol in YFinanceDataFetcher._price_cache:
            price, ts = YFinanceDataFetcher._price_cache[symbol]
            if time.time() - ts < YFinanceDataFetcher._cache_ttl:
                return price
        return None
    
    @staticmethod
    def _set_cached_price(symbol: str, price: float):
        """设置价格缓存"""
        YFinanceDataFetcher._price_cache[symbol] = (price, time.time())

    @staticmethod
    def begin_scan_cycle():
        """v16.2: 开始新的扫描周期，清空OHLCV缓存"""
        YFinanceDataFetcher._scan_cycle_id += 1
        YFinanceDataFetcher._scan_cycle_cache.clear()
        if not YFinanceDataFetcher._schwab_status_logged:
            logger.info(
                f"[SCHWAB_FALLBACK] mode={YFinanceDataFetcher._schwab_fallback_mode} "
                f"provider_available={_schwab_provider_available}"
            )
            YFinanceDataFetcher._schwab_status_logged = True

    @staticmethod
    def _get_ohlcv_cache(symbol: str, interval: str, lookback: int) -> Optional[List]:
        """v16.2: 从扫描周期缓存获取OHLCV数据"""
        key = f"{symbol}_{interval}_{lookback}"
        return YFinanceDataFetcher._scan_cycle_cache.get(key)

    @staticmethod
    def _set_ohlcv_cache(symbol: str, interval: str, lookback: int, bars: List):
        """v16.2: 设置扫描周期OHLCV缓存"""
        key = f"{symbol}_{interval}_{lookback}"
        YFinanceDataFetcher._scan_cycle_cache[key] = bars

    @staticmethod
    def _schwab_mode_enabled() -> bool:
        return YFinanceDataFetcher._schwab_fallback_mode in ("observe", "active")

    @staticmethod
    def _schwab_mode_active() -> bool:
        return YFinanceDataFetcher._schwab_fallback_mode == "active"

    @staticmethod
    def _fetch_from_schwab_ohlcv(symbol: str, interval: str, lookback_bars: int) -> Optional[List[Dict]]:
        """GCC-0205: 股票数据yfinance失败后的Schwab后备通道（加密直接跳过）"""
        if is_crypto_symbol(symbol):
            return None
        if not YFinanceDataFetcher._schwab_mode_enabled():
            return None
        if not _schwab_provider_available:
            if not YFinanceDataFetcher._schwab_unavailable_warned:
                logger.warning(
                    "[SCHWAB_FALLBACK] provider unavailable; "
                    "check schwab_data_provider deps/env/token"
                )
                YFinanceDataFetcher._schwab_unavailable_warned = True
            return None
        try:
            provider = get_schwab_provider()
            df = provider.get_kline(symbol, interval=interval, bars=max(lookback_bars, 10))
            if df is None or df.empty:
                return None
            recent = df.tail(lookback_bars)
            bars: List[Dict] = []
            for idx, row in recent.iterrows():
                try:
                    b = {
                        "open": float(row["open"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "close": float(row["close"]),
                        "volume": float(row.get("volume", 0.0) or 0.0),
                        "timestamp": str(idx),
                    }
                    if b["close"] > 0 and b["high"] >= b["low"]:
                        bars.append(b)
                except Exception:
                    continue
            return bars if bars else None
        except Exception as e:
            logger.warning(f"[SCHWAB_FALLBACK] {symbol} {interval} fetch error: {e}")
            return None

    @staticmethod
    def _fetch_from_schwab_price(symbol: str) -> Optional[float]:
        """GCC-0205: 当前价后备通道（仅股票）"""
        if is_crypto_symbol(symbol):
            return None
        if not YFinanceDataFetcher._schwab_mode_enabled():
            return None
        if not _schwab_provider_available:
            if not YFinanceDataFetcher._schwab_unavailable_warned:
                logger.warning(
                    "[SCHWAB_FALLBACK] provider unavailable; "
                    "check schwab_data_provider deps/env/token"
                )
                YFinanceDataFetcher._schwab_unavailable_warned = True
            return None
        try:
            provider = get_schwab_provider()
            df = provider.get_kline(symbol, interval="1m", bars=2)
            if df is None or df.empty:
                return None
            price = float(df["close"].iloc[-1])
            return price if price > 0 else None
        except Exception as e:
            logger.warning(f"[SCHWAB_FALLBACK] {symbol} price fetch error: {e}")
            return None

    @staticmethod
    def _fetch_with_timeout(func, timeout: int = None):
        """v16.2: 带超时保护的函数执行，防止yfinance无限阻塞
        注意: 不能用with语句，因为__exit__会调用shutdown(wait=True)导致超时无效
        """
        if timeout is None:
            timeout = YFinanceDataFetcher.FETCH_TIMEOUT
        logger.debug(f"[v16.2] _fetch_with_timeout: 启动线程池，超时={timeout}秒")
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(func)
        try:
            result = future.result(timeout=timeout)
            logger.debug(f"[v16.2] _fetch_with_timeout: 成功获取结果")
            executor.shutdown(wait=False)
            return result
        except FuturesTimeoutError:
            logger.warning(f"[v16.2] yfinance调用超时({timeout}秒)！正在强制返回...")
            executor.shutdown(wait=False)
            return None
        except Exception as e:
            logger.warning(f"[v16.2] _fetch_with_timeout异常: {e}")
            executor.shutdown(wait=False)
            raise e

    @staticmethod
    def _retry_fetch(fetch_func, symbol: str, *args, **kwargs) -> Any:
        """带重试+超时的数据获取"""
        import random

        last_error = None
        for attempt in range(YFinanceDataFetcher.MAX_RETRIES):
            try:
                # v16.2: 用超时保护包裹每次尝试
                result = YFinanceDataFetcher._fetch_with_timeout(
                    lambda: fetch_func(symbol, *args, **kwargs)
                )
                if result is not None:
                    return result
            except Exception as e:
                last_error = e
                if attempt < YFinanceDataFetcher.MAX_RETRIES - 1:
                    delay = YFinanceDataFetcher.RETRY_DELAY * (2 ** attempt) + random.uniform(0, 1)
                    time.sleep(delay)

        if last_error:
            logger.debug(f"[yf] {symbol} 获取失败(重试{YFinanceDataFetcher.MAX_RETRIES}次): {last_error}")
        return None

    @staticmethod
    def get_current_price(symbol: str) -> Optional[float]:
        """获取当前价格 - 增强版"""
        # 先查缓存
        cached = YFinanceDataFetcher._get_cached_price(symbol)
        if cached:
            return cached
        
        def _fetch(sym):
            yf_sym = CRYPTO_SYMBOL_MAP.get(sym, sym)
            ticker = yf.Ticker(yf_sym)
            
            # 方法1: 从 info 获取
            try:
                info = ticker.info
                price = info.get("regularMarketPrice") or info.get("currentPrice")
                if price and float(price) > 0:
                    return float(price)
            except Exception:  # v16 P2-2
                pass
            
            # 方法2: 从历史数据获取 (多period尝试)
            for period in ["1d", "5d", "7d"]:
                try:
                    hist = ticker.history(period=period, interval="1m")
                    if not hist.empty:
                        price = float(hist["Close"].iloc[-1])
                        if price > 0:
                            return price
                except Exception:  # v16 P2-2
                    continue
            
            return None
        
        price = YFinanceDataFetcher._retry_fetch(_fetch, symbol)
        if price:
            YFinanceDataFetcher._set_cached_price(symbol, price)
            return price

        # GCC-0205: yfinance失败后尝试Schwab（默认observe仅记录，不替换）
        schwab_price = YFinanceDataFetcher._fetch_from_schwab_price(symbol)
        if schwab_price is not None:
            logger.info(
                f"[SCHWAB_FALLBACK] price {symbol} success mode={YFinanceDataFetcher._schwab_fallback_mode}"
            )
            if YFinanceDataFetcher._schwab_mode_active():
                YFinanceDataFetcher._set_cached_price(symbol, schwab_price)
                return schwab_price
        return None

    @staticmethod
    def get_1m_close_price(symbol: str) -> Optional[float]:
        """获取最近完成的1分钟K线收盘价 - 增强版"""
        def _fetch(sym):
            ticker = yf.Ticker(sym)
            
            for period in ["1d", "5d", "7d"]:
                try:
                    hist = ticker.history(period=period, interval="1m")
                    if not hist.empty and len(hist) >= 2:
                        return float(hist["Close"].iloc[-2])
                    elif not hist.empty:
                        return float(hist["Close"].iloc[-1])
                except Exception:  # v16 P2-2
                    continue
            
            return None
        
        return YFinanceDataFetcher._retry_fetch(_fetch, symbol)

    @staticmethod
    def get_period_open(symbol: str, timeframe: str = "1h") -> Optional[float]:
        """获取当前周期的开盘价 - 增强版"""
        def _fetch(sym):
            ticker = yf.Ticker(sym)
            interval = "1h" if timeframe == "1h" else "30m"
            
            for period in ["1d", "2d", "5d"]:
                try:
                    hist = ticker.history(period=period, interval=interval)
                    if not hist.empty:
                        return float(hist["Open"].iloc[-1])
                except Exception:  # v16 P2-2
                    continue
            
            return None
        
        return YFinanceDataFetcher._retry_fetch(_fetch, symbol)

    @staticmethod
    def get_previous_period_open(symbol: str, timeframe: str = "1h") -> Optional[float]:
        """获取前一个周期的开盘价 - 增强版"""
        def _fetch(sym):
            ticker = yf.Ticker(sym)
            interval = "1h" if timeframe == "1h" else "30m"
            
            for period in ["2d", "5d", "7d"]:
                try:
                    hist = ticker.history(period=period, interval=interval)
                    if not hist.empty and len(hist) >= 2:
                        return float(hist["Open"].iloc[-2])
                    elif not hist.empty:
                        return float(hist["Open"].iloc[-1])
                except Exception:  # v16 P2-2
                    continue
            
            return None
        
        return YFinanceDataFetcher._retry_fetch(_fetch, symbol)

    @staticmethod
    def get_today_market_open_price(symbol: str) -> Optional[float]:
        """
        v8.3: 获取美股当天开盘价 (09:30的价格)

        返回当天第一根K线的开盘价，如果当天没有数据则返回None
        """
        def _fetch(sym):
            ticker = yf.Ticker(sym)

            try:
                # 获取最近2天的1小时数据
                hist = ticker.history(period="2d", interval="1h")
                if hist.empty:
                    return None

                # 获取今天的纽约日期
                ny_now = get_ny_now()
                today_str = ny_now.strftime("%Y-%m-%d")

                # 过滤出今天的数据
                hist.index = hist.index.tz_convert('America/New_York')
                today_data = hist[hist.index.strftime("%Y-%m-%d") == today_str]

                if not today_data.empty:
                    # 返回今天第一根K线的开盘价
                    return float(today_data["Open"].iloc[0])

                # 如果今天没有数据（还没开盘），返回None
                return None
            except Exception as e:
                logger.warning(f"[{sym}] 获取当天开盘价失败: {e}")
                return None

        return YFinanceDataFetcher._retry_fetch(_fetch, symbol)

    @staticmethod
    def get_recent_high_low(symbol: str, lookback_bars: int = 30) -> tuple:
        """获取最近N根K线的最高价和最低价 - 增强版"""
        def _fetch(sym):
            ticker = yf.Ticker(sym)

            for period in ["5d", "7d", "1mo"]:
                try:
                    hist = ticker.history(period=period, interval="15m")
                    if not hist.empty and len(hist) >= 2:
                        recent = hist.tail(lookback_bars)
                        high = float(recent["High"].max())
                        low = float(recent["Low"].min())
                        return (high, low)
                except Exception:  # v16 P2-2
                    continue

            return None

        result = YFinanceDataFetcher._retry_fetch(_fetch, symbol)
        return result if result else (None, None)

    @staticmethod
    def get_first_local_extremes(symbol: str, lookback_bars: int = 30) -> tuple:
        """
        v20.3: 获取最近的局部极值点（第一个拐点）

        优先级：
        1. 从当前K线往前找第一个局部高点/低点
        2. 找不到则回退到30根K线的绝对最高/最低

        局部高点: K线高点 > 前一根高点 且 > 后一根高点
        局部低点: K线低点 < 前一根低点 且 < 后一根低点

        Returns:
            (local_high, local_low, high_type, low_type)
            high_type/low_type: "local" 或 "absolute"
        """
        def _fetch(sym):
            ticker = yf.Ticker(sym)

            for period in ["5d", "7d", "1mo"]:
                try:
                    hist = ticker.history(period=period, interval="15m")
                    if not hist.empty and len(hist) >= 4:  # 至少需要4根才能判断拐点
                        recent = hist.tail(lookback_bars)
                        highs = recent["High"].values
                        lows = recent["Low"].values
                        n = len(highs)

                        # 从倒数第2根往前找（倒数第1根是当前未完成的K线）
                        local_high = None
                        local_low = None
                        high_type = "absolute"
                        low_type = "absolute"

                        # 找第一个局部高点 (从后往前)
                        for i in range(n - 2, 0, -1):  # 从倒数第2根到第2根
                            if highs[i] > highs[i-1] and highs[i] > highs[i+1]:
                                local_high = float(highs[i])
                                high_type = "local"
                                break

                        # 找第一个局部低点 (从后往前)
                        for i in range(n - 2, 0, -1):
                            if lows[i] < lows[i-1] and lows[i] < lows[i+1]:
                                local_low = float(lows[i])
                                low_type = "local"
                                break

                        # 找不到局部极值则使用绝对极值
                        if local_high is None:
                            local_high = float(recent["High"].max())
                        if local_low is None:
                            local_low = float(recent["Low"].min())

                        return (local_high, local_low, high_type, low_type)
                except Exception:
                    continue

            return None

        result = YFinanceDataFetcher._retry_fetch(_fetch, symbol)
        return result if result else (None, None, None, None)

    @staticmethod
    def get_5m_ohlcv(symbol: str, lookback_bars: int = 100) -> Optional[List[Dict]]:
        """
        v12.0: 获取5分钟K线OHLCV数据 (用于剥头皮策略)
        v16.2: 增加扫描周期缓存

        Args:
            symbol: 交易对符号
            lookback_bars: 需要的K线数量 (默认100根)

        Returns:
            List[Dict]: OHLCV数据列表，每项包含 {open, high, low, close, volume}
            按时间正序排列（最旧的在前）
        """
        # v16.2: 扫描周期缓存检查
        cached = YFinanceDataFetcher._get_ohlcv_cache(symbol, "5m", lookback_bars)
        if cached is not None:
            return cached

        def _fetch(sym):
            ticker = yf.Ticker(sym)

            # 5分钟K线需要更多天数来获取足够的bars
            # 100根5分钟 ≈ 500分钟 ≈ 8小时，但市场有休市，需要更长period
            for period in ["5d", "7d", "1mo"]:
                try:
                    hist = ticker.history(period=period, interval="5m")
                    if hist.empty:
                        continue

                    # 确保有足够的数据
                    if len(hist) < lookback_bars:
                        continue

                    # 取最近N根K线
                    recent = hist.tail(lookback_bars)

                    # v21.28: 统一验证
                    bars = []
                    for idx, row in recent.iterrows():
                        b = _safe_ohlcv_row(row, idx)
                        if b:
                            bars.append(b)

                    return bars
                except Exception as e:
                    logger.debug(f"[yf] {sym} 获取5分钟数据失败 (period={period}): {e}")
                    continue

            return None

        result = YFinanceDataFetcher._retry_fetch(_fetch, symbol)
        # v16.2: 缓存结果
        if result is not None:
            YFinanceDataFetcher._set_ohlcv_cache(symbol, "5m", lookback_bars, result)
        return result

    @staticmethod
    def get_15m_ohlcv(symbol: str, lookback_bars: int = 100) -> Optional[List[Dict]]:
        """
        v3.565: 获取15分钟K线OHLCV数据 (用于MACD背离外挂 + GCC-0258 S11多周期信号)
        v16.2: 增加扫描周期缓存
        GCC-0258 S11: 加密优先Coinbase FIFTEEN_MINUTE, 美股fallback Schwab 15min

        Args:
            symbol: 交易对符号
            lookback_bars: 需要的K线数量 (默认100根)

        Returns:
            List[Dict]: OHLCV数据列表，每项包含 {open, high, low, close, volume, timestamp}
            按时间正序排列（最旧的在前）
        """
        # v16.2: 扫描周期缓存检查
        cached = YFinanceDataFetcher._get_ohlcv_cache(symbol, "15m", lookback_bars)
        if cached is not None:
            return cached

        # GCC-0258 S11: 加密货币优先 Coinbase FIFTEEN_MINUTE (granularity=900)
        if is_crypto_symbol(symbol):
            cb_bars = _coinbase_fetch_candles(symbol, granularity=900, limit=min(lookback_bars, 300))
            if cb_bars and len(cb_bars) >= min(lookback_bars, 10):
                YFinanceDataFetcher._set_ohlcv_cache(symbol, "15m", lookback_bars, cb_bars)
                return cb_bars
            logger.info(f"[COINBASE] {symbol} 15m失败, 降级yfinance")

        def _fetch(sym):
            ticker = yf.Ticker(sym)

            # 15分钟K线: 100根 ≈ 1500分钟 ≈ 25小时
            for period in ["5d", "7d", "1mo"]:
                try:
                    hist = ticker.history(period=period, interval="15m")
                    if hist.empty:
                        continue

                    if len(hist) < lookback_bars:
                        continue

                    recent = hist.tail(lookback_bars)

                    # v21.28: 统一验证
                    bars = []
                    for idx, row in recent.iterrows():
                        b = _safe_ohlcv_row(row, idx)
                        if b:
                            bars.append(b)

                    return bars
                except Exception as e:
                    logger.debug(f"[yf] {sym} 获取15分钟数据失败 (period={period}): {e}")
                    continue

            return None

        result = YFinanceDataFetcher._retry_fetch(_fetch, symbol)
        # GCC-0258 S11: 美股yfinance失败 → Schwab 15min fallback
        if result is None:
            schwab_bars = YFinanceDataFetcher._fetch_from_schwab_ohlcv(symbol, "15min", lookback_bars)
            if schwab_bars:
                logger.info(f"[SCHWAB_FALLBACK] 15m {symbol} success bars={len(schwab_bars)}")
                if YFinanceDataFetcher._schwab_mode_active():
                    result = schwab_bars
        # v16.2: 缓存结果
        if result is not None:
            YFinanceDataFetcher._set_ohlcv_cache(symbol, "15m", lookback_bars, result)
        return result

    @staticmethod
    def get_1h_ohlcv(symbol: str, lookback_bars: int = 30) -> Optional[List[Dict]]:
        """
        v3.530: 获取1小时K线OHLCV数据 (用于SuperTrend外挂)
        v16.2: 增加扫描周期缓存
        v21.20: 加密货币优先走Coinbase API，失败降级yfinance

        Args:
            symbol: 交易对符号
            lookback_bars: 需要的K线数量 (默认30根)

        Returns:
            List[Dict]: OHLCV数据列表，每项包含 {open, high, low, close, volume, timestamp}
            按时间正序排列（最旧的在前）
        """
        # v16.2: 扫描周期缓存检查
        cached = YFinanceDataFetcher._get_ohlcv_cache(symbol, "1h", lookback_bars)
        if cached is not None:
            return cached

        # v21.20: 加密货币优先 Coinbase
        if is_crypto_symbol(symbol):
            cb_bars = _coinbase_fetch_candles(symbol, granularity=3600, limit=lookback_bars)
            if cb_bars and len(cb_bars) >= min(lookback_bars, 10):
                YFinanceDataFetcher._set_ohlcv_cache(symbol, "1h", lookback_bars, cb_bars)
                return cb_bars
            logger.info(f"[COINBASE] {symbol} 1H失败, 降级yfinance")

        def _fetch(sym):
            ticker = yf.Ticker(sym)

            for period in ["7d", "1mo", "3mo"]:
                try:
                    hist = ticker.history(period=period, interval="1h")
                    if hist.empty:
                        continue
                    if len(hist) < lookback_bars:
                        continue
                    recent = hist.tail(lookback_bars)
                    bars = []
                    for idx, row in recent.iterrows():
                        b = _safe_ohlcv_row(row, idx)
                        if b:
                            bars.append(b)
                    return bars
                except Exception as e:
                    logger.debug(f"[yf] {sym}/{yf_sym} 获取1小时数据失败 (period={period}): {e}")
                    continue
            return None

        result = YFinanceDataFetcher._retry_fetch(_fetch, symbol)
        if result is None:
            schwab_bars = YFinanceDataFetcher._fetch_from_schwab_ohlcv(symbol, "1h", lookback_bars)
            if schwab_bars:
                logger.info(
                    f"[SCHWAB_FALLBACK] 1h {symbol} success bars={len(schwab_bars)} "
                    f"mode={YFinanceDataFetcher._schwab_fallback_mode}"
                )
                if YFinanceDataFetcher._schwab_mode_active():
                    result = schwab_bars
        if result is not None:
            YFinanceDataFetcher._set_ohlcv_cache(symbol, "1h", lookback_bars, result)
        return result

    @staticmethod
    def get_4h_ohlcv(symbol: str, lookback_bars: int = 30) -> Optional[List[Dict]]:
        """
        v3.546: 获取4小时K线OHLCV数据 (用于外挂4小时周期)
        v16.2: 增加扫描周期缓存，同品种同lookback不重复下载
        v21.20: 加密货币优先走Coinbase 1H数据 → 本地resample 4H

        Args:
            symbol: 交易对符号
            lookback_bars: 需要的K线数量 (默认30根)

        Returns:
            List[Dict]: OHLCV数据列表，每项包含 {open, high, low, close, volume, timestamp}
            按时间正序排列（最旧的在前）
        """
        # v16.2: 扫描周期缓存检查
        cached = YFinanceDataFetcher._get_ohlcv_cache(symbol, "4h", lookback_bars)
        if cached is not None:
            return cached

        # v21.20: 加密货币优先 Coinbase 1H → resample 4H
        # v21.25: Coinbase API max=300根, cap limit避免HTTP 400 (chan_bs 120*4+4=484 > 300)
        if is_crypto_symbol(symbol):
            _cb_limit = min(lookback_bars * 4 + 4, 300)
            cb_1h = _coinbase_fetch_candles(symbol, granularity=3600, limit=_cb_limit)
            if cb_1h and len(cb_1h) >= 8:
                # 每4根1H合并为1根4H
                bars_4h = []
                for i in range(0, len(cb_1h) - 3, 4):
                    chunk = cb_1h[i:i+4]
                    bars_4h.append({
                        "open": chunk[0]["open"],
                        "high": max(c["high"] for c in chunk),
                        "low": min(c["low"] for c in chunk),
                        "close": chunk[-1]["close"],
                        "volume": sum(c["volume"] for c in chunk),
                        "timestamp": chunk[0]["timestamp"],
                    })
                # GCC-0261: 要求至少返回lookback的一半, 否则降级yfinance获取更多
                _min_accept = max(lookback_bars // 2, 5)
                if len(bars_4h) >= _min_accept:
                    result = bars_4h[-lookback_bars:] if len(bars_4h) > lookback_bars else bars_4h
                    YFinanceDataFetcher._set_ohlcv_cache(symbol, "4h", lookback_bars, result)
                    return result
            logger.info(f"[COINBASE] {symbol} 4H失败, 降级yfinance")

        def _fetch(sym):
            yf_sym = CRYPTO_SYMBOL_MAP.get(sym, sym)
            ticker = yf.Ticker(yf_sym)

            # 4小时K线: yfinance没有原生4h，需要用1h重采样
            # v21.1: 美股用交易时间顺序合并(每4根1h→1根4h)，加密用日历resample
            # 原因: 美股每天只7根1h，resample('4h')按日历切会产生大量NaN被dropna丢弃
            is_crypto = is_crypto_symbol(sym)
            for period in ["1mo", "3mo"]:
                try:
                    hist = ticker.history(period=period, interval="1h")
                    if hist.empty:
                        continue

                    if is_crypto:
                        # 加密货币: 24小时连续交易，日历resample正常工作
                        hist_4h = hist.resample('4h').agg({
                            'Open': 'first',
                            'High': 'max',
                            'Low': 'min',
                            'Close': 'last',
                            'Volume': 'sum'
                        }).dropna()
                    else:
                        # 美股: 按交易时间顺序每4根1h合并为1根4h
                        hist = hist.dropna(subset=['Close'])
                        n = len(hist)
                        rows = []
                        for i in range(0, n - 3, 4):
                            chunk = hist.iloc[i:i+4]
                            rows.append({
                                'Open': chunk['Open'].iloc[0],
                                'High': chunk['High'].max(),
                                'Low': chunk['Low'].min(),
                                'Close': chunk['Close'].iloc[-1],
                                'Volume': chunk['Volume'].sum(),
                            })
                        if not rows:
                            continue
                        import pandas as pd
                        hist_4h = pd.DataFrame(rows)

                    # v21.1: 1mo不够→升级3mo; 3mo有多少返回多少(调用方自己检查最低要求)
                    if len(hist_4h) < lookback_bars and period != "3mo":
                        continue
                    if len(hist_4h) == 0:
                        continue

                    # 取最近N根K线(可能少于lookback_bars)
                    recent = hist_4h.tail(lookback_bars)

                    # v21.28: 统一验证
                    bars = []
                    for idx, row in recent.iterrows():
                        b = _safe_ohlcv_row(row, idx)
                        if b:
                            bars.append(b)

                    return bars
                except Exception as e:
                    logger.debug(f"[yf] {sym}/{yf_sym} 获取4小时数据失败 (period={period}): {e}")
                    continue

            return None

        # 4H不走Schwab fallback：
        # TradingView webhook为主链路，Schwab无原生4H且会映射到1D，易引入周期失真。
        # 因此4H仅保留 Coinbase -> yfinance 流程。
        result = YFinanceDataFetcher._retry_fetch(_fetch, symbol)
        # v16.2: 缓存结果（包括None，避免重复失败调用）
        if result is not None:
            YFinanceDataFetcher._set_ohlcv_cache(symbol, "4h", lookback_bars, result)
        return result

    @staticmethod
    def get_ohlcv(symbol: str, timeframe_minutes: int, lookback_bars: int = 30) -> Optional[List[Dict]]:
        """
        v20: 通用OHLCV获取方法，根据timeframe自动选择获取策略

        Args:
            symbol: 交易对符号
            timeframe_minutes: 周期(分钟) — 60=1h, 120=2h, 240=4h等
            lookback_bars: 需要的K线数量

        Returns:
            List[Dict]: OHLCV数据列表 或 None
        """
        if timeframe_minutes <= 60:
            return YFinanceDataFetcher.get_1h_ohlcv(symbol, lookback_bars)
        elif timeframe_minutes == 240:
            return YFinanceDataFetcher.get_4h_ohlcv(symbol, lookback_bars)
        else:
            # 通用重采样: 下载1h数据，重采样到目标周期
            cache_key = f"{timeframe_minutes // 60}h"
            cached = YFinanceDataFetcher._get_ohlcv_cache(symbol, cache_key, lookback_bars)
            if cached is not None:
                return cached

            def _fetch(sym):
                import yfinance as yf
                yf_sym = CRYPTO_SYMBOL_MAP.get(sym, sym)
                ticker = yf.Ticker(yf_sym)
                # 需要足够的1h数据来重采样
                hours_needed = lookback_bars * (timeframe_minutes / 60) * 1.5
                period = "1mo" if hours_needed <= 500 else "3mo"
                for p in [period, "3mo"]:
                    try:
                        hist = ticker.history(period=p, interval="1h")
                        if hist.empty:
                            continue
                        resample_rule = f"{timeframe_minutes // 60}h"
                        hist_resampled = hist.resample(resample_rule).agg({
                            'Open': 'first', 'High': 'max',
                            'Low': 'min', 'Close': 'last', 'Volume': 'sum'
                        }).dropna()
                        if len(hist_resampled) < lookback_bars:
                            continue
                        recent = hist_resampled.tail(lookback_bars)
                        # v21.28: 统一验证
                        bars = []
                        for idx, row in recent.iterrows():
                            b = _safe_ohlcv_row(row, idx)
                            if b:
                                bars.append(b)
                        return bars
                    except Exception:
                        continue
                return None

            result = YFinanceDataFetcher._retry_fetch(_fetch, symbol)
            if result is not None:
                YFinanceDataFetcher._set_ohlcv_cache(symbol, cache_key, lookback_bars, result)
            return result


# ============================================================
# v3.540: 趋势同步HTTP服务器
# ============================================================

def _create_trend_sync_app():
    """
    v3.540: 创建Flask应用接收趋势更新

    端点:
    - POST /update_trend: 接收主程序趋势更新，立即刷新内存缓存
    - GET /trend_status: 查看当前趋势状态
    """
    global _global_trend_cache, _global_trend_lock

    if not _flask_available:
        return None

    app = Flask(__name__)

    # 禁用Flask默认日志，避免刷屏
    import logging as flask_logging
    flask_log = flask_logging.getLogger('werkzeug')
    flask_log.setLevel(flask_logging.ERROR)

    @app.route('/update_trend', methods=['POST'])
    def update_trend():
        """接收主程序的趋势更新通知，立即刷新内存缓存"""
        global _global_trend_cache
        data = request.json
        symbol = data.get("symbol")
        trend = data.get("trend")
        regime = data.get("regime")
        reason = data.get("reason", "")
        current_trend = data.get("current_trend")  # v3.551fix: 当前周期方向
        trend_x4 = data.get("trend_x4", "SIDE")  # v3.571: x4大周期道氏趋势
        current_regime = data.get("current_regime", "UNKNOWN")  # v3.572: 当前周期震荡/趋势
        regime_x4 = data.get("regime_x4", "UNKNOWN")  # v3.572: x4周期震荡/趋势

        if not symbol or not trend:
            return jsonify({"status": "error", "message": "missing symbol or trend"}), 400

        with _global_trend_lock:
            # v21: 保留已有的l2_recommendation
            _existing_l2_rec = _global_trend_cache.get(symbol, {}).get("l2_recommendation", "HOLD")
            _global_trend_cache[symbol] = {
                "trend": trend,
                "regime": regime,
                "current_trend": current_trend or trend,  # v3.551fix
                "trend_x4": trend_x4.upper() if trend_x4 else "SIDE",  # v3.571: x4大周期
                "current_regime": current_regime,  # v3.572: 当前周期震荡/趋势
                "regime_x4": regime_x4,  # v3.572: x4周期震荡/趋势
                "l2_recommendation": _existing_l2_rec,  # v21: 保留L2 recommendation
                "update_time": datetime.now().isoformat(),
                "reason": reason
            }

        # v3.572: 显示趋势信息 (x4就是大周期，用于顺大逆小)
        ct = current_trend or trend
        logger.info(f"[v3.572] 趋势更新: {symbol} → 当前:{ct}({current_regime}) x4大周期:{trend_x4}({regime_x4})")

        # v21.8: 同步到共识度方向缓存
        update_consensus_direction(symbol, "x4_trend", trend_x4 or "SIDE")
        update_consensus_direction(symbol, "current_trend", ct or "SIDE")
        # Vision方向从data中读取 (主程序在L1计算后推送)
        _vision_dir = data.get("vision_direction")
        if _vision_dir:
            update_consensus_direction(symbol, "vision", _vision_dir)

        return jsonify({"status": "ok", "symbol": symbol, "trend": trend, "regime": regime,
                       "current_trend": ct, "trend_x4": trend_x4, "current_regime": current_regime, "regime_x4": regime_x4})

    @app.route('/update_l2_recommendation', methods=['POST'])
    def update_l2_recommendation():
        """v21: 接收主程序的L2 recommendation更新，更新内存缓存"""
        global _global_trend_cache
        data = request.json
        symbol = data.get("symbol")
        l2_rec = data.get("l2_recommendation", "HOLD")

        if not symbol:
            return jsonify({"status": "error", "message": "missing symbol"}), 400

        with _global_trend_lock:
            if symbol in _global_trend_cache:
                _global_trend_cache[symbol]["l2_recommendation"] = l2_rec
            else:
                _global_trend_cache[symbol] = {
                    "trend": "SIDE",
                    "regime": "RANGING",
                    "l2_recommendation": l2_rec,
                    "update_time": datetime.now().isoformat(),
                }

        # v21.8: 同步L2方向到共识度缓存
        update_consensus_direction(symbol, "l2_rec", l2_rec)

        logger.info(f"[v21] L2 recommendation更新: {symbol} → {l2_rec}")
        return jsonify({"status": "ok", "symbol": symbol, "l2_recommendation": l2_rec})

    @app.route('/trend_status', methods=['GET'])
    def trend_status():
        """查看当前趋势状态"""
        with _global_trend_lock:
            status = dict(_global_trend_cache)
        return jsonify({"status": "ok", "trends": status})

    @app.route('/reload_state', methods=['POST'])
    def reload_state():
        """
        v17.1: 热重载配额状态
        调用方式: curl -X POST http://127.0.0.1:6002/reload_state
        """
        global _scan_engine_instance
        if _scan_engine_instance is None:
            return jsonify({"status": "error", "message": "扫描引擎未初始化"}), 500

        try:
            # 重新加载激活外挂状态 (v21.7: 只加载激活外挂)
            # _scan_engine_instance._load_tracking_state()  # v21: 禁用
            # _scan_engine_instance._load_scalping_state()  # v21: 禁用
            _scan_engine_instance._load_supertrend_state()
            _scan_engine_instance._load_rob_hoffman_state()  # v2.0.1恢复
            _scan_engine_instance._load_double_pattern_state()
            # _scan_engine_instance._load_feiyun_state()  # v21: 禁用
            _scan_engine_instance._load_chan_bs_state()  # v21.1: 缠论买卖点
            # _scan_engine_instance._load_supertrend_av2_state()  # v15.2: 屏蔽

            logger.info("[v17.1] 配额状态已热重载")
            return jsonify({"status": "ok", "message": "配额状态已重载"})
        except Exception as e:
            logger.error(f"[v17.1] 配额重载失败: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500

    return app


def _start_trend_sync_server(port: int = 6002):
    """
    v3.540: 在后台线程启动趋势同步HTTP服务器

    Args:
        port: 监听端口 (默认6002)
    """
    global _trend_sync_app

    if not _flask_available:
        logger.warning("[v3.540] Flask未安装，趋势同步HTTP服务器禁用")
        return

    _trend_sync_app = _create_trend_sync_app()
    if _trend_sync_app is None:
        return

    def run_server():
        try:
            # 使用threaded=True允许并发请求
            _trend_sync_app.run(host='127.0.0.1', port=port, threaded=True, use_reloader=False)
        except Exception as e:
            logger.error(f"[v3.540] 趋势同步服务器启动失败: {e}")

    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    logger.info(f"[v3.540] 趋势同步服务器已启动 (端口{port})")


# ============================================================
# 扫描引擎核心
# ============================================================

class PriceScanEngine:
    """
    价格扫描引擎 v11.0 (配合主程序 v3.360)

    v11.0 更新:
    - P0-Tracking正常运行: 扫描引擎一直工作
    - L1外挂条件激活: 触发时检查L1趋势状态
      * UP趋势(consensus=AGREE) + BUY触发 → 激活L1外挂
      * DOWN趋势(consensus=AGREE) + SELL触发 → 激活L1外挂
      * 震荡/无趋势 → P0-Tracking正常执行，不激活L1外挂
    - 启动冷却期: 重启后5分钟内不触发信号，防止状态异常导致误触发
    - 解冻后使用当前价: 不再依赖历史high/low，避免价格跳跃误触发
    """

    # v11.0: 启动冷却期配置
    STARTUP_COOLDOWN_SECONDS = 300  # 5分钟

    def __init__(self, config: Dict = None):
        self.config = config or CONFIG
        self.running = False

        # v11.0: 记录启动时间，用于启动冷却期检查
        self.startup_time = time.time()

        # P0-Open状态
        # {symbol: {
        #     "base_price": float,          # 基准价（上次触发价或周期开盘价）
        #     "period_start": str,          # 周期开始时间
        #     "triggered_action": str,      # 本周期触发的动作 ("BUY"/"SELL"/None)
        #     "last_trigger_price": float,  # v8.0: 上次触发时的价格
        # }}
        self.state: Dict[str, Dict] = {}

        # P0-Tracking状态
        # {symbol: {
        #     "peak_price": float,
        #     "trough_price": float,
        #     "last_position": int,
        #     "period_start": str,
        #     "triggered_action": str,       # v8.0: 本周期触发的动作
        #     "trigger_history": [           # v8.0: 6小时内触发历史
        #         {"action": "BUY", "time": "...", "price": float},
        #         {"action": "SELL", "time": "...", "price": float},
        #     ],
        #     "freeze_until": str,           # v8.0: 冻结截止时间(ISO格式)
        # }}
        self.tracking_state: Dict[str, Dict] = {}

        # v12.0: Chandelier+ZLSMA剥头皮状态
        # {symbol: {
        #     "freeze_until": str,           # 冻结截止时间(ISO格式)
        #     "last_signal": str,            # 上次信号 ("BUY"/"SELL")
        #     "last_trigger_time": str,      # 上次触发时间
        #     "last_trigger_price": float,   # 上次触发价格
        #     # v12.4新增:
        #     "total_cost": float,           # 累计买入金额
        #     "total_revenue": float,        # 累计卖出金额
        #     "rounds_completed": int,       # 已完成回合数
        #     "in_round": bool,              # 是否在回合中
        # }}
        self.scalping_state: Dict[str, Dict] = {}

        # v12.4: 剥头皮全局状态 (利润目标追踪)
        self.scalping_global: Dict = {
            "daily_target_rate": 0.0,       # 0.3%-0.4% 每日随机目标
            "target_generated_date": "",    # 生成日期 (NY时间)
            "global_frozen_until": None,    # 全局冻结到次日8AM
        }

        # v13.0: 剥头皮5分钟周期触发状态
        # {symbol: {"last_trigger_bar": timestamp, "triggered_direction": "BUY"/"SELL"}}
        self.scalping_cycle_state: Dict[str, Dict] = {}

        # v3.530: SuperTrend外挂状态
        # {symbol: {
        #     "freeze_until": str,           # 冻结截止时间(ISO格式)
        #     "last_signal": str,            # 上次信号 ("BUY"/"SELL")
        #     "last_trigger_time": str,      # 上次触发时间
        # }}
        self.supertrend_state: Dict[str, Dict] = {}

        # v3.530: SuperTrend 1小时周期触发状态
        # {symbol: {"last_trigger_bar": timestamp, "triggered_direction": "BUY"/"SELL"}}
        self.supertrend_cycle_state: Dict[str, Dict] = {}

        # v3.545: Rob Hoffman外挂状态
        self.rob_hoffman_state: Dict[str, Dict] = {}
        self.rob_hoffman_cycle_state: Dict[str, Dict] = {}

        # v3.545: 双底双顶外挂状态
        self.double_pattern_state: Dict[str, Dict] = {}
        self.double_pattern_cycle_state: Dict[str, Dict] = {}

        # v3.545: 飞云双突破外挂状态
        self.feiyun_state: Dict[str, Dict] = {}
        self.feiyun_cycle_state: Dict[str, Dict] = {}

        # v21.16: MACD背离外挂已从扫描引擎删除, 仅保留L2小周期版本

        # v21.1: 缠论买卖点外挂状态
        self.chan_bs_state: Dict[str, Dict] = {}
        self.chan_bs_cycle_state: Dict[str, Dict] = {}

        # v2.1: Brooks PA外挂已合并到 Brooks Vision

        # v3.550: SuperTrend+QQE MOD+A-V2外挂状态
        # {symbol: {
        #     "freeze_until": str,           # 冻结截止时间(ISO格式)
        #     "last_signal": str,            # 上次信号 ("BUY"/"SELL")
        #     "last_trigger_time": str,      # 上次触发时间
        #     "buy_used": bool,              # 今日是否已买入
        #     "sell_used": bool,             # 今日是否已卖出
        #     "reset_date": str,             # 重置日期
        # }}
        self.supertrend_av2_state: Dict[str, Dict] = {}
        self.supertrend_av2_cycle_state: Dict[str, Dict] = {}

        # 信号队列
        self.signals: Dict[str, Dict] = {}

        # v20.5: ATR动态阈值 - 重启后首轮强制重算标志
        self._atr_startup_recalculated = False

        # v21.7: 扫描频率优化 — per-symbol上次外挂扫描时间
        self._last_plugin_scan: Dict[str, float] = {}

        # v21.12: 趋势阶段缓存 — per-symbol, 供rhythm/ATR/plugins读取
        self._current_trend_phase: Dict[str, dict] = {}

        # 邮件通知器
        self.email_notifier = EmailNotifier(self.config.get("email", {}))

        # 加载持久化状态 (v21.7: 只加载激活外挂)
        self._load_state()
        self._load_tracking_state()  # v21.27: 只恢复移动止盈止损字段, P0-Tracking仍禁用
        # self._load_scalping_state()  # v21: 剥头皮已禁用
        self._load_supertrend_state()  # ✅ 激活
        self._load_rob_hoffman_state()  # v2.0.1恢复
        self._load_double_pattern_state()  # ✅ Vision形态激活
        # self._load_feiyun_state()  # v21: 飞云已禁用
        self._load_chan_bs_state()  # ✅ 缠论买卖点激活
        # Brooks PA 已合并到 Brooks Vision (brooks_vision.py)
        # self._load_supertrend_av2_state()  # v15.2: 已屏蔽
        self._load_global_trend_cache()  # v3.571: 启动时加载趋势缓存

        # v3.550: 外挂利润追踪器
        if _profit_tracker_available:
            self.profit_tracker = PluginProfitTracker()
            logger.info("[v3.550] 外挂利润追踪器已初始化")
        else:
            self.profit_tracker = None

        # v21.3: 结构性改进模块
        if _modules_available:
            self.stock_selector = StockSelector()
            self.frequency_controller = TradeFrequencyController(enforce=True)  # Phase 2: 拦截模式 (SYS-006)
            self._selection_done_today = ""  # 当天是否已完成评分
            logger.info("[v21.3] 预选+频率控制模块已初始化 (拦截模式)")
        else:
            self.stock_selector = None
            self.frequency_controller = None
            self._selection_done_today = ""

        logger.info("=" * 60)
        logger.info("Price Scan Engine v20.6 初始化 (配合主程序 v3.600)")
        logger.info("-" * 60)
        logger.info("v20.5: 精简外挂 + ATR(14)动态阈值")
        logger.info("  - P0-Tracking: 优先局部拐点，找不到用绝对极值")
        logger.info(f"  - 第一层顺大: x4定方向(DOWN禁BUY/UP禁SELL) + 第二层逆小: EMA{EMA_PERIOD_CRYPTO}(加密)/EMA{EMA_PERIOD_STOCK}(美股)+K线")
        logger.info("  - 立体仓位: check_position_control() (5档)")
        logger.info("  - 冻结: 统一次日NY 8AM")
        logger.info("-" * 60)
        # v20.5: 显示配额规则 (ATR动态阈值)
        unified_threshold = self.config['crypto']['p0_tracking_threshold'] * 100
        logger.info("【配额规则 v20.5】")
        logger.info(f"P0-Tracking: 1买+1卖/天 | 阈值: ±{unified_threshold:.1f}% (加密/美股统一)")
        logger.info(f"  └─ 基准价: 优先局部极值点(拐点)，兜底30根K线绝对极值")
        logger.info(f"移动止盈/止损: 2买+2卖/天 | 第1次ATR(14)动态 + 第2次固定阈值")
        logger.info(f"  └─ 第1次: ATR(14)动态阈值 (纽约8AM刷新)")
        logger.info(f"  └─ 第2次: 固定阈值 美股3.5% / 加密4.0%")
        logger.info("其他外挂: 1买+1卖/天")
        logger.info("-" * 60)
        logger.info("【外挂仓位区间】")
        logger.info("飞云(突破): BUY[0-2] SELL[3-5]")
        logger.info("RobHoffman(回撤): BUY[1-3] SELL[2-4]")
        logger.info("SuperTrend(趋势): BUY[1-3] SELL[2-4]")
        logger.info("缠论BS(买卖点): 无仓位限制")
        logger.info("剥头皮/MACD: 无仓位限制")
        logger.info("-" * 60)
        logger.info(f"加密货币: {self.config['crypto']['symbols']}")
        logger.info(f"美股: {self.config['stock']['symbols']}")
        logger.info("=" * 60)

    def _load_state(self):
        """加载P0-Open状态"""
        state_data = safe_json_read(self.config["state_file"])
        if state_data:
            self.state = state_data.get("symbols", {})
            logger.info(f"加载P0-Open状态: {len(self.state)} 个品种")

    def _load_tracking_state(self):
        """v21.27: 选择性加载 — 只恢复移动止盈/止损字段, P0-Tracking不加载"""
        _TRAILING_KEYS = {
            "trailing_stop_count", "trailing_buy_count",
            "trailing_high", "trailing_low", "trailing_reset_date",
            "atr_cache_until", "atr_cache_value",
            "last_position",
            "bar_freeze_dir", "bar_freeze_count", "bar_freeze_bar_start",
            "last_volume", "avg_volume",
        }
        state_data = safe_json_read(self.config["tracking_state_file"])
        if not state_data:
            return
        saved = state_data.get("symbols", {})
        restored = 0
        for sym, st in saved.items():
            stop_cnt = st.get("trailing_stop_count", 0)
            buy_cnt = st.get("trailing_buy_count", 0)
            high = st.get("trailing_high")
            low = st.get("trailing_low")
            if stop_cnt or buy_cnt or high or low:
                # 只注入trailing相关字段到tracking_state
                if sym not in self.tracking_state:
                    self.tracking_state[sym] = {}
                for k in _TRAILING_KEYS:
                    if k in st:
                        self.tracking_state[sym][k] = st[k]
                restored += 1
                logger.info(f"[{sym}] 移动止损恢复: 止损[{stop_cnt}/2]止盈[{buy_cnt}/2] "
                            f"high={high} low={low}")
        if restored:
            logger.info(f"v21.27 移动止损状态恢复: {restored}/{len(saved)} 个品种")

    def _save_state(self):
        """保存P0-Open状态"""
        data = {
            "symbols": self.state,
            "updated_at": datetime.now().isoformat(),
        }
        safe_json_write(self.config["state_file"], data)

    def _save_tracking_state(self):
        """保存P0-Tracking状态"""
        data = {
            "symbols": self.tracking_state,
            "updated_at": datetime.now().isoformat(),
        }
        safe_json_write(self.config["tracking_state_file"], data)

    def _load_scalping_state(self):
        """v12.0: 加载Chandelier+ZLSMA剥头皮状态"""
        state_file = self.config.get("scalping_state_file", "scalping_state.json")
        state_data = safe_json_read(state_file)
        if state_data:
            self.scalping_state = state_data.get("symbols", {})
            # v12.4: 加载全局状态
            if "global" in state_data:
                self.scalping_global = state_data["global"]
            # v3.551fix: 不再启动清零计数，由_reset_scalping_daily_count_if_needed()运行时处理
            for sym, st in self.scalping_state.items():
                buy_cnt = st.get("daily_buy_count", 0)
                sell_cnt = st.get("daily_sell_count", 0)
                if buy_cnt > 0 or sell_cnt > 0:
                    logger.info(f"[{sym}] 剥头皮恢复计数: BUY={buy_cnt}, SELL={sell_cnt}, 日期={st.get('daily_reset_date', '?')}")
            if self.scalping_global.get("global_frozen_until"):
                logger.info(f"  剥头皮恢复全局冻结: {self.scalping_global['global_frozen_until']}")
            logger.info(f"加载剥头皮状态: {len(self.scalping_state)} 个品种")

    def _save_scalping_state(self):
        """v12.0: 保存Chandelier+ZLSMA剥头皮状态"""
        state_file = self.config.get("scalping_state_file", "scalping_state.json")
        data = {
            "symbols": self.scalping_state,
            "global": self.scalping_global,  # v12.4: 保存全局状态
            "updated_at": datetime.now().isoformat(),
        }
        safe_json_write(state_file, data)

    def _load_supertrend_state(self):
        """v15.2fix: 加载SuperTrend外挂状态 (补缺)"""
        state_file = self.config.get("supertrend_state_file", "scan_supertrend_state.json")
        state_data = safe_json_read(state_file)
        if state_data:
            self.supertrend_state = state_data.get("symbols", {})
            # v3.551fix: 不再启动清零，由check_plugin_daily_limit()运行时处理
            for sym, st in self.supertrend_state.items():
                if st.get("buy_used") or st.get("sell_used"):
                    logger.info(f"[{sym}] SuperTrend恢复配额: 买[{'✓' if st.get('buy_used') else '○'}] 卖[{'✓' if st.get('sell_used') else '○'}] 冻结={st.get('freeze_until', '无')}")
            logger.info(f"加载SuperTrend状态: {len(self.supertrend_state)} 个品种")

    def _save_supertrend_state(self):
        """v3.530: 保存SuperTrend外挂状态"""
        state_file = self.config.get("supertrend_state_file", "scan_supertrend_state.json")
        data = {
            "symbols": self.supertrend_state,
            "updated_at": datetime.now().isoformat(),
        }
        safe_json_write(state_file, data)

    # ========== v15.1: 新增外挂状态持久化 (重启安全) ==========

    def _load_rob_hoffman_state(self):
        """v15.1: 加载Rob Hoffman外挂状态 (重启恢复)"""
        state_file = self.config.get("rob_hoffman_state_file", "scan_rob_hoffman_state.json")
        state_data = safe_json_read(state_file)
        if state_data:
            self.rob_hoffman_state = state_data.get("symbols", {})
            # v3.551fix: 不再启动清零，由check_plugin_daily_limit()运行时处理
            for sym, st in self.rob_hoffman_state.items():
                if st.get("buy_used") or st.get("sell_used"):
                    logger.info(f"[{sym}] Rob Hoffman恢复配额: 买[{'✓' if st.get('buy_used') else '○'}] 卖[{'✓' if st.get('sell_used') else '○'}] 冻结={st.get('freeze_until', '无')}")
            logger.info(f"[v15.1] 加载Rob Hoffman状态: {len(self.rob_hoffman_state)} 个品种")

    def _save_rob_hoffman_state(self):
        """v15.1: 保存Rob Hoffman外挂状态"""
        state_file = self.config.get("rob_hoffman_state_file", "scan_rob_hoffman_state.json")
        data = {
            "symbols": self.rob_hoffman_state,
            "updated_at": datetime.now().isoformat(),
        }
        safe_json_write(state_file, data)

    def _load_double_pattern_state(self):
        """v15.1: 加载双底双顶外挂状态 (重启恢复)"""
        state_file = self.config.get("double_pattern_state_file", "scan_double_pattern_state.json")
        state_data = safe_json_read(state_file)
        if state_data:
            self.double_pattern_state = state_data.get("symbols", {})
            # v3.551fix: 不再启动清零，由check_plugin_daily_limit()运行时处理
            for sym, st in self.double_pattern_state.items():
                if st.get("buy_used") or st.get("sell_used"):
                    logger.info(f"[{sym}] 双底双顶恢复配额: 买[{'✓' if st.get('buy_used') else '○'}] 卖[{'✓' if st.get('sell_used') else '○'}] 冻结={st.get('freeze_until', '无')}")
            logger.info(f"[v15.1] 加载双底双顶状态: {len(self.double_pattern_state)} 个品种")

    def _save_double_pattern_state(self):
        """v15.1: 保存双底双顶外挂状态"""
        state_file = self.config.get("double_pattern_state_file", "scan_double_pattern_state.json")
        data = {
            "symbols": self.double_pattern_state,
            "updated_at": datetime.now().isoformat(),
        }
        safe_json_write(state_file, data)

    def _load_feiyun_state(self):
        """v15.1: 加载飞云外挂状态 (重启恢复)"""
        state_file = self.config.get("feiyun_state_file", "scan_feiyun_state.json")
        state_data = safe_json_read(state_file)
        if state_data:
            self.feiyun_state = state_data.get("symbols", {})
            # v3.551fix: 不再启动清零，由check_plugin_daily_limit()运行时处理
            for sym, st in self.feiyun_state.items():
                if st.get("buy_used") or st.get("sell_used"):
                    logger.info(f"[{sym}] 飞云恢复配额: 买[{'✓' if st.get('buy_used') else '○'}] 卖[{'✓' if st.get('sell_used') else '○'}] 冻结={st.get('freeze_until', '无')}")
            logger.info(f"[v15.1] 加载飞云状态: {len(self.feiyun_state)} 个品种")

    def _save_feiyun_state(self):
        """v15.1: 保存飞云外挂状态"""
        state_file = self.config.get("feiyun_state_file", "scan_feiyun_state.json")
        data = {
            "symbols": self.feiyun_state,
            "updated_at": datetime.now().isoformat(),
        }
        safe_json_write(state_file, data)

    # v21.16: _load/_save_macd_divergence_state 已删除 (扫描引擎MACD移除)

    def _load_chan_bs_state(self):
        """v21.1: 加载缠论买卖点外挂状态 (重启恢复)"""
        state_file = self.config.get("chan_bs_state_file", "scan_chan_bs_state.json")
        state_data = safe_json_read(state_file)
        if state_data:
            self.chan_bs_state = state_data.get("symbols", {})
            for sym, st in self.chan_bs_state.items():
                if st.get("buy_used") or st.get("sell_used"):
                    logger.info(f"[{sym}] 缠论BS恢复配额: 买[{'✓' if st.get('buy_used') else '○'}] 卖[{'✓' if st.get('sell_used') else '○'}] 冻结={st.get('freeze_until', '无')}")
            logger.info(f"[v21.1] 加载缠论BS状态: {len(self.chan_bs_state)} 个品种")

    def _save_chan_bs_state(self):
        """v21.1: 保存缠论买卖点外挂状态"""
        state_file = self.config.get("chan_bs_state_file", "scan_chan_bs_state.json")
        data = {
            "symbols": self.chan_bs_state,
            "updated_at": datetime.now().isoformat(),
        }
        safe_json_write(state_file, data)

    # _load_brooks_pa_state / _save_brooks_pa_state: 已删除 (合并到 Brooks Vision)

    def _load_supertrend_av2_state(self):
        """v3.550: 加载SuperTrend+AV2外挂状态 (重启恢复)"""
        state_file = self.config.get("supertrend_av2_state_file", "scan_supertrend_av2_state.json")
        state_data = safe_json_read(state_file)
        if state_data:
            self.supertrend_av2_state = state_data.get("symbols", {})
            # v3.551fix: 不再启动清零，由check_plugin_daily_limit()运行时处理
            for sym, st in self.supertrend_av2_state.items():
                if st.get("buy_used") or st.get("sell_used"):
                    logger.info(f"[{sym}] SuperTrend+AV2恢复配额: 买[{'✓' if st.get('buy_used') else '○'}] 卖[{'✓' if st.get('sell_used') else '○'}] 冻结={st.get('freeze_until', '无')}")
            logger.info(f"[v3.550] 加载SuperTrend+AV2状态: {len(self.supertrend_av2_state)} 个品种")

    def _save_supertrend_av2_state(self):
        """v3.550: 保存SuperTrend+AV2外挂状态"""
        state_file = self.config.get("supertrend_av2_state_file", "scan_supertrend_av2_state.json")
        data = {
            "symbols": self.supertrend_av2_state,
            "updated_at": datetime.now().isoformat(),
        }
        safe_json_write(state_file, data)

    # ========== v21.17: N字门控状态读取 (5min缓存) ==========

    def _load_n_gate_state(self) -> dict:
        """v21.17: 读取主程序持久化的N字门控状态 (5min缓存)"""
        now = time.time()
        if hasattr(self, '_n_gate_cache_ts') and now - self._n_gate_cache_ts < 300:
            return getattr(self, '_n_gate_cache', {})
        try:
            with open("state/n_gate_active.json", "r") as f:
                self._n_gate_cache = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, Exception):
            self._n_gate_cache = {}
        self._n_gate_cache_ts = now
        return self._n_gate_cache

    # ========== v3.571: 启动时加载趋势缓存 ==========

    def _load_global_trend_cache(self):
        """
        v3.572: 启动时从global_trend_state.json加载趋势数据到内存缓存

        解决问题: 扫描引擎先于主程序启动时，内存缓存为空，
        外挂读取不到趋势数据，只能用默认值。

        此函数在启动时从文件加载，确保即使主程序未启动也能使用上次的趋势数据。
        """
        global _global_trend_cache

        state = safe_json_read(GLOBAL_TREND_STATE_FILE)
        if not state:
            logger.info("[v3.572] global_trend_state.json不存在或为空，趋势缓存未加载")
            return

        symbols_data = state.get("symbols", {})
        loaded_count = 0

        with _global_trend_lock:
            for symbol, sym_data in symbols_data.items():
                if not sym_data:
                    continue
                _global_trend_cache[symbol] = {
                    "trend": sym_data.get("big_trend", "SIDE"),
                    "regime": sym_data.get("regime", "RANGING"),
                    "current_trend": sym_data.get("current_trend", sym_data.get("big_trend", "SIDE")),
                    "trend_x4": sym_data.get("trend_x4", "SIDE"),  # v3.571: x4趋势
                    "current_regime": sym_data.get("current_regime", "UNKNOWN"),  # v3.572: 当前震荡/趋势
                    "regime_x4": sym_data.get("regime_x4", "UNKNOWN"),  # v3.572: x4震荡/趋势
                    "update_time": sym_data.get("change_time", ""),
                    "reason": sym_data.get("change_reason", "启动加载"),
                }
                loaded_count += 1

        logger.info(f"[v3.572] 启动加载趋势缓存: {loaded_count} 个品种 (来自global_trend_state.json)")
        # 打印几个样本
        if loaded_count > 0:
            samples = list(_global_trend_cache.items())[:3]
            for sym, data in samples:
                logger.info(f"  └─ {sym}: 当前={data.get('current_trend')}({data.get('current_regime')}) x4={data.get('trend_x4')}({data.get('regime_x4')})")

    # ========== v12.4: 剥头皮利润目标管理 ==========

    def _generate_daily_scalping_target(self) -> float:
        """v12.4: 生成每日剥头皮利润目标 (0.3%-0.4%)"""
        import random
        from zoneinfo import ZoneInfo

        ny_now = datetime.now(ZoneInfo("America/New_York"))
        today_str = ny_now.strftime("%Y-%m-%d")

        # 检查是否需要生成新目标
        if self.scalping_global.get("target_generated_date") == today_str:
            return self.scalping_global.get("daily_target_rate", 0.0035)

        # 生成新的每日目标 (0.3%-0.4%)
        target_rate = random.uniform(0.003, 0.004)
        self.scalping_global["daily_target_rate"] = target_rate
        self.scalping_global["target_generated_date"] = today_str

        logger.info(f"[v12.4] 生成每日剥头皮目标: {target_rate:.2%}")
        self._save_scalping_state()
        return target_rate

    def _check_scalping_global_frozen(self) -> tuple:
        """v12.4: 检查剥头皮是否全局冻结 (达到目标后)"""
        from zoneinfo import ZoneInfo

        frozen_until = self.scalping_global.get("global_frozen_until")
        if not frozen_until:
            return False, None

        # 解析冻结时间
        try:
            if isinstance(frozen_until, str):
                frozen_dt = datetime.fromisoformat(frozen_until)
            else:
                frozen_dt = frozen_until
        except Exception:  # v16 P2-2
            return False, None

        ny_now = datetime.now(ZoneInfo("America/New_York"))
        if ny_now.tzinfo is None:
            ny_now = ny_now.replace(tzinfo=ZoneInfo("America/New_York"))
        if frozen_dt.tzinfo is None:
            frozen_dt = frozen_dt.replace(tzinfo=ZoneInfo("America/New_York"))

        if ny_now < frozen_dt:
            return True, frozen_dt.strftime("%Y-%m-%d %H:%M")
        else:
            # 已解冻，重置状态
            self._reset_scalping_daily_state()
            return False, None

    def _reset_scalping_daily_state(self):
        """v12.4: 重置剥头皮每日状态 (解冻时调用)"""
        logger.info("[v12.4] 剥头皮解冻，重置每日状态")

        # 重置全局状态
        self.scalping_global["global_frozen_until"] = None
        self.scalping_global["daily_target_rate"] = 0.0
        self.scalping_global["target_generated_date"] = ""

        # v14.2: 重置强制清盘标记
        self.scalping_global["force_liquidate_755am"] = False
        self.scalping_global["liquidate_reason"] = ""
        self.scalping_global["liquidate_executed"] = False
        self.scalping_global["liquidate_time"] = ""

        # 重置各币种的累计数据
        for symbol in self.scalping_state:
            self.scalping_state[symbol]["total_cost"] = 0.0
            self.scalping_state[symbol]["total_revenue"] = 0.0
            self.scalping_state[symbol]["rounds_completed"] = 0
            self.scalping_state[symbol]["in_round"] = False

        self._save_scalping_state()

    def _on_scalping_buy(self, symbol: str, price: float, quantity: float = 1.0):
        """v12.4: 记录剥头皮买入"""
        if symbol not in self.scalping_state:
            self.scalping_state[symbol] = {}

        state = self.scalping_state[symbol]
        cost = price * quantity
        state["total_cost"] = state.get("total_cost", 0.0) + cost
        state["in_round"] = True
        state["last_entry_price"] = price

        logger.info(f"[v12.4] {symbol} 剥头皮买入: 价格={price:.4f}, 累计成本={state['total_cost']:.2f}")
        self._save_scalping_state()

    def _on_scalping_sell(self, symbol: str, price: float, quantity: float = 1.0) -> dict:
        """
        v12.4: 记录剥头皮卖出，检查利润目标
        v14.2: 第3次卖出特殊规则 - 有利润就清仓，避免亏损
        """
        if symbol not in self.scalping_state:
            self.scalping_state[symbol] = {}

        state = self.scalping_state[symbol]
        revenue = price * quantity
        state["total_revenue"] = state.get("total_revenue", 0.0) + revenue
        state["rounds_completed"] = state.get("rounds_completed", 0) + 1
        state["in_round"] = False

        # 计算利润率
        total_cost = state.get("total_cost", 0.0)
        total_revenue = state.get("total_revenue", 0.0)
        pnl_rate = (total_revenue - total_cost) / total_cost if total_cost > 0 else 0

        # v14.2: 获取当前卖出次数 (包括这次)
        sell_count = state.get("daily_sell_count", 0) + 1  # +1 因为计数还没更新

        logger.info(f"[v14.2] {symbol} 剥头皮卖出(第{sell_count}次): 价格={price:.4f}, 累计收入={total_revenue:.2f}, 利润率={pnl_rate:.2%}")

        # 检查是否达到目标
        target_rate = self.scalping_global.get("daily_target_rate", 0.0035)
        result = {
            "pnl_rate": pnl_rate,
            "target_rate": target_rate,
            "target_reached": False,
            "should_freeze": False,
            "sell_count": sell_count,
        }

        # v14.2: 清仓规则
        # 规则1: 任何时候达到目标利润率 → 清仓锁利润
        if pnl_rate >= target_rate:
            result["target_reached"] = True
            result["should_freeze"] = True
            result["reason"] = f"🎯 目标达成 {pnl_rate:.2%} >= {target_rate:.2%} (第{sell_count}次)"
            logger.info(f"[v14.2] 🎯 {symbol} 剥头皮目标达成! {result['reason']}")

        # 规则2: 第3次卖出，未达目标但有利润 → 也清仓锁利润，避免亏损
        elif sell_count >= 3 and pnl_rate > 0:
            result["target_reached"] = False
            result["should_freeze"] = True
            result["reason"] = f"💰 第3次有利润清仓 {pnl_rate:.2%} > 0 (未达目标{target_rate:.2%})"
            logger.info(f"[v14.2] 💰 {symbol} 第3次有利润清仓! {result['reason']}")

        # 规则3: 第3次卖出，亏损 → 标记7:55 AM强制清盘
        elif sell_count >= 3 and pnl_rate <= 0:
            result["target_reached"] = False
            result["should_freeze"] = True  # 也冻结，停止交易
            result["force_liquidate_755am"] = True  # 标记需要7:55清盘
            result["reason"] = f"⚠️ 第3次亏损 {pnl_rate:.2%}，将在7:55AM清盘"
            logger.info(f"[v14.2] ⚠️ {symbol} 第3次亏损，标记7:55AM强制清盘! {result['reason']}")
            # 记录到全局状态
            self.scalping_global["force_liquidate_755am"] = True
            self.scalping_global["liquidate_reason"] = f"第3次亏损 {pnl_rate:.2%}"

        self._save_scalping_state()
        return result

    def _freeze_scalping_until_tomorrow(self, reason: str = "目标达成"):
        """v12.4: 冻结剥头皮到次日8AM纽约时间"""
        ny_now = get_ny_now()
        tomorrow_8am = get_next_8am_ny()
        self.scalping_global["global_frozen_until"] = tomorrow_8am.isoformat()

        logger.info(f"[v12.4] 剥头皮全局冻结至 {tomorrow_8am.strftime('%Y-%m-%d %H:%M')} NY ({reason})")
        self._save_scalping_state()

        # 发送邮件通知
        pnl_rate = 0
        for sym, state in self.scalping_state.items():
            cost = state.get("total_cost", 0)
            rev = state.get("total_revenue", 0)
            if cost > 0:
                pnl_rate = (rev - cost) / cost

        email_subject = f"🎯 剥头皮目标达成 | 利润 {pnl_rate:.2%}"
        email_body = f"""
========================================
🎯 剥头皮每日目标达成
========================================

时间: {ny_now.strftime('%Y-%m-%d %H:%M:%S')} (纽约时间)
原因: {reason}
利润率: {pnl_rate:.2%}
目标: {self.scalping_global.get('daily_target_rate', 0):.2%}

冻结至: {tomorrow_8am.strftime('%Y-%m-%d %H:%M')} (纽约时间)

========================================
"""
        self.email_notifier.send_signal_notification(email_subject, email_body)

    def _get_scalping_pnl_rate(self) -> float:
        """v12.4: 计算当前剥头皮总利润率"""
        total_cost = 0.0
        total_revenue = 0.0
        for sym, state in self.scalping_state.items():
            total_cost += state.get("total_cost", 0.0)
            total_revenue += state.get("total_revenue", 0.0)

        if total_cost > 0:
            return (total_revenue - total_cost) / total_cost
        return 0.0

    def _check_755am_force_liquidate(self):
        """
        v14.2: 检查7:55 AM纽约时间强制清盘
        如果第3次卖出后亏损，在7:55 AM强制清盘所有剥头皮持仓
        """
        # 检查是否有强制清盘标记
        if not self.scalping_global.get("force_liquidate_755am", False):
            return

        # 检查是否已执行过清盘
        if self.scalping_global.get("liquidate_executed", False):
            return

        ny_now = get_ny_now()

        # 检查是否在7:55-7:59 AM纽约时间
        if ny_now.hour == 7 and 55 <= ny_now.minute <= 59:
            logger.info(f"[v14.2] ⚠️ 7:55 AM纽约时间到达，执行强制清盘!")

            liquidate_reason = self.scalping_global.get("liquidate_reason", "第3次亏损")
            pnl_rate = self._get_scalping_pnl_rate()

            # 发送强制清盘通知邮件
            email_subject = f"⚠️ 剥头皮强制清盘 | 亏损 {pnl_rate:.2%}"
            email_body = f"""
========================================
⚠️ 剥头皮7:55AM强制清盘
========================================

时间: {ny_now.strftime('%Y-%m-%d %H:%M:%S')} (纽约时间)

原因: {liquidate_reason}
累计利润率: {pnl_rate:.2%}

说明: 第3次买卖未能达到利润目标且整体亏损
执行强制清盘以限制损失

冻结至: 次日8AM

========================================
"""
            self.email_notifier.send_signal_notification(email_subject, email_body)

            # 标记已执行，避免重复
            self.scalping_global["liquidate_executed"] = True
            self.scalping_global["liquidate_time"] = ny_now.isoformat()

            # 冻结到次日8AM
            self._freeze_scalping_until_tomorrow(f"7:55AM强制清盘 ({liquidate_reason})")

            logger.info(f"[v14.2] ⚠️ 强制清盘完成，冻结到次日8AM")
            self._save_scalping_state()

    def _generate_scalping_daily_report(self, reset_date: str):
        """
        v14.1: 生成剥头皮每日统计报告
        在纽约时间早上8点重置前调用，保存到 剥头皮/ 目录
        """
        import os
        from datetime import datetime

        # 创建目录
        report_dir = os.path.join(os.path.dirname(__file__), "剥头皮")
        os.makedirs(report_dir, exist_ok=True)

        # 统计数据
        total_cost = 0.0
        total_revenue = 0.0
        total_buy_count = 0
        total_sell_count = 0
        symbol_stats = []

        for symbol, state in self.scalping_state.items():
            cost = state.get("total_cost", 0.0)
            revenue = state.get("total_revenue", 0.0)
            buy_count = state.get("daily_buy_count", 0)
            sell_count = state.get("daily_sell_count", 0)
            rounds = state.get("rounds_completed", 0)

            if cost > 0 or revenue > 0 or buy_count > 0 or sell_count > 0:
                pnl = revenue - cost
                pnl_rate = (pnl / cost * 100) if cost > 0 else 0
                symbol_stats.append({
                    "symbol": symbol,
                    "cost": cost,
                    "revenue": revenue,
                    "pnl": pnl,
                    "pnl_rate": pnl_rate,
                    "buy_count": buy_count,
                    "sell_count": sell_count,
                    "rounds": rounds
                })
                total_cost += cost
                total_revenue += revenue
                total_buy_count += buy_count
                total_sell_count += sell_count

        total_pnl = total_revenue - total_cost
        total_pnl_rate = (total_pnl / total_cost * 100) if total_cost > 0 else 0

        # 生成报告
        ny_now = get_ny_now()
        report_lines = [
            "=" * 60,
            f"剥头皮每日统计报告",
            "=" * 60,
            f"统计日期: {reset_date}",
            f"生成时间: {ny_now.strftime('%Y-%m-%d %H:%M:%S')} (纽约时间)",
            "",
            "-" * 60,
            "汇总",
            "-" * 60,
            f"总成本:     ${total_cost:,.2f}",
            f"总收入:     ${total_revenue:,.2f}",
            f"总盈亏:     ${total_pnl:,.2f}",
            f"收益率:     {total_pnl_rate:+.2f}%",
            f"总买入次数: {total_buy_count}",
            f"总卖出次数: {total_sell_count}",
            "",
            "-" * 60,
            "各币种明细",
            "-" * 60,
        ]

        if symbol_stats:
            for s in symbol_stats:
                report_lines.append(f"\n{s['symbol']}:")
                report_lines.append(f"  成本: ${s['cost']:,.2f} | 收入: ${s['revenue']:,.2f}")
                report_lines.append(f"  盈亏: ${s['pnl']:,.2f} ({s['pnl_rate']:+.2f}%)")
                report_lines.append(f"  买入: {s['buy_count']}次 | 卖出: {s['sell_count']}次 | 完成轮次: {s['rounds']}")
        else:
            report_lines.append("今日无交易记录")

        report_lines.append("")
        report_lines.append("=" * 60)

        # 保存报告
        report_filename = f"scalping_{reset_date}.txt"
        report_path = os.path.join(report_dir, report_filename)

        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(report_lines))

        logger.info(f"[v14.1] 剥头皮每日报告已生成: {report_path}")

        # 同时保存JSON格式
        json_filename = f"scalping_{reset_date}.json"
        json_path = os.path.join(report_dir, json_filename)
        json_data = {
            "date": reset_date,
            "generated_at": ny_now.isoformat(),
            "summary": {
                "total_cost": total_cost,
                "total_revenue": total_revenue,
                "total_pnl": total_pnl,
                "total_pnl_rate": total_pnl_rate,
                "total_buy_count": total_buy_count,
                "total_sell_count": total_sell_count
            },
            "symbols": symbol_stats
        }
        safe_json_write(json_path, json_data)

        return report_path

    # ========== v12.4 END ==========

    def _save_signals(self):
        """保存信号供主程序读取"""
        data = {
            "signals": self.signals,
            "tracking_state": self.tracking_state,
            "updated_at": datetime.now().isoformat(),
            "engine_status": "running" if self.running else "stopped",
        }
        safe_json_write(self.config["signal_file"], data)

    def _update_heartbeat(self):
        """更新心跳"""
        data = {
            "timestamp": datetime.now().isoformat(),
            "status": "alive",
            "symbols_monitored": len(self.state),
            "tracking_symbols": len(self.tracking_state),
            "version": "11.3.1",
            "startup_cooldown_remaining": max(0, self.STARTUP_COOLDOWN_SECONDS - (time.time() - self.startup_time)),
        }
        safe_json_write(self.config["heartbeat_file"], data)

    def _is_in_startup_cooldown(self) -> bool:
        """
        v11.0: 检查是否在启动冷却期内

        Returns:
            True: 在冷却期内，不应触发信号
            False: 冷却期已过，可以正常触发
        """
        elapsed = time.time() - self.startup_time
        return elapsed < self.STARTUP_COOLDOWN_SECONDS

    def _is_in_market_open_cooldown(self, symbol: str) -> bool:
        """
        v11.2: 检查美股是否在开盘缓冲期内

        开盘缓冲期: 9:30-9:40 NY
        在此期间不触发信号，让价格稳定后再开始追踪

        Returns:
            True: 在开盘缓冲期内，不应触发信号
            False: 缓冲期已过或不适用
        """
        if not is_us_stock(symbol):
            return False

        cooldown_until = self.tracking_state.get(symbol, {}).get("market_open_cooldown_until")
        if not cooldown_until:
            return False

        try:
            cooldown_dt = datetime.fromisoformat(cooldown_until)
            # 确保时区一致
            if cooldown_dt.tzinfo is None:
                cooldown_dt = NY_TZ.localize(cooldown_dt)

            ny_now = get_ny_now()
            if ny_now < cooldown_dt:
                return True
            else:
                # 缓冲期已过，清除标记
                self.tracking_state[symbol]["market_open_cooldown_until"] = None
                return False
        except Exception as e:
            logger.warning(f"[{symbol}] 解析开盘缓冲期失败: {e}")
            return False

    def _should_activate_plugins(self, symbol: str) -> tuple:
        """
        v11.0: 读取L1趋势状态和飞云外挂状态，判断是否激活外挂

        注意: P0-Tracking一直运行，此函数只判断外挂是否激活

        读取主程序state.json中的:
        - l1_trend_for_scan: L1趋势状态
        - feiyun_plugin_for_scan: 飞云双突破外挂状态

        L1外挂激活条件:
        - consensus=AGREE/DEEPSEEK_ARBITER 且 direction=UP/DOWN → 激活L1外挂

        飞云外挂激活条件:
        - is_double=True 且 L1趋势方向一致 → 激活飞云外挂

        Returns:
            (should_activate_l1: bool, scan_direction: str or None, should_activate_feiyun: bool, feiyun_signal: str or None)
        """
        state_file = self.config["tracking"]["state_file"]
        state_data = safe_json_read(state_file)

        # P0-Tracking一直运行，只是外挂不激活
        if not state_data:
            logger.debug(f"[{symbol}] state.json不存在，外挂不激活(P0继续)")
            return (False, None, False, None)

        # 获取symbol对应的state (支持BTCUSDC和BTC-USD两种格式)
        main_symbol = REVERSE_SYMBOL_MAP.get(symbol, symbol)
        symbol_state = state_data.get(main_symbol) or state_data.get(symbol)

        if not symbol_state:
            logger.debug(f"[{symbol}] 未找到symbol状态，外挂不激活(P0继续)")
            return (False, None, False, None)

        # 读取L1趋势状态
        l1_trend = symbol_state.get("l1_trend_for_scan", {})
        if not l1_trend:
            logger.debug(f"[{symbol}] 未找到l1_trend_for_scan，外挂不激活(P0继续)")
            return (False, None, False, None)

        direction = l1_trend.get("direction", "SIDE")
        consensus = l1_trend.get("consensus", "DISAGREE")

        # L1外挂激活判断
        should_activate_l1 = False
        scan_direction = None

        if consensus in ("AGREE", "DEEPSEEK_ARBITER"):
            if direction == "UP":
                should_activate_l1 = True
                scan_direction = "BUY_ONLY"
            elif direction == "DOWN":
                should_activate_l1 = True
                scan_direction = "SELL_ONLY"

        # v11.0: 读取飞云外挂状态
        feiyun_state = symbol_state.get("feiyun_plugin_for_scan", {})
        should_activate_feiyun = feiyun_state.get("activate_feiyun_plugin", False)
        feiyun_signal = feiyun_state.get("signal", "NONE") if should_activate_feiyun else None

        # 日志: 外挂状态(P0一直运行)
        if not should_activate_l1 and not should_activate_feiyun:
            if direction == "SIDE":
                logger.debug(f"[{symbol}] L1=SIDE，外挂不激活(P0继续)")
            elif consensus not in ("AGREE", "DEEPSEEK_ARBITER"):
                logger.debug(f"[{symbol}] consensus={consensus}，外挂不激活(P0继续)")

        return (should_activate_l1, scan_direction, should_activate_feiyun, feiyun_signal)

    def _get_current_trend(self, symbol: str) -> str:
        """
        v11.3: 从主程序state.json读取当前周期趋势(current_trend)

        用于P0-Open条件判断:
        - current_trend = UP → 允许P0-Open触发
        - current_trend = DOWN → 允许P0-Open触发
        - current_trend = SIDE → 不触发P0-Open (震荡市)

        v11.3.1修复: l1_trend_for_scan中没有current_trend字段，
        需要从_last_final_decision.three_way_signals.market_regime读取

        Returns:
            "UP" / "DOWN" / "SIDE"
        """
        state_file = self.config["tracking"]["state_file"]
        state_data = safe_json_read(state_file)

        if not state_data:
            logger.debug(f"[{symbol}] state.json不存在，返回SIDE")
            return "SIDE"

        # 获取symbol对应的state (支持BTCUSDC和BTC-USD两种格式)
        main_symbol = REVERSE_SYMBOL_MAP.get(symbol, symbol)
        symbol_state = state_data.get(main_symbol) or state_data.get(symbol)

        if not symbol_state:
            logger.debug(f"[{symbol}] 未找到symbol状态，返回SIDE")
            return "SIDE"

        # v11.3.1修复: 优先从_last_final_decision.market_regime读取current_trend
        # 因为l1_trend_for_scan中没有current_trend字段，只有direction(大周期趋势)
        final_decision = symbol_state.get("_last_final_decision", {})
        three_way = final_decision.get("three_way_signals", {})
        market_regime = three_way.get("market_regime", {})
        if isinstance(market_regime, dict):
            current_trend = market_regime.get("current_trend", "")
            if current_trend in ("UP", "DOWN", "SIDE"):
                return current_trend

        # 备选: 从l1_trend_for_scan读取direction (大周期趋势方向)
        # 注意: direction是big_trend(x4大周期)，不是current_trend(当前周期)
        # 如果没有market_regime，用direction作为备选
        l1_trend = symbol_state.get("l1_trend_for_scan", {})
        if l1_trend:
            direction = l1_trend.get("direction", "SIDE")
            if direction in ("UP", "DOWN", "SIDE"):
                logger.debug(f"[{symbol}] 使用l1_trend_for_scan.direction={direction}作为备选")
                return direction

        return "SIDE"

    def _get_trend_for_plugin(self, symbol: str) -> dict:
        """
        v3.540: 获取外挂使用的趋势状态
        v3.571: 新增trend_x4字段，供顺大逆小策略使用

        优先级:
        1. 内存缓存 _global_trend_cache (最新，来自HTTP更新)
        2. global_trend_state.json (持久化)
        3. state.json (原有逻辑，通过_get_current_trend)

        Args:
            symbol: 交易品种 (yfinance格式，如BTC-USD)

        Returns:
            dict: {
                "trend": "UP"/"DOWN"/"SIDE",          # 当前周期趋势
                "regime": "TRENDING"/"RANGING",
                "trend_x4": "UP"/"DOWN"/"SIDE",       # v3.571: x4大周期道氏趋势
                "current_regime": "TRENDING"/"RANGING"/"UNKNOWN",  # v3.572: 当前周期震荡/趋势
                "regime_x4": "TRENDING"/"RANGING"/"UNKNOWN",       # v3.572: x4周期震荡/趋势
                "source": "memory_cache"/"global_trend_state"/"state_json"
            }
        """
        # 转换为主程序格式 (yfinance -> 主程序)
        main_symbol = REVERSE_SYMBOL_MAP.get(symbol, symbol)

        # 1. 优先使用内存缓存 (来自主程序HTTP更新，最快响应)
        with _global_trend_lock:
            if main_symbol in _global_trend_cache:
                cache = _global_trend_cache[main_symbol]
                # v16 P2-6: 趋势缓存30分钟TTL
                update_time_str = cache.get("update_time")
                if update_time_str:
                    try:
                        update_dt = datetime.fromisoformat(update_time_str)
                        age = (datetime.now() - update_dt).total_seconds()
                        if age > 1800:  # 30 min TTL
                            logger.warning(f"[v16] {symbol} 趋势缓存过期({age/60:.0f}min)，降级到文件")
                        else:
                            trend = cache.get("trend", "SIDE")
                            regime = cache.get("regime", "RANGING")
                            trend_x4 = cache.get("trend_x4", "SIDE")  # v3.571
                            current_regime = cache.get("current_regime", "UNKNOWN")  # v3.572
                            regime_x4 = cache.get("regime_x4", "UNKNOWN")  # v3.572
                            logger.debug(f"[v3.572] {symbol} 趋势来自内存缓存: 当前={trend} x4={trend_x4} ({regime}) 当前震荡={current_regime} x4震荡={regime_x4}")
                            return {
                                "trend": trend,
                                "regime": regime,
                                "trend_x4": trend_x4,  # v3.571
                                "current_regime": current_regime,  # v3.572
                                "regime_x4": regime_x4,  # v3.572
                                "l2_recommendation": cache.get("l2_recommendation", "HOLD"),  # v21
                                "source": "memory_cache"
                            }
                    except Exception:
                        pass  # 解析失败，降级到文件
                else:
                    trend = cache.get("trend", "SIDE")
                    regime = cache.get("regime", "RANGING")
                    trend_x4 = cache.get("trend_x4", "SIDE")  # v3.571
                    current_regime = cache.get("current_regime", "UNKNOWN")  # v3.572
                    regime_x4 = cache.get("regime_x4", "UNKNOWN")  # v3.572
                    logger.debug(f"[v3.572] {symbol} 趋势来自内存缓存(无时间戳): 当前={trend} x4={trend_x4} ({regime}) 当前震荡={current_regime} x4震荡={regime_x4}")
                    return {
                        "trend": trend,
                        "regime": regime,
                        "trend_x4": trend_x4,  # v3.571
                        "current_regime": current_regime,  # v3.572
                        "regime_x4": regime_x4,  # v3.572
                        "l2_recommendation": cache.get("l2_recommendation", "HOLD"),  # v21
                        "source": "memory_cache"
                    }

        # 2. v16 P2-9: 使用safe_json_read替代bare open()
        state = safe_json_read(GLOBAL_TREND_STATE_FILE)
        if state:
            sym_state = state.get("symbols", {}).get(main_symbol, {})
            if sym_state:
                # v16 P1-9b: 优先取current_trend，其次big_trend
                trend = sym_state.get("current_trend", sym_state.get("big_trend", "SIDE"))
                regime = sym_state.get("regime", "RANGING")
                trend_x4 = sym_state.get("trend_x4", "SIDE")  # v3.571
                current_regime = sym_state.get("current_regime", "UNKNOWN")  # v3.572
                regime_x4 = sym_state.get("regime_x4", "UNKNOWN")  # v3.572
                logger.debug(f"[v3.572] {symbol} 趋势来自global_trend_state.json: 当前={trend} x4={trend_x4} ({regime}) 当前震荡={current_regime} x4震荡={regime_x4}")
                return {
                    "trend": trend,
                    "regime": regime,
                    "trend_x4": trend_x4,  # v3.571
                    "current_regime": current_regime,  # v3.572
                    "regime_x4": regime_x4,  # v3.572
                    "l2_recommendation": sym_state.get("l2_recommendation", "HOLD"),  # v21
                    "source": "global_trend_state"
                }

        # 3. 降级到原有逻辑 (state.json)
        current_trend = self._get_current_trend(symbol)
        regime = "TRENDING" if current_trend in ("UP", "DOWN") else "RANGING"
        logger.debug(f"[v3.572] {symbol} 趋势来自state.json: {current_trend} (无x4数据, 无震荡数据)")
        return {
            "trend": current_trend,
            "regime": regime,
            "trend_x4": "SIDE",  # v3.571: 降级时无x4数据，默认SIDE
            "current_regime": "UNKNOWN",  # v3.572: 降级时无震荡数据
            "regime_x4": "UNKNOWN",  # v3.572: 降级时无x4震荡数据
            "l2_recommendation": "HOLD",  # v21: 降级时不阻止
            "source": "state_json"
        }

    def _get_current_trend_for_scalping(self, symbol: str) -> dict:
        """
        v3.546: 获取剥头皮使用的当前周期趋势 (current_trend)
        v3.571: 新增trend_x4字段，供顺大逆小策略使用

        剥头皮使用当前周期趋势而非大周期趋势:
        - current_trend = UP/DOWN → 允许触发
        - current_trend = SIDE → 禁用

        Args:
            symbol: 交易品种 (yfinance格式，如BTC-USD)

        Returns:
            dict: {
                "current_trend": "UP"/"DOWN"/"SIDE",
                "regime": "TRENDING"/"RANGING",
                "trend_x4": "UP"/"DOWN"/"SIDE",  # v3.571
                "current_regime": "TRENDING"/"RANGING"/"UNKNOWN",  # v3.572
                "regime_x4": "TRENDING"/"RANGING"/"UNKNOWN",       # v3.572
                "source": "memory_cache"/"state_json"
            }
        """
        # 转换为主程序格式 (yfinance -> 主程序)
        main_symbol = REVERSE_SYMBOL_MAP.get(symbol, symbol)

        # 1. 优先使用内存缓存 (来自主程序HTTP更新)
        # v3.551fix: HTTP推送现在包含current_trend(当前周期方向)
        with _global_trend_lock:
            if main_symbol in _global_trend_cache:
                cache = _global_trend_cache[main_symbol]
                if "current_trend" in cache:
                    current_trend = cache["current_trend"]
                    regime = cache.get("regime", "RANGING")
                    trend_x4 = cache.get("trend_x4", "SIDE")  # v3.571
                    current_regime = cache.get("current_regime", "UNKNOWN")  # v3.572
                    regime_x4 = cache.get("regime_x4", "UNKNOWN")  # v3.572
                    logger.debug(f"[v3.572] {symbol} 剥头皮趋势来自内存缓存: 当前={current_trend} x4={trend_x4} ({regime}) 当前震荡={current_regime} x4震荡={regime_x4}")
                    return {
                        "current_trend": current_trend,
                        "regime": regime,
                        "trend_x4": trend_x4,  # v3.571
                        "current_regime": current_regime,  # v3.572
                        "regime_x4": regime_x4,  # v3.572
                        "source": "memory_cache"
                    }

        # 2. v16 P2-9: 使用safe_json_read替代bare open()
        try:
            state = safe_json_read(os.path.join("logs", "state.json"))

            # v3.551修复: 品种在根级别，current_trend在_last_final_decision深层嵌套
            symbol_state = state.get(main_symbol) or state.get(symbol)
            if symbol_state:
                final_decision = symbol_state.get("_last_final_decision", {})
                three_way = final_decision.get("three_way_signals", {})
                market_regime = three_way.get("market_regime", {})
                if isinstance(market_regime, dict):
                    current_trend = market_regime.get("current_trend", "SIDE")
                    if current_trend:
                        current_trend = current_trend.upper()
                    regime = market_regime.get("regime", "RANGING")
                    trend_x4 = market_regime.get("trend_x4", "SIDE")  # v3.571
                    if trend_x4:
                        trend_x4 = trend_x4.upper()
                    current_regime = market_regime.get("current_regime", "UNKNOWN")  # v3.572
                    regime_x4 = market_regime.get("regime_x4", "UNKNOWN")  # v3.572
                    logger.info(f"[v3.572] {symbol} 剥头皮趋势来自state.json: 当前={current_trend} x4={trend_x4} ({regime}) 当前震荡={current_regime} x4震荡={regime_x4}")
                    return {
                        "current_trend": current_trend,
                        "regime": regime,
                        "trend_x4": trend_x4,  # v3.571
                        "current_regime": current_regime,  # v3.572
                        "regime_x4": regime_x4,  # v3.572
                        "source": "state_json"
                    }

            logger.info(f"[v3.551] {symbol} state.json中未找到趋势数据, 剥头皮默认SIDE禁用")
        except Exception as e:
            logger.warning(f"[v3.546] 剥头皮读取state.json失败: {e}")

        # 3. 默认返回SIDE (禁用剥头皮)
        return {
            "current_trend": "SIDE",
            "regime": "RANGING",
            "trend_x4": "SIDE",  # v3.571
            "current_regime": "UNKNOWN",  # v3.572
            "regime_x4": "UNKNOWN",  # v3.572
            "source": "default"
        }

    def _get_l1_signals_for_supertrend(self, symbol: str) -> dict:
        """
        v3.530: 从state.json读取L1三方信号，供SuperTrend外挂使用

        读取 _last_final_decision.three_way_signals.v3300_five_module 中的信号

        Returns:
            dict: {
                "ai_signal": "BUY"/"SELL"/"HOLD",
                "ai_confidence": 0.0-1.0,
                "human_signal": "BUY"/"SELL"/"HOLD",
                "human_confidence": 0.0-1.0,
                "tech_signal": "BUY"/"SELL"/"HOLD",
                "tech_confidence": 0.0-1.0,
                "signal": "BUY"/"SELL"/"HOLD",  # 综合信号
            }
        """
        default_signals = {
            "ai_signal": "HOLD",
            "ai_confidence": 0.5,
            "human_signal": "HOLD",
            "human_confidence": 0.5,
            "tech_signal": "HOLD",
            "tech_confidence": 0.5,
            "signal": "HOLD",
        }

        state_file = self.config["tracking"]["state_file"]
        state_data = safe_json_read(state_file)

        if not state_data:
            return default_signals

        # 获取symbol对应的state
        main_symbol = REVERSE_SYMBOL_MAP.get(symbol, symbol)
        symbol_state = state_data.get(main_symbol) or state_data.get(symbol)

        if not symbol_state:
            return default_signals

        # 从 _last_final_decision.three_way_signals.v3300_five_module 读取
        final_decision = symbol_state.get("_last_final_decision", {})
        three_way = final_decision.get("three_way_signals", {})
        five_module = three_way.get("v3300_five_module", {})

        if not five_module:
            return default_signals

        return {
            "ai_signal": five_module.get("ai_signal", "HOLD"),
            "ai_confidence": five_module.get("ai_confidence", 0.5),
            "human_signal": five_module.get("human_signal", "HOLD"),
            "human_confidence": five_module.get("human_confidence", 0.5),
            "tech_signal": five_module.get("tech_signal", "HOLD"),
            "tech_confidence": five_module.get("tech_confidence", 0.5),
            "signal": five_module.get("signal", "HOLD"),
        }

    def _get_market_data_for_supertrend(self, symbol: str) -> dict:
        """
        v3.530: 从state.json读取市场数据，供SuperTrend外挂使用
        v16.4: 新增position_units，用于跌幅保护判断

        读取 _last_final_decision.three_way_signals.market_regime 中的数据

        Returns:
            dict: {
                "regime": "TRENDING"/"RANGING",
                "direction": "UP"/"DOWN"/"SIDE",
                "position_pct": 0-100,
                "current_trend": "UP"/"DOWN"/"SIDE",
                "position_units": 0-5,  # v16.4: 实际持仓数量
            }
        """
        default_data = {
            "regime": "UNKNOWN",
            "direction": "SIDE",
            "position_pct": 50.0,
            "current_trend": "SIDE",
            "position_units": 0,  # v16.4: 默认无持仓
        }

        state_file = self.config["tracking"]["state_file"]
        state_data = safe_json_read(state_file)

        if not state_data:
            return default_data

        # 获取symbol对应的state
        main_symbol = REVERSE_SYMBOL_MAP.get(symbol, symbol)
        symbol_state = state_data.get(main_symbol) or state_data.get(symbol)

        if not symbol_state:
            return default_data

        # v16.4: 读取实际持仓数量
        position_units = symbol_state.get("position_units", 0)

        # 从 _last_final_decision.three_way_signals.market_regime 读取
        final_decision = symbol_state.get("_last_final_decision", {})
        three_way = final_decision.get("three_way_signals", {})
        market_regime = three_way.get("market_regime", {})

        if not isinstance(market_regime, dict):
            default_data["position_units"] = position_units
            return default_data

        return {
            "regime": market_regime.get("regime", "UNKNOWN"),
            "direction": market_regime.get("direction", "SIDE"),
            "position_pct": market_regime.get("position_pct", 50.0),
            "current_trend": market_regime.get("current_trend", "SIDE"),
            "position_units": position_units,  # v16.4: 实际持仓数量
        }

    def _notify_main_server(self, symbol: str, signal_data: dict) -> dict:
        """通知主程序执行交易，返回服务器响应"""
        # GCC-0142+0145: Path A信号通道, P0-P4优先级自动推断
        from dualpath_traffic import traffic_mgr as _tm, infer_priority
        _pri = infer_priority(
            signal_data.get("signal_type", ""),
            signal_data.get("crash_sell", False),
        )
        with _tm.signal_path(symbol, priority=_pri):
            return self._notify_main_server_inner(symbol, signal_data)

    def _notify_main_server_inner(self, symbol: str, signal_data: dict) -> dict:
        """_notify_main_server实际逻辑(被signal_path包裹)"""
        # KEY-004-T02: 统一外挂事件source字段与日志标签
        signal_type = signal_data.get("signal_type", "P0-Open")
        source = signal_data.get("source") or signal_type
        signal_data["source"] = source

        # KEY-011: 4H外挂不再推入GCC-TM信号池 (v0.3: 信号池只接受15min级别信号源)
        # 原: gcc_push_signal(symbol, source, _sig_action, _sig_conf)

        def _record_key004_trade(executed_flag: bool) -> None:
            try:
                tracker = getattr(self, "_plugin_profit_tracker", None)
                if tracker is None:
                    from plugin_profit_tracker import PluginProfitTracker

                    tracker = PluginProfitTracker()
                    self._plugin_profit_tracker = tracker
                tracker.record_trade(
                    symbol=symbol,
                    plugin_name=signal_type,
                    action=signal_data.get("signal", ""),
                    price=float(signal_data.get("price", 0.0)),
                    executed=bool(executed_flag),
                    asset_type=signal_data.get("type", "crypto"),
                    source=source,
                )
            except Exception as track_err:
                logger.debug(f"[KEY-004] tracker record skipped: {track_err}")

        # v21.27: 移动止损/移动止盈豁免P0冷却和日限次 (保命优先，与Signal Gate/FilterChain口径一致)
        _p0_safety_exempt = signal_data.get("signal_type", "") in ("移动止损", "移动止盈")

        # v21.2: P0发送失败冷却 (同品种失败后5分钟内不再重试)
        if not _p0_safety_exempt and hasattr(self, '_p0_fail_cooldown') and symbol in self._p0_fail_cooldown:
            cooldown_until = self._p0_fail_cooldown[symbol]
            if datetime.now() < cooldown_until:
                plugin_name = signal_data.get("signal_type", "未知")
                logger.debug(f"[v21.2] {symbol} {plugin_name} P0发送失败冷却中，跳过(至{cooldown_until.strftime('%H:%M:%S')})")
                _record_key004_trade(False)
                return {"executed": False, "reason": "v21.2: P0发送失败冷却中"}
            else:
                del self._p0_fail_cooldown[symbol]
        # v21.19: P0每日限次回流检查 — v3.670: 已取消(server侧限次已移除)
        # 原逻辑: server回告今日限次已满则跳过，现在不再检查

        # v21.21: Signal Gate 微观结构过滤 (Phase1: 仅观察不拦截)
        # 绿色通道: 移动止损/移动止盈/暴跌平仓 直接放行
        _sg_signal_type = signal_data.get("signal_type", "")
        _sg_is_exempt = (
            _sg_signal_type in ("移动止损", "移动止盈")
            or signal_data.get("crash_sell", False)
        )
        if not _sg_is_exempt:
            _sg_result = _scan_read_signal_gate(symbol, signal_data.get("signal", "BUY"))
            if _sg_result:
                _sg_vr = _sg_result.get("vr")
                _sg_vr_str = f"{_sg_vr:.3f}" if _sg_vr is not None else "?"
                logger.info(
                    f"[SIGNAL_GATE] {symbol} {signal_data.get('signal','')} "
                    f"go={_sg_result['go']} regime={_sg_result.get('regime','?')} "
                    f"vr={_sg_vr_str} src={_sg_signal_type} reason={_sg_result.get('reason','')}"
                )
                SIGNAL_GATE_SCAN_ENABLED = False  # Phase2改True
                if SIGNAL_GATE_SCAN_ENABLED and not _sg_result["go"]:
                    _record_key004_trade(False)
                    return {"executed": False, "reason": f"signal_gate拦截: {_sg_result.get('reason','')}"}

        # v21.24: FilterChain Vision门控 (Phase2: 真拦截)
        # GCC-0194: 只豁免BrooksVision/VisionPattern(自己过滤自己=循环), 移动止损/止盈也过滤
        FILTER_CHAIN_SCAN_ENABLED = True
        _fc_signal_type = signal_data.get("signal_type", "")
        _fc_exempt = _fc_signal_type in ("BrooksVision", "VisionPattern", "双底双顶")
        _fc = None if _fc_exempt else _scan_read_filter_chain(symbol, signal_data.get("signal", "BUY"))
        if _fc:
            _fc_vol = _fc.get("volume_score", 0) or 0
            _fc_weight = _fc.get("final_weight", 1.0)
            _fc_size = _fc.get("execution_size", "STANDARD")
            _fc_struct = _fc.get("overall_structure", "")
            _fc_pos = _fc.get("position", "")
            logger.info(
                f"[FILTER_CHAIN] {symbol} {signal_data.get('signal','')} "
                f"passed={_fc['passed']} struct={_fc_struct}/{_fc_pos} "
                f"size={_fc_size}(w={_fc_weight:.2f}) blocked={_fc.get('blocked_by','')} "
                f"vision={_fc.get('vision','')} vol={_fc_vol:.0%} micro={_fc.get('micro_go','')}"
            )
            if FILTER_CHAIN_SCAN_ENABLED and not _fc["passed"]:
                logger.info(f"[FILTER_CHAIN拦截] {symbol} {signal_data.get('signal','')} by={_fc.get('blocked_by','')} struct={_fc_struct}/{_fc_pos} size={_fc_size} reason={_fc.get('vision_reason','')}")
                _record_key004_trade(False)
                return {"executed": False, "reason": f"FilterChain拦截: {_fc.get('reason','')}"}

        # GCC-0047: 取消单外挂互斥,允许多外挂激活,靠FilterChain+门禁过滤
        # 原v20.4/v21互斥锁定已移除,每个外挂独立发送
        plugin_name = signal_data.get("signal_type", "未知")
        logger.info(f"[GCC-0047] {symbol} {plugin_name}触发，发送P0信号(多外挂并行)")

        main_server_url = self.config.get("main_server_url", "http://localhost:6001")
        endpoint = f"{main_server_url}/p0_signal"

        # v21.8: 计算共识度评分 (Phase1: 仅记录)
        _p0_consensus = calc_consensus_score(symbol, signal_data["signal"], signal_data.get("trend_info"))
        log_consensus_score(symbol, signal_data["signal"], signal_data.get("signal_type", "P0"), _p0_consensus)

        payload = {
            "symbol": symbol,
            "signal": signal_data["signal"],
            "price": signal_data["price"],
            "base_price": signal_data["base_price"],
            "change_pct": signal_data["change_pct"],
            "timeframe": signal_data["timeframe"],
            "type": signal_data.get("type", "crypto"),
            "signal_type": signal_data.get("signal_type", "P0-Open"),
            "source": source,
            "position_units": signal_data.get("position_units"),        # v21.29: 仓位二次校验用
            "consensus_score": round(_p0_consensus["score"], 4),        # v21.8
            "consensus_label": _p0_consensus.get("label", ""),          # v21.8
            "consensus_would_block": _p0_consensus.get("would_block", False),  # v21.8
        }

        logger.info(
            f"[KEY-004][PLUGIN_EVENT] phase=dispatch symbol={symbol} "
            f"source={source} action={signal_data.get('signal','')} executed=NA reason=pending "
            f"price={signal_data.get('price', 0)}"
        )

        try:
            logger.info(f"[P0] 通知主程序: {endpoint}")
            response = requests.post(endpoint, json=payload, timeout=10)

            if response.status_code == 200:
                result = response.json()
                logger.info(f"[P0] 主程序响应: {result}")
                logger.info(
                    f"[KEY-004][PLUGIN_EVENT] phase=response symbol={symbol} "
                    f"source={source} action={signal_data.get('signal','')} "
                    f"executed={result.get('executed', False)} reason={result.get('reason','')} "
                    f"price={signal_data.get('price', 0)}"
                )
                _record_key004_trade(bool(result.get("executed", False)))
                # v21.19: server返回"限次"时今日不再发该方向
                if not result.get("executed", False) and "限次" in result.get("reason", ""):
                    if hasattr(self, '_p0_daily_banned'):
                        _ban_key = f"{symbol}_{signal_data.get('signal', '')}"
                        self._p0_daily_banned[_ban_key] = get_today_date_ny()
                        logger.info(f"[v21.19] {symbol} {signal_data.get('signal','')} 被server限次，今日标记禁发")
                # v21.2→v21.18: 发送失败冷却 (连续3次→冻结到次日8AM)
                if not result.get("executed", False) and "发送失败" in result.get("reason", ""):
                    if hasattr(self, '_p0_fail_cooldown'):
                        _fc = self._p0_fail_count.get(symbol, 0) + 1
                        self._p0_fail_count[symbol] = _fc
                        if _fc >= 3:
                            # 计算到次日8AM的时长 (用naive datetime兼容_p0_fail_cooldown)
                            _freeze_secs = (get_next_8am_ny() - get_ny_now()).total_seconds()
                            self._p0_fail_cooldown[symbol] = datetime.now() + timedelta(seconds=max(_freeze_secs, 3600))
                            logger.info(f"[v21.18] {symbol} P0连续{_fc}次发送失败，冻结到次日8AM({_freeze_secs/3600:.1f}h)")
                        else:
                            cooldown_minutes = 5
                            self._p0_fail_cooldown[symbol] = datetime.now() + timedelta(minutes=cooldown_minutes)
                            logger.info(f"[v21.2] {symbol} P0发送失败({_fc}/3)，设置{cooldown_minutes}分钟冷却")
                # v20.7: 暴跌卖出标记，允许本周期再卖1次
                if result.get("executed", False):
                    if signal_data.get("crash_sell") and hasattr(self, '_crash_sell_this_cycle'):
                        self._crash_sell_this_cycle.add(symbol)
                        logger.info(f"[v20.7] {symbol} 暴跌卖出，本周期允许再卖1次")
                    # v21.2→v21.18: 执行成功则清除冷却+重置失败计数
                    if hasattr(self, '_p0_fail_cooldown') and symbol in self._p0_fail_cooldown:
                        del self._p0_fail_cooldown[symbol]
                    if hasattr(self, '_p0_fail_count') and symbol in self._p0_fail_count:
                        del self._p0_fail_count[symbol]
                    # v21.3: 记录交易到频率控制器 (Module B)
                    if _modules_available and self.frequency_controller:
                        action = signal_data.get("signal", "")
                        source = signal_data.get("signal_type", "")
                        self.frequency_controller.record_trade(symbol, action, source)
                        # v21.4: 预选等级日志 (Phase2: C/D级强警告)
                        if self.stock_selector:
                            tier = self.stock_selector.get_tier(symbol)
                            if tier == "D":
                                logger.warning(f"[v21.4] ⚠ {symbol} 等级=D, {action}({source}) — 低质量品种交易!")
                            elif tier == "C":
                                logger.warning(f"[v21.4] {symbol} 等级=C, {action}({source}) — 减配品种交易")
                return result
            else:
                logger.error(f"[P0] 主程序返回错误: {response.status_code}")
                logger.info(
                    f"[KEY-004][PLUGIN_EVENT] phase=response symbol={symbol} "
                    f"source={source} action={signal_data.get('signal','')} "
                    f"executed=False reason=HTTP_{response.status_code}"
                )
                _record_key004_trade(False)
                return {"executed": False, "reason": f"HTTP {response.status_code}"}

        except requests.exceptions.ConnectionError:
            if hasattr(self, '_signal_executed_this_cycle'):
                self._signal_executed_this_cycle.discard(symbol)
                logger.warning(f"[v21] {symbol} 连接异常，解除本周期锁定")
            logger.error(f"[P0] 无法连接主程序: {endpoint}")
            logger.info(
                f"[KEY-004][PLUGIN_EVENT] phase=error symbol={symbol} "
                f"source={source} action={signal_data.get('signal','')} executed=False reason=connection_error"
            )
            _record_key004_trade(False)
            return {"executed": False, "reason": "无法连接主程序"}
        except requests.exceptions.Timeout:
            if hasattr(self, '_signal_executed_this_cycle'):
                self._signal_executed_this_cycle.discard(symbol)
                logger.warning(f"[v21] {symbol} 请求超时，解除本周期锁定")
            logger.error(f"[P0] 主程序请求超时: {endpoint}")
            logger.info(
                f"[KEY-004][PLUGIN_EVENT] phase=error symbol={symbol} "
                f"source={source} action={signal_data.get('signal','')} executed=False reason=timeout"
            )
            _record_key004_trade(False)
            return {"executed": False, "reason": "主程序请求超时"}
        except Exception as e:
            logger.error(f"[P0] 通知主程序异常: {e}")
            logger.info(
                f"[KEY-004][PLUGIN_EVENT] phase=error symbol={symbol} "
                f"source={source} action={signal_data.get('signal','')} executed=False reason={str(e)}"
            )
            _record_key004_trade(False)
            return {"executed": False, "reason": str(e)}

    def _get_symbol_config(self, symbol: str) -> tuple:
        """获取品种配置
        v20: timeframe从symbol_config.json动态读取，CONFIG值作为默认
        v20.1: 返回值增加p0_tracking_threshold (P0-Tracking专用阈值)"""
        # v20: 动态读取品种周期
        from timeframe_params import read_symbol_timeframe
        _tf_minutes = read_symbol_timeframe(symbol, default=240)
        _tf_params = get_timeframe_params(_tf_minutes, is_crypto=is_crypto_symbol(symbol))
        _tf_str = _tf_params["scan_timeframe_str"]  # "1h", "4h"等

        if symbol in self.config["crypto"]["symbols"] or symbol in CRYPTO_SYMBOL_MAP:
            return (
                self.config["crypto"]["threshold"],
                self.config["crypto"]["tracking_threshold"],  # 移动止盈/止损: 2.5%
                _tf_str,
                True,
                self.config["crypto"]["p0_tracking_threshold"],  # v20.2: P0-Tracking: 2.5%
            )
        else:
            return (
                self.config["stock"]["threshold"],
                self.config["stock"]["tracking_threshold"],  # 移动止盈/止损: 3%
                _tf_str,
                False,
                self.config["stock"]["p0_tracking_threshold"],  # v20.2: P0-Tracking: 3%
            )

    def _get_position_from_main_state(self, symbol: str) -> int:
        """从主程序state.json读取持仓数量"""
        pos, _ = self._get_position_and_max(symbol)
        return pos

    def _get_position_and_max(self, symbol: str) -> tuple:
        """v21.17: 从主程序state.json读取(position_units, max_units)"""
        state_file = self.config["tracking"]["state_file"]
        state_data = safe_json_read(state_file)

        if not state_data:
            return (0, 5)

        st = state_data.get(symbol)
        if not st:
            main_symbol = REVERSE_SYMBOL_MAP.get(symbol, symbol)
            st = state_data.get(main_symbol)

        if st:
            pos = st.get("position_units", 0) or 0
            mx = st.get("max_units", 5)
            if mx is None:  # v21.26: state中max_units=null时用默认5，防止比较TypeError
                mx = 5
            return (pos, mx)
        return (0, 5)

    def _get_entry_price_from_main_state(self, symbol: str) -> float:
        """
        v16.8: 从主程序state.json读取平均入场价

        open_buys格式:
        - 数字: 直接是价格
        - dict: {"price": x, "size": 1, ...}
        """
        state_file = self.config["tracking"]["state_file"]
        state_data = safe_json_read(state_file)

        if not state_data:
            return 0.0

        # 尝试symbol和main_symbol
        symbol_data = None
        if symbol in state_data:
            symbol_data = state_data[symbol]
        else:
            main_symbol = REVERSE_SYMBOL_MAP.get(symbol, symbol)
            if main_symbol in state_data:
                symbol_data = state_data[main_symbol]

        if not symbol_data:
            return 0.0

        open_buys = symbol_data.get("open_buys", [])
        if not open_buys:
            return 0.0

        # 计算平均入场价
        prices = []
        for item in open_buys:
            if isinstance(item, (int, float)):
                if item > 0:  # 过滤0价格
                    prices.append(item)
            elif isinstance(item, dict):
                price = item.get("price", 0)
                if price > 0:
                    prices.append(price)

        if not prices:
            return 0.0

        return sum(prices) / len(prices)

    def _check_period_reset_open(self, symbol: str, timeframe: str):
        """
        v8.3: 检查P0-Open周期重置
        - 加密货币: 使用前一个周期的开盘价
        - 美股: 使用当天开盘价，且只在开盘时间才设置
        """
        period_start = get_current_period_start(timeframe)
        period_key = period_start.isoformat()

        # v8.3: 美股特殊处理
        is_stock = is_us_stock(symbol)
        market_open = is_us_market_open()

        if symbol in self.state:
            old_period = self.state[symbol].get("period_start")
            old_base_price = self.state[symbol].get("base_price")

            # v8.3: 美股非开盘时间，检查是否需要更新基准价
            if is_stock:
                if not market_open:
                    # 美股非开盘时间，不更新基准价，但检查解冻状态
                    old_freeze_until = self.state[symbol].get("freeze_until")
                    if old_freeze_until and not is_frozen_until(old_freeze_until):
                        logger.info(f"[{symbol}] P0-Open解冻 (非开盘时间)")
                        self.state[symbol]["freeze_until"] = None
                    return  # 非开盘时间不重置

                # 美股开盘时间，检查是否是新交易日
                ny_now = get_ny_now()
                today_str = ny_now.strftime("%Y-%m-%d")
                last_update_date = self.state[symbol].get("last_update_date", "")

                if last_update_date != today_str:
                    # 新交易日，使用当天开盘价
                    logger.info(f"[{symbol}] P0-Open新交易日({today_str})，重置状态")

                    new_base_price = YFinanceDataFetcher.get_today_market_open_price(symbol)
                    if new_base_price:
                        logger.info(f"[{symbol}] 使用当天开盘价作为基准: {new_base_price:.2f}")
                    else:
                        # 当天开盘价获取失败，保留旧基准
                        new_base_price = old_base_price
                        logger.warning(f"[{symbol}] 当天开盘价获取失败，保留旧基准: {old_base_price}")

                    # 检查解冻状态
                    old_freeze_until = self.state[symbol].get("freeze_until")
                    if old_freeze_until and not is_frozen_until(old_freeze_until):
                        logger.info(f"[{symbol}] P0-Open解冻")
                        old_freeze_until = None

                    self.state[symbol] = {
                        "base_price": new_base_price,
                        "period_start": period_key,
                        "triggered_action": None,
                        "freeze_until": old_freeze_until,
                        "last_update_date": today_str,  # v8.3: 记录更新日期
                    }

                    if symbol in self.signals:
                        del self.signals[symbol]
                # else: 同一交易日内，不重复设置基准价

            else:
                # 加密货币：每小时周期重置
                if old_period != period_key:
                    logger.info(f"[{symbol}] P0-Open新周期，重置状态")

                    # v8.0: 加密货币使用前一个周期的开盘价
                    new_base_price = YFinanceDataFetcher.get_previous_period_open(symbol, timeframe)
                    if new_base_price:
                        logger.info(f"[{symbol}] 使用前周期开盘价作为基准: {new_base_price:.2f}")
                    else:
                        new_base_price = YFinanceDataFetcher.get_period_open(symbol, timeframe)
                        logger.info(f"[{symbol}] 备选使用当前周期开盘价: {new_base_price}")

                    old_freeze_until = self.state[symbol].get("freeze_until")
                    if old_freeze_until and not is_frozen_until(old_freeze_until):
                        logger.info(f"[{symbol}] P0-Open解冻")
                        old_freeze_until = None

                    self.state[symbol] = {
                        "base_price": new_base_price,
                        "period_start": period_key,
                        "triggered_action": None,
                        "freeze_until": old_freeze_until,
                    }

                    if symbol in self.signals:
                        del self.signals[symbol]
        else:
            # 首次初始化
            if is_stock:
                # v8.3: 美股首次初始化
                if market_open:
                    base_price = YFinanceDataFetcher.get_today_market_open_price(symbol)
                    if base_price:
                        logger.info(f"[{symbol}] 首次初始化，使用当天开盘价: {base_price:.2f}")
                    else:
                        logger.warning(f"[{symbol}] 首次初始化，当天开盘价获取失败，暂不设置基准")
                        base_price = None
                else:
                    logger.info(f"[{symbol}] 首次初始化，美股未开盘，暂不设置基准价")
                    base_price = None

                ny_now = get_ny_now()
                self.state[symbol] = {
                    "base_price": base_price,
                    "period_start": period_key,
                    "triggered_action": None,
                    "freeze_until": None,
                    "last_update_date": ny_now.strftime("%Y-%m-%d") if market_open else "",
                }
            else:
                # 加密货币首次初始化
                base_price = YFinanceDataFetcher.get_previous_period_open(symbol, timeframe)
                if not base_price:
                    base_price = YFinanceDataFetcher.get_period_open(symbol, timeframe)
                self.state[symbol] = {
                    "base_price": base_price,
                    "period_start": period_key,
                    "triggered_action": None,
                    "freeze_until": None,
            }

    def _check_tracking_period_reset(self, symbol: str, timeframe: str):
        """
        v11.2: 检查P0-Tracking周期重置和冻结状态
        v11.2新增: 美股开盘日重置逻辑
        """
        period_start = get_current_period_start(timeframe)
        period_key = period_start.isoformat()

        if symbol not in self.tracking_state:
            # v3.546: 首次初始化（包含每日买卖限制）
            # v17.2: 添加P0保护和移动止损字段
            self.tracking_state[symbol] = {
                "peak_price": None,
                "trough_price": None,
                "last_position": 0,
                "period_start": period_key,
                "triggered_action": None,
                "trigger_history": [],
                "freeze_until": None,
                "last_trading_date": "",  # v11.2: 上次交易日期
                "market_open_cooldown_until": None,  # v11.2: 开盘缓冲期
                "buy_used": False,   # v3.546: 今日是否已买入
                "sell_used": False,  # v3.546: 今日是否已卖出
                "reset_date": None,  # v3.546: 重置日期
                # v16.8→v20.2: 移动止损字段 (改为计数器，每天最多2次)
                "trailing_stop_count": 0,  # v20.2: SELL计数器，最多2次/天
                "trailing_buy_count": 0,   # v20.2: BUY计数器，最多2次/天
                "trailing_high": None,
                "trailing_low": None,
                "trailing_reset_date": None,
                # v17.2: P0信号保护
                "p0_buy_protection_until": None,
                "p0_sell_protection_until": None,
                # v21.17: 同K线单方向冻结 (替换v20.1首末档限制)
                "bar_freeze_dir": None,         # 当前K线已交易方向 BUY/SELL/None
                "bar_freeze_count": 0,          # 当前K线同方向交易次数
                "bar_freeze_bar_start": None,   # 冻结记录对应的K线周期
                # v20.5: ATR动态阈值缓存
                "atr_cache_until": None,   # ISO时间戳，下一个纽约8AM (缓存过期时间)
                "atr_cache_value": None,   # ATR(14) 原始值(美元)
                # v21.14 SYS-032: volume数据(供EXIT_SCHEDULER使用)
                "last_volume": 0,
                "avg_volume": 0,
            }
        else:
            old_period = self.tracking_state[symbol].get("period_start")

            # v11.2: 美股开盘日重置检测
            if is_us_stock(symbol) and is_us_market_open():
                today_date = get_today_trading_date()
                last_trading_date = self.tracking_state[symbol].get("last_trading_date", "")

                # 检测是否是新交易日
                if last_trading_date != today_date:
                    # 新交易日！检查是否在开盘窗口内(9:30-9:35)
                    if is_us_market_open_window():
                        logger.info("=" * 70)
                        logger.info(f"[{symbol}] v11.2 美股开盘日重置! (新交易日: {today_date})")
                        logger.info(f"[{symbol}]   上次交易日: {last_trading_date or '无'}")
                        logger.info(f"[{symbol}]   旧基准价 peak={self.tracking_state[symbol].get('peak_price')} trough={self.tracking_state[symbol].get('trough_price')}")

                        # 重置基准价为None，使用当前价安全初始化
                        self.tracking_state[symbol]["peak_price"] = None
                        self.tracking_state[symbol]["trough_price"] = None
                        self.tracking_state[symbol]["_needs_safe_init"] = True
                        self.tracking_state[symbol]["triggered_action"] = None  # 重置触发状态
                        # v21.17: 新交易日清除K线冻结记录
                        self.tracking_state[symbol]["bar_freeze_dir"] = None
                        self.tracking_state[symbol]["bar_freeze_count"] = 0
                        self.tracking_state[symbol]["bar_freeze_bar_start"] = None

                        # 设置开盘缓冲期(9:40结束)
                        cooldown_end = get_us_market_open_cooldown_end()
                        self.tracking_state[symbol]["market_open_cooldown_until"] = cooldown_end.isoformat()

                        # 更新交易日期
                        self.tracking_state[symbol]["last_trading_date"] = today_date

                        logger.info(f"[{symbol}]   基准价将使用当前价初始化")
                        logger.info(f"[{symbol}]   开盘缓冲期至 {cooldown_end.strftime('%H:%M:%S')} NY")
                        logger.info("=" * 70)

                    elif is_us_market_open():
                        # 已经过了开盘窗口但还没更新日期（可能是程序刚启动）
                        # 静默更新日期，但仍设置safe_init以防万一
                        logger.info(f"[{symbol}] v11.2 美股开盘日更新 (非开盘窗口): {last_trading_date} → {today_date}")
                        self.tracking_state[symbol]["last_trading_date"] = today_date

                        # 如果基准价看起来是周五的陈旧数据，也需要重置
                        # 通过检查period_start是否是今天之前来判断
                        old_period_date = old_period[:10] if old_period else ""
                        if old_period_date and old_period_date < today_date:
                            logger.info(f"[{symbol}]   检测到陈旧基准价(period={old_period_date})，启用安全初始化")
                            self.tracking_state[symbol]["_needs_safe_init"] = True

            # 检查是否解冻
            freeze_until = self.tracking_state[symbol].get("freeze_until")
            if freeze_until and not is_frozen_until(freeze_until):
                # 解冻！
                logger.info(f"[{symbol}] P0-Tracking解冻")
                self.tracking_state[symbol]["freeze_until"] = None
                self.tracking_state[symbol]["trigger_history"] = []

                # v11.0: 解冻后设置为None，让后续逻辑用当前价初始化
                # 避免使用历史high/low导致的价格跳跃误触发
                self.tracking_state[symbol]["peak_price"] = None
                self.tracking_state[symbol]["trough_price"] = None
                self.tracking_state[symbol]["_needs_safe_init"] = True  # v11.0: 标记需要安全初始化
                logger.info(f"[{symbol}] v11.0: 解冻后将使用当前价安全初始化")

            if old_period != period_key:
                # 新周期开始，只重置触发标志
                logger.info(f"[{symbol}] P0-Tracking新周期，重置触发状态")
                self.tracking_state[symbol]["triggered_action"] = None
                self.tracking_state[symbol]["period_start"] = period_key

                # 清理过期的触发历史（只保留6小时内的）
                self._cleanup_trigger_history(symbol)

    def _cleanup_trigger_history(self, symbol: str):
        """清理过期的触发历史"""
        if symbol not in self.tracking_state:
            return

        history = self.tracking_state[symbol].get("trigger_history", [])
        if not history:
            return

        cutoff = datetime.now() - timedelta(hours=self.config["tracking"]["freeze_window_hours"])

        new_history = []
        for record in history:
            try:
                record_time = datetime.fromisoformat(record["time"])
                if record_time > cutoff:
                    new_history.append(record)
            except Exception:  # v16 P2-2
                pass

        self.tracking_state[symbol]["trigger_history"] = new_history

    def _check_and_freeze(self, symbol: str):
        """
        v3.546: 检查是否需要冻结
        改为: 买卖各1次后才冻结到次日8AM (加密货币和美股统一规则)
        v16 P1-8: 先检查freeze_until是否仍有效，再检查日期重置
        """
        if symbol not in self.tracking_state:
            return

        state = self.tracking_state[symbol]

        # v16 P1-8: 检查日期变化时，先确认冻结是否仍有效
        today = get_today_date_ny()
        if state.get("reset_date") != today:
            # 先检查freeze是否仍在有效期
            freeze_str = state.get("freeze_until")
            if freeze_str:
                try:
                    freeze_dt = datetime.fromisoformat(freeze_str)
                    ny_now = get_ny_now()
                    if freeze_dt.tzinfo is None:
                        freeze_dt = freeze_dt.replace(tzinfo=ZoneInfo("America/New_York"))
                    if ny_now < freeze_dt:
                        # 冻结仍有效，不重置
                        logger.info(f"[{symbol}] P0-Tracking 日期变化但冻结仍有效至 {freeze_dt.strftime('%m-%d %H:%M')}")
                        return
                except Exception as e:
                    logger.warning(f"[{symbol}] 解析冻结时间失败: {freeze_str}, {e}")
            # 冻结无效或不存在，重置买卖状态
            state["buy_used"] = False
            state["sell_used"] = False
            state["freeze_until"] = None
            # v16.8→v20.2: 重置移动止损/止盈配额 (计数器)
            state["trailing_stop_count"] = 0
            state["trailing_buy_count"] = 0
            state["trailing_high"] = None
            state["trailing_low"] = None
            # v17.2: 重置P0信号保护
            state["p0_buy_protection_until"] = None
            state["p0_sell_protection_until"] = None
            state["reset_date"] = today
            logger.info(f"[{symbol}] P0-Tracking 新一天，重置买卖状态 (含移动止损+P0保护)")
            return

        # v3.546: 检查买卖是否都用完
        buy_used = state.get("buy_used", False)
        sell_used = state.get("sell_used", False)

        # 买卖各1次后才冻结
        if buy_used and sell_used:
            freeze_until = get_next_8am_ny()
            state["freeze_until"] = freeze_until.isoformat()
            logger.info(f"[{symbol}] P0-Tracking冻结! 买卖各1次已完成")
            logger.info(f"[{symbol}] 解冻时间: {freeze_until.strftime('%Y-%m-%d %H:%M')} NY")

    def _scan_tracking(self, symbol: str, current_price: float, is_crypto: bool):
        """
        v11.0: 扫描P0-Tracking（追踪止损/追涨买入）

        v11.0变更:
        - P0-Tracking正常运行扫描
        - 触发时检查L1和飞云外挂状态，决定是否激活
        - L1外挂: 趋势跟随(道氏理论确认趋势后激活)
        - 飞云外挂: 趋势捕捉(双突破共振确认趋势开启)
        - 两个外挂独立检查，哪个激活运行哪个

        v11.4变更 (已在v11.6移除):
        - [已移除] 趋势对齐条件 - 导致暴跌时SELL被跳过

        v11.6变更:
        - 移除P0-Tracking趋势对齐检查，允许任何趋势下触发BUY/SELL
        - P0-Open仍保留趋势对齐要求
        """
        # v16.6: P0-Tracking完全独立运行，不依赖L1/飞云外挂

        # v20.1: 分离P0-Tracking和移动止盈/止损的阈值
        threshold, trailing_threshold, timeframe, _, p0_tracking_threshold = self._get_symbol_config(symbol)

        # 检查周期重置和冻结状态
        self._check_tracking_period_reset(symbol, timeframe)

        # v16.8: 移动止损独立于原P0-Tracking的冻结状态
        # 先获取持仓信息（移动止损需要）
        position = self._get_position_from_main_state(symbol)

        # 检查是否被冻结（只影响原P0-Tracking）
        freeze_until = self.tracking_state[symbol].get("freeze_until")
        original_frozen = is_frozen_until(freeze_until)

        # v8.0: 检查本周期是否已触发（互斥，只影响原P0-Tracking）
        period_triggered = self.tracking_state[symbol].get("triggered_action")

        # v16.8: 先运行移动止损检查（独立于冻结状态）
        # v20.1: 移动止盈/止损使用trailing_threshold (加密2.5%, 美股3%)
        self._check_trailing_stop(symbol, current_price, is_crypto, position, trailing_threshold, timeframe)

        # v20.4: 禁用P0-Tracking原逻辑，只保留移动止盈/止损
        return

        # 原P0-Tracking被冻结或已触发时跳过
        if original_frozen:
            logger.info(f"[{symbol}] P0-Tracking原逻辑: 冻结中，跳过")
            return

        if period_triggered:
            logger.info(f"[{symbol}] P0-Tracking原逻辑: 本周期已触发{period_triggered}，跳过")
            return

        # position已在上面获取
        last_position = self.tracking_state[symbol].get("last_position", 0)

        # 检测持仓变化，初始化基准价格
        if position > 0 and last_position == 0:
            # 刚买入，初始化peak_price
            # v20.3: 优先使用局部高点，找不到则用绝对高点
            local_high, local_low, high_type, low_type = YFinanceDataFetcher.get_first_local_extremes(
                symbol, self.config["tracking"]["lookback_bars"]
            )
            if local_high:
                self.tracking_state[symbol]["peak_price"] = max(current_price, local_high)
            else:
                self.tracking_state[symbol]["peak_price"] = current_price
            self.tracking_state[symbol]["trough_price"] = None
            logger.info(f"[{symbol}] 检测到买入，初始化peak_price: {self.tracking_state[symbol]['peak_price']:.2f} ({high_type or 'current'})")

        elif position == 0 and last_position > 0:
            # 刚清仓，初始化trough_price
            # v20.3: 优先使用局部低点，找不到则用绝对低点
            local_high, local_low, high_type, low_type = YFinanceDataFetcher.get_first_local_extremes(
                symbol, self.config["tracking"]["lookback_bars"]
            )
            if local_low:
                self.tracking_state[symbol]["trough_price"] = min(current_price, local_low)
            else:
                self.tracking_state[symbol]["trough_price"] = current_price
            self.tracking_state[symbol]["peak_price"] = None
            logger.info(f"[{symbol}] 检测到清仓，初始化trough_price: {self.tracking_state[symbol]['trough_price']:.2f} ({low_type or 'current'})")

        # 更新last_position
        self.tracking_state[symbol]["last_position"] = position

        # 有持仓时：更新peak_price，检查卖出触发
        if position > 0:
            peak_price = self.tracking_state[symbol].get("peak_price")

            if peak_price is None:
                # v11.0: 检查是否需要安全初始化（解冻后或状态恢复）
                needs_safe_init = self.tracking_state[symbol].get("_needs_safe_init", False)

                if needs_safe_init or self._is_in_startup_cooldown():
                    # v11.0: 使用当前价作为基准，避免历史价格跳跃
                    peak_price = current_price
                    self.tracking_state[symbol]["peak_price"] = peak_price
                    self.tracking_state[symbol]["_needs_safe_init"] = False
                    logger.info(f"[{symbol}] v11.0 安全初始化peak_price: {peak_price:.2f} (当前价)")
                else:
                    # v20.3: 回溯历史数据，优先使用局部高点
                    local_high, local_low, high_type, low_type = YFinanceDataFetcher.get_first_local_extremes(
                        symbol, self.config["tracking"]["lookback_bars"]
                    )
                    # v11.1+v20.3: 使用中间值初始化，避免历史价格导致虚假跌幅
                    # 公式: 新基准 = 高点 - (高点 - 当前价) / 2
                    if local_high and current_price < local_high:
                        peak_price = local_high - (local_high - current_price) / 2
                        logger.info(f"[{symbol}] 回溯初始化peak_price: {peak_price:.2f} (中间值: {high_type}={local_high:.2f}, current={current_price:.2f})")
                    else:
                        peak_price = current_price
                        logger.info(f"[{symbol}] 回溯初始化peak_price: {peak_price:.2f} (当前价)")
                    self.tracking_state[symbol]["peak_price"] = peak_price

            # 更新peak_price
            if current_price > peak_price:
                self.tracking_state[symbol]["peak_price"] = current_price
                peak_price = current_price

            # 检查卖出触发
            drawdown = (peak_price - current_price) / peak_price

            # v20.1: P0-Tracking使用独立阈值 (加密/美股都是5%)
            # v20.3: 移除仓位限制，局部极值点已降低误触发风险
            if drawdown >= p0_tracking_threshold:
                # v20.5: 提前获取K线数据 (急跌检测+Position Control共用)
                _p0_tf = read_symbol_timeframe(symbol, default=240)
                _p0_params = get_timeframe_params(_p0_tf, is_crypto=is_crypto_symbol(symbol))
                _p0_lookback = max(20, int(_p0_params["bars_per_day"] * 3))
                bars = YFinanceDataFetcher.get_ohlcv(symbol, _p0_tf, _p0_lookback)
                ema10 = calculate_ema10(bars) if bars else 0.0

                # v3.546: 检查今日卖出是否已用完 (v20.5: 传入bars用于急跌检测)
                can_sell, limit_reason = check_plugin_daily_limit(
                    self.tracking_state[symbol], "SELL",
                    bars=bars, current_price=current_price)
                if not can_sell:
                    logger.info(f"[v3.546] {symbol} P0-Tracking SELL 被限制: {limit_reason}")
                    return

                # v11.0: 启动冷却期内不触发信号
                if self._is_in_startup_cooldown():
                    elapsed = time.time() - self.startup_time
                    remaining = self.STARTUP_COOLDOWN_SECONDS - elapsed
                    logger.info(f"[{symbol}] v11.0 启动冷却期内，跳过SELL信号 (剩余 {remaining:.0f}秒)")
                    return

                # v11.2: 美股开盘缓冲期内不触发信号
                if self._is_in_market_open_cooldown(symbol):
                    cooldown_until = self.tracking_state[symbol].get("market_open_cooldown_until", "")[:19]
                    logger.info(f"[{symbol}] v11.2 开盘缓冲期内，跳过SELL信号 (至 {cooldown_until})")
                    return

                # v16.6: P0-Tracking完全独立运行，不依赖L1/飞云外挂

                # v17.3: Position Control检查
                trend_info = self._get_trend_for_plugin(symbol)
                big_trend = trend_info.get("trend_x4", "SIDE") if trend_info else "SIDE"
                current_trend = trend_info.get("trend", "SIDE") if trend_info else "SIDE"
                pos_allowed, pos_reason, target_pos = check_position_control(
                    position, "SELL", big_trend, current_trend, "P0-Tracking",
                    current_price, ema10, bars
                )
                log_signal_decision(symbol, "SELL", position, pos_allowed, pos_reason, target_pos, "P0-Tracking", current_price, big_trend, current_trend)
                if not pos_allowed:
                    logger.info("=" * 70)
                    logger.info(f"[v19] {symbol} P0-Tracking SELL → HOLD")
                    logger.info(f"  ├─ 当前仓位: {position}/5")
                    logger.info(f"  ├─ 当前价格: {current_price:.2f}")
                    logger.info(f"  └─ 原因: {pos_reason}")
                    logger.info("=" * 70)
                    return

                # v20.1: 首档K线内冻结检查 (v20.5: 传入bars用于急跌检测)
                current_bar_start = self.tracking_state[symbol].get("period_start", "")
                bar_ok, bar_reason = check_first_position_bar_freeze(
                    self.tracking_state[symbol], "SELL", position, current_bar_start,
                    bars=bars, current_price=current_price)
                if not bar_ok:
                    logger.info(f"[v20.1] {symbol} P0-Tracking SELL → HOLD | {bar_reason}")
                    return

                # 触发卖出
                logger.info("=" * 70)
                logger.info(f"[P0-Tracking] {symbol} SELL 触发!")
                logger.info(f"  peak_price: {peak_price:.2f}")
                logger.info(f"  当前价: {current_price:.2f}")
                logger.info(f"  回撤: {drawdown*100:.2f}% (阈值: {p0_tracking_threshold*100:.1f}%)")
                logger.info(f"  仓位: {position}/5 → 目标: {target_pos}/5")
                logger.info(f"  {pos_reason}")  # v19: 显示Position Control状态
                logger.info("=" * 70)

                # v8.0: 标记本周期已触发
                self.tracking_state[symbol]["triggered_action"] = "SELL"
                # 更新基准价为当前价
                self.tracking_state[symbol]["peak_price"] = current_price

                # 记录触发历史
                self.tracking_state[symbol].setdefault("trigger_history", []).append({
                    "action": "SELL",
                    "time": datetime.now().isoformat(),
                    "price": current_price,
                })

                # v19: 获取仓位控制规则描述
                position_rule_desc = self._get_position_rule_desc(position, "SELL")

                signal_data = {
                    "signal": "SELL",
                    "price": current_price,
                    "base_price": peak_price,
                    "change_pct": round(-drawdown * 100, 2),
                    "threshold": p0_tracking_threshold * 100,
                    "timeframe": timeframe,
                    "timestamp": datetime.now().isoformat(),
                    "type": "crypto" if is_crypto else "stock",
                    "signal_type": "P0-Tracking",
                    # v19: 仓位控制信息
                    "position_units": position,
                    "target_position": target_pos,  # v19: 目标仓位(激进卖出)
                    "sell_units": position - target_pos,  # v19: 要卖出的档数
                    "position_control_rule": position_rule_desc,
                }

                # v16.6: 直接通知服务器，P0-Tracking独立运行
                main_symbol = REVERSE_SYMBOL_MAP.get(symbol, symbol)
                server_response = self._notify_main_server(main_symbol, signal_data)
                signal_data["server_executed"] = server_response.get("executed", False)
                signal_data["server_reason"] = server_response.get("reason", "")

                # 只在实际执行成功时发送邮件和消耗配额
                if server_response.get("executed", False):
                    # v20.1: 5→4卖出时添加K线冻结信息到邮件
                    if position == 5:
                        signal_data["bar_freeze_info"] = f"同K线单方向冻结(SELL, 最多2次)"
                    self.email_notifier.send_signal_notification(symbol, signal_data)
                    self.tracking_state[symbol]["sell_used"] = True
                    self.tracking_state[symbol]["reset_date"] = get_today_date_ny()
                    self._check_and_freeze(symbol)
                    # v16.8→v20.2: 显示完整状态
                    st = self.tracking_state[symbol]
                    round1 = f"买[{'✓' if st.get('buy_used') else '○'}]卖[✓]"
                    stop_cnt = st.get('trailing_stop_count', 0)
                    buy_cnt = st.get('trailing_buy_count', 0)
                    round2 = f"止损[{stop_cnt}/2]止盈[{buy_cnt}/2]"
                    th = st.get('trailing_high')
                    th_str = f"{th:.2f}" if th else "无"
                    logger.info(f"[v16.8] {symbol} P0-Tracking SELL已执行")
                    logger.info(f"  来回1({round1}) 来回2({round2})")
                    logger.info(f"  peak={peak_price:.2f} | trailing_high={th_str}")
                    # v17.2: 设置P0抓顶保护 (阻止其他外挂BUY)
                    protect_until = set_p0_sell_protection(st)
                    logger.info(f"  [v17.2] P0抓顶保护已设置: 至{protect_until}或L1=DOWN")
                    # v21.17: 同K线单方向冻结记录
                    _bar_start = self.tracking_state[symbol].get("period_start")
                    if _bar_start and _bar_start == st.get("bar_freeze_bar_start") and st.get("bar_freeze_dir") == "SELL":
                        st["bar_freeze_count"] = st.get("bar_freeze_count", 0) + 1
                    else:
                        st["bar_freeze_dir"] = "SELL"
                        st["bar_freeze_count"] = 1
                        st["bar_freeze_bar_start"] = _bar_start
                    logger.info(f"  [v21.17] K线冻结: SELL x{st['bar_freeze_count']} bar={_bar_start[:16] if _bar_start else 'None'}")
                    self._save_tracking_state()  # v17.2: 立即保存，防止重启丢失
                else:
                    logger.info(f"[{symbol}] P0-Tracking SELL: 未执行({server_response.get('reason', '')}), 不消耗配额")

                # 外挂利润追踪
                if self.profit_tracker:
                    self.profit_tracker.record_trade(
                        symbol=main_symbol, plugin_name="P0-Tracking",
                        action="SELL", price=current_price,
                        executed=server_response.get("executed", False),
                        asset_type="crypto" if is_crypto else "stock")

        # v8.2: 不满仓时可买入 (position < 5)
        if position < 5:
            trough_price = self.tracking_state[symbol].get("trough_price")

            if trough_price is None:
                # v11.0: 检查是否需要安全初始化（解冻后或状态恢复）
                needs_safe_init = self.tracking_state[symbol].get("_needs_safe_init", False)

                if needs_safe_init or self._is_in_startup_cooldown():
                    # v11.0: 使用当前价作为基准，避免历史价格跳跃
                    trough_price = current_price
                    self.tracking_state[symbol]["trough_price"] = trough_price
                    self.tracking_state[symbol]["_needs_safe_init"] = False
                    logger.info(f"[{symbol}] v11.0 安全初始化trough_price: {trough_price:.2f} (当前价)")
                else:
                    # v20.3: 回溯历史数据，优先使用局部低点
                    local_high, local_low, high_type, low_type = YFinanceDataFetcher.get_first_local_extremes(
                        symbol, self.config["tracking"]["lookback_bars"]
                    )
                    # v11.1+v20.3: 使用中间值初始化，避免历史价格导致虚假涨幅
                    # 公式: 新基准 = 低点 + (当前价 - 低点) / 2
                    if local_low and current_price > local_low:
                        trough_price = local_low + (current_price - local_low) / 2
                        logger.info(f"[{symbol}] 回溯初始化trough_price: {trough_price:.2f} (中间值: {low_type}={local_low:.2f}, current={current_price:.2f})")
                    else:
                        trough_price = current_price
                        logger.info(f"[{symbol}] 回溯初始化trough_price: {trough_price:.2f} (当前价)")
                    self.tracking_state[symbol]["trough_price"] = trough_price

            # 更新trough_price
            if current_price < trough_price:
                self.tracking_state[symbol]["trough_price"] = current_price
                trough_price = current_price

            # 检查买入触发
            rise = (current_price - trough_price) / trough_price

            # v20.1: P0-Tracking使用独立阈值 (加密/美股都是5%)
            # v20.3: 移除仓位限制，局部极值点已降低误触发风险
            if rise >= p0_tracking_threshold:
                # v3.546: 检查今日买入是否已用完
                can_buy, limit_reason = check_plugin_daily_limit(self.tracking_state[symbol], "BUY")
                if not can_buy:
                    logger.info(f"[v3.546] {symbol} P0-Tracking BUY 被限制: {limit_reason}")
                    return

                # v11.0: 启动冷却期内不触发信号
                if self._is_in_startup_cooldown():
                    elapsed = time.time() - self.startup_time
                    remaining = self.STARTUP_COOLDOWN_SECONDS - elapsed
                    logger.info(f"[{symbol}] v11.0 启动冷却期内，跳过BUY信号 (剩余 {remaining:.0f}秒)")
                    return

                # v11.2: 美股开盘缓冲期内不触发信号
                if self._is_in_market_open_cooldown(symbol):
                    cooldown_until = self.tracking_state[symbol].get("market_open_cooldown_until", "")[:19]
                    logger.info(f"[{symbol}] v11.2 开盘缓冲期内，跳过BUY信号 (至 {cooldown_until})")
                    return

                # v16.6: P0-Tracking完全独立运行，不依赖L1/飞云外挂

                # v17.3: Position Control检查
                trend_info = self._get_trend_for_plugin(symbol)
                big_trend = trend_info.get("trend_x4", "SIDE") if trend_info else "SIDE"
                current_trend = trend_info.get("trend", "SIDE") if trend_info else "SIDE"
                # v17.3: 计算EMA10 (仓位0-4都需要)
                ema10 = 0.0
                _p0_tf = read_symbol_timeframe(symbol, default=240)
                _p0_params = get_timeframe_params(_p0_tf, is_crypto=is_crypto_symbol(symbol))
                _p0_lookback = max(20, int(_p0_params["bars_per_day"] * 3))  # v20: ~3天bar数，EMA10足够
                bars = YFinanceDataFetcher.get_ohlcv(symbol, _p0_tf, _p0_lookback)
                if bars:
                    ema10 = calculate_ema10(bars)
                pos_allowed, pos_reason, target_pos = check_position_control(
                    position, "BUY", big_trend, current_trend, "P0-Tracking",
                    current_price, ema10, bars
                )
                log_signal_decision(symbol, "BUY", position, pos_allowed, pos_reason, target_pos, "P0-Tracking", current_price, big_trend, current_trend)
                if not pos_allowed:
                    logger.info("=" * 70)
                    logger.info(f"[v19] {symbol} P0-Tracking BUY → HOLD")
                    logger.info(f"  ├─ 当前仓位: {position}/5")
                    logger.info(f"  ├─ 当前价格: {current_price:.2f}")
                    logger.info(f"  └─ 原因: {pos_reason}")
                    logger.info("=" * 70)
                    return

                # v20.1: 首档K线内冻结检查
                current_bar_start = self.tracking_state[symbol].get("period_start", "")
                bar_ok, bar_reason = check_first_position_bar_freeze(
                    self.tracking_state[symbol], "BUY", position, current_bar_start)
                if not bar_ok:
                    logger.info(f"[v20.1] {symbol} P0-Tracking BUY → HOLD | {bar_reason}")
                    return

                # 触发买入
                logger.info("=" * 70)
                logger.info(f"[P0-Tracking] {symbol} BUY 触发!")
                logger.info(f"  trough_price: {trough_price:.2f}")
                logger.info(f"  当前价: {current_price:.2f}")
                logger.info(f"  涨幅: {rise*100:.2f}% (阈值: {p0_tracking_threshold*100:.1f}%)")
                logger.info(f"  仓位: {position}/5 → 目标: {target_pos}/5")
                logger.info(f"  {pos_reason}")  # v19: 显示Position Control状态
                logger.info("=" * 70)

                # v8.0: 标记本周期已触发
                self.tracking_state[symbol]["triggered_action"] = "BUY"
                # 更新基准价为当前价
                self.tracking_state[symbol]["trough_price"] = current_price

                # 记录触发历史
                self.tracking_state[symbol].setdefault("trigger_history", []).append({
                    "action": "BUY",
                    "time": datetime.now().isoformat(),
                    "price": current_price,
                })

                # v19: 获取仓位控制规则描述
                position_rule_desc = self._get_position_rule_desc(position, "BUY")

                signal_data = {
                    "signal": "BUY",
                    "price": current_price,
                    "base_price": trough_price,
                    "change_pct": round(rise * 100, 2),
                    "threshold": p0_tracking_threshold * 100,
                    "timeframe": timeframe,
                    "timestamp": datetime.now().isoformat(),
                    "type": "crypto" if is_crypto else "stock",
                    "signal_type": "P0-Tracking",
                    # v19: 仓位控制信息
                    "position_units": position,
                    "target_position": target_pos,  # v19: 目标仓位
                    "position_control_rule": position_rule_desc,
                }

                # v16.6: 直接通知服务器，P0-Tracking独立运行
                main_symbol = REVERSE_SYMBOL_MAP.get(symbol, symbol)
                server_response = self._notify_main_server(main_symbol, signal_data)
                signal_data["server_executed"] = server_response.get("executed", False)
                signal_data["server_reason"] = server_response.get("reason", "")

                # 只在实际执行成功时发送邮件和消耗配额
                if server_response.get("executed", False):
                    # v20.1: 0→1买入时添加K线冻结信息到邮件
                    if position == 0:
                        signal_data["bar_freeze_info"] = "首买K线冻结已激活(同K线内禁止清仓)"
                    self.email_notifier.send_signal_notification(symbol, signal_data)
                    self.tracking_state[symbol]["buy_used"] = True
                    self.tracking_state[symbol]["reset_date"] = get_today_date_ny()
                    self._check_and_freeze(symbol)
                    # v16.8→v20.2: 显示完整状态
                    st = self.tracking_state[symbol]
                    round1 = f"买[✓]卖[{'✓' if st.get('sell_used') else '○'}]"
                    stop_cnt = st.get('trailing_stop_count', 0)
                    buy_cnt = st.get('trailing_buy_count', 0)
                    round2 = f"止损[{stop_cnt}/2]止盈[{buy_cnt}/2]"
                    tl = st.get('trailing_low')
                    tl_str = f"{tl:.2f}" if tl else "无"
                    logger.info(f"[v16.8] {symbol} P0-Tracking BUY已执行")
                    logger.info(f"  来回1({round1}) 来回2({round2})")
                    logger.info(f"  trough={trough_price:.2f} | trailing_low={tl_str}")
                    # v17.2: 设置P0抄底保护 (阻止其他外挂SELL)
                    protect_until = set_p0_buy_protection(st)
                    logger.info(f"  [v17.2] P0抄底保护已设置: 至{protect_until}或L1=UP")
                    # v21.17: 同K线单方向冻结记录
                    _bar_start = self.tracking_state[symbol].get("period_start")
                    if _bar_start and _bar_start == st.get("bar_freeze_bar_start") and st.get("bar_freeze_dir") == "BUY":
                        st["bar_freeze_count"] = st.get("bar_freeze_count", 0) + 1
                    else:
                        st["bar_freeze_dir"] = "BUY"
                        st["bar_freeze_count"] = 1
                        st["bar_freeze_bar_start"] = _bar_start
                    logger.info(f"  [v21.17] K线冻结: BUY x{st['bar_freeze_count']} bar={_bar_start[:16] if _bar_start else 'None'}")
                    self._save_tracking_state()  # v17.2: 立即保存，防止重启丢失
                else:
                    logger.info(f"[{symbol}] P0-Tracking BUY: 未执行({server_response.get('reason', '')}), 不消耗配额")

                # 外挂利润追踪
                if self.profit_tracker:
                    self.profit_tracker.record_trade(
                        symbol=main_symbol, plugin_name="P0-Tracking",
                        action="BUY", price=current_price,
                        executed=server_response.get("executed", False),
                        asset_type="crypto" if is_crypto else "stock")

        # v16.8: 移动止损已在函数开头调用（独立于冻结状态）

    def _get_atr_threshold(self, symbol: str, current_price: float) -> tuple:
        """
        v20.5: 计算ATR(14)动态阈值
        返回: (atr_threshold_pct, atr_value, multiplier, asset_type, regime_key)
        - atr_threshold_pct: 阈值百分比 (1%~上限按资产类型)
        - atr_value: ATR(14)原始值(美元)
        - multiplier: ATR倍数
        - asset_type: 资产分类
        - regime_key: 市场状态 (TRENDING/DEFAULT/RANGING)
        """
        fallback_threshold = self.config.get("crypto", {}).get("tracking_threshold", 0.025)
        if not is_crypto_symbol(symbol):
            fallback_threshold = self.config.get("stock", {}).get("tracking_threshold", 0.025)

        state = self.tracking_state.get(symbol)
        if state is None:
            # 理论上不会发生 (_check_tracking_period_reset已初始化)
            asset_type = _classify_asset_type(symbol)
            return (fallback_threshold, 0.0, 0.0, asset_type, "FALLBACK")

        # 1. 判断是否需要重算ATR
        need_recalc = False
        if not self._atr_startup_recalculated:
            # 重启后首轮: 强制重算 (忽略state文件中的缓存)
            need_recalc = True
        else:
            cache_until_str = state.get("atr_cache_until")
            if cache_until_str:
                try:
                    cache_until = datetime.fromisoformat(cache_until_str)
                    ny_now = get_ny_now()
                    if cache_until.tzinfo is None:
                        cache_until = cache_until.replace(tzinfo=ZoneInfo("America/New_York"))
                    if ny_now >= cache_until:
                        need_recalc = True  # 缓存过期
                except Exception:
                    need_recalc = True
            else:
                need_recalc = True  # 无缓存

        # 2. 使用缓存或重算
        atr_value = state.get("atr_cache_value")
        if not need_recalc and atr_value is not None and atr_value > 0:
            pass  # 使用缓存的atr_value
        else:
            # 重算ATR(14)
            try:
                _tf_minutes = read_symbol_timeframe(symbol, default=240)
                _tf_params = get_timeframe_params(_tf_minutes, is_crypto=is_crypto_symbol(symbol))
                _lookback = max(20, int(_tf_params["bars_per_day"] * 3))
                bars = YFinanceDataFetcher.get_ohlcv(symbol, _tf_minutes, _lookback)
                if bars and len(bars) >= 15:
                    atr_value = _calculate_atr_14(bars)
                    # v21.14 SYS-032: 顺带更新volume到tracking_state(复用OHLCV,无额外请求)
                    if len(bars) >= 2:
                        _last_vol = float(bars[-1].get("volume", bars[-1].get("v", 0)))
                        _vol_window = bars[-20:] if len(bars) >= 20 else bars
                        _avg_vol = sum(float(b.get("volume", b.get("v", 0))) for b in _vol_window) / len(_vol_window)
                        state["last_volume"] = _last_vol
                        state["avg_volume"] = _avg_vol
                else:
                    atr_value = 0.0
            except Exception as e:
                logger.warning(f"[{symbol}] ATR计算异常: {e}")
                atr_value = 0.0

            # 缓存结果
            if atr_value > 0:
                next_8am = get_next_8am_ny()
                state["atr_cache_value"] = atr_value
                state["atr_cache_until"] = next_8am.isoformat()
                logger.info(f"[{symbol}] ATR(14)=${atr_value:.2f} (缓存至{next_8am.strftime('%Y-%m-%d %H:%M')} NY)")
            else:
                logger.warning(f"[{symbol}] ATR计算失败，使用固定阈值{fallback_threshold*100:.1f}%")

        # 3. ATR失败时fallback
        if not atr_value or atr_value <= 0:
            asset_type = _classify_asset_type(symbol)
            return (fallback_threshold, 0.0, 0.0, asset_type, "FALLBACK")

        # 4. 资产分类 → 倍数表查找
        asset_type = _classify_asset_type(symbol)
        trend_info = self._get_trend_for_plugin(symbol)
        regime_key = _get_market_regime_for_atr(trend_info)
        multiplier_table = ATR_MULTIPLIER_TABLE.get(asset_type, ATR_MULTIPLIER_TABLE["山寨币"])
        multiplier = multiplier_table.get(regime_key, multiplier_table["DEFAULT"])

        # 5. 计算阈值百分比
        if current_price <= 0:
            return (fallback_threshold, atr_value, 0.0, asset_type, "FALLBACK")
        atr_threshold_pct = (atr_value * multiplier) / current_price

        # 6. 安全边界 clamp [1%, 上限按资产类型]
        upper = ATR_CLAMP_UPPER.get(asset_type, 0.10)
        if atr_threshold_pct < 0.01 or atr_threshold_pct > upper:
            logger.info(f"[{symbol}] ATR阈值{atr_threshold_pct*100:.2f}%超出范围，clamp到[1%, {upper*100:.0f}%]")
        atr_threshold_pct = max(0.01, min(upper, atr_threshold_pct))

        # v21.12 RES-008: 持仓时间衰减 + 制度倍数 (arXiv:2602.12030)
        # Phase 1: 仅记录, 不调整实际阈值
        # 时间衰减: atr *= (1 - DECAY_RATE * holding_hours / EXPECTED_HOURS), clamp [0.7, 1.0]
        # 制度倍数: atr *= atr_regime_mult (INITIAL=1.15放宽/FINAL=0.85收紧)
        HOLDING_DECAY_ENABLED = False  # Phase 1
        HOLDING_DECAY_RATE = 0.3
        HOLDING_EXPECTED_HOURS = {"科技股": 48, "BTC": 72, "ETH": 72, "中型币": 48, "山寨币": 48}
        # v21.12: 读取趋势阶段的ATR制度倍数
        _tp = self._current_trend_phase.get(symbol, {})
        _atr_regime_mult = _tp.get("risk_budget", {}).get("atr_regime_mult", 1.0)
        _entry_ts = state.get("entry_timestamp")
        if _entry_ts:
            try:
                _entry_dt = datetime.fromisoformat(_entry_ts)
                _holding_hours = (get_ny_now() - _entry_dt.replace(
                    tzinfo=ZoneInfo("America/New_York") if _entry_dt.tzinfo is None else _entry_dt.tzinfo
                )).total_seconds() / 3600
                _expected = HOLDING_EXPECTED_HOURS.get(asset_type, 48)
                _decay = max(0.7, 1.0 - HOLDING_DECAY_RATE * _holding_hours / _expected)
                _combined = _decay * _atr_regime_mult
                _adjusted_threshold = atr_threshold_pct * _combined
                if HOLDING_DECAY_ENABLED:
                    atr_threshold_pct = _adjusted_threshold
                elif _holding_hours > 6:  # 只记录持仓>6h的
                    _phase_label = _tp.get("phase", "?")
                    _regime_label = _tp.get("market_regime", "?")
                    print(f"[v21.12] 时间衰减[观察]: {symbol} 持仓{_holding_hours:.0f}h "
                          f"phase={_phase_label} regime={_regime_label} "
                          f"ATR阈值 原{atr_threshold_pct*100:.2f}%→建议{_adjusted_threshold*100:.2f}% "
                          f"(decay={_decay:.2f} x regime={_atr_regime_mult:.2f} = {_combined:.2f}, 未启用)")
            except Exception:
                pass

        # v21.11 SYS-028: VP止损锚定 (Phase2: 实际替换ATR止损)
        _SYS028_ENABLED = True
        if atr_value > 0 and current_price > 0:
            try:
                _tf_min = read_symbol_timeframe(symbol, default=240)
                _tf_p = get_timeframe_params(_tf_min, is_crypto=is_crypto_symbol(symbol))
                _vp_lookback = max(50, int(_tf_p["bars_per_day"] * 3))
                _vp_bars = YFinanceDataFetcher.get_ohlcv(symbol, _tf_min, _vp_lookback)
                if _vp_bars and len(_vp_bars) >= 10:
                    _atr_stop = current_price * (1 - atr_threshold_pct)
                    _vp_anchor = _vol_analyzer.anchor_stop_to_hvn(
                        _vp_bars, current_price, _atr_stop, "SELL")
                    if _vp_anchor["anchored"]:
                        _vp_new_pct = 1 - _vp_anchor["suggested_stop"] / current_price
                        # v21.31: VP压缩下限 — 不低于原ATR阈值的50%(防止极端压缩→价差过小)
                        _vp_floor = atr_threshold_pct * 0.5
                        if _SYS028_ENABLED and _vp_floor < _vp_new_pct < atr_threshold_pct:
                            _old_pct = atr_threshold_pct
                            atr_threshold_pct = _vp_new_pct
                            logger.info(f"[SYS-028] VP止损锚定: {symbol} "
                                        f"ATR止损={_atr_stop:.2f}→VP={_vp_anchor['suggested_stop']:.2f} "
                                        f"阈值{_old_pct:.3%}→{atr_threshold_pct:.3%} "
                                        f"HVN={_vp_anchor['nearest_hvn']:.2f}")
                        else:
                            _skip = "压缩过大" if 0 < _vp_new_pct <= _vp_floor else "方向不符"
                            logger.info(f"[SYS-028] VP止损锚定[跳过:{_skip}]: {symbol} "
                                        f"ATR止损={_atr_stop:.2f} VP建议={_vp_anchor['suggested_stop']:.2f} "
                                        f"HVN={_vp_anchor['nearest_hvn']:.2f} "
                                        f"(VP={_vp_new_pct:.3%} floor={_vp_floor:.3%})")
            except Exception:
                pass

        return (atr_threshold_pct, atr_value, multiplier, asset_type, regime_key)

    def _check_trailing_stop(self, symbol: str, current_price: float, is_crypto: bool,
                             position: int, tracking_threshold: float, timeframe: str):
        """
        v16.8: 移动止损/止盈检查
        v16.9: 添加独立的日期重置检查

        移动止损 (Trailing Stop):
        - 有持仓时激活
        - 从入场价开始追踪最高价
        - 从最高价回撤X%触发SELL
        - v20.2: 最多2次SELL配额 (trailing_stop_count)

        移动止盈 (Trailing Buy):
        - 空仓/轻仓时激活
        - 追踪最低价
        - 从最低价上涨X%触发BUY
        - v20.2: 最多2次BUY配额 (trailing_buy_count)

        配额说明 (v20.7更新):
        - 原P0-Tracking: buy_used + sell_used (各1次, 已禁用)
        - 移动止损/止盈: trailing_stop_count + trailing_buy_count (各最多2次)
          - 第1次: ATR(14)动态阈值
          - 第2次: 固定阈值 (美股2.75%, BTC/ETH 3.0%, SOL 3.25%, ZEC 3.5%)
        - v20.7: 中间仓位只用固定阈值
          - BUY(止盈): 仓位2/3/4=固定, 仓位0/1=双阈值
          - SELL(止损): 仓位4/3/2=固定, 仓位5/1=双阈值
        """
        state = self.tracking_state[symbol]

        # v21.7: current_price 无效防护
        if current_price is None or current_price <= 0:
            logger.warning(f"[v21.7] {symbol} current_price无效({current_price}), 跳过移动止损检查")
            return

        # v16.9: 移动止损独立日期重置检查
        today = get_today_date_ny()
        trailing_reset_date = state.get("trailing_reset_date")
        if trailing_reset_date != today:
            # 检查冻结是否仍有效
            freeze_str = state.get("freeze_until")
            still_frozen = False
            if freeze_str:
                try:
                    freeze_dt = datetime.fromisoformat(freeze_str)
                    ny_now = get_ny_now()
                    if freeze_dt.tzinfo is None:
                        freeze_dt = freeze_dt.replace(tzinfo=ZoneInfo("America/New_York"))
                    still_frozen = ny_now < freeze_dt
                except Exception:
                    pass

            if not still_frozen:
                # 新一天且未冻结，重置移动止损/止盈配额
                state["trailing_stop_count"] = 0  # v20.2: 计数器重置
                state["trailing_buy_count"] = 0   # v20.2: 计数器重置
                state["trailing_high"] = None
                state["trailing_low"] = None
                # v17.2: 重置P0信号保护
                state["p0_buy_protection_until"] = None
                state["p0_sell_protection_until"] = None
                state["trailing_reset_date"] = today
                logger.info(f"[{symbol}] v16.9 移动止损新一天重置: 止损[0/2]止盈[0/2]+P0保护[○]")

        # v20.5: 计算ATR动态阈值
        atr_threshold, atr_value, atr_multiplier, asset_type, regime_key = \
            self._get_atr_threshold(symbol, current_price)

        # v21.13 SYS-032: 分批退出调度器 — 流动性评分 (Phase 1 观察)
        # 流动性 = 唐纳奇通道宽度 × 成交量 → 退出速度建议
        EXIT_SCHEDULER_ENABLED = False  # Phase 1
        if position >= 3 and atr_value and atr_value > 0:
            try:
                # 唐纳奇通道宽度(相对): ATR / 当前价 → 波动率代理
                _dc_width_pct = atr_value / current_price if current_price > 0 else 0
                # 成交量: 从tracking_state获取最近成交量(如果有)
                _recent_vol = state.get("last_volume", 0)
                _avg_vol = state.get("avg_volume", 0)
                _vol_ratio = _recent_vol / _avg_vol if _avg_vol > 0 else 1.0
                # 流动性评分 [0-100]: 高=流动性好可快速退出, 低=应放慢
                _liquidity = min(100, max(0, int(_vol_ratio * 50 + (1 - min(_dc_width_pct * 20, 1)) * 50)))
                # 退出建议: 高位满仓+低流动性→分批, 高流动性→可直接退
                if _liquidity < 30:
                    _exit_advice = "SLOW"   # 流动性差,建议分批(5→3→1→0)
                elif _liquidity < 60:
                    _exit_advice = "NORMAL"  # 正常速度退出
                else:
                    _exit_advice = "FAST"    # 流动性好,可快速退出
                # 高ATR时额外警告
                _high_atr_tag = " [高ATR放慢退出]" if _dc_width_pct > 0.04 else ""
                logger.info(f"[EXIT_SCHEDULER] {symbol} pos={position} liquidity={_liquidity} "
                              f"→{_exit_advice}{_high_atr_tag} | "
                              f"atr_pct={_dc_width_pct:.3f} vol_ratio={_vol_ratio:.2f}")
            except Exception:
                pass

        # 检查是否在冷却期
        if self._is_in_startup_cooldown():
            return
        if self._is_in_market_open_cooldown(symbol):
            return

        # ====== 移动止损 (有持仓时) ======
        if position > 0:
            # 获取入场价
            entry_price = self._get_entry_price_from_main_state(symbol)

            # 初始化或更新trailing_high
            trailing_high = state.get("trailing_high")
            if trailing_high is None:
                # 没有值 → 用入场价初始化
                if entry_price > 0:
                    trailing_high = entry_price
                    state["trailing_high"] = trailing_high
                    logger.info(f"[{symbol}] v16.8 移动止损初始化: trailing_high={trailing_high:.2f} (入场价)")
                else:
                    # 无法获取入场价，用当前价
                    trailing_high = current_price
                    state["trailing_high"] = trailing_high
                    logger.info(f"[{symbol}] v16.8 移动止损初始化: trailing_high={trailing_high:.2f} (当前价)")

            # 更新最高价
            if current_price > trailing_high:
                state["trailing_high"] = current_price
                trailing_high = current_price
                logger.debug(f"[{symbol}] 移动止损更新: trailing_high={trailing_high:.2f}")

            # 检查是否触发止损
            if trailing_high > 0:
                drawdown = (trailing_high - current_price) / trailing_high
                # v21.x: 纯ATR动态阈值，全仓位统一使用ATR(14)×倍数
                effective_threshold = atr_threshold
                if drawdown >= effective_threshold:
                    # v20.5: 获取K线数据 (急跌检测+Position Control共用)
                    _p0_tf = read_symbol_timeframe(symbol, default=240)
                    _p0_params = get_timeframe_params(_p0_tf, is_crypto=is_crypto_symbol(symbol))
                    _p0_lookback = max(50, int(_p0_params["bars_per_day"] * 3))
                    bars = YFinanceDataFetcher.get_ohlcv(symbol, _p0_tf, _p0_lookback)
                    if not bars or len(bars) < 20:
                        logger.warning(f"[v21.7] {symbol} 移动止损K线不足: 需要20根, 获得{len(bars) if bars else 0}")
                    ema10 = calculate_ema10(bars) if bars else 0.0

                    # v20.5: 配额检查 (急跌时绕过2次/天限制)
                    stop_count = state.get("trailing_stop_count", 0)
                    crash, drop_pct = is_crash_bar(bars, current_price)

                    # v21.18: 30分钟发送冷却 (crash-sell豁免)
                    if not crash:
                        _cd_key = f"{symbol}_SELL"
                        _cd_until = self._trailing_send_cooldown.get(_cd_key)
                        if _cd_until and datetime.now() < _cd_until:
                            _cd_remain = (_cd_until - datetime.now()).total_seconds() / 60
                            logger.info(f"[v21.18] {symbol} 移动止损 SELL → 冷却中(剩余{_cd_remain:.0f}min)")
                            return

                    # v21.30: N字门控已转外挂，仅观察日志(与主程序v3.671对齐)
                    _ng = self._load_n_gate_state()
                    _ms = REVERSE_SYMBOL_MAP.get(symbol, symbol)
                    if (not crash) and _ng.get(f"{_ms}_SELL", {}).get("block", False):
                        _ng_reason = _ng.get(f"{_ms}_SELL", {}).get("reason", "")
                        logger.info(f"[N_GATE][观察] {symbol} SELL 移动止损: {_ng_reason} (已转外挂,不拦截)")
                    if stop_count >= 1 and not crash:
                        pass  # 配额已用完且非急跌，跳过卖出 (安全期: 1次/天)
                    else:
                        if stop_count >= 1 and crash:
                            logger.info(f"[v20.5] {symbol} 移动止损急跌保护: 绕过配额限制(跌{drop_pct:.1f}%≥{CRASH_SELL_THRESHOLD_PCT}%)")
                        # v21.21: 唐纳奇支撑保护 — 固定底部10%区间 (不再区分regime)
                        # 历史有效率3%说明regime分类无效，简化为绝对边界
                        if not crash and bars and len(bars) >= 20:
                            _dc_highs = [b["high"] for b in bars[-20:]]
                            _dc_lows = [b["low"] for b in bars[-20:]]
                            _dc_upper, _dc_lower = max(_dc_highs), min(_dc_lows)
                            _dc_range = _dc_upper - _dc_lower
                            if _dc_range > 0:
                                _dc_pos = (current_price - _dc_lower) / _dc_range
                                if _dc_pos < 0.10:
                                    logger.info(f"[v21.21] {symbol} 移动止损 SELL → HOLD | 支撑保护(pos={_dc_pos:.1%}<10%, DC={_dc_lower:.2f}-{_dc_upper:.2f})")
                                    return
                        # v17.3: Position Control检查
                        trend_info = self._get_trend_for_plugin(symbol)
                        big_trend = trend_info.get("trend_x4", "SIDE") if trend_info else "SIDE"
                        current_trend = trend_info.get("trend", "SIDE") if trend_info else "SIDE"
                        pos_allowed, pos_reason, target_pos = check_position_control(
                            position, "SELL", big_trend, current_trend, "移动止损",
                            current_price, ema10, bars
                        )
                        log_signal_decision(symbol, "SELL", position, pos_allowed, pos_reason, target_pos, "移动止损", current_price, big_trend, current_trend)
                        if not pos_allowed:
                            logger.info("=" * 70)
                            logger.info(f"[v19] {symbol} 移动止损 SELL → HOLD")
                            logger.info(f"  ├─ 当前仓位: {position}/5")
                            logger.info(f"  ├─ 当前价格: {current_price:.2f}")
                            logger.info(f"  └─ 原因: {pos_reason}")
                            logger.info("=" * 70)
                            return

                        # v20.1: 首档K线内冻结检查 (v20.5: 传入bars用于急跌检测)
                        current_bar_start = self.tracking_state[symbol].get("period_start", "")
                        bar_ok, bar_reason = check_first_position_bar_freeze(
                            self.tracking_state[symbol], "SELL", position, current_bar_start,
                            bars=bars, current_price=current_price)
                        if not bar_ok:
                            logger.info(f"[v20.1] {symbol} 移动止损 SELL → HOLD | {bar_reason}")
                            return

                        # v21.23 SYS-032: 分批退出调度器 (Phase2: 真实覆盖target_pos)
                        EXIT_SCHEDULER_ENABLED = True  # Phase2
                        _atr_v = self.tracking_state[symbol].get("atr_cache_value")
                        _exit_plan = optimal_exit_scheduler(
                            position, target_pos, bars, current_price, _atr_v, symbol)
                        if _exit_plan["step"] > 1:
                            if EXIT_SCHEDULER_ENABLED and _exit_plan["recommended_target"] > target_pos:
                                _orig_target = target_pos
                                target_pos = _exit_plan["recommended_target"]
                                logger.info(
                                    f"[SYS-032] {symbol} 分批退出: {position}→{target_pos}档"
                                    f"(原目标{_orig_target}档,步长{_exit_plan['step']}) "
                                    f"流动性={_exit_plan['liquidity']:.1f} ATR={_exit_plan['atr_pct']:.1%} "
                                    f"({_exit_plan['reason']})"
                                )
                            else:
                                logger.info(
                                    f"[SYS-032][观察] {symbol} 移动止损 建议{position}→"
                                    f"{_exit_plan['recommended_target']}档(步长{_exit_plan['step']}) "
                                    f"流动性={_exit_plan['liquidity']:.1f} ATR={_exit_plan['atr_pct']:.1%} "
                                    f"({_exit_plan['reason']})"
                                )

                        logger.info("=" * 70)
                        logger.info(f"[S2][移动止损] {symbol} SELL 触发!")
                        logger.info(f"  trailing_high: {trailing_high:.2f}")
                        logger.info(f"  入场价: {entry_price:.2f}")
                        logger.info(f"  当前价: {current_price:.2f}")
                        _th_label = f"ATR阈值: {effective_threshold*100:.2f}% (ATR=${atr_value:.2f} x{atr_multiplier})"
                        logger.info(f"  回撤: {drawdown*100:.2f}% ({_th_label})")
                        # v21.4: 通道位置日志(便于分析止损是否过紧)
                        if bars and len(bars) >= 20:
                            _sl_dc_highs = [b["high"] for b in bars[-20:]]
                            _sl_dc_lows = [b["low"] for b in bars[-20:]]
                            _sl_dc_upper, _sl_dc_lower = max(_sl_dc_highs), min(_sl_dc_lows)
                            _sl_dc_range = _sl_dc_upper - _sl_dc_lower
                            _sl_dc_pos = (current_price - _sl_dc_lower) / _sl_dc_range if _sl_dc_range > 0 else 0.5
                            logger.info(f"  通道位置: {_sl_dc_pos:.1%} (DC20={_sl_dc_lower:.2f}-{_sl_dc_upper:.2f})")
                        logger.info(f"  仓位: {position}/5 → 目标: {target_pos}/5")
                        logger.info(f"  {pos_reason}")  # v18
                        logger.info("=" * 70)

                        # 记录触发历史
                        state.setdefault("trigger_history", []).append({
                            "action": "TRAILING_STOP_SELL",
                            "time": datetime.now().isoformat(),
                            "price": current_price,
                            "trailing_high": trailing_high,
                            "atr_threshold": round(effective_threshold * 100, 2),  # v20.6: 固定阈值
                            "asset_type": asset_type,
                        })

                        # v19: 获取仓位控制规则描述
                        position_rule_desc = self._get_position_rule_desc(position, "SELL")

                        signal_data = {
                            "signal": "SELL",
                            "price": current_price,
                            "base_price": trailing_high,
                            "change_pct": round(-drawdown * 100, 2),
                            "threshold": round(effective_threshold * 100, 2),  # v20.6: 固定阈值
                            "timeframe": timeframe,
                            "timestamp": datetime.now().isoformat(),
                            "type": "crypto" if is_crypto else "stock",
                            "signal_type": "移动止损",
                            "entry_price": entry_price,
                            # v19: 仓位控制信息
                            "position_units": position,
                            "target_position": target_pos,  # v19: 目标仓位(激进卖出)
                            "sell_units": position - target_pos,  # v19: 要卖出的档数
                            "position_control_rule": position_rule_desc,
                            # v20.6: ATR详情 + 阈值类型
                            "atr_value": atr_value,
                            "atr_multiplier": atr_multiplier,
                            "atr_asset_type": asset_type,
                            "atr_regime": regime_key,
                            "atr_threshold_pct": round(effective_threshold * 100, 2),
                            "threshold_type": "ATR",
                            "crash_sell": crash,  # v20.7: 暴跌标记
                        }

                        # v21.8: 移动止损共识度日志 (保命信号不拦截, 仅记录)
                        # v21.14修复: 传入实际trend_info(原传None→regime始终sideways)
                        _ts_consensus = calc_consensus_score(symbol, "SELL", self._get_trend_for_plugin(symbol))
                        log_consensus_score(symbol, "SELL", "移动止损", _ts_consensus)

                        # v3.660: 移动止损信号归入GCC-TM信号池(不再直接下单)
                        main_symbol = REVERSE_SYMBOL_MAP.get(symbol, symbol)
                        try:
                            from gcc_trading_module import gcc_push_signal as _gcc_push
                            _gcc_push(main_symbol, "TrailingStop", "SELL", confidence=0.8)
                            logger.info(f"[v3.660] {main_symbol} 移动止损SELL → GCC-TM信号池")
                        except Exception as _gp_err:
                            logger.warning(f"[v3.660] {main_symbol} gcc_push_signal失败: {_gp_err}")
                        # 仍通知服务器记录(会被GCC_TM_ONLY门控拦截,仅观察)
                        server_response = self._notify_main_server(main_symbol, signal_data)
                        signal_data["server_executed"] = server_response.get("executed", False)
                        signal_data["server_reason"] = server_response.get("reason", "")

                        # v21.18: 发送后30分钟冷却 (无论成败)
                        self._trailing_send_cooldown[f"{symbol}_SELL"] = datetime.now() + timedelta(minutes=30)

                        # 只在执行成功时消耗配额
                        if server_response.get("executed", False):
                            state["trailing_stop_count"] = state.get("trailing_stop_count", 0) + 1  # v20.2
                            # v21.5: 每次执行后双向重置基准价格(修复: 不重置导致来回交易)
                            state["trailing_high"] = current_price
                            state["trailing_low"] = current_price
                            # v20.1: 5→4卖出时添加K线冻结信息到邮件
                            if position == 5:
                                signal_data["bar_freeze_info"] = f"同K线单方向冻结(SELL, 最多2次)"
                            self.email_notifier.send_signal_notification(symbol, signal_data)
                            # v16.8→v20.2: 显示完整状态
                            round1 = f"买[{'✓' if state.get('buy_used') else '○'}]卖[{'✓' if state.get('sell_used') else '○'}]"
                            stop_cnt = state.get('trailing_stop_count', 0)
                            buy_cnt = state.get('trailing_buy_count', 0)
                            round2 = f"止损[{stop_cnt}/1]止盈[{buy_cnt}/1]"
                            pk = state.get('peak_price')
                            pk_str = f"{pk:.2f}" if pk else "无"
                            logger.info(f"[v16.8] {symbol} 移动止损SELL已执行")
                            logger.info(f"  来回1({round1}) 来回2({round2})")
                            logger.info(f"  入场价={entry_price:.2f} | 最高={trailing_high:.2f} | peak={pk_str}")
                            _th_exec = f"ATR(14)=${atr_value:.2f} x{atr_multiplier} → {effective_threshold*100:.2f}%"
                            logger.info(f"  {_th_exec}")
                            # v17.2: 设置P0抓顶保护 (阻止其他外挂BUY)
                            protect_until = set_p0_sell_protection(state)
                            logger.info(f"  [v17.2] P0抓顶保护已设置: 至{protect_until}或L1=DOWN")
                            # v21.17: 同K线单方向冻结记录
                            _bar_start = self.tracking_state[symbol].get("period_start")
                            if _bar_start and _bar_start == state.get("bar_freeze_bar_start") and state.get("bar_freeze_dir") == "SELL":
                                state["bar_freeze_count"] = state.get("bar_freeze_count", 0) + 1
                            else:
                                state["bar_freeze_dir"] = "SELL"
                                state["bar_freeze_count"] = 1
                                state["bar_freeze_bar_start"] = _bar_start
                            logger.info(f"  [v21.17] K线冻结: SELL x{state['bar_freeze_count']} bar={_bar_start[:16] if _bar_start else 'None'}")
                            self._save_tracking_state()  # v17.2: 立即保存，防止重启丢失
                        else:
                            logger.info(f"[{symbol}] 移动止损SELL: 未执行({server_response.get('reason', '')}), 不消耗配额")

                        # 外挂利润追踪
                        if self.profit_tracker:
                            self.profit_tracker.record_trade(
                                symbol=main_symbol, plugin_name="移动止损",
                                action="SELL", price=current_price,
                                executed=server_response.get("executed", False),
                                asset_type="crypto" if is_crypto else "stock")
                        # v21.29: 止损SELL发送后本轮不再检查止盈BUY(防同轮双向交易)
                        return
        else:
            # 清仓后重置trailing_high
            if state.get("trailing_high") is not None:
                state["trailing_high"] = None
                logger.info(f"[{symbol}] 清仓，重置trailing_high")

        # ====== 移动止盈 (未满仓时) ======
        if position < 5:
            # 检查配额 (v20.2: 最多2次/天)
            if state.get("trailing_buy_count", 0) >= 1:
                # 配额已用完，跳过 (安全期: 1次/天)
                pass
            else:
                # 初始化或更新trailing_low
                trailing_low = state.get("trailing_low")
                if trailing_low is None:
                    # 没有值 → 用当前价初始化
                    trailing_low = current_price
                    state["trailing_low"] = trailing_low
                    logger.info(f"[{symbol}] v16.8 移动止盈初始化: trailing_low={trailing_low:.2f}")

                # 更新最低价
                if current_price < trailing_low:
                    state["trailing_low"] = current_price
                    trailing_low = current_price
                    logger.debug(f"[{symbol}] 移动止盈更新: trailing_low={trailing_low:.2f}")

                # 检查是否触发止盈买入
                if trailing_low > 0:
                    rise = (current_price - trailing_low) / trailing_low
                    # v21.x: 纯ATR动态阈值，全仓位统一使用ATR(14)×倍数
                    effective_threshold = atr_threshold
                    if rise >= effective_threshold:
                        # v21.18: 30分钟发送冷却
                        _cd_key = f"{symbol}_BUY"
                        _cd_until = self._trailing_send_cooldown.get(_cd_key)
                        if _cd_until and datetime.now() < _cd_until:
                            _cd_remain = (_cd_until - datetime.now()).total_seconds() / 60
                            logger.info(f"[v21.18] {symbol} 移动止盈 BUY → 冷却中(剩余{_cd_remain:.0f}min)")
                            return

                        # v21.30: N字门控已转外挂，仅观察日志(与主程序v3.671对齐)
                        _ng = self._load_n_gate_state()
                        _ms = REVERSE_SYMBOL_MAP.get(symbol, symbol)
                        _ng_buy_info = _ng.get(f"{_ms}_BUY", {})
                        if _ng_buy_info.get("block", False):
                            logger.info(f"[N_GATE][观察] {symbol} BUY 移动止盈: {_ng_buy_info.get('reason', '')} (已转外挂,不拦截)")

                        # v17.3: Position Control检查
                        trend_info = self._get_trend_for_plugin(symbol)
                        big_trend = trend_info.get("trend_x4", "SIDE") if trend_info else "SIDE"
                        current_trend = trend_info.get("trend", "SIDE") if trend_info else "SIDE"

                        # v21.9: 移动止盈BUY豁免x4顺大过滤
                        # 移动止盈是仓位管理(卖高接低), 不是方向性交易
                        # 底部回接需要在x4=DOWN时买入, check_position_control已有EMA10+仓位保护

                        # v17.3: 计算EMA10 (仓位0-4都需要)
                        ema10 = 0.0
                        _p0_tf = read_symbol_timeframe(symbol, default=240)
                        _p0_params = get_timeframe_params(_p0_tf, is_crypto=is_crypto_symbol(symbol))
                        _p0_lookback = max(20, int(_p0_params["bars_per_day"] * 3))  # v20: ~3天bar数，EMA10足够
                        bars = YFinanceDataFetcher.get_ohlcv(symbol, _p0_tf, _p0_lookback)
                        if bars:
                            ema10 = calculate_ema10(bars)
                        pos_allowed, pos_reason, target_pos = check_position_control(
                            position, "BUY", big_trend, current_trend, "移动止盈",
                            current_price, ema10, bars
                        )
                        log_signal_decision(symbol, "BUY", position, pos_allowed, pos_reason, target_pos, "移动止盈", current_price, big_trend, current_trend)
                        if not pos_allowed:
                            logger.info("=" * 70)
                            logger.info(f"[v19] {symbol} 移动止盈 BUY → HOLD")
                            logger.info(f"  ├─ 当前仓位: {position}/5")
                            logger.info(f"  ├─ 当前价格: {current_price:.2f}")
                            logger.info(f"  └─ 原因: {pos_reason}")
                            logger.info("=" * 70)
                            return

                        # v20.1: 首档K线内冻结检查
                        current_bar_start = self.tracking_state[symbol].get("period_start", "")
                        bar_ok, bar_reason = check_first_position_bar_freeze(
                            self.tracking_state[symbol], "BUY", position, current_bar_start)
                        if not bar_ok:
                            logger.info(f"[v20.1] {symbol} 移动止盈 BUY → HOLD | {bar_reason}")
                            return

                        logger.info("=" * 70)
                        logger.info(f"[S2][移动止盈] {symbol} BUY 触发!")
                        logger.info(f"  trailing_low: {trailing_low:.2f}")
                        logger.info(f"  当前价: {current_price:.2f}")
                        _th_label = f"ATR阈值: {effective_threshold*100:.2f}% (ATR=${atr_value:.2f} x{atr_multiplier})"
                        logger.info(f"  涨幅: {rise*100:.2f}% ({_th_label})")
                        logger.info(f"  仓位: {position}/5 → 目标: {target_pos}/5")
                        logger.info(f"  {pos_reason}")  # v18
                        logger.info("=" * 70)

                        # 记录触发历史
                        state.setdefault("trigger_history", []).append({
                            "action": "TRAILING_BUY",
                            "time": datetime.now().isoformat(),
                            "price": current_price,
                            "trailing_low": trailing_low,
                            "atr_threshold": round(effective_threshold * 100, 2),  # v20.6
                            "asset_type": asset_type,
                        })

                        # v19: 获取仓位控制规则描述
                        position_rule_desc = self._get_position_rule_desc(position, "BUY")

                        signal_data = {
                            "signal": "BUY",
                            "price": current_price,
                            "base_price": trailing_low,
                            "change_pct": round(rise * 100, 2),
                            "threshold": round(effective_threshold * 100, 2),  # v20.6
                            "timeframe": timeframe,
                            "timestamp": datetime.now().isoformat(),
                            "type": "crypto" if is_crypto else "stock",
                            "signal_type": "移动止盈",
                            # v19: 仓位控制信息
                            "position_units": position,
                            "target_position": target_pos,  # v19: 目标仓位
                            "position_control_rule": position_rule_desc,
                            # v20.6: ATR详情 + 阈值类型
                            "atr_value": atr_value,
                            "atr_multiplier": atr_multiplier,
                            "atr_asset_type": asset_type,
                            "atr_regime": regime_key,
                            "atr_threshold_pct": round(effective_threshold * 100, 2),
                            "threshold_type": "ATR",
                        }

                        # v21.8: 移动止盈共识度日志 (保命信号不拦截, 仅记录)
                        # v21.14修复: 传入实际trend_info(原传None→regime始终sideways)
                        _tp_consensus = calc_consensus_score(symbol, "BUY", self._get_trend_for_plugin(symbol))
                        log_consensus_score(symbol, "BUY", "移动止盈", _tp_consensus)

                        # v3.660: 移动止盈信号归入GCC-TM信号池(不再直接下单)
                        main_symbol = REVERSE_SYMBOL_MAP.get(symbol, symbol)
                        try:
                            from gcc_trading_module import gcc_push_signal as _gcc_push
                            _gcc_push(main_symbol, "TrailingProfit", "BUY", confidence=0.7)
                            logger.info(f"[v3.660] {main_symbol} 移动止盈BUY → GCC-TM信号池")
                        except Exception as _gp_err:
                            logger.warning(f"[v3.660] {main_symbol} gcc_push_signal失败: {_gp_err}")
                        # 仍通知服务器记录(会被GCC_TM_ONLY门控拦截,仅观察)
                        server_response = self._notify_main_server(main_symbol, signal_data)
                        signal_data["server_executed"] = server_response.get("executed", False)
                        signal_data["server_reason"] = server_response.get("reason", "")

                        # v21.18: 发送后30分钟冷却 (无论成败)
                        self._trailing_send_cooldown[f"{symbol}_BUY"] = datetime.now() + timedelta(minutes=30)

                        # 只在执行成功时消耗配额
                        if server_response.get("executed", False):
                            state["trailing_buy_count"] = state.get("trailing_buy_count", 0) + 1  # v20.2
                            # v21.5: 每次执行后双向重置基准价格(修复: 不重置导致来回交易)
                            state["trailing_low"] = current_price
                            state["trailing_high"] = current_price
                            # v21.17: K线冻结信息到邮件
                            signal_data["bar_freeze_info"] = f"同K线单方向冻结(BUY, 最多2次)"
                            self.email_notifier.send_signal_notification(symbol, signal_data)
                            # v16.8→v20.2: 显示完整状态
                            round1 = f"买[{'✓' if state.get('buy_used') else '○'}]卖[{'✓' if state.get('sell_used') else '○'}]"
                            stop_cnt = state.get('trailing_stop_count', 0)
                            buy_cnt = state.get('trailing_buy_count', 0)
                            round2 = f"止损[{stop_cnt}/1]止盈[{buy_cnt}/1]"
                            tr = state.get('trough_price')
                            tr_str = f"{tr:.2f}" if tr else "无"
                            logger.info(f"[v16.8] {symbol} 移动止盈BUY已执行")
                            logger.info(f"  来回1({round1}) 来回2({round2})")
                            logger.info(f"  最低={trailing_low:.2f} | trough={tr_str}")
                            _th_exec = f"ATR(14)=${atr_value:.2f} x{atr_multiplier} → {effective_threshold*100:.2f}%"
                            logger.info(f"  {_th_exec}")
                            # v17.2: 设置P0抄底保护 (阻止其他外挂SELL)
                            protect_until = set_p0_buy_protection(state)
                            logger.info(f"  [v17.2] P0抄底保护已设置: 至{protect_until}或L1=UP")
                            # v21.17: 同K线单方向冻结记录
                            _bar_start = self.tracking_state[symbol].get("period_start")
                            if _bar_start and _bar_start == state.get("bar_freeze_bar_start") and state.get("bar_freeze_dir") == "BUY":
                                state["bar_freeze_count"] = state.get("bar_freeze_count", 0) + 1
                            else:
                                state["bar_freeze_dir"] = "BUY"
                                state["bar_freeze_count"] = 1
                                state["bar_freeze_bar_start"] = _bar_start
                            logger.info(f"  [v21.17] K线冻结: BUY x{state['bar_freeze_count']} bar={_bar_start[:16] if _bar_start else 'None'}")
                            self._save_tracking_state()  # v17.2: 立即保存，防止重启丢失
                        else:
                            logger.info(f"[{symbol}] 移动止盈BUY: 未执行({server_response.get('reason', '')}), 不消耗配额")

                        # 外挂利润追踪
                        if self.profit_tracker:
                            self.profit_tracker.record_trade(
                                symbol=main_symbol, plugin_name="移动止盈",
                                action="BUY", price=current_price,
                                executed=server_response.get("executed", False),
                                asset_type="crypto" if is_crypto else "stock")
        else:
            # 满仓后重置trailing_low
            if state.get("trailing_low") is not None:
                state["trailing_low"] = None
                logger.info(f"[{symbol}] 满仓，重置trailing_low")

    def _scan_open_crypto(self, symbol: str, current_price: float):
        """
        v11.3: P0-Open扫描 (只对加密货币开放)

        激活条件:
        - current_trend = UP → 只能触发BUY (趋势对齐)
        - current_trend = DOWN → 只能触发SELL (趋势对齐)
        - current_trend = SIDE → 不触发 (震荡市)

        阈值:
        - BTC/ETH/SOL: 2%
        - ZEC: 2.5%

        触发后:
        - 冻结6小时
        - 发送信号通知
        """
        p0_config = self.config.get("p0_open", {})

        if not p0_config.get("enabled_crypto", False):
            return  # P0-Open未启用

        # 获取当前趋势
        current_trend = self._get_current_trend(symbol)

        # v3.571: 获取x4趋势用于顺大逆小过滤
        trend_info = self._get_trend_for_plugin(symbol)
        trend_x4 = trend_info.get("trend_x4", "SIDE")

        # 检查趋势要求
        if p0_config.get("require_trend", True):
            if current_trend == "SIDE":
                logger.debug(f"[{symbol}] P0-Open: current_trend=SIDE，跳过(震荡市不触发)")
                return

        # 检查P0-Open周期重置
        # v20: 动态读取品种周期，不再硬编码4h
        _, _, _open_tf, _ = self._get_symbol_config(symbol)
        self._check_period_reset_open(symbol, _open_tf)

        if symbol not in self.state:
            return

        # 检查冻结状态
        freeze_until = self.state[symbol].get("freeze_until")
        if freeze_until and is_frozen_until(freeze_until):
            logger.debug(f"[{symbol}] P0-Open冻结中，跳过")
            return

        # 检查是否已触发
        triggered_action = self.state[symbol].get("triggered_action")
        if triggered_action:
            logger.debug(f"[{symbol}] P0-Open本周期已触发{triggered_action}，跳过")
            return

        base_price = self.state[symbol].get("base_price")
        if not base_price:
            logger.debug(f"[{symbol}] P0-Open无基准价，跳过")
            return

        # v11.3: 获取按币种阈值 (BTC/ETH/SOL 2%, ZEC 2.5%)
        thresholds = p0_config.get("thresholds", {})
        threshold = thresholds.get(symbol, p0_config.get("default_threshold", 0.02))

        # 计算涨跌幅
        change_pct = (current_price - base_price) / base_price

        # 获取仓位
        position = self._get_position_from_main_state(symbol)

        # v11.3: 趋势对齐检查 - UP只买，DOWN只卖
        trend_aligned = p0_config.get("trend_aligned", True)

        # 判断触发 - 趋势UP时只能买入
        if change_pct >= threshold and position < 5:
            # v11.3: 趋势对齐检查
            if trend_aligned and current_trend != "UP":
                logger.debug(f"[{symbol}] P0-Open: 涨幅{change_pct*100:.1f}%但current_trend={current_trend}≠UP，跳过BUY(趋势不对齐)")
                return



            # 触发买入
            logger.info(f"[{symbol}] P0-Open触发BUY! 涨幅{change_pct*100:.1f}%>={threshold*100:.1f}% (current_trend={current_trend})")

            # v17.5: 统一冻结到次日8AM (美股/加密货币一致)
            freeze_until = get_next_8am_ny()
            self.state[symbol]["freeze_until"] = freeze_until.isoformat()
            self.state[symbol]["triggered_action"] = "BUY"
            logger.info(f"[{symbol}] P0-Open冻结至次日8AM ({freeze_until.strftime('%m-%d %H:%M')} NY)")

            # v17.4: 获取仓位控制规则描述
            position_rule_desc = self._get_position_rule_desc(position, "BUY")

            # 发送信号
            signal_data = {
                "signal": "BUY",
                "price": current_price,
                "base_price": base_price,
                "change_pct": change_pct * 100,
                "threshold": threshold * 100,
                "timeframe": timeframe,
                "timestamp": datetime.now().isoformat(),
                "type": "crypto",
                "signal_type": "P0-Open",
                "current_trend": current_trend,
                # v17.4: 仓位控制信息
                "position_units": position,
                "position_control_rule": position_rule_desc,
            }

            # v12.2修复: 先通知服务器，根据响应决定邮件状态
            main_symbol = REVERSE_SYMBOL_MAP.get(symbol, symbol)
            server_response = self._notify_main_server(main_symbol, signal_data)
            signal_data["server_executed"] = server_response.get("executed", False)
            signal_data["server_reason"] = server_response.get("reason", "")
            self.email_notifier.send_signal_notification(symbol, signal_data)
            # v3.550: 外挂利润追踪
            if self.profit_tracker:
                self.profit_tracker.record_trade(
                    symbol=main_symbol, plugin_name="P0-Open",
                    action="BUY", price=current_price,
                    executed=server_response.get("executed", False),
                    asset_type="crypto")

        # 判断触发 - 趋势DOWN时只能卖出
        elif change_pct <= -threshold and position > 0:
            # v11.3: 趋势对齐检查
            if trend_aligned and current_trend != "DOWN":
                logger.debug(f"[{symbol}] P0-Open: 跌幅{change_pct*100:.1f}%但current_trend={current_trend}≠DOWN，跳过SELL(趋势不对齐)")
                return



            # 触发卖出
            logger.info(f"[{symbol}] P0-Open触发SELL! 跌幅{change_pct*100:.1f}%<=-{threshold*100:.1f}% (current_trend={current_trend})")

            # v17.5: 统一冻结到次日8AM (美股/加密货币一致)
            freeze_until = get_next_8am_ny()
            self.state[symbol]["freeze_until"] = freeze_until.isoformat()
            self.state[symbol]["triggered_action"] = "SELL"
            logger.info(f"[{symbol}] P0-Open冻结至次日8AM ({freeze_until.strftime('%m-%d %H:%M')} NY)")

            # v17.4: 获取仓位控制规则描述
            position_rule_desc = self._get_position_rule_desc(position, "SELL")

            # 发送信号
            signal_data = {
                "signal": "SELL",
                "price": current_price,
                "base_price": base_price,
                "change_pct": change_pct * 100,
                "threshold": threshold * 100,
                "timeframe": timeframe,
                "timestamp": datetime.now().isoformat(),
                "type": "crypto",
                "signal_type": "P0-Open",
                "current_trend": current_trend,
                # v17.4: 仓位控制信息
                "position_units": position,
                "position_control_rule": position_rule_desc,
            }

            # v12.2修复: 先通知服务器，根据响应决定邮件状态
            main_symbol = REVERSE_SYMBOL_MAP.get(symbol, symbol)
            server_response = self._notify_main_server(main_symbol, signal_data)
            signal_data["server_executed"] = server_response.get("executed", False)
            signal_data["server_reason"] = server_response.get("reason", "")
            self.email_notifier.send_signal_notification(symbol, signal_data)
            # v3.550: 外挂利润追踪
            if self.profit_tracker:
                self.profit_tracker.record_trade(
                    symbol=main_symbol, plugin_name="P0-Open",
                    action="SELL", price=current_price,
                    executed=server_response.get("executed", False),
                    asset_type="crypto")

    def _reset_scalping_daily_count_if_needed(self, symbol: str):
        """
        v12.1: 纽约时间早上8点重置剥头皮每日计数
        """
        ny_now = get_ny_now()
        scalping_config = self.config["crypto"].get("scalping", {})
        daily_limit_config = scalping_config.get("daily_limit", {})
        reset_hour = daily_limit_config.get("reset_hour_ny", 8)

        # 计算当前周期的重置日期 (8点前算前一天)
        if ny_now.hour >= reset_hour:
            reset_date = ny_now.strftime("%Y-%m-%d")
        else:
            reset_date = (ny_now - timedelta(days=1)).strftime("%Y-%m-%d")

        # 初始化状态
        if symbol not in self.scalping_state:
            self.scalping_state[symbol] = {}

        state = self.scalping_state[symbol]
        if state.get("daily_reset_date") != reset_date:
            # v14.1: 重置前生成每日报告 (只在第一个币种触发时生成一次)
            old_date = state.get("daily_reset_date", "")
            if old_date and old_date != reset_date:
                # 检查是否已经为这个旧日期生成过报告
                if not hasattr(self, '_last_report_date') or self._last_report_date != old_date:
                    self._generate_scalping_daily_report(old_date)
                    # v3.550: 同时生成外挂利润日报
                    if self.profit_tracker and save_daily_report:
                        try:
                            save_daily_report(self.profit_tracker, old_date)
                        except Exception as e:
                            logger.error(f"[v3.550] 外挂利润日报生成失败: {e}")
                    self._last_report_date = old_date

            self.scalping_state[symbol]["daily_buy_count"] = 0
            self.scalping_state[symbol]["daily_sell_count"] = 0
            self.scalping_state[symbol]["daily_reset_date"] = reset_date
            logger.info(f"[{symbol}] 剥头皮每日计数重置 (NY 8AM, date={reset_date})")

    def _check_scalping_daily_limit(self, symbol: str, action: str, trend: str) -> tuple:
        """
        v12.1: 检查剥头皮是否达到每日限制
        v17.5: 统一为1买+1卖，方向过滤由外层check_x4_trend_filter()处理

        Args:
            symbol: 交易品种
            action: BUY 或 SELL
            trend: L1趋势 (UP/DOWN/SIDE)

        Returns:
            (is_allowed, reason): 是否允许交易及原因
        """
        # SIDE趋势: 完全禁用剥头皮
        if trend == "SIDE":
            return False, "SIDE趋势禁用剥头皮"

        scalping_config = self.config["crypto"].get("scalping", {})
        daily_limit_config = scalping_config.get("daily_limit", {})

        # v17.5: 统一限制 (配置: max_buy=1, max_sell=1)
        max_buy = daily_limit_config.get("max_buy", 1)
        max_sell = daily_limit_config.get("max_sell", 1)

        state = self.scalping_state.get(symbol, {})
        buy_count = state.get("daily_buy_count", 0)
        sell_count = state.get("daily_sell_count", 0)

        if action == "BUY":
            if buy_count >= max_buy:
                return False, f"买入已达限制({buy_count}/{max_buy})"
        else:  # SELL
            if sell_count >= max_sell:
                return False, f"卖出已达限制({sell_count}/{max_sell})"

        return True, ""

    def _scan_chandelier_zlsma(self, symbol: str, market_type: str = "crypto"):
        """
        v12.0: Chandelier Exit + ZLSMA 剥头皮策略扫描
        v3.550: 支持加密货币和美股市场

        策略规则:
        - BUY: Chandelier买入信号 + HA收盘>ZLSMA + 大阳线
        - SELL: Chandelier卖出信号 + HA收盘<ZLSMA + 大阴线
        - v3.546: 买卖不限方向, SIDE/RANGING不触发

        使用5分钟K线
        """
        # 检查剥头皮功能是否启用 (v21.15: 关闭→观察模式)
        scalping_config = self.config[market_type].get("scalping", {})
        _scalp_observe = not scalping_config.get("enabled", False)
        # 观察模式不return，继续运行检测逻辑

        # 检查外挂是否可用
        if not _chandelier_zlsma_available:
            return

        # 启动冷却期检查
        if time.time() - self.startup_time < self.STARTUP_COOLDOWN_SECONDS:
            return

        # v12.4: 检查全局冻结 (达到利润目标后)
        is_global_frozen, frozen_until_str = self._check_scalping_global_frozen()
        if is_global_frozen:
            logger.debug(f"[{symbol}] 剥头皮全局冻结至 {frozen_until_str}，跳过")
            return

        # v12.4: 生成每日目标
        self._generate_daily_scalping_target()

        # 初始化剥头皮状态
        if symbol not in self.scalping_state:
            self.scalping_state[symbol] = {
                "freeze_until": None,
                "last_signal": None,
                "last_trigger_time": None,
                "last_trigger_price": None,
                # v12.4新增
                "total_cost": 0.0,
                "total_revenue": 0.0,
                "rounds_completed": 0,
                "in_round": False,
            }

        # 检查是否被冻结 (单品种冻结)
        freeze_until = self.scalping_state[symbol].get("freeze_until")
        if is_frozen_until(freeze_until):
            logger.debug(f"[{symbol}] 剥头皮冻结中，跳过")
            return

        # v3.546: 获取当前周期趋势 (剥头皮专用)
        trend_info = self._get_current_trend_for_scalping(symbol)
        current_trend = trend_info.get("current_trend", "SIDE")
        regime = trend_info.get("regime", "RANGING")
        trend_x4 = trend_info.get("trend_x4", "SIDE")  # v3.571
        trend_source = trend_info.get("source", "unknown")

        # v12.1: 每日计数重置检查
        self._reset_scalping_daily_count_if_needed(symbol)

        # v3.546: 只在当前周期有趋势(UP/DOWN)时允许剥头皮
        if current_trend == "SIDE":
            logger.info(f"[v3.546] {symbol} 当前周期SIDE趋势，剥头皮禁用 (来源:{trend_source})")
            return

        # v3.551fix: 移除regime==RANGING的Gate 2检查
        # 剥头皮只需当前周期current_trend(UP/DOWN/SIDE)判断，不受大周期regime限制
        # regime由VA_OVERLAP等大周期逻辑决定，会误伤强趋势中的短线机会

        # 获取5分钟K线数据
        lookback_bars = scalping_config.get("lookback_bars", 100)
        bars = YFinanceDataFetcher.get_5m_ohlcv(symbol, lookback_bars)
        if not bars or len(bars) < 60:  # 至少需要60根K线
            logger.info(f"[{symbol}] 5分钟K线数据不足")
            return

        # v13.0: 获取当前K线时间戳，用于周期控制
        current_bar_time = None
        if bars:
            last_bar = bars[-1]
            current_bar_time = last_bar.get("timestamp") or last_bar.get("time") or last_bar.get("datetime")
            # 转换为字符串用于比较
            if current_bar_time and not isinstance(current_bar_time, str):
                current_bar_time = str(current_bar_time)

        # v13.0: 5分钟周期触发检查 - 同一根K线只触发一次
        if symbol in self.scalping_cycle_state and current_bar_time:
            state = self.scalping_cycle_state[symbol]
            if state.get("last_trigger_bar") == current_bar_time:
                logger.debug(f"[v3.530] {symbol} 剥头皮本5分钟周期已触发 {state.get('triggered_direction')}，跳过")
                return

        # 获取仓位信息
        position_pct = self._get_position_pct(symbol)

        # 调用外挂计算
        try:
            plugin = get_chandelier_zlsma_plugin()
            result = plugin.process(
                symbol=symbol,
                bars=bars,
                l1_trend=current_trend,
                position_pct=position_pct
            )
        except Exception as e:
            logger.error(f"[{symbol}] 剥头皮外挂异常: {e}")
            return

        if not result or not result.should_execute():
            logger.info(f"[{symbol}] 剥头皮: 扫描完成, 无触发信号")
            return

        # v3.546: 移除趋势方向过滤，剥头皮不限制买卖方向
        # (原v3.540: UP只买, DOWN只卖 - 已移除)

        # v12.1: 每日交易次数限制检查
        is_allowed, limit_reason = self._check_scalping_daily_limit(symbol, result.action, current_trend)
        if not is_allowed:
            logger.info(f"[{symbol}] 剥头皮{result.action}跳过: {limit_reason}")
            return



        # v21.17: 检查实际持仓 (读取max_units, 避免满仓买入或无仓位卖出)
        position_units, _max_units = self._get_position_and_max(symbol)
        if result.action == "BUY" and position_units >= _max_units:
            logger.info(f"[{symbol}] 剥头皮: 满仓({position_units}/{_max_units})，跳过BUY (保护配额)")
            return
        if result.action == "SELL" and position_units <= 0:
            logger.info(f"[{symbol}] 剥头皮: 无仓位({position_units}/{_max_units})，跳过SELL (保护配额)")
            return

        # v19: Position Control检查
        # v19: 计算EMA10 (仓位0-4都需要, 使用5m K线)
        ema10 = 0.0
        scalping_bars = YFinanceDataFetcher.get_5m_ohlcv(symbol, 20)
        if scalping_bars:
            ema10 = calculate_ema10(scalping_bars)
        pos_allowed, pos_reason, target_pos = check_position_control(
            position_units, result.action, trend_x4, current_trend, "剥头皮",
            result.entry_price, ema10, scalping_bars
        )
        log_signal_decision(symbol, result.action, position_units, pos_allowed, pos_reason, target_pos, "剥头皮", result.entry_price, trend_x4, current_trend)
        if not pos_allowed:
            logger.info("=" * 70)
            logger.info(f"[v19] {symbol} 剥头皮 {result.action} → HOLD")
            logger.info(f"  ├─ 当前仓位: {position_units}/5")
            logger.info(f"  ├─ 入场价格: {result.entry_price:.4f}")
            logger.info(f"  └─ 原因: {pos_reason}")
            logger.info("=" * 70)
            return

        # 触发信号!
        logger.info(f"[{symbol}] 剥头皮触发{result.action}! {result.reason}")
        logger.info(f"  ├─ ZLSMA: {result.zlsma:.4f}, CE方向: {result.ce_direction}")
        logger.info(f"  ├─ 入场: {result.entry_price:.4f}, 止损: {result.stop_loss:.4f}")
        logger.info(f"  └─ L1趋势: {current_trend} ({regime}), 仓位: {position_pct:.0f}%, 来源: {trend_source}")

        # v13.0: 记录5分钟周期触发状态
        if current_bar_time:
            self.scalping_cycle_state[symbol] = {
                "last_trigger_bar": current_bar_time,
                "triggered_direction": result.action
            }
            logger.info(f"[v3.530] {symbol} 剥头皮触发 {result.action}，记录周期状态 (bar={current_bar_time})")

        # v20.2: 移除单次交易冻结，统一使用24小时周期+8AM解冻
        # 单次交易不再冻结，由每日配额(1买+1卖)控制，配额用完后冻结到8AM

        # v16.2修复: 先保存旧状态，计数器延迟到执行成功后再更新
        old_state = self.scalping_state.get(symbol, {})
        # v20.2: 不设置单次冻结，保留配额冻结(freeze_until由配额用完时设置)
        self.scalping_state[symbol] = {
            "freeze_until": old_state.get("freeze_until"),  # v20.2: 保留配额冻结，不设置单次冻结
            "last_signal": result.action,
            "last_trigger_time": datetime.now().isoformat(),
            "last_trigger_price": result.entry_price,
            # v16.2: 计数器暂时不增加，等执行成功后再更新
            "daily_buy_count": old_state.get("daily_buy_count", 0),
            "daily_sell_count": old_state.get("daily_sell_count", 0),
            "daily_reset_date": old_state.get("daily_reset_date", ""),
            # v16 P1-6: 保留profit跟踪字段
            "total_cost": old_state.get("total_cost", 0.0),
            "total_revenue": old_state.get("total_revenue", 0.0),
            "rounds_completed": old_state.get("rounds_completed", 0),
            "in_round": old_state.get("in_round", False),
            "entry_price": old_state.get("entry_price", 0.0),
            "buy_price": old_state.get("buy_price", 0.0),
            "quantity": old_state.get("quantity", 0.0),
            "current_position": old_state.get("current_position", 0),
        }
        logger.info(f"[{symbol}] 剥头皮触发 {result.action} (无单次冻结，配额控制)")

        # 构建信号数据 (v12.0修复: 添加_notify_main_server和邮件所需字段)
        # v17.4: 构建仓位控制规则说明
        position_rule_desc = self._get_position_rule_desc(position_units, result.action)

        signal_data = {
            "signal": result.action,
            "price": result.entry_price,
            "base_price": result.zlsma,  # 使用ZLSMA作为基准价格
            "change_pct": ((result.entry_price - result.zlsma) / result.zlsma * 100) if result.zlsma > 0 else 0,
            "timeframe": "5m",  # 剥头皮使用5分钟周期
            "zlsma": result.zlsma,
            "ce_direction": result.ce_direction,
            "stop_loss": result.stop_loss,
            "take_profit": result.take_profit,
            "timestamp": datetime.now().isoformat(),
            "type": market_type,
            "signal_type": "Chandelier+ZLSMA",
            "current_trend": current_trend,
            "reason": result.reason,
            "position_pct": position_pct,
            "activate_scalping_plugin": True,  # v12.0: 剥头皮外挂标记
            # v19: 仓位控制信息
            "position_units": position_units,
            "target_position": target_pos,  # v19: 目标仓位
            "sell_units": position_units - target_pos if result.action == "SELL" else 0,  # v19: 要卖出的档数
            "position_control_rule": position_rule_desc,
        }

        # v21.15: 观察模式 — 只记录日志,不发送信号
        if _scalp_observe:
            main_symbol = REVERSE_SYMBOL_MAP.get(symbol, symbol)
            logger.info(f"[OBSERVE][剥头皮] {main_symbol} {result.action} "
                       f"price={result.entry_price:.4f} reason={result.reason} "
                       f"(观察模式,不执行)")
            return

        # v12.2修复: 先通知服务器，根据响应决定邮件状态
        main_symbol = REVERSE_SYMBOL_MAP.get(symbol, symbol)
        server_response = self._notify_main_server(main_symbol, signal_data)

        # 将服务器执行结果写入signal_data供邮件使用
        signal_data["server_executed"] = server_response.get("executed", False)
        signal_data["server_reason"] = server_response.get("reason", "")

        # v12.4: 利润追踪 (仅在执行成功时记录)
        if server_response.get("executed", False):
            # v16.2修复: 只有实际执行成功才更新每日计数
            current_state = self.scalping_state.get(symbol, {})
            if result.action == "BUY":
                current_state["daily_buy_count"] = current_state.get("daily_buy_count", 0) + 1
                self._on_scalping_buy(symbol, result.entry_price)
            elif result.action == "SELL":
                current_state["daily_sell_count"] = current_state.get("daily_sell_count", 0) + 1
                self._on_scalping_sell(symbol, result.entry_price)
                # v16.3: 取消利润目标冻结，由买卖次数控制
            self.scalping_state[symbol] = current_state

            # v16.3: 买卖各3次后冻结至次日8AM (取消利润目标控制)
            buy_count = current_state.get("daily_buy_count", 0)
            sell_count = current_state.get("daily_sell_count", 0)
            max_buy = scalping_config.get("daily_limit", {}).get("max_buy", 3)
            max_sell = scalping_config.get("daily_limit", {}).get("max_sell", 3)

            if buy_count >= max_buy and sell_count >= max_sell:
                self._freeze_scalping_until_tomorrow(f"买卖各{max_buy}次已用完")
                logger.info(f"[v16.3] {symbol} 剥头皮: 买卖各{max_buy}次完成，冻结至次日8AM")
            else:
                logger.info(f"[{symbol}] 剥头皮今日计数: BUY={buy_count}/{max_buy}, SELL={sell_count}/{max_sell} (已执行)")

        # v12.4: 只在实际执行成功时发送邮件
        if server_response.get("executed", False):
            self.email_notifier.send_signal_notification(symbol, signal_data)
        else:
            # v16.2: 显示计数未变化
            unchanged_state = self.scalping_state.get(symbol, {})
            logger.info(f"[{symbol}] 剥头皮: 未执行({server_response.get('reason', '')}), 计数不变 BUY={unchanged_state.get('daily_buy_count', 0)}/SELL={unchanged_state.get('daily_sell_count', 0)}, 不发送邮件")

        # v3.550: 外挂利润追踪
        if self.profit_tracker:
            self.profit_tracker.record_trade(
                symbol=main_symbol, plugin_name="Chandelier+ZLSMA",
                action=result.action, price=result.entry_price,
                executed=server_response.get("executed", False),
                asset_type=market_type)

    def _get_position_rule_desc(self, position: int, action: str) -> str:
        """
        v20.4: 获取当前仓位的控制规则描述
        用于邮件通知中显示Position Control规则
        """
        if action == "BUY":
            rules = {
                0: "0→1: 需前一根阳线(P0系列直通)",
                1: "1→2: 需>EMA5+突破实体高(OR加分)",
                2: "2→3: 需>EMA10+突破实体高(OR加分)",
                3: "3→4: 需>EMA10+突破实体高(OR加分)",
                4: "4→5: 需cur=UP+价格>EMA10",
                5: "5/5满仓: 禁止买入",
            }
        else:  # SELL (v21.31: 严格逐级，每次只减1档)
            rules = {
                0: "0/5空仓: 禁止卖出",
                1: "清仓: 需cur=DOWN+价格<EMA10→0档",
                2: "四卖: 需<EMA10+跌破实体低(OR加分)→1档(逐级)",
                3: "三卖: 需<EMA10+跌破实体低(OR加分)→2档(逐级)",
                4: "二卖: 需<EMA5+跌破实体低(OR加分)→3档(逐级)",
                5: "一卖: 需前1根阴→4档(逐级)",
            }
        return rules.get(position, f"仓位{position}: 未知规则")

    def _get_position_pct(self, symbol: str) -> float:
        """获取当前仓位百分比 (从state.json读取)"""
        try:
            state_data = safe_json_read(os.path.join("logs", "state.json"))
            if not state_data:
                return 50.0  # 默认中位

            # 尝试从position_pct字段读取
            main_symbol = REVERSE_SYMBOL_MAP.get(symbol, symbol)
            positions = state_data.get("positions", {})
            if main_symbol in positions:
                return float(positions[main_symbol].get("position_pct", 50.0))

            # 尝试从l2_analysis_results读取
            l2_results = state_data.get("l2_analysis_results", {})
            if main_symbol in l2_results:
                return float(l2_results[main_symbol].get("position_pct", 50.0))

            return 50.0
        except Exception:
            return 50.0

    def _scan_supertrend(self, symbol: str, market_type: str = "crypto"):
        """
        v3.546: SuperTrend外挂扫描 (L1层集成到扫描引擎)
        v15.3: 支持加密货币和美股市场

        策略规则:
        - BUY1: 红区 + QQE蓝 + MACD蓝 + 位置过滤
        - SELL1: 绿区 + QQE红 + MACD红 + 位置过滤
        - v3.546: 4小时周期，每日买卖各1次后冻结到次日8AM

        使用4小时K线数据

        Args:
            symbol: 交易对
            market_type: 市场类型 ("crypto" 或 "stock")
        """
        # 检查SuperTrend功能是否启用
        supertrend_config = self.config[market_type].get("supertrend", {})
        if not supertrend_config.get("enabled", False):
            return

        # 检查外挂是否可用
        if not _supertrend_available:
            return

        # 启动冷却期检查
        if time.time() - self.startup_time < self.STARTUP_COOLDOWN_SECONDS:
            return

        # v3.546: 初始化SuperTrend状态（包含每日买卖限制）
        if symbol not in self.supertrend_state:
            self.supertrend_state[symbol] = {
                "freeze_until": None,
                "last_signal": None,
                "last_trigger_time": None,
                "buy_used": False,
                "sell_used": False,
                "reset_date": None,
            }

        # v3.571: 获取当前周期L1趋势和x4大周期趋势
        trend_info = self._get_trend_for_plugin(symbol)
        current_trend = trend_info.get("trend", "SIDE") if trend_info else "SIDE"
        trend_x4 = trend_info.get("trend_x4", "SIDE") if trend_info else "SIDE"
        logger.debug(f"[v3.571] {symbol} SuperTrend趋势检查: 当前={current_trend}, x4={trend_x4}, market={market_type}")

        # v3.572: 检查每日限制 - 如果买卖都用完则完全冻结 (使用x4趋势)
        state = self.supertrend_state[symbol]
        if state.get("buy_used") and state.get("sell_used"):
            can_trade, reason = check_plugin_daily_limit(state, "BUY", trend_x4=trend_x4, current_trend=current_trend, market_type=market_type)
            if not can_trade:
                logger.debug(f"[{symbol}] SuperTrend {reason}")
                return

        # v3.546: 获取4小时K线数据 (OHLCV)
        ohlcv_lookback = supertrend_config.get("ohlcv_lookback", 30)
        bars = YFinanceDataFetcher.get_4h_ohlcv(symbol, ohlcv_lookback)
        if not bars or len(bars) < 15:
            logger.info(f"[{symbol}] SuperTrend: 4小时K线数据不足 (获取={len(bars) if bars else 0}根)")
            return

        # 获取当前K线时间戳，用于周期控制
        current_bar_time = None
        if bars:
            last_bar = bars[-1]
            current_bar_time = last_bar.get("timestamp") or last_bar.get("time") or last_bar.get("datetime")
            if current_bar_time and not isinstance(current_bar_time, str):
                current_bar_time = str(current_bar_time)

        # v21.14: 移除per-bar周期限制 (N字门控替代), 仅保留每日配额

        # v3.546: 获取收盘价序列 (120根4h用于QQE/MACD)
        close_lookback = supertrend_config.get("close_lookback", 120)
        bars_120 = YFinanceDataFetcher.get_4h_ohlcv(symbol, close_lookback)
        if not bars_120 or len(bars_120) < 50:
            logger.info(f"[{symbol}] SuperTrend: 收盘价数据不足 (获取={len(bars_120) if bars_120 else 0}根)")
            return
        close_prices = [bar["close"] for bar in bars_120]

        # 获取L1三方信号
        l1_signals = self._get_l1_signals_for_supertrend(symbol)

        # 获取市场数据
        market_data = self._get_market_data_for_supertrend(symbol)

        # 调用外挂计算
        try:
            plugin = get_supertrend_plugin()
            result = plugin.process(
                symbol=symbol,
                ohlcv_bars=bars,
                close_prices=close_prices,
                l1_signals=l1_signals,
                market_data=market_data,
            )
        except Exception as e:
            logger.error(f"[{symbol}] SuperTrend外挂异常: {e}")
            return

        # 检查是否应该执行
        if not result:
            logger.info(f"[{symbol}] SuperTrend: 扫描完成, 无结果")
            return

        # 只处理 PLUGIN_AGREE 或 PLUGIN_CONFLICT 模式
        mode_val = getattr(result.mode, 'value', result.mode) if result.mode else None
        if mode_val not in ("PLUGIN_AGREE", "PLUGIN_CONFLICT"):
            logger.info(f"[{symbol}] SuperTrend: 扫描完成, 模式={mode_val} (非触发)")
            return

        # 获取动作
        action = result.action
        if action not in ("BUY", "SELL"):
            logger.info(f"[{symbol}] SuperTrend: 扫描完成, 无买卖动作")
            return

        # v21.8: 缓存SuperTrend方向 + 共识度日志
        _st_direction = getattr(result, 'supertrend_direction', action)
        update_consensus_direction(symbol, "supertrend", "UP" if _st_direction == "UP" else ("DOWN" if _st_direction == "DOWN" else action))
        _consensus = calc_consensus_score(symbol, action, trend_info)
        log_consensus_score(symbol, action, "SuperTrend", _consensus)


        # v3.572: 检查该方向是否已用完 (使用x4趋势顺大逆小)
        state = self.supertrend_state[symbol]
        can_trade, limit_reason = check_plugin_daily_limit(state, action, trend_x4=trend_x4, current_trend=current_trend, market_type=market_type)
        if not can_trade:
            logger.info(f"[v3.572] {symbol} SuperTrend {action} 被限制: {limit_reason} (x4={trend_x4})")
            return

        # v21.17: 检查实际持仓 (读取max_units, 避免满仓买入或无仓位卖出)
        position_units, _max_units = self._get_position_and_max(symbol)
        if action == "BUY" and position_units >= _max_units:
            logger.info(f"[{symbol}] SuperTrend: 满仓({position_units}/{_max_units})，跳过BUY (保护配额)")
            return
        if action == "SELL" and position_units <= 0:
            logger.info(f"[{symbol}] SuperTrend: 无仓位({position_units}/{_max_units})，跳过SELL (保护配额)")
            return

        # 区间限制已移除，保留EMA Position Control检查
        current_price = bars[-1]["close"] if bars else 0.0
        ema10 = calculate_ema10(bars) if bars else 0.0
        pos_allowed, pos_reason, target_pos = check_position_control(
            position_units, action, trend_x4, current_trend, "SuperTrend",
            current_price, ema10, bars
        )
        log_signal_decision(symbol, action, position_units, pos_allowed, pos_reason, target_pos, "SuperTrend", current_price, trend_x4, current_trend)
        if not pos_allowed:
            logger.info(f"[v19] {symbol} SuperTrend {action} → HOLD | {pos_reason}")
            return

        # v21.20: 分型过滤 — v3.670: 已取消

        # 触发信号!
        logger.info(f"[v19] {symbol} SuperTrend触发{action}!")
        logger.info(f"  ├─ 模式: {mode_val}")
        logger.info(f"  ├─ 指标信号: {result.indicator_signal}")
        logger.info(f"  ├─ L1综合: {result.l1_signal}")
        logger.info(f"  ├─ ST趋势: {result.supertrend_trend} (1=绿区, -1=红区)")
        logger.info(f"  ├─ QQE: {result.qqe_hist:+.2f}")
        logger.info(f"  ├─ MACD: {result.macd_hist:+.4f}")
        logger.info(f"  ├─ 仓位: {position_units}/5 → 目标: {target_pos}/5")
        logger.info(f"  └─ 原因: {result.reason}")

        # v3.546: 记录4小时周期触发状态
        if current_bar_time:
            self.supertrend_cycle_state[symbol] = {
                "last_trigger_bar": current_bar_time,
                "triggered_direction": action
            }
            logger.info(f"[v3.546] {symbol} SuperTrend触发 {action}，记录周期状态 (bar={current_bar_time})")

        # v16.7: 移除提前配额更新，改为执行成功后更新
        state["last_signal"] = action
        state["last_trigger_time"] = datetime.now().isoformat()

        # 获取当前价格
        current_price = bars[-1]["close"] if bars else 0

        # KEY-004: 因子观测台 record_signal — supertrend (fail-silent)
        try:
            from factor_db import record_signal as _rs_st
            _st_regime = str(detect_dc_regime(bars, current_price)) if bars else None
            _rs_st(symbol=symbol, factor_name="supertrend",
                   signal=1 if action == "BUY" else -1,
                   market_regime=_st_regime,
                   close_price=float(current_price))
        except Exception:
            pass

        # KEY-007: Plugin KNN记录+查询 — supertrend (Phase1: 仅日志)
        try:
            from plugin_knn import extract_supertrend_features, plugin_knn_record_and_query, plugin_knn_should_suppress, infer_regime_from_bars
            _pknn_feat = extract_supertrend_features(result, bars, market_data)
            _pknn_ind = {"qqe_hist": float(getattr(result, 'qqe_hist', 0) or 0),
                         "macd_hist": float(getattr(result, 'macd_hist', 0) or 0),
                         "position_pct": float(market_data.get('position_pct', 50)),
                         "dc_position": _pknn_feat[4] if len(_pknn_feat) > 4 else 0.5}
            _pknn_res = plugin_knn_record_and_query("supertrend", symbol, _pknn_feat, action,
                                                     close_price=float(current_price), indicator_values=_pknn_ind,
                                                     regime=infer_regime_from_bars(bars))
            if plugin_knn_should_suppress(action, _pknn_res):
                logger.info(f"[PLUGIN_KNN][抑制] {symbol} SuperTrend {action} ← KNN反向{_pknn_res.bias}")
                return
        except Exception:
            pass

        # v19: 获取仓位控制规则描述
        position_rule_desc = self._get_position_rule_desc(position_units, action)

        # 构建信号数据
        signal_data = {
            "signal": action,
            "price": current_price,
            "base_price": current_price,  # SuperTrend无基准价概念
            "change_pct": 0,
            "timeframe": "4h",  # v3.546: 改为4小时周期
            "timestamp": datetime.now().isoformat(),
            "type": market_type,
            "signal_type": "SuperTrend",
            "current_trend": market_data.get("current_trend", "SIDE"),
            "reason": result.reason,
            "position_pct": market_data.get("position_pct", 50),
            "activate_supertrend_plugin": True,  # SuperTrend外挂标记
            "plugin_mode": mode_val,
            "indicator_signal": result.indicator_signal,
            "supertrend_trend": result.supertrend_trend,
            "qqe_hist": result.qqe_hist,
            "macd_hist": result.macd_hist,
            # v19: 仓位控制信息
            "position_units": position_units,
            "target_position": target_pos,  # v19: 目标仓位
            "sell_units": position_units - target_pos if action == "SELL" else 0,  # v19: 要卖出的档数
            "position_control_rule": position_rule_desc,
            # v21.5: 仓位区间限制 (边界策略: 空仓/轻仓买入, 重仓/满仓卖出)
            "position_valid_range": "BUY[0-1] SELL[4-5]",
        }

        # 通知主程序
        main_symbol = REVERSE_SYMBOL_MAP.get(symbol, symbol)
        server_response = self._notify_main_server(main_symbol, signal_data)

        # 记录服务器响应
        signal_data["server_executed"] = server_response.get("executed", False)
        signal_data["server_reason"] = server_response.get("reason", "")

        # v16.7: 只在实际执行成功时更新配额和发送邮件
        if server_response.get("executed", False):
            status_msg = update_plugin_daily_state(state, action, trend=current_trend, market_type=market_type)
            logger.info(f"[v16.7] {symbol} SuperTrend 执行成功，更新配额: {status_msg}")
            self._save_supertrend_state()  # 持久化保存
            self.email_notifier.send_signal_notification(symbol, signal_data)
        else:
            logger.info(f"[{symbol}] SuperTrend: 未执行({server_response.get('reason', '')}), 不消耗配额")

        # v3.550: 外挂利润追踪
        if self.profit_tracker:
            self.profit_tracker.record_trade(
                symbol=main_symbol, plugin_name="SuperTrend",
                action=action, price=current_price,
                executed=server_response.get("executed", False),
                asset_type=market_type)

    # ========================================================================
    # v3.550: SuperTrend+QQE MOD+A-V2外挂扫描 (知识卡片"超级趋势过滤器交易系统")
    # ========================================================================

    def _scan_supertrend_av2(self, symbol: str, market_type: str = "crypto"):
        """
        v3.550: SuperTrend+QQE MOD+A-V2外挂扫描
        v15.3: 支持加密货币和美股市场

        来源: 知识卡片"超级趋势过滤器交易系统"
        策略规则:
        - BUY: SuperTrend买入 + QQE蓝色 + A-V2绿色 + 位置<80%
        - SELL: SuperTrend卖出 + QQE红色 + A-V2红色 + 位置>20%
        - 震荡过滤: QQE灰色 = 不交易
        - 止损: A-V2趋势线
        - 止盈: SuperTrend折线(ATR跟踪)

        参数 (来自知识卡片):
        - SuperTrend: ATR周期=9, 乘数=3.9
        - A-V2: 1MA均线, 参数52/10

        使用4小时K线数据

        Args:
            symbol: 交易对
            market_type: 市场类型 ("crypto" 或 "stock")
        """
        # 检查功能是否启用
        av2_config = self.config[market_type].get("supertrend_av2", {})
        if not av2_config.get("enabled", False):
            return

        # 检查外挂是否可用
        if not _supertrend_av2_available:
            return

        # 启动冷却期检查
        if time.time() - self.startup_time < self.STARTUP_COOLDOWN_SECONDS:
            return

        # v3.550: 初始化状态（包含每日买卖限制）
        if symbol not in self.supertrend_av2_state:
            self.supertrend_av2_state[symbol] = {
                "freeze_until": None,
                "last_signal": None,
                "last_trigger_time": None,
                "buy_used": False,
                "sell_used": False,
                "reset_date": None,
            }

        # v3.572: 获取当前周期和x4大周期趋势供顺大逆小使用
        trend_info = self._get_trend_for_plugin(symbol)
        current_trend = trend_info.get("trend", "SIDE") if trend_info else "SIDE"
        trend_x4 = trend_info.get("trend_x4", "SIDE") if trend_info else "SIDE"

        # v3.572: 检查每日限制 - 如果买卖都用完则完全冻结 (使用x4趋势)
        state = self.supertrend_av2_state[symbol]
        if state.get("buy_used") and state.get("sell_used"):
            can_trade, reason = check_plugin_daily_limit(state, "BUY", trend_x4=trend_x4, current_trend=current_trend, market_type=market_type)
            if not can_trade:
                logger.debug(f"[{symbol}] SuperTrend+AV2 {reason}")
                return

        # v3.550: 获取4小时K线数据 (OHLCV)
        ohlcv_lookback = av2_config.get("ohlcv_lookback", 100)
        bars = YFinanceDataFetcher.get_4h_ohlcv(symbol, ohlcv_lookback)
        if not bars or len(bars) < 20:
            logger.debug(f"[{symbol}] SuperTrend+AV2: 4小时K线数据不足")
            return

        # 获取当前K线时间戳，用于周期控制
        current_bar_time = None
        if bars:
            last_bar = bars[-1]
            current_bar_time = last_bar.get("timestamp") or last_bar.get("time") or last_bar.get("datetime")
            if current_bar_time and not isinstance(current_bar_time, str):
                current_bar_time = str(current_bar_time)

        # v21.14: 移除per-bar周期限制 (N字门控替代), 仅保留每日配额

        # v3.550: 获取收盘价序列 (120根4h用于QQE和A-V2)
        close_lookback = av2_config.get("close_lookback", 120)
        bars_120 = YFinanceDataFetcher.get_4h_ohlcv(symbol, close_lookback)
        if not bars_120 or len(bars_120) < 60:
            logger.debug(f"[{symbol}] SuperTrend+AV2: 收盘价数据不足")
            return
        close_prices = [bar["close"] for bar in bars_120]

        # 获取市场数据 (位置%)
        market_data = self._get_market_data_for_supertrend(symbol)

        # 调用外挂计算
        try:
            plugin = get_supertrend_av2_plugin()
            result = plugin.process(
                symbol=symbol,
                ohlcv_bars=bars,
                close_prices=close_prices,
                position_pct=market_data.get("position_pct", 50.0),
            )
        except Exception as e:
            logger.error(f"[{symbol}] SuperTrend+AV2外挂异常: {e}")
            return

        # 检查是否应该执行
        if not result:
            return

        # 只处理 ACTIVE 模式
        mode_val = getattr(result.mode, 'value', result.mode) if result.mode else None
        if mode_val != "ACTIVE":
            return

        # 获取动作
        action = result.action
        if action not in ("BUY", "SELL"):
            return

        # v21.8: 缓存ST+AV2方向 + 共识度日志
        _av2_st_dir = getattr(result, 'supertrend_direction', action)
        update_consensus_direction(symbol, "supertrend", "UP" if _av2_st_dir == "UP" else ("DOWN" if _av2_st_dir == "DOWN" else action))
        _consensus = calc_consensus_score(symbol, action, trend_info)
        log_consensus_score(symbol, action, "SuperTrend+AV2", _consensus)



        # v3.572: 检查该方向是否已用完 (使用x4趋势顺大逆小)
        state = self.supertrend_av2_state[symbol]
        can_trade, limit_reason = check_plugin_daily_limit(state, action, trend_x4=trend_x4, current_trend=current_trend, market_type=market_type)
        if not can_trade:
            logger.info(f"[v3.572] {symbol} SuperTrend+AV2 {action} 被限制: {limit_reason} (x4={trend_x4})")
            return

        # 触发信号!
        logger.info(f"[v3.550] {symbol} SuperTrend+AV2触发{action}!")
        logger.info(f"  ├─ 模式: {mode_val}")
        logger.info(f"  ├─ SuperTrend: {result.supertrend_direction} (价格{'>'if result.supertrend_direction=='UP'else'<'}SuperTrend线)")
        logger.info(f"  ├─ QQE颜色: {result.qqe_color} (蓝=多/红=空/灰=震荡)")
        logger.info(f"  ├─ A-V2颜色: {result.av2_color} (绿=上升/红=下降)")
        logger.info(f"  ├─ A-V2值: {result.av2_value:.4f} (止损位)")
        logger.info(f"  ├─ SuperTrend线: {result.supertrend_line:.4f} (止盈跟踪)")
        logger.info(f"  ├─ 位置%: {result.position_pct:.1f}%")
        logger.info(f"  └─ 原因: {result.reason}")

        # v3.550: 记录4小时周期触发状态
        if current_bar_time:
            self.supertrend_av2_cycle_state[symbol] = {
                "last_trigger_bar": current_bar_time,
                "triggered_direction": action
            }
            logger.info(f"[v3.550] {symbol} SuperTrend+AV2触发 {action}，记录周期状态 (bar={current_bar_time})")

        # v16.7: 移除提前配额更新，改为执行成功后更新
        state["last_signal"] = action
        state["last_trigger_time"] = datetime.now().isoformat()

        # 获取当前价格
        current_price = bars[-1]["close"] if bars else 0

        # KEY-004: 因子观测台 record_signal — supertrend_av2 (fail-silent, 当前暂停)
        try:
            from factor_db import record_signal as _rs_av2
            _rs_av2(symbol=symbol, factor_name="supertrend_av2",
                    signal=1 if action == "BUY" else -1,
                    market_regime=str(detect_dc_regime(bars, current_price)) if bars else None,
                    close_price=float(current_price))
        except Exception:
            pass

        # KEY-007: Plugin KNN记录+查询 — supertrend_av2 (Phase1: 仅日志)
        try:
            from plugin_knn import extract_supertrend_av2_features, plugin_knn_record_and_query, plugin_knn_should_suppress, infer_regime_from_bars
            _pknn_feat = extract_supertrend_av2_features(result, bars, market_data)
            _pknn_res = plugin_knn_record_and_query("supertrend_av2", symbol, _pknn_feat, action,
                                                     close_price=float(current_price),
                                                     regime=infer_regime_from_bars(bars))
            if plugin_knn_should_suppress(action, _pknn_res):
                logger.info(f"[PLUGIN_KNN][抑制] {symbol} SuperTrend+AV2 {action} ← KNN反向{_pknn_res.bias}")
                return
        except Exception:
            pass

        # v17.4: 获取仓位信息
        position_units = self._get_position_from_main_state(symbol)
        position_rule_desc = self._get_position_rule_desc(position_units, action)

        # 构建信号数据
        signal_data = {
            "signal": action,
            "price": current_price,
            "base_price": current_price,
            "change_pct": 0,
            "timeframe": "4h",
            "timestamp": datetime.now().isoformat(),
            "type": market_type,
            "signal_type": "SuperTrend+AV2",
            "current_trend": market_data.get("current_trend", "SIDE"),
            "reason": result.reason,
            "position_pct": result.position_pct,
            "activate_supertrend_av2_plugin": True,  # SuperTrend+AV2外挂标记
            "plugin_mode": mode_val,
            "supertrend_direction": result.supertrend_direction,
            "supertrend_line": result.supertrend_line,
            "qqe_color": result.qqe_color,
            "qqe_value": result.qqe_value,
            "av2_color": result.av2_color,
            "av2_value": result.av2_value,
            "stop_loss": result.stop_loss,
            "take_profit": result.take_profit,
            # v17.4: 仓位控制信息
            "position_units": position_units,
            "position_control_rule": position_rule_desc,
        }

        # 通知主程序
        main_symbol = REVERSE_SYMBOL_MAP.get(symbol, symbol)
        server_response = self._notify_main_server(main_symbol, signal_data)

        # 记录服务器响应
        signal_data["server_executed"] = server_response.get("executed", False)
        signal_data["server_reason"] = server_response.get("reason", "")

        # v16.7: 只在实际执行成功时更新配额和发送邮件
        if server_response.get("executed", False):
            status_msg = update_plugin_daily_state(state, action)
            logger.info(f"[v16.7] {symbol} SuperTrend+AV2 执行成功，更新配额: {status_msg}")
            self._save_supertrend_av2_state()  # 持久化保存
            self.email_notifier.send_signal_notification(symbol, signal_data)
        else:
            logger.info(f"[{symbol}] SuperTrend+AV2: 未执行({server_response.get('reason', '')}), 不消耗配额")

        # v3.550: 外挂利润追踪
        if self.profit_tracker:
            self.profit_tracker.record_trade(
                symbol=main_symbol, plugin_name="SuperTrend+AV2",
                action=action, price=current_price,
                executed=server_response.get("executed", False),
                asset_type=market_type)

    # ========================================================================
    # v3.545: Rob Hoffman外挂扫描
    # ========================================================================

    def _scan_rob_hoffman(self, symbol: str, market_type: str = "crypto"):
        """
        v3.546: Rob Hoffman外挂扫描 (L1层集成到扫描引擎)
        v3.550: 支持加密货币和美股市场

        策略规则:
        - 多头排列 + 回调入场 → BUY
        - 空头排列 + 反弹入场 → SELL
        - EMA纠缠 → 震荡过滤
        - v3.546: 4小时周期，每日买卖各1次后冻结到次日8AM

        使用4小时K线数据
        """
        if not _rob_hoffman_available:
            return

        # 检查配置
        hoffman_config = self.config[market_type].get("rob_hoffman", {})
        if not hoffman_config.get("enabled", True):
            return

        # 启动冷却期检查
        if time.time() - self.startup_time < self.STARTUP_COOLDOWN_SECONDS:
            return

        # v3.546: 初始化状态（包含每日买卖限制）
        if symbol not in self.rob_hoffman_state:
            self.rob_hoffman_state[symbol] = {
                "freeze_until": None,
                "last_signal": None,
                "last_trigger_time": None,
                "buy_used": False,
                "sell_used": False,
                "reset_date": None,
            }

        # v3.571: 获取当前周期L1趋势和x4大周期趋势
        trend_info = self._get_trend_for_plugin(symbol)
        current_trend_for_limit = trend_info.get("trend", "SIDE") if trend_info else "SIDE"
        trend_x4 = trend_info.get("trend_x4", "SIDE") if trend_info else "SIDE"
        logger.debug(f"[v3.571] {symbol} RobHoffman趋势检查: 当前={current_trend_for_limit}, x4={trend_x4}, market={market_type}")

        # v3.572: 检查每日限制 - 如果买卖都用完则完全冻结 (使用x4趋势)
        state = self.rob_hoffman_state[symbol]
        if state.get("buy_used") and state.get("sell_used"):
            can_trade, reason = check_plugin_daily_limit(state, "BUY", trend_x4=trend_x4, current_trend=current_trend_for_limit, market_type=market_type)
            if not can_trade:
                logger.debug(f"[{symbol}] Rob Hoffman {reason}")
                return

        # v3.546: 获取4小时K线数据
        bars = YFinanceDataFetcher.get_4h_ohlcv(symbol, 60)
        if not bars or len(bars) < 30:
            logger.info(f"[{symbol}] Rob Hoffman: 4小时K线数据不足 (获取={len(bars) if bars else 0}根)")
            return

        # 获取当前K线时间戳，用于周期控制
        current_bar_time = None
        if bars:
            last_bar = bars[-1]
            current_bar_time = last_bar.get("timestamp") or last_bar.get("time")
            if current_bar_time and not isinstance(current_bar_time, str):
                current_bar_time = str(current_bar_time)

        # v21.14: 移除per-bar周期限制 (N字门控替代), 仅保留每日配额

        # 获取市场数据
        market_data = self._get_market_data_for_supertrend(symbol)
        current_trend = market_data.get("current_trend", "SIDE")
        pos_in_channel = market_data.get("position_pct", 50) / 100.0
        position_units = market_data.get("position_units", 0)  # v16.4: 实际持仓

        # 调用外挂
        try:
            plugin = get_rob_hoffman_plugin()
            result = plugin.process_for_scan(
                symbol=symbol,
                ohlcv_bars=bars,
                current_trend=current_trend,
                pos_in_channel=pos_in_channel,
                position_units=position_units,  # v16.4: 传递持仓供退出判断
            )
        except Exception as e:
            logger.error(f"[{symbol}] Rob Hoffman外挂异常: {e}")
            return

        # 检查是否应该激活
        if not plugin.should_activate_for_scan(result):
            logger.info(f"[{symbol}] RobHoffman: 扫描完成, 未激活 (信号={result.signal.value if result else 'None'})")
            return

        action = plugin.get_action_for_scan(result)
        if action not in ("BUY", "SELL"):
            logger.info(f"[{symbol}] RobHoffman: 扫描完成, 无买卖动作 (action={action})")
            return

        # v21.8: 共识度日志
        _consensus = calc_consensus_score(symbol, action, trend_info)
        log_consensus_score(symbol, action, "RobHoffman", _consensus)




        # v3.572: 检查该方向是否已用完 (使用x4趋势顺大逆小)
        state = self.rob_hoffman_state[symbol]
        can_trade, limit_reason = check_plugin_daily_limit(state, action, trend_x4=trend_x4, current_trend=current_trend_for_limit, market_type=market_type)
        if not can_trade:
            logger.info(f"[v3.572] {symbol} Rob Hoffman {action} 被限制: {limit_reason} (x4={trend_x4})")
            return

        # v21.17: 检查实际持仓 (读取max_units, 避免满仓买入或无仓位卖出)
        position_units, _max_units = self._get_position_and_max(symbol)
        if action == "BUY" and position_units >= _max_units:
            logger.info(f"[{symbol}] Rob Hoffman: 满仓({position_units}/{_max_units})，跳过BUY (保护配额)")
            return
        if action == "SELL" and position_units <= 0:
            logger.info(f"[{symbol}] Rob Hoffman: 无仓位({position_units}/{_max_units})，跳过SELL (保护配额)")
            return

        # 区间限制已移除，保留EMA Position Control检查
        current_price = bars[-1]["close"] if bars else 0.0
        ema10 = calculate_ema10(bars) if bars else 0.0
        pos_allowed, pos_reason, target_pos = check_position_control(
            position_units, action, trend_x4, current_trend_for_limit, "RobHoffman",
            current_price, ema10, bars
        )
        log_signal_decision(symbol, action, position_units, pos_allowed, pos_reason, target_pos, "RobHoffman", current_price, trend_x4, current_trend_for_limit)
        if not pos_allowed:
            logger.info(f"[v19] {symbol} Rob Hoffman {action} → HOLD | {pos_reason}")
            return

        # 触发信号!
        logger.info(f"[v19] {symbol} Rob Hoffman触发{action}!")
        logger.info(f"  ├─ 信号: {result.signal.value}")
        logger.info(f"  ├─ 排列: {result.alignment.value if result.alignment else 'N/A'}")
        logger.info(f"  ├─ 入场价: {result.entry_price:.2f}")
        logger.info(f"  ├─ 仓位: {position_units}/5 → 目标: {target_pos}/5")
        logger.info(f"  └─ 原因: {result.reason}")

        # v3.546: 记录4小时周期触发状态
        if current_bar_time:
            self.rob_hoffman_cycle_state[symbol] = {
                "last_trigger_bar": current_bar_time,
                "triggered_direction": action
            }

        # v16.7: 移除提前配额更新，改为执行成功后更新
        state["last_signal"] = action
        state["last_trigger_time"] = datetime.now().isoformat()

        # 构建信号数据
        current_price = bars[-1]["close"] if bars else 0

        # KEY-004: 因子观测台 record_signal — rob_hoffman (fail-silent, 当前暂停)
        try:
            from factor_db import record_signal as _rs_rh
            _rs_rh(symbol=symbol, factor_name="rob_hoffman",
                   signal=1 if action == "BUY" else -1,
                   market_regime=str(detect_dc_regime(bars, current_price)) if bars else None,
                   close_price=float(current_price))
        except Exception:
            pass

        # KEY-007: Plugin KNN记录+查询 — rob_hoffman (Phase1: 仅日志)
        try:
            from plugin_knn import extract_rob_hoffman_features, plugin_knn_record_and_query, plugin_knn_should_suppress, infer_regime_from_bars
            _pknn_feat = extract_rob_hoffman_features(result, bars, market_data)
            _pknn_ind = {"er_value": float(getattr(result, 'er_value', 0) or 0),
                         "position_pct": float(market_data.get('position_pct', 50))}
            _pknn_res = plugin_knn_record_and_query("rob_hoffman", symbol, _pknn_feat, action,
                                                     close_price=float(current_price), indicator_values=_pknn_ind,
                                                     regime=infer_regime_from_bars(bars))
            if plugin_knn_should_suppress(action, _pknn_res):
                logger.info(f"[PLUGIN_KNN][抑制] {symbol} RobHoffman {action} ← KNN反向{_pknn_res.bias}")
                return
        except Exception:
            pass

        # v19: 获取仓位控制规则描述
        position_rule_desc = self._get_position_rule_desc(position_units, action)

        signal_data = {
            "signal": action,
            "price": current_price,
            "base_price": current_price,
            "change_pct": 0,
            "timeframe": "4h",  # v3.546: 改为4小时周期
            "timestamp": datetime.now().isoformat(),
            "type": market_type,
            "signal_type": "RobHoffman",
            "current_trend": current_trend,
            "reason": result.reason,
            "position_pct": market_data.get("position_pct", 50),
            "activate_rob_hoffman_plugin": True,
            "entry_price": result.entry_price,
            "stop_loss": result.stop_loss,
            "take_profit": result.take_profit,
            # v17.4: 仓位控制信息
            "position_units": position_units,
            "position_control_rule": position_rule_desc,
            # v19: 目标仓位信息
            "target_position": target_pos,
            "sell_units": position_units - target_pos if action == "SELL" else 0,
            # v20.2: 仓位区间限制 (回撤入场策略)
            "position_valid_range": "[1-3]" if action == "BUY" else "[2-4]",
        }

        # 通知主程序
        main_symbol = REVERSE_SYMBOL_MAP.get(symbol, symbol)
        server_response = self._notify_main_server(main_symbol, signal_data)

        signal_data["server_executed"] = server_response.get("executed", False)
        signal_data["server_reason"] = server_response.get("reason", "")

        # v16.7: 只在实际执行成功时更新配额和发送邮件
        if server_response.get("executed", False):
            status_msg = update_plugin_daily_state(state, action, trend=current_trend_for_limit, market_type=market_type)
            logger.info(f"[v16.7] {symbol} Rob Hoffman 执行成功，更新配额: {status_msg}")
            self._save_rob_hoffman_state()  # v15.1: 持久化保存
            self.email_notifier.send_signal_notification(symbol, signal_data)
        else:
            logger.info(f"[{symbol}] Rob Hoffman: 未执行({server_response.get('reason', '')}), 不消耗配额")

        # v3.550: 外挂利润追踪
        if self.profit_tracker:
            self.profit_tracker.record_trade(
                symbol=main_symbol, plugin_name="RobHoffman",
                action=action, price=current_price,
                executed=server_response.get("executed", False),
                asset_type=market_type)

    # ========================================================================
    # v3.545: 双底双顶外挂扫描
    # ========================================================================

    def _scan_double_pattern(self, symbol: str, market_type: str = "crypto"):
        """
        v21: Vision形态外挂扫描 (原双底双顶, 改为读取GPT-4o形态识别结果)
        v3.550: 支持加密货币和美股市场

        策略规则:
        - 8种形态: 双底/双顶/头肩底/头肩顶/123反转/2B假突破
        - stage=BREAKOUT + confidence>=0.70 + volume_confirmed=true → 信号触发
        - v21: 观察模式(美股) / 执行模式(加密货币)

        使用Vision pattern_latest.json结果
        """
        if not _double_pattern_available:
            return

        # 检查配置
        dp_config = self.config[market_type].get("double_pattern", {})
        if not dp_config.get("enabled", True):
            return

        # 启动冷却期检查
        if time.time() - self.startup_time < self.STARTUP_COOLDOWN_SECONDS:
            return

        # v3.546: 初始化状态（包含每日买卖限制）
        if symbol not in self.double_pattern_state:
            self.double_pattern_state[symbol] = {
                "freeze_until": None,
                "last_signal": None,
                "last_trigger_time": None,
                "buy_used": False,
                "sell_used": False,
                "reset_date": None,
            }

        # v3.572: 获取趋势信息用于顺大逆小过滤 (移到frozen check之前)
        trend_info = self._get_trend_for_plugin(symbol)
        current_trend = trend_info.get("trend", "SIDE") if trend_info else "SIDE"
        trend_x4 = trend_info.get("trend_x4", "SIDE") if trend_info else "SIDE"
        logger.debug(f"[v3.572] {symbol} 双底双顶趋势检查: 当前={current_trend}, x4={trend_x4}, market={market_type}")

        # v3.572: 检查每日限制 - 如果买卖都用完则完全冻结 (使用x4趋势)
        state = self.double_pattern_state[symbol]
        if state.get("buy_used") and state.get("sell_used"):
            can_trade, reason = check_plugin_daily_limit(state, "BUY", trend_x4=trend_x4, current_trend=current_trend, market_type=market_type)
            if not can_trade:
                logger.debug(f"[{symbol}] 双底双顶 {reason}")
                return

        # v3.546: 获取4小时K线数据 (v21: plugin不再使用bars, 但current_price/L2/周期检查仍需要)
        bars = YFinanceDataFetcher.get_4h_ohlcv(symbol, 50)
        if not bars or len(bars) < 20:
            logger.debug(f"[{symbol}] 双底双顶: 4小时K线数据不足")
            return

        # 获取当前K线时间戳
        current_bar_time = None
        if bars:
            last_bar = bars[-1]
            current_bar_time = last_bar.get("timestamp") or last_bar.get("time")
            if current_bar_time and not isinstance(current_bar_time, str):
                current_bar_time = str(current_bar_time)

        # v21.14: 移除per-bar周期限制 (N字门控替代), 仅保留每日配额

        # 获取市场数据 (current_trend和trend_x4已在前面获取)
        market_data = self._get_market_data_for_supertrend(symbol)
        pos_in_channel = market_data.get("position_pct", 50) / 100.0
        current_price = bars[-1]["close"] if bars else 0
        symbol_tf_minutes = read_symbol_timeframe(REVERSE_SYMBOL_MAP.get(symbol, symbol), default=240)
        plugin_scan_interval_seconds = SCAN_INTERVAL_BY_TF.get(symbol_tf_minutes, 300)

        # GCC-0046: 扫描引擎直接调用Vision形态识别 (脱离TV依赖)
        # analyze_patterns内部有4H冷却(PATTERN_COOLDOWN_MINUTES=240)，不会每次都调API
        # 冷却期内返回None，plugin继续读上次的pattern_latest.json缓存
        pattern_lookup_symbol = REVERSE_SYMBOL_MAP.get(symbol, symbol)
        if _vision_pattern_available and _vision_get_symbols_config:
            _v_cfgs = _vision_get_symbols_config()
            _v_cfg = _v_cfgs.get(pattern_lookup_symbol)
            if _v_cfg:
                try:
                    _v_result = _vision_analyze_patterns(pattern_lookup_symbol, _v_cfg)
                    if _v_result:
                        logger.info(f"[GCC-0046] {symbol} Vision形态刷新: {_v_result.get('pattern','NONE')} "
                                    f"stage={_v_result.get('stage','NONE')} conf={_v_result.get('confidence',0):.2f}")
                except Exception as _ve:
                    logger.warning(f"[GCC-0046] {symbol} Vision形态调用异常: {_ve}")

        # 调用外挂 (读取pattern_latest.json — 上面的Vision调用已刷新)
        try:
            plugin = get_double_pattern_plugin()
            result = plugin.process_for_scan(
                symbol=pattern_lookup_symbol,
                ohlcv_bars=bars,
                current_trend=current_trend,
                pos_in_channel=pos_in_channel,
                current_price=current_price,
            )
        except Exception as e:
            logger.error(f"[{symbol}] 双底双顶外挂异常: {e}")
            return

        # 检查是否应该激活
        if not plugin.should_activate_for_scan(result):
            return

        action = plugin.get_action_for_scan(result)
        if action not in ("BUY", "SELL"):
            return

        # v3.620: 双底双顶取消x4和当前周期方向限制 (形态反转本身就是逆势信号，不应被趋势过滤)
        # 其他外挂(SuperTrend/RobHoffman/飞云等)仍保留顺大逆小过滤
        logger.debug(f"[v3.620] {symbol} 双底双顶 {action} 跳过x4过滤 (x4={trend_x4}, 当前={current_trend})")

        # v21.8: 共识度日志 (双底双顶不用共识拦截, 但记录供复盘)
        _consensus = calc_consensus_score(symbol, action, trend_info)
        log_consensus_score(symbol, action, "双底双顶", _consensus)



        # 安全期: 仅满仓/空仓限制，区间检查已移除
        position_units = self._get_position_from_main_state(symbol)
        max_units = MAX_UNITS_PER_SYMBOL
        if action == "BUY" and position_units >= max_units:
            logger.info(f"[{symbol}] VisionPattern: 满仓({position_units}/{max_units})，跳过BUY")
            return
        if action == "SELL" and position_units <= 0:
            logger.info(f"[{symbol}] VisionPattern: 无仓位，跳过SELL")
            return

        # v3.572: 检查该方向是否已用完 (使用x4趋势顺大逆小)
        state = self.double_pattern_state[symbol]
        can_trade, limit_reason = check_plugin_daily_limit(state, action, trend_x4=trend_x4, current_trend=current_trend, market_type=market_type)
        if not can_trade:
            logger.info(f"[v3.572] {symbol} 双底双顶 {action} 被限制: {limit_reason} (x4={trend_x4})")
            return

        # 触发信号!
        logger.info(f"[VisionPattern] {symbol} 形态触发{action}!")
        logger.info(f"  ├─ 形态: {result.pattern.value if result.pattern else 'N/A'}")
        logger.info(f"  ├─ 阶段: {result.stage.value if result.stage else 'N/A'}")
        logger.info(f"  ├─ 置信度: {result.confidence:.2f}")
        logger.info(f"  └─ 原因: {result.reason}")

        # v3.546: 记录4小时周期触发状态
        if current_bar_time:
            self.double_pattern_cycle_state[symbol] = {
                "last_trigger_bar": current_bar_time,
                "triggered_direction": action
            }

        # v16.7: 移除提前配额更新，改为执行成功后更新
        state["last_signal"] = action
        state["last_trigger_time"] = datetime.now().isoformat()

        # KEY-004: 因子观测台 record_signal — double_pattern (fail-silent, 当前运行)
        try:
            from factor_db import record_signal as _rs_dp
            _dp_regime = str(detect_dc_regime(bars, current_price)) if bars else None
            _rs_dp(symbol=symbol, factor_name="double_pattern",
                   signal=1 if action == "BUY" else -1,
                   market_regime=_dp_regime,
                   close_price=float(current_price))
        except Exception:
            pass

        # KEY-007: Plugin KNN记录+查询 — double_pattern (Phase1: 仅日志)
        try:
            from plugin_knn import extract_double_pattern_features, plugin_knn_record_and_query, plugin_knn_should_suppress, infer_regime_from_bars
            _pknn_feat = extract_double_pattern_features(result, bars)
            _pknn_ind = {"confidence": float(getattr(result, 'confidence', 0) or 0)}
            _pknn_res = plugin_knn_record_and_query("double_pattern", symbol, _pknn_feat, action,
                                                     close_price=float(current_price), indicator_values=_pknn_ind,
                                                     regime=infer_regime_from_bars(bars))
            if plugin_knn_should_suppress(action, _pknn_res):
                logger.info(f"[PLUGIN_KNN][抑制] {symbol} VisionPattern {action} ← KNN反向{_pknn_res.bias}")
                return
        except Exception:
            pass

        # 构建信号数据
        signal_data = {
            "signal": action,
            "price": current_price,
            "base_price": current_price,
            "change_pct": 0,
            "timeframe": "4h",  # v3.546: 改为4小时周期
            "timestamp": datetime.now().isoformat(),
            "type": market_type,
            "signal_type": "VisionPattern",
            "current_trend": current_trend,
            "reason": result.reason,
            "position_pct": market_data.get("position_pct", 50),
            "activate_double_pattern_plugin": True,
            "pattern": result.pattern.value if result.pattern else "NONE",
            "neckline": result.neckline,
            "target": result.target,
            "stop_loss": result.stop_loss,
            "symbol_timeframe_minutes": symbol_tf_minutes,
            "plugin_scan_interval_seconds": plugin_scan_interval_seconds,
        }

        # v21: 观察/执行模式检查
        is_observe = (market_type == "stock" and VISION_PATTERN_OBSERVE_STOCK) or \
                     (market_type == "crypto" and VISION_PATTERN_OBSERVE_CRYPTO)

        main_symbol = REVERSE_SYMBOL_MAP.get(symbol, symbol)

        if is_observe:
            # 观察模式: 记录日志 + 发邮件, 不执行交易
            logger.info(f"[VisionPattern][OBSERVE] {symbol} {action} → 观察模式，不执行交易")
            logger.info(f"  ├─ 形态: {result.pattern.value} conf={result.confidence:.2f}")
            logger.info(f"  └─ 原因: {result.reason}")
            signal_data["observe_mode"] = True
            self.email_notifier.send_signal_notification(symbol, signal_data)
            return

        # 执行模式: 通知主程序
        server_response = self._notify_main_server(main_symbol, signal_data)

        signal_data["server_executed"] = server_response.get("executed", False)
        signal_data["server_reason"] = server_response.get("reason", "")

        # v16.7: 只在实际执行成功时更新配额和发送邮件
        if server_response.get("executed", False):
            status_msg = update_plugin_daily_state(state, action)
            logger.info(f"[VisionPattern] {symbol} 执行成功，更新配额: {status_msg}")
            self._save_double_pattern_state()
            self.email_notifier.send_signal_notification(symbol, signal_data)
        else:
            logger.info(f"[VisionPattern] {symbol}: 未执行({server_response.get('reason', '')}), 不消耗配额")

        # v3.550: 外挂利润追踪
        if self.profit_tracker:
            self.profit_tracker.record_trade(
                symbol=main_symbol, plugin_name="VisionPattern",
                action=action, price=current_price,
                executed=server_response.get("executed", False),
                asset_type=market_type)

    # ========================================================================
    # v3.671: N字结构外挂扫描
    # ========================================================================

    def _scan_n_structure(self, symbol: str, market_type: str = "crypto"):
        """
        N字结构外挂 (v1.0) — 读取 n_structure_state.json，状态转换时生成 BUY/SELL 信号。

        信号规则:
          PERFECT_N  + UP   → BUY
          PERFECT_N  + DOWN → SELL
          UP_BREAK   + UP   → BUY  (突破加速)
          DOWN_BREAK + DOWN → SELL (破位加速)
          其余状态 → 无信号 (DEEP_PULLBACK保守不生成)
        """
        try:
            from n_structure_plugin import check_signal as _ns_check
        except ImportError:
            logger.warning("[NStructPlugin] n_structure_plugin.py 未找到，N字外挂禁用")
            return

        # 启动冷却
        if time.time() - self.startup_time < self.STARTUP_COOLDOWN_SECONDS:
            return

        main_symbol = REVERSE_SYMBOL_MAP.get(symbol, symbol)

        # 获取信号
        action, reason, quality = _ns_check(main_symbol)
        if not action:
            logger.debug(f"[NStructPlugin] {main_symbol} 无信号: {reason}")
            return

        # 获取市场数据
        market_data = self._get_market_data_for_supertrend(symbol)

        # 获取K线和价格 (market_data无current_price字段，需从yfinance取)
        bars = YFinanceDataFetcher.get_4h_ohlcv(symbol, 30)
        if not bars or len(bars) < 5:
            logger.info(f"[NStructPlugin] {main_symbol} K线数据不足，跳过")
            return
        current_price = bars[-1]["close"]
        if not current_price or current_price <= 0:
            logger.info(f"[NStructPlugin] {main_symbol} 无价格数据，跳过")
            return

        # 趋势信息
        trend_info = self._get_trend_for_plugin(symbol)
        current_trend = trend_info.get("trend", "SIDE") if trend_info else "SIDE"



        # 安全期: 仅满仓/空仓限制，区间检查已移除
        position_units = self._get_position_from_main_state(symbol)
        if action == "BUY" and position_units >= MAX_UNITS_PER_SYMBOL:
            logger.info(f"[NStructPlugin] {main_symbol} BUY: 满仓，跳过")
            return
        if action == "SELL" and position_units <= 0:
            logger.info(f"[NStructPlugin] {main_symbol} SELL: 空仓，跳过")
            return

        # 每日配额: 1买+1卖/天
        if not hasattr(self, 'n_struct_state'):
            self.n_struct_state = {}
        if main_symbol not in self.n_struct_state:
            self.n_struct_state[main_symbol] = {"buy_used": False, "sell_used": False,
                                                 "reset_date": None, "freeze_until": None}
        can_trade, limit_reason = check_plugin_daily_limit(
            self.n_struct_state[main_symbol], action)
        if not can_trade:
            logger.info(f"[NStructPlugin] {main_symbol} {action} 配额限制: {limit_reason}")
            return

        # v21.20: 分型过滤 — v3.670: 已取消

        # KEY-004: 因子观测台记录
        try:
            from factor_db import record_signal as _rs_ns
            _rs_ns(symbol=main_symbol, factor_name="n_structure",
                   signal=1 if action == "BUY" else -1,
                   market_regime=str(detect_dc_regime(bars, current_price)) if bars else None,
                   close_price=float(current_price))
        except Exception:
            pass

        # 触发信号
        logger.info(f"[NStructPlugin] {main_symbol} {action} 触发! quality={quality:.2f} {reason}")

        signal_data = {
            "signal": action,
            "price": current_price,
            "base_price": current_price,
            "change_pct": 0,
            "timeframe": "4h",
            "timestamp": datetime.now().isoformat(),
            "type": market_type,
            "signal_type": "N字结构",
            "current_trend": current_trend,
            "reason": reason,
            "position_pct": market_data.get("position_pct", 50),
            "n_quality": quality,
        }

        server_response = self._notify_main_server(main_symbol, signal_data)
        if server_response.get("executed", False):
            update_plugin_daily_state(self.n_struct_state[main_symbol], action)

    # ========================================================================
    # v21.1: 缠论买卖点外挂扫描
    # ========================================================================

    def _scan_chan_bs(self, symbol: str, market_type: str = "crypto"):
        """
        v21.1: 缠论买卖点外挂扫描 (4H, 一/二/三买卖点)

        策略规则:
        - 基于czsc库的笔/中枢检测
        - 一买/二买/三买 → BUY, 一卖/二卖/三卖 → SELL
        - 配额: 1买+1卖/天, 执行后冻结至次日8AM NY
        - 仓位范围: 无限制

        使用4小时K线数据, lookback=120
        """
        if not _chan_bs_available:
            return

        # 检查配置
        chan_bs_config = self.config[market_type].get("chan_bs", {})
        if not chan_bs_config.get("enabled", True):
            return

        # 启动冷却期检查
        if time.time() - self.startup_time < self.STARTUP_COOLDOWN_SECONDS:
            return

        # 初始化状态
        if symbol not in self.chan_bs_state:
            self.chan_bs_state[symbol] = {
                "freeze_until": None,
                "last_signal": None,
                "last_trigger_time": None,
                "buy_used": False,
                "sell_used": False,
                "reset_date": None,
            }

        # 获取趋势信息
        trend_info = self._get_trend_for_plugin(symbol)
        current_trend_for_limit = trend_info.get("trend", "SIDE") if trend_info else "SIDE"
        trend_x4 = trend_info.get("trend_x4", "SIDE") if trend_info else "SIDE"
        logger.debug(f"[v21.1] {symbol} 缠论BS趋势检查: 当前={current_trend_for_limit}, x4={trend_x4}, market={market_type}")

        # 检查每日限制 - 如果买卖都用完则完全冻结
        state = self.chan_bs_state[symbol]
        if state.get("buy_used") and state.get("sell_used"):
            can_trade, reason = check_plugin_daily_limit(state, "BUY", trend_x4=trend_x4, current_trend=current_trend_for_limit, market_type=market_type)
            if not can_trade:
                logger.debug(f"[{symbol}] 缠论BS {reason}")
                return

        # 获取4小时K线数据 (120根 ≈ 20天, 保证足够的笔和中枢)
        bars = YFinanceDataFetcher.get_4h_ohlcv(symbol, 120)
        if not bars or len(bars) < 30:
            logger.info(f"[{symbol}] 缠论BS: 4小时K线数据不足 (获取={len(bars) if bars else 0}根)")
            return

        # 获取当前K线时间戳
        current_bar_time = None
        if bars:
            last_bar = bars[-1]
            current_bar_time = last_bar.get("timestamp") or last_bar.get("time")
            if current_bar_time and not isinstance(current_bar_time, str):
                current_bar_time = str(current_bar_time)

        # v21.14: 移除per-bar周期限制 (N字门控替代), 仅保留每日配额

        # 获取市场数据
        market_data = self._get_market_data_for_supertrend(symbol)
        current_trend = market_data.get("current_trend", "SIDE")

        # 调用外挂
        try:
            plugin = get_chan_bs_plugin()
            from chan_bs_plugin import get_symbol_min_strength as _chanbs_min_str
            _chanbs_ms = _chanbs_min_str(symbol)
            result = plugin.process_for_scan(
                symbol=symbol,
                ohlcv_bars=bars,
                current_trend=current_trend,
                min_strength=_chanbs_ms,
            )
        except Exception as e:
            logger.error(f"[{symbol}] 缠论BS外挂异常: {e}")
            return

        # 检查是否应该激活
        if not plugin.should_activate_for_scan(result, min_strength=_chanbs_ms):
            logger.info(f"[{symbol}] 缠论BS: 扫描完成, 未激活 (笔={result.bi_count}, 中枢={result.zs_count}, {result.reason})")
            return

        action = plugin.get_action_for_scan(result)
        if action not in ("BUY", "SELL"):
            logger.info(f"[{symbol}] 缠论BS: 扫描完成, 无买卖动作 (action={action})")
            return

        is_bs1 = (
            result.bs_type in (ChanBSPoint.BUY_1, ChanBSPoint.SELL_1)
            if (result and result.bs_type and ChanBSPoint is not None)
            else False
        )

        logger.info(f"[缠论BS] {symbol} {result.bs_type.value}触发{action}! (强度={result.strength:.0%})")

        # v21.8: 缓存缠论BS方向 + 共识度日志
        update_consensus_direction(symbol, "current_trend", "UP" if action == "BUY" else "DOWN")
        _consensus = calc_consensus_score(symbol, action, trend_info)
        log_consensus_score(symbol, action, "缠论BS", _consensus)


        # v21.7: current_price 提前定义 (rhythm/dc_regime检查需要)
        current_price = bars[-1]["close"] if bars and len(bars) > 0 else 0.0


        # 检查该方向配额
        state = self.chan_bs_state[symbol]
        can_trade, limit_reason = check_plugin_daily_limit(state, action, trend_x4=trend_x4, current_trend=current_trend_for_limit, market_type=market_type)
        if not can_trade:
            logger.info(f"[v21.1] {symbol} 缠论BS {action} 被限制: {limit_reason} (x4={trend_x4})")
            return

        # v21.17: 检查实际持仓 (读取max_units, 避免满仓买入或无仓位卖出)
        position_units, _max_units = self._get_position_and_max(symbol)
        if action == "BUY" and position_units >= _max_units:
            logger.info(f"[{symbol}] 缠论BS: 满仓({position_units}/{_max_units})，跳过BUY (保护配额)")
            return
        if action == "SELL" and position_units <= 0:
            logger.info(f"[{symbol}] 缠论BS: 无仓位({position_units}/{_max_units})，跳过SELL (保护配额)")
            return

        # Position Control检查
        current_price = bars[-1]["close"] if bars else 0.0
        ema10 = calculate_ema10(bars) if bars else 0.0
        pos_allowed, pos_reason, target_pos = check_position_control(
            position_units, action, trend_x4, current_trend_for_limit, "缠论BS",
            current_price, ema10, bars
        )
        log_signal_decision(symbol, action, position_units, pos_allowed, pos_reason, target_pos, "缠论BS", current_price, trend_x4, current_trend_for_limit)
        if not pos_allowed:
            logger.info("=" * 70)
            logger.info(f"[v21.1] {symbol} 缠论BS {action} → HOLD")
            logger.info(f"  ├─ 当前仓位: {position_units}/5")
            logger.info(f"  ├─ 当前价格: {current_price:.2f}")
            logger.info(f"  └─ 原因: {pos_reason}")
            logger.info("=" * 70)
            return

        # v21.20: 分型过滤 — v3.670: 已取消

        # 触发信号!
        logger.info(f"[v21.1] {symbol} 缠论BS触发{action}!")
        logger.info(f"  ├─ 类型: {result.bs_type.value}")
        logger.info(f"  ├─ 强度: {result.strength:.0%}")
        logger.info(f"  ├─ 中枢: [{result.zs_zd:.2f} ~ {result.zs_zg:.2f}]")
        logger.info(f"  ├─ 仓位: {position_units}/5 → 目标: {target_pos}/5")
        logger.info(f"  └─ 原因: {result.reason}")

        # 记录4小时周期触发状态
        if current_bar_time:
            self.chan_bs_cycle_state[symbol] = {
                "last_trigger_bar": current_bar_time,
                "triggered_direction": action
            }

        state["last_signal"] = action
        state["last_trigger_time"] = datetime.now().isoformat()

        # KEY-004: 因子观测台 record_signal — chan_bi (fail-silent)
        try:
            from factor_db import record_signal as _rs_chan
            _rs_chan(symbol=symbol, factor_name="chan_bi",
                     signal=1 if action == "BUY" else -1,
                     market_regime=str(detect_dc_regime(bars, current_price)) if bars else None,
                     close_price=float(current_price))
        except Exception:
            pass

        # KEY-007: Plugin KNN记录+查询 — chan_bi (Phase1: 仅日志)
        try:
            from plugin_knn import extract_chanbs_features, plugin_knn_record_and_query, plugin_knn_should_suppress, infer_regime_from_bars
            _pknn_feat = extract_chanbs_features(result, bars)
            _pknn_ind = {"strength": float(getattr(result, 'strength', 0) or 0),
                         "zs_count": float(getattr(result, 'zs_count', 0) or 0)}
            _pknn_res = plugin_knn_record_and_query("chan_bi", symbol, _pknn_feat, action,
                                                     close_price=float(current_price), indicator_values=_pknn_ind,
                                                     regime=infer_regime_from_bars(bars))
            if plugin_knn_should_suppress(action, _pknn_res):
                logger.info(f"[PLUGIN_KNN][抑制] {symbol} ChanBS {action} ← KNN反向{_pknn_res.bias}")
                return
        except Exception:
            pass

        # 构建信号数据
        position_rule_desc = self._get_position_rule_desc(position_units, action)

        signal_data = {
            "signal": action,
            "price": current_price,
            "base_price": current_price,
            "change_pct": 0,
            "timeframe": "4h",
            "timestamp": datetime.now().isoformat(),
            "type": market_type,
            "signal_type": "ChanBS",
            "current_trend": current_trend,
            "reason": result.reason,
            "position_pct": market_data.get("position_pct", 50),
            "activate_chan_bs_plugin": True,
            "bs_type": result.bs_type.value if result.bs_type else "NONE",
            "strength": result.strength,
            "stop_loss": result.stop_loss,
            "target": result.target,
            "zs_zg": result.zs_zg,
            "zs_zd": result.zs_zd,
            "bi_count": result.bi_count,
            "zs_count": result.zs_count,
            # 仓位控制信息
            "position_units": position_units,
            "position_control_rule": position_rule_desc,
            "target_position": target_pos,
            "sell_units": position_units - target_pos if action == "SELL" else 0,
            "position_valid_range": "无限制",
        }

        # v21.26: 缠论恢复执行模式 — 信号同时推入GCC-TM信号池 + 走正常执行路径
        main_symbol = REVERSE_SYMBOL_MAP.get(symbol, symbol)

        # GCC-TM: 4H缠论不再推入信号池 (v0.3: 信号池只接受15min级别信号源)
        # 原: gcc_push_signal(symbol, "ChanBS", action, _chanbs_conf)

        server_response = self._notify_main_server(main_symbol, signal_data)
        signal_data["server_executed"] = server_response.get("executed", False)
        signal_data["server_reason"] = server_response.get("reason", "")
        if server_response.get("executed", False):
            status_msg = update_plugin_daily_state(state, action, trend=current_trend_for_limit, market_type=market_type)
            logger.info(f"[v21.1] {symbol} 缠论BS 执行成功，更新配额: {status_msg}")
            self._save_chan_bs_state()
            self.email_notifier.send_signal_notification(symbol, signal_data)
        else:
            logger.info(f"[{symbol}] 缠论BS: 未执行({server_response.get('reason', '')}), 不消耗配额")

        # 外挂利润追踪
        if self.profit_tracker:
            self.profit_tracker.record_trade(
                symbol=main_symbol, plugin_name="ChanBS",
                action=action, price=current_price,
                executed=server_response.get("executed", False),
                asset_type=market_type)

    # _scan_brooks_pa: 已删除 (合并到 Brooks Vision brooks_vision.py)

    # ========================================================================
    # v3.545: 飞云双突破外挂扫描
    # ========================================================================

    def _scan_feiyun(self, symbol: str, market_type: str = "crypto"):
        """
        v3.545: 飞云双突破外挂扫描 (L1层集成到扫描引擎)
        v3.550: 支持加密货币和美股市场

        策略规则:
        - 趋势线突破 + 形态突破 + UP趋势 → BUY
        - 趋势线跌破 + 形态跌破 + DOWN趋势 → SELL
        - v3.546: 4小时周期，每日买卖各1次后冻结到次日8AM

        使用4小时K线数据
        """
        if not _feiyun_available:
            return

        # 检查配置
        feiyun_config = self.config[market_type].get("feiyun", {})
        if not feiyun_config.get("enabled", True):
            return

        # 启动冷却期检查
        if time.time() - self.startup_time < self.STARTUP_COOLDOWN_SECONDS:
            return

        # v3.546: 初始化状态（包含每日买卖限制）
        if symbol not in self.feiyun_state:
            self.feiyun_state[symbol] = {
                "freeze_until": None,
                "last_signal": None,
                "last_trigger_time": None,
                "buy_used": False,
                "sell_used": False,
                "reset_date": None,
            }

        # v3.571: 获取当前周期L1趋势和x4大周期趋势
        trend_info = self._get_trend_for_plugin(symbol)
        current_trend_for_limit = trend_info.get("trend", "SIDE") if trend_info else "SIDE"
        trend_x4 = trend_info.get("trend_x4", "SIDE") if trend_info else "SIDE"
        logger.debug(f"[v3.571] {symbol} 飞云趋势检查: 当前={current_trend_for_limit}, x4={trend_x4}, market={market_type}")

        # v3.572: 检查每日限制 - 如果买卖都用完则完全冻结 (使用x4趋势)
        state = self.feiyun_state[symbol]
        if state.get("buy_used") and state.get("sell_used"):
            can_trade, reason = check_plugin_daily_limit(state, "BUY", trend_x4=trend_x4, current_trend=current_trend_for_limit, market_type=market_type)
            if not can_trade:
                logger.debug(f"[{symbol}] 飞云 {reason}")
                return

        # v3.546: 获取4小时K线数据
        bars = YFinanceDataFetcher.get_4h_ohlcv(symbol, 40)
        if not bars or len(bars) < 15:
            logger.info(f"[{symbol}] 飞云: 4小时K线数据不足 (获取={len(bars) if bars else 0}根)")
            return

        # 获取当前K线时间戳
        current_bar_time = None
        if bars:
            last_bar = bars[-1]
            current_bar_time = last_bar.get("timestamp") or last_bar.get("time")
            if current_bar_time and not isinstance(current_bar_time, str):
                current_bar_time = str(current_bar_time)

        # v21.14: 移除per-bar周期限制 (N字门控替代), 仅保留每日配额

        # 获取市场数据
        market_data = self._get_market_data_for_supertrend(symbol)
        current_trend = market_data.get("current_trend", "SIDE")
        pos_in_channel = market_data.get("position_pct", 50) / 100.0
        position_units = market_data.get("position_units", 0)  # v16.4: 实际持仓

        # 调用外挂
        try:
            plugin = get_feiyun_plugin()
            result = plugin.process(
                symbol=symbol,
                ohlcv_bars=bars,
                current_trend=current_trend,
                pos_in_channel=pos_in_channel,
                position_units=position_units,  # v16.4: 传递持仓供退出判断
            )
        except Exception as e:
            logger.error(f"[{symbol}] 飞云外挂异常: {e}")
            return

        # 检查是否应该激活 (只激活双突破)
        if not plugin.should_activate(result):
            logger.info(f"[{symbol}] 飞云: 扫描完成, 未激活 (信号={result.signal.value if result else 'None'})")
            return

        action = "BUY" if result.signal == FeiyunSignal.DOUBLE_BREAK_BUY else "SELL"




        # v3.572: 检查该方向是否已用完 (使用x4趋势顺大逆小)
        state = self.feiyun_state[symbol]
        can_trade, limit_reason = check_plugin_daily_limit(state, action, trend_x4=trend_x4, current_trend=current_trend_for_limit, market_type=market_type)
        if not can_trade:
            logger.info(f"[v3.572] {symbol} 飞云 {action} 被限制: {limit_reason} (x4={trend_x4})")
            return

        # v21.17: 检查实际持仓 (读取max_units, 避免满仓买入或无仓位卖出)
        position_units, _max_units = self._get_position_and_max(symbol)
        if action == "BUY" and position_units >= _max_units:
            logger.info(f"[{symbol}] 飞云: 满仓({position_units}/{_max_units})，跳过BUY (保护配额)")
            return
        if action == "SELL" and position_units <= 0:
            logger.info(f"[{symbol}] 飞云: 无仓位({position_units}/{_max_units})，跳过SELL (保护配额)")
            return

        # 区间限制已移除，保留EMA Position Control检查
        current_price = bars[-1]["close"] if bars else 0.0
        ema10 = calculate_ema10(bars) if bars else 0.0
        pos_allowed, pos_reason, target_pos = check_position_control(
            position_units, action, trend_x4, current_trend_for_limit, "飞云",
            current_price, ema10, bars
        )
        log_signal_decision(symbol, action, position_units, pos_allowed, pos_reason, target_pos, "飞云", current_price, trend_x4, current_trend_for_limit)
        if not pos_allowed:
            logger.info(f"[v19] {symbol} 飞云 {action} → HOLD | {pos_reason}")
            return

        # 触发信号!
        logger.info(f"[v19] {symbol} 飞云双突破触发{action}!")
        logger.info(f"  ├─ 信号: {result.signal.value}")
        logger.info(f"  ├─ 双突破: {result.is_double}")
        logger.info(f"  ├─ 置信度: {result.confidence:.2f}")
        logger.info(f"  ├─ 仓位: {position_units}/5 → 目标: {target_pos}/5")
        logger.info(f"  └─ 原因: {result.reason}")

        # v3.546: 记录4小时周期触发状态
        if current_bar_time:
            self.feiyun_cycle_state[symbol] = {
                "last_trigger_bar": current_bar_time,
                "triggered_direction": action
            }

        # v16.7: 移除提前配额更新，改为执行成功后更新
        state["last_signal"] = action
        state["last_trigger_time"] = datetime.now().isoformat()

        # 构建信号数据
        current_price = bars[-1]["close"] if bars else 0

        # KEY-004: 因子观测台 record_signal — feiyun (fail-silent, 当前暂停)
        try:
            from factor_db import record_signal as _rs_fy
            _rs_fy(symbol=symbol, factor_name="feiyun",
                   signal=1 if action == "BUY" else -1,
                   market_regime=str(detect_dc_regime(bars, current_price)) if bars else None,
                   close_price=float(current_price))
        except Exception:
            pass

        # KEY-007: Plugin KNN记录+查询 — feiyun (Phase1: 仅日志)
        try:
            from plugin_knn import extract_feiyun_features, plugin_knn_record_and_query, plugin_knn_should_suppress, infer_regime_from_bars
            _pknn_feat = extract_feiyun_features(result, bars)
            _pknn_ind = {"confidence": float(getattr(result, 'confidence', 0) or 0),
                         "is_double": 1.0 if getattr(result, 'is_double', False) else 0.0}
            _pknn_res = plugin_knn_record_and_query("feiyun", symbol, _pknn_feat, action,
                                                     close_price=float(current_price), indicator_values=_pknn_ind,
                                                     regime=infer_regime_from_bars(bars))
            if plugin_knn_should_suppress(action, _pknn_res):
                logger.info(f"[PLUGIN_KNN][抑制] {symbol} 飞云 {action} ← KNN反向{_pknn_res.bias}")
                return
        except Exception:
            pass

        # v19: 获取仓位控制规则描述
        position_rule_desc = self._get_position_rule_desc(position_units, action)

        signal_data = {
            "signal": action,
            "price": current_price,
            "base_price": current_price,
            "change_pct": 0,
            "timeframe": "4h",  # v3.546: 改为4小时周期
            "timestamp": datetime.now().isoformat(),
            "type": market_type,
            "signal_type": "Feiyun",
            "current_trend": current_trend,
            "reason": result.reason,
            "position_pct": market_data.get("position_pct", 50),
            "activate_feiyun_plugin": True,
            "is_double_break": result.is_double,
            "confidence": result.confidence,
            "entry_price": result.entry_price,
            "stop_loss": result.stop_loss,
            "take_profit": result.take_profit,
            # v17.4: 仓位控制信息
            "position_units": position_units,
            "position_control_rule": position_rule_desc,
            # v19: 目标仓位信息
            "target_position": target_pos,
            "sell_units": position_units - target_pos if action == "SELL" else 0,
            # v20.2: 仓位区间限制 (突破入场策略)
            "position_valid_range": "[0-2]" if action == "BUY" else "[3-5]",
        }

        # 通知主程序
        main_symbol = REVERSE_SYMBOL_MAP.get(symbol, symbol)
        server_response = self._notify_main_server(main_symbol, signal_data)

        signal_data["server_executed"] = server_response.get("executed", False)
        signal_data["server_reason"] = server_response.get("reason", "")

        # v16.7: 只在实际执行成功时更新配额和发送邮件
        if server_response.get("executed", False):
            status_msg = update_plugin_daily_state(state, action, trend=current_trend_for_limit, market_type=market_type)
            logger.info(f"[v16.7] {symbol} 飞云 执行成功，更新配额: {status_msg}")
            self._save_feiyun_state()  # v15.1: 持久化保存
            self.email_notifier.send_signal_notification(symbol, signal_data)
        else:
            logger.info(f"[{symbol}] 飞云: 未执行({server_response.get('reason', '')}), 不消耗配额")

        # v3.550: 外挂利润追踪
        if self.profit_tracker:
            self.profit_tracker.record_trade(
                symbol=main_symbol, plugin_name="Feiyun",
                action=action, price=current_price,
                executed=server_response.get("executed", False),
                asset_type=market_type)

    # v21.16: _scan_macd_divergence 已删除 (扫描引擎MACD移除, 仅保留L2小周期版本)

    # ═══════════════════════════════════════════════════════════
    # GCC-0258 S11: 15min多周期外挂扫描 — 填充GCC-TM信号池
    # 复用现有外挂(Hoffman/缠论/SuperTrend), 喂15min K线产生高频信号
    # ═══════════════════════════════════════════════════════════
    def _scan_plugins_15m(self, symbol: str, market_type: str = "crypto"):
        """
        GCC-0258 S11: 15min子周期外挂扫描, 信号推入GCC-TM信号池。
        不影响现有4H外挂逻辑和主程序交易路径。
        每30分钟调用一次, 15min K线每次有2根新数据。
        """
        try:
            from gcc_trading_module import gcc_push_signal as _gcc_push_15m
        except ImportError:
            return

        main_symbol = REVERSE_SYMBOL_MAP.get(symbol, symbol)

        # ── 获取15min K线 ──
        bars_15m = YFinanceDataFetcher.get_15m_ohlcv(symbol, 60)  # 60根=15小时
        if not bars_15m or len(bars_15m) < 30:
            logger.debug(f"[S11] {symbol} 15m K线不足({len(bars_15m) if bars_15m else 0}根), 跳过")
            return

        # 趋势信息(大周期, 用于过滤)
        trend_info = self._get_trend_for_plugin(symbol)
        current_trend = trend_info.get("trend", "SIDE") if trend_info else "SIDE"
        pos_in_channel = 0.5

        try:
            market_data = self._get_market_data_for_supertrend(symbol)
            pos_in_channel = market_data.get("position_pct", 50) / 100.0
        except Exception:
            pass

        pushed = 0

        # ── 1. Hoffman 15m ──
        if _rob_hoffman_available:
            try:
                plugin = get_rob_hoffman_plugin()
                result = plugin.process_for_scan(
                    symbol=symbol,
                    ohlcv_bars=bars_15m,
                    current_trend=current_trend,
                    pos_in_channel=pos_in_channel,
                    position_units=0,  # 15m信号不做仓位判断
                )
                if plugin.should_activate_for_scan(result):
                    action = plugin.get_action_for_scan(result)
                    if action in ("BUY", "SELL"):
                        _gcc_push_15m(main_symbol, "Hoffman_15m", action, min(0.7, result.confidence))
                        pushed += 1
                        logger.info(f"[S11] {symbol} Hoffman_15m → {action} (conf={result.confidence:.2f})")
            except Exception as e:
                logger.debug(f"[S11] {symbol} Hoffman_15m error: {e}")

        # ── 2. 缠论 15m ──
        if _chan_bs_available:
            try:
                bars_15m_long = YFinanceDataFetcher.get_15m_ohlcv(symbol, 200)  # 缠论需要更多数据
                if bars_15m_long and len(bars_15m_long) >= 60:
                    chan_plugin = get_chan_bs_plugin()
                    chan_result = chan_plugin.process_for_scan(
                        symbol=symbol,
                        ohlcv_bars=bars_15m_long,
                        current_trend=current_trend,
                    )
                    if chan_plugin.should_activate_for_scan(chan_result):
                        action = chan_plugin.get_action_for_scan(chan_result)
                        if action in ("BUY", "SELL"):
                            _conf = min(0.7, chan_result.strength) if hasattr(chan_result, 'strength') else 0.6
                            _gcc_push_15m(main_symbol, "ChanBS_15m", action, _conf)
                            pushed += 1
                            logger.info(f"[S11] {symbol} ChanBS_15m → {action}")
            except Exception as e:
                logger.debug(f"[S11] {symbol} ChanBS_15m error: {e}")

        # ── 3. SuperTrend 15m ──
        # v0.3: 纯15min数据, 不传4H l1_signals/market_data, 方向过滤交给Vision门控
        if _supertrend_available:
            try:
                st_config = self.config[market_type].get("supertrend", {})
                if st_config.get("enabled", False):
                    close_prices_15m = [b["close"] for b in bars_15m]
                    plugin = get_supertrend_plugin()
                    st_result = plugin.process(
                        symbol=symbol,
                        ohlcv_bars=bars_15m,
                        close_prices=close_prices_15m,
                        l1_signals={},       # 空: 不混入4H信号
                        market_data={},      # 空: 纯15min判断
                    )
                    if st_result and st_result.action in ("BUY", "SELL"):
                        _gcc_push_15m(main_symbol, "SuperTrend_15m", st_result.action, 0.6)
                        pushed += 1
                        logger.info(f"[S11] {symbol} SuperTrend_15m → {st_result.action}")
            except Exception as e:
                logger.debug(f"[S11] {symbol} SuperTrend_15m error: {e}")

        # ═══════════════════════════════════════════════════════════
        # GCC-0259 S1-S4: 技术指标信号 (从15min K线直接计算, 零API成本)
        # ═══════════════════════════════════════════════════════════
        try:
            import numpy as np
            closes = np.array([float(b["close"]) for b in bars_15m])
            highs = np.array([float(b["high"]) for b in bars_15m])
            lows = np.array([float(b["low"]) for b in bars_15m])
            n = len(closes)

            if n >= 21:
                # ── S1: RSI(14) 超买超卖 ──
                delta = np.diff(closes[-(15):])  # 最近15个close→14个diff
                gain = np.where(delta > 0, delta, 0)
                loss = np.where(delta < 0, -delta, 0)
                avg_gain = np.mean(gain) if len(gain) > 0 else 0
                avg_loss = np.mean(loss) if len(loss) > 0 else 0
                if avg_loss > 0:
                    rs = avg_gain / avg_loss
                    rsi = 100 - (100 / (1 + rs))
                else:
                    rsi = 100.0 if avg_gain > 0 else 50.0

                # S1: RSI — v0.3禁用(均值回归信号, 与趋势跟随系统矛盾)
                # if rsi < 30: _gcc_push_15m(main_symbol, "RSI_15m", "BUY", 0.55)
                # elif rsi > 70: _gcc_push_15m(main_symbol, "RSI_15m", "SELL", 0.55)

                # ── S2: EMA9×EMA21 金叉死叉 ──
                def _ema(arr, period):
                    alpha = 2.0 / (period + 1)
                    ema = np.empty_like(arr, dtype=float)
                    ema[0] = arr[0]
                    for i in range(1, len(arr)):
                        ema[i] = alpha * arr[i] + (1 - alpha) * ema[i - 1]
                    return ema

                ema9 = _ema(closes, 9)
                ema21 = _ema(closes, 21)
                # 交叉检测: 前一根 vs 当前根
                if ema9[-2] <= ema21[-2] and ema9[-1] > ema21[-1]:
                    _gcc_push_15m(main_symbol, "EMA_Cross_15m", "BUY", 0.6)
                    pushed += 1
                    logger.info(f"[GCC-0259] {symbol} EMA9×21金叉 → BUY")
                elif ema9[-2] >= ema21[-2] and ema9[-1] < ema21[-1]:
                    _gcc_push_15m(main_symbol, "EMA_Cross_15m", "SELL", 0.6)
                    pushed += 1
                    logger.info(f"[GCC-0259] {symbol} EMA9×21死叉 → SELL")

                # ── S3: MACD柱状图翻转 ──
                ema12 = _ema(closes, 12)
                ema26 = _ema(closes, 26)
                macd_line = ema12 - ema26
                macd_signal = _ema(macd_line, 9)
                histogram = macd_line - macd_signal
                if histogram[-2] <= 0 and histogram[-1] > 0:
                    _gcc_push_15m(main_symbol, "MACD_Hist_15m", "BUY", 0.55)
                    pushed += 1
                    logger.info(f"[GCC-0259] {symbol} MACD柱状图翻正 → BUY")
                elif histogram[-2] >= 0 and histogram[-1] < 0:
                    _gcc_push_15m(main_symbol, "MACD_Hist_15m", "SELL", 0.55)
                    pushed += 1
                    logger.info(f"[GCC-0259] {symbol} MACD柱状图翻负 → SELL")

                # ── S3: BB(20,2) 均值回归 — 30min K线 ──
                # v3.660: 启用BB外挂(左侧交易), 用30min数据更稳定
                # 原B3独立通道合并入B1, 由GCC-TM统一决策
                try:
                    _bb_bars = None
                    if market_type == "crypto":
                        from coinbase_data_provider import get_candles as _cb_get
                        _bb_bars_raw = _cb_get(main_symbol, granularity="THIRTY_MINUTE", limit=40)
                        if _bb_bars_raw and len(_bb_bars_raw) >= 25:
                            _bb_bars_raw.sort(key=lambda x: x.get("start", "0"))
                            _bb_bars = _bb_bars_raw
                    if _bb_bars is None:
                        # 美股/fallback: 用15min合成30min
                        if n >= 50:
                            _bb_closes_30m = [(closes[j] + closes[j+1]) / 2 for j in range(0, n-1, 2)]
                        else:
                            _bb_closes_30m = None
                    else:
                        _bb_closes_30m = [float(b.get("close", 0)) for b in _bb_bars]

                    if _bb_closes_30m and len(_bb_closes_30m) >= 25:
                        _bb_arr = np.array(_bb_closes_30m)
                        _bb_window = _bb_arr[-20:]
                        _bb_mid = float(np.mean(_bb_window))
                        _bb_std = float(np.std(_bb_window, ddof=1))
                        _bb_lower = _bb_mid - 2.0 * _bb_std
                        _bb_upper = _bb_mid + 2.0 * _bb_std
                        _bb_cur = float(_bb_closes_30m[-1])

                        # RSI(14) on 30min
                        _bb_delta = np.diff(_bb_arr[-(15):])
                        _bb_gain = np.where(_bb_delta > 0, _bb_delta, 0)
                        _bb_loss = np.where(_bb_delta < 0, -_bb_delta, 0)
                        _bb_ag = float(np.mean(_bb_gain)) if len(_bb_gain) > 0 else 0
                        _bb_al = float(np.mean(_bb_loss)) if len(_bb_loss) > 0 else 0
                        _bb_rsi = 100 - (100 / (1 + _bb_ag / _bb_al)) if _bb_al > 0 else (100 if _bb_ag > 0 else 50)

                        if _bb_cur <= _bb_lower and _bb_rsi < 30:
                            _gcc_push_15m(main_symbol, "BB_MeanRev_30m", "BUY", 0.65)
                            pushed += 1
                            logger.info(f"[S3][BB] {symbol} 30m BB下轨+RSI={_bb_rsi:.0f}<30 → BUY (price={_bb_cur:.0f} lower={_bb_lower:.0f} mid={_bb_mid:.0f})")
                except Exception as _bb_e:
                    logger.debug(f"[S3][BB] {symbol} BB_30m error: {_bb_e}")

        except Exception as _ind_e:
            logger.debug(f"[GCC-0259] {symbol} 技术指标信号异常: {_ind_e}")

        if pushed > 0:
            logger.info(f"[S11+0259] {symbol} 15m扫描完成: {pushed}个信号推入GCC-TM信号池")

    def _scan_crypto(self):
        """扫描加密货币 - v3.545: P0-Tracking + 剥头皮 + L1外挂"""
        for idx, symbol in enumerate(self.config["crypto"]["symbols"]):
            try:
                # v3.572: 品种间间隔，避免API请求集中
                if idx > 0:
                    time.sleep(0.3)

                # v20.4: 每周期每品种只执行1次信号
                main_symbol = REVERSE_SYMBOL_MAP.get(symbol, symbol)

                # v21.7: 扫描频率优化 — 外挂扫描受TF间隔控制, 移动止盈止损始终扫描
                _sym_tf = read_symbol_timeframe(main_symbol, default=240)
                _scan_interval_tf = SCAN_INTERVAL_BY_TF.get(_sym_tf, 300)
                _last_scan = self._last_plugin_scan.get(main_symbol, 0)
                _should_scan_plugins = (time.time() - _last_scan) >= _scan_interval_tf

                if _should_scan_plugins:
                    self._last_plugin_scan[main_symbol] = time.time()
                    logger.info(f"[{symbol}] 扫描4外挂+移动止盈止损: SuperTrend→VisionPattern→缠论BS→MACD背离→移动止盈/止损")

                    # GCC-0141: 外挂扫描计时
                    from dualpath_profiler import profiler as _dp
                    _dp.start(f"plugins_{symbol}")

                    # v21.12 RES-007: 趋势阶段估计 + 市场制度 (Phase 1 记录)
                    _trend_info = self._get_trend_for_plugin(symbol)
                    _x4_dir = _trend_info.get("trend_x4", "SIDE") if _trend_info else "SIDE"
                    _tf_min = read_symbol_timeframe(main_symbol, default=240)
                    _phase_bars = YFinanceDataFetcher.get_ohlcv(symbol, _tf_min, 25)
                    _trend_phase = estimate_trend_phase(_phase_bars, _x4_dir)
                    self._current_trend_phase[symbol] = _trend_phase  # v21.12: 缓存供rhythm/ATR读取
                    if _trend_phase.get("phase") != "NEUTRAL":
                        print(f"[v21.12] {symbol} 趋势阶段: {_trend_phase['phase']} "
                              f"regime={_trend_phase['market_regime']} "
                              f"(进度{_trend_phase['progress']:.0%}, x4={_x4_dir}, "
                              f"momentum={_trend_phase['ema_momentum']:.4f})")

                    # GCC-0047: 取消单外挂互斥,所有外挂都可激活,靠FilterChain过滤
                    # v3.530: SuperTrend外挂 (4H)
                    self._scan_supertrend(symbol)

                    # v21: Vision形态外挂 — v21.15禁用(Brooks Vision已覆盖形态识别)
                    # self._scan_double_pattern(symbol)

                    # v3.545: Rob Hoffman外挂 (1H EMA排列+IRB回调入场, v2.0.1恢复)
                    self._scan_rob_hoffman(symbol)

                    # v3.671: N字结构外挂 — v0.3禁用(效果不行, Vision三方门控替代)
                    # self._scan_n_structure(symbol)

                    # v21.1: 缠论买卖点外挂 (4H, 一/二/三买卖点)
                    self._scan_chan_bs(symbol)

                    # Brooks PA已合并到 Brooks Vision (brooks_vision.py)

                    # v3.545: 飞云双突破外挂 - 暂时禁用 (BUY能力不足，信号严重偏空)
                    # if main_symbol not in self._signal_executed_this_cycle:
                    #     self._scan_feiyun(symbol)

                    # v21.16: MACD背离外挂已删除(扫描引擎), 仅保留L2小周期版本

                    # v3.550: SuperTrend+QQE MOD+A-V2外挂 - v15.2: 暂时屏蔽
                    # self._scan_supertrend_av2(symbol)

                    # GCC-0258 S11: 15min多周期外挂扫描 (在4H外挂之后, gcc_observe之前)
                    self._scan_plugins_15m(symbol, market_type="crypto")

                    # GCC-0141: 外挂扫描计时结束
                    _dp.stop(f"plugins_{symbol}")

                    # v0.2 顺大逆小: 外挂扫描完成后触发GCC-TM轮次决策
                    try:
                        from gcc_trading_module import gcc_observe as _gcc_observe_round
                        from gcc_trading_module import _GCC_TM_EXECUTE_SYMBOLS as _GCC_EXEC
                        _gcc_lookback = 180  # GCC-0261: 加密Wyckoff需1个月4H≈180根
                        _gcc_bars_raw = _phase_bars or YFinanceDataFetcher.get_ohlcv(symbol, _tf_min, _gcc_lookback)
                        _gcc_bars = _verify_and_get_4h(main_symbol, _gcc_bars_raw, _gcc_lookback)
                        if _gcc_bars and len(_gcc_bars) >= 5:
                            _gcc_observe_round(
                                main_symbol, _gcc_bars,
                                observe_only=main_symbol not in _GCC_EXEC,
                            )
                            logger.info(f"[GCC-TM][ROUND] {main_symbol} crypto round triggered")
                    except ImportError:
                        pass
                    except Exception as _gcc_round_err:
                        logger.debug(f"[GCC-TM][ROUND] {main_symbol} crypto error: {_gcc_round_err}")

                else:
                    logger.debug(f"[v21.7] {symbol} 外挂扫描跳过(TF={_sym_tf}min, 间隔{_scan_interval_tf}s未到)")

                # v3.660: B3独立通道已删除, BB均值回归改为外挂(S3)接入B1 GCC-TM

                # 获取当前价格 (用于P0-Open和P0-Tracking)
                # GCC-0141: 价格拉取计时
                from dualpath_profiler import profiler as _dp
                _dp.start(f"price_{symbol}")
                current_price = YFinanceDataFetcher.get_1m_close_price(symbol)
                if not current_price:
                    current_price = YFinanceDataFetcher.get_current_price(symbol)
                _dp.stop(f"price_{symbol}")
                if not current_price:
                    continue

                # v11.3: P0-Open (已暂停，不再运行)
                # self._scan_open_crypto(symbol, current_price)

                # P0-Tracking/移动止盈止损
                if P0_TRACKING_ENABLED and main_symbol not in self._signal_executed_this_cycle:
                    self._scan_tracking(symbol, current_price, is_crypto=True)
                elif TRAILING_STOP_ENABLED and main_symbol not in self._signal_executed_this_cycle:
                    _, trailing_threshold, timeframe, _, _ = self._get_symbol_config(symbol)
                    self._check_tracking_period_reset(symbol, timeframe)
                    position = self._get_position_from_main_state(symbol)
                    self._check_trailing_stop(symbol, current_price, True, position, trailing_threshold, timeframe)

                # v20.7: 暴跌允许同K线卖2次 — 第1次卖完后立即再扫一次
                if P0_TRACKING_ENABLED and main_symbol in self._crash_sell_this_cycle:
                    logger.info(f"[v20.7] {symbol} 暴跌连卖: 尝试第2次卖出")
                    self._scan_tracking(symbol, current_price, is_crypto=True)
                elif TRAILING_STOP_ENABLED and main_symbol in self._crash_sell_this_cycle:
                    logger.info(f"[v20.7] {symbol} 暴跌连卖(止损): 尝试第2次卖出")
                    _, trailing_threshold, timeframe, _, _ = self._get_symbol_config(symbol)
                    position = self._get_position_from_main_state(symbol)
                    self._check_trailing_stop(symbol, current_price, True, position, trailing_threshold, timeframe)

                # v20.4: 记录本周期执行情况
                if main_symbol in self._signal_executed_this_cycle:
                    logger.info(f"[v20.4] {symbol} 本周期已执行信号，其余外挂已跳过")

            except Exception as e:
                logger.error(f"扫描 {symbol} 异常: {e}")

    def _scan_stocks(self):
        """扫描美股 - v21: P0-Tracking + 4个外挂 (SuperTrend/Vision形态/缠论BS/MACD背离)"""
        if not is_us_market_open():
            logger.info("美股市场未开盘，跳过扫描")
            return

        stock_symbols = self.config["stock"]["symbols"]
        logger.info(f"[美股扫描] 共{len(stock_symbols)}只: {stock_symbols}")
        for idx, symbol in enumerate(stock_symbols):
            try:
                # v3.572: 品种间间隔，避免API请求集中
                if idx > 0:
                    time.sleep(0.3)

                # v21.7: 扫描频率优化 — 外挂扫描受TF间隔控制, 移动止盈止损始终扫描
                _sym_tf = read_symbol_timeframe(symbol, default=240)
                _scan_interval_tf = SCAN_INTERVAL_BY_TF.get(_sym_tf, 300)
                _last_scan = self._last_plugin_scan.get(symbol, 0)
                _should_scan_plugins = (time.time() - _last_scan) >= _scan_interval_tf

                if _should_scan_plugins:
                    self._last_plugin_scan[symbol] = time.time()

                    # GCC-0141: 外挂扫描计时
                    from dualpath_profiler import profiler as _dp
                    _dp.start(f"plugins_{symbol}")

                    # v21.12 RES-007: 趋势阶段估计 + 市场制度 (Phase 1 记录)
                    _trend_info_s = self._get_trend_for_plugin(symbol)
                    _x4_dir_s = _trend_info_s.get("trend_x4", "SIDE") if _trend_info_s else "SIDE"
                    _tf_min_s = read_symbol_timeframe(symbol, default=240)
                    _phase_bars_s = YFinanceDataFetcher.get_ohlcv(symbol, _tf_min_s, 25)
                    _trend_phase_s = estimate_trend_phase(_phase_bars_s, _x4_dir_s)
                    self._current_trend_phase[symbol] = _trend_phase_s  # v21.12: 缓存
                    if _trend_phase_s.get("phase") != "NEUTRAL":
                        print(f"[v21.12] {symbol} 趋势阶段: {_trend_phase_s['phase']} "
                              f"regime={_trend_phase_s['market_regime']} "
                              f"(进度{_trend_phase_s['progress']:.0%}, x4={_x4_dir_s}, "
                              f"momentum={_trend_phase_s['ema_momentum']:.4f})")

                    # GCC-0047: 取消单外挂互斥,所有外挂都可激活,靠FilterChain过滤
                    # v3.550: SuperTrend外挂 (4H)
                    self._scan_supertrend(symbol, market_type="stock")

                    # v21: Vision形态外挂 — v21.15禁用(Brooks Vision已覆盖形态识别)
                    # self._scan_double_pattern(symbol, market_type="stock")

                    # v3.545: Rob Hoffman外挂 (1H EMA排列+IRB回调入场, v2.0.1恢复)
                    self._scan_rob_hoffman(symbol, market_type="stock")

                    # v3.671: N字结构外挂 — v0.3禁用(效果不行, Vision三方门控替代)
                    # self._scan_n_structure(symbol, market_type="stock")

                    # v21.1: 缠论买卖点外挂 (4H, 二买/三买/二卖/三卖)
                    self._scan_chan_bs(symbol, market_type="stock")

                    # Brooks PA已合并到 Brooks Vision (brooks_vision.py)

                    # v3.550: 飞云双突破外挂 - 暂时禁用 (BUY能力不足，信号严重偏空)
                    # if symbol not in self._signal_executed_this_cycle:
                    #     self._scan_feiyun(symbol, market_type="stock")

                    # v21.16: MACD背离外挂已删除(扫描引擎), 仅保留L2小周期版本

                    # v3.550: SuperTrend+AV2外挂 (4小时周期) - v15.2: 暂时屏蔽
                    # self._scan_supertrend_av2(symbol, market_type="stock")

                    # GCC-0258 S11: 15min多周期外挂扫描 (在4H外挂之后, gcc_observe之前)
                    self._scan_plugins_15m(symbol, market_type="stock")

                    # GCC-0141: 外挂扫描计时结束
                    _dp.stop(f"plugins_{symbol}")

                    # v0.2 顺大逆小: 外挂扫描完成后触发GCC-TM轮次决策
                    try:
                        from gcc_trading_module import gcc_observe as _gcc_observe_round
                        from gcc_trading_module import _GCC_TM_EXECUTE_SYMBOLS as _GCC_EXEC
                        _gcc_lookback_s = 450  # GCC-0261: 美股Wyckoff需3个月4H≈450根
                        _gcc_bars_s_raw = _phase_bars_s or YFinanceDataFetcher.get_ohlcv(symbol, _tf_min_s, _gcc_lookback_s)
                        _gcc_bars_s = _verify_and_get_4h(symbol, _gcc_bars_s_raw, _gcc_lookback_s)
                        if _gcc_bars_s and len(_gcc_bars_s) >= 5:
                            _gcc_observe_round(
                                symbol, _gcc_bars_s,
                                observe_only=symbol not in _GCC_EXEC,
                            )
                            logger.info(f"[GCC-TM][ROUND] {symbol} stock round triggered")
                    except ImportError:
                        pass
                    except Exception as _gcc_round_err:
                        logger.debug(f"[GCC-TM][ROUND] {symbol} stock error: {_gcc_round_err}")
                else:
                    logger.debug(f"[v21.7] {symbol} 外挂扫描跳过(TF={_sym_tf}min, 间隔{_scan_interval_tf}s未到)")

                # 获取当前价格 (用于P0-Tracking) v21.7: 两层fallback
                # GCC-0141: 价格拉取计时
                from dualpath_profiler import profiler as _dp
                _dp.start(f"price_{symbol}")
                current_price = YFinanceDataFetcher.get_1m_close_price(symbol)
                if not current_price:
                    current_price = YFinanceDataFetcher.get_current_price(symbol)
                _dp.stop(f"price_{symbol}")
                if not current_price:
                    logger.warning(f"[v21.7] {symbol} 获取价格失败(1m+current), 跳过移动止损")
                    continue

                # P0-Tracking/移动止盈止损
                if P0_TRACKING_ENABLED and symbol not in self._signal_executed_this_cycle:
                    self._scan_tracking(symbol, current_price, is_crypto=False)
                elif TRAILING_STOP_ENABLED and symbol not in self._signal_executed_this_cycle:
                    _, trailing_threshold, timeframe, _, _ = self._get_symbol_config(symbol)
                    self._check_tracking_period_reset(symbol, timeframe)
                    position = self._get_position_from_main_state(symbol)
                    self._check_trailing_stop(symbol, current_price, False, position, trailing_threshold, timeframe)

                # v20.7: 暴跌允许同K线卖2次 — 第1次卖完后立即再扫一次
                if P0_TRACKING_ENABLED and symbol in self._crash_sell_this_cycle:
                    logger.info(f"[v20.7] {symbol} 暴跌连卖: 尝试第2次卖出")
                    self._scan_tracking(symbol, current_price, is_crypto=False)
                elif TRAILING_STOP_ENABLED and symbol in self._crash_sell_this_cycle:
                    logger.info(f"[v20.7] {symbol} 暴跌连卖(止损): 尝试第2次卖出")
                    _, trailing_threshold, timeframe, _, _ = self._get_symbol_config(symbol)
                    position = self._get_position_from_main_state(symbol)
                    self._check_trailing_stop(symbol, current_price, False, position, trailing_threshold, timeframe)

                # v20.4: 记录本周期执行情况
                if symbol in self._signal_executed_this_cycle:
                    logger.info(f"[v20.4] {symbol} 本周期已执行信号，其余外挂已跳过")

            except Exception as e:
                logger.error(f"扫描 {symbol} 异常: {e}")

    def scan_once(self):
        """执行一次扫描"""
        logger.info(f"[扫描] {datetime.now().strftime('%H:%M:%S')}")

        # GCC-0141: DualPath基准计时
        from dualpath_profiler import profiler as _dp
        _dp.start("scan_once_total")

        # v16.2: 开始新扫描周期，清空OHLCV缓存（避免同周期重复下载）
        YFinanceDataFetcher.begin_scan_cycle()

        # GCC-0143: DualPath Path B预加载调度
        try:
            from dualpath_loader import loader as _dl
            _dl.schedule_prefetch()
        except Exception:
            pass

        # v20.4: 每扫描周期每品种只执行1次买卖信号
        self._signal_executed_this_cycle = set()
        self._crash_sell_this_cycle = set()  # v20.7: 暴跌允许同K线卖2次
        # v21.2: P0发送失败冷却 (跨周期保持，只在此初始化dict结构)
        if not hasattr(self, '_p0_fail_cooldown'):
            self._p0_fail_cooldown = {}  # {symbol: datetime}
        # v21.18: 移动止盈/止损发送冷却 (30min, crash-sell豁免)
        if not hasattr(self, '_trailing_send_cooldown'):
            self._trailing_send_cooldown = {}  # {symbol_BUY/SELL: datetime}
        # v21.18: P0连续失败计数 (3次→冻结到次日8AM)
        if not hasattr(self, '_p0_fail_count'):
            self._p0_fail_count = {}  # {symbol: int}
        # v21.19: P0每日限次回流 (server返回"限次"时今日停发该方向)
        if not hasattr(self, '_p0_daily_banned'):
            self._p0_daily_banned = {}  # {symbol_BUY/SELL: date_str}

        # v21.3: 每日股票预选评分 (Module A)
        if _modules_available and self.stock_selector:
            today = get_today_date_ny()
            if self._selection_done_today != today:
                try:
                    self.stock_selector.run_daily()
                    self._selection_done_today = today
                    logger.info(f"[v21.3] 每日预选评分完成 ({today})")
                except Exception as e:
                    logger.warning(f"[v21.3] 预选评分异常: {e}")

        # v14.2: 检查7:55 AM强制清盘
        self._check_755am_force_liquidate()

        # KEY-006: Brooks Vision 实战执行 (v2.3: pattern_chart + P0信号发送)
        # 放在外挂扫描前, Brooks Vision先跑完, EXECUTE结果发送给主程序
        # v2.2: radar_tick()冷却期返回缓存结果,需去重防止重复P0发送
        try:
            # GCC-0141: Brooks Vision计时
            from dualpath_profiler import profiler as _dp
            _dp.start("brooks_vision")
            import brooks_vision as _bv_module
            from brooks_vision import radar_tick
            _pre_scan_ts = _bv_module._last_scan_ts
            _bv_results = radar_tick()
            _dp.stop("brooks_vision")
            # v2.2: 去重 — 只有本次是新鲜扫描才发送P0信号
            # fix: 读模块属性而非import值快照, radar_tick()更新后本地var不同步
            _bv_is_fresh = (_bv_module._last_scan_ts > _pre_scan_ts)
            for _bv_r in (_bv_results or []):
                _bv_final = _bv_r.get("final", "")
                if "EXECUTE" not in _bv_final:
                    continue
                if not _bv_is_fresh:
                    continue  # v2.2: 缓存结果不重复发P0
                _bv_sym = _bv_r.get("symbol", "")
                _bv_signal = _bv_r.get("radar", {}).get("signal", "")
                _bv_conf = _bv_r.get("radar", {}).get("confidence", 0)
                _bv_pattern = _bv_r.get("radar", {}).get("brooks_pattern", "NONE")
                _bv_price = _bv_r.get("price_at_signal", 0)
                if not _bv_sym or not _bv_signal or _bv_price <= 0:
                    continue
                # 品种名映射: BTC-USD → BTCUSDC, 美股保持原名
                _bv_main_sym = REVERSE_SYMBOL_MAP.get(_bv_sym, _bv_sym)
                _bv_is_crypto = _bv_sym in REVERSE_SYMBOL_MAP
                _bv_signal_data = {
                    "signal": _bv_signal,
                    "price": _bv_price,
                    "base_price": _bv_price,
                    "change_pct": 0,
                    "timeframe": "4h",
                    "timestamp": datetime.now().isoformat(),
                    "type": "crypto" if _bv_is_crypto else "stock",
                    "signal_type": "BrooksVision",
                    "source": "BrooksVision",
                    "reason": f"[{_bv_pattern}] conf={_bv_conf}",
                    "brooks_pattern": _bv_pattern,
                    "brooks_confidence": _bv_conf,
                    "activate_supertrend_plugin": True,  # 走外挂路径
                }
                logger.info(f"[BROOKS_VISION] P0发送: {_bv_main_sym} {_bv_signal} "
                            f"[{_bv_pattern}] conf={_bv_conf} price={_bv_price:.2f}")
                _bv_resp = self._notify_main_server(_bv_main_sym, _bv_signal_data)
                _bv_executed = _bv_resp.get('executed', False)
                logger.info(
                    f"[BROOKS_VISION] P0响应: {_bv_main_sym} executed={_bv_executed} "
                    f"reason={_bv_resp.get('reason', '')}"
                )
                try:
                    from brooks_vision import log_dispatch_result
                    log_dispatch_result(_bv_main_sym, _bv_resp, _bv_r.get("radar", {}))
                except Exception as _bv_log_err:
                    logger.debug(f"[BROOKS_VISION] dispatch log skipped: {_bv_log_err}")
                # v2.4: 只在实际成交后才消耗Brooks Vision每日配额 + v2.2: 成交后才发邮件
                if _bv_executed:
                    try:
                        from brooks_vision import _mark_executed, _send_radar_email
                        _mark_executed(_bv_sym, _bv_signal)
                        _send_radar_email(
                            _bv_sym, _bv_signal,
                            _bv_r.get("radar", {}),
                            _bv_r.get("filter", {}),
                            _bv_r.get("l2_signal", "N/A"),
                        )
                        logger.info(f"[BROOKS_VISION] 配额消耗+邮件: {_bv_sym} {_bv_signal}")
                    except Exception as _me_err:
                        logger.warning(f"[BROOKS_VISION] 配额/邮件失败: {_me_err}")
            # GCC-0144: Vision形态驱动预加载 — 收集有形态的品种
            _bv_active_syms = []
            for _bv_r2 in (_bv_results or []):
                _bv_pat = _bv_r2.get("radar", {}).get("brooks_pattern", "NONE")
                if _bv_pat not in ("NONE", "", None):
                    _bv_s = _bv_r2.get("symbol", "")
                    if _bv_s:
                        _bv_active_syms.append(_bv_s)
            if _bv_active_syms:
                try:
                    from dualpath_loader import loader as _dl
                    _dl.vision_prefetch(_bv_active_syms)
                except Exception:
                    pass
        except ImportError as _imp_err:
            if not getattr(self, '_radar_import_warned', False):
                logger.info(f"[BROOKS_VISION] brooks_vision未安装, 跳过: {_imp_err}")
                self._radar_import_warned = True
        except Exception as _radar_err:
            logger.warning(f"[BROOKS_VISION] 执行异常: {_radar_err}")

        self._scan_crypto()
        self._scan_stocks()

        self._save_state()
        self._save_tracking_state()
        self._save_scalping_state()  # v12.0: 保存剥头皮状态
        self._save_supertrend_state()  # v3.530: 保存SuperTrend状态
        # v16 P1-7: 补齐4个外挂save调用
        self._save_rob_hoffman_state()
        self._save_double_pattern_state()
        self._save_feiyun_state()
        self._save_supertrend_av2_state()
        self._save_signals()
        self._update_heartbeat()

        # v20.5: 首轮扫描完成后标记ATR已全部重算，后续走24h缓存
        if not self._atr_startup_recalculated:
            self._atr_startup_recalculated = True
            logger.info("[v20.5] ATR(14)首轮重算完成，后续使用24h缓存(纽约8AM刷新)")

        # GCC-0141: DualPath基准计时 — 本轮结束
        try:
            from dualpath_profiler import profiler as _dp
            _dp.stop("scan_once_total")
            # GCC-0142: 记录流量隔离统计(本轮增量)
            from dualpath_traffic import traffic_mgr as _tm
            _tm_stats = _tm.get_stats_delta()
            _dp.record("traffic_signal_count", _tm_stats["signal_count"])
            _dp.record("traffic_relay_blocked", _tm_stats["relay_blocked_count"])
            _dp.flush()
        except Exception:
            pass

    def run(self):
        """主循环"""
        self.running = True
        self._stop_event = threading.Event()  # v16.2: 可中断的sleep

        # v16 P2-8: 注册SIGTERM/SIGINT优雅退出
        # v16.2: 双Ctrl+C强制退出（解决Windows下yfinance阻塞无法退出）
        import signal as _signal
        import atexit as _atexit

        _first_sigint_time = [0]  # 用list包装以便在闭包中修改

        def _graceful_shutdown(signum, frame):
            import os as _os
            now = time.time()
            # v16.2: 2秒内连按两次Ctrl+C → 强制退出
            if now - _first_sigint_time[0] < 2.0:
                logger.warning("[v16.2] 双Ctrl+C，强制退出!")
                _os._exit(1)
            _first_sigint_time[0] = now
            logger.info(f"收到信号{signum}，优雅退出...（2秒内再按Ctrl+C强制退出）")
            self.running = False
            self._stop_event.set()  # v16.2: 唤醒sleep

        try:
            _signal.signal(_signal.SIGTERM, _graceful_shutdown)
        except (OSError, ValueError):
            pass  # Windows可能不支持SIGTERM
        _signal.signal(_signal.SIGINT, _graceful_shutdown)

        def _save_all_states():
            self._save_state()
            self._save_tracking_state()
            self._save_scalping_state()
            self._save_supertrend_state()
            self._save_rob_hoffman_state()
            self._save_double_pattern_state()
            self._save_feiyun_state()
            self._save_supertrend_av2_state()

        _atexit.register(_save_all_states)

        logger.info("=" * 60)
        logger.info("扫描引擎 v21 启动 (配合主程序 v3.640)")
        logger.info("-" * 60)
        logger.info("【v21 外挂清单】")
        logger.info("  ✅ SuperTrend:  4H | 1买+1卖/天")
        logger.info("  ✅ Vision形态:  4H | GPT-4o 8种形态识别")
        logger.info("  ✅ 缠论买卖点:  4H | 二买/三买/二卖/三卖")
        logger.info("  ✅ MACD背离:   15m | 仅震荡市激活")
        logger.info("  ✅ 移动止盈止损: 动态 | ATR(14)动态阈值")
        logger.info("  ❌ Rob Hoffman: 暂停观察")
        logger.info("  ❌ 剥头皮:      信号噪音大")
        logger.info("  ❌ 飞云双突破:   BUY能力不足")
        logger.info("  ❌ SuperTrend+AV2: 暂时屏蔽")
        logger.info("  ❌ P0-Open:     已暂停")
        logger.info("-" * 60)
        logger.info(f"启动冷却期: {self.STARTUP_COOLDOWN_SECONDS}秒")
        logger.info("=" * 60)

        try:
            while self.running:
                self.scan_once()
                # v16.2: 使用Event.wait替代time.sleep，可被Ctrl+C中断
                self._stop_event.wait(timeout=self.config["scan_interval"])
                if self._stop_event.is_set():
                    break

        except KeyboardInterrupt:
            logger.info("收到停止信号")
        finally:
            self.running = False
            # GCC-0143: 停止DualPath预加载
            try:
                from dualpath_loader import loader as _dl
                _dl.stop()
            except Exception:
                pass
            self._save_state()
            self._save_tracking_state()
            self._save_scalping_state()  # v12.0
            self._save_supertrend_state()  # v3.530
            # v16 P1-7: 补齐4个外挂save调用
            self._save_rob_hoffman_state()
            self._save_double_pattern_state()
            self._save_feiyun_state()
            self._save_supertrend_av2_state()
            self._save_signals()
            logger.info("扫描引擎停止")

    def stop(self):
        """停止引擎"""
        self.running = False


# ============================================================
# 主程序集成接口
# ============================================================

class ScanSignalReader:
    """供主程序使用的信号读取器"""

    def __init__(self, signal_file: str = "scan_signals.json",
                 heartbeat_file: str = "scan_heartbeat.json",
                 heartbeat_timeout: int = 120):
        self.signal_file = signal_file
        self.heartbeat_file = heartbeat_file
        self.heartbeat_timeout = heartbeat_timeout

    def is_engine_alive(self) -> bool:
        """检查扫描引擎是否存活"""
        heartbeat = safe_json_read(self.heartbeat_file)
        if not heartbeat:
            return False

        try:
            last_beat = datetime.fromisoformat(heartbeat["timestamp"])
            elapsed = (datetime.now() - last_beat).total_seconds()
            return elapsed < self.heartbeat_timeout
        except Exception:  # v16 P2-2
            return False

    def get_signal(self, symbol: str) -> Optional[Dict]:
        """获取指定品种的P0信号"""
        if not self.is_engine_alive():
            return None

        data = safe_json_read(self.signal_file)
        if not data:
            return None

        signals = data.get("signals", {})
        return signals.get(symbol)

    def get_all_signals(self) -> Dict[str, Dict]:
        """获取所有P0信号"""
        if not self.is_engine_alive():
            return {}

        data = safe_json_read(self.signal_file)
        if not data:
            return {}

        return data.get("signals", {})

    def get_tracking_state(self) -> Dict[str, Dict]:
        """获取追踪状态"""
        data = safe_json_read(self.signal_file)
        if not data:
            return {}

        return data.get("tracking_state", {})


# ============================================================
# 命令行入口
# ============================================================

def print_status():
    """打印当前状态"""
    reader = ScanSignalReader()

    print("\n" + "=" * 70)
    print("Price Scan Engine v11.3.1 状态 (P0-Tracking + P0-Open趋势对齐)")
    print("=" * 70)

    alive = reader.is_engine_alive()
    print(f"\n引擎状态: {'运行中' if alive else '未运行'}")
    print("L1外挂激活: UP+BUY→激活 | DOWN+SELL→激活 | 震荡→仅P0执行")
    print("美股开盘: 9:30-9:35检测新交易日 → 重置基准价 → 9:40后开始触发")

    ny_now = get_ny_now()
    print(f"纽约时间: {ny_now.strftime('%Y-%m-%d %H:%M:%S')}")

    # P0-Open信号
    signals = reader.get_all_signals()
    if signals:
        print(f"\n当前P0信号 ({len(signals)}个):")
        for symbol, sig in signals.items():
            sig_type = sig.get('signal_type', 'P0-Open')
            print(f"  [{symbol}] {sig['signal']} @ {sig['price']:.2f} ({sig['change_pct']:+.2f}%) [{sig_type}]")
    else:
        print("\n当前无P0信号")

    # P0-Tracking状态
    tracking = reader.get_tracking_state()
    if tracking:
        print(f"\nP0-Tracking追踪状态 ({len(tracking)}个):")
        for symbol, state in tracking.items():
            peak = state.get("peak_price")
            trough = state.get("trough_price")
            pos = state.get("last_position", 0)
            triggered = state.get("triggered_action")
            freeze_until = state.get("freeze_until")

            status_parts = []
            if pos > 0 and peak:
                status_parts.append(f"持仓={pos} | peak={peak:.2f}")
            elif pos == 0 and trough:
                status_parts.append(f"空仓 | trough={trough:.2f}")
            else:
                status_parts.append(f"持仓={pos}")

            if triggered:
                status_parts.append(f"本周期已触发{triggered}")

            if freeze_until and is_frozen_until(freeze_until):
                status_parts.append(f"[冻结]至{freeze_until[:16]}")

            # v11.2: 显示美股开盘日状态
            last_trading_date = state.get("last_trading_date", "")
            cooldown_until = state.get("market_open_cooldown_until", "")
            if last_trading_date:
                status_parts.append(f"交易日={last_trading_date}")
            if cooldown_until:
                status_parts.append(f"[开盘缓冲]至{cooldown_until[11:19]}")

            print(f"  [{symbol}] {' | '.join(status_parts)}")

    # P0-Open状态
    state = safe_json_read(CONFIG["state_file"])
    if state:
        symbols = state.get("symbols", {})
        print(f"\nP0-Open监控品种 ({len(symbols)}个):")
        for symbol, s in symbols.items():
            triggered = s.get("triggered_action")
            base = s.get("base_price", "-")

            status = f"已触发{triggered}" if triggered else "监控中"
            base_str = f"{base:.2f}" if isinstance(base, (int, float)) else str(base)

            print(f"  [{symbol}] {status} | 基准价(前周期开盘): {base_str}")

    print("\n" + "=" * 70)


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description="Price Scan Engine v14.0 (趋势同步+剥头皮+SuperTrend)")
    parser.add_argument("--status", action="store_true", help="查看当前状态")
    parser.add_argument("--once", action="store_true", help="只扫描一次")
    parser.add_argument("--interval", type=int, default=300, help="扫描间隔（秒）")
    parser.add_argument("--no-http", action="store_true", help="禁用趋势同步HTTP服务器")

    args = parser.parse_args()

    if args.status:
        print_status()
        return

    CONFIG["scan_interval"] = args.interval

    # v3.540: 启动趋势同步HTTP服务器 (后台线程)
    if not args.no_http:
        _start_trend_sync_server(port=6002)

    engine = PriceScanEngine(CONFIG)

    # v17.1: 保存实例供热重载API使用
    global _scan_engine_instance
    _scan_engine_instance = engine

    if args.once:
        engine.scan_once()
        print_status()
    else:
        engine.run()


if __name__ == "__main__":
    main()
