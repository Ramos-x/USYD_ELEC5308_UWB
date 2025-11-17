"""
实时UWB定位系统
从串口读取UWB数据，应用增强型定位算法，实时显示位置
"""

import os
import sys
import json
import re
import csv
import serial
import serial.tools.list_ports
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from collections import deque
import time
import traceback
from datetime import datetime
from enhanced_positioning_model import (
    DistanceCorrectionModel,
    EnhancedPositioningSystem
)

# ANSI转义字符正则表达式
ANSI_RE = re.compile(r"\x1B\[[0-9;?]*[ -/]*[@-~]")

# DW1000 时间戳常量
MASK40 = (1 << 40) - 1  # 40位掩码
DWT_TIME_UNITS = 1.0 / (499.2e6 * 128.0)  # ≈ 15.65e-12 s
SPEED_OF_LIGHT = 299702547.0  # m/s


def strip_ansi(s: str) -> str:
    """移除ANSI转义字符"""
    return ANSI_RE.sub('', s)


def hex5_to_u40(h: str) -> int:
    """将10位十六进制字符串转换为40位无符号整数"""
    return int(h, 16) & MASK40


def rel40(newer: int, older: int) -> int:
    """计算40位环形计数器的差值"""
    return (newer - older) & MASK40


class RealtimePositioning:
    """实时定位系统"""

    def __init__(self, model_path, anchor_positions=None, debug=False, csv_output=None):
        """
        参数:
            model_path: str, 模型文件路径
            anchor_positions: dict, 锚点坐标 {anchor_id: [x, y, z]}
            debug: bool, 是否启用调试模式
            csv_output: str, CSV输出文件路径(可选)
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

        # CSV输出
        self.csv_output = csv_output
        self.csv_file = None
        self.csv_writer = None
        if csv_output:
            self._init_csv_writer()

        # 统计
        self.total_updates = 0
        self.total_lines = 0
        self.json_errors = 0
        self.role_mismatches = 0
        self.insufficient_anchors = 0
        self.start_time = time.time()

    def _init_csv_writer(self):
        """初始化CSV写入器"""
        try:
            # 使用 buffering=1 启用行缓冲，每写入一行就立即刷新
            self.csv_file = open(self.csv_output, 'w', newline='', encoding='utf-8', buffering=1)
            self.csv_writer = csv.writer(self.csv_file)

            # 写入表头
            header = [
                'timestamp', 'elapsed_time',
                'x', 'y', 'z',
                'velocity', 'is_static',
                'anchor_count',
                'a1_measured', 'a1_filtered', 'a1_corrected',
                'a2_measured', 'a2_filtered', 'a2_corrected',
                'a3_measured', 'a3_filtered', 'a3_corrected',
                'a4_measured', 'a4_filtered', 'a4_corrected',
                'a5_measured', 'a5_filtered', 'a5_corrected'
            ]
            self.csv_writer.writerow(header)
            self.csv_file.flush()
            print(f"CSV日志已启用: {self.csv_output}")
        except Exception as e:
            print(f"警告: 无法创建CSV文件: {e}")
            self.csv_file = None
            self.csv_writer = None

    def _write_csv_row(self, result):
        """写入一行CSV数据"""
        if not self.csv_writer:
            return

        try:
            pos = result['position']
            elapsed = time.time() - self.start_time
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

            # 基本信息
            row = [
                timestamp,
                f"{elapsed:.3f}",
                f"{pos[0]:.6f}",
                f"{pos[1]:.6f}",
                f"{pos[2]:.6f}",
                f"{result['velocity']:.6f}",
                1 if result['is_static'] else 0,
                len(result['distances'])
            ]

            # 每个anchor的距离数据
            for aid in range(1, 6):
                if aid in result['distances']:
                    dist_data = result['distances'][aid]
                    row.extend([
                        f"{dist_data['raw_distance']:.6f}",  # 修复: 使用 raw_distance 而不是 measured_distance
                        f"{dist_data['filtered_distance']:.6f}",
                        f"{dist_data['corrected_distance']:.6f}"
                    ])
                else:
                    row.extend(['', '', ''])  # 该anchor无数据

            self.csv_writer.writerow(row)
            self.csv_file.flush()
        except Exception as e:
            # 总是打印CSV写入错误，帮助调试
            print(f"\n警告: CSV写入错误: {e}")
            if self.debug:
                traceback.print_exc()

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
                    if self.debug:
                        print(f"[DEBUG]   跳过anchor: 无aid字段")
                    continue

                # 获取扩展数据
                ex = anchor.get('ex', {})
                qual = anchor.get('qual', {})
                ipatov = qual.get('ipatov', {})

                if self.debug:
                    print(f"[DEBUG]   处理 Anchor {aid}:")
                    print(f"[DEBUG]     ex字段存在: {bool(ex)}")
                    print(f"[DEBUG]     complete字段: {ex.get('complete')}")

                # 检查是否有完整的交互数据
                if not ex.get('complete'):
                    if self.debug:
                        print(f"[DEBUG]     跳过: complete不为1")
                    continue

                # 计算DS-TWR距离
                tx1_hex = ex.get('tx1', '0000000000')
                rx1_hex = ex.get('rx1', '0000000000')
                tx2_hex = ex.get('tx2', '0000000000')
                rx2_hex = ex.get('rx2', '0000000000')
                tx3r_hex = ex.get('tx3r', '0000000000')
                rx3_hex = ex.get('rx3', '0000000000')

                if self.debug:
                    print(f"[DEBUG]     时间戳: tx1={tx1_hex}, rx1={rx1_hex}, tx2={tx2_hex}")
                    print(f"[DEBUG]             rx2={rx2_hex}, tx3r={tx3r_hex}, rx3={rx3_hex}")

                # 检查是否所有时间戳都有效
                if tx1_hex == '0000000000' or rx1_hex == '0000000000' or \
                   tx2_hex == '0000000000' or rx2_hex == '0000000000' or \
                   tx3r_hex == '0000000000' or rx3_hex == '0000000000':
                    if self.debug:
                        print(f"[DEBUG]     跳过: 时间戳为0")
                    continue

                # 转换为40位无符号整数(关键修复!)
                tx1 = hex5_to_u40(tx1_hex)    # Tag发送第1次
                rx1 = hex5_to_u40(rx1_hex)    # Anchor收到tx1
                tx2 = hex5_to_u40(tx2_hex)    # Anchor回复
                rx2 = hex5_to_u40(rx2_hex)    # Tag收到tx2
                tx3 = hex5_to_u40(tx3r_hex)   # Tag发送第3次
                rx3 = hex5_to_u40(rx3_hex)    # Anchor收到tx3

                # 计算时间差(40位环形计数器)
                Tround1 = rel40(rx2, tx1)     # Tag域: TX1 -> RX2
                Treply2 = rel40(tx3, rx2)     # Tag域: RX2 -> TX3
                Treply1 = rel40(tx2, rx1)     # Anchor域: RX1 -> TX2
                Tround2 = rel40(rx3, tx2)     # Anchor域: TX2 -> RX3

                # 有效性检查
                if Tround1 <= 0 or Tround2 <= 0 or Treply1 <= 0 or Treply2 <= 0:
                    if self.debug:
                        print(f"[DEBUG]     跳过: 时间差为负或零")
                    continue

                # 转换为秒
                tround1 = Tround1 * DWT_TIME_UNITS
                treply1 = Treply1 * DWT_TIME_UNITS
                tround2 = Tround2 * DWT_TIME_UNITS
                treply2 = Treply2 * DWT_TIME_UNITS

                if self.debug:
                    print(f"[DEBUG]     tround1={tround1:.9f}s, treply1={treply1:.9f}s")
                    print(f"[DEBUG]     tround2={tround2:.9f}s, treply2={treply2:.9f}s")

                # ToF
                tof = (tround1 * tround2 - treply1 * treply2) / (tround1 + tround2 + treply1 + treply2)
                distance = tof * SPEED_OF_LIGHT

                if self.debug:
                    print(f"[DEBUG]     ToF={tof:.9f}s, 距离={distance:.3f}m")

                if distance < 0 or distance > 100:
                    if self.debug:
                        print(f"[DEBUG]     跳过: 距离超出范围 ({distance:.3f}m)")
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

                if self.debug:
                    print(f"[DEBUG]     ✓ 成功添加测量数据")

            return measurements

        except json.JSONDecodeError:
            return None
        except Exception as e:
            if self.debug:
                print(f"[DEBUG] 解析异常: {e}")
                print(f"[DEBUG] 堆栈跟踪:")
                traceback.print_exc()
            else:
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

                            # 写入CSV
                            self._write_csv_row(result)

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

        if self.csv_file:
            self.csv_file.close()
            print(f"CSV文件已保存: {self.csv_output}")


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
        1: [0.3, 0.3, 0.6],      # Anchor 1
        2: [3.3, 0.3, 1.82],      # Anchor 2
        3: [3.3, 3.6, 0.52],      # Anchor 3
        4: [0.1, 3.6, 1.63],      # Anchor 4
        5: [1.65, 2.08, 0.75],      # Anchor 5
    }

    print("\n当前锚点坐标配置:")
    for aid, pos in anchor_positions.items():
        print(f"  Anchor {aid}: X={pos[0]:.2f}m, Y={pos[1]:.2f}m, Z={pos[2]:.2f}m")

    print("\n提示: 如需修改锚点坐标，请编辑本文件中的 anchor_positions 字典")

    # 询问是否启用调试模式
    use_debug = input("\n是否启用调试模式? (y/n): ").lower().strip() == 'y'

    # 询问是否保存CSV
    use_csv = input("\n是否保存定位数据到CSV? (y/n): ").lower().strip() == 'y'
    csv_output = None
    if use_csv:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        csv_output = os.path.join(script_dir, f'positioning_log_{timestamp}.csv')

    # 创建定位系统
    positioning = RealtimePositioning(model_path, anchor_positions, debug=use_debug, csv_output=csv_output)

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
