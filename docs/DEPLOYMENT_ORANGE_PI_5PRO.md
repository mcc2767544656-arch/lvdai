# Orange Pi 5 Pro 部署记录（边缘机 · 2026-10-18）

> **读者**：后续接手这台板子的会话/人。
> **性质**：这是**某台具体机器**的现场部署记录，不是通用安装文档；里面的 IP、SSID、密码、路径只对这台机器成立。
> **状态**：可用，能跑规划闭环仿真并在浏览器看三维页面。未做 systemd 常驻（手动启动）。

---

## 0. 一句话现状

板子从 **512GB TF 卡**启动 Orange Pi 官方 Jammy server 镜像；NodeFlow 部署在 `/home/orangepi/nodeflow`；
仿真 ZMQ 跑 **5655**，三维观察 Web 跑 **8080**，进程用 `setsid nohup` 手动拉起，**重启后不会自动恢复**。
NVMe 固态已刷同一镜像但**未扩容、未启用**（板子没有 SPI Flash，无法纯 NVMe 启动）。

---

## 1. 硬件与系统

| 项 | 值 |
|---|---|
| 板卡 | Orange Pi 5 Pro（RK3588S，aarch64） |
| 内存 | 3.8 GiB（`free -h` 可见；**不要跑需要 >2.5G 常驻内存的服务**） |
| 启动介质 | 512GB microSD → 系统里是 `mmcblk1`（`/` 在 `mmcblk1p2`，471.1G，已自动扩容） |
| 系统镜像 | `Orangepi5pro_1.0.6_ubuntu_jammy_server_linux6.1.43.img`（Ubuntu 22.04 "Orange Pi 1.0.6 Jammy"） |
| 内核 | `6.1.43-rockchip-rk3588 #1.0.6 SMP`（**已 apt-mark hold，见 §7**） |
| 无线 | `wlan0`，Broadcom `brcmfmac`（板载 AP6275P 模块），5GHz 可用 |
| 有线 | `enP4p65s0` |
| NVMe | `nvme0n1` = aigo P2000 128GB，刷了同一镜像但 rootfs 只有 2.9G、**未扩容未启用** |
| eMMC | 无 |
| SPI Flash | **没有**（`cat /proc/mtd` 为空）。官方手册说明 5 Pro 出厂不焊，需自行购买焊接，且 SPI 与 eMMC 共用引脚 |

### 登录
- 用户 `orangepi`，密码 `orangepi`（默认，**未修改**）；`sudo` 同密码（需要密码，没有免密）。

---

## 2. 网络

### 有线
`enP4p65s0`，DHCP，家里路由器给 `192.168.31.198`，路由 metric 100。

### WiFi（现场用手机热点）
NetworkManager 连接名 **`PhoneHotspot-10000`**：

| 项 | 值 |
|---|---|
| SSID | `10000` |
| 密码 | WPA2-PSK `88888888`（**8 位**；6 位的 `888888` 会被 NetworkManager 以 `802-11-wireless-security.psk: property is invalid` 拒绝） |
| 自动连接 | yes，`autoconnect-retries 0`（永久重试） |
| 省电 | `802-11-wireless.powersave 2`（关闭，避免热点下断流） |
| 路由 metric | IPv4/IPv6 = 600（有线 100，插网线时不会被 WiFi 抢默认路由） |

实测（2026-10-18 23:59）：连上安卓热点，`192.168.43.70/24`，5GHz 5180MHz，-34 dBm，协商 390 Mbit/s；
强制走 `wlan0` 出网：`api.deepseek.com` 401（能通、无 key）、`github.com` 200。

### 找板子
装了 **avahi**（`avahi-daemon` enabled，`libnss-mdns`），现场不用记 IP：

```bash
ssh orangepi@orangepi5pro.local
```

若 `.local` 不解析：看手机热点"已连接设备"里的 IP（通常是 `192.168.43.x`），或 `ping orangepi5pro.local`。
SSH 服务 `enabled` + `active`，监听 `0.0.0.0:22`。

---

## 3. 工具链（都是为这台机器现场装的）

| 组件 | 版本/位置 | 安装方式与注意事项 |
|---|---|---|
| Python | **3.12.15** `/usr/bin/python3.12` | 系统自带只有 3.10.12；`add-apt-repository ppa:deadsnakes/ppa` |
| Node.js | **v22.23.3**，`/usr/local/lib/nodejs/node-v22.23.3-linux-arm64`，`/usr/local/bin/node` 软链 | **不要用 NodeSource**（`deb.nodesource.com` 国内连不上，会卡住 apt）；用 npmmirror 二进制 tarball |
| npm | 10.9.9，registry 已设为 `https://registry.npmmirror.com` | |
| pip | 默认源改为 **阿里云** `https://mirrors.aliyun.com/pypi/simple/` | **清华源会返回 403**（索引可读、包文件被拒），不要用 |
| opencode | **2.0.32**（v2 线），`/usr/local/bin/opencode` → `/usr/local/lib/opencode/opencode2` | 见下方说明；**尚未配置模型 API key**，见 §7 |
| opencode（旧） | 1.19.3，`/usr/local/bin/opencode1` | v1 线，保留作回退 |

