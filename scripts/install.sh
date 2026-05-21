#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${VIDEO_DIRECTOR_VENV:-${SKILL_ROOT}/.venv}"
REQUIREMENTS_FILE="${SKILL_ROOT}/requirements.txt"
PIP_CACHE_DIR="${VIDEO_DIRECTOR_PIP_CACHE_DIR:-${SKILL_ROOT}/.cache/pip}"
ALLOW_SYSTEM_INSTALL=1
SKIP_DOCTOR=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-system-install|--skip-system-install)
      ALLOW_SYSTEM_INSTALL=0
      ;;
    --skip-doctor)
      SKIP_DOCTOR=1
      ;;
    --venv)
      shift
      if [[ $# -eq 0 ]]; then
        echo "FAIL install: --venv requires a path" >&2
        exit 2
      fi
      VENV_DIR="$1"
      ;;
    -h|--help)
      cat <<'EOF'
usage: scripts/install.sh [--no-system-install] [--skip-doctor] [--venv PATH]

Prepare Video Director as an Agent-native Skill:
  - detect Python 3.10+
  - create/reuse an isolated virtual environment
  - install requirements.txt
  - check local write permissions
  - check or attempt to install ffmpeg/ffprobe
  - run doctor.sh unless --skip-doctor is set
EOF
      exit 0
      ;;
    *)
      echo "FAIL install: unknown option $1" >&2
      exit 2
      ;;
  esac
  shift
done

pass() {
  printf 'PASS %s\n' "$*"
}

fail() {
  printf 'FAIL %s\n' "$*" >&2
}

info() {
  printf 'INFO %s\n' "$*"
}

python_exec() {
  local candidate="$1"
  shift
  if [[ "${candidate}" == *" "* ]]; then
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

venv_python_path() {
  if [[ -x "${VENV_DIR}/bin/python" ]]; then
    printf '%s\n' "${VENV_DIR}/bin/python"
    return 0
  fi
  if [[ -x "${VENV_DIR}/Scripts/python.exe" ]]; then
    printf '%s\n' "${VENV_DIR}/Scripts/python.exe"
    return 0
  fi
  return 1
}

print_python_fix() {
  cat <<'EOF'
FIX python:
  macOS: brew install python@3.11
  Debian/Ubuntu: sudo apt-get update && sudo apt-get install -y python3 python3-venv python3-pip
  Windows: winget install Python.Python.3.11
EOF
}

print_ffmpeg_fix() {
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

try_install_ffmpeg() {
  if [[ "${ALLOW_SYSTEM_INSTALL}" -ne 1 ]]; then
    return 1
  fi
  if command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1; then
    return 0
  fi

  if command -v brew >/dev/null 2>&1; then
    info "attempting ffmpeg install with Homebrew"
    brew install ffmpeg
    return $?
  fi
  if command -v apt-get >/dev/null 2>&1; then
    info "attempting ffmpeg install with apt-get"
    if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
      apt-get update && apt-get install -y ffmpeg
      return $?
    fi
    if command -v sudo >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1; then
      sudo apt-get update && sudo apt-get install -y ffmpeg
      return $?
    fi
    return 1
  fi
  if command -v dnf >/dev/null 2>&1; then
    info "attempting ffmpeg install with dnf"
    if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
      dnf install -y ffmpeg
      return $?
    fi
    if command -v sudo >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1; then
      sudo dnf install -y ffmpeg
      return $?
    fi
    return 1
  fi
  if command -v pacman >/dev/null 2>&1; then
    info "attempting ffmpeg install with pacman"
    if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
      pacman -S --needed --noconfirm ffmpeg
      return $?
    fi
    if command -v sudo >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1; then
      sudo pacman -S --needed --noconfirm ffmpeg
      return $?
    fi
    return 1
  fi
  if command -v apk >/dev/null 2>&1; then
    info "attempting ffmpeg install with apk"
    if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
      apk add ffmpeg
      return $?
    fi
    if command -v sudo >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1; then
      sudo apk add ffmpeg
      return $?
    fi
    return 1
  fi
  if command -v winget.exe >/dev/null 2>&1; then
    info "attempting ffmpeg install with winget"
    winget.exe install Gyan.FFmpeg
    return $?
  fi
  return 1
}

if [[ ! -f "${REQUIREMENTS_FILE}" ]]; then
  fail "requirements file not found: ${REQUIREMENTS_FILE}"
  exit 1
fi

if [[ ! -w "${SKILL_ROOT}" ]]; then
  fail "skill directory is not writable: ${SKILL_ROOT}"
  printf 'FIX permissions:\n  chmod u+w %q\n' "${SKILL_ROOT}"
  exit 1
fi
pass "skill directory writable: ${SKILL_ROOT}"

mkdir -p "${PIP_CACHE_DIR}"
export PIP_CACHE_DIR
pass "pip cache directory: ${PIP_CACHE_DIR}"

if ! PYTHON_CMD="$(resolve_python)"; then
  fail "Python 3.10+ not found"
  print_python_fix
  exit 1
fi
pass "python: $(python_version "${PYTHON_CMD}")"

if [[ ! -d "${VENV_DIR}" ]]; then
  info "creating virtual environment: ${VENV_DIR}"
  if ! python_exec "${PYTHON_CMD}" -m venv "${VENV_DIR}"; then
    fail "failed to create virtual environment"
    printf 'FIX venv:\n  %s -m ensurepip --upgrade\n  %s -m venv %q\n' "${PYTHON_CMD}" "${PYTHON_CMD}" "${VENV_DIR}"
    exit 1
  fi
else
  info "reusing virtual environment: ${VENV_DIR}"
fi

if ! VENV_PYTHON="$(venv_python_path)"; then
  fail "virtual environment python not found under ${VENV_DIR}"
  exit 1
fi
pass "venv python: ${VENV_PYTHON}"

if ! "${VENV_PYTHON}" -m pip --version >/dev/null 2>&1; then
  fail "pip is unavailable in virtual environment"
  printf 'FIX pip:\n  %q -m ensurepip --upgrade\n' "${VENV_PYTHON}"
  exit 1
fi
pass "pip available"

info "installing baseline Python requirements"
if ! "${VENV_PYTHON}" -m pip install -r "${REQUIREMENTS_FILE}"; then
  fail "pip install failed"
  printf 'FIX python dependency:\n  %q -m pip install -r %q\n' "${VENV_PYTHON}" "${REQUIREMENTS_FILE}"
  exit 1
fi
pass "requirements installed: ${REQUIREMENTS_FILE}"

if ! "${VENV_PYTHON}" - >/dev/null 2>&1 <<'PY'
import importlib
importlib.import_module("PIL")
PY
then
  fail "PIL import failed after install"
  printf 'FIX python dependency:\n  %q -m pip install -r %q\n' "${VENV_PYTHON}" "${REQUIREMENTS_FILE}"
  exit 1
fi
pass "python dependency importable: PIL"

if command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1; then
  pass "ffmpeg/ffprobe available"
elif try_install_ffmpeg && command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1; then
  pass "ffmpeg/ffprobe installed"
else
  fail "ffmpeg/ffprobe unavailable"
  print_ffmpeg_fix
  exit 1
fi

export VIDEO_DIRECTOR_PYTHON="${VENV_PYTHON}"
if [[ "${SKIP_DOCTOR}" -ne 1 ]]; then
  bash "${SCRIPT_DIR}/doctor.sh" "${SKILL_ROOT}/runtime/templates/video.template.json"
fi

pass "Video Director install complete"
