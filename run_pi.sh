#!/usr/bin/env bash
# Pi 本機 all-in-one 模式的一鍵啟動：同時跑
#   1) 網頁排版介面 + API（server/app.py，不開驗證）
#   2) 排程器（server/scheduler.py，直接呼叫合成→推到螢幕，不經網路）
#   3) UPS 電量看門狗（device_agent/ups/ups_daemon.py）
#
# 正式長期運行建議改用 systemd/ 底下的三個 unit 檔分開管理（各自 restart 互不影響），
# 這支腳本主要給快速開發/測試用。
set -euo pipefail

cd "$(dirname "$0")"

DEVICE_ID="${1:-${EPAGERPI_DEVICE_ID:-phat-01}}"

export EPAGERPI_AUTH_ENABLED=0
export PYTHONPATH="$(pwd)"

echo "[run_pi] device=${DEVICE_ID}  (Ctrl-C 結束全部)"

python3 -m server.app &
APP_PID=$!

python3 -m server.scheduler --device "${DEVICE_ID}" &
SCHED_PID=$!

UPS_PID=""
if [ -f device_agent/config.yaml ]; then
  python3 -m device_agent.ups.ups_daemon &
  UPS_PID=$!
else
  echo "[run_pi] 沒找到 device_agent/config.yaml，跳過 UPS 監控"
  echo "[run_pi]（複製 device_agent/config.example.yaml 成 config.yaml 即可啟用）"
fi

cleanup() {
  echo "[run_pi] 關閉中..."
  kill "${APP_PID}" "${SCHED_PID}" ${UPS_PID} 2>/dev/null || true
}
trap cleanup EXIT INT TERM

wait
