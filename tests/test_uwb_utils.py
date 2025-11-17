"""
UWB工具函数测试

测试Run/common/uwb_utils.py中的工具函数
"""

import pytest
from Run.common.uwb_utils import UWBUtils, UWBConstants, strip_ansi


class TestUWBConstants:
    """测试UWB物理常量"""

    def test_speed_of_light(self):
        """测试光速常量"""
        assert UWBConstants.SPEED_OF_LIGHT == 299_702_547.0

    def test_dwt_time_units(self):
        """测试DW1000时间单位"""
        expected = 1.0 / (499.2e6 * 128.0)
        assert abs(UWBConstants.DWT_TIME_UNITS - expected) < 1e-15

    def test_mask40(self):
        """测试40-bit掩码"""
        assert UWBConstants.MASK40 == (1 << 40) - 1
        assert UWBConstants.MASK40 == 0xFFFFFFFFFF


class TestUWBUtils:
    """测试UWB工具函数"""

    def test_hex5_to_u40_basic(self):
        """测试基本的十六进制转换"""
        result = UWBUtils.hex5_to_u40("0000000001")
        assert result == 1

        result = UWBUtils.hex5_to_u40("00000000FF")
        assert result == 255

    def test_hex5_to_u40_large_value(self):
        """测试大值转换"""
        result = UWBUtils.hex5_to_u40("FFFFFFFFFF")
        assert result == (1 << 40) - 1

    def test_rel40_no_wrap(self):
        """测试无回绕的差值计算"""
        newer = 1000
        older = 500
        result = UWBUtils.rel40(newer, older)
        assert result == 500

    def test_rel40_with_wrap(self):
        """测试回绕情况的差值计算"""
        mask40 = (1 << 40) - 1
        newer = 10
        older = mask40 - 10
        result = UWBUtils.rel40(newer, older)
        # newer - older = 10 - (2^40 - 11) = 21 (mod 2^40)
        assert result == 21

    def test_tof_to_distance(self):
        """测试ToF到距离的转换"""
        # 1米的飞行时间
        tof = 1.0 / UWBConstants.SPEED_OF_LIGHT
        distance = UWBUtils.tof_to_distance(tof)
        assert abs(distance - 1.0) < 1e-6

    def test_compute_tof_seconds_valid(self):
        """测试有效的ToF计算"""
        # 简单的测试用例
        tx1, rx1 = 1000, 2000
        tx2, rx2 = 3000, 4000
        tx3, rx3 = 5000, 6000

        tof = UWBUtils.compute_tof_seconds(tx1, rx1, tx2, rx2, tx3, rx3)
        assert tof is not None
        assert tof > 0

    def test_compute_tof_seconds_invalid(self):
        """测试无效输入"""
        # 所有时间戳相同会导致分母为0
        tx1 = rx1 = tx2 = rx2 = tx3 = rx3 = 1000
        tof = UWBUtils.compute_tof_seconds(tx1, rx1, tx2, rx2, tx3, rx3)
        assert tof is None


class TestStripAnsi:
    """测试ANSI转义序列过滤"""

    def test_strip_ansi_no_escape(self):
        """测试无转义序列的字符串"""
        text = "Hello World"
        result = strip_ansi(text)
        assert result == "Hello World"

    def test_strip_ansi_with_color(self):
        """测试包含颜色代码的字符串"""
        text = "\x1b[31mRed Text\x1b[0m"
        result = strip_ansi(text)
        assert result == "Red Text"

    def test_strip_ansi_multiple_codes(self):
        """测试多个转义序列"""
        text = "\x1b[1m\x1b[31mBold Red\x1b[0m Normal"
        result = strip_ansi(text)
        assert result == "Bold Red Normal"

    def test_strip_ansi_empty_string(self):
        """测试空字符串"""
        result = strip_ansi("")
        assert result == ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
