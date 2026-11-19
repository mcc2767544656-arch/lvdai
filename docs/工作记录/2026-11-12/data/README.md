# 标定数据说明（2026-11-12）

## 数据来源

由 `../tools/采集脚本_teleop_rtk_log.py` 采集：同时写入

1. **指令侧**：`web_teleop.velocity_cmd` 共享缓冲区（20Hz）—— 驱动实际收到的速度指令
2. **输出侧**：`pwm_driver.pwm_status` 共享缓冲区（20Hz）—— 左右通道 duty_cycle（ns）
3. **实际侧**：UM982 `$KSXT`（10Hz）—— 经纬度、双天线航向、地面速度、东北向速度分量、解状态

三个来源合成一张 CSV，每 50ms 一行。

## 文件清单

| 文件 | 行数 | 时长 | 内容 | 质量 |
|---|---|---|---|---|
| `run1_手动驾驶.csv` | 7201 | 360s | 人工遥控：满杆直线前后、原地转向 | 好；**无 duty 列**（当时采集器未加） |
| `run2_手动分段推杆.csv` | 3339 | 167s | 人工分段推杆（各档位停留） | 好，速度表主要来源 |
| `run3_手动推杆第二轮_后半串口冻结.csv` | 12001 | 600s | 同上，第二轮 | **后半段串口冻结，不可用**（仅前 ~86s 有效） |
| `run4_自动扫转向_低档.csv` | 6001 | 300s | 脚本自动扫 0.5–2.0 rad/s | 前段有效；cmd≥3.0 段冻结 |
| `run5_自动扫转向_高档.csv` | 4801 | 240s | 脚本自动扫 2.5–4.0 rad/s | 好（已启用串口自愈） |
| `速度标定表.csv` | 25 | — | 由 run2+run3 去噪汇总 | 派生 |
| `转向标定表.csv` | 14 | — | 由 run4+run5 去噪汇总 | 派生 |

## 列定义

| 列 | 单位 | 说明 |
|---|---|---|
| `t` | s | 采集开始后的相对时间 |
| `cmd_lin` | m/s | 速度指令（`web_teleop` 限幅后的值） |
| `cmd_ang` | rad/s | 角速度指令 |
| `duty_l` | ns | CH1（油门）duty_cycle 原始值 |
| `duty_r` | ns | CH2（转向）duty_cycle 原始值 |
| `lat` / `lon` | deg | KSXT 纬度/经度 |
| `hdg` | deg | 双天线真北航向 |
| `gs_kmh` | km/h | KSXT 地面速度（注意是**天线**速度） |
| `ve` / `vn` | km/h | 东/北向速度分量 |
| `pos_q` | — | KSXT 定位质量（实测恒为 3 = RTK 固定） |
| `hdq_q` | — | 定向质量 |
| `sats` | — | 卫星数 |

### 脉宽换算（重要）

香橙派 PWM 是**反相**极性（`pwm_inverted_polarity: true`），duty 记的是低电平时间：

```
周期 = 20 ms（50 Hz）
脉宽(ns) = 20,000,000 − duty(ns)
中位 1.5 ms；1.0 ms = 满油门一侧；2.0 ms = 另一侧
```

## 数据质量与已知偏差

1. **串口冻结**：`$KSXT` 会停止更新，表现为 lat/lon/hdg/gs 长时间不变。已知两次（run3 中段 129s、run4 高速段）。分析时按「连续 ≥20 行完全相同」剔除。
2. **速度是天线速度**：原地转向时天线绕旋转中心画圆，`gs` 会显示约 `ω×r`（实测 r ≈ 0.6 m），**不代表车辆平动**。
3. **电压条件**：采集时电池 79.3V（满电 87.6V，标称 72V 系统），速度比满电状态约低 10%。
4. **地面**：空地，轮式/履带在松软地面的打滑未单独评估。
5. `run1` 与 `run2` 是人工推杆，档位不严格等间距；等间距数据来自 run4/run5 的脚本扫档。

## 复现方法

```bash
cd /home/orangepi/nodeflow
source .venv/bin/activate

# 1) 起数据流（遥控图）
python3 -m tools.cli.core.cli runtime start configs/graphs/web_pwm_teleop.yaml --background
python3 -m tools.cli.core.cli runtime start-dataflow

# 2) 开采集（时长秒数，输出文件）
python3 docs/工作记录/2026-11-12/tools/采集脚本_teleop_rtk_log.py 300 /tmp/calib.csv

# 3) 人工推杆，或让脚本自动扫档（档位列表、每档保持秒、间隔秒）
python3 docs/工作记录/2026-11-12/tools/扫档脚本_teleop_sweep.py 0.5,1.0,1.5 3 2
```

采集脚本依赖 `$KSXT` 串口；若设备未连接会直接退出。脚本已内置**串口自愈**：1.5s 收不到 KSXT 就重开端口。