> **opencode 的 v1/v2 分发差异（容易装错）**
> - `npm i -g opencode-ai` 装到的是 **v1 线**（`latest` 标签停在 1.19.3），不是最新版。
> - v2 的官方入口是 `curl -fsSL https://opencode.ai/v2/install | bash`，它实际从 npm 拉 **`@opencode/cli-linux-arm64`**（当前 2.0.32），落到 `~/.opencode/bin/opencode`。
> - 本机做法：从 npmmirror 下同名 tgz 手工解包 → `/usr/local/lib/opencode/opencode2`，符号链接 `/usr/local/bin/opencode`。
> - 升级时把版本号换掉重跑即可：
>   `curl -fL -o /tmp/cli.tgz https://registry.npmmirror.com/@opencode/cli-linux-arm64/-/cli-linux-arm64-<版本>.tgz`

---

## 4. NodeFlow 部署

- 位置：`/home/orangepi/nodeflow`（从 Mac 的 `~/Desktop/Nodeflow` rsync 过来，**排除了** `.git`、`node_modules`、`.venv`、缓存；约 61MB / 2873 文件）
- 虚拟环境：`/home/orangepi/nodeflow/.venv`（Python 3.12）
- 已安装：
  - `pip install -e .`（提供 `nodeflow` / `nodeflow-cli`）
  - `requirements.txt`
  - `cloud/server/requirements.txt`
  - `edge/nodes/observability/trajectory_viz/requirements.txt`（flask / flask-socketio / python-socketio / numpy / shapely）← **漏装会直接导致运行图启动失败**
  - `edge/nodes/planning/global_coverage/requirements.txt`
  - `cloud/web` 的 `npm install`（157MB，**未**构建产物，没跑 build）
- **未安装**：`cloud/monitor`、`tools/editor` 的 node_modules（各自 145M/197M，需要时再装）

### 启动（当前实际用法）

```bash
cd /home/orangepi/nodeflow
. .venv/bin/activate

# 1) 仿真服务（ZMQ 5655 + 内置仿真循环）
setsid nohup python3 simulation/server.py > /tmp/sim_run.log 2>&1 < /dev/null &

# 2) 规划闭环运行图（观察节点提供 8080）
setsid nohup python3 -m edge.runtime.main configs/graphs/planning_simulation.yaml \
  > /tmp/graph_run.log 2>&1 < /dev/null &
```

> 必须用 `setsid` + 重定向 + `< /dev/null`，否则通过 SSH（`ssh -tt`）启动的后台进程会占住 pty，导致会话不退出。

### 停止

```bash
pkill -f "edge.runtime.main"; pkill -f "simulation/server.py"
```

### 访问

- 二维/曲线：`http://<板子IP>:8080/`
- 三维农场：`http://<板子IP>:8080/3d`（页面标题「农场三维观察 · NodeFlow」）
- 日志：`/tmp/sim_run.log`、`/tmp/graph_run.log`；运行时状态目录 `/tmp/nodeflow/runs/<run_id>/`

### 已知小毛病

在错误目录下执行 `.venv/bin/nodeflow-cli status` 可能报 `No module named 'edge'`；在仓库根目录、激活 venv 后执行即可。

---

## 5. 端口表（重要，改动过）

| 端口 | 用途 | 归属 |
|---|---|---|
| **5555** | **adbd**（`/usr/bin/usbdevice start` 拉起的 USB-ADB 调试口，来自 `orangepi-bsp-cli-orangepi5pro`） | 开机自动起，**不要占用** |
| **5655** | NodeFlow 仿真 ZMQ | 本项目 |
| **8080** | NodeFlow 观察节点 Web（2D/3D） | 本项目 |

**为什么改端口**：5 Pro 镜像自带 `adbd` 监听 `0.0.0.0:5555`，而 NodeFlow 仿真默认也是 5555，冲突导致
`zmq.error.ZMQError: Address already in use (tcp://*:5555)`、`trajectory_viz` 启动即退出。
选择**改我们自己的端口到 5655**，没有动 adbd（现场可能还要用 RKDevTool/ADB 调试）。
`adbd` 不是 systemd 服务，`pkill -x adbd` 可临时释放，但**重启后会回来**（由 `usbdevice` 拉起）。

### 端口改造：用脚本，别手工 sed

改动已经封装成幂等脚本 **[scripts/apply_pi5pro_ports.sh](../scripts/apply_pi5pro_ports.sh)**：

```bash
cd /home/orangepi/nodeflow
bash scripts/apply_pi5pro_ports.sh
```

它会改写这些位置（重复执行无副作用）：

- `configs/graphs/*.yaml`、`examples/*.yaml` 里的 `simulator_port`
- `simulation/config.yaml` 的 `zmq_port`
- `simulation/server.py` 的默认端口
- `tools/cli/core/cli.py`、`tools/cli/cli/core/cli.py` 的 CLI 默认端口
- `tools/preflight_runtime.py`（否则预检会把 adbd 误判成"仿真器已在运行"）

