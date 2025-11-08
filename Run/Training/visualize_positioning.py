"""
UWB定位数据三维可视化
绘制定位轨迹的3D散点图
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
import os

def plot_positioning_3d(csv_file):
    """
    绘制3D定位轨迹

    参数:
        csv_file: str, CSV文件路径
    """
    # 读取数据
    print(f"Reading data file: {csv_file}")
    df = pd.read_csv(csv_file)

    # 提取坐标
    x = df['x'].values
    y = df['y'].values
    z = df['z'].values
    elapsed_time = df['elapsed_time'].values

    print(f"Total data points: {len(x)}")
    print(f"X range: [{x.min():.3f}, {x.max():.3f}] m")
    print(f"Y range: [{y.min():.3f}, {y.max():.3f}] m")
    print(f"Z range: [{z.min():.3f}, {z.max():.3f}] m")

    # 锚点坐标
    anchor_positions = {
        1: [0.3, 0.3, 0.6],
        2: [3.3, 0.3, 1.82],
        3: [3.3, 3.6, 0.52],
        4: [0.1, 3.6, 1.63],
        5: [1.65, 2.08, 0.75],
    }

    # 创建图形
    fig = plt.figure(figsize=(16, 12))

    # 3D轨迹图 (主图)
    ax1 = fig.add_subplot(221, projection='3d')

    # 绘制定位轨迹 - 使用时间颜色映射
    scatter = ax1.scatter(x, y, z, c=elapsed_time, cmap='viridis',
                          s=20, alpha=0.6, label='Position')

    # 绘制轨迹线
    ax1.plot(x, y, z, 'b-', alpha=0.3, linewidth=0.5, label='Trajectory')

    # 绘制起点和终点
    ax1.scatter([x[0]], [y[0]], [z[0]], c='green', s=200, marker='o',
                edgecolors='black', linewidths=2, label='Start')
    ax1.scatter([x[-1]], [y[-1]], [z[-1]], c='red', s=200, marker='s',
                edgecolors='black', linewidths=2, label='End')

    # 绘制锚点
    for aid, pos in anchor_positions.items():
        ax1.scatter([pos[0]], [pos[1]], [pos[2]],
                   c='red', s=300, marker='^',
                   edgecolors='black', linewidths=2)
        ax1.text(pos[0], pos[1], pos[2]+0.2, f'A{aid}',
                fontsize=12, fontweight='bold')

    # 设置标签
    ax1.set_xlabel('X (m)', fontsize=12)
    ax1.set_ylabel('Y (m)', fontsize=12)
    ax1.set_zlabel('Z (m)', fontsize=12)
    ax1.set_title('3D Positioning Trajectory (Color = Time)', fontsize=14, fontweight='bold')
    ax1.legend(loc='upper right')

    # 添加颜色条
    cbar = plt.colorbar(scatter, ax=ax1, pad=0.1, shrink=0.8)
    cbar.set_label('Time (s)', fontsize=10)

    # 设置视角
    ax1.view_init(elev=20, azim=45)

    # XY平面投影
    ax2 = fig.add_subplot(222)
    ax2.scatter(x, y, c=elapsed_time, cmap='viridis', s=10, alpha=0.5)
    ax2.plot(x, y, 'b-', alpha=0.2, linewidth=0.5)
    ax2.scatter(x[0], y[0], c='green', s=100, marker='o', edgecolors='black', linewidths=2, label='Start')
    ax2.scatter(x[-1], y[-1], c='red', s=100, marker='s', edgecolors='black', linewidths=2, label='End')

    # 绘制锚点 (XY平面)
    for aid, pos in anchor_positions.items():
        ax2.scatter(pos[0], pos[1], c='red', s=150, marker='^',
                   edgecolors='black', linewidths=2)
        ax2.text(pos[0]+0.1, pos[1]+0.1, f'A{aid}', fontsize=10)

    ax2.set_xlabel('X (m)', fontsize=11)
    ax2.set_ylabel('Y (m)', fontsize=11)
    ax2.set_title('XY Plane Projection', fontsize=12, fontweight='bold')
    ax2.grid(True, alpha=0.3)
    ax2.set_aspect('equal')
    ax2.legend()

    # XZ平面投影
    ax3 = fig.add_subplot(223)
    ax3.scatter(x, z, c=elapsed_time, cmap='viridis', s=10, alpha=0.5)
    ax3.plot(x, z, 'b-', alpha=0.2, linewidth=0.5)
    ax3.scatter(x[0], z[0], c='green', s=100, marker='o', edgecolors='black', linewidths=2)
    ax3.scatter(x[-1], z[-1], c='red', s=100, marker='s', edgecolors='black', linewidths=2)

    # 绘制锚点 (XZ平面)
    for aid, pos in anchor_positions.items():
        ax3.scatter(pos[0], pos[2], c='red', s=150, marker='^',
                   edgecolors='black', linewidths=2)

    ax3.set_xlabel('X (m)', fontsize=11)
    ax3.set_ylabel('Z (m)', fontsize=11)
    ax3.set_title('XZ Plane Projection', fontsize=12, fontweight='bold')
    ax3.grid(True, alpha=0.3)

    # YZ平面投影
    ax4 = fig.add_subplot(224)
    ax4.scatter(y, z, c=elapsed_time, cmap='viridis', s=10, alpha=0.5)
    ax4.plot(y, z, 'b-', alpha=0.2, linewidth=0.5)
    ax4.scatter(y[0], z[0], c='green', s=100, marker='o', edgecolors='black', linewidths=2)
    ax4.scatter(y[-1], z[-1], c='red', s=100, marker='s', edgecolors='black', linewidths=2)

    # 绘制锚点 (YZ平面)
    for aid, pos in anchor_positions.items():
        ax4.scatter(pos[1], pos[2], c='red', s=150, marker='^',
                   edgecolors='black', linewidths=2)

    ax4.set_xlabel('Y (m)', fontsize=11)
    ax4.set_ylabel('Z (m)', fontsize=11)
    ax4.set_title('YZ Plane Projection', fontsize=12, fontweight='bold')
    ax4.grid(True, alpha=0.3)

    plt.tight_layout()

    # 保存图片
    output_file = csv_file.replace('.csv', '_3d_plot.png')
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"\nImage saved: {output_file}")
    plt.close()

    # 创建交互式3D图 (单独窗口)
    create_interactive_3d(x, y, z, elapsed_time, anchor_positions, csv_file)


def create_interactive_3d(x, y, z, elapsed_time, anchor_positions, csv_file):
    """创建可旋转的交互式3D图"""
    fig = plt.figure(figsize=(12, 9))
    ax = fig.add_subplot(111, projection='3d')

    # 绘制定位轨迹
    scatter = ax.scatter(x, y, z, c=elapsed_time, cmap='plasma',
                        s=30, alpha=0.7, label='Position')
    ax.plot(x, y, z, 'b-', alpha=0.2, linewidth=1, label='Trajectory')

    # 起点和终点
    ax.scatter([x[0]], [y[0]], [z[0]], c='lime', s=300, marker='o',
              edgecolors='black', linewidths=3, label='Start', zorder=10)
    ax.scatter([x[-1]], [y[-1]], [z[-1]], c='red', s=300, marker='s',
              edgecolors='black', linewidths=3, label='End', zorder=10)

    # 绘制锚点
    for aid, pos in anchor_positions.items():
        ax.scatter([pos[0]], [pos[1]], [pos[2]],
                  c='orangered', s=400, marker='^',
                  edgecolors='black', linewidths=2.5, zorder=10)
        ax.text(pos[0], pos[1], pos[2]+0.3, f'Anchor {aid}',
               fontsize=13, fontweight='bold',
               bbox=dict(boxstyle='round,pad=0.3', facecolor='yellow', alpha=0.7))

    # 设置标签
    ax.set_xlabel('X Coordinate (m)', fontsize=13, labelpad=10)
    ax.set_ylabel('Y Coordinate (m)', fontsize=13, labelpad=10)
    ax.set_zlabel('Z Coordinate (m)', fontsize=13, labelpad=10)
    ax.set_title(f'UWB 3D Positioning Trajectory\nData Points: {len(x)} | Duration: {elapsed_time[-1]:.1f}s',
                fontsize=15, fontweight='bold', pad=20)

    # 添加图例
    ax.legend(loc='upper left', fontsize=11, framealpha=0.9)

    # 添加颜色条
    cbar = plt.colorbar(scatter, ax=ax, pad=0.1, shrink=0.7)
    cbar.set_label('Elapsed Time (s)', fontsize=11)

    # 设置网格
    ax.grid(True, alpha=0.3)

    # 设置初始视角
    ax.view_init(elev=25, azim=135)

    # 保存交互式图
    interactive_file = csv_file.replace('.csv', '_3d_interactive.png')
    plt.savefig(interactive_file, dpi=300, bbox_inches='tight')
    print(f"Interactive 3D plot saved: {interactive_file}")
    plt.close()


def main():
    """Main function"""
    # 获取最新的CSV文件
    script_dir = os.path.dirname(os.path.abspath(__file__))
    csv_file = os.path.join(script_dir, 'positioning_log_20251108_133602.csv')

    if not os.path.exists(csv_file):
        print(f"Error: File not found - {csv_file}")
        return

    print("=" * 80)
    print("UWB Positioning Data 3D Visualization")
    print("=" * 80)

    # 绘制3D图
    plot_positioning_3d(csv_file)

    print("\nVisualization complete!")
    print("Tip: You can drag the mouse to rotate the 3D plot and view from different angles")


if __name__ == '__main__':
    main()