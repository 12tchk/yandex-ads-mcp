#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${YD_MCP_ENV_FILE:-/etc/yandex-ads-mcp.env}"
PYTHON_BIN="${YD_MCP_PYTHON:-${REPO_DIR}/venv/bin/python}"

if [[ ! -r "${ENV_FILE}" ]]; then
  printf 'Yandex Ads MCP env file is not readable: %s\n' "${ENV_FILE}" >&2
  exit 1
fi

if [[ ! -x "${PYTHON_BIN}" ]]; then
  printf 'Yandex Ads MCP Python is not executable: %s\n' "${PYTHON_BIN}" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

# These values are enforced here and validated again inside server.py.
export YD_READONLY=true
export YD_WRITE_ARMED=false
export YD_CONFIRM=true
export YD_REQUIRE_LOGIN_ALLOWLIST=true
export YD_ALLOW_ALL_TOOLS=false
export YD_LOG_BODIES=false

exec "${PYTHON_BIN}" "${REPO_DIR}/server.py"
