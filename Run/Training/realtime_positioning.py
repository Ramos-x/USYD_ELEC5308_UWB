"""
实时UWB定位系统
从串口读取UWB数据，应用增强型定位算法，实时显示位置
"""

import os
import sys
import json
import re
import serial
import serial.tools.list_ports
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from collections import deque
import time
from enhanced_positioning_model import (
    DistanceCorrectionModel,
    EnhancedPositioningSystem
)

# ANSI转义字符正则表达式
ANSI_RE = re.compile(r"\x1B\[[0-9;?]*[ -/]*[@-~]")


def strip_ansi(s: str) -> str:
    """移除ANSI转义字符"""
    return ANSI_RE.sub('', s)


class RealtimePositioning:
    """实时定位系统"""

    def __init__(self, model_path, anchor_positions=None, debug=False):
        """
        参数:
            model_path: str, 模型文件路径
            anchor_positions: dict, 锚点坐标 {anchor_id: [x, y, z]}
            debug: bool, 是否启用调试模式
        """
        # 加载模型
        print("加载距离校正模型...")
        self.correction_model = DistanceCorrectionModel()
        self.correction_model.load_model(model_path)

        # 创建定位系统
        self.positioning_system = EnhancedPositioningSystem(self.correction_model)

        # 设置锚点位置
        if anchor_positions is not None:
            anchor_pos_dict = {
                aid: np.array(pos) for aid, pos in anchor_positions.items()
            }
            self.positioning_system.set_anchor_positions(anchor_pos_dict)
            print(f"已设置 {len(anchor_positions)} 个锚点坐标")
        else:
            print("警告: 未设置锚点坐标，使用默认值")

        # 数据缓冲
        self.position_history = deque(maxlen=100)
        self.distance_history = {i: deque(maxlen=50) for i in range(1, 6)}

        # 串口
        self.serial_port = None

        # 调试模式
        self.debug = debug

        # 统计
        self.total_updates = 0
        self.total_lines = 0
        self.json_errors = 0
        self.role_mismatches = 0
        self.insufficient_anchors = 0
        self.start_time = time.time()

    def find_serial_port(self):
        """自动查找串口"""
        ports = list(serial.tools.list_ports.comports())
        if not ports:
            print("错误: 未找到可用串口")
            return None

        print("\n可用串口:")
        for i, port in enumerate(ports):
            print(f"  {i+1}. {port.device} - {port.description}")

        if len(ports) == 1:
            selected = ports[0].device
            print(f"\n自动选择: {selected}")
            return selected

        # 让用户选择
        while True:
            try:
                choice = input(f"\n请选择串口 (1-{len(ports)}): ")
                idx = int(choice) - 1
                if 0 <= idx < len(ports):
                    return ports[idx].device
            except:
                pass
            print("无效选择，请重试")

    def connect_serial(self, port=None, baudrate=2000000):
        """连接串口"""
        if port is None:
            port = self.find_serial_port()
            if port is None:
                return False

        try:
            self.serial_port = serial.Serial(
                port=port,
                baudrate=baudrate,
                timeout=1.0
            )
            print(f"\n已连接到串口: {port}, 波特率: {baudrate}")
            time.sleep(0.5)  # 等待串口稳定
            return True
        except Exception as e:
            print(f"串口连接失败: {e}")
            return False

    def parse_json_line(self, line):
        """解析JSON格式的串口数据"""
        try:
            data = json.loads(line)

            if data.get('role') != 'tag':
                return None

            # 提取anchor数据
            measurements = {}

            for anchor in data.get('anchors', []):
                aid = anchor.get('aid')
                if aid is None:
                    continue

                # 获取扩展数据
                ex = anchor.get('ex', {})
                qual = anchor.get('qual', {})
                ipatov = qual.get('ipatov', {})

                # 检查是否有完整的交互数据
                if not ex.get('complete'):
                    continue

                # 计算DS-TWR距离
                tx1_hex = ex.get('tx1', '0000000000')
                rx1_hex = ex.get('rx1', '0000000000')
                tx2_hex = ex.get('tx2', '0000000000')
                rx2_hex = ex.get('rx2', '0000000000')
                tx3r_hex = ex.get('tx3r', '0000000000')
                rx3_hex = ex.get('rx3', '0000000000')

                # 转换为64位整数
                tx1 = int(tx1_hex, 16)
                rx1 = int(rx1_hex, 16)
                tx2 = int(tx2_hex, 16)
                rx2 = int(rx2_hex, 16)
                tx3 = int(tx3r_hex, 16)
                rx3 = int(rx3_hex, 16)

                # DS-TWR计算 (参考bu03.c中的逻辑)
                DWT_TIME_UNITS = 1.0 / (499.2e6 * 128.0)
                SPEED_OF_LIGHT = 299702547.0

                # 计算时间差 (40位环形)
                def time_diff(newer, older):
                    diff = (newer - older) & 0xFFFFFFFFFF
                    return diff * DWT_TIME_UNITS

                tround1 = time_diff(rx2, tx1)
                treply1 = time_diff(tx2, rx1)
                tround2 = time_diff(rx3, tx3)
                treply2 = time_diff(tx3, rx2)

                # ToF
                tof = (tround1 * tround2 - treply1 * treply2) / (tround1 + tround2 + treply1 + treply2)
                distance = tof * SPEED_OF_LIGHT

                if distance < 0 or distance > 100:
                    continue

                # 提取信道质量参数
                channel_quality = {
                    'peak': ipatov.get('peak', 0),
                    'pwr': ipatov.get('pwr', 0),
                    'fp_idx': ipatov.get('fp_idx', 0),
                    'acc': ipatov.get('acc', 1),  # 避免除零
                    'xo': qual.get('xo', 0)
                }

                measurements[aid] = {
                    'measured_distance': distance,
                    'channel_quality': channel_quality
                }

            return measurements

        except json.JSONDecodeError:
            return None
        except Exception as e:
            print(f"解析错误: {e}")
            return None

    def process_realtime(self, callback=None):
        """
        实时处理数据

        参数:
            callback: function(position_result), 每次更新后调用
        """
        if self.serial_port is None:
            print("错误: 串口未连接")
            return

        print("\n开始实时定位...")
        if self.debug:
            print("[调试模式已启用]")
        print("按 Ctrl+C 停止")
        print("-" * 60)

        try:
            while True:
                # 使用readline()逐行读取串口数据
                line = self.serial_port.readline()

                if not line:
                    if self.debug:
                        print("[DEBUG] 未接收到数据")
                    continue

                # 解码并移除ANSI转义字符
                if isinstance(line, (bytes, bytearray)):
                    line = line.decode('utf-8', errors='ignore')

                original_line = line
                line = strip_ansi(line.strip())

                if self.debug and original_line != line.strip():
                    print(f"[DEBUG] 移除了ANSI转义字符")

                # 跳过空行和非JSON行
                if not line:
                    if self.debug:
                        print("[DEBUG] 跳过空行")
                    continue

                if not (line.startswith('{') and line.endswith('}')):
                    if self.debug:
                        print(f"[DEBUG] 跳过非JSON行: {line[:50]}...")
                    continue

                self.total_lines += 1

                if self.debug:
                    print(f"\n[DEBUG] ========== 第 {self.total_lines} 行 ==========")
                    print(f"[DEBUG] 接收到JSON: {line[:100]}...")

                # 解析JSON
                try:
                    data = json.loads(line)

                    if self.debug:
                        print(f"[DEBUG] JSON解析成功")
                        print(f"[DEBUG] role: {data.get('role')}")
                        print(f"[DEBUG] anchor数量: {len(data.get('anchors', []))}")

                    if data.get('role') != 'tag':
                        self.role_mismatches += 1
                        if self.debug:
                            print(f"[DEBUG] 跳过: role不是'tag'")
                        continue

                    measurements = self.parse_json_line(line)

                    if self.debug:
                        if measurements:
                            print(f"[DEBUG] 成功解析到 {len(measurements)} 个有效anchor测量:")
                            for aid, meas in measurements.items():
                                dist = meas['measured_distance']
                                print(f"[DEBUG]   Anchor {aid}: {dist:.3f}m")
                        else:
                            print(f"[DEBUG] 没有有效的anchor测量数据")

                    if measurements and len(measurements) >= 3:
                        # 估算位置
                        result = self.positioning_system.estimate_position(measurements)

                        if result['position'] is not None:
                            self.total_updates += 1

                            # 保存历史
                            self.position_history.append(result['position'])
                            for aid, dist_data in result['distances'].items():
                                self.distance_history[aid].append(
                                    dist_data['filtered_distance']
                                )

                            # 打印信息
                            pos = result['position']
                            static_str = "静态" if result['is_static'] else "动态"
                            vel = result['velocity']

                            if self.debug:
                                print(f"[DEBUG] 定位成功!")
                                print(f"[DEBUG] 位置: X={pos[0]:.3f}, Y={pos[1]:.3f}, Z={pos[2]:.3f}")
                                print(f"[DEBUG] 状态: {static_str}, 速度: {vel:.3f}m/s")
                            else:
                                print(f"\r[{self.total_updates:04d}] 位置: "
                                      f"X={pos[0]:6.3f}m Y={pos[1]:6.3f}m Z={pos[2]:6.3f}m | "
                                      f"{static_str} | 速度: {vel:.3f}m/s | "
                                      f"Anchors: {len(measurements)}   ",
                                      end='', flush=True)

                            # 回调
                            if callback:
                                callback(result)
                        else:
                            if self.debug:
                                print(f"[DEBUG] 定位失败: 无法计算位置")
                    else:
                        self.insufficient_anchors += 1
                        if self.debug:
                            anchor_count = len(measurements) if measurements else 0
                            print(f"[DEBUG] 跳过: anchor数量不足 ({anchor_count} < 3)")

                except json.JSONDecodeError as e:
                    self.json_errors += 1
                    if self.debug:
                        print(f"[DEBUG] JSON解析失败: {e}")
                        print(f"[DEBUG] 原始数据: {line[:100]}...")
                except Exception as e:
                    if self.debug:
                        print(f"[DEBUG] 处理异常: {e}")

        except KeyboardInterrupt:
            print("\n\n停止定位")

            # 统计信息
            elapsed = time.time() - self.start_time
            print(f"\n统计信息:")
            print(f"  运行时间: {elapsed:.1f}秒")
            print(f"  总接收行数: {self.total_lines}")
            print(f"  成功定位次数: {self.total_updates}")
            print(f"  平均更新率: {self.total_updates/elapsed:.2f} Hz" if elapsed > 0 else "  平均更新率: N/A")
            print(f"  JSON解析错误: {self.json_errors}")
            print(f"  role不匹配: {self.role_mismatches}")
            print(f"  anchor数量不足: {self.insufficient_anchors}")

    def close(self):
        """关闭连接"""
        if self.serial_port:
            self.serial_port.close()
            print("串口已关闭")


