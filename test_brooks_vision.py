"""Tests for brooks_vision.py v2.6 refactor — L2不拦截 + 形态方向不覆盖."""
import pytest
from unittest.mock import patch, MagicMock
from brooks_vision import _parse_vision_dict, PATTERN_SIGNAL_MAP, scan_symbol


# ===================================================================
# _parse_vision_dict tests
# ===================================================================

class TestParseVisionDict:
    """v2.6: PATTERN_SIGNAL_MAP仅用于白名单校验，不覆盖GPT direction."""

    def test_buy_signal_from_up(self):
        resp = {"direction": "UP", "confidence": 75, "reason": "bullish",
                "stoploss": 100.0, "brooks_pattern": "DOUBLE_BOTTOM"}
        result = _parse_vision_dict(resp)
        assert result["signal"] == "BUY"
        assert result["brooks_pattern"] == "DOUBLE_BOTTOM"
        assert result["confidence"] == 75

    def test_sell_signal_from_down(self):
        resp = {"direction": "DOWN", "confidence": 0.8, "reason": "bearish",
                "stoploss": 200.0, "brooks_pattern": "DOUBLE_TOP"}
        result = _parse_vision_dict(resp)
        assert result["signal"] == "SELL"
        assert result["confidence"] == 80  # 0.8 -> 80

    def test_side_returns_none_signal(self):
        resp = {"direction": "SIDE", "confidence": 50, "brooks_pattern": "NONE"}
        result = _parse_vision_dict(resp)
        assert result["signal"] == "NONE"

    def test_no_direction_override_by_pattern(self):
        """v2.6核心: GPT说DOWN但形态是DOUBLE_BOTTOM(BUY形态), 不应覆盖为BUY."""
        resp = {"direction": "DOWN", "confidence": 70, "reason": "test",
                "stoploss": 50.0, "brooks_pattern": "DOUBLE_BOTTOM"}
        result = _parse_vision_dict(resp)
        # v2.6: 信任GPT判断, 不用MAP覆盖
        assert result["signal"] == "SELL"
        assert result["brooks_pattern"] == "DOUBLE_BOTTOM"

    def test_unknown_pattern_normalized_to_none(self):
        resp = {"direction": "UP", "confidence": 60,
                "brooks_pattern": "UNKNOWN_PATTERN"}
        result = _parse_vision_dict(resp)
        assert result["brooks_pattern"] == "NONE"

    def test_wedge_compat_buy(self):
        resp = {"direction": "UP", "confidence": 65, "brooks_pattern": "WEDGE"}
        result = _parse_vision_dict(resp)
        assert result["brooks_pattern"] == "WEDGE_FALLING"

    def test_wedge_compat_sell(self):
        resp = {"direction": "DOWN", "confidence": 65, "brooks_pattern": "WEDGE"}
        result = _parse_vision_dict(resp)
        assert result["brooks_pattern"] == "WEDGE_RISING"

    def test_wedge_side_becomes_none(self):
        resp = {"direction": "SIDE", "confidence": 50, "brooks_pattern": "WEDGE"}
        result = _parse_vision_dict(resp)
        assert result["brooks_pattern"] == "NONE"

    def test_mtr_compat_buy(self):
        resp = {"direction": "UP", "confidence": 70, "brooks_pattern": "MTR"}
        result = _parse_vision_dict(resp)
        assert result["brooks_pattern"] == "MTR_BUY"

    def test_mtr_compat_sell(self):
        resp = {"direction": "DOWN", "confidence": 70, "brooks_pattern": "MTR"}
        result = _parse_vision_dict(resp)
        assert result["brooks_pattern"] == "MTR_SELL"

    def test_empty_resp(self):
        assert _parse_vision_dict(None)["signal"] == "NONE"
        assert _parse_vision_dict({})["signal"] == "NONE"
        assert _parse_vision_dict("bad")["signal"] == "NONE"

    def test_all_map_patterns_are_valid(self):
        """所有MAP中的形态应该通过白名单校验."""
        for pattern in PATTERN_SIGNAL_MAP:
            resp = {"direction": "UP", "confidence": 50, "brooks_pattern": pattern}
            result = _parse_vision_dict(resp)
            assert result["brooks_pattern"] == pattern, f"{pattern} should be valid"