> ⚠️ **重新 rsync 仓库会覆盖这些改动**，之后跑一次上面的脚本即可恢复。
> 若要让改动长期固化，应改上游默认值（或把端口做成环境变量），而不是留在机器上。

---

## 6. 系统层做过的变更

1. **关闭自动升级**（现场测试前避免意外升级打断）
   - `/etc/apt/apt.conf.d/20auto-upgrades` 写入 `APT::Periodic::Unattended-Upgrade "0";` 与 `Update-Package-Lists "0";`
   - `systemctl disable --now unattended-upgrades`
2. **锁定内核**（用户要求"不一定真更新内核"，先挡住）
   - `apt-mark hold linux-dtb-current-rockchip-rk3588 linux-image-current-rockchip-rk3588 wiringpi`
   - 解除：`sudo apt-mark unhold linux-image-current-rockchip-rk3588 linux-dtb-current-rockchip-rk3588`
3. **安装的工具**：`htop tmux jq avahi-utils picocom rsync git net-tools lsof build-essential`
   （`picocom` 是为后面接 RTK 串口准备的）
4. **avahi**：`apt install avahi-daemon libnss-mdns`，`systemctl enable --now avahi-daemon`

---

## 7. 未决事项 / 待办

- [ ] **systemd 化**：把仿真 + 运行图做成 `nodeflow-sim.service` / `nodeflow-runtime.service`，开机自启、崩溃重启。仓库有 `scripts/install_edge_service.sh`，但**它是旧路径**（`python3 -m runtime.main`、`runtime.task.agent_main`），当前代码是 `edge.runtime.main`，直接用会起不来，需要改 `ExecStart`。
- [ ] **opencode 配置模型 key**：`opencode` 已装但没有任何 provider 配置，需要 key 后写 `~/.config/opencode/`（或让用户交互式登录）。
- [ ] **NVMe 固态**：用户计划拆掉/另作他用。若要用：需在一台 Linux 上 `growpart /dev/nvme0n1 2` + `resize2fs`，且**因为板上无 SPI Flash，必须靠 TF 卡里的 u-boot 引导**（见 §9）。
- [ ] **WiFi 重启验证**：热点已关，尚未验证"重启后自动连上热点"这条路径。下次开热点时重启一次确认。
- [ ] **RTK**：用户会提供 UM982 等模块和说明书；串口权限（`dialout` 组）、波特率、双天线主从约定见 `docs/UM982_HEADING_AND_TRACKING.md`。

---

## 8. 排障速查

| 现象 | 检查 |
|---|---|
| 运行图起不来，`Node 'trajectory_viz' failed at startup` | 装 `edge/nodes/observability/trajectory_viz/requirements.txt` |
| `ZMQError: Address already in use` | `sudo ss -tlnp \| grep <port>`；5555 归属 adbd，本项目应使用 5655 |
| 浏览器打不开 8080 | 只在**运行图**起来后才有 8080（单独跑 `simulation/server.py` 只有 5655） |
| WiFi 连不上 | `nmcli device wifi list`；`journalctl -u NetworkManager -n 50`；确认密码是 8 位 |
| 找不到板子 | `avahi-resolve -n orangepi5pro.local`、`ip -4 addr`、手机热点设备列表 |
| pip 报 403 | 清华源不可用，换阿里云 `-i https://mirrors.aliyun.com/pypi/simple/` |
| apt 卡在 nodesource | 已移除 nodesource 源；Node 用 npmmirror 二进制 |

---

## 9. 关于"从 NVMe 启动"（背景知识，别再走弯路）

RK3588 引导 ROM 的顺序是 **SPI Flash → eMMC → TF 卡**，**NVMe 不在其中**。
5 Pro 出厂无 SPI Flash，因此**纯 NVMe 启动做不到**（除非自己焊 SPI 芯片）。
当前有效做法：TF 卡里放系统（现状），或按官方手册 §2.6 把 `rkspi_loader.img` 写到 TF 卡让 u-boot 只做引导、
根文件系统放 NVMe（`dd if=rkspi_loader.img of=$(findmnt -n -o SOURCE / | sed 's/.$//')`，会毁掉 TF 卡上的系统）。

u-boot 里的实际启动顺序（从镜像提取）：
`boot_targets=mmc0 mmc1 nvme scsi mtd2 mtd1 mtd0 usb0 pxe dhcp` —— NVMe 排在 SD 卡之后。

---

## 10. 今晚踩过的坑（给后来者省时间）

1. **macOS 26 无法 `dd` 到 `/dev/rdisk*`**：TCC 保护，连 root 也是 `Operation not permitted`（errno=1）。要么给终端/App 完全磁盘访问权限，要么去 Windows/Linux 写盘（用户最后是在 Windows 上烧的）。
2. **`deb.nodesource.com` 国内不可达**：`curl | bash` 会静默卡十几分钟。
3. **清华 pypi 源 403**：换阿里云。
4. **`trajectory_viz` 的 flask 依赖不在主 requirements 里**：README 提了，容易漏。
5. **`adbd` 占 5555**：见 §5。
6. **SSH 启动后台进程要 `setsid` + 重定向**：否则占 pty，会话不退出。
