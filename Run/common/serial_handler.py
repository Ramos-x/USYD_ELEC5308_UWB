"""
串口通信处理模块

这个模块包含串口通信相关的函数和类：
- 自动搜索串口
- 校准配置管理
- 串口读取器
"""

import json
import os
from typing import Optional, Dict
import serial
import serial.tools.list_ports


def find_serial_port(target_device_name: str = "USB-SERIAL CH340") -> Optional[str]:
    """
    自动搜索包含目标设备名称的串口

    Args:
        target_device_name: 目标设备名称，默认为"USB-SERIAL CH340"

    Returns:
        找到的串口设备路径，如果未找到则返回None

    Example:
        >>> port = find_serial_port()
        >>> if port:
        ...     print(f"找到串口: {port}")
    """
    ports = serial.tools.list_ports.comports()
    target_upper = target_device_name.upper()

    for port in ports:
        # 检查描述和硬件ID
        if target_upper in port.description.upper():
            return port.device
        if port.hwid and target_upper in port.hwid.upper():
            return port.device

    return None


class SerialHandler:
    """串口通信处理器"""

    # 默认配置
    DEFAULT_BAUD = 2000000
    DEFAULT_TIMEOUT = 0.2
    DEFAULT_DEVICE_NAME = "USB-SERIAL CH340"

    def __init__(self, port: Optional[str] = None,
                 baud: int = DEFAULT_BAUD,
                 timeout: float = DEFAULT_TIMEOUT):
        """
        初始化串口处理器

        Args:
            port: 串口设备路径，如果为None则自动搜索
            baud: 波特率，默认2000000
            timeout: 读超时(秒)，默认0.2
        """
        self.port = port
        self.baud = baud
        self.timeout = timeout
        self.serial_conn = None

    def open(self) -> bool:
        """
        打开串口连接

        Returns:
            成功返回True，失败返回False
        """
        try:
            if self.port is None:
                self.port = find_serial_port()
                if self.port is None:
                    return False

            self.serial_conn = serial.Serial(
                port=self.port,
                baudrate=self.baud,
                timeout=self.timeout
            )
            return True

        except Exception:
            return False

    def close(self):
        """关闭串口连接"""
        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.close()

    def read_line(self) -> Optional[str]:
        """
        读取一行数据

        Returns:
            读取的字符串，如果失败则返回None
        """
        if not self.serial_conn or not self.serial_conn.is_open:
            return None

        try:
            line = self.serial_conn.readline()
            return line.decode('utf-8', errors='replace').strip()
        except Exception:
            return None


class CalibrationConfig:
    """UWB校准配置管理器"""

    def __init__(self, config_file: str = "anchor_calibration.json"):
        """
        初始化校准配置管理器

        Args:
            config_file: 配置文件路径
        """
        # 如果是相对路径，使用脚本所在目录
        if not os.path.isabs(config_file):
            script_dir = os.path.dirname(os.path.abspath(__file__))
            config_file = os.path.join(script_dir, "..", config_file)

        self.config_file = config_file
        self.config = self.load()

    def load(self) -> Dict:
        """
        从配置文件加载校准数据

        Returns:
            校准配置字典，如果文件不存在则返回默认值
        """
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"警告：无法加载配置文件 {self.config_file}: {e}")

        # 默认配置（5个锚点）
        return {
            "bias": {str(i): 0.0 for i in range(1, 6)},
            "scale": {str(i): 1.0 for i in range(1, 6)}
        }

    def save(self) -> bool:
        """
        保存校准数据到配置文件

        Returns:
            成功返回True，失败返回False
        """
        try:
            # 确保目录存在
            os.makedirs(os.path.dirname(self.config_file), exist_ok=True)

            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)

            print(f"✓ 校准数据已保存到 {self.config_file}")
            return True

        except Exception as e:
            print(f"错误：无法保存配置文件: {e}")
            return False

    def get_bias(self, anchor_id: int) -> float:
        """
        获取指定锚点的偏置

        Args:
            anchor_id: 锚点ID

        Returns:
            偏置值(米)
        """
        return float(self.config.get("bias", {}).get(str(anchor_id), 0.0))

    def get_scale(self, anchor_id: int) -> float:
        """
        获取指定锚点的缩放系数

        Args:
            anchor_id: 锚点ID

        Returns:
            缩放系数
        """
        return float(self.config.get("scale", {}).get(str(anchor_id), 1.0))

    def set_bias(self, anchor_id: int, bias: float):
        """
        设置指定锚点的偏置

        Args:
            anchor_id: 锚点ID
            bias: 偏置值(米)
        """
        if "bias" not in self.config:
            self.config["bias"] = {}
        self.config["bias"][str(anchor_id)] = bias

    def set_scale(self, anchor_id: int, scale: float):
        """
        设置指定锚点的缩放系数

        Args:
            anchor_id: 锚点ID
            scale: 缩放系数
        """
        if "scale" not in self.config:
            self.config["scale"] = {}
        self.config["scale"][str(anchor_id)] = scale

    def apply_calibration(self, anchor_id: int, raw_distance: float) -> float:
        """
        应用校准到原始距离测量值

        Args:
            anchor_id: 锚点ID
            raw_distance: 原始距离(米)

        Returns:
            校准后的距离(米)
        """
        scale = self.get_scale(anchor_id)
        bias = self.get_bias(anchor_id)
        return raw_distance * scale + bias
