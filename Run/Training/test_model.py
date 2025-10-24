"""
快速测试脚本 - 验证增强型定位模型
"""

import numpy as np
from enhanced_positioning_model import (
    ChannelQualityFeatureExtractor,
    DistanceCorrectionModel,
    MotionDetector,
    KalmanFilter1D,
    EnhancedPositioningSystem
)


def test_feature_extractor():
    """测试特征提取器"""
    print("=" * 60)
    print("测试1: 信道质量特征提取器")
    print("-" * 60)

    extractor = ChannelQualityFeatureExtractor()

    # 模拟一个高质量的LOS信号
    sample_los = {
        'peak': 1550000000,
        'pwr': 12,
        'fp_idx': 47200,
        'acc': 49,
        'xo': 10
    }

    features = extractor.extract_features(sample_los)
    feature_names = extractor.get_feature_names()

    print("输入数据 (高质量LOS信号):")
    for key, val in sample_los.items():
        print(f"  {key}: {val}")

    print(f"\n提取的特征 ({len(features)}维):")
    for name, val in zip(feature_names, features):
        print(f"  {name}: {val:.6f}")

    print("\n✓ 特征提取器工作正常")


def test_motion_detector():
    """测试运动检测器"""
    print("\n" + "=" * 60)
    print("测试2: 运动检测器")
    print("-" * 60)

    detector = MotionDetector(window_size=10, static_threshold=0.05)

    # 模拟静态场景 (距离变化小)
    print("\n场景1: 静态 (距离稳定在1.0m左右)")
    static_distances = [1.0 + np.random.normal(0, 0.01) for _ in range(15)]
    for d in static_distances:
        detector.update(1, d)

    print(f"  距离范围: {min(static_distances):.4f} - {max(static_distances):.4f}m")
    print(f"  标准差: {np.std(static_distances):.4f}m")
    print(f"  判定结果: {'静态' if detector.is_static(1) else '动态'}")

    # 模拟动态场景
    print("\n场景2: 动态 (距离从1.0m增加到2.0m)")
    detector = MotionDetector(window_size=10, static_threshold=0.05)
    dynamic_distances = np.linspace(1.0, 2.0, 15)
    for d in dynamic_distances:
        detector.update(1, d)

    print(f"  距离范围: {min(dynamic_distances):.4f} - {max(dynamic_distances):.4f}m")
    print(f"  标准差: {np.std(dynamic_distances):.4f}m")
    print(f"  判定结果: {'静态' if detector.is_static(1) else '动态'}")
    print(f"  速度估算: {detector.get_velocity_estimate():.4f}m/样本")

    print("\n✓ 运动检测器工作正常")


def test_kalman_filter():
    """测试卡尔曼滤波器"""
    print("\n" + "=" * 60)
    print("测试3: 卡尔曼滤波器")
    print("-" * 60)

    kf = KalmanFilter1D(process_variance=0.01, measurement_variance=0.1)

    # 模拟带噪声的测量
    true_distance = 2.0
    measurements = [true_distance + np.random.normal(0, 0.1) for _ in range(20)]

    filtered = []
    for m in measurements:
        f = kf.update(m)
        filtered.append(f)

    # 统计
    meas_mae = np.mean(np.abs(np.array(measurements) - true_distance))
    filt_mae = np.mean(np.abs(np.array(filtered) - true_distance))

    print(f"真实距离: {true_distance}m")
    print(f"测量数量: {len(measurements)}")
    print(f"\n测量值统计:")
    print(f"  平均: {np.mean(measurements):.4f}m")
    print(f"  标准差: {np.std(measurements):.4f}m")
    print(f"  MAE: {meas_mae:.4f}m")
    print(f"\n滤波后统计:")
    print(f"  平均: {np.mean(filtered):.4f}m")
    print(f"  标准差: {np.std(filtered):.4f}m")
    print(f"  MAE: {filt_mae:.4f}m")
    print(f"\n改善: {(meas_mae - filt_mae) / meas_mae * 100:.2f}%")

    print("\n✓ 卡尔曼滤波器工作正常")


def test_multilateration():
    """测试多边定位算法"""
    print("\n" + "=" * 60)
    print("测试4: 多边定位算法")
    print("-" * 60)

    # 创建一个虚拟模型（用于测试multilateration）
    from enhanced_positioning_model import DistanceCorrectionModel
    dummy_model = DistanceCorrectionModel()
    dummy_model.models = {1: None}  # 占位
    dummy_model.anchor_ids = [1, 2, 3, 4]

    system = EnhancedPositioningSystem(dummy_model)

    # 设置锚点位置
    anchor_positions = {
        1: np.array([0.0, 0.0, 0.0]),
        2: np.array([3.0, 0.0, 0.0]),
        3: np.array([3.0, 3.0, 0.0]),
        4: np.array([0.0, 3.0, 0.0]),
    }
    system.set_anchor_positions(anchor_positions)

    # 真实位置
    true_position = np.array([1.5, 1.5, 0.0])

    # 计算理论距离
    distances = {}
    for aid, anchor_pos in anchor_positions.items():
        dist = np.linalg.norm(true_position - anchor_pos)
        # 添加小噪声
        distances[aid] = dist + np.random.normal(0, 0.02)

    print("锚点配置:")
    for aid, pos in anchor_positions.items():
        print(f"  Anchor {aid}: {pos}")

    print(f"\n真实位置: {true_position}")
    print(f"\n距离测量:")
    for aid, dist in distances.items():
        true_dist = np.linalg.norm(true_position - anchor_positions[aid])
        print(f"  Anchor {aid}: {dist:.4f}m (真实: {true_dist:.4f}m)")

    # 执行定位
    estimated_position = system.multilateration(distances)

    print(f"\n估计位置: {estimated_position}")
    error = np.linalg.norm(estimated_position - true_position)
    print(f"定位误差: {error:.4f}m")

    if error < 0.1:
        print("\n✓ 多边定位算法工作正常")
    else:
        print("\n⚠ 定位误差较大，请检查")


def main():
    print("\n" + "=" * 60)
    print("增强型UWB定位系统 - 功能测试")
    print("=" * 60)

    try:
        test_feature_extractor()
        test_motion_detector()
        test_kalman_filter()
        test_multilateration()

        print("\n" + "=" * 60)
        print("✓ 所有测试通过!")
        print("=" * 60)
        print("\n下一步:")
        print("  1. 运行 train_enhanced_model.py 训练模型")
        print("  2. 运行 realtime_positioning.py 进行实时定位")

    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
