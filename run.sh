#!/usr/bin/env bash
#
# 啟動 Docker container 執行實價登錄擷取主程式，並掛載 logs/。
#
# 用法：
#   ./run.sh                      # 下載並解析最新一期
#   ./run.sh --season 113S1       # 指定民國 113 年第 1 季
#   ./run.sh pytest               # 執行單元測試

set -euo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly COMPOSE_FILE="${SCRIPT_DIR}/docker/docker-compose.yaml"

mkdir -p "${SCRIPT_DIR}/logs"

if [[ "${1:-}" == "pytest" ]]; then
  exec docker compose -f "${COMPOSE_FILE}" run --rm app pytest
fi

exec docker compose -f "${COMPOSE_FILE}" run --rm app \
  python -m twlandprice.fetcher "$@"
