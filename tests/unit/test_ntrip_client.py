"""NTRIP 客户端：握手、GGA 上行、RTCM 下行。用本地假服务器，不碰外网。"""
import base64
import socket
import threading
import time

import pytest

from edge.nodes.sensing.rtk_driver.ntrip_client import NTRIPClient


class FakeNTripServer:
    """最小 NTRIP 源站：校验认证头，回 ICY 200 OK，然后推一段伪 RTCM。"""

    def __init__(self, status="ICY 200 OK", payload=b"\xd3\x00\x13test-rtcm"):
        self.status = status
        self.payload = payload
        self.received = []
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, daemon=True)

    def start(self):
        self.thread.start()
        return self

    def _serve(self):
        conn, _ = self.sock.accept()
        conn.settimeout(3)
        header = b""
        while b"\r\n\r\n" not in header:
            chunk = conn.recv(1)
            if not chunk:
                conn.close()
                return
            header += chunk
        self.received.append(header.decode("ascii", "replace"))
        conn.sendall((self.status + "\r\n\r\n").encode())
        if self.payload:
            # 等客户端上行 GGA 后再推流，模拟 VRS 行为
            try:
                gga = conn.recv(200)
                if gga:
                    self.received.append(gga.decode("ascii", "replace"))
            except socket.timeout:
                pass
            conn.sendall(self.payload)
        time.sleep(0.4)
        conn.close()

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def test_connect_uploads_gga_and_receives_rtcm():
    server = FakeNTripServer().start()
    client = NTRIPClient("127.0.0.1", server.port, "/RTCM33_GRCEJ",
                         "cqcc139580", "31818", timeout=2.0)
    try:
        assert client.connect() is True
        assert client.connected

        assert client.send_gga("$GNGGA,064921.00,2855.2251,N,12002.8188,E,1,28,0.8,107.2,M,9.3,M,,*45")
        data = b""
        deadline = time.time() + 2
        while time.time() < deadline and len(data) < len(server.payload):
            data += client.poll(0.3)
        assert data.startswith(b"\xd3")
        assert data == server.payload
    finally:
        client.close()
        server.close()

    # 认证头与挂载点、GGA 原样上行
    assert "GET /RTCM33_GRCEJ HTTP/1.0" in server.received[0]
    expected = base64.b64encode(b"cqcc139580:31818").decode()
    assert f"Authorization: Basic {expected}" in server.received[0]
    assert "GNGGA" in server.received[1]


def test_connect_rejects_unauthorized():
    server = FakeNTripServer(status="HTTP/1.0 401 Unauthorized", payload=b"").start()
    client = NTRIPClient("127.0.0.1", server.port, "M", "u", "bad", timeout=2.0)
    try:
        assert client.connect() is False
        assert client.connected is False
        assert "401" in client.last_error
    finally:
        client.close()
        server.close()


def test_send_gga_rejects_non_sentence_and_closed_socket():
    client = NTRIPClient("127.0.0.1", 1, "M", "u", "p")
    assert client.send_gga("GNGGA,not-a-sentence") is False
    assert client.poll(0.1) == b""
    client.close()


def test_password_missing_disables_ntrip(monkeypatch):
    """没有密码时不应建立连接；节点会记错误并跳过。"""
    from edge.nodes.sensing.rtk_driver import run as driver_module
    node = driver_module.RTKDriverNode.__new__(driver_module.RTKDriverNode)
    node.ntrip_password = ""
    node.ntrip_password_env = "NTRIP_PASSWORD_UNSET_FOR_TEST"
    node.ntrip_password_file = ""
    monkeypatch.delenv("NTRIP_PASSWORD_UNSET_FOR_TEST", raising=False)
    assert node._resolve_ntrip_password() == ""
