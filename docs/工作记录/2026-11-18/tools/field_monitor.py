#!/usr/bin/env python3
"""现场综合监测 — 串口连续性 + RTK 解算质量 + USB 事件

一个进程独占串口，避免多个监测脚本抢数据。

用法:
    python3 field_monitor.py [时长秒] [端口]
默认 3600 秒, /dev/ttyACM3

输出目录: /root/field_logs/<YYYYmmdd_HHMMSS>/
    quality.csv  每秒一行（含串口行率/间隔 + GGA/GSV 解算指标）
    events.log   质量跳变、断流、坏帧、USB 复位
"""
import os
import re
import select
import sys
import termios
import time

PORT = sys.argv[2] if len(sys.argv) > 2 else "/dev/ttyACM3"
DURATION = int(sys.argv[1]) if len(sys.argv) > 1 else 3600
GAP_WARN = 0.5
USB_RE = re.compile(r"usb 5-1|cdc_acm|device descriptor|error -71|over-?current", re.I)

outdir = "/root/field_logs/" + time.strftime("%Y%m%d_%H%M%S")
os.makedirs(outdir, exist_ok=True)
csvf = open(os.path.join(outdir, "quality.csv"), "w", buffering=1)
logf = open(os.path.join(outdir, "events.log"), "w", buffering=1)
csvf.write("time,rate,maxgap,quality,sats,hdop,diff_age,fix_type,ths_valid,heading,"
           "max_snr,avg_snr,lines,bad,usb\n")


def log(msg):
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


def cksum_ok(line):
    if not line.startswith("$") or "*" not in line:
        return False
    body, _, ck = line[1:].rpartition("*")
    try:
        want = int(ck[:2], 16)
    except ValueError:
        return False
    calc = 0
    for ch in body:
        calc ^= ord(ch)
    return calc == want


st = {"quality": None, "sats": None, "hdop": None, "diff_age": None,
      "fix_type": None, "ths_valid": None, "heading": None, "snr": []}


def parse(line):
    f = line.split(",")
    tag = f[0]
    if tag.endswith("GGA") and len(f) > 9:
        st["quality"] = int(f[6]) if f[6].isdigit() else None
        st["sats"] = int(f[7]) if f[7].isdigit() else None
        st["hdop"] = f[8] or None
        if len(f) > 13:
            st["diff_age"] = f[13] or None
    elif tag.endswith("GSA") and len(f) > 2:
        st["fix_type"] = int(f[2]) if f[2].isdigit() else None
    elif tag.endswith("GSV"):
        for i in (7, 11, 15, 19):
            if len(f) > i and f[i].isdigit():
                st["snr"].append(int(f[i]))
    elif tag.endswith("THS") and len(f) > 2:
        st["ths_valid"] = (f[2] == "T")
        try:
            st["heading"] = float(f[1]) if f[1] else None
        except ValueError:
            st["heading"] = None


def main():
    log("start port=%s duration=%ds out=%s" % (PORT, DURATION, outdir))
    fd = open_port()
    kmsg = os.open("/dev/kmsg", os.O_RDONLY | os.O_NONBLOCK)
    while True:
        try:
            if not os.read(kmsg, 1 << 16):
                break
        except OSError:
            break

    buf = b""
    lines = bad = usb = 0
    max_gap = 0.0
    win_lines = 0
    win_max_gap = 0.0
    last_data = None
    win_start = time.time()
    next_tick = win_start + 1.0
    t_end = time.time() + DURATION
    last_q = last_sats = None

    while time.time() < t_end:
        now = time.time()
        r, _, _ = select.select([fd], [], [], 0.05)
        if r:
            try:
                data = os.read(fd, 8192)
            except OSError:
                break
            if data:
                if last_data is not None:
                    gap = now - last_data
                    max_gap = max(max_gap, gap)
                    win_max_gap = max(win_max_gap, gap)
                    if gap > GAP_WARN:
                        log("EVENT gap %.2fs" % gap)
                last_data = now
                buf += data
                while b"\n" in buf:
                    raw, _, buf = buf.partition(b"\n")
                    line = raw.decode("ascii", "replace").strip()
                    if not line:
                        continue
                    lines += 1
                    win_lines += 1
                    if not line.startswith("$"):
                        continue          # 忽略 #HEADINGA 等非 NMEA 日志
                    if cksum_ok(line):
                        parse(line)
                    else:
                        bad += 1
                        log("EVENT bad line: %s" % line[:60])

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
                    usb += 1
                    log("EVENT kmsg: %s" % txt[:150])

        if now >= next_tick:
            dt = now - win_start
            rate = win_lines / dt if dt > 0 else 0
            snr = st["snr"]
            csvf.write("%s,%.1f,%.2f,%s,%s,%s,%s,%s,%s,%s,%s,%s,%d,%d,%d\n" % (
                time.strftime("%H:%M:%S"), rate, win_max_gap, st["quality"], st["sats"],
                st["hdop"], st["diff_age"], st["fix_type"], st["ths_valid"], st["heading"],
                max(snr) if snr else "", round(sum(snr) / len(snr), 1) if snr else "",
                lines, bad, usb))
            if st["quality"] != last_q:
                log("EVENT quality %s -> %s (sats=%s hdop=%s diff=%s)" % (
                    last_q, st["quality"], st["sats"], st["hdop"], st["diff_age"]))
                last_q = st["quality"]
            if st["sats"] is not None and last_sats is not None and st["sats"] < last_sats - 3:
                log("EVENT sats drop %s -> %s" % (last_sats, st["sats"]))
            last_sats = st["sats"]
            st["snr"] = []
            win_lines = 0
            win_max_gap = 0.0
            win_start = now
            next_tick += 1.0

    log("end lines=%d bad=%d usb=%d maxgap=%.2f" % (lines, bad, usb, max_gap))
    print("done ->", outdir)


if __name__ == "__main__":
    main()
