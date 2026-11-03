# OEM700 / Air700E NTRIP（CORS）配置说明

来源：`OEM700_2217_V3.doc`（供应商提供的模块命令手册，5 页）+ 现场实测。

## 1. 命令格式

```
$snp,<host>,<port>,<mount point>,<user name>,<password>,<up gga>,*XX
```

手册示例：

```
$snp,ntrip.gnss-info.com,2101,SEP01,ntrip,ntrip4u,1,*4E
```

字段说明：

| 字段 | 含义 | 本系统取值 |
|---|---|---|
| host | CORS 域名或 IP | `rtkcq.cn` 或 `103.40.12.16` |
| port | 端口 | `8001`（ITRF2008）/ `8002`（WGS84）/ `8003`（CGCS2000） |
| mount point | 挂载点 | `RTCM33_GRC` 或 `RTCM33_GRCEJ` |
| user name | 账号 | `cqcc139580` |
| password | 密码 | 已单独提供，**不写入本仓库** |
| up gga | 是否上传 GGA | `1` |

## 2. 校验和

算法：`$` 之后、`*` 之前所有字符的 **逐字节 XOR**，两位大写十六进制。

已验证：

| 命令体 | XOR | 完整命令 |
|---|---|---|
| `sne,1,` | `49` | `$sne,1,*49` |
| `sne,0,` | `48` | `$sne,0,*48` |
| `gnp,` | `55` | `$gnp,*55` |
| `snp,ntrip.gnss-info.com,2101,SEP01,ntrip,ntrip4u,1,` | `4E` | 手册示例 |

注意：末尾逗号也算进校验和。

## 3. 开关与查询

| 命令 | 作用 |
|---|---|
| `$sne,1,*49` | 打开 NTRIP |
| `$sne,0,*48` | 关闭 NTRIP |
| `$gnp,*55` | 查询 NTRIP 参数（手册只给了这一条，按命名推断为 get） |
| `$snp,...` | 设置 NTRIP 参数 |

## 4. 现场实测（2026-11-03，已确认）

**模块的 `$` 命令口就是 NMEA 数据口**，不是 AT 口，也不是 Lua REPL。

| 端口 | 行为 |
|---|---|
| 数据口（最初 `ttyACM3`，重枚举后 `ttyACM4`） | `$gnp` / `$snp` / `$sne` 都在这里响应，同时输出 NMEA |
| `ttyACM0` | 静默，不发 `$gnp` 响应 |
| `ttyACM1` | LuatOS Lua REPL，发 `$` 会报 `unexpected symbol near '$'` |
| `ttyACM2` | 高速二进制日志，不要 `cat` |

实测过程：

1. 查询旧配置：

```
$gnp,103.143.19.54,8002,RTCM33GRCEJ15,gj011,14231,1,*10
```

2. 写入新配置后模块回 `$snp,ok,*69`，再查：

```
$gnp,103.40.12.16,8002,RTCM33_GRCEJ,cqcc139580,31818,1,*5B
```

3. 写入后模块**重启并重新枚举 USB**：`ttyACM3` 消失，变成 `ttyACM4`。重启后配置仍在（已写 NVM）。

> 因此脚本不要写死端口号。按 `/dev/serial/by-id/usb-AirM2M_AirM2M_Compo_000000000001-if06` 找，或写配置后重新扫描 `/dev/ttyACM*`。

## 5. 本次写入的值

| 字段 | 旧值 | 新值 |
|---|---|---|
| host | `103.143.19.54` | `103.40.12.16`（`rtkcq.cn` 解析到该 IP） |
| port | `8002` | `8002`（WGS84） |
| mount | `RTCM33GRCEJ15` | `RTCM33_GRCEJ` |
| user | `gj011` | `cqcc139580` |
| password | `14231` | 新密码已写入，不记录在仓库 |
| up gga | `1` | `1` |

写入命令（密码用占位符表示）：

```
$snp,103.40.12.16,8002,RTCM33_GRCEJ,cqcc139580,<PASSWORD>,1,*4F
```

## 6. 尚未打通的部分

- **4G 没有 IP**：`ip addr` 只有 `wlan0` 和 `docker0`，没有 wwan/ppp 接口；日志停在 `I/user.ntrip wait IP_READY`。
- **GNSS 没有定位**：GGA 质量 `0`、可见卫星 `0`（天线未接或室内无视野）。
- 所以暂时无法验证 `I/user.ntrip recv:` 和 RTK 固定解，账号写入本身已确认成功。

## 7. 验证方法（等 4G 和天线就绪）

1. 接好 GNSS 天线，放到室外/窗边。
2. 确认 4G 拿到 IP（出现 wwan/ppp/usb 网卡，或日志不再 `wait IP_READY`）。
3. `$gnp,*55` 确认参数没被改回。
4. 观察日志出现 `I/user.ntrip recv:`，GGA 质量从 `0/1` 变 `4/5`。
5. 若 4G 一直无 IP，先查 SIM 卡、APN（`$sap,apn,user,pass,*sum`）和 4G 天线。

## 8. 风险提示

- 不要动 GGA/RMC 的输出频率（见 `AIR700E_WATCHDOG_AND_RATE_TRAP.md`）。
- `$snp` 是**全量参数**命令，不是“只改密码”；必须把原有 host/port/mount 一起带上，否则会把其它字段覆盖成空。
- 写入 `$snp` / `$sne` 后模块会重启并重新枚举，串口名会变，操作前先确认当前数据口。
- 改之前先把当前参数读出来（`$gnp`），留好回滚值。
