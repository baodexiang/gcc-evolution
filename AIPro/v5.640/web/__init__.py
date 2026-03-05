"""
Web Module
==========
Flask routes and templates for AI PRO Trading v5.411
"""

from .routes import create_routes
from .i18n import I18n, get_translation, t, translate_analysis_result
from .user_system import UserSystem

__all__ = ["create_routes", "I18n", "get_translation", "t", "translate_analysis_result", "UserSystem"]
