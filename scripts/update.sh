#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REMOTE_NAME="${VIDEO_DIRECTOR_REMOTE:-origin}"
REMOTE_REF="${VIDEO_DIRECTOR_REMOTE_REF:-}"
RUN_VERIFY="${VIDEO_DIRECTOR_SKIP_VERIFY:-0}"

usage() {
  cat <<'EOF'
usage: scripts/update.sh [--skip-verify] [--remote NAME] [--ref REF]

Update an existing Video Director Git checkout and verify the installed Skill.

Options:
  --skip-verify   update only; do not run install, doctor, or smoke checks
  --remote NAME   Git remote to fetch from, default: origin
  --ref REF       optional remote ref to fast-forward to, for example origin/main
  -h, --help      show this help

This script never overwrites local modifications. If the Skill is not a Git
checkout, the Agent should back it up, clone the latest repository, and repoint
the Agent skill registration to the whole repository.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-verify)
      RUN_VERIFY="1"
      shift
      ;;
    --remote)
      if [[ $# -lt 2 ]]; then
        echo "FAIL update: --remote requires a value" >&2
        exit 2
      fi
      REMOTE_NAME="$2"
      shift 2
      ;;
    --ref)
      if [[ $# -lt 2 ]]; then
        echo "FAIL update: --ref requires a value" >&2
        exit 2
      fi
      REMOTE_REF="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "FAIL update: unknown option $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

info() {
  printf 'INFO update: %s\n' "$*"
}

pass() {
  printf 'PASS update: %s\n' "$*"
}

fail() {
  printf 'FAIL update: %s\n' "$*" >&2
}

if ! command -v git >/dev/null 2>&1; then
  fail "git is required to update a Git checkout"
  exit 1
fi

if ! GIT_ROOT="$(git -C "${SKILL_ROOT}" rev-parse --show-toplevel 2>/dev/null)"; then
  fail "registered Skill is not a Git checkout: ${SKILL_ROOT}"
  cat >&2 <<EOF
ACTION_REQUIRED non_git_copy
Backup this directory, clone https://github.com/ek0kies/video-director to a stable
local path, and repoint the current Agent's video-director Skill registration to
the whole cloned repository.
EOF
  exit 3
fi

cd "${GIT_ROOT}"
info "install path: ${GIT_ROOT}"
info "registered skill path: ${SKILL_ROOT}"

if [[ -n "$(git status --porcelain)" ]]; then
  fail "local changes are present; refusing to update"
  git status --short >&2
  cat >&2 <<'EOF'
ACTION_REQUIRED dirty_tree
Ask whether to back up, commit, or stop. Do not overwrite these changes.
EOF
  exit 4
fi

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [[ "${CURRENT_BRANCH}" == "HEAD" && -z "${REMOTE_REF}" ]]; then
  fail "checkout is detached; pass --ref <remote/ref> or update manually"
  exit 5
fi

info "fetching ${REMOTE_NAME}"
git fetch --prune "${REMOTE_NAME}"

if [[ -n "${REMOTE_REF}" ]]; then
  info "fast-forwarding to ${REMOTE_REF}"
  git merge --ff-only "${REMOTE_REF}"
else
  UPSTREAM="$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || true)"
  if [[ -n "${UPSTREAM}" ]]; then
    info "fast-forwarding from ${UPSTREAM}"
    git merge --ff-only "${UPSTREAM}"
  else
    info "fast-forwarding from ${REMOTE_NAME}/${CURRENT_BRANCH}"
    git merge --ff-only "${REMOTE_NAME}/${CURRENT_BRANCH}"
  fi
fi

pass "repository updated"

if [[ "${RUN_VERIFY}" == "1" ]]; then
  pass "verification skipped by request"
  exit 0
fi

bash "${SCRIPT_DIR}/install.sh" --skip-system-install
bash "${SCRIPT_DIR}/doctor.sh" "${GIT_ROOT}/runtime/templates/video.template.json"
bash "${GIT_ROOT}/tests/smoke.sh"

pass "Video Director update verified"
