import socket
import threading
import time
from datetime import datetime

import dirtyjson
import json
import re
import os

# ------------------ 参数配置 ------------------
HOST = "0.0.0.0"
PORT_GOOD = 9000
PORT_BAD = 9001
WATCH_INTERVAL = 10
INPUT_FILE = "input.txt"  # 模拟输入文件
# ---------------------------------------------

good_count = 0
bad_count = 0
fixed_count = 0
last_good_time = time.time()

good_log = open("good_packets.txt", "a", encoding="utf-8")
bad_log = open("bad_packets.txt", "a", encoding="utf-8")

print(f"[INIT] Listening TCP on ports {PORT_GOOD} (GOOD) and {PORT_BAD} (BAD)...")


def try_fix_json(raw: str):
    if not raw or len(raw) < 10:
        return None

    # 粘包检测
    if raw.count('{"role"') > 1 or '}{' in raw:
        return None

    s = raw
    s = re.sub(r'("([^"\\]|\\.)*")\s+("([^"\\]|\\.)*")', r'\1: \3', s)
    s = re.sub(
        r'("([^"\\]|\\.)*")\s+(-?\d+(\.\d+)?([eE][+-]?\d+)?|true|false|null|\[|\{)',
        r'\1: \3',
        s,
    )


    s = re.sub(
        r'(\}|\]|"|[0-9eE\.\-truefalsenull])\s+("([^"\\]|\\.)*"\s*:)',
        r'\1, \2',
        s,
    )


    open_braces = s.count('{')
    close_braces = s.count('}')
    open_brackets = s.count('[')
    close_brackets = s.count(']')

    if open_braces > close_braces:
        s += '}' * (open_braces - close_braces)
    if open_brackets > close_brackets:
        s += ']' * (open_brackets - close_brackets)


    try:
        json.loads(s)
        return s
    except Exception:
        pass
    try:
        obj = dirtyjson.loads(s)
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return None



def process_line(line: str, label="GOOD"):
    global good_count, bad_count, fixed_count, last_good_time
    line = line.strip()
    timestamp = datetime.now().strftime("%H:%M:%S")

    if not line:
        return

    if label == "GOOD":
        good_count += 1
        last_good_time = time.time()
        good_log.write(f"[{timestamp}] {line}\n")
        good_log.flush()
        print(f"[GOOD] {line[:100]}{'...' if len(line) > 100 else ''}")

    else:
        bad_count += 1
        fixed = try_fix_json(line)
        if fixed:
            fixed_count += 1
            good_log.write(f"[FIXED] {timestamp} {fixed}\n")
            good_log.flush()
            print(f" [FIXED] {line[:60]}... → repaired")
        else:
            bad_log.write(f"[{timestamp}] {line}\n")
            bad_log.flush()
            print(f" [BAD] {line[:80]}{'...' if len(line) > 80 else ''}")


def listen_tcp(port, label):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, port))
    srv.listen(5)
    print(f"[{label}] Listening on {port} ...")

    while True:
        conn, addr = srv.accept()
        print(f"[{label}] Connection from {addr}")

        with conn:
            while True:
                data = conn.recv(16384)
                if not data:
                    break
                lines = data.decode(errors="ignore").splitlines()
                for line in lines:
                    process_line(line, label)



def file_input_task():
    if not os.path.exists(INPUT_FILE):
        print(f"[FILE] No {INPUT_FILE} found, skip simulation.")
        return

    print(f"[FILE] Reading from {INPUT_FILE} for simulation...")
    with open(INPUT_FILE, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:

            if '"anchors":[' in line and line.strip().endswith('}'):
                process_line(line, "GOOD")
            else:
                process_line(line, "BAD")
            time.sleep(0.1)

    print("[FILE] Simulation complete.")

# 丢包检测
def watchdog():
    global good_count, bad_count, fixed_count, last_good_time
    while True:
        time.sleep(WATCH_INTERVAL)
        now = time.time()

        if now - last_good_time > WATCH_INTERVAL:
            print("\n⚠️ [WATCHDOG] No GOOD packets in last 10s!")
            print(f"   Possibly LOST {bad_count} packets.")
            print(f"   🔧 FIXED recovered: {fixed_count} / BAD: {bad_count}\n")

            bad_count = 0
            fixed_count = 0



# 启动
t1 = threading.Thread(target=listen_tcp, args=(PORT_GOOD, "GOOD"), daemon=True)
t2 = threading.Thread(target=listen_tcp, args=(PORT_BAD, "BAD"), daemon=True)
t3 = threading.Thread(target=watchdog, daemon=True)
t1.start()
t2.start()
t3.start()

# 文件模拟输入（若存在 input.txt）
t4 = threading.Thread(target=file_input_task, daemon=True)
t4.start()

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\n[EXIT] Closing logs...")
    good_log.close()
    bad_log.close()