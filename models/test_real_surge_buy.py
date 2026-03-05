#!/usr/bin/env python3
"""
⚠️ 警告：这是真实交易测试脚本！
模拟 SOLUSDC 暴涨信号，触发真实买入 + 邮件通知

运行前请确认：
1. 3Commas webhook 配置正确
2. SOLUSDC 仓位未满 (position_units < max_units)
3. 你接受真实买入的后果
"""

import os
import sys
import json
import time
import ssl
import smtplib
import requests
from email.message import EmailMessage
from datetime import datetime
import pytz

# ========== 配置 ==========
SYMBOL = "SOLUSDC"

# 3Commas 配置 (从环境变量读取)
THREECOMMAS_WEBHOOK_URL = os.getenv("THREECOMMAS_WEBHOOK_URL", "")
THREECOMMAS_SECRET = os.getenv("THREECOMMAS_SECRET", "")

# SOLUSDC 的 bot UUID
PAIR_CONFIG = {
    "SOLUSDC": {
        "exchange": "coinbase",
        "long_bot_uuid": "69d2e27c-bbf9-4a7a-8e54-f989e0a4d346",
        "short_bot_uuid": "dd6ae8bc-9ab7-4e44-ae31-b8bada86015e",
        "unit_size": 10.0,
    },
}

# 邮件配置
EMAIL_ENABLED = True
EMAIL_SMTP_SERVER = "smtp.gmail.com"
EMAIL_SMTP_PORT = 587
EMAIL_FROM = "aistockllmpro@gmail.com"
EMAIL_PASSWORD = "ficw ovws zvzb qmfs"
EMAIL_TO = ["baodexiang@hotmail.com"]

# 纽约时区
NY_TIMEZONE = pytz.timezone("America/New_York")


def send_3commas_signal(final_action: str, last_close: float, symbol: str) -> bool:
    """发送3Commas交易信号"""
    if final_action not in ["BUY", "SELL"]:
        print(f"[3Commas] final_action={final_action} 非 BUY/SELL，跳过。")
        return False

    if not THREECOMMAS_WEBHOOK_URL:
        print("[3Commas] THREECOMMAS_WEBHOOK_URL 未设置，跳过下单。")
        return False

    if not THREECOMMAS_SECRET:
        print("[3Commas] THREECOMMAS_SECRET 未设置，跳过下单。")
        return False

    cfg = PAIR_CONFIG.get(symbol)
    if not cfg:
        print(f"[3Commas] 未在 PAIR_CONFIG 中找到 {symbol}，跳过下单。")
        return False

    if final_action == "BUY":
        bot_uuid = cfg.get("long_bot_uuid")
        action = "enter_long"
    else:
        bot_uuid = cfg.get("short_bot_uuid")
        action = "enter_short"

    if not bot_uuid:
        print(f"[3Commas] {symbol} 缺少对应 {final_action} bot_uuid，跳过下单。")
        return False

    payload = {
        "secret": THREECOMMAS_SECRET,
        "max_lag": "300",
        "timestamp": int(time.time()),
        "trigger_price": float(last_close),
        "tv_exchange": cfg.get("exchange", "coinbase"),
        "tv_instrument": symbol,
        "action": action,
        "bot_uuid": bot_uuid,
    }

    print(f"[3Commas] 发送请求...")
    print(f"[3Commas] URL: {THREECOMMAS_WEBHOOK_URL}")
    print(f"[3Commas] Payload: {json.dumps(payload, indent=2)}")

    try:
        resp = requests.post(THREECOMMAS_WEBHOOK_URL, json=payload, timeout=10)
        ok_http = 200 <= resp.status_code < 300

        print(f"[3Commas] HTTP status={resp.status_code}")
        raw_text = (resp.text or "").strip()
        print("[3Commas] raw_response:", raw_text[:500])

        ok_logic = True
        try:
            data = resp.json()
            if isinstance(data, dict) and (
                data.get("error")
                or str(data.get("status", "")).lower() == "error"
            ):
                ok_logic = False
        except Exception:
            pass

        print(f"[3Commas] {symbol} {final_action} webhook ok_http={ok_http}, ok_logic={ok_logic}")
        return ok_http and ok_logic

    except Exception as e:
        print("[3Commas] 请求异常:", e)
        return False


