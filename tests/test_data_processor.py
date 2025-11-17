"""
数据预处理器测试

测试Run/common/data_processor.py中的LinkPreprocessor
"""

import pytest
from Run.common.data_processor import LinkPreprocessor


class TestLinkPreprocessor:
    """测试LinkPreprocessor类"""

    def test_initialization(self):
        """测试初始化"""
        preprocessor = LinkPreprocessor()
        assert preprocessor.median_win == 5
        assert preprocessor.ema_alpha == 0.3
        assert preprocessor.outlier_k == 3.0
        assert preprocessor.noise_win == 10

    def test_custom_parameters(self):
        """测试自定义参数"""
        preprocessor = LinkPreprocessor(
            median_win=7,
            ema_alpha=0.5,
            outlier_k=2.5,
            noise_win=15
        )
        assert preprocessor.median_win == 7
        assert preprocessor.ema_alpha == 0.5
        assert preprocessor.outlier_k == 2.5
        assert preprocessor.noise_win == 15

    def test_process_single_value(self):
        """测试处理单个值"""
        preprocessor = LinkPreprocessor()
        value, noise = preprocessor.process(3.0)
        assert isinstance(value, float)
        assert isinstance(noise, float)
        assert value == 3.0  # 第一个值应该直接返回

    def test_process_multiple_values(self):
        """测试处理多个值"""
        preprocessor = LinkPreprocessor()
        values = [3.0, 3.1, 2.9, 3.0, 3.2]

        for v in values:
            filtered, noise = preprocessor.process(v)
            assert isinstance(filtered, float)
            assert isinstance(noise, float)

    def test_outlier_detection(self):
        """测试离群点检测"""
        preprocessor = LinkPreprocessor(outlier_k=2.0)

        # 输入正常值
        for _ in range(10):
            preprocessor.process(3.0)

        # 输入离群点
        filtered, _ = preprocessor.process(10.0)

        # 离群点应该被过滤掉，不会是10.0
        assert abs(filtered - 10.0) > 1.0

    def test_ema_smoothing(self):
        """测试EMA平滑"""
        preprocessor = LinkPreprocessor(ema_alpha=0.5)

        # 输入稳定值
        for _ in range(5):
            preprocessor.process(3.0)

        # 输入新值
        filtered, _ = preprocessor.process(5.0)

        # EMA应该在3.0和5.0之间
        assert 3.0 < filtered < 5.0

    def test_reset(self):
        """测试重置功能"""
        preprocessor = LinkPreprocessor()

        # 处理一些数据
        for i in range(10):
            preprocessor.process(float(i))

        # 重置
        preprocessor.reset()

        # 检查状态已重置
        assert len(preprocessor.history) == 0
        assert preprocessor.ema_value is None
        assert preprocessor.noise_sigma == 0.1

    def test_get_statistics(self):
        """测试获取统计信息"""
        preprocessor = LinkPreprocessor()

        # 处理一些数据
        for i in range(10):
            preprocessor.process(float(i))

        stats = preprocessor.get_statistics()

        assert 'ema_value' in stats
        assert 'noise_sigma' in stats
        assert 'history_size' in stats
        assert 'median_win' in stats
        assert 'ema_alpha' in stats
        assert 'outlier_k' in stats

        assert stats['history_size'] > 0
        assert stats['median_win'] == 5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
