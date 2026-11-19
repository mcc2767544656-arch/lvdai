#!/usr/bin/env python3
"""RTK 解算层质量监测 — GGA 质量/差分龄期/星数/SNR/航向有效性

用法: python3 rtk_quality_monitor.py [时长秒] [端口]
输出: /tmp/rtk_quality.csv  (每秒一行) 与 /tmp/rtk_quality.log (事件)
"""
import os
import re
import select
import sys
import termios
import time

PORT = sys.argv[2] if len(sys.argv) > 2 else "/dev/ttyACM3"
DURATION = int(sys.argv[1]) if len(sys.argv) > 1 else 1800
CSV_PATH = "/tmp/rtk_quality.csv"
LOG_PATH = "/tmp/rtk_quality.log"

csvf = open(CSV_PATH, "w", buffering=1)
logf = open(LOG_PATH, "w", buffering=1)
csvf.write("time,quality,sats,hdop,diff_age,fix_type,ths_valid,heading,max_snr,avg_snr\n")


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


state = {
    "quality": None, "sats": None, "hdop": None, "diff_age": None,
    "fix_type": None, "ths_valid": None, "heading": None,
    "snr": [],
}


def parse(line):
    f = line.split(",")
    tag = f[0]
    if tag.endswith("GGA") and len(f) > 9:
        state["quality"] = int(f[6]) if f[6].isdigit() else None
        state["sats"] = int(f[7]) if f[7].isdigit() else None
        state["hdop"] = f[8] or None
        if len(f) > 13:
            state["diff_age"] = f[13] or None
    elif tag.endswith("GSA") and len(f) > 2:
        state["fix_type"] = int(f[2]) if f[2].isdigit() else None
    elif tag.endswith("GSV"):
        # 只取信噪比字段，容忍多语句
        for i in (7, 11, 15, 19):
            if len(f) > i and f[i].isdigit():
                state["snr"].append(int(f[i]))
    elif tag.endswith("THS") and len(f) > 2:
        state["ths_valid"] = (f[2] == "T")
        try:
            state["heading"] = float(f[1]) if f[1] else None
        except ValueError:
            state["heading"] = None


def main():
    log("start port=%s duration=%ds" % (PORT, DURATION))
    fd = open_port()
    buf = b""
    t_end = time.time() + DURATION
    next_tick = time.time()
    last_q = None
    last_sats = None

    while time.time() < t_end:
        r, _, _ = select.select([fd], [], [], 0.05)
        if r:
            try:
                buf += os.read(fd, 8192)
            except OSError:
                break
            while b"\n" in buf:
                raw, _, buf = buf.partition(b"\n")
                line = raw.decode("ascii", "replace").strip()
                if line and cksum_ok(line):
                    parse(line)

        now = time.time()
        if now >= next_tick:
            snr = state["snr"]
            max_snr = max(snr) if snr else ""
            avg_snr = round(sum(snr) / len(snr), 1) if snr else ""
            csvf.write("%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n" % (
                time.strftime("%H:%M:%S"), state["quality"], state["sats"],
                state["hdop"], state["diff_age"], state["fix_type"],
                state["ths_valid"], state["heading"], max_snr, avg_snr))
            if state["quality"] != last_q:
                log("EVENT quality %s -> %s (sats=%s hdop=%s diff_age=%s)" % (
                    last_q, state["quality"], state["sats"], state["hdop"], state["diff_age"]))
                last_q = state["quality"]
            if state["sats"] is not None and last_sats is not None and state["sats"] < last_sats - 3:
                log("EVENT sats drop %s -> %s" % (last_sats, state["sats"]))
            last_sats = state["sats"]
            state["snr"] = []
            next_tick += 1.0


if __name__ == "__main__":
    main()
