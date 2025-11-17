"""
配置管理模块
提供统一的配置加载和管理功能
"""

import json
import os
import yaml
from typing import Dict, Tuple, List, Optional, Any

# 获取配置文件目录
CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
ANCHOR_CONFIG_FILE = os.path.join(CONFIG_DIR, 'anchor_config.json')
SYSTEM_CONFIG_FILE = os.path.join(CONFIG_DIR, 'system_config.yaml')


class ConfigManager:
    """配置管理器"""

    def __init__(self, anchor_config_file: Optional[str] = None,
                 system_config_file: Optional[str] = None):
        """
        初始化配置管理器

        Args:
            anchor_config_file: 锚点配置文件路径，默认使用anchor_config.json
            system_config_file: 系统配置文件路径，默认使用system_config.yaml
        """
        self.anchor_config_file = anchor_config_file or ANCHOR_CONFIG_FILE
        self.system_config_file = system_config_file or SYSTEM_CONFIG_FILE
        self._anchor_config = None
        self._system_config = None
        self.load_configs()

    def load_configs(self):
        """加载所有配置文件"""
        # 加载锚点配置（JSON）
        try:
            with open(self.anchor_config_file, 'r', encoding='utf-8') as f:
                self._anchor_config = json.load(f)
        except FileNotFoundError:
            raise FileNotFoundError(f"锚点配置文件不存在: {self.anchor_config_file}")
        except json.JSONDecodeError as e:
            raise ValueError(f"锚点配置文件格式错误: {e}")

        # 加载系统配置（YAML）
        try:
            if os.path.exists(self.system_config_file):
                with open(self.system_config_file, 'r', encoding='utf-8') as f:
                    self._system_config = yaml.safe_load(f) or {}
            else:
                # 使用默认系统配置
                self._system_config = self._get_default_system_config()
        except yaml.YAMLError as e:
            raise ValueError(f"系统配置文件格式错误: {e}")

    def _get_default_system_config(self) -> Dict[str, Any]:
        """获取默认系统配置"""
        return {
            'serial': {
                'baud': 2000000,
                'timeout': 0.2,
                'device_name': 'USB-SERIAL CH340'
            },
            'processing': {
                'median_window': 5,
                'ema_alpha': 0.3,
                'outlier_k': 3.0,
                'noise_window': 10
            },
            'positioning': {
                'max_iterations': 20,
                'convergence_threshold': 0.001,
                'initial_step': 0.5
            },
            'logging': {
                'level': 'INFO',
                'console_output': True,
                'file_output': True
            }
        }

    def load_config(self):
        """兼容旧的load_config方法"""
        self.load_configs()
        # 兼容旧代码，设置_config指向锚点配置
        self._config = self._anchor_config

    @property
    def anchor_positions(self) -> Dict[int, Tuple[float, float, float]]:
        """
        获取锚点坐标字典

        Returns:
            {anchor_id: (x, y, z)}
        """
        if not self._anchor_config:
            self.load_configs()

        return {
            int(k): (v['x'], v['y'], v['z'])
            for k, v in self._anchor_config['anchors'].items()
        }

    @property
    def anchor_positions_list(self) -> List[List[float]]:
        """
        获取锚点坐标列表（用于numpy数组）

        Returns:
            [[x1, y1, z1], [x2, y2, z2], ...]
        """
        positions = self.anchor_positions
        return [list(positions[i]) for i in sorted(positions.keys())]

    @property
    def input_anchors(self) -> List[int]:
        """获取输入锚点ID列表"""
        return self._anchor_config.get('input_anchors', [1, 2, 3, 4, 5])

    @property
    def output_anchors(self) -> List[int]:
        """获取输出锚点ID列表"""
        return self._anchor_config.get('output_anchors', [1, 2, 3, 4, 5])

    @property
    def min_anchors_for_3d(self) -> int:
        """获取3D定位所需的最小锚点数量"""
        return self._anchor_config.get('min_anchors_for_3d', 4)

    @property
    def position_bounds(self) -> Dict[str, Tuple[float, float]]:
        """
        获取位置边界

        Returns:
            {'x': (min, max), 'y': (min, max), 'z': (min, max)}
        """
        bounds = self._anchor_config.get('position_bounds', {})
        return {
            'x': tuple(bounds.get('x', [-1.0, 5.0])),
            'y': tuple(bounds.get('y', [-1.0, 5.0])),
            'z': tuple(bounds.get('z', [-1.0, 3.5]))
        }

    def get_anchor_info(self, anchor_id: int) -> Dict:
        """
        获取指定锚点的完整信息

        Args:
            anchor_id: 锚点ID

        Returns:
            锚点信息字典
        """
        return self._anchor_config['anchors'].get(str(anchor_id), {})

    # ==================== 新增：系统配置访问方法 ====================

    @property
    def serial_config(self) -> Dict[str, Any]:
        """
        获取串口配置

        Returns:
            串口配置字典，包含：
            - baud: 波特率
            - timeout: 超时时间（秒）
            - device_name: 设备名称
        """
        return self._system_config.get('serial', {
            'baud': 2000000,
            'timeout': 0.2,
            'device_name': 'USB-SERIAL CH340'
        })

    @property
    def processing_config(self) -> Dict[str, Any]:
        """
        获取数据处理配置

        Returns:
            处理配置字典，包含：
            - median_window: 中值滤波窗口大小
            - ema_alpha: 指数滑动平均系数
            - outlier_k: 离群点检测阈值（k倍标准差）
            - noise_window: 噪声估计窗口大小
        """
        return self._system_config.get('processing', {
            'median_window': 5,
            'ema_alpha': 0.3,
            'outlier_k': 3.0,
            'noise_window': 10
        })

    @property
    def positioning_config(self) -> Dict[str, Any]:
        """
        获取定位算法配置

        Returns:
            定位配置字典，包含：
            - max_iterations: 最大迭代次数
            - convergence_threshold: 收敛阈值
            - initial_step: 初始步长
        """
        return self._system_config.get('positioning', {
            'max_iterations': 20,
            'convergence_threshold': 0.001,
            'initial_step': 0.5
        })

    @property
    def logging_config(self) -> Dict[str, Any]:
        """
        获取日志配置

        Returns:
            日志配置字典，包含：
            - level: 日志级别
            - console_output: 是否输出到控制台
            - file_output: 是否输出到文件
        """
        return self._system_config.get('logging', {
            'level': 'INFO',
            'console_output': True,
            'file_output': True
        })


# 全局配置管理器实例
_global_config = None


def get_config() -> ConfigManager:
    """
    获取全局配置管理器实例（单例模式）

    Returns:
        ConfigManager实例
    """
    global _global_config
    if _global_config is None:
        _global_config = ConfigManager()
    return _global_config


# 便捷函数
def get_anchor_positions() -> Dict[int, Tuple[float, float, float]]:
    """获取锚点坐标字典"""
    return get_config().anchor_positions


def get_anchor_positions_list() -> List[List[float]]:
    """获取锚点坐标列表"""
    return get_config().anchor_positions_list


def get_input_anchors() -> List[int]:
    """获取输入锚点ID列表"""
    return get_config().input_anchors


def get_output_anchors() -> List[int]:
    """获取输出锚点ID列表"""
    return get_config().output_anchors
