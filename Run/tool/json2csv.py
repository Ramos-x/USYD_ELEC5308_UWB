#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
将串口(或文件)输出的 JSON 日志转换为用于训练的 CSV。
满足需求：
1) 支持直接从 COM5 以 2,000,000 波特率读取；也可从文件/STDIN 读取。
2) 每条 CSV 为单行，格式为 [distance1,(qual), distance2,(qual), ..., distance5,(qual)]，
   其中 (qual) = [peak, pwr, fp_idx, acc, xo]，均取自对应 anchor 的 qual 字段。

用法：
  1) 从串口读取（默认 COM5, 2000000）：
     python json2csv.py --serial COM5 --baud 2000000 --out out.csv
  2) 从文件或 STDIN 读取：
     python json2csv.py --in log.txt --out out.csv
     type log.txt | python json2csv.py --in - --out out.csv

说明：
  - 每行一个 JSON，与示例中的结构一致：{ role, tag, tick, anchor_count, anchors: [...] }
  - 距离使用非对称 DS-TWR 公式，基于 ex 中的 40-bit 时间戳（5 字节 HEX）。
  - 对每个 anchor (aid=1..5) 单独输出其距离与对应的 (peak,pwr,fp_idx,acc,xo)。
"""
import argparse
import json
import sys
import csv
import re
from typing import Optional, Dict, Any, List
import os

try:
    import serial  # type: ignore
    try:
        import serial.tools.list_ports as _list_ports  # type: ignore
    except Exception:  # noqa: E722
        _list_ports = None
except Exception:  # noqa: E722
    serial = None
    _list_ports = None

# 物理常量与 DW1000 时间单位
C = 299_792_458.0  # m/s
DWT_TIME_UNITS = 1.0 / (499.2e6 * 128.0)  # ≈ 15.65e-12 s
MASK40 = (1 << 40) - 1
ANSI_RE = re.compile(r"\x1B\[[0-9;?]*[ -/]*[@-~]")


def strip_ansi(s: str) -> str:
    return ANSI_RE.sub('', s)


def hex5_to_u40(h: str) -> int:
    return int(h, 16) & MASK40


def rel40(newer: int, older: int) -> int:
    return (newer - older) & MASK40


def compute_distance_m(ex: Dict[str, Any]) -> Optional[float]:
    """使用非对称 DS-TWR 公式计算距离（单位：米）。需要 ex 中提供：
    tx1, rx1, tx2, rx2, tx3r(优先)/tx3p, rx3（均为 10 位 HEX 字符串）。
    返回 float（米）或 None（无效/缺失）。
    """
    if not isinstance(ex, dict):
        return None

    # tx3 优先使用实际发送时间 tx3r；若无则回退到 tx3p
    tx3_hex = ex.get("tx3r", "0000000000")
    if not isinstance(tx3_hex, str) or len(tx3_hex) != 10 or tx3_hex == "0000000000":
        tx3_hex = ex.get("tx3p", "0000000000")

    # 基本字段校验
    req_keys = ("tx1", "rx1", "tx2", "rx2", "rx3")
    for k in req_keys:
        v = ex.get(k, "0000000000")
        if not isinstance(v, str) or len(v) != 10 or v == "0000000000":
            return None
    if not isinstance(tx3_hex, str) or len(tx3_hex) != 10 or tx3_hex == "0000000000":
        return None

    # 转换为 40-bit 无符号整数
    tx1   = hex5_to_u40(ex["tx1"])    # Tag 域起点
    rx1_a = hex5_to_u40(ex["rx1"])    # Anchor 收到 tx1
    tx2_a = hex5_to_u40(ex["tx2"])    # Anchor 回复
    rx2   = hex5_to_u40(ex["rx2"])    # Tag 收到 tx2
    tx3   = hex5_to_u40(tx3_hex)        # Tag 发起第三次
    rx3_a = hex5_to_u40(ex["rx3"])    # Anchor 收到 tx3

    # 回绕安全差值（均为设备时钟计数，不是秒）
    Tround1 = rel40(rx2,  tx1)     # Tag 域：TX1 -> RX2
    Treply2 = rel40(tx3,  rx2)     # Tag 域：RX2 -> TX3
    Treply1 = rel40(tx2_a, rx1_a)  # Anchor 域：RX1 -> TX2
    Tround2 = rel40(rx3_a, tx2_a)  # Anchor 域：TX2 -> RX3

    # 有效性检查
    if Tround1 <= 0 or Tround2 <= 0 or Treply1 <= 0 or Treply2 <= 0:
        return None

    # 非对称 DS-TWR
    num = Tround1 * Tround2 - Treply1 * Treply2
    den = Tround1 + Tround2 + Treply1 + Treply2
    if den <= 0 or num <= 0:
        return None

    time_s = (num / den) * DWT_TIME_UNITS
    return time_s * C


def best_quality_anchor(anchors: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """选择质量字段来源的“最佳”锚点：
    1) 优先 ex.complete == 1
    2) 否则选择 ipatov.peak 最大者
    返回锚点字典或 None
    """
    if not anchors:
        return None
    complete_ones = [a for a in anchors if ((a.get('ex') or {}).get('complete') == 1)]
    if complete_ones:
        return complete_ones[0]
    # 回退：peak 最大
    def peak_of(a):
        q = a.get('qual') or {}
        ip = q.get('ipatov') or {}
        return ip.get('peak') or 0
    return max(anchors, key=peak_of)


def process_record(js: Dict[str, Any]) -> Optional[List[Any]]:
    """处理一条 JSON 记录，输出一行 CSV 列值。
    返回列表：[d1,peak1,pwr1,fp_idx1,acc1,xo1, ..., d5,peak5,pwr5,fp_idx5,acc5,xo5]
    若该记录无有效信息则返回 None
    """
    if js.get('role') != 'tag':
        return None

    anchors = js.get('anchors') or []

    # 预分配结果（aid=1..5）
    d_by_aid = {aid: None for aid in (1, 2, 3, 4, 5)}
    q_by_aid = {aid: {'peak': None, 'pwr': None, 'fp_idx': None, 'acc': None, 'xo': None} for aid in (1,2,3,4,5)}

    for a in anchors:
        aid = a.get('aid')
        if not isinstance(aid, int) or aid not in d_by_aid:
            continue
        ex = a.get('ex') or {}
        dist = compute_distance_m(ex)
        d_by_aid[aid] = dist
        q = a.get('qual') or {}
        ip = q.get('ipatov') or {}
        q_by_aid[aid] = {
            'peak': ip.get('peak'),
            'pwr': ip.get('pwr'),
            'fp_idx': ip.get('fp_idx'),
            'acc': ip.get('acc'),
            'xo': q.get('xo')
        }

    # 组装输出顺序：对每个 aid 依次 (d, peak, pwr, fp_idx, acc, xo)
    row: List[Any] = []
    for aid in (1, 2, 3, 4, 5):
        qa = q_by_aid[aid]
        d_val = d_by_aid[aid] if d_by_aid[aid] is not None else 0
        row.extend([d_val, qa['peak'], qa['pwr'], qa['fp_idx'], qa['acc'], qa['xo']])

    # 仅当至少一个“距离”有效时才输出（剔除只有质检字段但无距离的记录）
    has_distance = any(d_by_aid[aid] is not None for aid in (1, 2, 3, 4, 5))
    if has_distance:
        return row
    return None


def iter_lines(src, is_serial: bool=False):
    if is_serial:
        # 逐行读取串口
        while True:
            line = src.readline()
            if not line:
                continue
            if isinstance(line, (bytes, bytearray)):
                line = line.decode('utf-8', errors='ignore')
            line = strip_ansi(line.strip())
            if not line:
                continue
            yield line
    else:
        for line in src:
            if isinstance(line, (bytes, bytearray)):
                line = line.decode('utf-8', errors='ignore')
            line = strip_ansi(line.strip())
            if not line:
                continue
            yield line


def parse_args():
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument('--in', dest='infile', help='输入文件路径，或 - 表示 STDIN')
    g.add_argument('--serial', dest='serial_port', nargs='?', const='COM5', help='串口号，默认 COM5')
    p.add_argument('--baud', type=int, default=2000000, help='串口波特率，默认 2000000')
    p.add_argument('--out', required=True, help='输出 CSV 路径')
    p.add_argument('--delimiter', default=',', help='CSV 分隔符，默认 ,')
    p.add_argument('--count', type=int, default=None, help='收集的最大行数（仅统计成功写入的记录）。缺省为不限；交互模式默认 1000')
    return p.parse_args()


def open_input(args):
    if getattr(args, 'infile', None):
        if args.infile == '-' or str(args.infile).lower() == 'stdin':
            return sys.stdin, False
        return open(args.infile, 'r', encoding='utf-8', errors='ignore'), False
    if getattr(args, 'serial_port', None):
        if serial is None:
            raise SystemExit('未安装 pyserial，请先 pip install pyserial')
        ser = serial.Serial(args.serial_port or 'COM5', args.baud, timeout=1)
        return ser, True
    raise SystemExit('缺少输入源 (--in 或 --serial)')


def _prompt_with_default(prompt: str, default: str) -> str:
    s = input(f"{prompt} [{default}]: ").strip()
    return s if s else default


def _interactive_args():
    class _NS:
        pass
    ns = _NS()

    print("=== JSON → CSV 交互模式 ===")
    print("选择输入源：")
    print("  1) 串口 (Serial)")
    print("  2) 文件 (File)")
    print("  3) 标准输入 (STDIN)")
    choice = input("请输入选项编号 (1/2/3) [1]: ").strip() or '1'

    if choice == '1':
        ns.infile = None
        # 列出可用串口
        default_port = 'COM5'
        if _list_ports is not None:
            ports = list(_list_ports.comports())
            if ports:
                print("检测到以下串口：")
                for p in ports:
                    print(f"  {p.device}: {getattr(p, 'description', '')}")
                if any(p.device == 'COM5' for p in ports):
                    default_port = 'COM5'
                else:
                    default_port = ports[0].device
        ns.serial_port = _prompt_with_default("请输入串口号", default_port)
        baud = _prompt_with_default("请输入波特率", "2000000")
        try:
            ns.baud = int(baud)
        except Exception:
            ns.baud = 2000000
    elif choice == '2':
        ns.serial_port = None
        ns.baud = 2000000
        while True:
            path = input("请输入输入文件路径: ").strip()
            if path and os.path.isfile(path):
                ns.infile = path
                break
            print("路径无效，请重试。")
    else:
        ns.serial_port = None
        ns.baud = 2000000
        ns.infile = '-'

    ns.out = _prompt_with_default("请输入输出 CSV 文件名(保存到当前目录)", "out.csv")
    # 强制输出到当前工作目录
    ns.out = os.path.join(os.getcwd(), os.path.basename(ns.out))
    ns.delimiter = _prompt_with_default("请输入分隔符", ",")
    cnt = _prompt_with_default("请输入收集条数", "1000")
    try:
        ns.count = int(cnt)
    except Exception:
        ns.count = 1000
    print(f"将输出保存到: {ns.out}")
    return ns


def main():
    # 无参数时进入交互模式
    if len(sys.argv) <= 1:
        args = _interactive_args()
    else:
        args = parse_args()

    # 打开输入
    src, is_serial = open_input(args)

    # 打开输出
    fout = open(args.out, 'w', newline='', encoding='utf-8')
    w = csv.writer(fout, delimiter=args.delimiter)

    # 写表头：对每个 anchor 输出 d,peak,pwr,fp_idx,acc,xo
    header: List[str] = []
    for aid in (1, 2, 3, 4, 5):
        prefix = f'a{aid}'
        header.extend([f'{prefix}_m', f'{prefix}_peak', f'{prefix}_pwr', f'{prefix}_fp_idx', f'{prefix}_acc', f'{prefix}_xo'])
    w.writerow(header)

    # 最大收集条数（仅统计成功写入的记录）
    max_rows = getattr(args, 'count', None)
    written = 0

    for line in iter_lines(src, is_serial):
        if not (line.startswith('{') and line.endswith('}')):
            continue
        try:
            js = json.loads(line)
        except Exception:
            continue
        row = process_record(js)
        if row is not None:
            w.writerow(row)
            fout.flush()
            written += 1
            if max_rows is not None and written >= max_rows:
                print(f"已收集 {written} 条，停止。")
                break

    fout.close()
    try:
        if hasattr(src, 'close'):
            src.close()
    except Exception:
        pass


if __name__ == '__main__':
    main()
