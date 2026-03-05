# Price Scan Engine v21 — 完整插件清单

**文档日期**: 2026-02-16  
**版本**: v21.16  
**范围**: 所有集成插件的配置、执行路径、状态管理、日限制、冻结逻辑

---

## 目录

1. [插件总览](#插件总览)
2. [P0-Tracking (追踪止损/止盈)](#p0-tracking)
3. [P0-Open (开盘价突破)](#p0-open)
4. [Chandelier+ZLSMA 剥头皮](#chandelier-zlsma-剥头皮)
5. [SuperTrend](#supertrend)
6. [SuperTrend+AV2](#supertrend-av2)
7. [Rob Hoffman](#rob-hoffman)
8. [双底双顶 (Vision Pattern)](#双底双顶-vision-pattern)
9. [缠论买卖点](#缠论买卖点)
10. [飞云双突破](#飞云双突破)
11. [MACD背离](#macd背离)
12. [全局门控与过滤](#全局门控与过滤)
13. [状态持久化](#状态持久化)

---

## 插件总览

| 插件名称 | 周期 | 加密 | 美股 | 启用 | 配额 | 冻结 | 观察模式 |
|---------|------|------|------|------|------|------|---------|
| P0-Tracking | 4h | ✓ | ✓ | ✓ | 1买+1卖 | 8AM NY | ✗ |
| P0-Open | 4h | ✗ | ✗ | ✗ | 1买+1卖 | 8AM NY | ✗ |
| Chandelier+ZLSMA | 5m | ✗ | ✗ | ✗ | 1买+1卖 | 8AM NY | ✓ |
| SuperTrend | 4h | ✓ | ✓ | ✓ | 1买+1卖 | 8AM NY | ✗ |
| SuperTrend+AV2 | 4h | ✓ | ✓ | ✓ | 1买+1卖 | 8AM NY | ✗ |
| Rob Hoffman | 4h | ✓ | ✓ | ✓ | 1买+1卖 | 8AM NY | ✗ |
| 双底双顶 | 4h | ✓ | ✓ | ✓ | 1买+1卖 | 8AM NY | ✓(美股) |
| 缠论买卖点 | 4h | ✓ | ✓ | ✓ | 1买+1卖 | 8AM NY | ✗ |
| 飞云双突破 | 4h | ✓ | ✓ | ✓ | 1买+1卖 | 8AM NY | ✗ |
| MACD背离 | 4h | ✗ | ✗ | ✗ | 1买+1卖 | 8AM NY | ✗ |

**说明**:
- **周期**: K线周期 (4h=4小时, 5m=5分钟)
- **加密/美股**: 是否支持该市场
- **启用**: 配置中是否默认启用
- **配额**: 每日买卖限制
- **冻结**: 配额用完后冻结到何时
- **观察模式**: 是否支持观察模式(记录日志不执行)

---

## P0-Tracking

### 配置位置
- **文件**: `price_scan_engine_v21.py`
- **配置**: `CONFIG["tracking"]` (行 839-845)
- **加密配置**: `CONFIG["crypto"]["p0_tracking_threshold"]` = 0.025 (2.5%)
- **美股配置**: `CONFIG["stock"]["p0_tracking_threshold"]` = 0.025 (2.5%)

### 启用/禁用逻辑
```python
# 行 6050: def _scan_tracking(self, symbol: str, current_price: float, is_crypto: bool)
# P0-Tracking 始终运行，无启用开关
# 只有 _check_trailing_stop() 后直接 return (v20.4禁用P0-Open)
```

### 执行路径

#### 1. 入口函数
- **函数**: `_scan_tracking()` (行 6050)
- **调用位置**: `_scan_crypto()` (行 9320) / `_scan_stocks()` (行 9407)
- **触发频率**: 每个扫描周期 (5分钟)

#### 2. 核心逻辑
```
_scan_tracking()
  ├─ 初始化状态 (tracking_state[symbol])
  ├─ 获取4小时K线 (get_4h_ohlcv, 30根)
  ├─ 获取趋势信息 (_get_trend_for_plugin)
  ├─ 检查周期重置 (_check_period_reset_tracking)
  ├─ 获取基准价格 (baseline_price)
  ├─ 检查P0-Tracking信号
  │  ├─ BUY: 从最低点(trough)上涨≥2.5%
  │  └─ SELL: 从最高点(peak)下跌≥2.5%
  ├─ 检查移动止损 (_check_trailing_stop)
  │  ├─ 第1次: min(ATR动态, 固定2.5%)
  │  └─ 第2次: max(ATR动态, 固定2.5%)
  ├─ 检查每日配额 (check_plugin_daily_limit)
  ├─ 检查顺大逆小 (check_x4_trend_filter)
  ├─ 检查P0保护 (check_p0_signal_protection)
  ├─ 检查仓位控制 (check_position_control)
  ├─ 通知主程序 (_notify_main_server)
  └─ 保存状态 (_save_tracking_state)
```

#### 3. 日限制检查
- **函数**: `check_plugin_daily_limit()` (行 1246)
- **规则**:
  - 每天 BUY 1次 + SELL 1次
  - 配额用完后冻结至次日纽约时间 8AM
  - 急跌保护: 当前K线跌≥5%时绕过SELL配额限制

#### 4. 冻结逻辑
- **冻结时间**: `get_next_8am_ny()` (行 1226)
- **冻结字段**: `tracking_state[symbol]["freeze_until"]`
- **重置日期**: `tracking_state[symbol]["reset_date"]`
- **优先级**: 冻结检查 > 日期重置 (行 1271-1299)

#### 5. 状态管理
- **状态文件**: `logs/scan_tracking_state.json`
- **加载**: `_load_tracking_state()` (行 4430)
- **保存**: `_save_tracking_state()` (行 4467)
- **字段**:
  ```json
  {
    "symbol": {
      "baseline_price": float,
      "peak_price": float,
      "trough_price": float,
      "buy_used": bool,
      "sell_used": bool,
      "freeze_until": "ISO8601",
      "reset_date": "YYYY-MM-DD",
      "trailing_stop_count": int,
      "trailing_buy_count": int,
      "trailing_reset_date": "YYYY-MM-DD",
      "p0_buy_protection_until": "ISO8601",
      "p0_sell_protection_until": "ISO8601"
    }
  }
  ```

#### 6. 关键检查点
| 检查项 | 函数 | 行号 | 说明 |
|-------|------|------|------|
| 周期重置 | `_check_period_reset_tracking()` | 6100 | 新周期重置基准价 |
| 日限制 | `check_plugin_daily_limit()` | 1246 | 每日1买+1卖 |
| 顺大逆小 | `check_x4_trend_filter()` | 1366 | x4定方向+N字豁免 |
| P0保护 | `check_p0_signal_protection()` | 1465 | P0信号后保护期 |
| 仓位控制 | `check_position_control()` | 2411 | 立体仓位门控 |
| L2确认 | `check_l2_recommendation()` | 1420 | L2空间位置确认 |
| 节奏过滤 | `check_rhythm_quality()` | 1573 | 唐纳奇通道位置 |

---

## P0-Open

### 配置位置
- **文件**: `price_scan_engine_v21.py`
- **配置**: `CONFIG["p0_open"]` (行 850-864)
- **启用状态**: `enabled_crypto=False`, `enabled_stock=False` (v12.1暂停)

### 启用/禁用逻辑
```python
# 行 7186: if not p0_config.get("enabled_crypto", False):
#         return  # 加密货币P0-Open禁用
# 行 7186: if not p0_config.get("enabled_stock", False):
#         return  # 美股P0-Open禁用
```

### 执行路径
- **函数**: `_scan_open_crypto()` (行 7167)
- **调用位置**: `_scan_crypto()` (行 9320)
- **触发频率**: 每个扫描周期 (5分钟)
- **状态**: 完全禁用 (v12.1)

---

## Chandelier+ZLSMA 剥头皮

### 配置位置
- **文件**: `price_scan_engine_v21.py`
- **配置**: `CONFIG["crypto"]["scalping"]` (行 732-743)
- **启用状态**: `enabled=False` (v20.4禁用)

### 启用/禁用逻辑
```python
# 行 7457: _scalp_observe = not scalping_config.get("enabled", False)
# enabled=False时:
#   - _scalp_observe=True (观察模式)
#   - 继续检测但不执行 (v21.15)
#   - 记录[OBSERVE][剥头皮]日志后return
```

### 执行路径

#### 1. 入口函数
- **函数**: `_scan_chandelier_zlsma()` (行 7443)
- **调用位置**: `_scan_crypto()` (行 9320)
- **触发频率**: 每个扫描周期 (5分钟)

#### 2. 核心逻辑
```
_scan_chandelier_zlsma()
  ├─ 检查启用状态 (enabled=False → 观察模式)
  ├─ 检查外挂可用性 (_chandelier_zlsma_available)
  ├─ 启动冷却期检查 (STARTUP_COOLDOWN_SECONDS)
  ├─ 检查全局冻结 (_check_scalping_global_frozen)
  ├─ 生成每日目标 (_generate_daily_scalping_target)
  ├─ 初始化状态 (scalping_state[symbol])
  ├─ 检查单品种冻结 (is_frozen_until)
  ├─ 获取趋势信息 (_get_current_trend_for_scalping)
  ├─ 每日计数重置 (_reset_scalping_daily_count_if_needed)
  ├─ 趋势过滤 (current_trend==SIDE → 禁用)
  ├─ 获取5分钟K线 (get_5m_ohlcv, 100根)
  ├─ 周期触发检查 (scalping_cycle_state)
  ├─ 调用外挂 (get_chandelier_zlsma_plugin)
  ├─ 检查每日限制 (_check_scalping_daily_limit)
  ├─ 检查顺大逆小 (check_x4_trend_filter)
  ├─ 检查P0保护 (check_p0_signal_protection)
  ├─ 检查仓位 (position_units)
  ├─ 检查仓位控制 (check_position_control)
  ├─ 观察模式检查 (v21.15)
  ├─ 通知主程序 (_notify_main_server)
  └─ 保存状态 (_save_scalping_state)
```

#### 3. 日限制检查
- **函数**: `_check_scalping_daily_limit()` (行 6800)
- **规则**:
  - 每天 BUY 1次 + SELL 1次 (v17.2)
  - 配额用完后冻结至次日纽约时间 8AM
  - 趋势过滤: UP只买, DOWN只卖, SIDE禁用

#### 4. 冻结逻辑
- **冻结时间**: `get_next_8am_ny()` (行 1226)
- **冻结字段**: `scalping_state[symbol]["freeze_until"]`
- **重置日期**: `scalping_state[symbol]["daily_reset_date"]`

#### 5. 周期触发控制
- **状态**: `scalping_cycle_state[symbol]`
- **字段**: `last_trigger_bar`, `triggered_direction`
- **规则**: 同一根5分钟K线只触发一次单向操作 (v13.0)

#### 6. 观察模式 (v21.15)
```python
# 行 7680-7685: 观察模式逻辑
if _scalp_observe:
    logger.info(f"[OBSERVE][剥头皮] {main_symbol} {result.action} ...")
    return  # 不发送信号
```

#### 7. 状态管理
- **状态文件**: `logs/scan_scalping_state.json`
- **加载**: `_load_scalping_state()` (行 4475)
- **保存**: `_save_scalping_state()` (行 4494)
- **字段**:
  ```json
  {
    "symbol": {
      "freeze_until": "ISO8601",
      "last_signal": "BUY|SELL",
      "last_trigger_time": "ISO8601",
      "last_trigger_price": float,
      "daily_buy_count": int,
      "daily_sell_count": int,
      "daily_reset_date": "YYYY-MM-DD",
      "total_cost": float,
      "total_revenue": float,
      "rounds_completed": int,
      "in_round": bool
    }
  }
  ```

---

## SuperTrend

### 配置位置
- **文件**: `price_scan_engine_v21.py`
- **配置**: 
  - 加密: `CONFIG["crypto"]["supertrend"]` (行 747-753)
  - 美股: `CONFIG["stock"]["supertrend"]` (行 799-805)
- **启用状态**: `enabled=True`

### 启用/禁用逻辑
```python
# 行 7801: if not supertrend_config.get("enabled", False):
#         return
```

### 执行路径

#### 1. 入口函数
- **函数**: `_scan_supertrend()` (行 7783)
- **调用位置**: `_scan_crypto()` (行 9320) / `_scan_stocks()` (行 9407)
- **触发频率**: 每个扫描周期 (5分钟)

#### 2. 核心逻辑
```
_scan_supertrend()
  ├─ 检查启用状态 (enabled=True)
  ├─ 检查外挂可用性 (_supertrend_available)
  ├─ 启动冷却期检查
  ├─ 初始化状态 (supertrend_state[symbol])
  ├─ 获取趋势信息 (_get_trend_for_plugin)
  ├─ 检查每日限制 (check_plugin_daily_limit)
  ├─ 获取4小时K线 (get_4h_ohlcv, 30根)
  ├─ 获取收盘价序列 (120根用于QQE/MACD)
  ├─ 获取L1三方信号 (_get_l1_signals_for_supertrend)
  ├─ 获取市场数据 (_get_market_data_for_supertrend)
  ├─ 调用外挂 (get_supertrend_plugin)
  ├─ 检查模式 (PLUGIN_AGREE/PLUGIN_CONFLICT)
  ├─ 缓存方向 + 共识度日志 (v21.8)
  ├─ 检查顺大逆小 (check_x4_trend_filter)
  ├─ 检查EMA5顺势 (check_ema5_momentum_filter)
  ├─ 检查L2确认 (check_l2_recommendation)
  ├─ 检查节奏质量 (check_rhythm_quality)
  ├─ 检查
