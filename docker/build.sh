#!/usr/bin/env bash
#
# 建立 TwLandPrice Docker image。
#
# 用法：
#   docker/build.sh

set -euo pipefail

readonly IMAGE_NAME="twlandprice:latest"
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

docker build \
  -t "${IMAGE_NAME}" \
  -f "${SCRIPT_DIR}/Dockerfile" \
  "${PROJECT_ROOT}"

echo "已建立 image：${IMAGE_NAME}"
