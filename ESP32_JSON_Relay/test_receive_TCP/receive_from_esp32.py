import socket, time, argparse

ap = argparse.ArgumentParser()
ap.add_argument("--ip", default="172.20.10.3")
ap.add_argument("--port", type=int, default=9001)   # 9000=GOOD, 9001=BAD
ap.add_argument("--outfile", default="received_data.txt")
ap.add_argument("--timeout", type=float, default=1.0)  # 秒，避免永久阻塞
args = ap.parse_args()

def connect(ip, port, timeout):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)  # 关键：让 recv 可被超时打断
    s.connect((ip, port))
    s.settimeout(timeout)
    return s

print(f"Connecting to ESP32 {args.ip}:{args.port} ...")
sock = connect(args.ip, args.port, args.timeout)
print("Connected! Receiving...  (Ctrl+C to stop)")

count = 0
with open(args.outfile, "w", encoding="utf-8") as f:
    try:
        while True:
            try:
                data = sock.recv(4096)
                if not data:
                    print("\nDisconnected by peer.")
                    break
                text = data.decode("utf-8", errors="ignore")
                print(text, end="")
                f.write(text)
                f.flush()
                count += len(text)
            except socket.timeout:
                # 没数据时每秒醒来一次，允许 Ctrl+C 打断
                pass
    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        sock.close()
print(f"Saved to: {args.outfile}")
