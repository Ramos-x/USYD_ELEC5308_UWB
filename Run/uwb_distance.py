"""
UWB距离计算模块
提供统一的DS-TWR距离计算功能
"""

from typing import Dict, Any, Optional


class DistanceCalculator:
    """UWB DS-TWR距离计算器"""

    # 物理常量
    SPEED_OF_LIGHT = 299_702_547.0  # m/s (更精确的值)
    SPEED_OF_LIGHT_ALTERNATIVE = 299_792_458.0  # m/s (标准值)

    # DW1000时间单位
    DWT_TIME_UNITS = 1.0 / (499.2e6 * 128.0)  # ≈ 15.65e-12 s

    # 40位时间戳掩码
    MASK40 = (1 << 40) - 1

    def __init__(self, speed_of_light: Optional[float] = None):
        """
        初始化距离计算器

        Args:
            speed_of_light: 光速值（m/s），默认使用SPEED_OF_LIGHT
        """
        self.speed_of_light = speed_of_light or self.SPEED_OF_LIGHT

    @staticmethod
    def hex5_to_u40(hex_str: str) -> int:
        """
        将5字节十六进制字符串转换为40位无符号整数

        Args:
            hex_str: 10位十六进制字符串（如"0A1B2C3D4E"）

        Returns:
            40位无符号整数
        """
        return int(hex_str, 16) & DistanceCalculator.MASK40

    @staticmethod
    def rel40(newer: int, older: int) -> int:
        """
        计算40位时间戳的差值（处理回绕）

        Args:
            newer: 较新的时间戳
            older: 较旧的时间戳

        Returns:
            时间差值
        """
        return (newer - older) & DistanceCalculator.MASK40

    def compute_distance(self, extended_data: Dict[str, Any]) -> Optional[float]:
        """
        使用非对称DS-TWR公式计算距离

        双边双向测距（Double-Sided Two-Way Ranging）公式：
        ToF = (Tround1 * Tround2 - Treply1 * Treply2) / (Tround1 + Tround2 + Treply1 + Treply2)
        Distance = ToF * DWT_TIME_UNITS * SPEED_OF_LIGHT

        Args:
            extended_data: 包含时间戳的字典，需要以下字段：
                - tx1: Tag第一次发送
                - rx1: Anchor接收tx1
                - tx2: Anchor回复
                - rx2: Tag接收tx2
                - tx3r/tx3p: Tag第三次发送（优先tx3r）
                - rx3: Anchor接收tx3

        Returns:
            距离（米），如果数据无效则返回None
        """
        if not isinstance(extended_data, dict):
            return None

        # tx3优先使用实际发送时间tx3r，如果不存在则使用tx3p
        tx3_hex = extended_data.get("tx3r", "0000000000")
        if not self._is_valid_hex(tx3_hex):
            tx3_hex = extended_data.get("tx3p", "0000000000")

        # 验证所有必需字段
        required_keys = ("tx1", "rx1", "tx2", "rx2", "rx3")
        for key in required_keys:
            value = extended_data.get(key, "0000000000")
            if not self._is_valid_hex(value):
                return None

        if not self._is_valid_hex(tx3_hex):
            return None

        # 转换时间戳
        try:
            tx1 = self.hex5_to_u40(extended_data["tx1"])  # Tag发送时刻
            rx1_anchor = self.hex5_to_u40(extended_data["rx1"])  # Anchor接收tx1时刻
            tx2_anchor = self.hex5_to_u40(extended_data["tx2"])  # Anchor回复时刻
            rx2 = self.hex5_to_u40(extended_data["rx2"])  # Tag接收tx2时刻
            tx3 = self.hex5_to_u40(tx3_hex)  # Tag第三次发送时刻
            rx3_anchor = self.hex5_to_u40(extended_data["rx3"])  # Anchor接收tx3时刻
        except (ValueError, KeyError):
            return None

        # 计算时间差（处理回绕）
        tround1 = self.rel40(rx2, tx1)  # Tag端：TX1 -> RX2
        treply2 = self.rel40(tx3, rx2)  # Tag端：RX2 -> TX3
        treply1 = self.rel40(tx2_anchor, rx1_anchor)  # Anchor端：RX1 -> TX2
        tround2 = self.rel40(rx3_anchor, tx2_anchor)  # Anchor端：TX2 -> RX3

        # 验证时间差的有效性
        if not all(t > 0 for t in [tround1, treply2, treply1, tround2]):
            return None

        # DS-TWR公式
        numerator = tround1 * tround2 - treply1 * treply2
        denominator = tround1 + tround2 + treply1 + treply2

        if denominator <= 0 or numerator <= 0:
            return None

        # 计算飞行时间（秒）
        tof_seconds = (numerator / denominator) * self.DWT_TIME_UNITS

        # 计算距离（米）
        distance_meters = tof_seconds * self.speed_of_light

        return distance_meters

    @staticmethod
    def _is_valid_hex(hex_str: str) -> bool:
        """
        验证十六进制字符串是否有效

        Args:
            hex_str: 待验证的字符串

        Returns:
            是否有效
        """
        return (
            isinstance(hex_str, str) and
            len(hex_str) == 10 and
            hex_str != "0000000000"
        )


# 便捷函数
def compute_distance_m(extended_data: Dict[str, Any]) -> Optional[float]:
    """
    计算UWB距离的便捷函数

    Args:
        extended_data: 包含时间戳的字典

    Returns:
        距离（米），如果数据无效则返回None
    """
    calculator = DistanceCalculator()
    return calculator.compute_distance(extended_data)


# 为了向后兼容，提供旧的函数名
def hex5_to_u40(hex_str: str) -> int:
    """向后兼容的函数"""
    return DistanceCalculator.hex5_to_u40(hex_str)


def rel40(newer: int, older: int) -> int:
    """向后兼容的函数"""
    return DistanceCalculator.rel40(newer, older)
