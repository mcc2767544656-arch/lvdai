"""NTRIP 客户端：上行 GGA、下行 RTCM 差分改正数。

为什么需要上行 GGA
------------------
VRS 类 CORS（本系统用的 rtkcq.cn 就是）在收到客户端的大概位置前不会下发
任何改正数：连接会返回 ``ICY 200 OK``，然后一直静默。2026-11-09 现场实测，
只发认证不上行 GGA 时 60 秒收到 0 字节；补上 GGA 后 15 秒内 GGA 质量从 1
跳到 4（RTK 固定解），差分龄期稳定在 1 秒。

用法
----
    c = NTRIPClient(host, port, mount, user, password)
    if c.connect():
        c.send_gga("$GNGGA,...*45")
        rtcm = c.poll(0.5)      # bytes，直接写回接收机串口
"""

import base64
import socket
from typing import Optional


class NTRIPClient:
    """一个最小可用的 NTRIP 1.0 客户端。"""

    def __init__(self, host: str, port: int, mount: str, user: str = "",
                 password: str = "", timeout: float = 5.0):
        self.host = host
        self.port = int(port)
        self.mount = mount.lstrip("/")
        self.user = user
        self.password = password
        self.timeout = timeout
        self.socket: Optional[socket.socket] = None
        self.last_error = ""

    def connect(self, initial_gga: str = "") -> bool:
        """建立连接并校验服务器应答。成功返回 True。

        initial_gga: 部分 VRS caster（如国内 CORS）在收到 GGA 前**不返回任何应答头**，
        必须先把接收机自己的 GGA 上行上去，否则会一直卡到超时。
        """
        self.close()
        try:
            sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
            sock.settimeout(self.timeout)
            request = (
                f"GET /{self.mount} HTTP/1.0\r\n"
                f"User-Agent: NTRIP NodeFlow\r\n"
                f"Authorization: Basic "
                f"{base64.b64encode(f'{self.user}:{self.password}'.encode()).decode()}\r\n"
                f"Accept: */*\r\n\r\n"
            )
            sock.sendall(request.encode("ascii"))
            if initial_gga:
                if not initial_gga.endswith("\r\n"):
                    initial_gga += "\r\n"
                sock.sendall(initial_gga.encode("ascii"))

            header = b""
            while b"\r\n\r\n" not in header and len(header) < 8192:
                chunk = sock.recv(1)
                if not chunk:
                    break
                header += chunk

            first_line = header.split(b"\r\n", 1)[0].decode("ascii", "replace").strip()
            ok = first_line.startswith("ICY 200") or (
                first_line.startswith("HTTP/") and " 200" in first_line
            )
            if not ok:
                self.last_error = first_line or "no response"
                sock.close()
                return False

            self.socket = sock
            self.last_error = ""
            return True

        except (socket.error, socket.timeout, OSError) as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return False

    @property
    def connected(self) -> bool:
        return self.socket is not None

    def send_gga(self, sentence: str) -> bool:
        """把接收机自己的 GGA 原样上行，服务器据此生成虚拟参考站。"""
        if not self.socket:
            return False
        if not sentence.startswith("$"):
            return False
        payload = sentence.strip()
        if not payload.endswith("\r\n"):
            payload += "\r\n"
        try:
            self.socket.sendall(payload.encode("ascii", "ignore"))
            return True
        except (socket.error, OSError):
            self.close()
            return False

    def poll(self, timeout: float = 0.5) -> bytes:
        """读取一批 RTCM 字节；无数据/连接断开返回 b''。"""
        if not self.socket:
            return b""
        try:
            self.socket.settimeout(timeout)
            data = self.socket.recv(4096)
            if not data:
                # 服务器主动关闭
                self.close()
                return b""
            return data
        except socket.timeout:
            return b""
        except (socket.error, OSError):
            self.close()
            return b""

    def close(self):
        if self.socket:
            try:
                self.socket.close()
            except Exception:
                pass
        self.socket = None
