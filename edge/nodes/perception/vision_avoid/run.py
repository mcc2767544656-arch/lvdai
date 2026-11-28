#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vision_avoid 节点：从本地视觉服务读取 (v, ω)，发布到 control.velocity。

不依赖 cv2/torch，NodeFlow 的 venv 直接能跑。
服务不可用 / 数据过期时发布 0，配合 web_teleop 的 auto_timeout 双重兜底。

图里的接法：
    vision_avoid.velocity_cmd -> web_teleop.auto_velocity
    web_teleop.velocity_cmd   -> pwm_driver.velocity_cmd
"""
import json
import time
import urllib.request

from edge.sdk.nodeflow_sdk import NodeFlowSDK


def fetch_state(url: str):
    try:
        with urllib.request.urlopen(url, timeout=0.3) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def main() -> None:
    with NodeFlowSDK(log_level="INFO") as sdk:
        url = sdk.get_param("service_url", "http://127.0.0.1:8092/state")
        stale = float(sdk.get_param("stale_timeout", 0.4))
        out = sdk.create_output_port("velocity_cmd")
        sdk.logger.info(f"VisionAvoid started, service={url} stale={stale}s")

        last_state = None
        last_warn = 0.0
        zero_sent = False

        try:
            while True:
                data = fetch_state(url)
                now = time.time()
                if data and (now - float(data.get("ts", 0.0))) <= stale:
                    v = float(data.get("linear", 0.0))
                    w = float(data.get("angular", 0.0))
                    st = str(data.get("state", "?"))
                    if st != last_state:
                        sdk.logger.info(f"vision state={st} v={v:.2f} w={w:.2f} "
                                        f"risk={data.get('risk', 0):.2f} estop={data.get('estop')}")
                        last_state = st
                    zero_sent = False
                else:
                    v = 0.0
                    w = 0.0
                    if now - last_warn >= 2.0:
                        sdk.logger.warning("vision stale/unreachable -> zero command")
                        last_warn = now
                    zero_sent = True

                out.send({
                    "linear_velocity": v,
                    "angular_velocity": w,
                    "timestamp": now,
                })
                time.sleep(0.05)
        except KeyboardInterrupt:
            pass
        finally:
            out.send({"linear_velocity": 0.0, "angular_velocity": 0.0, "timestamp": time.time()})
            sdk.logger.info("VisionAvoid stopped, zero sent")


if __name__ == "__main__":
    main()
