"""
UWB工具函数和常量

这个模块包含UWB定位系统中常用的工具函数和物理常量。
所有这些函数之前在多个文件中重复定义，现在统一到这里。
"""

import re
from typing import Optional


class UWBConstants:
    """UWB系统物理常量"""

    # 光速 (m/s) - 与固件一致
    SPEED_OF_LIGHT = 299_702_547.0

    # DW1000时间单位转换
    DWT_TIME_UNITS = 1.0 / (499.2e6 * 128.0)

    # 40-bit时间戳掩码
    MASK40 = (1 << 40) - 1

    # 64-bit时间戳掩码
    MASK64 = (1 << 64) - 1


class UWBUtils:
    """UWB工具函数集合"""

    @staticmethod
    def hex5_to_u40(h: str) -> int:
        """
        将10位十六进制字符串（高位在前）转换为40-bit无符号整数

        Args:
            h: 10位十六进制字符串，例如 "0A1B2C3D4E"

        Returns:
            40-bit无符号整数

        Example:
            >>> UWBUtils.hex5_to_u40("0A1B2C3D4E")
            43530798926
        """
        return int(h, 16) & UWBConstants.MASK40

    @staticmethod
    def rel40(newer: int, older: int) -> int:
        """
        计算40-bit时间戳的回绕安全差值 (newer - older)

        由于40-bit时间戳会回绕，直接相减可能产生错误结果。
        这个函数处理了回绕情况。

        Args:
            newer: 较新的时间戳
            older: 较旧的时间戳

        Returns:
            两个时间戳的差值

        Example:
            >>> UWBUtils.rel40(100, 50)
            50
            >>> UWBUtils.rel40(10, (1 << 40) - 10)  # 处理回绕
            20
        """
        return (newer - older) & UWBConstants.MASK40

    @staticmethod
    def rel64(newer: int, older: int) -> int:
        """
        计算64-bit时间戳的回绕安全差值 (newer - older)

        Args:
            newer: 较新的时间戳
            older: 较旧的时间戳

        Returns:
            两个时间戳的差值
        """
        return (newer - older) & UWBConstants.MASK64

    @staticmethod
    def compute_tof_seconds(tx1: int, rx1: int, tx2: int, rx2: int,
                           tx3: int, rx3: int) -> Optional[float]:
        """
        使用DS-TWR公式计算飞行时间(ToF)

        DS-TWR (Double-Sided Two-Way Ranging) 公式：
        ToF = (tRound1 * tRound2 - tReply1 * tReply2) /
              (tRound1 + tRound2 + tReply1 + tReply2)

        其中：
        - tRound1 = rx1 - tx1 (Anchor收到POLL相对Tag发送POLL的时间)
        - tRound2 = rx3 - tx2 (Tag收到FACK相对Anchor发送RESP的时间)
        - tReply1 = tx2 - rx1 (Anchor发送RESP相对收到POLL的时间)
        - tReply2 = tx3 - rx2 (Tag发送FINAL相对收到RESP的时间)

        Args:
            tx1: Tag发送POLL的时间
            rx1: Anchor收到POLL的时间
            tx2: Anchor发送RESP的时间
            rx2: Tag收到RESP的时间
            tx3: Tag发送FINAL的时间
            rx3: Anchor收到FINAL的时间

        Returns:
            飞行时间(秒)，如果计算失败则返回None
        """
        try:
            # 计算各个时间间隔
            tRound1 = UWBUtils.rel40(rx1, tx1)
            tReply1 = UWBUtils.rel40(tx2, rx1)
            tRound2 = UWBUtils.rel40(rx3, tx2)
            tReply2 = UWBUtils.rel40(tx3, rx2)

            # DS-TWR公式
            numerator = tRound1 * tRound2 - tReply1 * tReply2
            denominator = tRound1 + tRound2 + tReply1 + tReply2

            if denominator == 0:
                return None

            tof_dtu = numerator / denominator
            tof_seconds = tof_dtu * UWBConstants.DWT_TIME_UNITS

            return tof_seconds

        except (ValueError, ZeroDivisionError):
            return None

    @staticmethod
    def tof_to_distance(tof_seconds: float) -> float:
        """
        将飞行时间转换为距离

        Args:
            tof_seconds: 飞行时间(秒)

        Returns:
            距离(米)
        """
        return tof_seconds * UWBConstants.SPEED_OF_LIGHT


# ANSI转义序列正则表达式
ANSI_RE = re.compile(r'\x1B\[[0-9;?]*[ -/]*[@-~]')


def strip_ansi(s: str) -> str:
    """
    过滤ANSI/CSI控制序列

    移除字符串中的ANSI转义序列（例如 \\x1b[...），
    避免污染日志/JSON解析。

    Args:
        s: 包含ANSI转义序列的字符串

    Returns:
        移除转义序列后的干净字符串

    Example:
        >>> strip_ansi("\\x1b[31mRed Text\\x1b[0m")
        "Red Text"
    """
    return ANSI_RE.sub('', s)
