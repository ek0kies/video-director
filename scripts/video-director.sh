#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

video_director_python_is_compatible() {
  local candidate="$1"
  [[ -n "${candidate}" ]] || return 1
  [[ -x "${candidate}" ]] || command -v "${candidate}" >/dev/null 2>&1 || return 1
  "${candidate}" - >/dev/null 2>&1 <<'PY'
import sys

raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
}

video_director_resolve_python() {
  local candidates=()

  if [[ -n "${VIDEO_DIRECTOR_PYTHON:-}" ]]; then
    if video_director_python_is_compatible "${VIDEO_DIRECTOR_PYTHON}"; then
      command -v "${VIDEO_DIRECTOR_PYTHON}" 2>/dev/null || printf '%s\n' "${VIDEO_DIRECTOR_PYTHON}"
      return 0
    fi
    {
      echo "error: VIDEO_DIRECTOR_PYTHON is set but is not Python 3.11+: ${VIDEO_DIRECTOR_PYTHON}"
      echo "Unset VIDEO_DIRECTOR_PYTHON or point it to a compatible interpreter."
    } >&2
    return 1
  fi

  candidates+=(
    "python3"
    "python"
    "python3.13"
    "python3.12"
    "python3.11"
    "/opt/homebrew/opt/python@3.13/libexec/bin/python"
    "/opt/homebrew/opt/python@3.12/libexec/bin/python"
    "/opt/homebrew/opt/python@3.11/libexec/bin/python"
    "/opt/homebrew/bin/python3.13"
    "/opt/homebrew/bin/python3.12"
    "/opt/homebrew/bin/python3.11"
  )

  local candidate
  for candidate in "${candidates[@]}"; do
    if video_director_python_is_compatible "${candidate}"; then
      command -v "${candidate}" 2>/dev/null || printf '%s\n' "${candidate}"
      return 0
    fi
  done

  {
    echo "error: Python 3.11 or newer is required for Video Director."
    echo "Checked 'python3', 'python', and versioned Python commands."
    echo "If 'python3' or 'python' is compatible in your shell, set VIDEO_DIRECTOR_PYTHON to that command and retry."
    echo "Do not install Miniforge, Conda, Anaconda, pyenv, or another Python distribution automatically."
    echo "Ask the user to choose a lightweight Python installation method if no compatible interpreter exists."
    echo "Checked: ${candidates[*]}"
  } >&2
  return 1
}

PYTHON_BIN="$(video_director_resolve_python)"
exec "${PYTHON_BIN}" "${SCRIPT_DIR}/video_director.py" "$@"
