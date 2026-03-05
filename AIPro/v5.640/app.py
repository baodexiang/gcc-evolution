"""
AI PRO Trading System v5.498
============================
Cloud Validation Version - Synced from v3.498

Features:
- v3.498: HOLD门卫开放 + UNCLEAR位置策略
- v3.497: 美股成本价格高抛低吸
- v3.496: 美股盈亏动态策略调整 + Rob Hoffman外挂
- MACD背离外挂 (v3.495)
- L1/L2 analysis with Dow Theory (v3.280)
- DeepSeek AI arbitration (v3.330)
- Wyckoff analysis (v3.160)
- Multi-language support (EN/ZH)
- User registration/subscription system
- v3.435: trend_mid force rules (FORCE_DOWN/UP_MID + PRICE_OVERRIDE)

Flask main entry point
"""

import os
import sys
import logging
from datetime import datetime

# Azure compatibility
_app_dir = os.path.dirname(os.path.abspath(__file__))
if _app_dir not in sys.path:
    sys.path.insert(0, _app_dir)
os.chdir(_app_dir)

from flask import Flask

# Import configuration
import config

# Import modules
from data import StockDataProvider, CoinGeckoProvider
from core import SignalGenerator
from execution import DryRunner
from notification import EmailSender
from web import create_routes, UserSystem

# Configure logging
log_handlers = [logging.StreamHandler()]
try:
    os.makedirs(config.LOG_DIR, exist_ok=True)
    log_file = os.path.join(config.LOG_DIR, f"app_{datetime.now().strftime('%Y%m%d')}.log")
    log_handlers.append(logging.FileHandler(log_file, encoding='utf-8'))
except Exception as e:
    print(f"[WARN] Cannot create log file: {e}")

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=log_handlers
)
logger = logging.getLogger(__name__)


def create_app():
    """Create Flask application"""
    app = Flask(
        __name__,
        template_folder="web/templates",
        static_folder="web/static"
    )

    # Session secret
    app.secret_key = config.SESSION_SECRET

    # Initialize components
    logger.info(f"Initializing AI PRO Trading System v{config.VERSION}")
    logger.info(f"Mode: {'DRY_RUN' if config.DRY_RUN else 'LIVE'}")

    # Data providers
    # v5.496: StockDataProvider with TwelveData -> YFinance fallback
    stock_provider = StockDataProvider(
        twelvedata_api_key=config.TWELVEDATA_CONFIG["api_key"],
        cache_ttl=config.TWELVEDATA_CONFIG["cache_ttl"]
    )
    coingecko_provider = CoinGeckoProvider(cache_ttl=config.COINGECKO_CONFIG["cache_ttl"])
    logger.info("[v5.496] Data providers: StockDataProvider (TwelveData->YFinance fallback) + CoinGecko")

    # Signal generator (includes L1, L2, DeepSeek)
    signal_generator = SignalGenerator(config.ANALYSIS_CONFIG)
    logger.info("Signal generator initialized (L1 + L2 + DeepSeek)")

    # DRY_RUN executor
    dry_runner = DryRunner(config.LOG_DIR)
    logger.info("DRY_RUN executor initialized")

    # Email sender
    email_sender = EmailSender(
        smtp_server=config.EMAIL_SMTP_SERVER,
        smtp_port=config.EMAIL_SMTP_PORT,
        sender=config.EMAIL_SENDER,
        password=config.EMAIL_PASSWORD,
        recipient=config.EMAIL_RECIPIENT
    )
    if email_sender.enabled:
        logger.info("Email notifications enabled")
    else:
        logger.warning("Email notifications not configured")

    # User system
    user_system = UserSystem(
        db_path=config.USER_DB_PATH,
        max_users=config.USER_MAX_COUNT,
        session_lifetime_hours=config.SESSION_LIFETIME_HOURS
    )
    user_stats = user_system.get_user_count()
    logger.info(f"User system initialized: {user_stats['total']}/{user_stats['max_users']} users")

    # Register routes
    bp = create_routes(
        signal_generator,
        stock_provider,
        coingecko_provider,
        dry_runner,
        email_sender,
        user_system,
        config
    )
    app.register_blueprint(bp)
    logger.info("Web routes registered")

    # System info endpoint
    @app.route("/info")
    def info():
        return {
            "name": config.SYSTEM_NAME,
            "version": config.VERSION,
            "mode": "DRY_RUN" if config.DRY_RUN else "LIVE",
            "data_sources": config.DATA_SOURCES,
            "deepseek_enabled": config.DEEPSEEK_ENABLED,
            "email_enabled": email_sender.enabled,
            "users": user_system.get_user_count(),
            "started_at": app.config.get("started_at", "unknown")
        }

    app.config["started_at"] = datetime.now().isoformat()

    return app


# Create application instance
app = create_app()


if __name__ == "__main__":
    logger.info(f"Starting server http://{config.HOST}:{config.PORT}")
    logger.info("=" * 60)
    logger.info(f"  AI PRO Trading System v{config.VERSION}")
    logger.info(f"  Mode: DRY_RUN (Cloud Validation)")
    logger.info(f"  Data: Twelve Data (Stocks) + CoinGecko (Crypto)")
    logger.info(f"  DeepSeek: {'Enabled' if config.DEEPSEEK_ENABLED else 'Disabled'}")
    logger.info(f"  i18n: EN/ZH supported")
    logger.info("=" * 60)

    app.run(
        host=config.HOST,
        port=config.PORT,
        debug=config.DEBUG
    )
