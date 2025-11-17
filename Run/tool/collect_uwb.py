#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
收集固件通过串口输出的 JSON 行, 展平为 CSV 以便后续训练。
- 支持两种输入：
  1) 直接从串口读取 (需要安装 pyserial)
  2) 从文件或 stdin 读取（每行一个 JSON）

用法示例：
1) 从串口读取并保存：
   python collect_uwb.py --serial COM5 --baud 115200 --out data.csv

2) 从已有的日志文件读取：
   python collect_uwb.py --in log.txt --out data.csv

CSV 列包含：time_ms, role, tag, aid, seq, complete, dt_us_*, qual.cia, qual.ipatov.* 等。
"""
import argparse
import json
import sys
from datetime import datetime

try:
    import serial  # type: ignore
except Exception:  # noqa: E722
    serial = None


def parse_args():
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument('--serial', help='串口号，例如 COM5 或 /dev/ttyUSB0')
    g.add_argument('--in', dest='infile', help='输入文件路径（或使用 - 表示 STDIN）')
    p.add_argument('--baud', type=int, default=115200)
    p.add_argument('--out', required=True, help='输出 CSV 路径')
    return p.parse_args()


def open_input(args):
    if args.infile:
        if args.infile == '-' or args.infile.lower() == 'stdin':
            return sys.stdin
        return open(args.infile, 'r', encoding='utf-8', errors='ignore')
    if args.serial:
        if serial is None:
            raise SystemExit('未安装 pyserial，请先 pip install pyserial')
        return serial.Serial(args.serial, args.baud, timeout=1)
    raise SystemExit('缺少输入源')


def iter_lines(src):
    if hasattr(src, 'readline') and not hasattr(src, 'read'):  # pyserial
        while True:
            line = src.readline()
            if not line:
                continue
            if isinstance(line, (bytes, bytearray)):
                line = line.decode('utf-8', errors='ignore')
            yield line
    else:
        for line in src:
            yield line


def flatten_record(js):
    role = js.get('role')
    tag = js.get('tag')
    tick = js.get('tick')

    anchors = js.get('anchors') or []
    rows = []
    for a in anchors:
        aid = a.get('aid')
        ex = a.get('ex') or {}
        dt = a.get('dt_us') or {}
        q = a.get('qual') or {}
        ip = (q.get('ipatov') or {})

        rows.append({
            'time_ms': tick,
            'role': role,
            'tag': tag,
            'aid': aid,
            'seq': ex.get('seq'),
            'complete': ex.get('complete'),
            'dt_tx1_rx2': dt.get('tx1_rx2'),
            'dt_rx2_tx3p': dt.get('rx2_tx3p'),
            'dt_rx2_tx3r': dt.get('rx2_tx3r'),
            'qual_cia': q.get('cia'),
            'qual_xo': q.get('xo'),
            'ipatov_peak': ip.get('peak'),
            'ipatov_pwr': ip.get('pwr'),
            'ipatov_fp_idx': ip.get('fp_idx'),
            'ipatov_acc': ip.get('acc'),
        })
    return rows


def main():
    args = parse_args()
    src = open_input(args)

    import csv
    try:
        with open(args.out, 'w', newline='', encoding='utf-8') as fout:
            fieldnames = [
                'time_ms','role','tag','aid','seq','complete',
                'dt_tx1_rx2','dt_rx2_tx3p','dt_rx2_tx3r',
                'qual_cia','qual_xo','ipatov_peak','ipatov_pwr','ipatov_fp_idx','ipatov_acc'
            ]
            w = csv.DictWriter(fout, fieldnames=fieldnames)
            w.writeheader()

            for line in iter_lines(src):
                line = line.strip()
                if not line:
                    continue
                if line.startswith('{') and line.endswith('}'):  # 粗略过滤
                    try:
                        js = json.loads(line)
                    except Exception:
                        continue
                    if js.get('role') != 'tag':
                        continue
                    rows = flatten_record(js)
                    for r in rows:
                        w.writerow(r)
                        fout.flush()
    finally:
        # 确保关闭输入源（除了stdin）
        if hasattr(src, 'close') and src != sys.stdin:
            src.close()


if __name__ == '__main__':
    main()
