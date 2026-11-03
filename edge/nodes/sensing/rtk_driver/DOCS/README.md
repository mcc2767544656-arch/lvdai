# RTK 节点参考资料（DOCS）

本目录存放 UM982 / Air700E 相关的原始手册和现场记录，供离线查阅。

## 文件清单

| 文件 | 说明 | 来源 |
|---|---|---|
| `UM982_User_Manual_CH_R1.7.pdf` | UM982 用户手册（中文，R1.7，30 页） | unicorecomm.com |
| `Unicore_Reference_Commands_N4_V2_EN_R1.6.pdf` | Unicore N4 系列参考命令手册（英文，365 页） | unicorecomm.com |
| `OEM700_2217_V3.doc` | Air700E/OEM700 模块命令手册（含 `$snp` NTRIP 配置），5 页 | 供应商分享 |
| `AIR700E_WATCHDOG_AND_RATE_TRAP.md` | **必读**：看门狗机制、频率单位陷阱、把 20 当 20Hz 的事故、急救流程 | 现场记录 |
| `NTRIP_CORS_CONFIG.md` | `$snp` 命令格式、校验和算法、CORS 账号配置位置与现状 | 现场整理 |
| `UM982_COMMAND_CHANNEL.md` | 实测：数据口 115200 发命令、应答格式、单位验证、安全红线 | 现场整理 |

> 英文版 `UM982_User_Manual_EN_R1.8.pdf` 官方站点下载不稳定，暂未收录；中文 R1.7 已覆盖同样内容。

## 先看哪篇

1. **`AIR700E_WATCHDOG_AND_RATE_TRAP.md`** — 改任何频率/输出配置之前必须看，配错可能让模块进重启循环。
2. `NTRIP_CORS_CONFIG.md` — 配 CORS 账号、NTRIP 开关、校验和计算。
3. `Unicore_Reference_Commands_N4_V2_EN_R1.6.pdf` 第 7 章 — NMEA 输出命令（`GPRMC 1` = 1Hz，参数是周期秒）。
4. `UM982_User_Manual_CH_R1.7.pdf` — 硬件、电气、安装。

## 关键结论速查

- 频率参数是**周期（秒）**，不是 Hz：`1`=1Hz，`0.1`=10Hz，`20`=0.05Hz（会踩看门狗）。
- **不要用 0.05（20Hz）**：实测会让模块时基加速约 1.58 倍，GGA/RMC 跟着变 632ms。**10Hz（0.1）是稳定上限**。
- 航向只用 `GPTHS`（双天线基线）；RMC 的 course 是地面航迹角，不能当车头航向。
- 驱动默认 `configure_position_rate: false`，只提速 `GPTHS`，GGA/RMC 保持 1Hz。
- Air700E 看门狗约 **5 秒**，靠 GGA+RMC 活着；两者缺一就重启。
- 禁止 `UNLOGALL` / `FRESET` / `UNLOG GPGGA` / `UNLOG GPRMC`。
- 改频后先观察 10 秒再 `SAVECONFIG`。
- 本机数据口不固定：写 `$snp` 后模块会重启重枚举（实测 `ttyACM3` → `ttyACM4`）。按 `/dev/serial/by-id/...-if06` 找，别写死。
- `$gnp` / `$snp` 的响应在**数据口**上，不在 AT 口；`/dev/ttyACM1` 是 Lua REPL（不能直接发 `$`）；`/dev/ttyACM2` 是二进制日志，不要 `cat`。

## 下载记录

- 2026-11-03 下载中文手册与命令手册，校验页数通过（30 / 365 页）。
- 官方站点证书主机名不匹配，下载时使用了 `curl -k`；文件已用 pypdf 验证可正常解析。
- `OEM700_2217_V3.doc` 通过分享站 API 直接下载，大小 3,861,043 字节，与元数据一致。
