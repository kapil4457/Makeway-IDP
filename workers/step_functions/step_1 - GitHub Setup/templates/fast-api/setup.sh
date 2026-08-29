#!/usr/bin/env bash
#
# Golden-path setup for the __SERVICE_NAME__ FastAPI service (Makeway).
#
set -euo pipefail

SERVICE_NAME="${1:-$(basename "$PWD")}"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[makeway][fast-api] setting up ${SERVICE_NAME} in ${PROJECT_DIR}"

cd "${PROJECT_DIR}"

python3 -m venv .venv
# shellcheck disable=SC1091
. .venv/bin/activate

pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
python -m compileall -q .

echo "[makeway][fast-api] scaffold ready. Start with: SERVICE_NAME=${SERVICE_NAME} uvicorn main:app --reload"