#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${VIDEO_DIRECTOR_VENV:-${SKILL_ROOT}/.venv}"

if [[ "${1:-}" == "update" ]]; then
  shift
  exec bash "${SCRIPT_DIR}/update.sh" "$@"
fi

python_is_compatible() {
  local candidate="$1"
  [[ -n "${candidate}" ]] || return 1
  [[ -x "${candidate}" ]] || command -v "${candidate}" >/dev/null 2>&1 || return 1
  "${candidate}" - >/dev/null 2>&1 <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
}

venv_python() {
  if python_is_compatible "${VENV_DIR}/bin/python"; then
    printf '%s\n' "${VENV_DIR}/bin/python"
    return 0
  fi
  if python_is_compatible "${VENV_DIR}/Scripts/python.exe"; then
    printf '%s\n' "${VENV_DIR}/Scripts/python.exe"
    return 0
  fi
  return 1
}

if [[ -z "${VIDEO_DIRECTOR_PYTHON:-}" ]]; then
  if resolved_python="$(venv_python)"; then
    export VIDEO_DIRECTOR_PYTHON="${resolved_python}"
  elif [[ "${VIDEO_DIRECTOR_NO_AUTO_INSTALL:-0}" != "1" ]]; then
    bash "${SCRIPT_DIR}/install.sh" --skip-system-install
    resolved_python="$(venv_python)"
    export VIDEO_DIRECTOR_PYTHON="${resolved_python}"
  fi
fi

exec bash "${SCRIPT_DIR}/video-director.sh" "$@"
