"""
训练增强型UWB定位模型
使用现有的out_1m.csv和out_2m.csv数据训练距离校正模型
"""

import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from enhanced_positioning_model import (
    DistanceCorrectionModel,
    ChannelQualityFeatureExtractor
)

# 设置中文显示
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial']
plt.rcParams['axes.unicode_minus'] = False


def main():
    print("=" * 80)
    print("增强型UWB定位系统 - 模型训练")
    print("=" * 80)

    # 1. 数据文件和真实距离
    csv_files = [
        'out_1m.csv',
        'out_1.5m.csv',
        'out_2m.csv',
        'out_2.5m.csv'
    ]

    true_distances = [
        1.0,  # out_1m.csv的真实距离是1米
        1.5,
        2.0,  # out_2m.csv的真实距离是2米
        2.5
    ]

    # 检查文件是否存在
    script_dir = os.path.dirname(os.path.abspath(__file__))
    full_paths = []
    for csv_file in csv_files:
        full_path = os.path.join(script_dir, csv_file)
        if not os.path.exists(full_path):
            print(f"错误: 找不到文件 {full_path}")
            return
        full_paths.append(full_path)
        print(f"找到数据文件: {csv_file}")

    print(f"\n真实距离: {true_distances}")

    # 2. 创建模型
    print("\n" + "=" * 80)
    print("创建距离校正模型...")
    model = DistanceCorrectionModel(model_type='gradient_boosting')

    # 3. 加载训练数据
    print("\n加载训练数据...")
    training_df = model.load_training_data(full_paths, true_distances)

    print(f"总数据量: {len(training_df)} 条")
    print(f"Anchor分布:")
    for aid in sorted(training_df['anchor_id'].unique()):
        count = len(training_df[training_df['anchor_id'] == aid])
        print(f"  Anchor {aid}: {count} 条")

    # 4. 数据统计分析
    print("\n" + "=" * 80)
    print("数据统计分析:")
    for aid in sorted(training_df['anchor_id'].unique()):
        anchor_data = training_df[training_df['anchor_id'] == aid]
        measured = anchor_data['measured_distance'].values
        true_dist = anchor_data['true_distance'].values

        error = measured - true_dist
        mae = np.mean(np.abs(error))
        std = np.std(error)

        print(f"\nAnchor {aid}:")
        print(f"  测量距离 - 平均: {np.mean(measured):.4f}m, 标准差: {np.std(measured):.4f}m")
        print(f"  误差 - 平均: {np.mean(error):.4f}m, MAE: {mae:.4f}m, 标准差: {std:.4f}m")
        print(f"  信道质量 - SNR估算: {np.mean(anchor_data['peak'] / anchor_data['acc']):.2f}")

    # 5. 训练模型
    print("\n" + "=" * 80)
    print("开始训练模型...")
    results = model.train(training_df, n_estimators=200, max_depth=10)

    # 6. 输出训练结果
    print("\n" + "=" * 80)
    print("训练结果汇总:")
    print("-" * 80)
    print(f"{'Anchor':<8} {'样本数':<10} {'校正前MAE':<15} {'校正后MAE':<15} {'改善率':<10}")
    print("-" * 80)

    for aid in sorted(results.keys()):
        r = results[aid]
        print(f"{aid:<8} {r['test_samples']:<10} "
              f"{r['test_mae_before']:<15.4f} {r['test_mae_after']:<15.4f} "
              f"{r['improvement']:<10.2f}%")

    # 7. 保存模型
    model_path = os.path.join(script_dir, 'uwb_distance_correction_model.pkl')
    model.save_model(model_path)

    # 8. 可视化结果
    print("\n" + "=" * 80)
    print("生成可视化图表...")

    # 为每个anchor创建对比图
    fig, axes = plt.subplots(2, 3, figsize=(15, 10))
    fig.suptitle('距离校正效果对比', fontsize=16, fontweight='bold')

    for idx, aid in enumerate(sorted(results.keys())):
        if idx >= 5:
            break

        row = idx // 3
        col = idx % 3
        ax = axes[row, col]

        anchor_data = training_df[training_df['anchor_id'] == aid]

        # 提取特征并预测
        corrected_distances = []
        for _, row_data in anchor_data.iterrows():
            channel_quality = {
                'peak': row_data['peak'],
                'pwr': row_data['pwr'],
                'fp_idx': row_data['fp_idx'],
                'acc': row_data['acc'],
                'xo': row_data['xo']
            }
            corrected = model.predict_correction(
                aid,
                row_data['measured_distance'],
                channel_quality
            )
            corrected_distances.append(corrected)

        measured = anchor_data['measured_distance'].values
        true_dist = anchor_data['true_distance'].values
        corrected = np.array(corrected_distances)

        # 绘制散点图
        ax.scatter(true_dist, measured, alpha=0.3, s=20, label='校正前', color='red')
        ax.scatter(true_dist, corrected, alpha=0.3, s=20, label='校正后', color='blue')

        # 绘制理想线
        min_val = min(true_dist.min(), measured.min(), corrected.min())
        max_val = max(true_dist.max(), measured.max(), corrected.max())
        ax.plot([min_val, max_val], [min_val, max_val], 'k--', alpha=0.5, label='理想线')

        ax.set_xlabel('真实距离 (m)')
        ax.set_ylabel('测量/校正距离 (m)')
        ax.set_title(f'Anchor {aid}')
        ax.legend()
        ax.grid(True, alpha=0.3)

    # 删除多余的子图
    if len(results) < 6:
        axes[1, 2].remove()

    plt.tight_layout()

    # 保存图表
    plot_path = os.path.join(script_dir, 'correction_comparison.png')
    plt.savefig(plot_path, dpi=150, bbox_inches='tight')
    print(f"图表已保存到: {plot_path}")

    # 9. 创建误差分布图
    fig2, axes2 = plt.subplots(1, 2, figsize=(12, 5))
    fig2.suptitle('误差分布对比', fontsize=16, fontweight='bold')

    all_errors_before = []
    all_errors_after = []

    for aid in sorted(results.keys()):
        anchor_data = training_df[training_df['anchor_id'] == aid]

        corrected_distances = []
        for _, row_data in anchor_data.iterrows():
            channel_quality = {
                'peak': row_data['peak'],
                'pwr': row_data['pwr'],
                'fp_idx': row_data['fp_idx'],
                'acc': row_data['acc'],
                'xo': row_data['xo']
            }
            corrected = model.predict_correction(
                aid,
                row_data['measured_distance'],
                channel_quality
            )
            corrected_distances.append(corrected)

        measured = anchor_data['measured_distance'].values
        true_dist = anchor_data['true_distance'].values
        corrected = np.array(corrected_distances)

        errors_before = measured - true_dist
        errors_after = corrected - true_dist

        all_errors_before.extend(errors_before)
        all_errors_after.extend(errors_after)

    # 直方图
    axes2[0].hist(all_errors_before, bins=50, alpha=0.7, label='校正前', color='red')
    axes2[0].hist(all_errors_after, bins=50, alpha=0.7, label='校正后', color='blue')
    axes2[0].set_xlabel('误差 (m)')
    axes2[0].set_ylabel('频数')
    axes2[0].set_title('误差分布直方图')
    axes2[0].legend()
    axes2[0].grid(True, alpha=0.3)

    # 箱线图
    axes2[1].boxplot([all_errors_before, all_errors_after],
                     labels=['校正前', '校正后'])
    axes2[1].set_ylabel('误差 (m)')
    axes2[1].set_title('误差分布箱线图')
    axes2[1].grid(True, alpha=0.3)

    plt.tight_layout()
    error_plot_path = os.path.join(script_dir, 'error_distribution.png')
    plt.savefig(error_plot_path, dpi=150, bbox_inches='tight')
    print(f"误差分布图已保存到: {error_plot_path}")

    print("\n" + "=" * 80)
    print("训练完成!")
    print(f"模型文件: {model_path}")
    print(f"可视化结果: {plot_path}, {error_plot_path}")
    print("=" * 80)

    # 显示图表
    plt.show()


if __name__ == '__main__':
    main()
