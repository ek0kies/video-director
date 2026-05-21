#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SMOKE_ROOT="${VIDEO_DIRECTOR_SMOKE_ROOT:-${TMPDIR:-/tmp}/video-director-smoke-$$}"
DEMO_ROOT="${SMOKE_ROOT}/demo/contest"
CONFIG_PATH="${DEMO_ROOT}/video-director.contest-demo.local.json"
SUMMARY_PATH="${DEMO_ROOT}/output/contest-demo/latest_run.json"

cleanup() {
  if [[ "${VIDEO_DIRECTOR_KEEP_SMOKE:-0}" != "1" ]]; then
    rm -rf "${SMOKE_ROOT}"
  fi
}
trap cleanup EXIT

echo "INFO smoke root: ${SMOKE_ROOT}"

bash "${SKILL_ROOT}/scripts/install.sh" --no-system-install
bash "${SKILL_ROOT}/scripts/doctor.sh" "${SKILL_ROOT}/runtime/templates/video.template.json"

PENDING_CONFIG="${SMOKE_ROOT}/operation-confirmation.pending.local.json"
bash "${SKILL_ROOT}/scripts/run.sh" config local \
  --output-mode video \
  --output "${PENDING_CONFIG}" \
  --job-id operation-confirmation-pending \
  --narration-text smoke
if bash "${SKILL_ROOT}/scripts/run.sh" run "${PENDING_CONFIG}" --dry-run; then
  echo "STATUS FAIL pending operation confirmation should block run" >&2
  exit 1
fi
bash "${SKILL_ROOT}/scripts/run.sh" confirm-operation "${PENDING_CONFIG}" --note smoke-confirmed

VIDEO_DIRECTOR_DEMO_ROOT="${DEMO_ROOT}" bash "${SKILL_ROOT}/scripts/run.sh" demo
bash "${SKILL_ROOT}/scripts/doctor.sh" "${CONFIG_PATH}"
bash "${SKILL_ROOT}/scripts/run.sh" run "${CONFIG_PATH}" --dry-run
bash "${SKILL_ROOT}/scripts/run.sh" run "${CONFIG_PATH}"
bash "${SKILL_ROOT}/scripts/run.sh" summarize "${SUMMARY_PATH}"

echo "STATUS PASS video-director smoke completed"
