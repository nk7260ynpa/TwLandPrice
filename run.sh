#!/usr/bin/env bash
#
# 啟動 Docker container 執行實價登錄擷取主程式，並掛載 logs/。
#
# 用法：
#   ./run.sh                      # 下載並解析最新一期
#   ./run.sh --season 113S1       # 指定民國 113 年第 1 季
#   ./run.sh analyze --report district   # 統計分析（需先以 --db 入庫）
#   ./run.sh visualize            # 產生 HTML 視覺化報告（output/）
#   ./run.sh map                  # 產生互動式地價熱力圖（離線單檔，output/）
#   ./run.sh pytest               # 執行單元測試

set -euo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly COMPOSE_FILE="${SCRIPT_DIR}/docker/docker-compose.yaml"

mkdir -p "${SCRIPT_DIR}/logs"

if [[ "${1:-}" == "pytest" ]]; then
  exec docker compose -f "${COMPOSE_FILE}" run --rm app pytest
fi

if [[ "${1:-}" == "analyze" ]]; then
  shift
  exec docker compose -f "${COMPOSE_FILE}" run --rm app \
    python -m twlandprice.analyzer "$@"
fi

if [[ "${1:-}" == "visualize" ]]; then
  shift
  exec docker compose -f "${COMPOSE_FILE}" run --rm app \
    python -m twlandprice.visualizer "$@"
fi

if [[ "${1:-}" == "map" ]]; then
  shift
  exec docker compose -f "${COMPOSE_FILE}" run --rm app \
    python -m twlandprice.mapviewer "$@"
fi

exec docker compose -f "${COMPOSE_FILE}" run --rm app \
  python -m twlandprice.fetcher "$@"
