"""
Internationalization (i18n) Module
==================================
Supports English and Chinese language switching.
Default: English
"""

from typing import Dict

# English translations
EN = {
    # Navigation
    "nav_dashboard": "Dashboard",
    "nav_signals": "Signals",
    "nav_login": "Login",
    "nav_register": "Register",
    "nav_logout": "Logout",
    "nav_subscribe": "Subscribe",

    # Dashboard
    "dashboard_title": "Dashboard - AI PRO Trading",
    "signal_analysis": "Signal Analysis",
    "chart": "Chart",
    "chart_placeholder": "Select an asset to display chart",
    "asset_type": "Asset Type",
    "us_stocks": "US Stocks",
    "cryptocurrency": "Cryptocurrency",
    "symbol": "Symbol",
    "timeframe": "Timeframe",
    "run_analysis": "Run Analysis",
    "analyzing": "Analyzing...",
    "analysis_result": "Analysis Result",
    "select_asset": "Select an asset and click",
    "performance": "Performance",
    "recent_signals": "Recent Signals",
    "no_signals": "No signals yet",

    # Signal Display
    "confidence": "Confidence",
    "current_price": "Current Price",
    "analysis_reason": "Analysis Reason",

    # L1 Analysis
    "l1_trend": "L1 Trend",
    "decision": "Decision",  # v5.455
    "direction": "Direction",
    "strength": "Strength",
    "dow_theory": "Dow Theory",

    # L2 Analysis
    "l2_signal": "L2 Signal",
    "signal": "Signal",
    "score": "Score",
    "volume": "Volume",
    "reversal_pattern": "Reversal Pattern",

    # DeepSeek
    "deepseek_analysis": "DeepSeek AI Analysis",
    "ai_trend": "AI Trend",
    "ai_signal": "AI Signal",
    "ai_reason": "AI Reason",

    # Statistics
    "signals_count": "Signals",
    "buy_count": "Buy",
    "hold_count": "Hold",
    "sell_count": "Sell",
    "avg_confidence": "Avg Conf",
    "total_pnl": "Total P&L",

    # Signals Page
    "signals_title": "Signal History - AI PRO Trading",
    "signal_history": "Signal History",
    "time": "Time",
    "action": "Action",
    "price": "Price",
    "reason": "Reason",
    "filter_all": "All",
    "filter_buy": "Buy Only",
    "filter_sell": "Sell Only",

    # User System
    "login_title": "Login - AI PRO Trading",
    "register_title": "Register - AI PRO Trading",
    "email": "Email",
    "password": "Password",
    "confirm_password": "Confirm Password",
    "login_button": "Login",
    "register_button": "Register",
    "no_account": "Don't have an account?",
    "has_account": "Already have an account?",
    "login_success": "Login successful",
    "register_success": "Registration successful",
    "login_failed": "Invalid email or password",
    "register_failed": "Registration failed",
    "email_exists": "Email already registered",
    "password_mismatch": "Passwords do not match",
    "user_limit_reached": "User limit reached",

    # Subscription
    "subscribe_title": "Subscribe - AI PRO Trading",
    "subscribe_signals": "Subscribe to Signal Notifications",
    "subscribe_desc": "Receive real-time trading signals via email",
    "subscribe_button": "Subscribe",
    "unsubscribe_button": "Unsubscribe",
    "subscribed": "You are subscribed",
    "not_subscribed": "You are not subscribed",
    "max_stocks_alert": "Maximum {0} stocks allowed",
    "max_crypto_alert": "Maximum {0} cryptocurrencies allowed",
    "save_success": "Saved successfully!",
    "save_failed": "Save failed: ",
    "error_prefix": "Error: ",

    # Common
    "loading": "Loading...",
    "error": "Error",
    "success": "Success",
    "save": "Save",
    "cancel": "Cancel",
    "close": "Close",

    # Footer
    "footer_text": "AI PRO Trading System",
    "cloud_mode": "Cloud Validation Mode",
    "dry_run": "DRY RUN",

    # Admin
    "nav_admin": "Admin",
    "admin_title": "Admin Panel - AI PRO Trading",
    "admin_user_management": "User Management",
    "admin_total_users": "Total Users",
    "admin_subscribed": "Subscribed",
    "admin_not_subscribed": "Not Subscribed",
    "admin_available": "Available",
    "admin_max_users": "Max Users",
    "admin_email": "Email",
    "admin_created": "Created",
    "admin_last_login": "Last Login",
    "admin_status": "Status",
    "admin_actions": "Actions",
    "admin_toggle": "Toggle",
    "admin_delete": "Delete",
    "admin_confirm_toggle": "Toggle subscription for",
    "admin_confirm_delete": "Delete user",

    # =========================================================================
    # Analysis Result Translations (v5.455)
    # =========================================================================

    # K-line Shapes
    "shape_HAMMER": "Hammer",
    "shape_SHOOTING_STAR": "Shooting Star",
    "shape_STRONG_BULL": "Strong Bull",
    "shape_STRONG_BEAR": "Strong Bear",
    "shape_BULL": "Bull",
    "shape_BEAR": "Bear",
    "shape_DOJI": "Doji",
    "shape_UNKNOWN": "Unknown",

    # Form-Spirit States
    "fs_FORM_SPIRIT_BALANCED": "Form-Spirit Balanced",
    "fs_FORM_SCATTERED_SPIRIT_FOCUSED": "Form Scattered, Spirit Focused",
    "fs_FORM_FOCUSED_SPIRIT_SCATTERED": "Form Focused, Spirit Scattered",
    "fs_FORM_SPIRIT_SCATTERED": "Form-Spirit Scattered",

    # Form-Spirit Warnings
    "fs_warn_top": "Potential top pattern, avoid trading",
    "fs_warn_distribution": "Potential distribution pattern, high risk",
    "fs_warn_no_control": "No institutional control, stay out",

    # MACD Divergence
    "macd_no_div_ranging": "No divergence in ranging market",
    "macd_insufficient_data": "Insufficient data for MACD calculation",
    "macd_bearish_div": "Bearish divergence: Potential trend reversal down",
    "macd_bullish_div": "Bullish divergence: Potential trend reversal up",

    # L1 Recovery
    "l1_rebound": "Rebound",
    "l1_consecutive_rise": "consecutive rising bars",

    # Signal Reasons
    "reason_uptrend_pullback_buy": "Uptrend pullback buy",
    "reason_uptrend_rsi_oversold": "Uptrend RSI oversold",
    "reason_uptrend_extreme_overbought": "Uptrend extreme overbought",
    "reason_uptrend_waiting": "Uptrend waiting",
    "reason_downtrend_bounce_sell": "Downtrend bounce sell",
    "reason_downtrend_rsi_overbought": "Downtrend RSI overbought",
    "reason_downtrend_extreme_oversold": "Downtrend extreme oversold",
    "reason_downtrend_waiting": "Downtrend waiting",
    "reason_sideways_l2": "Sideways with L2",
    "reason_sideways_watching": "Sideways watching",
    "reason_ranging_low_buy": "Ranging low buy",
    "reason_ranging_high_sell": "Ranging high sell",
    "reason_ranging_wait": "Ranging wait for extremes",
    "reason_strong_stock_protected": "Strong stock protected (small pullback)",
    "reason_force_down_active": "FORCE_DOWN active",
    "reason_force_down_warning": "FORCE_DOWN warning",

    # Paper Trading (v5.485)
    "paper_trading": "Paper Trading",
    "paper_not_initialized": "Paper Trading not initialized",
    "setup_paper": "Setup Paper Trading",
    "paper_settings": "Paper Trading Settings",
    "total_assets": "TOTAL",
    "pnl": "P&L",
    "return_rate": "RETURN",
    "positions": "Positions",
    "trade_history": "Trades",
    "no_positions": "No positions",
    "no_trades": "No trades",
    "qty": "Qty",
    "cost": "Cost",
    "capital": "Capital",
    "stock_capital": "Stock Capital",
    "crypto_capital": "Crypto Capital",
    "select_stocks": "Select Stocks",
    "select_crypto": "Select Crypto",
    "fee_rate": "Fee Rate",
    "stock_fee": "Stock Fee",
    "crypto_fee": "Crypto Fee",
    "timeframe": "Trading Timeframe",
    "stock_timeframe": "Stock Timeframe",
    "crypto_timeframe": "Crypto Timeframe",
    "auto_trade": "Auto-follow system signals",
    "reset": "Reset",

    # What's New (v5.540)
    "whats_new_title": "What's New in v5.540",
    "whats_new_feature1_title": "Smart Stock Selection",
    "whats_new_feature1_desc": "Search stocks by name/symbol, filter by sector (Tech, AI, Chips, EV, Finance, Mining, China ADRs). Much easier to find and select stocks for paper trading.",
    "whats_new_feature2_title": "Trend Auto-Sync",
    "whats_new_feature2_desc": "L1 trend changes now automatically sync to scan engine plugins. Plugins respond to trend/ranging market conditions in real-time.",
    "whats_new_sectors_title": "Available Sectors",
    "whats_new_got_it": "Got it!",
}

