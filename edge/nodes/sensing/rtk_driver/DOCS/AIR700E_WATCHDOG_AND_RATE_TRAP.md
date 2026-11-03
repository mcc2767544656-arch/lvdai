# Air700E 看门狗与 UM982 输出频率的坑（现场记录）

> 一句话：**UM982 的频率参数单位是“秒/周期”，不是 Hz；Air700E 的看门狗只看“多久没收到 GGA/RMC”，约 5 秒。**
> 这两个概念混一次，模块可能进入重启循环，只能在刚上电的几秒内救回来。

## 1. 链路

```
UM982 (COM1) ──UART1──> Air700E (LuatOS ROVER App) ──USB──> Orange Pi 5 Pro
                                                        ├─ /dev/ttyACM3  数据口（NMEA，1Hz）
                                                        ├─ /dev/ttyACM1  Lua REPL（已确认）
                                                        ├─ /dev/ttyACM2  二进制日志（勿读）
                                                        └─ /dev/ttyACM0  AT（静默）
```

- UM982 **不直接暴露 USB**，所有配置要么经 Air700E 的 Lua REPL 转发，要么走 Air700E 自己的应用层。
- NTRIP 客户端、看门狗都在 Air700E 里，不在 NodeFlow / 树莓派侧。
- 实测：往 `ttyACM1` 直接发 `$gnp,*55` 会得到 Lua 报错 `unexpected symbol near '$'`，说明它是 Lua 解释器，不是模块命令口。

## 2. 看门狗

| 项目 | 说明 |
|---|---|
| 超时 | 约 5 秒 |
| 判据 | 必须同时收到 **GGA** 和 **RMC**，缺任一即重启 |
| 重启后果 | UM982 恢复 Air700E 的默认启动配置，自定义频率丢失 |

> 所以 GGA / RMC 是“生命线”，任何情况下都不能停、不能把周期拉长到看门狗超时以外。

## 3. 频率单位（手册确认）

Unicore 命令手册 7.1.1.11 原文：

```
GPRMC 1          → Output 1Hz GPRMC message at the current port
GPRMC COM2 1     → Output 1Hz GPRMC message at COM2
```

**参数是输出周期（秒），不是频率（Hz）。**

| 想要的频率 | 应写入的值 |
|---|---|
| 1 Hz | `1` |
| 5 Hz | `0.2` |
| 10 Hz | `0.1` |
| 20 Hz | `0.05` |
| 50 Hz | `0.02` |
| 0.2 Hz | `5` ← 已贴着 5 秒看门狗，危险 |
| 0.1 Hz | `10` ← 必触发重启循环 |

## 4. 事故记录：想要 20Hz，填了 20

现场配置时**以为单位是 Hz，填了 `20`**，本意是 20Hz。

但命令参数是**周期（秒）**：

```
20  →  20 秒才输出一次  →  0.05 Hz
```

Air700E 看门狗约 5 秒，20 秒的间隔直接把它饿死 → 模块进入**不断重启**，差点返厂。

这次事故不是玄学，就是**单位混淆**：想写频率，实际写的是周期。正确写法：

| 想要 | 应填 |
|---|---|
| 20 Hz | `0.05` |
| 10 Hz | `0.1` |
| 5 Hz | `0.2` |
| 1 Hz | `1` |

教训：**填任何频率值之前，先问一句“这个数字是 Hz 还是秒”**，再用 `1/期望频率` 换算。数值大于 4 基本就会踩看门狗。

## 5. 急救流程（3~5 秒窗口）

1. 断电，重新上电。
2. 立刻连 Lua REPL 口（`/dev/ttyACM1`，已确认）。
3. 在模块启动后 **3~5 秒内**写入安全值：

```lua
uart.write(1, "GPRMC 1\r\n")
uart.write(1, "GPGGA 1\r\n")
```

4. **不要** `SAVECONFIG`，先让它稳定跑着。
5. 错过窗口就等下一轮重启再试；连续失败只能返厂或刷固件（目前手上没有固件包）。

## 6. 禁止操作

| 操作 | 后果 |
|---|---|
| `UNLOGALL` | 停掉所有输出，含 GGA/RMC → 5 秒后重启 |
| `FRESET` | 恢复出厂，清 NVM → 重启 |
| `UNLOG GPGGA` | 停 GGA → 重启 |
| `UNLOG GPRMC` | 停 RMC → 重启 |
| 把 GGA/RMC 周期设为 > 4 秒 | 饿死看门狗 → 重启循环 |
| 没确认单位就改频率 | 可能直接写进重启循环 |
| 改完不验证就 `SAVECONFIG` | 把错误配置固化，断电也救不回 |

## 7. 安全改频流程

1. `LOG` 查询当前输出配置（只读，先看清现状）。
2. 只改一个消息类型，值保证 ≤ 1 秒。
3. 观察至少 10 秒：GGA/RMC 仍在、频率正确、模块没重启。
4. 稳定后再决定是否 `SAVECONFIG`。
5. 改之前把回滚命令写在手边：`GPRMC 1` / `GPGGA 1`。

## 8. 当前实测状态（2026-11-03）

- 数据口：写 `$snp` 后模块重枚举，当前 `/dev/ttyACM4`；NMEA 9 类语句、1Hz。
- **命令通道已确认**：数据口 `115200 8N1`，发 `VERSION` 返回
  `$command,VERSION,response: OK` 和 `#VERSION,...;UM982,R4.10Build13495,...`。
- **单位已实测确认是「秒」**：发 `GPZDA 2` 回 `$command,GPZDA 2,response: OK`，ZDA 间隔立刻变 2000ms。
- `GPRMC 1.5` 被固件拒绝：
  `PARSING FAILED FIELD OUT OF RANGE, Period 1.5 is not supported for this log message!`
  说明该消息只接受整数周期（或特定档位），不是通道问题、也不是应用覆盖。
- 已恢复 `GPRMC 1`、`GPZDA 1`，输出回到 1Hz。
- 定位状态：RMC=V、GGA 质量 0、可见星 0（天线未接或室内无视野）。
- NTRIP 账号已写入并回读确认，详见 `NTRIP_CORS_CONFIG.md`。

## 9. 参考

- `Unicore_Reference_Commands_N4_V2_EN_R1.6.pdf` — 7.1.1.11 GPRMC
- `UM982_User_Manual_CH_R1.7.pdf`
- `OEM700_2217_V3.doc` — Air700E/OEM700 命令手册（`$snp` NTRIP 配置）
- `../UM982_CONFIG.md` — 节点原有说明（含禁止命令、校准流程）
