#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_NAME="${CONDA_ENV_NAME:-game_demo}"
PYTHON_VERSION="${PYTHON_VERSION:-3.11}"
PORT="${PORT:-8000}"
HOST="${HOST:-127.0.0.1}"

cd "${ROOT_DIR}"

load_conda() {
  if command -v conda >/dev/null 2>&1; then
    return
  fi

  local candidates=(
    "${HOME}/miniconda3/etc/profile.d/conda.sh"
    "${HOME}/anaconda3/etc/profile.d/conda.sh"
    "/opt/homebrew/Caskroom/miniconda/base/etc/profile.d/conda.sh"
    "/opt/homebrew/anaconda3/etc/profile.d/conda.sh"
  )

  for conda_sh in "${candidates[@]}"; do
    if [[ -f "${conda_sh}" ]]; then
      # shellcheck source=/dev/null
      source "${conda_sh}"
      return
    fi
  done

  echo "[run.sh] Conda was not found."
  echo "[run.sh] Install Miniconda/Anaconda, or make sure 'conda' is available in PATH."
  exit 1
}

env_exists() {
  conda env list | awk '{print $1}' | grep -qx "${ENV_NAME}"
}

load_conda

if ! env_exists; then
  echo "[run.sh] Creating conda environment '${ENV_NAME}' with Python ${PYTHON_VERSION}..."
  conda create -y -n "${ENV_NAME}" "python=${PYTHON_VERSION}"
fi

if [[ "${CONDA_DEFAULT_ENV:-}" == "${ENV_NAME}" ]]; then
  PYTHON_CMD=(python)
  PIP_CMD=(python -m pip)
  UVICORN_CMD=(uvicorn)
  CONDA_PREFIX_FOR_ENV="${CONDA_PREFIX}"
else
  PYTHON_CMD=(conda run -n "${ENV_NAME}" python)
  PIP_CMD=(conda run -n "${ENV_NAME}" python -m pip)
  UVICORN_CMD=(conda run --no-capture-output -n "${ENV_NAME}" uvicorn)
  CONDA_PREFIX_FOR_ENV="$("${PYTHON_CMD[@]}" -c 'import os; print(os.environ["CONDA_PREFIX"])')"
fi

DEPS_MARKER="${CONDA_PREFIX_FOR_ENV}/.game_demo_deps_installed"

if [[ ! -f "${DEPS_MARKER}" || requirements.txt -nt "${DEPS_MARKER}" ]]; then
  echo "[run.sh] Installing/updating Python dependencies..."
  "${PIP_CMD[@]}" install --upgrade pip
  "${PIP_CMD[@]}" install -r requirements.txt
  touch "${DEPS_MARKER}"
fi

if [[ ! -f "llm.env" && ! -f ".env" ]]; then
  echo "[run.sh] Warning: no llm.env or .env file found. AI models will be unavailable until API keys are configured."
  echo "[run.sh] You can copy .env.example to llm.env and fill in your keys."
fi

echo "[run.sh] Starting YXP Dou Dizhu on http://${HOST}:${PORT}/"
echo "[run.sh] Press Ctrl+C to stop."
exec "${UVICORN_CMD[@]}" server.main:app --reload --host "${HOST}" --port "${PORT}"
