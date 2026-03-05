"""
Flask Routes v5.540
===================
Web API routes with i18n and user system support.

v5.540 Update:
- AutoTrader后台自动交易引擎
- 按配置周期自动运行分析并执行模拟交易
- BUY/SELL信号自动执行，HOLD信号跳过
- 美股按市场交易时间运行，加密货币24/7

v5.498 Update:
- Synced from v3.498 (HOLD门卫开放 + UNCLEAR位置策略)
- HOLD时门卫开放，让L1外挂自己判断趋势
- UNCLEAR阶段纯位置策略 (pos<20%→+2, pos>80%→-2)

v5.497 Update:
- 美股成本价格高抛低吸策略
- get_avg_cost_price计算平均成本
- get_cost_reduction_score_adj成本拉低评分

v5.493 Update:
- 模拟盘支持用户自选周期 (stock_timeframe / crypto_timeframe)
- 默认周期: 美股=4h, 加密货币=2h
- 用户可在模拟盘设置中修改周期
- 分析API优先使用用户配置的周期

v5.485 Update:
- Paper Trading 模拟盘功能
- 自动跟随系统信号买卖
- 交易历史记录（时间精确到秒）

v5.480 Update:
- 非交易时间处理: 使用缓存数据分析，显示市场状态
- 添加 market_status 字段到分析结果

v5.430 Update:
- All pages and APIs require login (except login/register)
- Reversal pattern info in analysis response
- Synced from v3.430
"""

import logging
from flask import Blueprint, render_template, request, jsonify, make_response, redirect, url_for
from datetime import datetime
from functools import wraps

from .i18n import I18n, get_translation, translate_analysis_result
from .user_system import UserSystem

logger = logging.getLogger(__name__)

# Global references (injected by app.py)
signal_generator = None
stock_provider = None
coingecko_provider = None
dry_runner = None
email_sender = None
user_system = None
config = None

# v5.485: Paper Trading
paper_account = None
paper_executor = None

# v5.540: Auto Trader
auto_trader = None


def get_lang():
    """Get current language from cookie or default"""
    return request.cookies.get("lang", "en")


def get_user():
    """Get current user from session"""
    token = request.cookies.get("session_token")
    if token and user_system:
        return user_system.validate_session(token)
    return None


def login_required(f):
    """Decorator for routes requiring login"""
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_user()
        if not user:
            if request.is_json:
                return jsonify({"success": False, "error": "Login required"}), 401
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """Decorator for routes requiring admin"""
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_user()
        if not user:
            if request.is_json:
                return jsonify({"success": False, "error": "Login required"}), 401
            return redirect("/login")
        if not user.get("is_admin", False):
            if request.is_json:
                return jsonify({"success": False, "error": "Admin required"}), 403
            return redirect("/")
        return f(*args, **kwargs)
    return decorated


