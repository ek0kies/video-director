"""Build review artifacts for viewer-facing Video Director copy."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


COPY_SOURCE_USER = "user_provided"
COPY_SOURCE_GENERATED = "generated"

_DURATION_RE = re.compile(r"(?<![A-Za-z0-9_])\d+\s*(?:s|min|minutes?|seconds?)|\d+\s*(?:秒|分钟)", re.IGNORECASE)
_PATH_RE = re.compile(r"(/Users/|/Volumes/|[A-Za-z]:\\|\\\\|(?:\.mov|\.mp4|\.json|\.local\.json)\b)", re.IGNORECASE)
_INSTRUCTION_RE = re.compile(
    r"(剪出一条|剪一条|生成一条|输出为|素材目录|使用\s*/|director_brief|narration_text|render|final_render)",
    re.IGNORECASE,
)
_KNOWN_BAD_RE = re.compile(r"(蒸到定型|豆腐.*蒸.*定型)")


def _split_sentences(text: str) -> List[str]:
    parts = re.split(r"[。！？!?；;\n]+", text)
    return [part.strip() for part in parts if part.strip()]


def _flag(code: str, severity: str, message: str, matches: List[str]) -> Dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "message": message,
        "matches": matches,
    }


def _matches(pattern: re.Pattern[str], text: str) -> List[str]:
    return sorted({match.group(0).strip() for match in pattern.finditer(text) if match.group(0).strip()})


def _review_flags(*, text: str, source: str) -> List[Dict[str, Any]]:
    flags: List[Dict[str, Any]] = []
    duration_matches = _matches(_DURATION_RE, text)
    if duration_matches and source == COPY_SOURCE_GENERATED:
        flags.append(
            _flag(
                "duration_in_generated_copy",
                "warning",
                "Generated viewer-facing copy contains a duration. Confirm it is a title choice, not a target-length instruction.",
                duration_matches,
            )
        )

    path_matches = _matches(_PATH_RE, text)
    if path_matches:
        flags.append(
            _flag(
                "path_or_file_in_copy",
                "error",
                "Viewer-facing copy appears to contain a local path, file extension, or config name.",
                path_matches,
            )
        )

    instruction_matches = _matches(_INSTRUCTION_RE, text)
    if instruction_matches:
        flags.append(
            _flag(
                "instruction_text_in_copy",
                "warning",
                "Viewer-facing copy appears to contain editing instructions or internal field names.",
                instruction_matches,
            )
        )

    known_bad_matches = _matches(_KNOWN_BAD_RE, text)
    if known_bad_matches:
        flags.append(
            _flag(
                "known_bad_cooking_claim",
                "warning",
                "Copy contains a known bad cooking claim observed in testing.",
                known_bad_matches,
            )
        )

    return flags


def build_copy_review_report(config: Dict[str, Any]) -> Dict[str, Any]:
    """Return a human-review report without requiring the copy to be approved."""
    inputs = config.get("inputs", {}) if isinstance(config.get("inputs"), dict) else {}
    review = inputs.get("copy_review", {}) if isinstance(inputs.get("copy_review"), dict) else {}
    text = str(inputs.get("narration_text") or inputs.get("script_text", "")).strip()
    source = str(inputs.get("narration_source") or COPY_SOURCE_USER).strip().lower()
    required = bool(review.get("required", source == COPY_SOURCE_GENERATED))
    status = str(review.get("status") or ("pending" if required else "approved")).strip().lower()
    cues = [{"index": index, "text": cue} for index, cue in enumerate(_split_sentences(text), start=1)]
    flags = _review_flags(text=text, source=source)
    blocking_flags = [flag for flag in flags if flag["severity"] == "error"]
    needs_review = required and status != "approved"
    report_status = "blocked" if blocking_flags else ("needs_review" if needs_review or flags else "approved")
    if blocking_flags:
        recommended_next_step = "Revise viewer-facing copy before approval; blocking issues are present."
    elif flags:
        recommended_next_step = "Review flagged copy carefully before rendering, or revise the generated narration."
    elif needs_review:
        recommended_next_step = "Approve the generated copy and rerun config with --copy-reviewed, or revise the generated narration."
    else:
        recommended_next_step = "Copy can proceed to dry-run or render."

    return {
        "status": report_status,
        "job_id": str(config.get("job_id") or inputs.get("job_id") or ""),
        "source": source,
        "copy_review": {
            "required": required,
            "status": status,
            "scope": str(review.get("scope") or "viewer_visible_narration"),
        },
        "viewer_copy": {
            "narration_text": text,
            "subtitle_cues": cues,
        },
        "flags": flags,
        "reviewer_checklist": [
            "Confirm target duration, paths, and editing instructions are not present in subtitles.",
            "Confirm every claimed action is visible in the source material or explicitly provided by the user.",
            "Confirm generated food, product, or tutorial claims are factually safe before adding --copy-reviewed.",
        ],
        "recommended_next_step": recommended_next_step,
    }


def write_copy_review_report(report: Dict[str, Any], output_path: Optional[Path]) -> None:
    if output_path is None:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
