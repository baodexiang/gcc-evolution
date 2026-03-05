# AI PRO Trading System v5.640 Deployment Guide

## New Features in v5.640

- **缠论K线合并+三段判定**: 提前捕捉趋势变化
  - `trend_8bar.py`: 缠论K线合并和三段判定模块
  - `merge()`: 处理包含关系，合并子周期K线
  - `judge()`: 三段判定 (底底高+顶顶高=上涨趋势)
  - `_find_sub_timeframe()`: 自动选择最优子周期数据源
  - 8根子K线(前两根当前周期) → 提前1-2根K线判断趋势

## Features from v5.540

- **趋势转折同步**: L1趋势变化自动同步到扫描引擎
- **智能选股**: 搜索过滤 + 板块分类 + 快捷预设

## Features from v5.496


- **MACD背离外挂**: 93%胜率半木夏策略，绕过L2 Gate限制
- **Multi-language**: EN/ZH switch in top-right corner
- **User System**: Registration, login, subscription
- **DeepSeek AI**: Trend arbitration when signals conflict

## 1. Local Testing

```bash
cd "AI Pro/v5.411"

# Install dependencies
pip install -r requirements.txt

# Create .env
cp .env.example .env
# Edit .env with your API keys

# Run locally
python app.py
```

Visit http://localhost:8000

## 2. Azure Deployment

### 2.1 Application Settings

| Name | Value |
|------|-------|
| `DEEPSEEK_API_KEY` | Your DeepSeek API key |
| `TWELVEDATA_API_KEY` | Your Twelve Data API key |
| `EMAIL_ENABLED` | true |
| `EMAIL_SMTP_SERVER` | smtp.gmail.com |
| `EMAIL_SMTP_PORT` | 587 |
| `EMAIL_SENDER` | your-email@gmail.com |
| `EMAIL_PASSWORD` | your-app-password |
| `SESSION_SECRET` | random-string-for-security |

### 2.2 Startup Command

```
gunicorn --bind=0.0.0.0:8000 --timeout 120 app:app
```

### 2.3 ZIP Deployment

```bash
cd "AI Pro/v5.411"
zip -r ../aipro-v5.420.zip . -x "*.pyc" -x "__pycache__/*" -x "logs/*" -x ".env" -x "users/*.json" -x "tmpclaude*"

az webapp deployment source config-zip \
    --resource-group YOUR_RESOURCE_GROUP \
    --name YOUR_APP_NAME \
    --src ../aipro-v5.420.zip
```

## 3. User Management

- Initial limit: 100 users
- Expandable to: 1000 users
- User data stored in: `users/users.json`

To expand user limit, change `USER_MAX_COUNT` in `config.py`.

## 4. API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Dashboard |
| `/signals` | GET | Signal history |
| `/login` | GET | Login page |
| `/register` | GET | Register page |
| `/subscribe` | GET | Subscription page |
| `/api/analyze` | POST | Run analysis |
| `/api/ohlcv` | GET | Get OHLCV chart data |
| `/api/login` | POST | User login |
| `/api/register` | POST | User register |
| `/api/subscribe` | POST | Subscribe notifications |
| `/api/lang/<lang>` | GET | Switch language (en/zh) |
| `/health` | GET | Health check |
| `/info` | GET | System info |

## 5. Version Mapping

| Main Program | Cloud Version | Features |
|--------------|---------------|----------|
| v3.640 | v5.640 | 缠论K线合并+三段判定 |
| v3.540 | v5.540 | 趋势同步+智能选股 |
| v3.496 | v5.496 | 美股盈亏动态策略调整 |
| v3.495 | v5.495 | MACD背离外挂 |
| v3.493 | v5.493 | L1趋势判断修复(道氏理论) |
| v3.420 | v5.420 | Reversal Pattern Detection |
| v3.411 | v5.411 | Full Position Block + L2-10m Shield |
| v3.410 | v5.410 | Volume-Price Theory |
| v3.xxx | v5.xxx | - |