def create_routes(
    app_signal_generator,
    app_stock_provider,
    app_coingecko_provider,
    app_dry_runner,
    app_email_sender,
    app_user_system,
    app_config
):
    """Create Flask routes"""
    global signal_generator, stock_provider, coingecko_provider
    global dry_runner, email_sender, user_system, config
    global paper_account, paper_executor, auto_trader

    signal_generator = app_signal_generator
    stock_provider = app_stock_provider
    coingecko_provider = app_coingecko_provider
    dry_runner = app_dry_runner
    email_sender = app_email_sender
    user_system = app_user_system
    config = app_config

    # v5.485: Initialize Paper Trading
    try:
        import os
        import sys
        # Add parent directory to path for paper_trading module
        parent_dir = os.path.dirname(os.path.dirname(__file__))
        if parent_dir not in sys.path:
            sys.path.insert(0, parent_dir)
        from paper_trading import PaperAccount, PaperTradeExecutor, AutoTrader
        data_dir = os.path.join(parent_dir, "data")
        paper_account = PaperAccount(data_dir)
        paper_executor = PaperTradeExecutor(paper_account)

        # v5.540: Initialize AutoTrader
        auto_trader = AutoTrader(
            paper_account=paper_account,
            signal_generator=signal_generator,
            stock_provider=stock_provider,
            crypto_provider=coingecko_provider,
            execute_trade_func=lambda s, a, p, src: paper_executor.execute_signal(s, a, p, src)
        )

        # v5.540: Auto-start if paper account is initialized and auto_trade enabled
        if paper_account.config.get("initialized") and paper_account.config.get("auto_trade", True):
            auto_trader.start()
            logger.info("AutoTrader started (paper account already initialized)")

        logger.info("Paper Trading module initialized with AutoTrader")
    except Exception as e:
        logger.error(f"Failed to initialize Paper Trading: {e}")
        import traceback
        logger.error(traceback.format_exc())
        paper_account = None
        paper_executor = None

    bp = Blueprint("main", __name__)

    # =========================================================================
    # Language Switch
    # =========================================================================

    @bp.route("/api/lang/<lang>")
    def set_language(lang):
        """Switch language"""
        if lang not in ["en", "zh"]:
            lang = "en"
        response = make_response(jsonify({"success": True, "lang": lang}))
        response.set_cookie("lang", lang, max_age=365*24*60*60)

        # Update user preference
        user = get_user()
        if user and user_system:
            user_system.set_language(user["email"], lang)

        return response

    # =========================================================================
    # Pages
    # =========================================================================

    @bp.route("/")
    @login_required
    def index():
        """Dashboard page - Login required"""
        lang = get_lang()
        i18n = I18n(lang)
        user = get_user()

        return render_template(
            "dashboard.html",
            stocks=config.AVAILABLE_STOCKS,
            crypto=config.AVAILABLE_CRYPTO,
            timeframes=config.SUPPORTED_TIMEFRAMES,
            version=config.VERSION,
            lang=lang,
            t=i18n.all(),
            user=user
        )

    @bp.route("/signals")
    @login_required
    def signals_page():
        """Signal history page - Login required"""
        lang = get_lang()
        i18n = I18n(lang)
        user = get_user()

        return render_template(
            "signals.html",
            version=config.VERSION,
            lang=lang,
            t=i18n.all(),
            user=user
        )

    @bp.route("/login")
    def login_page():
        """Login page"""
        lang = get_lang()
        i18n = I18n(lang)

        return render_template(
            "login.html",
            version=config.VERSION,
            lang=lang,
            t=i18n.all()
        )

    @bp.route("/register")
    def register_page():
        """Register page"""
        lang = get_lang()
        i18n = I18n(lang)

        return render_template(
            "register.html",
            version=config.VERSION,
            lang=lang,
            t=i18n.all()
        )

    @bp.route("/subscribe")
    @login_required
    def subscribe_page():
        """Subscription page"""
        lang = get_lang()
        i18n = I18n(lang)
        user = get_user()
        watchlist = user_system.get_watchlist(user["email"])

        return render_template(
            "subscribe.html",
            version=config.VERSION,
            lang=lang,
            t=i18n.all(),
            user=user,
            watchlist=watchlist,
            available_stocks=config.AVAILABLE_STOCKS,
            available_crypto=config.AVAILABLE_CRYPTO,
            timeframes=config.SUPPORTED_TIMEFRAMES
        )

    @bp.route("/admin")
    @admin_required
    def admin_page():
        """Admin panel page"""
        lang = get_lang()
        i18n = I18n(lang)
        user = get_user()
        users_list = user_system.get_all_users()
        user_stats = user_system.get_user_count()

        return render_template(
            "admin.html",
            version=config.VERSION,
            lang=lang,
            t=i18n.all(),
            user=user,
            users_list=users_list,
            user_stats=user_stats
        )

    # =========================================================================
    # Admin API
    # =========================================================================

    @bp.route("/api/admin/users")
    @admin_required
    def api_admin_users():
        """Get all users (admin only)"""
        users_list = user_system.get_all_users()
        user_stats = user_system.get_user_count()
        return jsonify({
            "success": True,
            "users": users_list,
            "stats": user_stats
        })

    @bp.route("/api/admin/delete", methods=["POST"])
    @admin_required
    def api_admin_delete():
        """Delete user (admin only)"""
        user = get_user()
        data = request.get_json()
        target_email = data.get("email", "")
        result = user_system.delete_user(user["email"], target_email)
        return jsonify(result)

    @bp.route("/api/admin/toggle", methods=["POST"])
    @admin_required
    def api_admin_toggle():
        """Toggle subscription (admin only)"""
        user = get_user()
        data = request.get_json()
        target_email = data.get("email", "")
        result = user_system.toggle_subscription(user["email"], target_email)
        return jsonify(result)

    # =========================================================================
    # User API
    # =========================================================================

    @bp.route("/api/register", methods=["POST"])
    def api_register():
        """Register new user"""
        data = request.get_json()
        email = data.get("email", "")
        password = data.get("password", "")
        confirm = data.get("confirm_password", "")

        if password != confirm:
            return jsonify({"success": False, "message": "password_mismatch"}), 400

        result = user_system.register(email, password)
        status = 200 if result["success"] else 400
        return jsonify(result), status

    @bp.route("/api/login", methods=["POST"])
    def api_login():
        """Login user"""
        data = request.get_json()
        email = data.get("email", "")
        password = data.get("password", "")

        result = user_system.login(email, password)

        if result["success"]:
            response = make_response(jsonify(result))
            response.set_cookie(
                "session_token",
                result["session_token"],
                max_age=24*60*60,
                httponly=True
            )
            return response

        return jsonify(result), 401

    @bp.route("/api/logout", methods=["POST"])
    def api_logout():
        """Logout user"""
        token = request.cookies.get("session_token")
        if token:
            user_system.logout(token)

        response = make_response(jsonify({"success": True}))
        response.delete_cookie("session_token")
        return response

    @bp.route("/api/subscribe", methods=["POST"])
    @login_required
    def api_subscribe():
        """Subscribe to notifications"""
        user = get_user()
        result = user_system.subscribe(user["email"])
        return jsonify(result)

    @bp.route("/api/unsubscribe", methods=["POST"])
    @login_required
    def api_unsubscribe():
        """Unsubscribe from notifications"""
        user = get_user()
        result = user_system.unsubscribe(user["email"])
        return jsonify(result)

    @bp.route("/api/user")
    def api_user():
        """Get current user info"""
        user = get_user()
        if user:
            return jsonify({"success": True, "user": user})
        return jsonify({"success": False, "user": None})

    @bp.route("/api/watchlist", methods=["GET"])
    @login_required
    def api_get_watchlist():
        """Get user watchlist"""
        user = get_user()
        watchlist = user_system.get_watchlist(user["email"])
        return jsonify({
            "success": True,
            "watchlist": watchlist,
            "available_stocks": config.AVAILABLE_STOCKS,
            "available_crypto": config.AVAILABLE_CRYPTO,
            "timeframes": list(config.SUPPORTED_TIMEFRAMES.keys())
        })

    @bp.route("/api/watchlist", methods=["POST"])
    @login_required
    def api_update_watchlist():
        """Update user watchlist"""
        user = get_user()
        data = request.get_json()

        stocks = data.get("stocks", [])
        crypto = data.get("crypto", [])
        timeframe = data.get("timeframe", "30m")

        result = user_system.update_watchlist(user["email"], stocks, crypto, timeframe)
        return jsonify(result)

    # =========================================================================
    # Analysis API
    # =========================================================================

    @bp.route("/api/analyze", methods=["POST"])
    @login_required
    def analyze():
        """Execute analysis - Login required"""
        try:
            data = request.get_json()
            symbol = data.get("symbol", "TSLA")
            asset_type = data.get("type", "stock")

            # v5.493: 优先使用用户配置的模拟盘周期
            timeframe = data.get("timeframe")
            if not timeframe:
                # 优先使用模拟盘用户配置的周期
                if paper_account and paper_account.config.get("initialized"):
                    timeframe = paper_account.get_timeframe(symbol)
                else:
                    # 回退到品种独立周期配置
                    from config import get_symbol_timeframe, SUPPORTED_TIMEFRAMES
                    symbol_minutes = get_symbol_timeframe(symbol)
                    timeframe_map = {v["minutes"]: k for k, v in SUPPORTED_TIMEFRAMES.items()}
                    timeframe = timeframe_map.get(symbol_minutes, "30m")

            logger.info(f"Analysis request: {symbol} ({asset_type}) @ {timeframe}")

            # Select provider
            provider = coingecko_provider if asset_type == "crypto" else stock_provider

            # v5.480: Check market status for stocks
            market_open = True
            market_status = "open"
            if asset_type == "stock" and hasattr(provider, 'is_market_open'):
                market_open = provider.is_market_open(symbol)
                market_status = "open" if market_open else "closed"
                if not market_open:
                    logger.info(f"[v5.480] Market closed for {symbol}, will use cached data")

            # Get OHLCV data
            bars = provider.get_ohlcv(symbol, timeframe, limit=100)

            if not bars:
                # v5.480: More helpful error message based on market status
                if asset_type == "crypto":
                    error_msg = f"Cannot get data for {symbol}. CoinGecko API may be rate limited (try again in 1 minute) or symbol not found."
                elif not market_open:
                    error_msg = f"Market is closed for {symbol}. No cached data available. Please try again during market hours (9:30 AM - 4:00 PM ET)."
                else:
                    error_msg = f"Cannot get data for {symbol}. Market may be closed or symbol not found."
                logger.warning(f"Empty bars for {symbol} ({asset_type}), market_open={market_open}")
                return jsonify({
                    "success": False,
                    "error": error_msg,
                    "market_status": market_status
                }), 400

            # Generate signal for current bar
            result = signal_generator.generate(bars, symbol, timeframe)

            # v5.496: Generate signals for last 10 bars (changed from 5)
            recent_5_signals = []
            for i in range(10):
                bar_index = len(bars) - 1 - i
                if bar_index >= 20:  # Need enough history for analysis (lowered for crypto)
                    bars_subset = bars[:bar_index + 1]
                    bar_result = signal_generator.generate(bars_subset, symbol, timeframe)
                    bar_data = bars[bar_index]

                    # Get bar timestamp
                    ts = bar_data.get("timestamp") or bar_data.get("datetime")
                    if hasattr(ts, "isoformat"):
                        ts_str = ts.isoformat()
                    else:
                        ts_str = str(ts)

                    recent_5_signals.append({
                        "bar_index": i,  # 0=current, 1=previous, etc.
                        "timestamp": ts_str,
                        "open": float(bar_data["open"]),
                        "high": float(bar_data["high"]),
                        "low": float(bar_data["low"]),
                        "close": float(bar_data["close"]),
                        "action": bar_result["action"],
                        "confidence": bar_result["confidence"],
                        "reason": bar_result.get("reason", "")[:50]  # Truncate reason
                    })

            # Record to DRY_RUN (only current bar)
            dry_runner.execute_signal(
                symbol=symbol,
                action=result["action"],
                price=result["current_price"],
                confidence=result["confidence"],
                reason=result["reason"],
                analysis=result,
                timeframe=timeframe
            )

            # v5.485: Execute paper trade if enabled
            paper_result = execute_paper_trade(
                symbol=symbol,
                action=result["action"],
                price=result["current_price"],
                source=f"L2-{timeframe}"
            )
            if paper_result:
                logger.info(f"Paper trade executed: {paper_result['action']} {symbol}")

            # Send notification to subscribed users (non-HOLD only)
            if result["action"] != "HOLD" and email_sender and user_system:
                subscribed = user_system.get_subscribed_users()
                for email in subscribed:
                    try:
                        email_sender.send_signal_notification(result, recipient=email)
                    except Exception as e:
                        logger.error(f"Failed to notify {email}: {e}")

            # v5.455: Translate result based on user language setting
            lang = get_lang()
            translated_result = translate_analysis_result(result, lang)

            # v5.455: Translate recent_5_signals reasons
            if lang != "en":
                for sig in recent_5_signals:
                    if sig.get("reason"):
                        translated_sig = translate_analysis_result({"reason": sig["reason"]}, lang)
                        sig["reason"] = translated_sig.get("reason", sig["reason"])[:50]

            # v5.480: Determine if using cached data
            using_cached = not market_open and asset_type == "stock"

            return jsonify({
                "success": True,
                "result": {
                    "symbol": translated_result["symbol"],
                    "timeframe": translated_result["timeframe"],
                    "timestamp": translated_result["timestamp"].isoformat(),
                    "action": translated_result["action"],
                    "confidence": translated_result["confidence"],
                    "current_price": translated_result["current_price"],
                    "reason": translated_result["reason"],
                    "source": translated_result.get("source", ""),
                    "l1": translated_result["l1"],
                    "l2": translated_result["l2"],
                    "deepseek": translated_result.get("deepseek", {}),
                    "recent_5_signals": recent_5_signals,  # v5.435: Last 5 bars signals
                    # v5.480: Market status info
                    "market_status": market_status,
                    "using_cached_data": using_cached,
                    "data_note": "Using last trading session data (market closed)" if using_cached else ""
                }
            })

        except Exception as e:
            logger.error(f"Analysis error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/price/<symbol>")
    @login_required
    def get_price(symbol):
        """Get current price - Login required"""
        try:
            asset_type = request.args.get("type", "stock")
            provider = coingecko_provider if asset_type == "crypto" else stock_provider
            price = provider.get_current_price(symbol)

            if price is None:
                return jsonify({"error": "Cannot get price"}), 400

            return jsonify({
                "symbol": symbol,
                "price": price,
                "timestamp": datetime.now().isoformat()
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/ohlcv")
    @login_required
    def get_ohlcv():
        """Get OHLCV data for chart - Login required"""
        try:
            symbol = request.args.get("symbol", "TSLA")
            timeframe = request.args.get("timeframe", "30m")
            asset_type = request.args.get("type", "stock")
            limit = int(request.args.get("limit", 100))

            provider = coingecko_provider if asset_type == "crypto" else stock_provider
            bars = provider.get_ohlcv(symbol, timeframe, limit=limit)

            if not bars:
                return jsonify({
                    "success": False,
                    "error": f"Cannot get OHLCV data for {symbol}"
                }), 400

            # Convert to chart format (Unix timestamp in seconds)
            ohlcv_data = []
            for bar in bars:
                ts = bar.get("timestamp") or bar.get("datetime")
                if isinstance(ts, str):
                    from datetime import datetime as dt
                    ts = dt.fromisoformat(ts.replace("Z", "+00:00"))
                if hasattr(ts, "timestamp"):
                    unix_ts = int(ts.timestamp())
                else:
                    unix_ts = int(ts)

                ohlcv_data.append({
                    "time": unix_ts,
                    "open": float(bar["open"]),
                    "high": float(bar["high"]),
                    "low": float(bar["low"]),
                    "close": float(bar["close"]),
                    "volume": float(bar.get("volume", 0))
                })

            return jsonify({
                "success": True,
                "symbol": symbol,
                "timeframe": timeframe,
                "ohlcv": ohlcv_data
            })
        except Exception as e:
            logger.error(f"OHLCV error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/history")
    @login_required
    def get_history():
        """Get signal history - Login required"""
        try:
            symbol = request.args.get("symbol")
            action = request.args.get("action")
            timeframe = request.args.get("timeframe")
            limit = int(request.args.get("limit", 50))

            history = dry_runner.get_history(symbol, action, timeframe, limit)

            return jsonify({
                "success": True,
                "history": history,
                "count": len(history)
            })
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/statistics")
    @login_required
    def get_statistics():
        """Get statistics - Login required"""
        try:
            stats = dry_runner.get_statistics()
            return jsonify({"success": True, "statistics": stats})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/positions")
    @login_required
    def get_positions():
        """Get open positions - Login required"""
        try:
            positions = dry_runner.get_open_positions()
            return jsonify({"success": True, "positions": positions})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/health")
    def health_check():
        """Health check"""
        return jsonify({
            "status": "healthy",
            "version": config.VERSION,
            "mode": "DRY_RUN",
            "timestamp": datetime.now().isoformat(),
            "deepseek_enabled": config.DEEPSEEK_ENABLED
        })

    @bp.route("/info")
    def info():
        """System info"""
        user_stats = user_system.get_user_count() if user_system else {}
        return jsonify({
            "name": config.SYSTEM_NAME,
            "version": config.VERSION,
            "mode": "DRY_RUN",
            "data_sources": config.DATA_SOURCES,
            "deepseek_enabled": config.DEEPSEEK_ENABLED,
            "users": user_stats
        })

    # =========================================================================
    # Paper Trading API (v5.485)
    # =========================================================================

    @bp.route("/api/paper/summary")
    @login_required
    def paper_summary():
        """Get paper trading account summary"""
        if not paper_account:
            return jsonify({"success": False, "error": "Paper trading not initialized"}), 500
        try:
            summary = paper_account.get_summary()
            return jsonify({"success": True, "summary": summary})
        except Exception as e:
            logger.error(f"Paper summary error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/paper/positions")
    @login_required
    def paper_positions():
        """Get paper trading positions"""
        if not paper_account:
            return jsonify({"success": False, "error": "Paper trading not initialized"}), 500
        try:
            positions = paper_account.get_positions_list()
            return jsonify({"success": True, "positions": positions})
        except Exception as e:
            logger.error(f"Paper positions error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/paper/trades")
    @login_required
    def paper_trades():
        """Get paper trading history"""
        if not paper_account:
            return jsonify({"success": False, "error": "Paper trading not initialized"}), 500
        try:
            limit = int(request.args.get("limit", 20))
            offset = int(request.args.get("offset", 0))
            result = paper_account.get_trades_list(limit=limit, offset=offset)
            return jsonify({"success": True, **result})
        except Exception as e:
            logger.error(f"Paper trades error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/paper/config")
    @login_required
    def paper_config():
        """Get paper trading configuration"""
        if not paper_account:
            return jsonify({"success": False, "error": "Paper trading not initialized"}), 500
        try:
            return jsonify({
                "success": True,
                "config": paper_account.config,
                "available_stocks": config.AVAILABLE_STOCKS,
                "available_crypto": [c["symbol"] for c in config.AVAILABLE_CRYPTO],
                "auto_trader_status": auto_trader.get_status() if auto_trader else None
            })
        except Exception as e:
            logger.error(f"Paper config error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/paper/initialize", methods=["POST"])
    @login_required
    def paper_initialize():
        """Initialize paper trading account"""
        if not paper_account:
            return jsonify({"success": False, "error": "Paper trading not initialized"}), 500
        try:
            data = request.get_json()
            stock_symbols = data.get("stock_symbols", [])
            crypto_symbols = data.get("crypto_symbols", [])
            stock_capital = data.get("stock_capital", 200000)
            crypto_capital = data.get("crypto_capital", 50000)

            paper_account.initialize(
                stock_symbols=stock_symbols,
                crypto_symbols=crypto_symbols,
                stock_capital=stock_capital,
                crypto_capital=crypto_capital
            )

            # v5.540: Start AutoTrader if auto_trade enabled
            if auto_trader and paper_account.config.get("auto_trade", True):
                if not auto_trader.running:
                    auto_trader.start()
                    logger.info("AutoTrader started after paper account initialization")

            return jsonify({
                "success": True,
                "message": "Paper trading account initialized",
                "summary": paper_account.get_summary(),
                "auto_trader_running": auto_trader.running if auto_trader else False
            })
        except ValueError as e:
            return jsonify({"success": False, "error": str(e)}), 400
        except Exception as e:
            logger.error(f"Paper initialize error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/paper/settings", methods=["POST"])
    @login_required
    def paper_settings():
        """Update paper trading settings"""
        if not paper_account:
            return jsonify({"success": False, "error": "Paper trading not initialized"}), 500
        try:
            data = request.get_json()
            paper_account.update_settings(
                stock_symbols=data.get("stock_symbols"),
                crypto_symbols=data.get("crypto_symbols"),
                stock_capital=data.get("stock_capital"),
                crypto_capital=data.get("crypto_capital"),
                stock_fee_rate=data.get("stock_fee_rate"),
                crypto_fee_rate=data.get("crypto_fee_rate"),
                stock_timeframe=data.get("stock_timeframe"),      # v5.493
                crypto_timeframe=data.get("crypto_timeframe"),    # v5.493
                auto_trade=data.get("auto_trade")
            )

            # v5.540: Control AutoTrader based on auto_trade setting
            if auto_trader:
                auto_trade_enabled = paper_account.config.get("auto_trade", True)
                if auto_trade_enabled and not auto_trader.running:
                    auto_trader.start()
                    logger.info("AutoTrader started (auto_trade enabled)")
                elif not auto_trade_enabled and auto_trader.running:
                    auto_trader.stop()
                    logger.info("AutoTrader stopped (auto_trade disabled)")

            return jsonify({
                "success": True,
                "message": "Settings updated",
                "config": paper_account.config,
                "auto_trader_running": auto_trader.running if auto_trader else False
            })
        except ValueError as e:
            return jsonify({"success": False, "error": str(e)}), 400
        except Exception as e:
            logger.error(f"Paper settings error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/paper/reset", methods=["POST"])
    @login_required
    def paper_reset():
        """Reset paper trading account"""
        if not paper_account:
            return jsonify({"success": False, "error": "Paper trading not initialized"}), 500
        try:
            paper_account.reset_account()
            return jsonify({
                "success": True,
                "message": "Paper trading account reset",
                "summary": paper_account.get_summary()
            })
        except Exception as e:
            logger.error(f"Paper reset error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/paper/export")
    @login_required
    def paper_export():
        """Export paper trading history as CSV"""
        if not paper_account:
            return jsonify({"success": False, "error": "Paper trading not initialized"}), 500
        try:
            csv_content = paper_account.export_trades_csv()
            response = make_response(csv_content)
            response.headers["Content-Type"] = "text/csv"
            response.headers["Content-Disposition"] = f"attachment; filename=paper_trades_{datetime.now().strftime('%Y%m%d')}.csv"
            return response
        except Exception as e:
            logger.error(f"Paper export error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # =========================================================================
    # v5.540: AutoTrader Control
    # =========================================================================

    @bp.route("/api/paper/auto-trader/status")
    @login_required
    def auto_trader_status():
        """Get AutoTrader status"""
        if not auto_trader:
            return jsonify({"success": False, "error": "AutoTrader not initialized"}), 500
        try:
            return jsonify({
                "success": True,
                "status": auto_trader.get_status()
            })
        except Exception as e:
            logger.error(f"AutoTrader status error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/paper/auto-trader/start", methods=["POST"])
    @login_required
    def auto_trader_start():
        """Start AutoTrader"""
        if not auto_trader:
            return jsonify({"success": False, "error": "AutoTrader not initialized"}), 500
        if not paper_account or not paper_account.config.get("initialized"):
            return jsonify({"success": False, "error": "Paper trading not initialized"}), 400
        try:
            if not auto_trader.running:
                auto_trader.start()
                logger.info("AutoTrader started via API")
            return jsonify({
                "success": True,
                "message": "AutoTrader started",
                "status": auto_trader.get_status()
            })
        except Exception as e:
            logger.error(f"AutoTrader start error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/paper/auto-trader/stop", methods=["POST"])
    @login_required
    def auto_trader_stop():
        """Stop AutoTrader"""
        if not auto_trader:
            return jsonify({"success": False, "error": "AutoTrader not initialized"}), 500
        try:
            if auto_trader.running:
                auto_trader.stop()
                logger.info("AutoTrader stopped via API")
            return jsonify({
                "success": True,
                "message": "AutoTrader stopped",
                "status": auto_trader.get_status()
            })
        except Exception as e:
            logger.error(f"AutoTrader stop error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    return bp


def execute_paper_trade(symbol: str, action: str, price: float, source: str):
    """
    Execute paper trade (called from signal generator)

    Args:
        symbol: Symbol code (TSLA, BTC-USD, etc.)
        action: Signal action (BUY, SELL, HOLD)
        price: Current price
        source: Trigger source (L2门卫, P0-Tracking, etc.)
    """
    if paper_executor:
        try:
            result = paper_executor.execute_signal(symbol, action, price, source)
            if result:
                logger.info(f"Paper trade executed: {result}")
            return result
        except Exception as e:
            logger.error(f"Paper trade execution error: {e}")
    return None