class RealtimeVisualizer:
    """实时可视化"""

    def __init__(self, positioning_system):
        self.positioning = positioning_system

        # 创建图形
        self.fig = plt.figure(figsize=(14, 6))
        self.ax_2d = self.fig.add_subplot(121)
        self.ax_dist = self.fig.add_subplot(122)

        # 2D轨迹图
        self.ax_2d.set_xlabel('X (m)')
        self.ax_2d.set_ylabel('Y (m)')
        self.ax_2d.set_title('2D定位轨迹')
        self.ax_2d.grid(True, alpha=0.3)
        self.ax_2d.set_aspect('equal')

        # 绘制锚点
        anchor_positions = positioning_system.positioning_system.anchor_positions
        for aid, pos in anchor_positions.items():
            self.ax_2d.plot(pos[0], pos[1], 'r^', markersize=12, label=f'Anchor {aid}')
            self.ax_2d.text(pos[0], pos[1] + 0.2, f'A{aid}', ha='center')

        # 轨迹线
        self.trajectory_line, = self.ax_2d.plot([], [], 'b-', linewidth=1, alpha=0.5)
        self.current_point, = self.ax_2d.plot([], [], 'go', markersize=10, label='当前位置')

        # 距离图
        self.ax_dist.set_xlabel('时间 (样本)')
        self.ax_dist.set_ylabel('距离 (m)')
        self.ax_dist.set_title('各Anchor距离变化')
        self.ax_dist.grid(True, alpha=0.3)

        self.distance_lines = {}
        colors = ['r', 'g', 'b', 'c', 'm']
        for i, aid in enumerate(range(1, 6)):
            line, = self.ax_dist.plot([], [], color=colors[i], label=f'Anchor {aid}')
            self.distance_lines[aid] = line

        self.ax_dist.legend(loc='upper right')

        plt.tight_layout()

    def update_plot(self, result):
        """更新图表"""
        # 更新2D轨迹
        if len(self.positioning.position_history) > 0:
            positions = np.array(list(self.positioning.position_history))
            self.trajectory_line.set_data(positions[:, 0], positions[:, 1])
            self.current_point.set_data([positions[-1, 0]], [positions[-1, 1]])

            # 自动调整范围
            x_min, x_max = positions[:, 0].min(), positions[:, 0].max()
            y_min, y_max = positions[:, 1].min(), positions[:, 1].max()
            margin = 0.5
            self.ax_2d.set_xlim(x_min - margin, x_max + margin)
            self.ax_2d.set_ylim(y_min - margin, y_max + margin)

        # 更新距离图
        for aid, line in self.distance_lines.items():
            history = list(self.positioning.distance_history[aid])
            if len(history) > 0:
                line.set_data(range(len(history)), history)

        # 调整距离图范围
        all_distances = []
        for history in self.positioning.distance_history.values():
            all_distances.extend(history)

        if len(all_distances) > 0:
            max_len = max(len(h) for h in self.positioning.distance_history.values())
            self.ax_dist.set_xlim(0, max_len)
            self.ax_dist.set_ylim(0, max(all_distances) * 1.1)

        plt.pause(0.001)


