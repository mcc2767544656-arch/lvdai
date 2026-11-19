#!/usr/bin/env python3
"""EMI 干扰监测 — RTK 串口连续性 / NMEA 校验 / USB 内核事件 / 无线链路

串口读取循环不做任何阻塞调用；ping/iw 在独立线程里，避免测量自身造成断流。
输出: /tmp/emi_monitor.log
"""
import os
import re
import select
import subprocess
import sys
import termios
import threading
import time

PORT = "/dev/ttyACM3"
LOG_PATH = "/tmp/emi_monitor.log"
DURATION = int(sys.argv[1]) if len(sys.argv) > 1 else 1800
SNAP_PERIOD = 2.0
GAP_WARN = 0.5
GW = "10.248.67.213"

logf = open(LOG_PATH, "w", buffering=1)
net = {"wifi": None, "ping": None}
stop_flag = threading.Event()


def w(msg):
    logf.write("%s %s\n" % (time.strftime("%H:%M:%S"), msg))


def open_port():
    fd = os.open(PORT, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    a = termios.tcgetattr(fd)
    a[0] = a[1] = a[3] = 0
    a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
    a[4] = a[5] = termios.B115200
    a[6][termios.VMIN] = 0
    a[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW, a)
    return fd


def nmea_ok(line):
    if not line.startswith("$") or "*" not in line:
        return None
    body, _, ck = line[1:].rpartition("*")
    try:
        want = int(ck[:2], 16)
    except ValueError:
        return False
    calc = 0
    for ch in body:
        calc ^= ord(ch)
    return calc == want


def wifi_dbm():
    try:
        out = subprocess.run(["iw", "dev", "wlan0", "link"], capture_output=True,
                             text=True, timeout=2).stdout
        m = re.search(r"signal:\s*(-\d+)", out)
        return int(m.group(1)) if m else None
    except Exception:
        return None


def ping_ms():
    try:
        out = subprocess.run(["ping", "-c", "1", "-W", "1", GW], capture_output=True,
                             text=True, timeout=2).stdout
        m = re.search(r"time=([\d.]+)", out)
        return float(m.group(1)) if m else None
    except Exception:
        return None


def net_probe():
    time.sleep(1.0)
    while not stop_flag.is_set():
        net["wifi"] = wifi_dbm()
        net["ping"] = ping_ms()
        time.sleep(2.0)


USB_RE = re.compile(r"usb 5-1|cdc_acm|device descriptor|error -71|over-?current", re.I)


def main():
    w("=== EMI monitor start, duration=%ds, port=%s ===" % (DURATION, PORT))
    fd = open_port()
    kmsg = os.open("/dev/kmsg", os.O_RDONLY | os.O_NONBLOCK)
    while True:  # 排空历史
        try:
            if not os.read(kmsg, 1 << 16):
                break
        except OSError:
            break

    # 串口预热 2 秒（丢弃启动时的积压数据）
    warm = time.time() + 2.0
    while time.time() < warm:
        try:
            r, _, _ = select.select([fd], [], [], 0.05)
            if r:
                os.read(fd, 8192)
        except OSError:
            break
    w("warmup done, baseline start")

    threading.Thread(target=net_probe, daemon=True).start()

    buf = b""
    lines = 0
    bad_crc = 0
    max_gap = 0.0
    win_max_gap = 0.0
    last_data_t = None
    usb_events = 0
    reconnects = 0
    win_lines = 0
    win_start = time.time()
    next_snap = time.time() + SNAP_PERIOD
    t_end = time.time() + DURATION

    while time.time() < t_end:
        now = time.time()
        try:
            r, _, _ = select.select([fd], [], [], 0.05)
        except (OSError, ValueError):
            r = []

        if r:
            try:
                data = os.read(fd, 8192)
            except OSError:
                data = b""
                fd = None
            if data:
                if last_data_t is not None:
                    gap = now - last_data_t
                    if gap > max_gap:
                        max_gap = gap
                    if gap > win_max_gap:
                        win_max_gap = gap
                    if gap > GAP_WARN:
                        w("EVENT serial gap %.2fs (连续数据中断)" % gap)
                last_data_t = now
                buf += data
                while b"\n" in buf:
                    raw, _, buf = buf.partition(b"\n")
                    line = raw.decode("ascii", "replace").strip()
                    if not line:
                        continue
                    lines += 1
                    win_lines += 1
                    if nmea_ok(line) is False:
                        bad_crc += 1
                        w("EVENT bad checksum: %s" % line[:80])

        if fd is None:
            reconnects += 1
            w("EVENT serial reopen #%d" % reconnects)
            time.sleep(0.5)
            try:
                fd = open_port()
            except OSError as e:
                w("EVENT reopen failed: %s" % e)
                time.sleep(1.0)

        while True:
            try:
                raw = os.read(kmsg, 8192)
            except OSError:
                break
            if not raw:
                break
            for part in raw.split(b"\n"):
                txt = part.decode("utf-8", "replace")
                if USB_RE.search(txt):
                    usb_events += 1
                    w("EVENT kmsg: %s" % txt[:160])

        if now >= next_snap:
            dt = now - win_start
            rate = win_lines / dt if dt > 0 else 0.0
            w("rate=%.1f/s lines=%d winmaxgap=%.2fs maxgap=%.2fs bad=%d usbev=%d recon=%d wifi=%s ping=%s"
              % (rate, lines, win_max_gap, max_gap, bad_crc, usb_events, reconnects,
                 net["wifi"], net["ping"]))
            win_lines = 0
            win_max_gap = 0.0
            win_start = now
            next_snap = now + SNAP_PERIOD

    stop_flag.set()
    w("=== EMI monitor end: lines=%d maxgap=%.2fs bad=%d usb_events=%d reconnects=%d ==="
      % (lines, max_gap, bad_crc, usb_events, reconnects))


if __name__ == "__main__":
    main()
