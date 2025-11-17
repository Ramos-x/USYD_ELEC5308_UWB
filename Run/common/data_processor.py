"""
数据预处理模块

这个模块包含UWB距离数据的预处理器：
- LinkPreprocessor: 单条距离链路的预处理器
  - 中值滤波（去尖峰）
  - 离群检测与处理（基于k·σ）
  - 指数滑动平均EMA（抑制抖动）
  - 噪声估计（σ，用于后续融合权重）
"""

from collections import deque
from typing import Tuple


class LinkPreprocessor:
    """
    单条距离链路的预处理器

    功能：
    1. 中值滤波（去尖峰）
    2. 离群检测与处理（基于k·σ）
    3. 指数滑动平均EMA（抑制抖动）
    4. 噪声估计（σ，用于后续融合权重）

    使用示例:
        >>> preprocessor = LinkPreprocessor()
        >>> for raw_value in raw_distances:
        ...     filtered_value, noise = preprocessor.process(raw_value)
        ...     print(f"原始: {raw_value:.3f}, 过滤后: {filtered_value:.3f}, 噪声σ: {noise:.3f}")
    """

    # 默认参数
    DEFAULT_MEDIAN_WIN = 5       # 中值滤波窗口大小（奇数，3-5）
    DEFAULT_EMA_ALPHA = 0.3      # 指数滑动平均系数（0.2-0.4，越大越跟随当前值）
    DEFAULT_OUTLIER_K = 3.0      # 离群门限倍数（k·σ，通常2-3）
    DEFAULT_NOISE_WIN = 10       # 噪声估计窗口大小

    def __init__(self,
                 median_win: int = DEFAULT_MEDIAN_WIN,
                 ema_alpha: float = DEFAULT_EMA_ALPHA,
                 outlier_k: float = DEFAULT_OUTLIER_K,
                 noise_win: int = DEFAULT_NOISE_WIN):
        """
        初始化预处理器

        Args:
            median_win: 中值滤波窗口大小（推荐3-5的奇数）
            ema_alpha: EMA平滑系数（0-1，越大越跟随当前值，推荐0.2-0.4）
            outlier_k: 离群点检测阈值（k倍标准差，推荐2-3）
            noise_win: 噪声估计窗口大小（推荐10-20）
        """
        self.median_win = median_win
        self.ema_alpha = ema_alpha
        self.outlier_k = outlier_k
        self.noise_win = noise_win

        # 历史窗口（用于中值和噪声估计）
        self.history = deque(maxlen=max(median_win, noise_win))

        # EMA状态
        self.ema_value = None

        # 噪声估计（标准差）
        self.noise_sigma = 0.1  # 初始值：10cm

    def process(self, raw_value: float) -> Tuple[float, float]:
        """
        处理单个原始测量值

        处理流程：
        1. 添加到历史窗口
        2. 中值滤波
        3. 估计噪声（MAD - 中位绝对偏差）
        4. 离群检测与处理
        5. 指数滑动平均EMA

        Args:
            raw_value: 原始距离测量值(米)

        Returns:
            (过滤后的值, 噪声σ) 的元组
        """
        # 步骤1：添加到历史窗口
        self.history.append(raw_value)

        # 数据不足时，直接返回
        if len(self.history) < 3:
            self.ema_value = raw_value
            return raw_value, self.noise_sigma

        # 步骤2：中值滤波
        history_list = list(self.history)
        median_window = history_list[-self.median_win:] if len(history_list) >= self.median_win else history_list
        median_val = sorted(median_window)[len(median_window) // 2]

        # 步骤3：估计噪声（MAD - 中位绝对偏差）
        if len(self.history) >= self.noise_win:
            noise_window = history_list[-self.noise_win:]
            median_noise = sorted(noise_window)[len(noise_window) // 2]

            # MAD = median(|xi - median|)
            mad = sorted([abs(x - median_noise) for x in noise_window])[len(noise_window) // 2]

            # σ ≈ 1.4826 * MAD（正态分布假设）
            self.noise_sigma = max(1.4826 * mad, 0.01)  # 最小1cm避免除零

        # 步骤4：离群检测与处理
        # 如果 |当前值 - 中值| > k·σ，用中值替换
        if abs(raw_value - median_val) > self.outlier_k * self.noise_sigma:
            # 检测到离群点，用中值替换
            filtered_value = median_val
        else:
            # 正常值
            filtered_value = raw_value

        # 步骤5：指数滑动平均EMA
        if self.ema_value is None:
            self.ema_value = filtered_value
        else:
            self.ema_value = self.ema_alpha * filtered_value + (1 - self.ema_alpha) * self.ema_value

        return self.ema_value, self.noise_sigma

    def reset(self):
        """重置预处理器状态"""
        self.history.clear()
        self.ema_value = None
        self.noise_sigma = 0.1

    def get_statistics(self) -> dict:
        """
        获取当前统计信息

        Returns:
            包含EMA值、噪声σ、历史窗口大小的字典
        """
        return {
            'ema_value': self.ema_value,
            'noise_sigma': self.noise_sigma,
            'history_size': len(self.history),
            'median_win': self.median_win,
            'ema_alpha': self.ema_alpha,
            'outlier_k': self.outlier_k
        }
