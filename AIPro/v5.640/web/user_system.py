"""
User System Module
==================
Handles user registration, login, and subscription.
Initial limit: 500 users, expandable to 1000.

v5.435 Security Updates:
- Enhanced password hashing with per-user random salt (32-char hex)
- Login attempt rate limiting (5 attempts per 15 minutes)
- Stronger password requirements (8+ chars, letters + numbers)
- Password change functionality with old password verification
- Backward compatible with legacy fixed-salt users
"""

import os
import json
import hashlib
import secrets
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, List
from pathlib import Path

logger = logging.getLogger(__name__)

# v5.435: Login attempt tracking for rate limiting
LOGIN_ATTEMPTS: Dict[str, List[datetime]] = {}
MAX_LOGIN_ATTEMPTS = 5  # Max attempts per 15 minutes
LOGIN_LOCKOUT_MINUTES = 15


class UserSystem:
    """User management system"""

    def __init__(
        self,
        db_path: str,
        max_users: int = 100,
        session_lifetime_hours: int = 24
    ):
        self.db_path = db_path
        self.max_users = max_users
        self.session_lifetime = timedelta(hours=session_lifetime_hours)
        self.users: Dict = {}
        self.sessions: Dict = {}
        self._load_users()

    def _load_users(self):
        """Load users from JSON file"""
        try:
            db_file = Path(self.db_path)
            if db_file.exists():
                with open(db_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.users = data.get("users", {})
                    logger.info(f"Loaded {len(self.users)} users")
            else:
                db_file.parent.mkdir(parents=True, exist_ok=True)
                self._save_users()
            # Ensure default admin exists
            self._ensure_admin()
        except Exception as e:
            logger.error(f"Failed to load users: {e}")
            self.users = {}

    def _ensure_admin(self):
        """Ensure default admin account exists"""
        admin_email = "admin@aipro.com"
        if admin_email not in self.users:
            # v5.435: Use per-user salt for admin too
            admin_salt = self._generate_salt()
            self.users[admin_email] = {
                "id": "admin_001",
                "email": admin_email,
                "salt": admin_salt,
                "password_hash": self._hash_password("admin888", admin_salt),
                "created_at": datetime.now().isoformat(),
                "subscribed": True,
                "subscription_date": datetime.now().isoformat(),
                "language": "en",
                "last_login": None,
                "is_admin": True
            }
            self._save_users()
            logger.warning("Default admin account created - CHANGE PASSWORD IMMEDIATELY!")
            logger.info("Default admin: admin@aipro.com / admin888")

    def _save_users(self):
        """Save users to JSON file"""
        try:
            with open(self.db_path, 'w', encoding='utf-8') as f:
                json.dump({"users": self.users}, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save users: {e}")

    def _hash_password(self, password: str, salt: str = None) -> str:
        """
        Hash password with salt
        v5.435: Support per-user random salt for enhanced security
        """
        if salt is None:
            # Legacy mode for backward compatibility
            salt = "aipro_v5411_salt"
        return hashlib.sha256(f"{salt}{password}".encode()).hexdigest()

    def _generate_salt(self) -> str:
        """v5.435: Generate random salt for new users"""
        return secrets.token_hex(16)

    def _check_rate_limit(self, email: str) -> tuple:
        """
        v5.435: Check if login attempts are within rate limit
        Returns: (is_allowed, remaining_attempts, lockout_seconds)
        """
        now = datetime.now()
        cutoff = now - timedelta(minutes=LOGIN_LOCKOUT_MINUTES)

        # Clean old attempts
        if email in LOGIN_ATTEMPTS:
            LOGIN_ATTEMPTS[email] = [
                t for t in LOGIN_ATTEMPTS[email] if t > cutoff
            ]
        else:
            LOGIN_ATTEMPTS[email] = []

        attempts = len(LOGIN_ATTEMPTS[email])
        remaining = MAX_LOGIN_ATTEMPTS - attempts

        if attempts >= MAX_LOGIN_ATTEMPTS:
            # Calculate lockout remaining time
            oldest_attempt = min(LOGIN_ATTEMPTS[email])
            unlock_time = oldest_attempt + timedelta(minutes=LOGIN_LOCKOUT_MINUTES)
            lockout_seconds = int((unlock_time - now).total_seconds())
            return (False, 0, max(0, lockout_seconds))

        return (True, remaining, 0)

    def _record_login_attempt(self, email: str):
        """v5.435: Record a failed login attempt"""
        if email not in LOGIN_ATTEMPTS:
            LOGIN_ATTEMPTS[email] = []
        LOGIN_ATTEMPTS[email].append(datetime.now())

    def _clear_login_attempts(self, email: str):
        """v5.435: Clear login attempts after successful login"""
        if email in LOGIN_ATTEMPTS:
            del LOGIN_ATTEMPTS[email]

    def register(self, email: str, password: str) -> Dict:
        """
        Register new user

        Returns:
            {
                "success": bool,
                "message": str,
                "user_id": str (if success)
            }
        """
        email = email.lower().strip()

        # Validate email
        if not email or "@" not in email:
            return {"success": False, "message": "Invalid email"}

        # Check if exists
        if email in self.users:
            return {"success": False, "message": "email_exists"}

        # Check user limit
        if len(self.users) >= self.max_users:
            return {"success": False, "message": "user_limit_reached"}

        # v5.435: Validate password (stronger requirements)
        if len(password) < 8:
            return {"success": False, "message": "Password too short (min 8 characters)"}

        # v5.435: Check password complexity
        has_letter = any(c.isalpha() for c in password)
        has_digit = any(c.isdigit() for c in password)
        if not (has_letter and has_digit):
            return {"success": False, "message": "Password must contain letters and numbers"}

        # Create user with per-user salt
        user_id = secrets.token_hex(8)
        user_salt = self._generate_salt()
        self.users[email] = {
            "id": user_id,
            "email": email,
            "salt": user_salt,  # v5.435: Per-user salt
            "password_hash": self._hash_password(password, user_salt),
            "created_at": datetime.now().isoformat(),
            "subscribed": False,
            "subscription_date": None,
            "language": "en",
            "last_login": None,
            "watchlist_stocks": [],  # Max 10 stocks
            "watchlist_crypto": [],  # Max 5 crypto
            "scan_timeframe": "30m"  # Default timeframe
        }

        self._save_users()
        logger.info(f"New user registered: {email}")

        return {
            "success": True,
            "message": "register_success",
            "user_id": user_id
        }

    def login(self, email: str, password: str) -> Dict:
        """
        Login user

        Returns:
            {
                "success": bool,
                "message": str,
                "session_token": str (if success),
                "user": dict (if success)
            }
        """
        email = email.lower().strip()

        # v5.435: Check rate limit before attempting login
        is_allowed, remaining, lockout_seconds = self._check_rate_limit(email)
        if not is_allowed:
            logger.warning(f"Login rate limited for {email}, lockout: {lockout_seconds}s")
            return {
                "success": False,
                "message": f"Too many login attempts. Try again in {lockout_seconds // 60 + 1} minutes",
                "lockout_seconds": lockout_seconds
            }

        if email not in self.users:
            self._record_login_attempt(email)
            return {"success": False, "message": "login_failed"}

        user = self.users[email]

        # v5.435: Support both old (fixed salt) and new (per-user salt) users
        user_salt = user.get("salt")  # None for legacy users
        if user["password_hash"] != self._hash_password(password, user_salt):
            self._record_login_attempt(email)
            return {"success": False, "message": "login_failed"}

        # Create session
        session_token = secrets.token_hex(32)
        self.sessions[session_token] = {
            "email": email,
            "user_id": user["id"],
            "created_at": datetime.now(),
            "expires_at": datetime.now() + self.session_lifetime
        }

        # v5.435: Clear failed attempts on successful login
        self._clear_login_attempts(email)

        # Update last login
        user["last_login"] = datetime.now().isoformat()
        self._save_users()

        logger.info(f"User logged in: {email}")

        return {
            "success": True,
            "message": "login_success",
            "session_token": session_token,
            "user": {
                "id": user["id"],
                "email": user["email"],
                "subscribed": user["subscribed"],
                "language": user.get("language", "en")
            }
        }

    def logout(self, session_token: str) -> Dict:
        """Logout user"""
        if session_token in self.sessions:
            del self.sessions[session_token]
            return {"success": True, "message": "Logged out"}
        return {"success": False, "message": "Invalid session"}

    def validate_session(self, session_token: str) -> Optional[Dict]:
        """
        Validate session token

        Returns user info if valid, None if invalid
        """
        if not session_token or session_token not in self.sessions:
            return None

        session = self.sessions[session_token]

        # Check expiry
        if datetime.now() > session["expires_at"]:
            del self.sessions[session_token]
            return None

        email = session["email"]
        if email not in self.users:
            return None

        user = self.users[email]
        return {
            "id": user["id"],
            "email": user["email"],
            "subscribed": user["subscribed"],
            "language": user.get("language", "en"),
            "is_admin": user.get("is_admin", False)
        }

    def subscribe(self, email: str) -> Dict:
        """Subscribe user to notifications"""
        email = email.lower().strip()

        if email not in self.users:
            return {"success": False, "message": "User not found"}

        self.users[email]["subscribed"] = True
        self.users[email]["subscription_date"] = datetime.now().isoformat()
        self._save_users()

        logger.info(f"User subscribed: {email}")
        return {"success": True, "message": "Subscribed"}

    def unsubscribe(self, email: str) -> Dict:
        """Unsubscribe user from notifications"""
        email = email.lower().strip()

        if email not in self.users:
            return {"success": False, "message": "User not found"}

        self.users[email]["subscribed"] = False
        self._save_users()

        logger.info(f"User unsubscribed: {email}")
        return {"success": True, "message": "Unsubscribed"}

    def set_language(self, email: str, language: str) -> Dict:
        """Set user language preference"""
        email = email.lower().strip()

        if email not in self.users:
            return {"success": False, "message": "User not found"}

        if language not in ["en", "zh"]:
            return {"success": False, "message": "Invalid language"}

        self.users[email]["language"] = language
        self._save_users()

        return {"success": True, "message": "Language updated"}

    def get_subscribed_users(self) -> List[str]:
        """Get list of subscribed user emails"""
        return [
            email for email, user in self.users.items()
            if user.get("subscribed", False)
        ]

    def get_user_count(self) -> Dict:
        """Get user statistics"""
        total = len(self.users)
        subscribed = len(self.get_subscribed_users())

        return {
            "total": total,
            "subscribed": subscribed,
            "max_users": self.max_users,
            "available": self.max_users - total
        }

    def cleanup_sessions(self):
        """Remove expired sessions"""
        now = datetime.now()
        expired = [
            token for token, session in self.sessions.items()
            if now > session["expires_at"]
        ]
        for token in expired:
            del self.sessions[token]

    def is_admin(self, email: str) -> bool:
        """Check if user is admin"""
        email = email.lower().strip()
        if email not in self.users:
            return False
        return self.users[email].get("is_admin", False)

    def change_password(self, email: str, old_password: str, new_password: str) -> Dict:
        """
        v5.435: Change user password
        Requires old password verification for security
        """
        email = email.lower().strip()

        if email not in self.users:
            return {"success": False, "message": "User not found"}

        user = self.users[email]

        # Verify old password
        user_salt = user.get("salt")
        if user["password_hash"] != self._hash_password(old_password, user_salt):
            return {"success": False, "message": "Current password incorrect"}

        # Validate new password
        if len(new_password) < 8:
            return {"success": False, "message": "New password too short (min 8 characters)"}

        has_letter = any(c.isalpha() for c in new_password)
        has_digit = any(c.isdigit() for c in new_password)
        if not (has_letter and has_digit):
            return {"success": False, "message": "Password must contain letters and numbers"}

        # Generate new salt and hash
        new_salt = self._generate_salt()
        user["salt"] = new_salt
        user["password_hash"] = self._hash_password(new_password, new_salt)
        self._save_users()

        logger.info(f"Password changed for {email}")
        return {"success": True, "message": "Password changed successfully"}

    def get_all_users(self) -> List[Dict]:
        """Get all users for admin panel"""
        users_list = []
        for email, user in self.users.items():
            users_list.append({
                "email": email,
                "id": user.get("id"),
                "created_at": user.get("created_at"),
                "subscribed": user.get("subscribed", False),
                "last_login": user.get("last_login"),
                "is_admin": user.get("is_admin", False)
            })
        return sorted(users_list, key=lambda x: x.get("created_at", ""), reverse=True)

    def delete_user(self, admin_email: str, target_email: str) -> Dict:
        """Delete user (admin only)"""
        admin_email = admin_email.lower().strip()
        target_email = target_email.lower().strip()

        if not self.is_admin(admin_email):
            return {"success": False, "message": "Not authorized"}

        if target_email not in self.users:
            return {"success": False, "message": "User not found"}

        if self.users[target_email].get("is_admin", False):
            return {"success": False, "message": "Cannot delete admin"}

        del self.users[target_email]
        self._save_users()
        logger.info(f"Admin {admin_email} deleted user {target_email}")
        return {"success": True, "message": "User deleted"}

    def toggle_subscription(self, admin_email: str, target_email: str) -> Dict:
        """Toggle user subscription (admin only)"""
        admin_email = admin_email.lower().strip()
        target_email = target_email.lower().strip()

        if not self.is_admin(admin_email):
            return {"success": False, "message": "Not authorized"}

        if target_email not in self.users:
            return {"success": False, "message": "User not found"}

        current = self.users[target_email].get("subscribed", False)
        self.users[target_email]["subscribed"] = not current
        self._save_users()
        return {"success": True, "subscribed": not current}

    def update_watchlist(self, email: str, stocks: List[str], crypto: List[str], timeframe: str) -> Dict:
        """Update user watchlist"""
        email = email.lower().strip()

        if email not in self.users:
            return {"success": False, "message": "User not found"}

        # Validate limits
        if len(stocks) > 10:
            return {"success": False, "message": "Max 10 stocks allowed"}
        if len(crypto) > 5:
            return {"success": False, "message": "Max 5 crypto allowed"}

        # Validate timeframe
        valid_timeframes = ["5m", "10m", "15m", "30m", "1h", "4h", "1d"]
        if timeframe not in valid_timeframes:
            timeframe = "30m"

        self.users[email]["watchlist_stocks"] = stocks[:10]
        self.users[email]["watchlist_crypto"] = crypto[:5]
        self.users[email]["scan_timeframe"] = timeframe
        self._save_users()

        logger.info(f"User {email} updated watchlist: {len(stocks)} stocks, {len(crypto)} crypto")
        return {"success": True, "message": "Watchlist updated"}

    def get_watchlist(self, email: str) -> Dict:
        """Get user watchlist"""
        email = email.lower().strip()

        if email not in self.users:
            return {"stocks": [], "crypto": [], "timeframe": "30m"}

        user = self.users[email]
        return {
            "stocks": user.get("watchlist_stocks", []),
            "crypto": user.get("watchlist_crypto", []),
            "timeframe": user.get("scan_timeframe", "30m")
        }
