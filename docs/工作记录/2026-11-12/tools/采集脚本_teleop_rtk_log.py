"""同时记录：web_teleop 速度指令（共享缓冲区）+ UM982 KSXT（串口 10Hz）"""
import os, sys, time, termios, csv, signal
sys.path.insert(0, '/home/orangepi/nodeflow')
import glob
# 数据缓冲区按 run 隔离，自动定位最近一轮的 velocity_cmd
_cands = glob.glob('/tmp/nodeflow/runs/*/buffers/web_teleop.velocity_cmd.buf')
if not _cands:
    raise SystemExit('找不到 web_teleop.velocity_cmd 缓冲区（dataflow 没在跑？）')
_newest = max(_cands, key=os.path.getmtime)
os.environ['NODEFLOW_BUFFERS_DIR'] = os.path.dirname(_newest)
from edge.sdk.shared_buffer_lite import SharedBufferLite

PORT = '/dev/serial/by-id/usb-AirM2M_AirM2M_Compo_000000000001-if06'
DUR = float(sys.argv[1]) if len(sys.argv) > 1 else 180.0
OUT = sys.argv[2] if len(sys.argv) > 2 else '/tmp/calib.csv'

def open_serial():
    f = os.open(PORT, os.O_RDWR | os.O_NOCTTY)
    a = termios.tcgetattr(f)
    a[0] = 0; a[1] = 0
    a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
    a[3] = 0; a[4] = a[5] = termios.B115200
    termios.tcsetattr(f, termios.TCSANOW, a)
    os.set_blocking(f, False)
    return f

fd = open_serial()
last_ksxt = time.time()

buf = SharedBufferLite('web_teleop.velocity_cmd', create=False)
pbuf = SharedBufferLite('pwm_driver.pwm_status', create=False)
fout = open(OUT, 'w', newline='')
writer = csv.writer(fout)
writer.writerow(['t','cmd_lin','cmd_ang','duty_l','duty_r','lat','lon','hdg','gs_kmh','ve','vn','pos_q','hdq_q','sats'])
fout.flush()
rows = 0
raw = b''
last = dict(cmd_lin=None, cmd_ang=None, lat=None, lon=None, hdg=None,
            gs=None, ve=None, vn=None, pq=None, hq=None, sats=None,
            dl=None, dr=None)
t0 = time.time()
next_row = t0
try:
    while time.time() - t0 < DUR:
        # 串口自愈：>1.5s 没收到 KSXT 就重开端口（ACM 在电机干扰下会卡死）
        if time.time() - last_ksxt > 1.5:
            try: os.close(fd)
            except Exception: pass
            time.sleep(0.2)
            try:
                fd = open_serial()
                raw = b''
            except Exception:
                time.sleep(0.3)
            last_ksxt = time.time()

        try:
            chunk = os.read(fd, 65536)
            if chunk:
                raw += chunk
                while b'\r\n' in raw:
                    line, raw = raw.split(b'\r\n', 1)
                    s = line.decode('ascii', 'replace')
                    if s.startswith('$KSXT,'):
                        last_ksxt = time.time()
                        p = s.split('*', 1)[0].split(',')
                        if len(p) >= 14:
                            try:
                                last.update(lat=float(p[3]), lon=float(p[2]),
                                            hdg=float(p[5]), gs=float(p[8]),
                                            pq=int(p[10]) if p[10] else None,
                                            hq=int(p[11]) if p[11] else None,
                                            sats=int(p[13]) if p[13] else None)
                                if len(p) > 18 and p[17] and p[18]:
                                    last.update(ve=float(p[17]), vn=float(p[18]))
                            except ValueError:
                                pass
        except BlockingIOError:
            pass

        d = buf.read()
        if d:
            last['cmd_lin'] = d.get('linear_velocity')
            last['cmd_ang'] = d.get('angular_velocity')
        pd = pbuf.read()
        if pd:
            last['dl'] = pd.get('left_duty_ns')
            last['dr'] = pd.get('right_duty_ns')

        now = time.time()
        if now >= next_row:
            writer.writerow([round(now - t0, 3), last['cmd_lin'], last['cmd_ang'],
                             last['dl'], last['dr'],
                             last['lat'], last['lon'], last['hdg'], last['gs'],
                             last['ve'], last['vn'], last['pq'], last['hq'], last['sats']])
            fout.flush()
            rows += 1
            next_row += 0.05
        time.sleep(0.005)
finally:
    os.close(fd); buf.close(); pbuf.close()
    fout.close()
    print(f"rows={rows} -> {OUT}")