# Chinese translations
ZH = {
    # Navigation
    "nav_dashboard": "控制台",
    "nav_signals": "信号记录",
    "nav_login": "登录",
    "nav_register": "注册",
    "nav_logout": "退出",
    "nav_subscribe": "订阅",

    # Dashboard
    "dashboard_title": "控制台 - AI PRO 交易系统",
    "signal_analysis": "信号分析",
    "chart": "K线图",
    "chart_placeholder": "选择标的后显示K线图",
    "asset_type": "资产类型",
    "us_stocks": "美股",
    "cryptocurrency": "加密货币",
    "symbol": "标的",
    "timeframe": "时间周期",
    "run_analysis": "执行分析",
    "analyzing": "分析中...",
    "analysis_result": "分析结果",
    "select_asset": "选择标的并点击",
    "performance": "绩效",
    "recent_signals": "最近信号",
    "no_signals": "暂无信号",

    # Signal Display
    "confidence": "置信度",
    "current_price": "当前价格",
    "analysis_reason": "分析理由",

    # L1 Analysis
    "l1_trend": "L1 趋势",
    "decision": "决定",  # v5.455
    "direction": "方向",
    "strength": "强度",
    "dow_theory": "道氏理论",

    # L2 Analysis
    "l2_signal": "L2 信号",
    "signal": "信号",
    "score": "评分",
    "volume": "成交量",
    "reversal_pattern": "形态外挂",

    # DeepSeek
    "deepseek_analysis": "DeepSeek AI 分析",
    "ai_trend": "AI趋势",
    "ai_signal": "AI信号",
    "ai_reason": "AI理由",

    # Statistics
    "signals_count": "信号数",
    "buy_count": "买入",
    "hold_count": "持有",
    "sell_count": "卖出",
    "avg_confidence": "平均确信",
    "total_pnl": "总盈亏",

    # Signals Page
    "signals_title": "信号历史 - AI PRO 交易系统",
    "signal_history": "信号历史",
    "time": "时间",
    "action": "动作",
    "price": "价格",
    "reason": "理由",
    "filter_all": "全部",
    "filter_buy": "仅买入",
    "filter_sell": "仅卖出",

    # User System
    "login_title": "登录 - AI PRO 交易系统",
    "register_title": "注册 - AI PRO 交易系统",
    "email": "邮箱",
    "password": "密码",
    "confirm_password": "确认密码",
    "login_button": "登录",
    "register_button": "注册",
    "no_account": "没有账号?",
    "has_account": "已有账号?",
    "login_success": "登录成功",
    "register_success": "注册成功",
    "login_failed": "邮箱或密码错误",
    "register_failed": "注册失败",
    "email_exists": "邮箱已注册",
    "password_mismatch": "两次密码不一致",
    "user_limit_reached": "用户数量已达上限",

    # Subscription
    "subscribe_title": "订阅 - AI PRO 交易系统",
    "subscribe_signals": "订阅信号通知",
    "subscribe_desc": "通过邮件接收实时交易信号",
    "subscribe_button": "订阅",
    "unsubscribe_button": "取消订阅",
    "subscribed": "已订阅",
    "not_subscribed": "未订阅",
    "max_stocks_alert": "最多选择 {0} 个股票",
    "max_crypto_alert": "最多选择 {0} 个加密货币",
    "save_success": "保存成功！",
    "save_failed": "保存失败: ",
    "error_prefix": "错误: ",

    # Common
    "loading": "加载中...",
    "error": "错误",
    "success": "成功",
    "save": "保存",
    "cancel": "取消",
    "close": "关闭",

    # Footer
    "footer_text": "AI PRO 交易系统",
    "cloud_mode": "云端验证模式",
    "dry_run": "模拟运行",

    # Admin
    "nav_admin": "管理",
    "admin_title": "管理面板 - AI PRO 交易系统",
    "admin_user_management": "用户管理",
    "admin_total_users": "总用户数",
    "admin_subscribed": "已订阅",
    "admin_not_subscribed": "未订阅",
    "admin_available": "剩余名额",
    "admin_max_users": "最大用户数",
    "admin_email": "邮箱",
    "admin_created": "注册时间",
    "admin_last_login": "最后登录",
    "admin_status": "状态",
    "admin_actions": "操作",
    "admin_toggle": "切换",
    "admin_delete": "删除",
    "admin_confirm_toggle": "切换订阅状态",
    "admin_confirm_delete": "删除用户",

    # =========================================================================
    # Analysis Result Translations (v5.455)
    # =========================================================================

    # K-line Shapes
    "shape_HAMMER": "锤子线",
    "shape_SHOOTING_STAR": "射击之星",
    "shape_STRONG_BULL": "大阳线",
    "shape_STRONG_BEAR": "大阴线",
    "shape_BULL": "阳线",
    "shape_BEAR": "阴线",
    "shape_DOJI": "十字星",
    "shape_UNKNOWN": "未知",

    # Form-Spirit States
    "fs_FORM_SPIRIT_BALANCED": "形神兼备",
    "fs_FORM_SCATTERED_SPIRIT_FOCUSED": "形散神聚",
    "fs_FORM_FOCUSED_SPIRIT_SCATTERED": "形不散神散",
    "fs_FORM_SPIRIT_SCATTERED": "形神皆散",

    # Form-Spirit Warnings
    "fs_warn_top": "阶段顶部特征，回避交易",
    "fs_warn_distribution": "诱多出货特征，高风险",
    "fs_warn_no_control": "无主力控盘，观望",

    # MACD Divergence
    "macd_no_div_ranging": "盘整中无背驰",
    "macd_insufficient_data": "MACD计算数据不足",
    "macd_bearish_div": "顶背驰: 趋势可能反转下跌",
    "macd_bullish_div": "底背驰: 趋势可能反转上涨",

    # L1 Recovery
    "l1_rebound": "反弹",
    "l1_consecutive_rise": "连续上涨",

    # Signal Reasons
    "reason_uptrend_pullback_buy": "上涨趋势回调买入",
    "reason_uptrend_rsi_oversold": "上涨趋势RSI超卖",
    "reason_uptrend_extreme_overbought": "上涨趋势极度超买",
    "reason_uptrend_waiting": "上涨趋势等待",
    "reason_downtrend_bounce_sell": "下跌趋势反弹卖出",
    "reason_downtrend_rsi_overbought": "下跌趋势RSI超买",
    "reason_downtrend_extreme_oversold": "下跌趋势极度超卖",
    "reason_downtrend_waiting": "下跌趋势等待",
    "reason_sideways_l2": "横盘配合L2",
    "reason_sideways_watching": "横盘观望",
    "reason_ranging_low_buy": "震荡低位买入",
    "reason_ranging_high_sell": "震荡高位卖出",
    "reason_ranging_wait": "震荡等待极值",
    "reason_strong_stock_protected": "强势股保护(小幅回调)",
    "reason_force_down_active": "强制下跌生效",
    "reason_force_down_warning": "强制下跌警告",

    # =========================================================================
    # Paper Trading (v5.485)
    # =========================================================================
    "paper_trading": "模拟盘",
    "paper_not_initialized": "模拟盘未初始化",
    "setup_paper": "设置模拟盘",
    "paper_settings": "模拟盘设置",
    "total_assets": "总资产",
    "pnl": "盈亏",
    "return_rate": "收益率",
    "positions": "持仓",
    "trade_history": "交易记录",
    "no_positions": "暂无持仓",
    "no_trades": "暂无交易记录",
    "symbol": "品种",
    "quantity": "数量",
    "avg_cost": "成本价",
    "current_price": "现价",
    "unrealized_pnl": "浮动盈亏",
    "time": "时间",
    "action": "操作",
    "price": "价格",
    "fee": "手续费",
    "realized_pnl": "实现盈亏",
    "source": "来源",
    "select_stocks": "选择美股 (最多5只)",
    "select_crypto": "选择加密货币 (最多2个)",
    "fee_rate": "手续费率",
    "stock_fee": "美股手续费",
    "crypto_fee": "加密货币手续费",
    "timeframe": "交易周期",
    "stock_timeframe": "美股周期",
    "crypto_timeframe": "加密货币周期",
    "auto_trade": "自动跟随信号",
    "save_settings": "保存设置",
    "reset_account": "重置账户",
    "export_trades": "导出记录",
    "confirm_reset": "确认重置模拟盘？所有持仓和交易记录将被清除。",
    "paper_buy": "买入",
    "paper_sell": "卖出",
    "stock_capital": "美股资金",
    "crypto_capital": "加密货币资金",
    "cash_available": "可用现金",

    # What's New (v5.540)
    "whats_new_title": "v5.540 新功能",
    "whats_new_feature1_title": "🔍 智能选股",
    "whats_new_feature1_desc": "支持按名称/代码搜索股票，按板块筛选（科技、AI、芯片、电动车、金融、矿业、中概股）。模拟盘选股更方便快捷。",
    "whats_new_feature2_title": "📡 趋势自动同步",
    "whats_new_feature2_desc": "L1趋势变化现在自动同步到扫描引擎外挂。外挂实时响应趋势/震荡市场状态变化。",
    "whats_new_sectors_title": "支持的板块",
    "whats_new_got_it": "知道了！",
}

