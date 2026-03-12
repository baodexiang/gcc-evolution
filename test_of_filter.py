"""
test_of_filter.py — OF-Filter 单元测试 (GCC-0255 S9)
覆盖 R1-R4 全规则 + Volume Profile + volume_score + Phase控制
"""
import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

# 确保项目根目录在 path
sys.path.insert(0, os.path.dirname(__file__))

from order_flow.of_filter import OFFilter, _is_crypto, _load_config


class TestIsCrypto(unittest.TestCase):
    """_is_crypto 品种识别"""

    def test_usdc(self):
        self.assertTrue(_is_crypto("BTCUSDC"))
        self.assertTrue(_is_crypto("ETHUSDC"))

    def test_usdt(self):
        self.assertTrue(_is_crypto("BTCUSDT"))

    def test_dash_usd(self):
        self.assertTrue(_is_crypto("BTC-USD"))
        self.assertTrue(_is_crypto("ETH-USD"))

    def test_stock(self):
        self.assertFalse(_is_crypto("TSLA"))
        self.assertFalse(_is_crypto("ONDS"))
        self.assertFalse(_is_crypto("AMD"))

    def test_empty(self):
        self.assertTrue(_is_crypto(""))


class TestApplyRules(unittest.TestCase):
    """R1-R4 规则引擎"""

    def setUp(self):
        self.of = OFFilter()

    def test_r1_cvd_sell_blocks_buy(self):
        passed, reason = self.of._apply_rules("BUY", 0.0, "SELL_DOMINANT", 1.0, "any")
        self.assertFalse(passed)
        self.assertIn("CVD_SELL_DOMINANT", reason)

    def test_r1_cvd_buy_blocks_sell(self):
        passed, reason = self.of._apply_rules("SELL", 0.0, "BUY_DOMINANT", 1.0, "any")
        self.assertFalse(passed)
        self.assertIn("CVD_BUY_DOMINANT", reason)

    def test_r1_cvd_aligned_passes(self):
        passed, _ = self.of._apply_rules("BUY", 0.0, "BUY_DOMINANT", 1.0, "any")
        self.assertTrue(passed)

    def test_r2_obi_sell_pressure_blocks_buy(self):
        passed, reason = self.of._apply_rules("BUY", -0.5, "BALANCED", 1.0, "any")
        self.assertFalse(passed)
        self.assertIn("OBI_SELL_PRESSURE", reason)

    def test_r2_obi_buy_pressure_blocks_sell(self):
        passed, reason = self.of._apply_rules("SELL", 0.5, "BALANCED", 1.0, "any")
        self.assertFalse(passed)
        self.assertIn("OBI_BUY_PRESSURE", reason)

    def test_r2_obi_within_threshold_passes(self):
        passed, _ = self.of._apply_rules("BUY", -0.2, "BALANCED", 1.0, "any")
        self.assertTrue(passed)

    def test_r3_rvol_low_blocks_breakout(self):
        passed, reason = self.of._apply_rules("BUY", 0.0, "BALANCED", 0.3, "breakout")
        self.assertFalse(passed)
        self.assertIn("RVOL_TOO_LOW", reason)

    def test_r3_rvol_low_passes_non_breakout(self):
        passed, _ = self.of._apply_rules("BUY", 0.0, "BALANCED", 0.3, "any")
        self.assertTrue(passed)

    def test_r4_multiple_blocks(self):
        passed, reason = self.of._apply_rules("BUY", -0.5, "SELL_DOMINANT", 0.3, "breakout")
        self.assertFalse(passed)
        parts = reason.split(",")
        self.assertGreaterEqual(len(parts), 2)  # 至少2个拦截原因

    def test_all_clear(self):
        passed, reason = self.of._apply_rules("BUY", 0.1, "BUY_DOMINANT", 1.5, "breakout")
        self.assertTrue(passed)
        self.assertEqual(reason, "")

    def test_unknown_data_passes(self):
        passed, _ = self.of._apply_rules("BUY", 0.0, "UNKNOWN", 1.0, "any")
        self.assertTrue(passed)


class TestVolumeScore(unittest.TestCase):
    """volume_score 归一化"""

    def setUp(self):
        self.of = OFFilter()

    def test_direction_consistent_high_rvol(self):
        score = self.of._calc_volume_score("BUY", 0.5, "BUY_PRESSURE", "BUY_DOMINANT", 2.0)
        self.assertGreater(score, 0.5)

    def test_direction_inconsistent(self):
        score = self.of._calc_volume_score("BUY", -0.5, "SELL_PRESSURE", "SELL_DOMINANT", 2.0)
        self.assertLess(score, 0.3)

    def test_score_bounds(self):
        for obi in (-1.0, 0.0, 1.0):
            for rvol in (0.1, 1.0, 5.0):
                score = self.of._calc_volume_score("BUY", obi, "NEUTRAL", "BALANCED", rvol)
                self.assertGreaterEqual(score, 0.0)
                self.assertLessEqual(score, 1.0)


