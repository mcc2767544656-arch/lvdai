#!/usr/bin/env python3
"""路线记录 — 读取 KSXT 10Hz，写成回放图可用的 CSV

用法: python3 record_route.py [输出文件]
停止: Ctrl-C 或 touch /tmp/stop_record
输出列: lat,lon,alt,heading,timestamp
"""
import glob
import os
import select
import signal
import sys
import termios
import time

OUT = sys.argv[1] if len(sys.argv) > 1 else "/root/field/route_%s.csv" % time.strftime("%Y%m%d_%H%M")
STOP = "/tmp/stop_record"
running = True


def _stop(*_):
    global running
    running = False


signal.signal(signal.SIGTERM, _stop)
signal.signal(signal.SIGINT, _stop)


def open_port():
    p = os.path.realpath(glob.glob("/dev/serial/by-id/*if06")[0])
    fd = os.open(p, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    a = termios.tcgetattr(fd)
    a[0] = a[1] = a[3] = 0
    a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
    a[4] = a[5] = termios.B115200
    a[6][termios.VMIN] = 0
    a[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW, a)
    return fd, p


def main():
    if os.path.exists(STOP):
        os.remove(STOP)
    fd, port = open_port()
    f = open(OUT, "w", buffering=1)
    f.write("lat,lon,alt,heading,timestamp\n")
    print("recording port=%s -> %s" % (port, OUT), flush=True)
    buf = b""
    n = 0
    t0 = time.time()
    last_q = None
    while running and not os.path.exists(STOP):
        r, _, _ = select.select([fd], [], [], 0.3)
        if not r:
            continue
        try:
            buf += os.read(fd, 8192)
        except OSError:
            time.sleep(0.3)
            try:
                fd, port = open_port()
            except OSError:
                continue
            continue
        while b"\n" in buf:
            raw, _, buf = buf.partition(b"\n")
            s = raw.decode("ascii", "replace").strip()
            if not s.startswith("$KSXT"):
                continue
            p = s.split("*")[0].split(",")
            if len(p) < 14:
                continue
            try:
                lat, lon, alt = float(p[3]), float(p[2]), float(p[4])
                hdg = float(p[5]) if p[5] else 0.0
                q = int(p[10]) if p[10] else -1
            except ValueError:
                continue
            f.write("%.8f,%.8f,%.2f,%.2f,%.3f\n" % (lat, lon, alt, hdg, time.time()))
            n += 1
            if q != last_q:
                last_q = q
            if n % 10 == 0 and n % 100 == 0:
                print("points=%d  %.0fs" % (n, time.time() - t0), flush=True)
    f.close()
    print("stopped. points=%d duration=%.1fs file=%s" % (n, time.time() - t0, OUT), flush=True)


if __name__ == "__main__":
    main()
