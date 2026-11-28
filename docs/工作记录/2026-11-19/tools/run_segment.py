#!/usr/bin/env python3
"""RTK 分段监测 — 自动识别「静止 ≥4s 后起步」与「行驶后停稳 ≥4s」

用法: python3 run_segment.py [端口]
输出: /root/field_logs/segment_<时间>/track.csv, events.log
"""
import glob
import math
import re
import os
import select
import sys
import termios
import time


def data_port():
    """按 by-id if06 找数据口，USB 重枚举后自动跟随"""
    for p in glob.glob("/dev/serial/by-id/*if06"):
        return os.path.realpath(p)
    for p in ("/dev/ttyACM4", "/dev/ttyACM3", "/dev/ttyACM5"):
        if os.path.exists(p):
            return p
    return None


PORT = sys.argv[1] if len(sys.argv) > 1 else (data_port() or "/dev/ttyACM3")
OUT = "/root/field_logs/segment_" + time.strftime("%Y%m%d_%H%M%S")
os.makedirs(OUT, exist_ok=True)
csvf = open(OUT + "/track.csv", "w", buffering=1)
logf = open(OUT + "/events.log", "w", buffering=1)
csvf.write("time,lat,lon,speed_mps,quality,heading,sats\n")

STILL_SPEED = 0.1      # m/s，低于算静止
STILL_SECS = 4.0       # 静止多久算“停稳”
MOVE_SPEED = 0.3       # m/s，高于算在动


def log(msg):
    line = "%s %s" % (time.strftime("%H:%M:%S"), msg)
    logf.write(line + "\n")
    print(line, flush=True)


def open_port(path=None):
    fd = os.open(path or PORT, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    a = termios.tcgetattr(fd)
    a[0] = a[1] = a[3] = 0
    a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
    a[4] = a[5] = termios.B115200
    a[6][termios.VMIN] = 0
    a[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW, a)
    return fd


def parse(s):
    p = s.split("*")[0].split(",")
    if len(p) < 14:
        return None
    try:
        return {
            "lat": float(p[3]), "lon": float(p[2]),
            "hdg": float(p[5]) if p[5] else None,
            "spd": float(p[8]) / 3.6 if p[8] else 0.0,   # km/h -> m/s
            "q": int(p[10]) if p[10] else -1,
            "sats": int(p[13]) if p[13] else 0,
        }
    except (ValueError, IndexError):
        return None


def dist_m(a, b):
    """局部平面近似，米"""
    lat_m = (b["lat"] - a["lat"]) * 111320.0
    lon_m = (b["lon"] - a["lon"]) * 111320.0 * math.cos(math.radians(a["lat"]))
    return math.hypot(lat_m, lon_m)


def fmt(p):
    return "%.8f, %.8f" % (p["lat"], p["lon"])


def main():
    log("start port=%s out=%s" % (PORT, OUT))
    kmsg = os.open("/dev/kmsg", os.O_RDONLY | os.O_NONBLOCK)
    while True:
        try:
            if not os.read(kmsg, 1 << 16):
                break
        except OSError:
            break
    usb_re = re.compile(r"usb \d-\d|cdc_acm|device descriptor|error -71", re.I)
    fd = open_port()
    buf = b""
    state = "WAIT"
    still_t0 = None
    still_pos = None
    end_t0 = None
    end_pos = None
    start = None
    t_start = None
    max_spd = 0.0
    last = None

    last_check = 0.0
    cur_port = PORT
    while True:
        now_chk = time.time()
        if now_chk - last_check > 2.0:
            last_check = now_chk
            newp = data_port()
            if newp and newp != cur_port:
                log("EVENT 端口变化 %s -> %s" % (cur_port, newp))
                try:
                    os.close(fd)
                except OSError:
                    pass
                cur_port = newp
                try:
                    fd = open_port(cur_port)
                except OSError:
                    pass
        while True:
            try:
                ev = os.read(kmsg, 8192)
            except OSError:
                break
            if not ev:
                break
            for part in ev.split(b"\n"):
                txt = part.decode("utf-8", "replace")
                if usb_re.search(txt):
                    log("EVENT usb: %s" % txt.strip()[:150])
        r, _, _ = select.select([fd], [], [], 0.3)
        if not r:
            continue
        try:
            buf += os.read(fd, 8192)
        except BlockingIOError:
            continue
        except OSError:
            log("EVENT 串口读失败，重新打开")
            time.sleep(0.5)
            newp = data_port()
            try:
                fd = open_port(newp or PORT)
                log("EVENT 重开成功 %s" % (newp or PORT))
            except OSError:
                continue
            continue

        while b"\n" in buf:
            raw, _, buf = buf.partition(b"\n")
            s = raw.decode("ascii", "replace").strip()
            if not s.startswith("$KSXT"):
                continue
            p = parse(s)
            if not p:
                continue
            now = time.time()
            last = p
            csvf.write("%s,%.8f,%.8f,%.2f,%d,%s,%d\n" % (
                time.strftime("%H:%M:%S"), p["lat"], p["lon"], p["spd"],
                p["q"], p["hdg"], p["sats"]))

            if state == "WAIT":
                if p["spd"] < STILL_SPEED:
                    if still_t0 is None:
                        still_t0, still_pos = now, p
                else:
                    if still_t0 and (now - still_t0) >= STILL_SECS and p["spd"] > MOVE_SPEED:
                        start, t_start = still_pos, now
                        max_spd = p["spd"]
                        state = "MOVING"
                        log("START  lat,lon=%s  q=%d sats=%d  (静止 %.1fs 后起步)" % (
                            fmt(start), start["q"], start["sats"], now - still_t0))
                    still_t0 = None

            elif state == "MOVING":
                max_spd = max(max_spd, p["spd"])
                if p["spd"] < STILL_SPEED:
                    if end_t0 is None:
                        end_t0, end_pos = now, p
                    elif (now - end_t0) >= STILL_SECS:
                        d = dist_m(start, end_pos)
                        dur = end_t0 - t_start
                        log("END    lat,lon=%s  q=%d sats=%d" % (
                            fmt(end_pos), end_pos["q"], end_pos["sats"]))
                        log("RESULT 距离 %.2f m  用时 %.1f s  平均 %.2f m/s  最大 %.2f m/s  "
                            "起点航向 %s" % (
                                d, dur, d / dur if dur > 0 else 0, max_spd,
                                "%.1f" % start["hdg"] if start["hdg"] else "-"))
                        state = "DONE"
                else:
                    end_t0 = None

            elif state == "DONE":
                if p["spd"] < STILL_SPEED and still_t0 is None:
                    still_t0 = now
                elif p["spd"] > MOVE_SPEED and (now - still_t0) >= STILL_SECS and still_t0:
                    # 第二段开始，重新进入 WAIT 逻辑
                    state = "WAIT"
                    still_t0, still_pos = None, None
                    log("--- 下一段准备 ---")


if __name__ == "__main__":
    main()
