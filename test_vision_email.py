# -*- coding: utf-8 -*-
"""
测试Vision比较邮件功能
运行: python test_vision_email.py
"""
import smtplib
from email.message import EmailMessage
from datetime import datetime
import pytz

# 邮件配置
EMAIL_SMTP_SERVER = 'smtp.gmail.com'
EMAIL_SMTP_PORT = 587
EMAIL_FROM = 'aistockllmpro@gmail.com'
EMAIL_PASSWORD = 'ficw ovws zvzb qmfs'
EMAIL_TO = ['baodexiang@hotmail.com']

def send_test_email():
    ny_tz = pytz.timezone('America/New_York')
    ny_time = datetime.now(ny_tz).strftime('%Y-%m-%d %H:%M:%S')

    subject = '[Vision TEST] BTCUSDC - Current:MISMATCH X4:MATCH Override:YES'
    body = f"""
========================================
Vision vs L1 Comparison Report (TEST)
========================================

Time: {ny_time} (New York)
Symbol: BTCUSDC

----------------------------------------
Current Period Comparison [MISMATCH]
----------------------------------------
L1:     Trend=UP    Regime=TRENDING
Vision: Trend=DOWN  Regime=TRENDING  Conf=90%

Direction Match: NO (UP vs DOWN)
Regime Match: YES

----------------------------------------
X4 Period Comparison [MATCH]
----------------------------------------
L1:     Trend=DOWN  Regime=TRENDING
Vision: Trend=DOWN  Regime=TRENDING  Conf=85%

Direction Match: YES
Regime Match: YES

----------------------------------------
Override Status
----------------------------------------
Override Applied: YES
Override: UP -> DOWN
Sync to Scan Engine: YES
Pass to L2: YES

========================================
Source: Vision Monitor v3.581 (TEST EMAIL)
========================================
"""

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = EMAIL_FROM
    msg['To'] = ', '.join(EMAIL_TO)
    msg.set_content(body)

    print(f"Sending test email to {EMAIL_TO[0]}...")

    with smtplib.SMTP(EMAIL_SMTP_SERVER, EMAIL_SMTP_PORT, timeout=30) as server:
        server.starttls()
        server.login(EMAIL_FROM, EMAIL_PASSWORD)
        server.send_message(msg)

    print(f"Test email sent successfully!")
    print(f"Check your inbox: {EMAIL_TO[0]}")

if __name__ == "__main__":
    send_test_email()