def main():
    print("=" * 80)
    print("实时UWB定位系统")
    print("=" * 80)

    # 模型路径
    script_dir = os.path.dirname(os.path.abspath(__file__))
    model_path = os.path.join(script_dir, 'uwb_distance_correction_model.pkl')

    if not os.path.exists(model_path):
        print(f"\n错误: 模型文件不存在: {model_path}")
        print("请先运行 train_enhanced_model.py 训练模型")
        return

    # 锚点坐标 (需要根据实际标定结果修改)
    anchor_positions = {
        1: [0.0, 0.0, 1.0],      # Anchor 1
        2: [3.0, 0.0, 1.0],      # Anchor 2
        3: [3.0, 3.0, 1.0],      # Anchor 3
        4: [0.0, 3.0, 1.0],      # Anchor 4
        5: [1.5, 1.5, 2.5],      # Anchor 5
    }

    print("\n当前锚点坐标配置:")
    for aid, pos in anchor_positions.items():
        print(f"  Anchor {aid}: X={pos[0]:.2f}m, Y={pos[1]:.2f}m, Z={pos[2]:.2f}m")

    print("\n提示: 如需修改锚点坐标，请编辑本文件中的 anchor_positions 字典")

    # 询问是否启用调试模式
    use_debug = input("\n是否启用调试模式? (y/n): ").lower().strip() == 'y'

    # 创建定位系统
    positioning = RealtimePositioning(model_path, anchor_positions, debug=use_debug)

    # 连接串口
    if not positioning.connect_serial():
        return

    # 询问是否需要可视化
    use_viz = input("\n是否启用实时可视化? (y/n): ").lower().strip() == 'y'

    if use_viz:
        # 创建可视化
        visualizer = RealtimeVisualizer(positioning)

        # 启动实时处理
        positioning.process_realtime(callback=visualizer.update_plot)
    else:
        # 仅命令行输出
        positioning.process_realtime()

    # 关闭
    positioning.close()


if __name__ == '__main__':
    main()
