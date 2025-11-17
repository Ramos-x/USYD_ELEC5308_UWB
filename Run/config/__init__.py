"""
配置管理模块
提供统一的配置加载和管理功能
"""

import json
import os
from typing import Dict, Tuple, List, Optional

# 获取配置文件目录
CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
ANCHOR_CONFIG_FILE = os.path.join(CONFIG_DIR, 'anchor_config.json')


class ConfigManager:
    """配置管理器"""

    def __init__(self, config_file: Optional[str] = None):
        """
        初始化配置管理器

        Args:
            config_file: 配置文件路径，默认使用anchor_config.json
        """
        self.config_file = config_file or ANCHOR_CONFIG_FILE
        self._config = None
        self.load_config()

    def load_config(self):
        """加载配置文件"""
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                self._config = json.load(f)
        except FileNotFoundError:
            raise FileNotFoundError(f"配置文件不存在: {self.config_file}")
        except json.JSONDecodeError as e:
            raise ValueError(f"配置文件格式错误: {e}")

    @property
    def anchor_positions(self) -> Dict[int, Tuple[float, float, float]]:
        """
        获取锚点坐标字典

        Returns:
            {anchor_id: (x, y, z)}
        """
        if not self._config:
            self.load_config()

        return {
            int(k): (v['x'], v['y'], v['z'])
            for k, v in self._config['anchors'].items()
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
        return self._config.get('input_anchors', [1, 2, 3, 4, 5])

    @property
    def output_anchors(self) -> List[int]:
        """获取输出锚点ID列表"""
        return self._config.get('output_anchors', [1, 2, 3, 4, 5])

    @property
    def min_anchors_for_3d(self) -> int:
        """获取3D定位所需的最小锚点数量"""
        return self._config.get('min_anchors_for_3d', 4)

    @property
    def position_bounds(self) -> Dict[str, Tuple[float, float]]:
        """
        获取位置边界

        Returns:
            {'x': (min, max), 'y': (min, max), 'z': (min, max)}
        """
        bounds = self._config.get('position_bounds', {})
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
        return self._config['anchors'].get(str(anchor_id), {})


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
