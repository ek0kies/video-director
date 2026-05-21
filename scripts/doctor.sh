#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${VIDEO_DIRECTOR_VENV:-${SKILL_ROOT}/.venv}"
CONFIG_PATH="${1:-${SKILL_ROOT}/runtime/templates/video.template.json}"

FAIL_COUNT=0

pass() {
  printf 'PASS %s\n' "$*"
}

fail() {
  FAIL_COUNT=$((FAIL_COUNT + 1))
  printf 'FAIL %s\n' "$*"
}

info() {
  printf 'INFO %s\n' "$*"
}

python_exec() {
  local candidate="$1"
  shift
  if [[ "${candidate}" == *" "* ]]; then
    # Controlled candidates such as "py -3"; do not pass user text here.
    local parts=()
    read -r -a parts <<<"${candidate}"
    "${parts[@]}" "$@"
  else
    "${candidate}" "$@"
  fi
}

python_is_compatible() {
  local candidate="$1"
  [[ -n "${candidate}" ]] || return 1
  [[ -x "${candidate}" ]] || command -v "${candidate%% *}" >/dev/null 2>&1 || return 1
  python_exec "${candidate}" - >/dev/null 2>&1 <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
}

python_version() {
  python_exec "$1" - <<'PY'
import sys
print(f"{sys.executable} {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
PY
}

resolve_python() {
  local candidates=()
  [[ -n "${VIDEO_DIRECTOR_PYTHON:-}" ]] && candidates+=("${VIDEO_DIRECTOR_PYTHON}")
  candidates+=(
    "${VENV_DIR}/bin/python"
    "${VENV_DIR}/Scripts/python.exe"
    python3
    python
    "py -3"
    python3.13
    python3.12
    python3.11
    python3.10
    /opt/homebrew/bin/python3.13
    /opt/homebrew/bin/python3.12
    /opt/homebrew/bin/python3.11
    /opt/homebrew/bin/python3.10
    /usr/local/bin/python3.13
    /usr/local/bin/python3.12
    /usr/local/bin/python3.11
    /usr/local/bin/python3.10
  )

  local candidate
  for candidate in "${candidates[@]}"; do
    if python_is_compatible "${candidate}"; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done
  return 1
}

os_repair_commands() {
  cat <<'EOF'
FIX ffmpeg:
  macOS: brew install ffmpeg
  Debian/Ubuntu: sudo apt-get update && sudo apt-get install -y ffmpeg
  Fedora/RHEL: sudo dnf install -y ffmpeg
  Arch: sudo pacman -S --needed ffmpeg
  Alpine: sudo apk add ffmpeg
  Windows: winget install Gyan.FFmpeg
EOF
}

PYTHON_CMD=""
if PYTHON_CMD="$(resolve_python)"; then
  pass "python: $(python_version "${PYTHON_CMD}")"
else
  fail "python: Python 3.10+ not found"
  cat <<'EOF'
FIX python:
  macOS: brew install python@3.11
  Debian/Ubuntu: sudo apt-get update && sudo apt-get install -y python3 python3-venv python3-pip
  Windows: winget install Python.Python.3.11
EOF
fi

if [[ -n "${PYTHON_CMD}" ]]; then
  if python_exec "${PYTHON_CMD}" - >/dev/null 2>&1 <<'PY'
import importlib
importlib.import_module("PIL")
PY
  then
    pass "python dependency: PIL importable"
  else
    fail "python dependency: PIL missing"
    printf 'FIX python dependency:\n  bash %q\n' "${SCRIPT_DIR}/install.sh"
  fi
fi

if command -v ffmpeg >/dev/null 2>&1; then
  pass "ffmpeg: $(command -v ffmpeg)"
else
  fail "ffmpeg: not found on PATH"
  os_repair_commands
fi

if command -v ffprobe >/dev/null 2>&1; then
  pass "ffprobe: $(command -v ffprobe)"
else
  fail "ffprobe: not found on PATH"
  os_repair_commands
fi

if [[ -w "${SKILL_ROOT}" ]]; then
  pass "skill directory writable: ${SKILL_ROOT}"
else
  fail "skill directory not writable: ${SKILL_ROOT}"
  printf 'FIX permissions:\n  chmod u+w %q\n' "${SKILL_ROOT}"
fi

if [[ -n "${PYTHON_CMD}" && -f "${CONFIG_PATH}" ]]; then
  export VIDEO_DIRECTOR_PYTHON="${PYTHON_CMD}"
  if output="$(bash "${SCRIPT_DIR}/video-director.sh" doctor "${CONFIG_PATH}" 2>&1)"; then
    pass "runtime doctor: ${CONFIG_PATH}"
    info "${output}"
  else
    fail "runtime doctor failed: ${CONFIG_PATH}"
    info "${output}"
  fi
elif [[ ! -f "${CONFIG_PATH}" ]]; then
  fail "config not found: ${CONFIG_PATH}"
  printf 'FIX config:\n  bash %q config local --output-mode video --output video-director.video.local.json --job-id demo --narration-text smoke\n' "${SCRIPT_DIR}/run.sh"
fi

if [[ "${FAIL_COUNT}" -eq 0 ]]; then
  printf 'STATUS PASS video-director environment is ready\n'
  exit 0
fi

printf 'STATUS FAIL video-director environment has %s failing check(s)\n' "${FAIL_COUNT}"
exit 1
