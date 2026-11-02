#!/usr/bin/env bash
# 把 NodeFlow 的仿真 ZMQ 端口从 5555 改成 5655。
#
# 为什么：Orange Pi 5 Pro 的官方镜像自带 adbd（usbdevice 拉起）监听 0.0.0.0:5555，
# 与仿真默认端口冲突，会导致 trajectory_viz 启动即退出。
# 我们在边缘机上选择改自己的端口，而不是动 adbd。
#
# 幂等：重复执行无副作用。重新 rsync 仓库后需要再跑一次。
#
# 用法： bash scripts/apply_pi5pro_ports.sh [仓库根目录]
set -euo pipefail

ROOT="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
OLD=5555
NEW=5655

cd "$ROOT"

echo "仓库: $ROOT"
echo "端口: $OLD -> $NEW"

changed=0
apply() {
  local file="$1"
  if [ -f "$file" ] && grep -q "$OLD" "$file"; then
    sed -i "s/$OLD/$NEW/g" "$file"
    echo "  改写 $file"
    changed=$((changed + 1))
  fi
}

# 运行图里的仿真连接端口
for f in configs/graphs/*.yaml examples/*.yaml; do apply "$f"; done

# 仿真服务默认端口
apply simulation/config.yaml
apply simulation/server.py

# CLI 与预检工具的默认端口
apply tools/cli/core/cli.py
apply tools/cli/cli/core/cli.py
apply tools/preflight_runtime.py

if [ "$changed" -eq 0 ]; then
  echo "已经是 $NEW，无需改动。"
else
  echo "完成，共改写 $changed 个文件。"
fi

echo
echo "自检："
echo "  YAML   simulator_port: $(grep -h 'simulator_port' configs/graphs/*.yaml | sort -u | tr -d ' ' | tr '\n' ' ')"
echo "  服务端 zmq_port:      $(grep -h 'zmq_port' simulation/config.yaml | tr -d ' ')"
RESIDUAL="$(grep -rl "$OLD" --include='*.py' --include='*.yaml' . 2>/dev/null | grep -vE 'node_modules|\.venv' | tr '\n' ' ')"
echo "  残留 $OLD（项目文件；node.yaml 里的默认值不影响，图配置会覆盖）: ${RESIDUAL:-无}"
