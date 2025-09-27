#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import sys
import time
import threading
from queue import Queue, Empty
from collections import deque
from collections import deque

import serial  # pip install pyserial
import re

# -------------------- 常量（与固件一致） --------------------
C = 299_702_547.0                     # m/s
DWT_TIME_UNITS = 1.0 / (499.2e6 * 128.0)
MASK40 = (1 << 40) - 1

# 串口配置
PORT = "COM5"
BAUD = 2000000
TIMEOUT = 0.2      # 读超时（秒），用于线程可中断

# 启动后自动零距标定时长（秒）：在这段时间内统计每个 anchor 的平均偏置并用于后续扣除
CALIB_SECS = 2.0

# 平滑与离群值抑制
SMOOTH_WIN = 3       # 中值窗口大小（奇数）
SMOOTH_ALPHA = 0.9   # EWMA 系数（0.0~1.0，越大越跟随）
OUTLIER_TH_M = 0.5   # 离群门限（米），超过则以中值替代

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
    def __init__(self, port: str, baud: int, timeout: float, line_q: Queue, stop_evt: threading.Event):
        super().__init__(daemon=True)
        self.port = port
        self.baud = baud
        self.timeout = timeout
        self.line_q = line_q
        self.stop_evt = stop_evt
        self.ser = None

    def run(self):
        while not self.stop_evt.is_set():
            try:
                if self.ser is None:
                    self.ser = serial.Serial(
                        self.port,
                        self.baud,
                        timeout=self.timeout,
                        bytesize=serial.EIGHTBITS,
                        parity=serial.PARITY_NONE,
                        stopbits=serial.STOPBITS_ONE,
                        xonxoff=False,      # 关闭软件流控
                        rtscts=False,       # 关闭RTS/CTS
                        dsrdtr=False,       # 关闭DSR/DTR
                        write_timeout=0
                    )
                    # 清空启动时可能残留/协商产生的输入数据
                    try:
                        self.ser.reset_input_buffer()
                    except Exception:
                        pass
                    # 小延时，等设备稳定
                    time.sleep(0.05)
                line = self.ser.readline()  # 读一行（以 \n 结束），bytes
                if not line:
                    continue
                try:
                    text = line.decode('utf-8', errors='ignore').strip()
                except Exception:
                    continue
                # 清洗 ANSI 转义，过滤空行
                text = strip_ansi(text).strip()
                if not text:
                    continue
                # 将非空文本全部入队，由工作线程决定如何处理（JSON/非JSON）
                self.line_q.put(text)
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

            # 非目标 JSON 行：直接丢弃（不打印）
            if not line.startswith('{"role":"tag"'):
                continue

            try:
                obj = json.loads(line)
            except Exception:
                # 有时串口会出现拼写/丢括号问题：直接跳过这行
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
                    continue
                ex = a.get("ex", {})
                # 可选：只在字段 complete==1 时计算
                # 如果你希望不管 complete 与否，只要 6 戳齐了就算，可以不看 complete
                dist = compute_distance_m(ex)
                if dist is None:
                    continue
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

# -------------------- 主线程：打印/展示共享对象 --------------------
def main():
    line_q = Queue(maxsize=1000)
    stop_evt = threading.Event()
    lock = threading.Lock()

    # 共享状态结构（线程安全）
    shared_state = {
        "last_update_ts": 0.0,
        "anchors": {}   # aid -> { seq, dist_m, ex{} }
    }

    reader = SerialReader(PORT, BAUD, TIMEOUT, line_q, stop_evt)
    worker = Worker(line_q, shared_state, lock, stop_evt)

    reader.start()
    worker.start()

    try:
        # 周期性打印各 anchor 的距离（带零距偏置抵消 + 平滑过滤）
        start_ts = time.time()
        bias_sum = {}   # aid -> 累计和
        bias_cnt = {}   # aid -> 计数
        bias     = {}   # aid -> learned bias
        calibrated = False

        # 平滑状态
        hist = {}       # aid -> deque
        smooth = {}     # aid -> 上一次平滑值

        while True:
            time.sleep(0.5)
            with lock:
                anchors_copy = dict(shared_state["anchors"])

            now = time.time()
            if not calibrated and anchors_copy:
                # 统计启动阶段的零距偏置
                for aid, info in anchors_copy.items():
                    d = info.get('dist_m')
                    if isinstance(d, (int, float)):
                        bias_sum[aid] = bias_sum.get(aid, 0.0) + float(d)
                        bias_cnt[aid] = bias_cnt.get(aid, 0) + 1
                if (now - start_ts) >= CALIB_SECS and bias_cnt:
                    # 计算每个 anchor 的平均偏置
                    for aid, cnt in bias_cnt.items():
                        if cnt > 0:
                            bias[aid] = bias_sum.get(aid, 0.0) / float(cnt)
                    calibrated = True

            if anchors_copy:
                # 仅输出距离，格式：aid:dist_m（米，三位小数），按 aid 升序
                items = sorted(anchors_copy.items(), key=lambda kv: kv[0])
                parts = []
                for aid, info in items:
                    d_raw = float(info.get('dist_m', float('nan')))
                    b = bias.get(aid, 0.0) if calibrated else 0.0
                    d_corr = d_raw - b
                    if d_corr < 0 or not (d_corr == d_corr):  # 负值或 NaN
                        d_corr = 0.0

                    q = hist.setdefault(aid, deque(maxlen=SMOOTH_WIN))
                    q.append(d_corr)
                    # 中值
                    med = sorted(q)[len(q)//2] if q else d_corr
                    prev = smooth.get(aid, med)

                    # 离群抑制：同时偏离中值与上次平滑都大于门限，则用中值替代本次观测
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

if __name__ == "__main__":
    main()