# ===================================================================
# scan_symbol tests — L2不拦截
# ===================================================================

class TestScanSymbolL2NoBlock:
    """v2.6: L2反方向不再拦截, 仅记录AGREE/L2_NEUTRAL."""

    def _make_mods(self, vision_resp):
        """构造mock mods dict."""
        mods = {
            "call_vision": MagicMock(return_value=vision_resp),
        }
        return mods

    def _make_radar(self, direction="BUY", pattern="DOUBLE_BOTTOM"):
        return {
            "direction": direction, "confidence": 75,
            "reason": "test", "stoploss": 100.0,
            "brooks_pattern": pattern,
        }

    @patch("brooks_vision._can_execute", return_value=True)
    @patch("brooks_vision._get_l2_signal", return_value="SELL")
    @patch("brooks_vision._simple_filter", return_value={"pass": True, "reason": "ok"})
    @patch("brooks_vision.radar_scan")
    def test_buy_not_blocked_by_l2_sell(self, mock_radar, mock_filter,
                                         mock_l2, mock_exec):
        """v2.6: BUY时L2=SELL不再拦截, 应该EXECUTE."""
        mock_radar.return_value = {
            "signal": "BUY", "pattern": "test", "confidence": 75,
            "stoploss": 100.0, "brooks_pattern": "DOUBLE_BOTTOM", "bars": [],
        }
        result = scan_symbol("BTCUSDC", {})
        assert result is not None
        assert "EXECUTE" in result["final"]
        assert "L2_NEUTRAL" in result["final"]

    @patch("brooks_vision._can_execute", return_value=True)
    @patch("brooks_vision._get_l2_signal", return_value="BUY")
    @patch("brooks_vision._simple_filter", return_value={"pass": True, "reason": "ok"})
    @patch("brooks_vision.radar_scan")
    def test_sell_not_blocked_by_l2_buy(self, mock_radar, mock_filter,
                                         mock_l2, mock_exec):
        """v2.6: SELL时L2=BUY不再拦截, 应该EXECUTE."""
        mock_radar.return_value = {
            "signal": "SELL", "pattern": "test", "confidence": 70,
            "stoploss": 200.0, "brooks_pattern": "DOUBLE_TOP", "bars": [],
        }
        result = scan_symbol("ETHUSDC", {})
        assert result is not None
        assert "EXECUTE" in result["final"]
        assert "L2_NEUTRAL" in result["final"]

    @patch("brooks_vision._can_execute", return_value=True)
    @patch("brooks_vision._get_l2_signal", return_value="BUY")
    @patch("brooks_vision._simple_filter", return_value={"pass": True, "reason": "ok"})
    @patch("brooks_vision.radar_scan")
    def test_l2_agree_tagged(self, mock_radar, mock_filter, mock_l2, mock_exec):
        """L2同方向时标记AGREE."""
        mock_radar.return_value = {
            "signal": "BUY", "pattern": "test", "confidence": 80,
            "stoploss": 100.0, "brooks_pattern": "BULL_FLAG", "bars": [],
        }
        result = scan_symbol("BTCUSDC", {})
        assert "AGREE" in result["final"]
        assert "EXECUTE" in result["final"]

    @patch("brooks_vision._can_execute", return_value=False)
    @patch("brooks_vision._get_l2_signal", return_value="HOLD")
    @patch("brooks_vision._simple_filter", return_value={"pass": True, "reason": "ok"})
    @patch("brooks_vision.radar_scan")
    def test_daily_limit_blocks(self, mock_radar, mock_filter, mock_l2, mock_exec):
        """每日限次仍然生效."""
        mock_radar.return_value = {
            "signal": "BUY", "pattern": "test", "confidence": 70,
            "stoploss": 100.0, "brooks_pattern": "NONE", "bars": [],
        }
        result = scan_symbol("BTCUSDC", {})
        assert "DAILY_LIMIT" in result["final"]
