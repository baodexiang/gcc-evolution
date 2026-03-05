# AI PRO TRADING SYSTEM v3.572 - 可移植部署包

## 快速开始

### Windows 部署

```batch
# 1. 复制整个 safety 文件夹到目标电脑
# 2. 运行安装脚本
setup.bat

# 3. 编辑 .env 文件，填入你的API密钥
notepad .env

# 4. 启动系统
start.bat
```

### Linux/Mac 部署

```bash
# 1. 复制整个 safety 文件夹到目标电脑
# 2. 运行安装脚本
chmod +x setup.sh
./setup.sh

# 3. 编辑 .env 文件
nano .env

# 4. 启动系统
./start.sh
```

---

## 文件结构

```
safety/
├── README.md                 # 本文档
├── setup.bat                 # Windows安装脚本
├── setup.sh                  # Linux/Mac安装脚本
├── start.bat                 # Windows启动脚本
├── start.sh                  # Linux/Mac启动脚本
├── requirements.txt          # Python依赖
├── .env.example              # 环境变量模板
│
├── llm_server_v3570.py       # 主程序
├── price_scan_engine_v16.py  # 扫描引擎
├── monitor_v3570.py          # 监控程序(可选)
│
├── models/                   # 模型文件目录
│   └── *.py
│
└── logs/                     # 日志目录(自动创建)
```

---

## 环境变量配置

编辑 `.env` 文件，填入以下必需配置：

| 变量名 | 说明 | 必需 |
|--------|------|------|
| `OPENAI_API_KEY` | OpenAI API密钥 (GPT-4o) | ✅ |
| `DEEPSEEK_API_KEY` | DeepSeek API密钥 | ✅ |
| `THREECOMMAS_WEBHOOK_URL` | 3Commas Webhook URL (加密货币) | ✅ |
| `THREECOMMAS_SECRET` | 3Commas 密钥 | ✅ |
| `SIGNALSTACK_WEBHOOK_URL` | SignalStack Webhook URL (美股) | ⚠️ |
| `SIGNALSTACK_SECRET` | SignalStack 密钥 | ⚠️ |
| `PORT` | 服务端口 (默认6001) | ❌ |

---

## 系统要求

- **Python**: 3.9+ (推荐3.11)
- **内存**: 4GB+
- **网络**: 需要访问以下服务
  - OpenAI API
  - DeepSeek API
  - 3Commas/SignalStack Webhook
  - Coinbase/Yahoo Finance (行情数据)

---

## 常见问题

### Q: 启动后报错 "THREECOMMAS_WEBHOOK_URL 未设置"
A: 检查 `.env` 文件是否正确配置，确保没有多余空格

### Q: matplotlib/Tkinter 崩溃
A: v3.572已修复此问题，确保使用最新版本

### Q: 邮件收到但3commas没收到信号
A: 检查webhook URL是否正确，可查看 logs/server.log 日志

---

## 版本信息

- **主程序**: v3.572
- **扫描引擎**: v16.9
- **更新日期**: 2026-01-29