# All translations
TRANSLATIONS = {
    "en": EN,
    "zh": ZH,
}


def get_translation(lang: str = "en") -> Dict[str, str]:
    """Get translation dictionary for specified language"""
    return TRANSLATIONS.get(lang, EN)


def t(key: str, lang: str = "en") -> str:
    """Translate a single key"""
    translations = get_translation(lang)
    return translations.get(key, key)


class I18n:
    """i18n helper class"""

    def __init__(self, lang: str = "en"):
        self.lang = lang if lang in TRANSLATIONS else "en"
        self.translations = get_translation(self.lang)

    def get(self, key: str, default: str = None) -> str:
        """Get translation for key"""
        return self.translations.get(key, default or key)

    def set_language(self, lang: str):
        """Change language"""
        if lang in TRANSLATIONS:
            self.lang = lang
            self.translations = get_translation(lang)

    def all(self) -> Dict[str, str]:
        """Get all translations"""
        return self.translations


def translate_analysis_result(result: Dict, lang: str = "en") -> Dict:
    """
    Translate analysis result fields based on language setting.

    v5.455: Supports EN/ZH switching for:
    - K-line shapes
    - Form-spirit states and warnings
    - MACD divergence warnings
    - Signal reasons
    """
    if not result or lang == "en":
        return result  # English is the default, no translation needed

    translations = get_translation(lang)
    translated = dict(result)

    # Translate L2 fields
    if "l2" in translated and translated["l2"]:
        l2 = dict(translated["l2"])

        # Translate candle shape
        if "candle_shape" in l2:
            shape_key = f"shape_{l2['candle_shape']}"
            l2["candle_shape"] = translations.get(shape_key, l2["candle_shape"])

        # Translate form-spirit state
        if "form_spirit" in l2 and l2["form_spirit"]:
            fs = dict(l2["form_spirit"])
            if "state" in fs:
                state_key = f"fs_{fs['state']}"
                fs["state"] = translations.get(state_key, fs["state"])
            if "warning" in fs and fs["warning"]:
                # Map English warnings to keys
                warning_map = {
                    "Potential top pattern, avoid trading": "fs_warn_top",
                    "Potential distribution pattern, high risk": "fs_warn_distribution",
                    "No institutional control, stay out": "fs_warn_no_control",
                }
                warn_key = warning_map.get(fs["warning"])
                if warn_key:
                    fs["warning"] = translations.get(warn_key, fs["warning"])
            l2["form_spirit"] = fs

        # Translate MACD divergence warning
        if "macd_divergence" in l2 and l2["macd_divergence"]:
            macd = dict(l2["macd_divergence"])
            if "warning" in macd and macd["warning"]:
                warning = macd["warning"]
                if "No divergence in ranging market" in warning:
                    macd["warning"] = translations.get("macd_no_div_ranging", warning)
                elif "Insufficient data" in warning:
                    macd["warning"] = translations.get("macd_insufficient_data", warning)
                elif "Bearish divergence" in warning:
                    # Extract strength percentage if present
                    import re
                    match = re.search(r'\(strength (\d+)%\)', warning)
                    base = translations.get("macd_bearish_div", "Bearish divergence")
                    if match:
                        macd["warning"] = f"{base} (强度{match.group(1)}%)" if lang == "zh" else warning
                    else:
                        macd["warning"] = base
                elif "Bullish divergence" in warning:
                    import re
                    match = re.search(r'\(strength (\d+)%\)', warning)
                    base = translations.get("macd_bullish_div", "Bullish divergence")
                    if match:
                        macd["warning"] = f"{base} (强度{match.group(1)}%)" if lang == "zh" else warning
                    else:
                        macd["warning"] = base
            l2["macd_divergence"] = macd

        translated["l2"] = l2

    # Translate L1 fields
    if "l1" in translated and translated["l1"]:
        l1 = dict(translated["l1"])

        # Translate MACD divergence in L1
        if "macd_divergence" in l1 and l1["macd_divergence"]:
            macd = dict(l1["macd_divergence"])
            if "warning" in macd and macd["warning"]:
                warning = macd["warning"]
                if "No divergence in ranging market" in warning:
                    macd["warning"] = translations.get("macd_no_div_ranging", warning)
                elif "Insufficient data" in warning:
                    macd["warning"] = translations.get("macd_insufficient_data", warning)
                elif "Bearish divergence" in warning:
                    import re
                    match = re.search(r'\(strength (\d+)%\)', warning)
                    base = translations.get("macd_bearish_div", "Bearish divergence")
                    if match:
                        macd["warning"] = f"{base} (强度{match.group(1)}%)" if lang == "zh" else warning
                    else:
                        macd["warning"] = base
                elif "Bullish divergence" in warning:
                    import re
                    match = re.search(r'\(strength (\d+)%\)', warning)
                    base = translations.get("macd_bullish_div", "Bullish divergence")
                    if match:
                        macd["warning"] = f"{base} (强度{match.group(1)}%)" if lang == "zh" else warning
                    else:
                        macd["warning"] = base
            l1["macd_divergence"] = macd

        translated["l1"] = l1

    # Translate main reason field
    if "reason" in translated and translated["reason"]:
        reason = translated["reason"]

        # Map English reasons to translation keys
        reason_map = {
            "Uptrend pullback buy": "reason_uptrend_pullback_buy",
            "Uptrend RSI oversold": "reason_uptrend_rsi_oversold",
            "Uptrend extreme overbought": "reason_uptrend_extreme_overbought",
            "Uptrend waiting": "reason_uptrend_waiting",
            "Downtrend bounce sell": "reason_downtrend_bounce_sell",
            "Downtrend RSI overbought": "reason_downtrend_rsi_overbought",
            "Downtrend extreme oversold": "reason_downtrend_extreme_oversold",
            "Downtrend waiting": "reason_downtrend_waiting",
            "Sideways watching": "reason_sideways_watching",
            "Ranging low buy": "reason_ranging_low_buy",
            "Ranging high sell": "reason_ranging_high_sell",
            "Ranging wait for extremes": "reason_ranging_wait",
            "Strong stock protected (small pullback)": "reason_strong_stock_protected",
        }

        # Check for exact match first
        if reason in reason_map:
            translated["reason"] = translations.get(reason_map[reason], reason)
        else:
            # Handle composite reasons with suffixes like [FORCE_DOWN active]
            base_reason = reason
            suffix = ""

            if "[FORCE_DOWN active]" in reason:
                base_reason = reason.replace(" [FORCE_DOWN active]", "")
                suffix = f" [{translations.get('reason_force_down_active', 'FORCE_DOWN active')}]"
            elif "[FORCE_DOWN warning]" in reason:
                base_reason = reason.replace(" [FORCE_DOWN warning]", "")
                suffix = f" [{translations.get('reason_force_down_warning', 'FORCE_DOWN warning')}]"

            # Handle "Sideways with L2 XXX" pattern
            if base_reason.startswith("Sideways with L2"):
                signal = base_reason.replace("Sideways with L2 ", "")
                base_translated = translations.get("reason_sideways_l2", "Sideways with L2")
                translated["reason"] = f"{base_translated} {signal}{suffix}"
            elif base_reason in reason_map:
                translated["reason"] = translations.get(reason_map[base_reason], base_reason) + suffix
            else:
                translated["reason"] = reason  # Keep original if no match

    return translated
