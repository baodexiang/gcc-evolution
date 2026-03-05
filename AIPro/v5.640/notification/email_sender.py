"""
邮件发送模块
============
发送交易信号邮件通知。
"""

import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class EmailSender:
    """邮件发送器"""

    def __init__(
        self,
        smtp_server: str = "smtp.gmail.com",
        smtp_port: int = 587,
        sender: str = "",
        password: str = "",
        recipient: str = ""
    ):
        """
        初始化邮件发送器

        Args:
            smtp_server: SMTP服务器地址
            smtp_port: SMTP端口
            sender: 发送者邮箱
            password: 邮箱密码/应用密码
            recipient: 接收者邮箱
        """
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.sender = sender
        self.password = password
        self.recipient = recipient

        self.enabled = bool(sender and password and recipient)

        if not self.enabled:
            logger.warning("Email not configured, skipping notifications")

    def send_signal_notification(self, signal: Dict, recipient: str = None) -> bool:
        """
        发送信号通知邮件

        Args:
            signal: 信号数据
            recipient: 收件人邮箱（可选，默认使用初始化时的收件人）

        Returns:
            是否发送成功
        """
        # 使用传入的recipient或默认recipient
        target_recipient = recipient or self.recipient

        if not self.sender or not self.password or not target_recipient:
            logger.debug("Email not enabled, skipping send")
            return False

        try:
            action = signal.get("action", "UNKNOWN")
            symbol = signal.get("symbol", "UNKNOWN")
            price = signal.get("current_price", 0)
            confidence = signal.get("confidence", 0)
            reason = signal.get("reason", "")

            # 构建邮件主题
            emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡"}.get(action, "⚪")
            subject = f"{emoji} [DRY RUN] {action} Signal: {symbol} @ ${price:.2f}"

            # 构建邮件内容
            body = self._build_email_body(signal)

            return self._send_email(subject, body, target_recipient)

        except Exception as e:
            logger.error(f"Failed to send signal notification: {e}")
            return False

    def _build_email_body(self, signal: Dict) -> str:
        """构建邮件HTML内容"""
        action = signal.get("action", "UNKNOWN")
        symbol = signal.get("symbol", "UNKNOWN")
        timeframe = signal.get("timeframe", "")
        price = signal.get("current_price", 0)
        confidence = signal.get("confidence", 0)
        reason = signal.get("reason", "")
        timestamp = signal.get("timestamp", datetime.now())

        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)

        l1 = signal.get("l1", {})
        l2 = signal.get("l2", {})

        color = {"BUY": "#00ff88", "SELL": "#ff4444", "HOLD": "#ffaa00"}.get(action, "#888")

        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; background-color: #1a1a2e; color: #eee; padding: 20px;">
            <div style="max-width: 600px; margin: 0 auto; background-color: #16213e; padding: 20px; border-radius: 10px;">
                <div style="text-align: center; padding: 20px; background-color: #0f3460; border-radius: 10px; margin-bottom: 20px;">
                    <p style="margin: 0; color: #ff9800; font-size: 12px;">DRY RUN MODE - 验证模式，非实际交易</p>
                    <h1 style="margin: 10px 0; color: {color}; font-size: 48px;">{action}</h1>
                    <h2 style="margin: 10px 0; color: #fff;">{symbol}</h2>
                    <p style="font-size: 24px; color: #eee;">${price:.2f}</p>
                </div>

                <table style="width: 100%; border-collapse: collapse; color: #eee;">
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid #0f3460;"><strong>Timeframe</strong></td>
                        <td style="padding: 10px; border-bottom: 1px solid #0f3460;">{timeframe}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid #0f3460;"><strong>Confidence</strong></td>
                        <td style="padding: 10px; border-bottom: 1px solid #0f3460;">{confidence*100:.0f}%</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid #0f3460;"><strong>L1 Trend</strong></td>
                        <td style="padding: 10px; border-bottom: 1px solid #0f3460;">{l1.get('trend', 'N/A')} ({l1.get('strength', 'N/A')})</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid #0f3460;"><strong>ADX</strong></td>
                        <td style="padding: 10px; border-bottom: 1px solid #0f3460;">{l1.get('adx', 0):.1f}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid #0f3460;"><strong>RSI</strong></td>
                        <td style="padding: 10px; border-bottom: 1px solid #0f3460;">{l2.get('rsi', 0):.1f}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid #0f3460;"><strong>L2 Score</strong></td>
                        <td style="padding: 10px; border-bottom: 1px solid #0f3460;">{l2.get('score', 0):.1f}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px;"><strong>Reason</strong></td>
                        <td style="padding: 10px;">{reason}</td>
                    </tr>
                </table>

                <p style="text-align: center; color: #888; font-size: 12px; margin-top: 20px;">
                    Generated at {timestamp.strftime('%Y-%m-%d %H:%M:%S')}
                </p>
                <p style="text-align: center; color: #888; font-size: 12px;">
                    AI PRO Trading System v5.00 - Cloud Validation
                </p>
            </div>
        </body>
        </html>
        """

        return html

    def _send_email(self, subject: str, html_body: str, recipient: str = None) -> bool:
        """发送邮件"""
        target = recipient or self.recipient
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self.sender
            msg["To"] = target

            # 添加HTML内容
            html_part = MIMEText(html_body, "html")
            msg.attach(html_part)

            # 连接SMTP服务器并发送
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.sender, self.password)
                server.send_message(msg)

            logger.info(f"Email sent: {subject} -> {target}")
            return True

        except Exception as e:
            logger.error(f"Email send failed -> {target}: {e}")
            return False

    def send_test_email(self) -> bool:
        """发送测试邮件"""
        test_signal = {
            "action": "TEST",
            "symbol": "TEST",
            "current_price": 100.00,
            "confidence": 0.85,
            "reason": "This is a test email",
            "timeframe": "30m",
            "timestamp": datetime.now(),
            "l1": {"trend": "UP", "strength": "MODERATE", "adx": 28.5},
            "l2": {"rsi": 45.2, "score": 25.3}
        }

        return self.send_signal_notification(test_signal)