class TestPhaseControl(unittest.TestCase):
    """Phase 控制"""

    def setUp(self):
        self.of = OFFilter()

    def test_phase0_returns_none(self):
        self.of._phase = 0
        # Mock data sources to avoid API calls
        self.of._get_obi_cvd = lambda s: {"obi": -0.5, "obi_bias": "SELL_PRESSURE",
                                           "cvd": 0, "cvd_bias": "SELL_DOMINANT"}
        self.of._get_rvol = lambda s: 1.0
        self.of._calc_volume_profile = lambda s: {"vp_position": "IN_VALUE",
                                                    "poc": 100, "val": 95, "vah": 105}
        self.of._write_state = lambda s, d, r: None  # skip I/O

        result = self.of.run("TSLA", "BUY")
        self.assertIsNone(result["passed"])

    def test_phase1_returns_bool(self):
        self.of._phase = 1
        self.of._reload_config = lambda: None  # 防止 run() 内重载覆盖
        self.of._get_obi_cvd = lambda s: {"obi": -0.5, "obi_bias": "SELL_PRESSURE",
                                           "cvd": 0, "cvd_bias": "SELL_DOMINANT"}
        self.of._get_rvol = lambda s: 1.0
        self.of._calc_volume_profile = lambda s: {"vp_position": "IN_VALUE",
                                                    "poc": 100, "val": 95, "vah": 105}
        self.of._write_state = lambda s, d, r: None

        result = self.of.run("TSLA", "BUY")
        self.assertIsInstance(result["passed"], bool)
        self.assertFalse(result["passed"])  # CVD_SELL + OBI_SELL should block

    def test_invalid_direction(self):
        result = self.of.run("TSLA", "HOLD")
        self.assertIsNone(result["passed"])


class TestVolumeProfile(unittest.TestCase):
    """Volume Profile 计算"""

    def setUp(self):
        self.of = OFFilter()

    def test_above_vah(self):
        # 模拟K线: 价格在100-110之间, 最后收盘115(超出VAH)
        bars = []
        for i in range(20):
            bars.append({"low": 100.0, "high": 110.0, "close": 105.0, "volume": 1000.0})
        bars.append({"low": 114.0, "high": 116.0, "close": 115.0, "volume": 100.0})

        with patch.object(self.of, '_build_volume_profile') as mock_vp:
            mock_vp.return_value = {"poc": 105.0, "val": 102.0, "vah": 108.0,
                                     "lvn": [], "hvn": [105.0], "vp_position": "ABOVE_VAH"}
            result = self.of._calc_volume_profile("TSLA")
            self.assertEqual(result["vp_position"], "ABOVE_VAH")

    def test_below_val(self):
        with patch.object(self.of, '_build_volume_profile') as mock_vp:
            mock_vp.return_value = {"poc": 105.0, "val": 102.0, "vah": 108.0,
                                     "lvn": [], "hvn": [], "vp_position": "BELOW_VAL"}
            result = self.of._calc_volume_profile("TSLA")
            self.assertEqual(result["vp_position"], "BELOW_VAL")


class TestConfig(unittest.TestCase):
    """配置加载"""

    def test_default_config(self):
        cfg = _load_config()
        self.assertEqual(cfg["phase"], 0)
        self.assertAlmostEqual(cfg["thresholds"]["obi_threshold"], 0.30)
        self.assertAlmostEqual(cfg["thresholds"]["rvol_low"], 0.50)

    def test_config_applied_to_filter(self):
        of = OFFilter()
        self.assertAlmostEqual(of.OBI_THRESHOLD, 0.30)
        self.assertAlmostEqual(of.RVOL_LOW, 0.50)
        self.assertEqual(of.CACHE_TTL_CRYPTO, 30)
        self.assertEqual(of.CACHE_TTL_STOCK, 60)


class TestStateWrite(unittest.TestCase):
    """状态文件写入"""

    def setUp(self):
        self.of = OFFilter()
        self.test_state = Path("state/test_filter_state.json")

    def test_result_has_all_fields(self):
        self.of._get_obi_cvd = lambda s: {"obi": 0.2, "obi_bias": "BUY_PRESSURE",
                                           "cvd": 0, "cvd_bias": "BUY_DOMINANT"}
        self.of._get_rvol = lambda s: 1.5
        self.of._calc_volume_profile = lambda s: {"vp_position": "ABOVE_VAH",
                                                    "poc": 400, "val": 395, "vah": 405}
        self.of._write_state = lambda s, d, r: None

        result = self.of.run("TSLA", "BUY")
        required_keys = {"passed", "volume_score", "micro_go", "blocked_by",
                         "obi", "cvd_bias", "rvol", "vp_position", "poc", "val", "vah",
                         "updated_ts"}
        self.assertTrue(required_keys.issubset(result.keys()),
                        f"Missing keys: {required_keys - result.keys()}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
