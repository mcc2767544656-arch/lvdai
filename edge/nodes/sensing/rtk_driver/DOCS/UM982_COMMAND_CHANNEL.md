# 给 UM982 发命令的正确姿势（实测）

> 2026-11-03 验证通过。之前从 REPL / AT 口发都不通，真正能用的是**数据口**。

## 1. 端口

UM982 的命令口就是输出 NMEA 的那个 **USB 数据口**：

```
/dev/serial/by-id/usb-AirM2M_AirM2M_Compo_000000000001-if06
```

当前实际设备是 `/dev/ttyACM4`。注意：

- 写 `$snp`（NTRIP 配置）后模块会重启并重新枚举，端口号会变（实测 `ttyACM3` → `ttyACM4`）；
- 不要写死 `/dev/ttyACM3`，每次按 by-id 或重新扫描 `/dev/ttyACM*`。

## 2. 串口参数

```
115200 8N1, raw, 无流控
```

Python 示例：

```python
import os, termios, time
fd = os.open('/dev/ttyACM4', os.O_RDWR | os.O_NOCTTY)
a = termios.tcgetattr(fd)
a[0] = 0; a[1] = 0
a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
a[3] = 0; a[4] = a[5] = termios.B115200
termios.tcsetattr(fd, termios.TCSANOW, a)

os.write(fd, b'VERSION\r\n')
time.sleep(0.5)
print(os.read(fd, 4096))
```

## 3. 应答格式

成功：

```
$command,VERSION,response: OK*04
#VERSION,98,GPS,UNKNOWN,1,3253000,0,0,18,493;UM982,R4.10Build13495,HRPT00-S10C-P,...
```

失败会明确说原因，例如：

```
$command,GPRMC 1.5,response: PARSING FAILED FIELD OUT OF RANGE,Period 1.5 is not supported for this log message!*43
```

## 4. 已验证的命令

| 命令 | 结果 |
|---|---|
| `VERSION` | OK，返回固件 `UM982 R4.10Build13495` |
| `GPZDA 2` | OK，ZDA 间隔变 2000ms → **参数单位是秒** |
| `GPZDA 0.05` | OK，ZDA 实测 59.2ms（约 17Hz） |
| `GPZDA 1` | OK，恢复 1000ms |
| `GPRMC 1.5` | 拒绝：`Period 1.5 is not supported for this log message` |
| `GPRMC 1` | 恢复 1Hz |

## 5. 关键结论

1. **频率参数是周期（秒）**：`1`=1Hz，`0.05`=20Hz，`2`=0.5Hz。
2. **不是所有档位都支持**：`GPRMC 1.5` 被拒（`Period 1.5 is not supported`），但 `GPZDA 0.05` 可以。
   说明每条消息有自己允许的周期集合，改之前先小步试。
3. USB 的另外三个口都不行：ACM0 静默、ACM1 是 Lua REPL、ACM2 是二进制日志。
4. 不要再通过 Lua REPL 的 `uart.write(1, ...)` 绕，直接走数据口。

## 5.1 20Hz 实测（2026-11-03）

用 `GPZDA` 做探路（不参与看门狗，改坏也不影响定位）：

```
发送: GPZDA 0.05
应答: $command,GPZDA 0.05,response: OK*2D
结果: 6 秒 103 条，平均间隔 59.2ms（约 17Hz）
```

同一次观测里 GGA/RMC 短暂抖动到平均 417ms，改回 `GPZDA 1` 后又稳定在 1000ms。
判断是改周期时模块重新同步了 NMEA 调度器，属于瞬态。

恢复：

```
发送: GPZDA 1
应答: $command,GPZDA 1,response: OK*07
结果: ZDA/GGA/RMC 全部 1000ms
```

经验：

1. `0.05` 档位被接受，但实测约 **17Hz**，不是精确 20Hz——后来确认是模块时基被改快，见 5.2。
2. 改一条消息的频率，可能引起其它消息短暂重同步；**等 10 秒稳定后再判断**。
3. 不要用 20Hz；10Hz（`0.1`）是稳定上限。
4. 改完先别 `SAVECONFIG`，确认 GGA/RMC 仍正常、模块没重启，再决定是否固化。

## 5.2 20Hz（0.05）会触发时基加速（重要）

继续实测发现，`0.05` 这个档位有坑：

| 命令 | 应答 | GPTHS 实测 | GGA / RMC 实测 |
|---|---|---|---|
| `GPTHS 0.05` | OK | 32 ms（约 31Hz） | 632 ms（约 1.58Hz） |
| `GPTHS 0.1` | OK | 95 ms（约 10.5Hz） | **1000 ms（正常 1Hz）** |

模块自己的 `#HEADINGA` 时间字段仍然每秒 +1，说明不是主机测错，而是 **0.05 把模块的调度时基改快了约 1.58 倍**，所有消息一起变快。

结论：

1. **这颗模块不要用 0.05（20Hz）**。
2. **10Hz（0.1）是稳定上限**，GGA/RMC 保持在 1Hz。
3. 0.05 不会饿死看门狗（是变快不是变慢），但会污染时间戳、加重串口和解析负载，没必要。

## 5.3 航向来源：为什么不动 RMC / GGA

- `$GNRMC` 里的 course 是 **地面航迹角（COG）**，由前后位置差算出来，不是主天线指向从天线的基线角，不能拿来做车头航向。
- 双天线航向要用 **`$GPTHS`**（或 `#HEADINGA`），这是基线解算出来的真北角。
- 因此驱动只对 `GPTHS` 提速，`GGA`/`RMC` 保持 1Hz：
  - `run.py` 新增参数 `configure_position_rate`，默认 `false`；
  - 只有显式打开时才会发 `GPRMC/GPGGA` 的频率命令；
  - 默认只发 `GPTHS {period}`。

## 6. 安全红线

- `GGA` / `RMC` 是 Air700E 看门狗的生命线，周期不能超过约 4 秒，否则重启循环。
- 禁止 `UNLOGALL`、`FRESET`、`UNLOG GPGGA`、`UNLOG GPRMC`。
- 改频前先 `LOG` 看现状，改完观察 10 秒再 `SAVECONFIG`。
- 急救窗口只有上电后 3~5 秒，详见 `AIR700E_WATCHDOG_AND_RATE_TRAP.md`。
