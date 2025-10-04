#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import sys
import time
import threading
from queue import Queue, Empty
from collections import deque
import os

import serial  # pip install pyserial
import serial.tools.list_ports
import re

# -------------------- 常量（与固件一致） --------------------
C = 299_702_547.0                     # m/s
DWT_TIME_UNITS = 1.0 / (499.2e6 * 128.0)
MASK40 = (1 << 40) - 1

# 串口配置
BAUD = 2000000
TIMEOUT = 0.2      # 读超时（秒），用于线程可中断
TARGET_DEVICE_NAME = "USB-SERIAL CH340"  # 目标设备名称
DEBUG_MODE = False  # 调试模式：打印接收到的所有行

def find_serial_port():
    """自动搜索包含目标设备名称的串口"""
    ports = serial.tools.list_ports.comports()
    for port in ports:
        if TARGET_DEVICE_NAME in port.description.upper() or \
                (port.hwid and TARGET_DEVICE_NAME in port.hwid.upper()):
            return port.device
    return None

# 配置文件路径（保存到代码文件所在目录）
_script_dir = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(_script_dir, "anchor_calibration.json")

# 加载或初始化校准配置
def load_calibration_config():
    """从配置文件加载校准数据，如果文件不存在则返回默认值"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"警告：无法加载配置文件 {CONFIG_FILE}: {e}")

    # 默认配置
    return {
        "bias": {
            "1": 0.0,
            "2": 0.0,
            "3": 0.0,
            "4": 0.0,
            "5": 0.0
        },
        "scale": {
            "1": 1.0,
            "2": 1.0,
            "3": 1.0,
            "4": 1.0,
            "5": 1.0
        }
    }

def save_calibration_config(config):
    """保存校准数据到配置文件"""
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        print(f"✓ 校准数据已保存到 {CONFIG_FILE}")
    except Exception as e:
        print(f"错误：无法保存配置文件: {e}")

# 加载配置
calib_config = load_calibration_config()

# 从配置文件读取矫正参数
MANUAL_BIAS_PER_ANCHOR_M = {int(k): float(v) for k, v in calib_config.get("bias", {}).items()}
MANUAL_SCALE_PER_ANCHOR = {int(k): float(v) for k, v in calib_config.get("scale", {}).items()}

# 平滑与离群值抑制
SMOOTH_WIN = 9       # 中值窗口大小（奇数）
SMOOTH_ALPHA = 0.3   # EWMA 系数（0.0~1.0，越大越跟随）
OUTLIER_TH_M = 0.5  # 离群门限（米），超过则以中值替代

# -------------------- 工具函数 --------------------
# 过滤 ANSI/CSI 控制序列（例如 \x1b[...），避免污染日志/JSON 解析
ANSI_RE = re.compile(r'\x1B\[[0-9;?]*[ -/]*[@-~]')
def strip_ansi(s: str) -> str:
    return ANSI_RE.sub('', s)

def hex5_to_u40(h: str) -> int:
    """把 10位HEX（高位在前）转成 40-bit 无符号整数。"""
    return int(h, 16) & MASK40

def rel40(newer: int, older: int) -> int:
    """40-bit 回绕安全差值 (newer - older)。"""
    return (newer - older) & MASK40

def compute_distance_m(ex: dict):
    """
    使用非对称 DS-TWR 公式计算距离（米）。
    需要 6 戳：tx1, rx1, tx2, rx2, tx3r(优先)/tx3p(回退), rx3（均为 5BHEX）。
    返回 float 或 None
    """
    # tx3 优先用实际发送时间 tx3r；如缺失则回退到计划时间 tx3p
    tx3_hex = ex.get("tx3r", "0000000000")
    if not isinstance(tx3_hex, str) or len(tx3_hex) != 10 or tx3_hex == "0000000000":
        tx3_hex = ex.get("tx3p", "0000000000")

    req = (("tx1",), ("rx1",), ("tx2",), ("rx2",), ("rx3",))
    # 基本字段校验
    for (k,) in req:
        v = ex.get(k, "0000000000")
        if not isinstance(v, str) or len(v) != 10 or v == "0000000000":
            return None
    if not isinstance(tx3_hex, str) or len(tx3_hex) != 10 or tx3_hex == "0000000000":
        return None

    # 将 5B HEX 转为 40-bit 无符号整数（使用 Python 大整数，避免精度损失）
    tx1   = hex5_to_u40(ex["tx1"])
    rx1_a = hex5_to_u40(ex["rx1"])
    tx2_a = hex5_to_u40(ex["tx2"])
    rx2   = hex5_to_u40(ex["rx2"])
    tx3   = hex5_to_u40(tx3_hex)
    rx3_a = hex5_to_u40(ex["rx3"])

    # 先用整数计算所有差值（回绕安全）
    Tround1 = rel40(rx2,  tx1)   # Tag 域：TX1 -> RX2
    Treply2 = rel40(tx3,  rx2)   # Tag 域：RX2 -> TX3
    Treply1 = rel40(tx2_a, rx1_a)  # Anchor 域：RX1 -> TX2
    Tround2 = rel40(rx3_a, tx2_a)  # Anchor 域：TX2 -> RX3

    # 参数合理性检查
    if Tround1 <= 0 or Tround2 <= 0 or Treply1 <= 0 or Treply2 <= 0:
        return None

    # 非对称 DS-TWR 公式（先用整数做乘加，最后一次性转浮点，降低数值抵消）
    num = Tround1 * Tround2 - Treply1 * Treply2
    den = Tround1 + Tround2 + Treply1 + Treply2
    if den <= 0 or num <= 0:
        return None

    dist_m = (num / den) * DWT_TIME_UNITS * C
    return dist_m

# -------------------- 线程：串口读取 → 行队列 --------------------
class SerialReader(threading.Thread):
    def __init__(self, port: str, baud: int, timeout: float, line_q: Queue, stop_evt: threading.Event, start_evt: threading.Event):
        super().__init__(daemon=True)
        self.port = port
        self.baud = baud
        self.timeout = timeout
        self.line_q = line_q
        self.stop_evt = stop_evt
        self.start_evt = start_evt
        self.ser = None
        self.buffer = b''  # 数据缓冲区

    def run(self):
        # 等待启动信号
        while not self.stop_evt.is_set():
            if self.start_evt.wait(timeout=0.1):
                break

        if self.stop_evt.is_set():
            return

        print("\n>>> 正在搜索串口...")
        # 如果没有指定端口，自动搜索
        port_to_use = self.port
        if not port_to_use or port_to_use == "AUTO":
            port_to_use = find_serial_port()
            if not port_to_use:
                print(f"错误：未找到 '{TARGET_DEVICE_NAME}' 设备")
                print("可用的串口设备：")
                ports = serial.tools.list_ports.comports()
                if ports:
                    for p in ports:
                        print(f"  {p.device}: {p.description}")
                else:
                    print("  (无)")
                return
            print(f">>> 找到设备: {port_to_use}")

        print(f">>> 正在打开串口 {port_to_use}...")
        while not self.stop_evt.is_set():
            try:
                if self.ser is None:
                    # 设置串口参数
                    self.ser = serial.Serial(
                        port_to_use,
                        self.baud,
                        timeout=0.1,        # 读取超时（秒），降低以提高响应速度
                        bytesize=serial.EIGHTBITS,
                        parity=serial.PARITY_NONE,
                        stopbits=serial.STOPBITS_ONE,
                        xonxoff=False,      # 关闭软件流控
                        rtscts=False,       # 关闭RTS/CTS
                        dsrdtr=False,       # 关闭DSR/DTR
                        write_timeout=0
                    )
                    # 尝试设置更大的读取缓冲区（如果支持）
                    try:
                        self.ser.set_buffer_size(rx_size=65536)
                    except Exception:
                        pass
                    # 清空启动时可能残留/协商产生的输入数据
                    try:
                        self.ser.reset_input_buffer()
                    except Exception:
                        pass
                    # 小延时，等设备稳定
                    time.sleep(0.05)
                    print(f">>> 串口 {port_to_use} 已打开")
                    if DEBUG_MODE:
                        print(f"[DEBUG] 串口读取线程正在运行，等待数据...")

                # 先检查是否有数据可读
                waiting = self.ser.in_waiting
                if DEBUG_MODE and waiting > 0:
                    print(f"[DEBUG] 检测到 {waiting} 字节待读取")

                if waiting == 0:
                    time.sleep(0.01)  # 短暂休眠，避免 CPU 占用过高
                    continue

                # 直接读取所有可用数据（非阻塞）
                if DEBUG_MODE:
                    print(f"[DEBUG] 读取 {waiting} 字节...")

                line = self.ser.read(waiting)

                if DEBUG_MODE:
                    print(f"[DEBUG] 读取完成")

                if not line:
                    continue

                # 累积到缓冲区
                self.buffer += line

                if DEBUG_MODE:
                    print(f"[DEBUG] 缓冲区累积，当前大小: {len(self.buffer)} 字节")

                # 从缓冲区提取完整的行（以 \n 分隔）
                while b'\n' in self.buffer:
                    pos = self.buffer.find(b'\n')
                    line_data = self.buffer[:pos]  # 不包含 \n
                    self.buffer = self.buffer[pos + 1:]  # 跳过 \n

                    # 去除可能的 \r
                    if line_data.endswith(b'\r'):
                        line_data = line_data[:-1]

                    if DEBUG_MODE:
                        print(f"[DEBUG] 提取完整行: {len(line_data)} 字节")
                        if line_data:
                            print(f"[DEBUG] 行开头: {repr(line_data[:50])}")
                            print(f"[DEBUG] 行末尾: {repr(line_data[-50:])}")

                    if not line_data:
                        if DEBUG_MODE:
                            print(f"[DEBUG] 空行，跳过")
                        continue

                    try:
                        text = line_data.decode('utf-8', errors='ignore').strip()
                        if DEBUG_MODE:
                            print(f"[DEBUG] 解码成功: {len(text)} 字符")
                    except Exception as e:
                        if DEBUG_MODE:
                            print(f"[DEBUG] 解码失败: {e}")
                        continue

                    # 清洗 ANSI 转义
                    text = strip_ansi(text).strip()

                    if not text:
                        if DEBUG_MODE:
                            print(f"[DEBUG] 清洗后为空，跳过")
                        continue

                    if DEBUG_MODE:
                        print(f"[DEBUG] 文本入队: {text[:60]}...")

                    # 入队
                    self.line_q.put(text)

                # 防止缓冲区无限增长
                if len(self.buffer) > 10000:
                    if DEBUG_MODE:
                        print(f"[DEBUG] 警告：缓冲区过大 ({len(self.buffer)} 字节)，保留最后 5000 字节")
                    self.buffer = self.buffer[-5000:]
            except serial.SerialException as e:
                # 串口断开/占用，稍后重试
                print(f"[SerialReader] serial error: {e}", file=sys.stderr)
                time.sleep(0.5)
                self._close()
            except Exception as e:
                print(f"[SerialReader] error: {e}", file=sys.stderr)
                time.sleep(0.1)

        self._close()

    def _close(self):
        if self.ser is not None:
            try:
                self.ser.close()
                print(">>> 串口已关闭")
            except Exception:
                pass
            self.ser = None

# -------------------- 线程：JSON 解析 + 距离计算 --------------------
class Worker(threading.Thread):
    """
    从 line_q 取行：
      - 过滤非 JSON 行
      - 解析 {"role":"tag", "anchors":[...]}
      - 给每个 anchor 计算距离
      - 把结果写入 shared_state（受锁保护）
    """
    def __init__(self, line_q: Queue, state: dict, lock: threading.Lock, stop_evt: threading.Event):
        super().__init__(daemon=True)
        self.line_q = line_q
        self.state = state
        self.lock = lock
        self.stop_evt = stop_evt

    def run(self):
        while not self.stop_evt.is_set():
            try:
                line = self.line_q.get(timeout=0.1)
            except Empty:
                continue

            # 非目标 JSON 行：直接丢弃
            if not line.startswith('{"role":"tag"'):
                # 调试：打印非 JSON 行
                if DEBUG_MODE:
                    print(f"[DEBUG] 接收到非目标行: {line[:80]}")
                continue

            # 调试：打印目标 JSON 行
            if DEBUG_MODE:
                print(f"[DEBUG] 接收到目标 JSON 行，长度: {len(line)} 字符")
                # 检查 JSON 是否完整（应该以 } 结尾）
                if not line.rstrip().endswith('}'):
                    print(f"[DEBUG] 警告：JSON 不完整，末尾20字符: ...{line[-20:]}")

            try:
                obj = json.loads(line)
                # 成功解析后打印统计信息
                if DEBUG_MODE:
                    anchors = obj.get("anchors", [])
                    print(f"[DEBUG] JSON 解析成功，包含 {len(anchors)} 个 anchors")
            except Exception as e:
                # 有时串口会出现拼写/丢括号问题：直接跳过这行
                if DEBUG_MODE:
                    print(f"[DEBUG] JSON 解析失败: {e}")
                    print(f"[DEBUG] 行开头100字符: {line[:100]}")
                    print(f"[DEBUG] 行结尾100字符: ...{line[-100:]}")
                continue

            anchors = obj.get("anchors", [])
            if not isinstance(anchors, list):
                continue

            # 结果容器：aid -> { 'seq': int, 'dist_m': float, 'ex': {...} }
            result = {}
            for a in anchors:
                try:
                    aid = int(a.get("aid"))
                except Exception:
                    if DEBUG_MODE:
                        print(f"[DEBUG] 无法获取 anchor ID")
                    continue
                ex = a.get("ex", {})

                # 只处理 complete==1 的数据
                if ex.get("complete", 0) != 1:
                    if DEBUG_MODE:
                        print(f"[DEBUG] Anchor {aid} 数据不完整 (complete={ex.get('complete', 0)})，跳过")
                    continue

                if DEBUG_MODE:
                    print(f"[DEBUG] 处理 Anchor {aid}, ex 字段: {list(ex.keys())}")

                dist = compute_distance_m(ex)

                if dist is None:
                    if DEBUG_MODE:
                        print(f"[DEBUG] Anchor {aid} 距离计算失败（返回 None）")
                        # 检查时间戳字段
                        for k in ["tx1", "rx1", "tx2", "rx2", "tx3r", "tx3p", "rx3"]:
                            v = ex.get(k, "缺失")
                            print(f"[DEBUG]   {k}: {v}")
                    continue

                if DEBUG_MODE:
                    print(f"[DEBUG] Anchor {aid} 距离计算成功: {dist:.3f}m")

                result[aid] = {
                    "seq": ex.get("seq"),
                    "dist_m": dist,
                    "ex": {k: ex.get(k) for k in ("tx1","rx1","tx2","rx2","tx3r","rx3")}
                }

            if result:
                with self.lock:
                    # 更新共享状态
                    now = time.time()
                    self.state["last_update_ts"] = now
                    # 合并更新每个 anchor 的最新值
                    dstore = self.state.setdefault("anchors", {})
                    for aid, info in result.items():
                        dstore[aid] = info

# -------------------- 命令行输入线程 --------------------
class CommandReader(threading.Thread):
    """在后台读取用户输入的命令"""
    def __init__(self, cmd_q: Queue, stop_evt: threading.Event):
        super().__init__(daemon=True)
        self.cmd_q = cmd_q
        self.stop_evt = stop_evt

    def run(self):
        while not self.stop_evt.is_set():
            try:
                line = input()
                self.cmd_q.put(line.strip())
            except (EOFError, KeyboardInterrupt):
                break
            except Exception:
                pass

# -------------------- 主线程：打印/展示共享对象 --------------------
def main():
    line_q = Queue(maxsize=1000)
    cmd_q = Queue()
    stop_evt = threading.Event()
    serial_start_evt = threading.Event()  # 用于控制串口启动
    lock = threading.Lock()

    # 共享状态结构（线程安全）
    shared_state = {
        "last_update_ts": 0.0,
        "anchors": {}   # aid -> { seq, dist_m, ex{} }
    }

    reader = SerialReader("AUTO", BAUD, TIMEOUT, line_q, stop_evt, serial_start_evt)
    worker = Worker(line_q, shared_state, lock, stop_evt)
    cmd_reader = CommandReader(cmd_q, stop_evt)

    reader.start()
    worker.start()
    cmd_reader.start()

    # 校准模式变量
    calibration_mode = True  # 启动时为校准模式，等待用户输入
    measuring = False  # 是否正在测量
    measure_start_ts = 0.0
    measure_duration = 3.0  # 测量持续时间（秒）
    measure_samples = []  # 当前测量的距离样本
    last_seq = {}  # 记录每个 anchor 最后处理的 seq，避免重复计数
    target_anchor_id = 0  # 要校准的 Anchor ID
    actual_distance = 1.0  # 实际距离，默认 1 米
    serial_started = False  # 串口是否已启动

    # 平滑状态
    hist = {}       # aid -> deque
    smooth = {}     # aid -> 上一次平滑值

    print("")
    print("=" * 60)
    print("UWB 距离测量与校准系统")
    print("=" * 60)
    print(f"目标设备: {TARGET_DEVICE_NAME} (自动搜索)")
    print(f"当前配置文件: {CONFIG_FILE}")
    print(f"默认校准距离: {actual_distance}m")
    print("命令:")
    print("  <Anchor ID>  - 校准指定的 Anchor (例如: 1, 2, 3...)")
    print("  d <距离>     - 设置实际距离 (例如: d 1.5)")
    print("  q            - 退出程序")
    print("  r            - 开始实时监测模式（完成校准后）")
    print("=" * 60)

    try:
        while True:
            # 处理用户命令
            try:
                cmd = cmd_q.get_nowait()
                if cmd.lower() == 'q':
                    print("退出程序...")
                    break
                elif cmd.lower() == 'r':
                    if calibration_mode:
                        calibration_mode = False
                        # 启动串口（如果还未启动）
                        if not serial_started:
                            serial_start_evt.set()
                            serial_started = True
                        print("\n>>> 进入实时监测模式")
                    else:
                        print(">>> 已经在实时监测模式")
                elif cmd.lower().startswith('d '):
                    # 设置实际距离
                    try:
                        dist = float(cmd[2:].strip())
                        if dist <= 0:
                            print("错误：距离必须大于0")
                        else:
                            actual_distance = dist
                            print(f">>> 实际距离已设置为: {actual_distance}m")
                    except ValueError:
                        print("错误：距离格式不正确，例如: d 1.5")
                else:
                    # 尝试解析为 Anchor ID
                    try:
                        aid = int(cmd)
                        if aid <= 0:
                            print("错误：Anchor ID 必须大于0")
                        else:
                            # 启动串口（如果还未启动）
                            if not serial_started:
                                serial_start_evt.set()
                                serial_started = True
                            target_anchor_id = aid
                            measuring = True
                            measure_start_ts = time.time()
                            measure_samples.clear()
                            last_seq.clear()  # 清空 seq 记录
                            print(f"\n>>> 开始校准 Anchor {target_anchor_id}，实际距离: {actual_distance}m，测量时间: {measure_duration}秒...")
                    except ValueError:
                        print(f"未知命令: {cmd}")
            except Empty:
                pass

            with lock:
                anchors_copy = dict(shared_state["anchors"])

            # 校准模式 - 测量中
            if measuring and anchors_copy:
                elapsed = time.time() - measure_start_ts
                if elapsed < measure_duration:
                    # 只收集目标 Anchor 的测量数据
                    if target_anchor_id in anchors_copy:
                        info = anchors_copy[target_anchor_id]
                        seq = info.get('seq')
                        d = info.get('dist_m')

                        # 只有当 seq 改变时才添加新样本（避免重复计数）
                        if isinstance(d, (int, float)) and isinstance(seq, int):
                            if target_anchor_id not in last_seq or last_seq[target_anchor_id] != seq:
                                measure_samples.append(float(d))
                                last_seq[target_anchor_id] = seq
                                if DEBUG_MODE:
                                    print(f"[DEBUG] 新样本: Anchor {target_anchor_id}, seq={seq}, dist={d:.3f}m, 总样本数={len(measure_samples)}")
                else:
                    # 测量完成，计算校准值
                    measuring = False

                    if len(measure_samples) > 0:
                        print("\n测量完成！计算校准参数...")

                        global calib_config, MANUAL_BIAS_PER_ANCHOR_M, MANUAL_SCALE_PER_ANCHOR

                        # 计算平均测量距离
                        avg_measured = sum(measure_samples) / len(measure_samples)
                        # 计算需要的偏置校正
                        bias_correction = avg_measured - actual_distance

                        # 更新配置
                        calib_config["bias"][str(target_anchor_id)] = round(bias_correction, 6)
                        MANUAL_BIAS_PER_ANCHOR_M[target_anchor_id] = bias_correction

                        print(f"  Anchor {target_anchor_id}: 测量={avg_measured:.3f}m, 偏置={bias_correction:.6f}m (样本数={len(measure_samples)})")

                        # 保存配置
                        save_calibration_config(calib_config)
                        print("\n校准完成！可以继续校准其他 Anchor，或输入 'r' 进入实时监测模式")
                        print("=" * 60)
                    else:
                        print(f"\n错误：未收到 Anchor {target_anchor_id} 的数据")
                        print("=" * 60)

            # 实时监测模式
            if not calibration_mode and not measuring and anchors_copy:
                items = sorted(anchors_copy.items(), key=lambda kv: kv[0])
                parts = []
                for aid, info in items:
                    d_raw = float(info.get('dist_m', float('nan')))
                    # 应用配置的偏置
                    b_manual = MANUAL_BIAS_PER_ANCHOR_M.get(aid, 0.0)
                    s_manual = MANUAL_SCALE_PER_ANCHOR.get(aid, 1.0)

                    d_corr = (d_raw - b_manual) * s_manual
                    if d_corr < 0 or not (d_corr == d_corr):  # 负值或 NaN
                        d_corr = 0.0

                    q = hist.setdefault(aid, deque(maxlen=SMOOTH_WIN))
                    q.append(d_corr)
                    # 中值
                    med = sorted(q)[len(q)//2] if q else d_corr
                    prev = smooth.get(aid, med)

                    # 离群抑制
                    x = d_corr
                    if len(q) >= 3 and abs(d_corr - med) > OUTLIER_TH_M and abs(d_corr - prev) > OUTLIER_TH_M:
                        x = med

                    # 指数平滑
                    s = SMOOTH_ALPHA * x + (1.0 - SMOOTH_ALPHA) * prev
                    smooth[aid] = s

                    parts.append(f"{aid}:{s:.3f}")
                print(' '.join(parts))

    except KeyboardInterrupt:
        pass
    finally:
        stop_evt.set()
        reader.join(timeout=1.0)
        worker.join(timeout=1.0)
        cmd_reader.join(timeout=1.0)

if __name__ == "__main__":
    main()
