"""
增强型UWB定位系统 - 基于信道质量参数的距离校正和动静态识别
作者：Claude Code
日期：2025

核心功能：
1. 基于信道质量参数的距离校正（使用机器学习）
2. 动态/静态场景识别
3. 卡尔曼滤波器用于动态定位
4. 多边定位算法
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
import pickle
import warnings
warnings.filterwarnings('ignore')


class ChannelQualityFeatureExtractor:
    """信道质量特征提取器"""

    def __init__(self):
        self.feature_names = []

    def extract_features(self, data_row):
        """
        从单个anchor的数据中提取特征
        参数对应bu03.c中的rxq结构：
        - peak: ipatovPeak (峰值索引/幅度)
        - pwr: ipatovPower (信道功率面积)
        - fp_idx: ipatovFpIndex (首径索引)
        - acc: ipatovAccumCount (累计符号数)
        - xo: xtalOffset (晶振偏移)
        """
        features = []

        # 基础信道质量参数
        peak = data_row['peak']
        pwr = data_row['pwr']
        fp_idx = data_row['fp_idx']
        acc = data_row['acc']
        xo = data_row['xo']

        # 1. 原始特征
        features.append(peak)
        features.append(pwr)
        features.append(fp_idx)
        features.append(acc)
        features.append(xo)

        # 2. 信号强度指示器 (SNR-like)
        if acc > 0:
            # 峰值功率与累积符号数的比值
            snr_estimate = peak / acc
            features.append(snr_estimate)
        else:
            features.append(0)

        # 3. 信道功率归一化
        if acc > 0:
            normalized_power = pwr / acc
            features.append(normalized_power)
        else:
            features.append(0)

        # 4. 首径质量指标 (First Path Quality)
        # 首径索引越小通常表示LOS(视距)条件越好
        features.append(fp_idx)

        # 5. 峰值与功率比 (Peak to Power Ratio)
        if pwr > 0:
            peak_to_power_ratio = peak / pwr
            features.append(peak_to_power_ratio)
        else:
            features.append(0)

        # 6. 晶振偏移的绝对值（影响时钟同步）
        features.append(abs(xo))

        # 7. 复合质量指标
        # 高SNR + 低首径索引 = 高质量LOS信号
        if acc > 0 and fp_idx > 0:
            quality_score = (peak / acc) / (fp_idx + 1)
            features.append(quality_score)
        else:
            features.append(0)

        return np.array(features)

    def get_feature_names(self):
        return [
            'peak', 'pwr', 'fp_idx', 'acc', 'xo',
            'snr_estimate', 'normalized_power', 'fp_idx_quality',
            'peak_to_power_ratio', 'abs_xo', 'composite_quality'
        ]


class DistanceCorrectionModel:
    """距离校正模型 - 使用信道质量参数进行ML校正"""

    def __init__(self, model_type='gradient_boosting'):
        self.model_type = model_type
        self.models = {}  # 每个anchor一个模型
        self.scalers = {}  # 每个anchor一个归一化器
        self.feature_extractor = ChannelQualityFeatureExtractor()
        self.anchor_ids = []

    def load_training_data(self, csv_files, true_distances):
        """
        加载训练数据

        参数:
            csv_files: list of str, CSV文件路径列表
            true_distances: list of float, 对应的真实距离（米）
        """
        all_data = []

        for csv_file, true_dist in zip(csv_files, true_distances):
            df = pd.read_csv(csv_file)

            # 提取所有anchor的数据
            for anchor_id in range(1, 6):  # a1 到 a5
                prefix = f'a{anchor_id}_'

                # 过滤出有效数据（测量距离不为0且所有信道质量参数都有效）
                valid_mask = (
                    (df[f'{prefix}m'] > 0) &
                    (df[f'{prefix}peak'].notna()) &
                    (df[f'{prefix}pwr'].notna()) &
                    (df[f'{prefix}fp_idx'].notna()) &
                    (df[f'{prefix}acc'].notna()) &
                    (df[f'{prefix}xo'].notna())
                )
                valid_data = df[valid_mask].copy()

                if len(valid_data) == 0:
                    continue

                # 为每一行数据提取特征
                for idx, row in valid_data.iterrows():
                    data_point = {
                        'anchor_id': anchor_id,
                        'measured_distance': row[f'{prefix}m'],
                        'true_distance': true_dist,
                        'peak': row[f'{prefix}peak'],
                        'pwr': row[f'{prefix}pwr'],
                        'fp_idx': row[f'{prefix}fp_idx'],
                        'acc': row[f'{prefix}acc'],
                        'xo': row[f'{prefix}xo'],
                    }
                    all_data.append(data_point)

        return pd.DataFrame(all_data)

    def train(self, training_df, n_estimators=200, max_depth=10):
        """
        训练模型

        参数:
            training_df: DataFrame, 包含anchor_id, measured_distance, true_distance和信道质量参数
            n_estimators: int, 树的数量
            max_depth: int, 树的最大深度
        """
        self.anchor_ids = sorted(training_df['anchor_id'].unique())

        results = {}

        # 为每个anchor训练独立的模型
        for anchor_id in self.anchor_ids:
            print(f"\n训练Anchor {anchor_id}的模型...")

            anchor_data = training_df[training_df['anchor_id'] == anchor_id].copy()

            if len(anchor_data) < 10:
                print(f"  警告: Anchor {anchor_id} 数据不足({len(anchor_data)}条), 跳过")
                continue

            # 提取特征
            X_features = []
            for idx, row in anchor_data.iterrows():
                features = self.feature_extractor.extract_features(row)
                X_features.append(features)

            X_features = np.array(X_features)

            # 添加测量距离作为特征
            X_measured = anchor_data['measured_distance'].values.reshape(-1, 1)
            X = np.hstack([X_measured, X_features])

            # 目标: 误差 = 真实距离 - 测量距离
            y_error = (anchor_data['true_distance'] - anchor_data['measured_distance']).values

            # 保存测量距离和真实距离用于评估
            measured_distances = anchor_data['measured_distance'].values
            true_distances = anchor_data['true_distance'].values

            # 归一化
            scaler = StandardScaler()
            X_scaled = scaler.fit_transform(X)

            # 训练/测试分割（同时分割所有相关数据）
            X_train, X_test, y_train, y_test, measured_train, measured_test, true_train, true_test = train_test_split(
                X_scaled, y_error, measured_distances, true_distances, test_size=0.2, random_state=42
            )

            # 创建模型
            if self.model_type == 'gradient_boosting':
                model = GradientBoostingRegressor(
                    n_estimators=n_estimators,
                    max_depth=max_depth,
                    learning_rate=0.05,
                    min_samples_split=5,
                    min_samples_leaf=2,
                    random_state=42
                )
            else:  # random_forest
                model = RandomForestRegressor(
                    n_estimators=n_estimators,
                    max_depth=max_depth,
                    min_samples_split=5,
                    min_samples_leaf=2,
                    random_state=42,
                    n_jobs=-1
                )

            # 训练
            model.fit(X_train, y_train)

            # 评估
            y_pred_train = model.predict(X_train)
            y_pred_test = model.predict(X_test)

            # 计算校正后的距离 (测量距离 + 预测的误差)
            corrected_train = measured_train + y_pred_train
            corrected_test = measured_test + y_pred_test

            # 校正前的误差
            train_mae_before = mean_absolute_error(true_train, measured_train)
            test_mae_before = mean_absolute_error(true_test, measured_test)

            # 校正后的误差
            train_mae_after = mean_absolute_error(true_train, corrected_train)
            test_mae_after = mean_absolute_error(true_test, corrected_test)

            # 保存模型和scaler
            self.models[anchor_id] = model
            self.scalers[anchor_id] = scaler

            # 记录结果
            results[anchor_id] = {
                'train_samples': len(y_train),
                'test_samples': len(y_test),
                'train_mae_before': train_mae_before,
                'train_mae_after': train_mae_after,
                'test_mae_before': test_mae_before,
                'test_mae_after': test_mae_after,
                'improvement': (test_mae_before - test_mae_after) / test_mae_before * 100
            }

            print(f"  训练集: {len(y_train)}条, 测试集: {len(y_test)}条")
            print(f"  校正前MAE: {test_mae_before:.4f}m")
            print(f"  校正后MAE: {test_mae_after:.4f}m")
            print(f"  改善: {results[anchor_id]['improvement']:.2f}%")

        return results

    def predict_correction(self, anchor_id, measured_distance, channel_quality):
        """
        预测距离校正值

        参数:
            anchor_id: int, anchor编号(1-5)
            measured_distance: float, TWR测量的原始距离(米)
            channel_quality: dict, 包含 peak, pwr, fp_idx, acc, xo

        返回:
            corrected_distance: float, 校正后的距离(米)
        """
        if anchor_id not in self.models:
            # 如果该anchor没有模型，返回原始值
            return measured_distance

        # 提取特征
        features = self.feature_extractor.extract_features(channel_quality)

        # 组合测量距离和特征
        X = np.hstack([[measured_distance], features]).reshape(1, -1)

        # 归一化
        X_scaled = self.scalers[anchor_id].transform(X)

        # 预测误差
        error_correction = self.models[anchor_id].predict(X_scaled)[0]

        # 应用校正
        corrected_distance = measured_distance + error_correction

        # 确保距离为正
        return max(0.01, corrected_distance)

    def save_model(self, filepath):
        """保存模型"""
        model_data = {
            'model_type': self.model_type,
            'models': self.models,
            'scalers': self.scalers,
            'anchor_ids': self.anchor_ids
        }
        with open(filepath, 'wb') as f:
            pickle.dump(model_data, f)
        print(f"模型已保存到: {filepath}")

    def load_model(self, filepath):
        """加载模型"""
        with open(filepath, 'rb') as f:
            model_data = pickle.load(f)

        self.model_type = model_data['model_type']
        self.models = model_data['models']
        self.scalers = model_data['scalers']
        self.anchor_ids = model_data['anchor_ids']
        print(f"模型已从 {filepath} 加载")


class MotionDetector:
    """运动检测器 - 区分动态和静态场景"""

    def __init__(self, window_size=10, static_threshold=0.05):
        """
        参数:
            window_size: int, 滑动窗口大小
            static_threshold: float, 静态判定阈值(米)
        """
        self.window_size = window_size
        self.static_threshold = static_threshold
        self.distance_history = {i: [] for i in range(1, 6)}

    def update(self, anchor_id, distance):
        """更新距离历史"""
        if anchor_id not in self.distance_history:
            self.distance_history[anchor_id] = []

        self.distance_history[anchor_id].append(distance)

        # 保持窗口大小
        if len(self.distance_history[anchor_id]) > self.window_size:
            self.distance_history[anchor_id].pop(0)

    def is_static(self, anchor_id=None):
        """
        判断是否静态

        参数:
            anchor_id: int or None, 如果为None则综合所有anchor判断

        返回:
            bool: True表示静态, False表示动态
        """
        if anchor_id is not None:
            # 单个anchor判断
            history = self.distance_history.get(anchor_id, [])
            if len(history) < 3:
                return True  # 数据不足，默认静态

            variance = np.var(history)
            return variance < (self.static_threshold ** 2)
        else:
            # 综合判断
            static_count = 0
            total_count = 0

            for aid in self.distance_history:
                history = self.distance_history[aid]
                if len(history) >= 3:
                    total_count += 1
                    if np.var(history) < (self.static_threshold ** 2):
                        static_count += 1

            if total_count == 0:
                return True

            # 超过2/3的anchor认为是静态，则判定为静态
            return static_count / total_count > 0.66

    def get_velocity_estimate(self):
        """估算速度(米/秒) - 基于距离变化率"""
        velocities = []

        for aid in self.distance_history:
            history = self.distance_history[aid]
            if len(history) >= 2:
                # 简单的差分估算
                vel = abs(history[-1] - history[-2])
                velocities.append(vel)

        if len(velocities) == 0:
            return 0.0

        # 返回中位数速度
        return np.median(velocities)


class KalmanFilter1D:
    """一维卡尔曼滤波器 - 用于平滑距离测量"""

    def __init__(self, process_variance=0.01, measurement_variance=0.1):
        """
        参数:
            process_variance: float, 过程噪声方差
            measurement_variance: float, 测量噪声方差
        """
        self.q = process_variance  # 过程噪声
        self.r = measurement_variance  # 测量噪声

        self.x = 0.0  # 状态估计(距离)
        self.p = 1.0  # 估计误差协方差
        self.is_initialized = False

    def update(self, measurement):
        """
        更新滤波器

        参数:
            measurement: float, 新的测量值

        返回:
            float: 滤波后的估计值
        """
        if not self.is_initialized:
            self.x = measurement
            self.is_initialized = True
            return self.x

        # 预测
        x_pred = self.x
        p_pred = self.p + self.q

        # 更新
        k = p_pred / (p_pred + self.r)  # 卡尔曼增益
        self.x = x_pred + k * (measurement - x_pred)
        self.p = (1 - k) * p_pred

        return self.x

    def reset(self):
        """重置滤波器"""
        self.x = 0.0
        self.p = 1.0
        self.is_initialized = False


class EnhancedPositioningSystem:
    """增强型定位系统 - 整合所有功能"""

    def __init__(self, correction_model):
        """
        参数:
            correction_model: DistanceCorrectionModel实例
        """
        self.correction_model = correction_model
        self.motion_detector = MotionDetector(window_size=10, static_threshold=0.08)

        # 为每个anchor创建卡尔曼滤波器
        self.kalman_filters = {i: KalmanFilter1D(
            process_variance=0.01,  # 动态场景下增大
            measurement_variance=0.1
        ) for i in range(1, 6)}

        # 锚点坐标（需要预先标定）
        self.anchor_positions = {
            1: np.array([0.0, 0.0, 0.0]),
            2: np.array([3.0, 0.0, 0.0]),
            3: np.array([3.0, 3.0, 0.0]),
            4: np.array([0.0, 3.0, 0.0]),
            5: np.array([1.5, 1.5, 2.0]),
        }

    def set_anchor_positions(self, positions):
        """
        设置锚点坐标

        参数:
            positions: dict, {anchor_id: np.array([x, y, z])}
        """
        self.anchor_positions = positions

    def process_measurement(self, anchor_id, measured_distance, channel_quality):
        """
        处理单个anchor的测量

        参数:
            anchor_id: int
            measured_distance: float, TWR原始距离(米)
            channel_quality: dict, 信道质量参数

        返回:
            dict: {
                'corrected_distance': 校正后距离,
                'filtered_distance': 滤波后距离,
                'is_static': 是否静态
            }
        """
        # 1. 距离校正
        corrected = self.correction_model.predict_correction(
            anchor_id, measured_distance, channel_quality
        )

        # 2. 更新运动检测器
        self.motion_detector.update(anchor_id, corrected)
        is_static = self.motion_detector.is_static(anchor_id)

        # 3. 卡尔曼滤波
        if is_static:
            # 静态场景：低过程噪声，高测量置信度
            self.kalman_filters[anchor_id].q = 0.001
            self.kalman_filters[anchor_id].r = 0.05
        else:
            # 动态场景：高过程噪声，适应快速变化
            self.kalman_filters[anchor_id].q = 0.05
            self.kalman_filters[anchor_id].r = 0.15

        filtered = self.kalman_filters[anchor_id].update(corrected)

        return {
            'raw_distance': measured_distance,
            'corrected_distance': corrected,
            'filtered_distance': filtered,
            'is_static': is_static
        }

    def multilateration(self, distances):
        """
        多边定位算法

        参数:
            distances: dict, {anchor_id: distance}

        返回:
            np.array: 估计的3D坐标 [x, y, z]
        """
        if len(distances) < 4:
            return None  # 至少需要4个anchor

        # 准备数据
        anchor_ids = list(distances.keys())
        A = []
        b = []

        # 使用第一个anchor作为参考
        ref_id = anchor_ids[0]
        ref_pos = self.anchor_positions[ref_id]
        ref_dist = distances[ref_id]

        for aid in anchor_ids[1:]:
            pos = self.anchor_positions[aid]
            dist = distances[aid]

            # 线性化方程
            A.append(2 * (pos - ref_pos))
            b.append(
                np.linalg.norm(pos)**2 - np.linalg.norm(ref_pos)**2 +
                ref_dist**2 - dist**2
            )

        A = np.array(A)
        b = np.array(b)

        # 最小二乘求解
        try:
            position, residuals, rank, s = np.linalg.lstsq(A, b, rcond=None)
            return position
        except:
            return None

    def estimate_position(self, measurements):
        """
        完整的定位流程

        参数:
            measurements: dict, {
                anchor_id: {
                    'measured_distance': float,
                    'channel_quality': dict
                }
            }

        返回:
            dict: {
                'position': np.array([x, y, z]),
                'is_static': bool,
                'velocity': float,
                'distances': dict
            }
        """
        # 处理所有测量
        processed = {}
        for aid, meas in measurements.items():
            result = self.process_measurement(
                aid,
                meas['measured_distance'],
                meas['channel_quality']
            )
            processed[aid] = result

        # 使用滤波后的距离进行定位
        filtered_distances = {
            aid: result['filtered_distance']
            for aid, result in processed.items()
        }

        # 多边定位
        position = self.multilateration(filtered_distances)

        # 运动状态
        is_static = self.motion_detector.is_static()
        velocity = self.motion_detector.get_velocity_estimate()

        return {
            'position': position,
            'is_static': is_static,
            'velocity': velocity,
            'distances': processed
        }


if __name__ == '__main__':
    print("增强型UWB定位系统")
    print("=" * 60)
    print("这是一个模块文件，请使用 train_enhanced_model.py 进行训练")
    print("使用 realtime_positioning.py 进行实时定位")