def send_email_notification(subject: str, body: str) -> None:
    """发送邮件通知"""
    if not EMAIL_ENABLED:
        print("[EMAIL] 邮件未启用")
        return
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = EMAIL_FROM
        msg["To"] = ", ".join(EMAIL_TO)
        msg.set_content(body)

        context = ssl.create_default_context()
        with smtplib.SMTP(EMAIL_SMTP_SERVER, EMAIL_SMTP_PORT) as server:
            server.starttls(context=context)
            server.login(EMAIL_FROM, EMAIL_PASSWORD)
            server.send_message(msg)

        print("[EMAIL] ✅ 发送成功！")
    except Exception as e:
        print("[EMAIL] ❌ 邮件发送失败：", e)


def main():
    print("=" * 60)
    print("⚠️  真实交易测试 - SOLUSDC 暴涨买入")
    print("=" * 60)
    
    # 检查环境变量
    if not THREECOMMAS_WEBHOOK_URL or not THREECOMMAS_SECRET:
        print("\n❌ 错误: 3Commas 环境变量未设置")
        print("请设置 THREECOMMAS_WEBHOOK_URL 和 THREECOMMAS_SECRET")
        return False
    
    # 模拟数据
    symbol = SYMBOL
    reference_close = 120.0  # 假设基准价
    current_close = 124.0    # 假设当前价 (+3.3% 暴涨)
    change_pct = (current_close - reference_close) / reference_close
    threshold = 0.025  # 2.5%
    
    old_position = 2  # 假设当前仓位
    max_units = 5
    new_position = old_position + 1
    
    now_ny = datetime.now(NY_TIMEZONE)
    time_str = now_ny.strftime("%Y-%m-%d %H:%M:%S")
    
    print(f"\n模拟暴涨场景:")
    print(f"  品种: {symbol}")
    print(f"  基准价: {reference_close}")
    print(f"  当前价: {current_close}")
    print(f"  涨幅: {change_pct:.2%}")
    print(f"  阈值: ±{threshold:.0%}")
    print(f"  信号: SURGE_BUY")
    
    # 确认
    print("\n" + "=" * 60)
    confirm = input("⚠️  确认执行真实买入? (输入 'yes' 确认): ")
    if confirm.lower() != 'yes':
        print("已取消")
        return False
    
    print("\n" + "=" * 60)
    print("执行买入...")
    print("=" * 60)
    
    # 1. 发送交易信号
    send_ok = send_3commas_signal("BUY", current_close, symbol)
    
    if send_ok:
        print(f"\n✅ {symbol} 暴涨买入信号已发送!")
        
        # 2. 发送邮件通知
        email_subject = f"⚡ [测试] 10m暴涨买入 | {symbol} | BUY"
        email_body = f"""
========================================
⚡ L2 10m 实时触发 - 暴涨买入 [测试]
========================================

时间: {time_str} (纽约时间)
品种: {symbol}
动作: BUY (暴涨追涨买入)

----------------------------------------
触发条件:
----------------------------------------
基准价格: {reference_close:.4f}
当前价格: {current_close:.4f}
涨跌幅: {change_pct:.2%}
阈值: ±{threshold:.0%}

----------------------------------------
仓位变化:
----------------------------------------
原仓位: {old_position}/{max_units}
新仓位: {new_position}/{max_units}
买入价格: {current_close:.4f}

----------------------------------------
触发原因: 暴涨{change_pct:.2%} > +{threshold:.0%}
========================================

⚠️ 这是测试交易
"""
        send_email_notification(email_subject, email_body)
        
        print("\n" + "=" * 60)
        print("✅ 测试完成!")
        print("=" * 60)
        return True
    else:
        print(f"\n❌ {symbol} 买入信号发送失败")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
